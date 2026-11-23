#include "engine/gpu/NfnextUnaryStateKernel.hpp"

#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace bng::engine::detail {
namespace {

static const char* kNfnextUnaryStateShader = R"METAL(
#include <metal_stdlib>
using namespace metal;

struct PCG32 {
    ulong state;
    ulong inc;
    void init(ulong initstate, ulong initseq) {
        state = 0ULL;
        inc = (initseq << 1ULL) | 1ULL;
        step();
        state += initstate;
        step();
    }
    void step() {
        state = state * 6364136223846793005ULL + inc;
    }
    uint next_u32() {
        ulong oldstate = state;
        step();
        ulong xorshifted = ((oldstate >> 18u) ^ oldstate) >> 27u;
        uint rot = (uint)(oldstate >> 59u);
        return ((uint)xorshifted >> rot) | ((uint)xorshifted << ((-rot) & 31u));
    }
    float next_float01() {
        uint v = next_u32();
        return ((float)(v >> 8) + 1.0f) / 16777218.0f;
    }
};

ulong splitmix64(ulong value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30ULL)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27ULL)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31ULL);
}

struct SimParams {
    uint numStates;
    uint numTransitions;
    uint numObservables;
    uint numOutputs;
    uint batchSize;
    uint numParticles;
    uint maxEvents;
    uint reserved;
    ulong baseSeed;
};

void scheduleForState(
    uint index,
    int state,
    float now,
    constant SimParams& params,
    constant uint* transitionOffsets,
    constant int* transitionDestinations,
    constant float* transitionRates,
    device float* nextTimes,
    device int* nextDestinations,
    device ulong* rngStates,
    device ulong* rngIncrements)
{
    PCG32 rng;
    rng.state = rngStates[index];
    rng.inc = rngIncrements[index];
    const uint begin = transitionOffsets[(uint)state];
    const uint end = transitionOffsets[(uint)state + 1];
    float total = 0.0f;
    for (uint i = begin; i < end; ++i) total += transitionRates[i];
    if (!(total > 0.0f)) {
        nextTimes[index] = INFINITY;
        nextDestinations[index] = -1;
        rngStates[index] = rng.state;
        return;
    }
    const float waitDraw = rng.next_float01();
    const float target = rng.next_float01() * total;
    const float wait = -log(waitDraw) / total;
    float cumulative = 0.0f;
    int destination = transitionDestinations[end - 1];
    for (uint i = begin; i < end; ++i) {
        cumulative += transitionRates[i];
        if (cumulative >= target) {
            destination = transitionDestinations[i];
            break;
        }
    }
    nextTimes[index] = now + wait;
    nextDestinations[index] = destination;
    rngStates[index] = rng.state;
}

