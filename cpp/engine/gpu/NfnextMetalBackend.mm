#include "engine/gpu/NfnextUnaryStateKernel.hpp"
#include "engine/gpu/NfnextGraphKernel.hpp"

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
        const auto setupEnd = std::chrono::steady_clock::now();

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
        output.setupTimeMs = std::chrono::duration<double, std::milli>(
            setupEnd - wallStart).count();
        output.deviceMemoryBytes =
            sizeof(params) +
            checkedBytes(plan.transitionOffsets.size(), sizeof(std::uint32_t)) +
            checkedBytes(plan.transitionDestinations.size(), sizeof(std::int32_t)) +
            checkedBytes(plan.transitionRates.size(), sizeof(float)) +
            checkedBytes(plan.initialStates.size(), sizeof(std::int32_t)) +
            checkedBytes(plan.observableStates.size(), sizeof(std::int32_t)) +
            timeBytes + stateBytes + outputBytes + eventBytes + flagBytes +
            checkedBytes(particleSlots, sizeof(float)) +
            checkedBytes(particleSlots, sizeof(std::int32_t)) +
            2 * checkedBytes(particleSlots, sizeof(std::uint64_t));
        output.wallTimeMs = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - wallStart).count();
        return output;
    }
}

namespace {

static const char* kNfnextGraphShader = R"METAL(
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
    uint next_bounded(uint bound) {
        if (bound <= 1u) return 0u;
        return next_u32() % bound;
    }
};

ulong splitmix64(ulong value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30ULL)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27ULL)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31ULL);
}

struct GraphSimParams {
    uint numTypes;
    uint maxSites;
    uint totalCapacity;
    uint totalMatchListSlots;
    uint numMatchLists;
    uint numRules;
    uint numObservables;
    uint numOutputs;
    uint batchSize;
    uint maxEvents;
    ulong baseSeed;
};

struct GpuSiteConstraint {
    ushort site;
    uchar kind;
    uchar pad;
    int state;
};

struct GpuMatchListDef {
    int anchorType;
    int partnerType;
    uint node0ConstraintOffset;
    uint node0ConstraintCount;
    uint node1ConstraintOffset;
    uint node1ConstraintCount;
    ushort bondSite0;
    ushort bondSite1;
    uint listOffset;
    uint listCapacity;
};

struct GpuRuleAction {
    uchar kind;
    uchar pad;
    ushort targetNode;
    ushort site;
    ushort partnerNode;
    ushort partnerSite;
    ushort reserved;
    int value;
};

struct GpuGraphRule {
    uint matchList0;
    uint matchList1;
    uint actionOffset;
    uint actionCount;
    uint vmOffset;
    uint vmLen;
    float rate;
    uchar isTwoComponent;
    uchar isInterchangeable;
    uchar isDynamicRate;
    uchar hasLocalObservable;
    uint createdCount;
    uint pad;
};

struct GpuVmInstr {
    uchar op;
    uchar pad0;
    ushort pad1;
    uint index;
    float value;
};

struct GpuObsPatternNode {
    int molType;
    uint constraintOffset;
    uint constraintCount;
};

struct GpuObsPatternBond {
    ushort firstNode;
    ushort firstSite;
    ushort secondNode;
    ushort secondSite;
};

struct GpuObsTermDef {
    uint nodeOffset;
    uint nodeCount;
    uint bondOffset;
    uint bondCount;
    uint weight;
    uint pad;
};

struct GpuObsDef {
    uint termOffset;
    uint termCount;
    uchar isSpecies;
    uchar pad0;
    ushort pad1;
};

bool nodeMatchesConstraints(
    uint pBase,
    uint maxSites,
    int mol,
    uint cOff,
    uint cCnt,
    constant GpuSiteConstraint* constraints,
    device const int* siteState,
    device const int* siteBondMol)
{
    const uint sBase = (pBase + (uint)mol) * maxSites;
    for (uint i = 0; i < cCnt; ++i) {
        const GpuSiteConstraint c = constraints[cOff + i];
        const uint idx = sBase + (uint)c.site;
        if (c.kind == 0u) {
            if (siteState[idx] != c.state) return false;
        } else if (c.kind == 1u) {
            if (siteBondMol[idx] >= 0) return false;
        } else if (c.kind == 2u) {
            if (siteBondMol[idx] < 0) return false;
        }
    }
    return true;
}

bool particleMatchesList(
    uint pBase,
    uint maxSites,
    int mol,
    GpuMatchListDef ml,
    constant GpuSiteConstraint* constraints,
    device const char* alive,
    device const int* molType,
    device const int* siteState,
    device const int* siteBondMol,
    device const int* siteBondSite)
{
    if (alive[pBase + (uint)mol] == 0) return false;
    if (molType[pBase + (uint)mol] != ml.anchorType) return false;
    if (!nodeMatchesConstraints(pBase, maxSites, mol,
                                ml.node0ConstraintOffset, ml.node0ConstraintCount,
                                constraints, siteState, siteBondMol)) {
        return false;
    }
    if (ml.partnerType < 0) return true;
    const uint sIdx = (pBase + (uint)mol) * maxSites + (uint)ml.bondSite0;
    const int partner = siteBondMol[sIdx];
    if (partner < 0 || partner == mol) return false;
    if (siteBondSite[sIdx] != (int)ml.bondSite1) return false;
    if (alive[pBase + (uint)partner] == 0) return false;
    if (molType[pBase + (uint)partner] != ml.partnerType) return false;
    return nodeMatchesConstraints(pBase, maxSites, partner,
                                  ml.node1ConstraintOffset, ml.node1ConstraintCount,
                                  constraints, siteState, siteBondMol);
}