kernel void nfnext_unary_state_batch(
    constant SimParams& params [[buffer(0)]],
    constant uint* transitionOffsets [[buffer(1)]],
    constant int* transitionDestinations [[buffer(2)]],
    constant float* transitionRates [[buffer(3)]],
    constant int* initialStates [[buffer(4)]],
    constant int* observableStates [[buffer(5)]],
    constant float* sampleTimes [[buffer(6)]],
    device int* particleStates [[buffer(7)]],
    device float* outputs [[buffer(8)]],
    device ulong* eventCounts [[buffer(9)]],
    device uint* errorFlags [[buffer(10)]],
    device float* nextTimes [[buffer(11)]],
    device int* nextDestinations [[buffer(12)]],
    device ulong* rngStates [[buffer(13)]],
    device ulong* rngIncrements [[buffer(14)]],
    uint trajectory [[thread_position_in_grid]])
{
    if (trajectory >= params.batchSize) return;
    const uint particleBase = trajectory * params.numParticles;
    for (uint particle = 0; particle < params.numParticles; ++particle) {
        const uint index = particleBase + particle;
        particleStates[index] = initialStates[particle];
        PCG32 rng;
        const ulong stream = (ulong)trajectory * (ulong)params.numParticles + (ulong)particle;
        const ulong key = params.baseSeed + stream * 2ULL;
        rng.init(splitmix64(key), splitmix64(key + 1ULL));
        rngStates[index] = rng.state;
        rngIncrements[index] = rng.inc;
        scheduleForState(index, particleStates[index], 0.0f, params,
                         transitionOffsets, transitionDestinations, transitionRates,
                         nextTimes, nextDestinations, rngStates, rngIncrements);
    }

    ulong events = 0ULL;
    for (uint output = 0; output < params.numOutputs; ++output) {
        const float sampleTime = sampleTimes[output];
        for (;;) {
            float earliest = INFINITY;
            int selected = -1;
            for (uint particle = 0; particle < params.numParticles; ++particle) {
                const uint index = particleBase + particle;
                if (nextTimes[index] < earliest) {
                    earliest = nextTimes[index];
                    selected = (int)particle;
                }
            }
            if (selected < 0 || earliest > sampleTime) break;
            if (events >= (ulong)params.maxEvents) {
                errorFlags[trajectory] = 1U;
                eventCounts[trajectory] = events;
                return;
            }
            const uint index = particleBase + (uint)selected;
            particleStates[index] = nextDestinations[index];
            ++events;
            scheduleForState(index, particleStates[index], earliest, params,
                             transitionOffsets, transitionDestinations, transitionRates,
                             nextTimes, nextDestinations, rngStates, rngIncrements);
        }
        for (uint observable = 0; observable < params.numObservables; ++observable) {
            uint count = 0U;
            const int targetState = observableStates[observable];
            for (uint particle = 0; particle < params.numParticles; ++particle) {
                const int state = particleStates[particleBase + particle];
                if (targetState < 0 || state == targetState) ++count;
            }
            outputs[(trajectory * params.numOutputs + output) * params.numObservables + observable] =
                (float)count;
        }
    }
    eventCounts[trajectory] = events;
}
)METAL";

struct SimParams {
    std::uint32_t numStates;
    std::uint32_t numTransitions;
    std::uint32_t numObservables;
    std::uint32_t numOutputs;
    std::uint32_t batchSize;
    std::uint32_t numParticles;
    std::uint32_t maxEvents;
    std::uint32_t reserved;
    std::uint64_t baseSeed;
};
static_assert(sizeof(SimParams) == 40);

std::size_t checkedBytes(std::size_t count, std::size_t itemSize) {
    if (count != 0 && itemSize > std::numeric_limits<std::size_t>::max() / count)
        throw std::runtime_error("NFnext Metal backend: device buffer size overflow");
    return count * itemSize;
}

id<MTLBuffer> makeBuffer(id<MTLDevice> device, const void* data,
                         std::size_t bytes) {
    const std::size_t allocated = bytes == 0 ? sizeof(std::uint32_t) : bytes;
    if (bytes == 0 || data == nullptr)
        return [device newBufferWithLength:allocated options:MTLResourceStorageModeShared];
    return [device newBufferWithBytes:data length:allocated options:MTLResourceStorageModeShared];
}

} // namespace