void updateMatchListForMol(
    uint traj,
    constant GraphSimParams& params,
    uint mlIdx,
    int mol,
    bool shouldContain,
    constant uint* typeOffsets,
    constant GpuMatchListDef* matchLists,
    device int* mlItems,
    device int* mlPos,
    device uint* mlCounts)
{
    const GpuMatchListDef ml = matchLists[mlIdx];
    const uint localIdx = (uint)mol - typeOffsets[(uint)ml.anchorType];
    const uint mlBase = traj * params.totalMatchListSlots + ml.listOffset;
    const uint cntIdx = traj * params.numMatchLists + mlIdx;
    const int pos = mlPos[mlBase + localIdx];
    if (shouldContain) {
        if (pos < 0) {
            const uint n = mlCounts[cntIdx];
            mlItems[mlBase + n] = mol;
            mlPos[mlBase + localIdx] = (int)n;
            mlCounts[cntIdx] = n + 1u;
        }
    } else {
        if (pos >= 0) {
            const uint lastIdx = mlCounts[cntIdx] - 1u;
            const int lastMol = mlItems[mlBase + lastIdx];
            mlItems[mlBase + (uint)pos] = lastMol;
            const uint lastLocal = (uint)lastMol - typeOffsets[(uint)ml.anchorType];
            mlPos[mlBase + lastLocal] = pos;
            mlPos[mlBase + localIdx] = -1;
            mlCounts[cntIdx] = lastIdx;
        }
    }
}

void refreshMolecule(
    uint traj,
    uint pBase,
    int mol,
    int slotType,
    constant GraphSimParams& params,
    constant uint* typeOffsets,
    constant GpuSiteConstraint* constraints,
    constant GpuMatchListDef* matchLists,
    device const char* alive,
    device const int* molType,
    device const int* siteState,
    device const int* siteBondMol,
    device const int* siteBondSite,
    device int* mlItems,
    device int* mlPos,
    device uint* mlCounts)
{
    for (uint mlIdx = 0; mlIdx < params.numMatchLists; ++mlIdx) {
        const GpuMatchListDef ml = matchLists[mlIdx];
        if (ml.anchorType != slotType) continue;
        const bool ok = particleMatchesList(
            pBase, params.maxSites, mol, ml, constraints,
            alive, molType, siteState, siteBondMol, siteBondSite);
        updateMatchListForMol(
            traj, params, mlIdx, mol, ok, typeOffsets, matchLists,
            mlItems, mlPos, mlCounts);
    }
}

int findSlotType(int mol, uint numTypes, constant uint* typeOffsets, constant uint* typeCaps) {
    const uint m = (uint)mol;
    for (uint t = 0; t < numTypes; ++t) {
        if (m >= typeOffsets[t] && m < typeOffsets[t] + typeCaps[t]) return (int)t;
    }
    return -1;
}

bool matchObsTermFromRoot(
    uint pBase,
    uint maxSites,
    int rootMol,
    GpuObsTermDef term,
    constant GpuObsPatternNode* obsNodes,
    constant GpuObsPatternBond* obsBonds,
    constant GpuSiteConstraint* constraints,
    constant uint* typeSiteCounts,
    device const char* alive,
    device const int* molType,
    device const int* siteState,
    device const int* siteBondMol,
    device const int* siteBondSite,
    bool requireWholeComplex)
{
    const GpuObsPatternNode n0 = obsNodes[term.nodeOffset];
    if (alive[pBase + (uint)rootMol] == 0) return false;
    if (molType[pBase + (uint)rootMol] != n0.molType) return false;
    if (!nodeMatchesConstraints(pBase, maxSites, rootMol,
                                n0.constraintOffset, n0.constraintCount,
                                constraints, siteState, siteBondMol)) {
        return false;
    }
    int assigned[4];
    for (uint i = 0; i < 4; ++i) assigned[i] = -1;
    assigned[0] = rootMol;

    // Resolve remaining nodes deterministically via pattern bonds.
    for (uint pass = 0; pass < term.nodeCount; ++pass) {
        bool progressed = false;
        for (uint bi = 0; bi < term.bondCount; ++bi) {
            const GpuObsPatternBond b = obsBonds[term.bondOffset + bi];
            int a = assigned[b.firstNode];
            int c = assigned[b.secondNode];
            if (a >= 0 && c < 0) {
                const uint idx = (pBase + (uint)a) * maxSites + (uint)b.firstSite;
                const int partner = siteBondMol[idx];
                if (partner < 0 || siteBondSite[idx] != (int)b.secondSite) return false;
                assigned[b.secondNode] = partner;
                progressed = true;
            } else if (c >= 0 && a < 0) {
                const uint idx = (pBase + (uint)c) * maxSites + (uint)b.secondSite;
                const int partner = siteBondMol[idx];
                if (partner < 0 || siteBondSite[idx] != (int)b.firstSite) return false;
                assigned[b.firstNode] = partner;
                progressed = true;
            }
        }
        if (!progressed) break;
    }

    // Validate all nodes assigned, distinct, alive, and satisfy constraints.
    for (uint ni = 0; ni < term.nodeCount; ++ni) {
        const int m = assigned[ni];
        if (m < 0 || alive[pBase + (uint)m] == 0) return false;
        for (uint nj = 0; nj < ni; ++nj) {
            if (assigned[nj] == m) return false;
        }
        const GpuObsPatternNode nd = obsNodes[term.nodeOffset + ni];
        if (molType[pBase + (uint)m] != nd.molType) return false;
        if (!nodeMatchesConstraints(pBase, maxSites, m,
                                    nd.constraintOffset, nd.constraintCount,
                                    constraints, siteState, siteBondMol)) {
            return false;
        }
    }
    // Validate all pattern bonds.
    for (uint bi = 0; bi < term.bondCount; ++bi) {
        const GpuObsPatternBond b = obsBonds[term.bondOffset + bi];
        const int a = assigned[b.firstNode];
        const int c = assigned[b.secondNode];
        const uint idx = (pBase + (uint)a) * maxSites + (uint)b.firstSite;
        if (siteBondMol[idx] != c || siteBondSite[idx] != (int)b.secondSite) return false;
    }
    if (requireWholeComplex) {
        // Every bond on every assigned molecule must stay within the assigned set,
        // and rootMol must be the smallest molecule of type n0.molType in assigned
        // so symmetric complexes are counted once.
        for (uint ni = 1; ni < term.nodeCount; ++ni) {
            if (obsNodes[term.nodeOffset + ni].molType == n0.molType &&
                assigned[ni] < rootMol) {
                return false;
            }
        }
        for (uint ni = 0; ni < term.nodeCount; ++ni) {
            const int m = assigned[ni];
            const uint sc = typeSiteCounts[(uint)molType[pBase + (uint)m]];
            for (uint s = 0; s < sc; ++s) {
                const int p = siteBondMol[(pBase + (uint)m) * maxSites + s];
                if (p < 0) continue;
                bool inSet = false;
                for (uint nj = 0; nj < term.nodeCount; ++nj) {
                    if (assigned[nj] == p) { inSet = true; break; }
                }
                if (!inSet) return false;
            }
        }
    }
    return true;
}

float evalObservable(
    uint pBase,
    uint obsIdx,
    constant GraphSimParams& params,
    constant uint* typeOffsets,
    constant uint* typeCaps,
    constant uint* typeSiteCounts,
    constant GpuSiteConstraint* constraints,
    constant GpuObsPatternNode* obsNodes,
    constant GpuObsPatternBond* obsBonds,
    constant GpuObsTermDef* obsTerms,
    constant GpuObsDef* observables,
    device const char* alive,
    device const int* molType,
    device const int* siteState,
    device const int* siteBondMol,
    device const int* siteBondSite)
{
    const GpuObsDef obs = observables[obsIdx];
    uint total = 0u;
    if (obs.isSpecies == 0u) {
        for (uint ti = 0; ti < obs.termCount; ++ti) {
            const GpuObsTermDef term = obsTerms[obs.termOffset + ti];
            const uint t0 = (uint)obsNodes[term.nodeOffset].molType;
            const uint start = typeOffsets[t0];
            const uint end = start + typeCaps[t0];
            uint matches = 0u;
            for (uint m = start; m < end; ++m) {
                if (matchObsTermFromRoot(pBase, params.maxSites, (int)m, term,
                                         obsNodes, obsBonds, constraints, typeSiteCounts,
                                         alive, molType, siteState, siteBondMol, siteBondSite,
                                         false)) {
                    ++matches;
                }
            }
            total += matches * term.weight;
        }
    } else {
        // Species observable: count each distinct complex matching at least one term.
        if (obs.termCount > 0u) {
            const uint t0 = (uint)obsNodes[obsTerms[obs.termOffset].nodeOffset].molType;
            const uint start = typeOffsets[t0];
            const uint end = start + typeCaps[t0];
            for (uint m = start; m < end; ++m) {
                if (alive[pBase + m] == 0) continue;
                bool matchedAny = false;
                for (uint ti = 0; ti < obs.termCount; ++ti) {
                    if (matchObsTermFromRoot(pBase, params.maxSites, (int)m,
                                             obsTerms[obs.termOffset + ti],
                                             obsNodes, obsBonds, constraints, typeSiteCounts,
                                             alive, molType, siteState, siteBondMol, siteBondSite,
                                             true)) {
                        matchedAny = true;
                        break;
                    }
                }
                if (matchedAny) ++total;
            }
        }
    }
    return (float)total;
}