NfnextMetalOutput simulateNfnextUnaryStateMetal(
    const NfnextUnaryStatePlan& plan, const NfnextGpuRequest& request) {
    const auto wallStart = std::chrono::steady_clock::now();
    if (request.sampleTimes.size() > std::numeric_limits<std::uint32_t>::max() ||
        plan.observableNames.size() > std::numeric_limits<std::uint32_t>::max() ||
        plan.transitionRates.size() > std::numeric_limits<std::uint32_t>::max() ||
        plan.initialStates.size() > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("NFnext Metal backend: model dimensions exceed kernel index capacity");
    }
    const auto batchSize = static_cast<std::uint32_t>(request.batchSize);
    const auto particleCount = static_cast<std::uint32_t>(plan.initialStates.size());
    const auto outputCount = static_cast<std::uint32_t>(request.sampleTimes.size());
    const auto observableCount = static_cast<std::uint32_t>(plan.observableNames.size());
    const std::size_t particleSlots = checkedBytes(request.batchSize, plan.initialStates.size());
    if (particleSlots > std::numeric_limits<std::uint32_t>::max())
        throw std::runtime_error("NFnext Metal backend: particle workspace exceeds kernel index capacity");
    const std::size_t outputValues = checkedBytes(
        checkedBytes(request.batchSize, request.sampleTimes.size()),
        plan.observableNames.size());
    const std::size_t stateBytes = checkedBytes(particleSlots, sizeof(std::int32_t));
    const std::size_t timeBytes = checkedBytes(request.sampleTimes.size(), sizeof(float));
    const std::size_t outputBytes = checkedBytes(outputValues, sizeof(float));
    const std::size_t eventBytes = checkedBytes(request.batchSize, sizeof(std::uint64_t));
    const std::size_t flagBytes = checkedBytes(request.batchSize, sizeof(std::uint32_t));

    std::vector<float> sampleTimes;
    sampleTimes.reserve(request.sampleTimes.size());
    for (const double time : request.sampleTimes) sampleTimes.push_back(static_cast<float>(time));

    SimParams params{};
    params.numStates = static_cast<std::uint32_t>(plan.transitionOffsets.size() - 1);
    params.numTransitions = static_cast<std::uint32_t>(plan.transitionRates.size());
    params.numObservables = observableCount;
    params.numOutputs = outputCount;
    params.batchSize = batchSize;
    params.numParticles = particleCount;
    params.maxEvents = static_cast<std::uint32_t>(request.maxEvents);
    params.baseSeed = request.seed;

    @autoreleasepool {
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        if (!device) throw std::runtime_error("NFnext Metal backend: no Metal device available");
        id<MTLCommandQueue> queue = [device newCommandQueue];
        if (!queue) throw std::runtime_error("NFnext Metal backend: failed to create command queue");

        NSError* error = nil;
        NSString* source = [NSString stringWithUTF8String:kNfnextUnaryStateShader];
        id<MTLLibrary> library = [device newLibraryWithSource:source options:nil error:&error];
        if (!library) {
            const std::string detail = error ? [[error localizedDescription] UTF8String] : "unknown shader compiler error";
            throw std::runtime_error("NFnext Metal backend: shader compile failed: " + detail);
        }
        id<MTLFunction> function = [library newFunctionWithName:@"nfnext_unary_state_batch"];
        if (!function) throw std::runtime_error("NFnext Metal backend: kernel entry point is missing");
        id<MTLComputePipelineState> pipeline =
            [device newComputePipelineStateWithFunction:function error:&error];
        if (!pipeline) {
            const std::string detail = error ? [[error localizedDescription] UTF8String] : "unknown pipeline error";
            throw std::runtime_error("NFnext Metal backend: pipeline creation failed: " + detail);
        }

        id<MTLBuffer> paramsBuffer = makeBuffer(device, &params, sizeof(params));
        id<MTLBuffer> offsetsBuffer = makeBuffer(device, plan.transitionOffsets.data(),
                                                  checkedBytes(plan.transitionOffsets.size(), sizeof(std::uint32_t)));
        id<MTLBuffer> destinationsBuffer = makeBuffer(device, plan.transitionDestinations.data(),
                                                       checkedBytes(plan.transitionDestinations.size(), sizeof(std::int32_t)));
        id<MTLBuffer> ratesBuffer = makeBuffer(device, plan.transitionRates.data(),
                                                checkedBytes(plan.transitionRates.size(), sizeof(float)));
        id<MTLBuffer> initialBuffer = makeBuffer(device, plan.initialStates.data(), stateBytes / request.batchSize);
        id<MTLBuffer> observableStatesBuffer = makeBuffer(device, plan.observableStates.data(),
                                                           checkedBytes(plan.observableStates.size(), sizeof(std::int32_t)));
        id<MTLBuffer> timesBuffer = makeBuffer(device, sampleTimes.data(), timeBytes);
        id<MTLBuffer> statesBuffer = makeBuffer(device, nullptr, stateBytes);
        id<MTLBuffer> outputBuffer = makeBuffer(device, nullptr, outputBytes);
        id<MTLBuffer> eventsBuffer = makeBuffer(device, nullptr, eventBytes);
        id<MTLBuffer> flagsBuffer = makeBuffer(device, nullptr, flagBytes);
        id<MTLBuffer> nextTimesBuffer = makeBuffer(
            device, nullptr, checkedBytes(particleSlots, sizeof(float)));
        id<MTLBuffer> nextDestinationsBuffer = makeBuffer(
            device, nullptr, checkedBytes(particleSlots, sizeof(std::int32_t)));
        id<MTLBuffer> rngStatesBuffer = makeBuffer(
            device, nullptr, checkedBytes(particleSlots, sizeof(std::uint64_t)));
        id<MTLBuffer> rngIncrementsBuffer = makeBuffer(
            device, nullptr, checkedBytes(particleSlots, sizeof(std::uint64_t)));
        if (!paramsBuffer || !offsetsBuffer || !destinationsBuffer || !ratesBuffer ||
            !initialBuffer || !observableStatesBuffer || !timesBuffer || !statesBuffer ||
            !outputBuffer || !eventsBuffer || !flagsBuffer || !nextTimesBuffer ||
            !nextDestinationsBuffer || !rngStatesBuffer || !rngIncrementsBuffer) {
            throw std::runtime_error("NFnext Metal backend: failed to allocate device buffers");
        }
        std::memset([flagsBuffer contents], 0, flagBytes);

        const auto dispatchStart = std::chrono::steady_clock::now();
        id<MTLCommandBuffer> command = [queue commandBuffer];
        id<MTLComputeCommandEncoder> encoder = [command computeCommandEncoder];
        [encoder setComputePipelineState:pipeline];
        [encoder setBuffer:paramsBuffer offset:0 atIndex:0];
        [encoder setBuffer:offsetsBuffer offset:0 atIndex:1];
        [encoder setBuffer:destinationsBuffer offset:0 atIndex:2];
        [encoder setBuffer:ratesBuffer offset:0 atIndex:3];
        [encoder setBuffer:initialBuffer offset:0 atIndex:4];
        [encoder setBuffer:observableStatesBuffer offset:0 atIndex:5];
        [encoder setBuffer:timesBuffer offset:0 atIndex:6];
        [encoder setBuffer:statesBuffer offset:0 atIndex:7];
        [encoder setBuffer:outputBuffer offset:0 atIndex:8];
        [encoder setBuffer:eventsBuffer offset:0 atIndex:9];
        [encoder setBuffer:flagsBuffer offset:0 atIndex:10];
        [encoder setBuffer:nextTimesBuffer offset:0 atIndex:11];
        [encoder setBuffer:nextDestinationsBuffer offset:0 atIndex:12];
        [encoder setBuffer:rngStatesBuffer offset:0 atIndex:13];
        [encoder setBuffer:rngIncrementsBuffer offset:0 atIndex:14];
        const MTLSize grid = MTLSizeMake(batchSize, 1, 1);
        const NSUInteger groupWidth = std::min<NSUInteger>(64, pipeline.maxTotalThreadsPerThreadgroup);
        [encoder dispatchThreads:grid threadsPerThreadgroup:MTLSizeMake(groupWidth, 1, 1)];
        [encoder endEncoding];
        [command commit];
        [command waitUntilCompleted];
        const auto dispatchEnd = std::chrono::steady_clock::now();
        if (command.status != MTLCommandBufferStatusCompleted) {
            const std::string detail = command.error ? [[command.error localizedDescription] UTF8String] : "unknown command error";
            throw std::runtime_error("NFnext Metal backend: command failed: " + detail);
        }

        const auto* flags = static_cast<const std::uint32_t*>([flagsBuffer contents]);
        for (std::size_t trajectory = 0; trajectory < request.batchSize; ++trajectory) {
            if (flags[trajectory] != 0)
                throw std::runtime_error("NFnext Metal backend: max_events exceeded in trajectory " +
                                         std::to_string(trajectory));
        }

        NfnextMetalOutput output;
        output.device = [[device name] UTF8String];
        output.observables.resize(outputValues);
        if (outputBytes != 0)
            std::memcpy(output.observables.data(), [outputBuffer contents], outputBytes);
        output.eventCounts.resize(request.batchSize);
        std::memcpy(output.eventCounts.data(), [eventsBuffer contents], eventBytes);
        output.dispatchWaitTimeMs = std::chrono::duration<double, std::milli>(
            dispatchEnd - dispatchStart).count();
        output.wallTimeMs = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - wallStart).count();
        return output;
    }
}

} // namespace bng::engine::detail