float evalVm(
    uint vmOffset,
    uint vmLen,
    constant GpuVmInstr* vmCode,
    thread const float* obsValues,
    thread bool& ok)
{
    float stack[32];
    uint top = 0u;
    uint pc = 0u;
    while (pc < vmLen) {
        const GpuVmInstr ins = vmCode[vmOffset + pc++];
        const uchar op = ins.op;
        if (op == 0u) {
            stack[top++] = ins.value;
        } else if (op == 1u) {
            stack[top++] = obsValues[ins.index];
        } else if (op == 2u) {
            float b = stack[--top]; stack[top - 1u] += b;
        } else if (op == 3u) {
            float b = stack[--top]; stack[top - 1u] -= b;
        } else if (op == 4u) {
            float b = stack[--top]; stack[top - 1u] *= b;
        } else if (op == 5u) {
            float b = stack[--top];
            if (b == 0.0f) { ok = false; return 0.0f; }
            stack[top - 1u] /= b;
        } else if (op == 6u) {
            float b = stack[--top]; stack[top - 1u] = pow(stack[top - 1u], b);
        } else if (op == 7u) {
            stack[top - 1u] = -stack[top - 1u];
        } else if (op == 8u) {
            stack[top - 1u] = exp(stack[top - 1u]);
        } else if (op == 9u) {
            stack[top - 1u] = log(stack[top - 1u]);
        } else if (op == 10u) {
            stack[top - 1u] = sqrt(stack[top - 1u]);
        } else if (op == 11u) {
            stack[top - 1u] = sin(stack[top - 1u]);
        } else if (op == 12u) {
            stack[top - 1u] = cos(stack[top - 1u]);
        } else if (op == 13u) {
            stack[top - 1u] = tan(stack[top - 1u]);
        } else if (op == 14u) {
            stack[top - 1u] = fabs(stack[top - 1u]);
        } else if (op == 15u) {
            float b = stack[--top]; stack[top - 1u] = min(stack[top - 1u], b);
        } else if (op == 16u) {
            float b = stack[--top]; stack[top - 1u] = max(stack[top - 1u], b);
        } else if (op == 17u) {
            float b = stack[--top]; stack[top - 1u] = (stack[top - 1u] < b) ? 1.0f : 0.0f;
        } else if (op == 18u) {
            float b = stack[--top]; stack[top - 1u] = (stack[top - 1u] <= b) ? 1.0f : 0.0f;
        } else if (op == 19u) {
            float b = stack[--top]; stack[top - 1u] = (stack[top - 1u] > b) ? 1.0f : 0.0f;
        } else if (op == 20u) {
            float b = stack[--top]; stack[top - 1u] = (stack[top - 1u] >= b) ? 1.0f : 0.0f;
        } else if (op == 21u) {
            float b = stack[--top]; stack[top - 1u] = (stack[top - 1u] == b) ? 1.0f : 0.0f;
        } else if (op == 22u) {
            float b = stack[--top]; stack[top - 1u] = (stack[top - 1u] != b) ? 1.0f : 0.0f;
        } else if (op == 23u) {
            if (stack[--top] == 0.0f) pc = ins.index;
        } else if (op == 24u) {
            pc = ins.index;
        }
    }
    if (top != 1u || !isfinite(stack[0]) || stack[0] < 0.0f) {
        ok = false;
        return 0.0f;
    }
    return stack[0];
}

void addTouched(thread int* touched, thread uint& touchedCount, int mol) {
    if (mol < 0) return;
    for (uint i = 0; i < touchedCount; ++i) {
        if (touched[i] == mol) return;
    }
    if (touchedCount < 32u) touched[touchedCount++] = mol;
}

kernel void nfnext_graph_batch(
    constant GraphSimParams& params [[buffer(0)]],
    constant uint* typeOffsets [[buffer(1)]],
    constant uint* typeCaps [[buffer(2)]],
    constant uint* typeSiteCounts [[buffer(3)]],
    constant char* initAlive [[buffer(4)]],
    constant int* initMolType [[buffer(5)]],
    constant int* initSiteState [[buffer(6)]],
    constant int* initSiteBondMol [[buffer(7)]],
    constant int* initSiteBondSite [[buffer(8)]],
    constant GpuSiteConstraint* constraints [[buffer(9)]],
    constant GpuMatchListDef* matchLists [[buffer(10)]],
    constant GpuRuleAction* actions [[buffer(11)]],
    constant GpuGraphRule* rules [[buffer(12)]],
    constant GpuVmInstr* vmCode [[buffer(13)]],
    constant GpuObsPatternNode* obsNodes [[buffer(14)]],
    constant GpuObsPatternBond* obsBonds [[buffer(15)]],
    constant GpuObsTermDef* obsTerms [[buffer(16)]],
    constant GpuObsDef* observables [[buffer(17)]],
    constant float* sampleTimes [[buffer(18)]],
    device char* alive [[buffer(19)]],
    device int* molType [[buffer(20)]],
    device int* siteState [[buffer(21)]],
    device int* siteBondMol [[buffer(22)]],
    device int* siteBondSite [[buffer(23)]],
    device int* mlItems [[buffer(24)]],
    device int* mlPos [[buffer(25)]],
    device uint* mlCounts [[buffer(26)]],
    device float* outputs [[buffer(27)]],
    device ulong* eventCounts [[buffer(28)]],
    device uint* errorFlags [[buffer(29)]],
    uint trajectory [[thread_position_in_grid]])
{
    if (trajectory >= params.batchSize) return;

    const uint pBase = trajectory * params.totalCapacity;
    const uint sBase = pBase * params.maxSites;
    for (uint m = 0; m < params.totalCapacity; ++m) {
        alive[pBase + m] = initAlive[m];
        molType[pBase + m] = initMolType[m];
        for (uint s = 0; s < params.maxSites; ++s) {
            const uint idx = m * params.maxSites + s;
            siteState[sBase + idx] = initSiteState[idx];
            siteBondMol[sBase + idx] = initSiteBondMol[idx];
            siteBondSite[sBase + idx] = initSiteBondSite[idx];
        }
    }
    const uint mlBaseAll = trajectory * params.totalMatchListSlots;
    for (uint i = 0; i < params.totalMatchListSlots; ++i) {
        mlPos[mlBaseAll + i] = -1;
    }
    for (uint mlIdx = 0; mlIdx < params.numMatchLists; ++mlIdx) {
        mlCounts[trajectory * params.numMatchLists + mlIdx] = 0u;
    }
    for (uint m = 0; m < params.totalCapacity; ++m) {
        if (alive[pBase + m] == 0) continue;
        const int t = molType[pBase + m];
        refreshMolecule(trajectory, pBase, (int)m, t, params, typeOffsets,
                        constraints, matchLists, alive, molType, siteState,
                        siteBondMol, siteBondSite, mlItems, mlPos, mlCounts);
    }

    PCG32 rng;
    const ulong key = params.baseSeed + (ulong)trajectory * 2ULL;
    rng.init(splitmix64(key), splitmix64(key + 1ULL));

    bool hasDynamicRules = false;
    for (uint r = 0; r < params.numRules; ++r) {
        if (rules[r].isDynamicRate != 0u) { hasDynamicRules = true; break; }
    }

    float ruleProps[256];
    float obsValues[32];
    ulong events = 0ULL;
    float time = 0.0f;

    for (uint outIdx = 0; outIdx < params.numOutputs; ++outIdx) {
        const float targetTime = sampleTimes[outIdx];
        for (;;) {
            if (hasDynamicRules) {
                for (uint oi = 0; oi < params.numObservables && oi < 32u; ++oi) {
                    obsValues[oi] = evalObservable(
                        pBase, oi, params, typeOffsets, typeCaps, typeSiteCounts,
                        constraints, obsNodes, obsBonds, obsTerms, observables,
                        alive, molType, siteState, siteBondMol, siteBondSite);
                }
            }
            float total = 0.0f;
            for (uint r = 0; r < params.numRules; ++r) {
                const GpuGraphRule rule = rules[r];
                float rate = rule.rate;
                if (rule.isDynamicRate != 0u) {
                    bool ok = true;
                    rate = evalVm(rule.vmOffset, rule.vmLen, vmCode, obsValues, ok);
                    if (!ok) {
                        errorFlags[trajectory] = 3u;
                        eventCounts[trajectory] = events;
                        return;
                    }
                }
                const uint c0 = mlCounts[trajectory * params.numMatchLists + rule.matchList0];
                float countF = 0.0f;
                if (rule.isTwoComponent == 0u) {
                    countF = (float)c0;
                } else if (rule.isInterchangeable != 0u) {
                    countF = (c0 > 1u) ? (0.5f * (float)c0 * (float)(c0 - 1u)) : 0.0f;
                } else {
                    const uint c1 = mlCounts[trajectory * params.numMatchLists + rule.matchList1];
                    countF = (float)c0 * (float)c1;
                }
                const float prop = rate * countF;
                ruleProps[r] = prop;
                total += prop;
            }
            if (!(total > 0.0f)) {
                time = targetTime;
                break;
            }
            const float u1 = rng.next_float01();
            const float dt = -log(u1) / total;
            if (time + dt > targetTime) {
                time = targetTime;
                break;
            }
            time += dt;
            if (events >= (ulong)params.maxEvents) {
                errorFlags[trajectory] = 1u;
                eventCounts[trajectory] = events;
                return;
            }

            const float pick = rng.next_float01() * total;
            float cum = 0.0f;
            uint selectedRule = params.numRules - 1u;
            for (uint r = 0; r < params.numRules; ++r) {
                cum += ruleProps[r];
                if (cum >= pick) { selectedRule = r; break; }
            }
            const GpuGraphRule rule = rules[selectedRule];
            const GpuMatchListDef ml0 = matchLists[rule.matchList0];
            const uint c0 = mlCounts[trajectory * params.numMatchLists + rule.matchList0];
            if (c0 == 0u) continue;
            const int m0 = mlItems[mlBaseAll + ml0.listOffset + rng.next_bounded(c0)];

            int nodes[4];
            for (uint i = 0; i < 4; ++i) nodes[i] = -1;
            nodes[0] = m0;
            if (rule.isTwoComponent != 0u) {
                const GpuMatchListDef ml1 = matchLists[rule.matchList1];
                const uint c1 = mlCounts[trajectory * params.numMatchLists + rule.matchList1];
                if (c1 == 0u) continue;
                int m1 = mlItems[mlBaseAll + ml1.listOffset + rng.next_bounded(c1)];
                if (m1 == m0) {
                    if (rule.isInterchangeable != 0u && c1 > 1u) {
                        const uint idx0 = (uint)mlPos[mlBaseAll + ml0.listOffset + ((uint)m0 - typeOffsets[(uint)ml0.anchorType])];
                        uint idx1 = rng.next_bounded(c1 - 1u);
                        if (idx1 >= idx0) ++idx1;
                        m1 = mlItems[mlBaseAll + ml1.listOffset + idx1];
                    } else {
                        // Exact Gillespie thinning null event for identical-particle collision.
                        continue;
                    }
                }
                nodes[1] = m1;
            } else if (ml0.partnerType >= 0) {
                nodes[1] = siteBondMol[(pBase + (uint)m0) * params.maxSites + (uint)ml0.bondSite0];
            }

            int touched[32];
            uint touchedCount = 0u;
            // Record reactants and their pre-reaction direct bond partners.
            for (uint ni = 0; ni < 2u; ++ni) {
                if (nodes[ni] < 0) continue;
                addTouched(touched, touchedCount, nodes[ni]);
                const uint sc = typeSiteCounts[(uint)molType[pBase + (uint)nodes[ni]]];
                for (uint s = 0; s < sc; ++s) {
                    addTouched(touched, touchedCount,
                               siteBondMol[(pBase + (uint)nodes[ni]) * params.maxSites + s]);
                }
            }

            // Apply actions.
            for (uint ai = 0; ai < rule.actionCount; ++ai) {
                const GpuRuleAction act = actions[rule.actionOffset + ai];
                if (act.kind == 3u) {
                    // Create molecule of type act.value in its contiguous type slice.
                    const uint t = (uint)act.value;
                    const uint start = typeOffsets[t];
                    const uint end = start + typeCaps[t];
                    int slot = -1;
                    for (uint cand = start; cand < end; ++cand) {
                        if (alive[pBase + cand] == 0) { slot = (int)cand; break; }
                    }
                    if (slot < 0) {
                        errorFlags[trajectory] = 2u;
                        eventCounts[trajectory] = events;
                        return;
                    }
                    alive[pBase + (uint)slot] = 1;
                    molType[pBase + (uint)slot] = (int)t;
                    for (uint s = 0; s < params.maxSites; ++s) {
                        const uint sIdx = (pBase + (uint)slot) * params.maxSites + s;
                        siteState[sIdx] = 0;
                        siteBondMol[sIdx] = -1;
                        siteBondSite[sIdx] = -1;
                    }
                    nodes[act.targetNode] = slot;
                    addTouched(touched, touchedCount, slot);
                }
            }
            for (uint ai = 0; ai < rule.actionCount; ++ai) {
                const GpuRuleAction act = actions[rule.actionOffset + ai];
                if (act.kind == 0u) {
                    const int m = nodes[act.targetNode];
                    siteState[(pBase + (uint)m) * params.maxSites + (uint)act.site] = act.value;
                } else if (act.kind == 1u) {
                    const int mA = nodes[act.targetNode];
                    const int mB = nodes[act.partnerNode];
                    const uint iA = (pBase + (uint)mA) * params.maxSites + (uint)act.site;
                    const uint iB = (pBase + (uint)mB) * params.maxSites + (uint)act.partnerSite;
                    siteBondMol[iA] = mB;
                    siteBondSite[iA] = (int)act.partnerSite;
                    siteBondMol[iB] = mA;
                    siteBondSite[iB] = (int)act.site;
                } else if (act.kind == 2u) {
                    const int mA = nodes[act.targetNode];
                    const int mB = nodes[act.partnerNode];
                    const uint iA = (pBase + (uint)mA) * params.maxSites + (uint)act.site;
                    const uint iB = (pBase + (uint)mB) * params.maxSites + (uint)act.partnerSite;
                    siteBondMol[iA] = -1;
                    siteBondSite[iA] = -1;
                    siteBondMol[iB] = -1;
                    siteBondSite[iB] = -1;
                } else if (act.kind == 4u) {
                    const int m = nodes[act.targetNode];
                    const uint sc = typeSiteCounts[(uint)molType[pBase + (uint)m]];
                    for (uint s = 0; s < sc; ++s) {
                        const uint iM = (pBase + (uint)m) * params.maxSites + s;
                        const int p = siteBondMol[iM];
                        const int ps = siteBondSite[iM];
                        if (p >= 0 && ps >= 0) {
                            const uint iP = (pBase + (uint)p) * params.maxSites + (uint)ps;
                            siteBondMol[iP] = -1;
                            siteBondSite[iP] = -1;
                            addTouched(touched, touchedCount, p);
                        }
                        siteBondMol[iM] = -1;
                        siteBondSite[iM] = -1;
                    }
                    alive[pBase + (uint)m] = 0;
                } else if (act.kind == 5u) {
                    int dq[32];
                    uint dqh = 0u, dqt = 0u;
                    const int root = nodes[act.targetNode];
                    if (root >= 0 && alive[pBase + (uint)root] != 0) {
                        dq[dqt++] = root;
                        alive[pBase + (uint)root] = 0;
                        addTouched(touched, touchedCount, root);
                        while (dqh < dqt) {
                            const int cur = dq[dqh++];
                            const uint sc = typeSiteCounts[(uint)molType[pBase + (uint)cur]];
                            for (uint s = 0; s < sc; ++s) {
                                const uint iM = (pBase + (uint)cur) * params.maxSites + s;
                                const int p = siteBondMol[iM];
                                const int ps = siteBondSite[iM];
                                siteBondMol[iM] = -1;
                                siteBondSite[iM] = -1;
                                if (p >= 0 && ps >= 0) {
                                    const uint iP = (pBase + (uint)p) * params.maxSites + (uint)ps;
                                    siteBondMol[iP] = -1;
                                    siteBondSite[iP] = -1;
                                    if (alive[pBase + (uint)p] != 0) {
                                        if (dqt >= 32u) {
                                            errorFlags[trajectory] = 4u;
                                            eventCounts[trajectory] = events;
                                            return;
                                        }
                                        alive[pBase + (uint)p] = 0;
                                        dq[dqt++] = p;
                                        addTouched(touched, touchedCount, p);
                                    }
                                }
                            }
                        }
                    }
                }
            }

            for (uint ti = 0; ti < touchedCount; ++ti) {
                const int m = touched[ti];
                const int st = findSlotType(m, params.numTypes, typeOffsets, typeCaps);
                if (st >= 0) {
                    refreshMolecule(trajectory, pBase, m, st, params, typeOffsets,
                                    constraints, matchLists, alive, molType, siteState,
                                    siteBondMol, siteBondSite, mlItems, mlPos, mlCounts);
                }
            }
            ++events;
        }

        for (uint oi = 0; oi < params.numObservables; ++oi) {
            const float val = evalObservable(
                pBase, oi, params, typeOffsets, typeCaps, typeSiteCounts,
                constraints, obsNodes, obsBonds, obsTerms, observables,
                alive, molType, siteState, siteBondMol, siteBondSite);
            outputs[(trajectory * params.numOutputs + outIdx) * params.numObservables + oi] = val;
        }
    }
    eventCounts[trajectory] = events;
}
)METAL";

struct GraphSimParams {
    std::uint32_t numTypes;
    std::uint32_t maxSites;
    std::uint32_t totalCapacity;
    std::uint32_t totalMatchListSlots;
    std::uint32_t numMatchLists;
    std::uint32_t numRules;
    std::uint32_t numObservables;
    std::uint32_t numOutputs;
    std::uint32_t batchSize;
    std::uint32_t maxEvents;
    std::uint64_t baseSeed;
};
static_assert(sizeof(GraphSimParams) == 48);

} // namespace

NfnextDeviceOutput simulateNfnextGraphMetal(
    const NfnextGraphPlan& plan, const NfnextGpuRequest& request) {
    const auto wallStart = std::chrono::steady_clock::now();
    const auto batchSize = static_cast<std::uint32_t>(request.batchSize);
    const std::size_t totalParticleSlots = checkedBytes(request.batchSize, plan.totalCapacity);
    const std::size_t totalSiteSlots = checkedBytes(totalParticleSlots, plan.maxSites);
    const std::size_t totalMlSlots = checkedBytes(request.batchSize, plan.totalMatchListSlots);
    const std::size_t totalMlCounts = checkedBytes(request.batchSize, plan.matchLists.size());
    const std::size_t outputValues = checkedBytes(
        checkedBytes(request.batchSize, request.sampleTimes.size()),
        plan.observables.size());

    std::vector<float> sampleTimes;
    sampleTimes.reserve(request.sampleTimes.size());
    for (const double t : request.sampleTimes) sampleTimes.push_back(static_cast<float>(t));

    GraphSimParams params{};
    params.numTypes = plan.numTypes;
    params.maxSites = plan.maxSites;
    params.totalCapacity = plan.totalCapacity;
    params.totalMatchListSlots = plan.totalMatchListSlots;
    params.numMatchLists = static_cast<std::uint32_t>(plan.matchLists.size());
    params.numRules = static_cast<std::uint32_t>(plan.rules.size());
    params.numObservables = static_cast<std::uint32_t>(plan.observables.size());
    params.numOutputs = static_cast<std::uint32_t>(request.sampleTimes.size());
    params.batchSize = batchSize;
    params.maxEvents = static_cast<std::uint32_t>(request.maxEvents);
    params.baseSeed = request.seed;

    @autoreleasepool {
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        if (!device) throw std::runtime_error("NFnext Metal graph backend: no Metal device available");
        id<MTLCommandQueue> queue = [device newCommandQueue];
        if (!queue) throw std::runtime_error("NFnext Metal graph backend: failed to create command queue");

        NSError* error = nil;
        NSString* source = [NSString stringWithUTF8String:kNfnextGraphShader];
        id<MTLLibrary> library = [device newLibraryWithSource:source options:nil error:&error];
        if (!library) {
            const std::string detail = error ? [[error localizedDescription] UTF8String] : "unknown shader error";
            throw std::runtime_error("NFnext Metal graph backend: shader compile failed: " + detail);
        }
        id<MTLFunction> function = [library newFunctionWithName:@"nfnext_graph_batch"];
        if (!function) throw std::runtime_error("NFnext Metal graph backend: kernel entry point missing");
        id<MTLComputePipelineState> pipeline =
            [device newComputePipelineStateWithFunction:function error:&error];
        if (!pipeline) {
            const std::string detail = error ? [[error localizedDescription] UTF8String] : "unknown pipeline error";
            throw std::runtime_error("NFnext Metal graph backend: pipeline creation failed: " + detail);
        }

        const auto flagBytes = checkedBytes(request.batchSize, sizeof(std::uint32_t));
        const auto eventBytes = checkedBytes(request.batchSize, sizeof(std::uint64_t));
        const auto outputBytes = checkedBytes(outputValues, sizeof(float));

        id<MTLBuffer> b0 = makeBuffer(device, &params, sizeof(params));
        id<MTLBuffer> b1 = makeBuffer(device, plan.typeOffsets.data(), checkedBytes(plan.typeOffsets.size(), sizeof(std::uint32_t)));
        id<MTLBuffer> b2 = makeBuffer(device, plan.typeCapacities.data(), checkedBytes(plan.typeCapacities.size(), sizeof(std::uint32_t)));
        id<MTLBuffer> b3 = makeBuffer(device, plan.typeSiteCounts.data(), checkedBytes(plan.typeSiteCounts.size(), sizeof(std::uint32_t)));
        id<MTLBuffer> b4 = makeBuffer(device, plan.initAlive.data(), checkedBytes(plan.initAlive.size(), sizeof(std::int8_t)));
        id<MTLBuffer> b5 = makeBuffer(device, plan.initMolType.data(), checkedBytes(plan.initMolType.size(), sizeof(std::int32_t)));
        id<MTLBuffer> b6 = makeBuffer(device, plan.initSiteState.data(), checkedBytes(plan.initSiteState.size(), sizeof(std::int32_t)));
        id<MTLBuffer> b7 = makeBuffer(device, plan.initSiteBondMol.data(), checkedBytes(plan.initSiteBondMol.size(), sizeof(std::int32_t)));
        id<MTLBuffer> b8 = makeBuffer(device, plan.initSiteBondSite.data(), checkedBytes(plan.initSiteBondSite.size(), sizeof(std::int32_t)));
        id<MTLBuffer> b9 = makeBuffer(device, plan.constraints.data(), checkedBytes(plan.constraints.size(), sizeof(GpuSiteConstraint)));
        id<MTLBuffer> b10 = makeBuffer(device, plan.matchLists.data(), checkedBytes(plan.matchLists.size(), sizeof(GpuMatchListDef)));
        id<MTLBuffer> b11 = makeBuffer(device, plan.actions.data(), checkedBytes(plan.actions.size(), sizeof(GpuRuleAction)));
        id<MTLBuffer> b12 = makeBuffer(device, plan.rules.data(), checkedBytes(plan.rules.size(), sizeof(GpuGraphRule)));
        id<MTLBuffer> b13 = makeBuffer(device, plan.vmCode.data(), checkedBytes(plan.vmCode.size(), sizeof(GpuVmInstr)));
        id<MTLBuffer> b14 = makeBuffer(device, plan.obsNodes.data(), checkedBytes(plan.obsNodes.size(), sizeof(GpuObsPatternNode)));
        id<MTLBuffer> b15 = makeBuffer(device, plan.obsBonds.data(), checkedBytes(plan.obsBonds.size(), sizeof(GpuObsPatternBond)));
        id<MTLBuffer> b16 = makeBuffer(device, plan.obsTerms.data(), checkedBytes(plan.obsTerms.size(), sizeof(GpuObsTermDef)));
        id<MTLBuffer> b17 = makeBuffer(device, plan.observables.data(), checkedBytes(plan.observables.size(), sizeof(GpuObsDef)));
        id<MTLBuffer> b18 = makeBuffer(device, sampleTimes.data(), checkedBytes(sampleTimes.size(), sizeof(float)));
        id<MTLBuffer> b19 = makeBuffer(device, nullptr, checkedBytes(totalParticleSlots, sizeof(std::int8_t)));
        id<MTLBuffer> b20 = makeBuffer(device, nullptr, checkedBytes(totalParticleSlots, sizeof(std::int32_t)));
        id<MTLBuffer> b21 = makeBuffer(device, nullptr, checkedBytes(totalSiteSlots, sizeof(std::int32_t)));
        id<MTLBuffer> b22 = makeBuffer(device, nullptr, checkedBytes(totalSiteSlots, sizeof(std::int32_t)));
        id<MTLBuffer> b23 = makeBuffer(device, nullptr, checkedBytes(totalSiteSlots, sizeof(std::int32_t)));
        id<MTLBuffer> b24 = makeBuffer(device, nullptr, checkedBytes(totalMlSlots, sizeof(std::int32_t)));
        id<MTLBuffer> b25 = makeBuffer(device, nullptr, checkedBytes(totalMlSlots, sizeof(std::int32_t)));
        id<MTLBuffer> b26 = makeBuffer(device, nullptr, checkedBytes(totalMlCounts, sizeof(std::uint32_t)));
        id<MTLBuffer> b27 = makeBuffer(device, nullptr, outputBytes);
        id<MTLBuffer> b28 = makeBuffer(device, nullptr, eventBytes);
        id<MTLBuffer> b29 = makeBuffer(device, nullptr, flagBytes);

        id<MTLBuffer> allBuffers[30] = {
            b0, b1, b2, b3, b4, b5, b6, b7, b8, b9,
            b10, b11, b12, b13, b14, b15, b16, b17, b18, b19,
            b20, b21, b22, b23, b24, b25, b26, b27, b28, b29
        };
        std::size_t totalBytes = 0;
        for (int i = 0; i < 30; ++i) {
            if (!allBuffers[i]) {
                throw std::runtime_error("NFnext Metal graph backend: failed to allocate device buffer " + std::to_string(i));
            }
            totalBytes += [allBuffers[i] length];
        }
        std::memset([b29 contents], 0, flagBytes);
        const auto setupEnd = std::chrono::steady_clock::now();

        const auto dispatchStart = std::chrono::steady_clock::now();
        id<MTLCommandBuffer> command = [queue commandBuffer];
        id<MTLComputeCommandEncoder> encoder = [command computeCommandEncoder];
        [encoder setComputePipelineState:pipeline];
        for (NSUInteger i = 0; i < 30; ++i) {
            [encoder setBuffer:allBuffers[i] offset:0 atIndex:i];
        }
        const MTLSize grid = MTLSizeMake(batchSize, 1, 1);
        const NSUInteger groupWidth = std::min<NSUInteger>(64, pipeline.maxTotalThreadsPerThreadgroup);
        [encoder dispatchThreads:grid threadsPerThreadgroup:MTLSizeMake(groupWidth, 1, 1)];
        [encoder endEncoding];
        [command commit];
        [command waitUntilCompleted];
        const auto dispatchEnd = std::chrono::steady_clock::now();
        if (command.status != MTLCommandBufferStatusCompleted) {
            const std::string detail = command.error ? [[command.error localizedDescription] UTF8String] : "unknown command error";
            throw std::runtime_error("NFnext Metal graph backend: command failed: " + detail);
        }

        const auto* flags = static_cast<const std::uint32_t*>([b29 contents]);
        for (std::size_t t = 0; t < request.batchSize; ++t) {
            if (flags[t] == 1u)
                throw std::runtime_error("NFnext Metal graph backend: max_events exceeded in trajectory " + std::to_string(t));
            if (flags[t] == 2u)
                throw std::runtime_error("NFnext Metal graph backend: particle capacity exceeded in trajectory " + std::to_string(t));
            if (flags[t] == 3u)
                throw std::runtime_error("NFnext Metal graph backend: invalid dynamic rate in trajectory " + std::to_string(t));
        }

        NfnextDeviceOutput output;
        output.device = [[device name] UTF8String];
        output.observables.resize(outputValues);
        if (outputBytes != 0) std::memcpy(output.observables.data(), [b27 contents], outputBytes);
        output.eventCounts.resize(request.batchSize);
        std::memcpy(output.eventCounts.data(), [b28 contents], eventBytes);
        output.dispatchWaitTimeMs = std::chrono::duration<double, std::milli>(dispatchEnd - dispatchStart).count();
        output.setupTimeMs = std::chrono::duration<double, std::milli>(setupEnd - wallStart).count();
        output.deviceMemoryBytes = totalBytes;
        output.wallTimeMs = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - wallStart).count();
        return output;
    }
}

} // namespace bng::engine::detail
