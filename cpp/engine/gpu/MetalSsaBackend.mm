// Apple Metal backend for the batched direct-SSA kernel.
//
// One compute thread runs one trajectory. The MSL kernel below is the
// reference implementation of the algorithm: the CUDA backend ports it
// statement for statement, including the PCG32 seeding and draw order.
//
// The two accelerators do NOT produce identical trajectories for a given seed,
// and that is a property of floating point rather than of either port. Both
// toolchains contract fused multiply-adds independently, and reaction
// selection accumulates `cum += propensity(r)` in reaction order, so a single
// differing contraction changes which reaction fires and the trajectories
// diverge from that point on. `logf` may also lower to a different library
// than the shading-language `log`.
//
// What IS shared is the seeded state and the draw ORDER. Cross-backend
// agreement is therefore a statistical question, validated against a
// closed-form reference -- never a bit-identity comparison.

#include "engine/gpu/GpuSsaBackend.hpp"

#import <Metal/Metal.h>
#import <Foundation/Foundation.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <stdexcept>
#include <string>

namespace bng::engine {

static const char* kMetalSsaShaderSource = R"(#include <metal_stdlib>
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

struct SimParams {
    uint numSpecies;
    uint numReactions;
    uint numObservables;
    uint numOutputPoints;
    uint batchSize;
    uint maxSimSteps;
    float tStart;
    float tEnd;
    ulong baseSeed;
};

struct TrajectoryContext {
    uint trajId;
    constant SimParams& params;
    constant float* rateConstants;
    constant uint* reactantOffsets;
    constant uint* reactantSpecies;
    constant float* reactantStoichOffsets;
    constant uint* reactChangeOffsets;
    constant uint* reactChangeSpecies;
    constant uint* prodChangeOffsets;
    constant uint* prodChangeSpecies;
    constant uint* obsOffsets;
    constant uint* obsSpecies;
    constant float* obsWeights;
    constant float* outputTimes;
    device int* y;
    device float* trajectoryObservables;
    device uint* trajectoryEventCounts;
    int local_y[64];

    float compute_prop(uint r) {
        float prop = rateConstants[r];
        uint rStart = reactantOffsets[r];
        uint rEnd = reactantOffsets[r + 1];
        for (uint i = rStart; i < rEnd; ++i) {
            int pop = (params.numSpecies <= 64) ? local_y[reactantSpecies[i]] : y[reactantSpecies[i]];
            float offset = reactantStoichOffsets[i];
            float eff = max(0.0f, (float)pop - offset);
            prop *= eff;
        }
        return prop;
    }

    void recordObservables(uint timeIdx) {
        if (params.numObservables == 0) return;
        device float* obsOut = trajectoryObservables + (trajId * params.numOutputPoints * params.numObservables + timeIdx * params.numObservables);
        for (uint g = 0; g < params.numObservables; ++g) {
            float sum = 0.0f;
            uint start = obsOffsets[g];
            uint end = obsOffsets[g + 1];
            for (uint i = start; i < end; ++i) {
                int pop = (params.numSpecies <= 64) ? local_y[obsSpecies[i]] : y[obsSpecies[i]];
                sum += obsWeights[i] * (float)pop;
            }
            obsOut[g] = sum;
        }
    }

    void run(constant int* initialSpecies) {
        if (params.numSpecies <= 64) {
            for (uint s = 0; s < params.numSpecies; ++s) {
                local_y[s] = initialSpecies[s];
            }
        } else {
            for (uint s = 0; s < params.numSpecies; ++s) {
                y[s] = initialSpecies[s];
            }
        }

        PCG32 rng;
        rng.init(123456789ULL + params.baseSeed, (ulong)trajId);

        float t = params.tStart;
        uint nextOutputTime = 0;
        uint ssaStepCount = 0;

        // Initial state output
        while (nextOutputTime < params.numOutputPoints && outputTimes[nextOutputTime] <= t + 1e-6f) {
            recordObservables(nextOutputTime);
            ++nextOutputTime;
        }

        // Direct SSA Main Loop
        while (t < params.tEnd) {
            while (nextOutputTime < params.numOutputPoints && outputTimes[nextOutputTime] <= t + 1e-6f) {
                recordObservables(nextOutputTime);
                ++nextOutputTime;
            }

            if (params.maxSimSteps > 0 && ssaStepCount >= params.maxSimSteps) {
                break;
            }

            // Pass 1: compute total propensity
            float totalPropensity = 0.0f;
            for (uint r = 0; r < params.numReactions; ++r) {
                totalPropensity += compute_prop(r);
            }

            if (totalPropensity <= 0.0f) {
                t = params.tEnd;
                break;
            }

            float r1 = rng.next_float01();
            float tau = -log(r1) / totalPropensity;

            if (t + tau > params.tEnd) {
                t = params.tEnd;
                break;
            }

            float eventTime = t + tau;
            while (nextOutputTime < params.numOutputPoints && outputTimes[nextOutputTime] < eventTime - 1e-6f) {
                recordObservables(nextOutputTime);
                ++nextOutputTime;
            }

            t = eventTime;

            // Pass 2: reaction selection
            float r2 = rng.next_float01();
            float target = r2 * totalPropensity;
            float cum = 0.0f;
            uint selected = params.numReactions - 1;
            for (uint r = 0; r < params.numReactions; ++r) {
                cum += compute_prop(r);
                if (cum >= target) {
                    selected = r;
                    break;
                }
            }

            // Fire reaction
            uint rcStart = reactChangeOffsets[selected];
            uint rcEnd = reactChangeOffsets[selected + 1];
            if (params.numSpecies <= 64) {
                for (uint i = rcStart; i < rcEnd; ++i) {
                    uint s = reactChangeSpecies[i];
                    if (local_y[s] > 0) local_y[s] -= 1;
                }
            } else {
                for (uint i = rcStart; i < rcEnd; ++i) {
                    uint s = reactChangeSpecies[i];
                    if (y[s] > 0) y[s] -= 1;
                }
            }

            uint pcStart = prodChangeOffsets[selected];
            uint pcEnd = prodChangeOffsets[selected + 1];
            if (params.numSpecies <= 64) {
                for (uint i = pcStart; i < pcEnd; ++i) {
                    uint s = prodChangeSpecies[i];
                    local_y[s] += 1;
                }
            } else {
                for (uint i = pcStart; i < pcEnd; ++i) {
                    uint s = prodChangeSpecies[i];
                    y[s] += 1;
                }
            }

            ++ssaStepCount;

            while (nextOutputTime < params.numOutputPoints && outputTimes[nextOutputTime] <= t + 1e-6f) {
                recordObservables(nextOutputTime);
                ++nextOutputTime;
            }
        }

        // Fill remaining output points through tEnd
        while (nextOutputTime < params.numOutputPoints) {
            recordObservables(nextOutputTime);
            ++nextOutputTime;
        }

        // Store final state back if using registers
        if (params.numSpecies <= 64) {
            for (uint s = 0; s < params.numSpecies; ++s) {
                y[s] = local_y[s];
            }
        }

        trajectoryEventCounts[trajId] = ssaStepCount;
    }
};

kernel void metal_batch_direct_ssa(
    constant SimParams& params [[buffer(0)]],
    constant float* rateConstants [[buffer(1)]],
    constant uint* reactantOffsets [[buffer(2)]],
    constant uint* reactantSpecies [[buffer(3)]],
    constant float* reactantStoichOffsets [[buffer(4)]],
    constant uint* reactChangeOffsets [[buffer(5)]],
    constant uint* reactChangeSpecies [[buffer(6)]],
    constant uint* prodChangeOffsets [[buffer(7)]],
    constant uint* prodChangeSpecies [[buffer(8)]],
    constant uint* obsOffsets [[buffer(9)]],
    constant uint* obsSpecies [[buffer(10)]],
    constant float* obsWeights [[buffer(11)]],
    constant float* outputTimes [[buffer(12)]],
    constant int* initialSpecies [[buffer(13)]],
    device int* trajectoryStates [[buffer(14)]],
    device float* trajectoryObservables [[buffer(15)]],
    device uint* trajectoryEventCounts [[buffer(16)]],
    uint trajId [[thread_position_in_grid]])
{
    if (trajId >= params.batchSize) return;

    device int* y = trajectoryStates + (trajId * params.numSpecies);
    TrajectoryContext ctx{
        trajId, params, rateConstants, reactantOffsets, reactantSpecies, reactantStoichOffsets,
        reactChangeOffsets, reactChangeSpecies, prodChangeOffsets, prodChangeSpecies,
        obsOffsets, obsSpecies, obsWeights, outputTimes, y, trajectoryObservables, trajectoryEventCounts,
        {}
    };
    ctx.run(initialSpecies);
}
)";

namespace {

struct MetalSimulatorImpl {
    id<MTLDevice> device = nil;
    id<MTLCommandQueue> commandQueue = nil;
    id<MTLComputePipelineState> pipelineState = nil;

    // GPU buffers holding the network structure
    id<MTLBuffer> bufRateConstants = nil;
    id<MTLBuffer> bufReactantOffsets = nil;
    id<MTLBuffer> bufReactantSpecies = nil;
    id<MTLBuffer> bufReactantStoichOffsets = nil;
    id<MTLBuffer> bufReactChangeOffsets = nil;
    id<MTLBuffer> bufReactChangeSpecies = nil;
    id<MTLBuffer> bufProdChangeOffsets = nil;
    id<MTLBuffer> bufProdChangeSpecies = nil;
    id<MTLBuffer> bufObsOffsets = nil;
    id<MTLBuffer> bufObsSpecies = nil;
    id<MTLBuffer> bufObsWeights = nil;
    id<MTLBuffer> bufInitialSpecies = nil;

    FlattenedReactionNetwork flatNet;
    double modelPrepTimeMs = 0.0;
    std::size_t staticMemoryBytes = 0;

    explicit MetalSimulatorImpl(const FlattenedReactionNetwork& fn) : flatNet(fn) {
        const auto t0 = std::chrono::high_resolution_clock::now();
        @autoreleasepool {
            device = MTLCreateSystemDefaultDevice();
            if (!device) {
                throw std::runtime_error("Metal backend: no Metal device available on this system.");
            }
            commandQueue = [device newCommandQueue];

            NSError* error = nil;
            NSString* src = [NSString stringWithUTF8String:kMetalSsaShaderSource];
            id<MTLLibrary> library = [device newLibraryWithSource:src options:nil error:&error];
            if (!library) {
                std::string errStr = error ? [[error localizedDescription] UTF8String] : "Unknown error";
                throw std::runtime_error("Metal backend: shader compile error: " + errStr);
            }

            id<MTLFunction> kernel = [library newFunctionWithName:@"metal_batch_direct_ssa"];
            pipelineState = [device newComputePipelineStateWithFunction:kernel error:&error];
            if (!pipelineState) {
                std::string errStr = error ? [[error localizedDescription] UTF8String] : "Unknown error";
                throw std::runtime_error("Metal backend: pipeline state error: " + errStr);
            }

            auto makeBuf = [&](const void* data, std::size_t bytes) -> id<MTLBuffer> {
                if (bytes == 0 || data == nullptr) {
                    staticMemoryBytes += sizeof(uint32_t);
                    return [device newBufferWithLength:sizeof(uint32_t) options:MTLResourceStorageModeShared];
                }
                staticMemoryBytes += bytes;
                return [device newBufferWithBytes:data length:bytes options:MTLResourceStorageModeShared];
            };

            bufRateConstants = makeBuf(flatNet.rateConstants.data(), flatNet.rateConstants.size() * sizeof(float));
            bufReactantOffsets = makeBuf(flatNet.reactantOffsets.data(), flatNet.reactantOffsets.size() * sizeof(uint32_t));
            bufReactantSpecies = makeBuf(flatNet.reactantSpecies.data(), flatNet.reactantSpecies.size() * sizeof(uint32_t));
            bufReactantStoichOffsets = makeBuf(flatNet.reactantStoichOffsets.data(), flatNet.reactantStoichOffsets.size() * sizeof(float));
            bufReactChangeOffsets = makeBuf(flatNet.reactChangeOffsets.data(), flatNet.reactChangeOffsets.size() * sizeof(uint32_t));
            bufReactChangeSpecies = makeBuf(flatNet.reactChangeSpecies.data(), flatNet.reactChangeSpecies.size() * sizeof(uint32_t));
            bufProdChangeOffsets = makeBuf(flatNet.prodChangeOffsets.data(), flatNet.prodChangeOffsets.size() * sizeof(uint32_t));
            bufProdChangeSpecies = makeBuf(flatNet.prodChangeSpecies.data(), flatNet.prodChangeSpecies.size() * sizeof(uint32_t));
            bufObsOffsets = makeBuf(flatNet.obsOffsets.data(), flatNet.obsOffsets.size() * sizeof(uint32_t));
            bufObsSpecies = makeBuf(flatNet.obsSpecies.data(), flatNet.obsSpecies.size() * sizeof(uint32_t));
            bufObsWeights = makeBuf(flatNet.obsWeights.data(), flatNet.obsWeights.size() * sizeof(float));
            bufInitialSpecies = makeBuf(flatNet.initialSpecies.data(), flatNet.initialSpecies.size() * sizeof(int32_t));
        }
        const auto t1 = std::chrono::high_resolution_clock::now();
        modelPrepTimeMs = std::chrono::duration<double, std::milli>(t1 - t0).count();
    }
};

class MetalSsaBackend final : public GpuSsaBackend {
public:
    explicit MetalSsaBackend(const FlattenedReactionNetwork& net)
        : net_(net), impl_(std::make_unique<MetalSimulatorImpl>(net)) {}

    const char* name() const noexcept override { return "metal"; }

    BatchSsaMetrics simulate(const FlattenedReactionNetwork& net,
                             const BatchSsaOptions& options) override {
        if (&net != &net_) {
            throw std::runtime_error(
                "Metal backend: simulate() was given a different network than the "
                "one this backend was constructed with");
        }
        return run(options);
    }

private:
    BatchSsaMetrics run(const BatchSsaOptions& options);

    std::unique_ptr<MetalSimulatorImpl> impl_;
    const FlattenedReactionNetwork& net_;
};

BatchSsaMetrics MetalSsaBackend::run(const BatchSsaOptions& options) {
    const auto tStartTotal = std::chrono::high_resolution_clock::now();

    BatchSsaMetrics metrics;
    metrics.batchSize = options.batchSize;
    metrics.modelPrepTimeMs = impl_->modelPrepTimeMs;
    metrics.observableNames = impl_->flatNet.observableNames;

    const uint32_t numPoints = static_cast<uint32_t>(options.nSteps) + 1;
    const uint32_t numSpecies = impl_->flatNet.numSpecies;
    const uint32_t numObs = impl_->flatNet.numObservables;
    const uint32_t batchSize = static_cast<uint32_t>(options.batchSize);

    std::vector<float> h_outputTimes = detail::batchOutputTimes(options);
    metrics.timePoints = h_outputTimes;

    GpuSimParams params;
    params.numSpecies = numSpecies;
    params.numReactions = impl_->flatNet.numReactions;
    params.numObservables = numObs;
    params.numOutputPoints = numPoints;
    params.batchSize = batchSize;
    params.maxSimSteps = static_cast<uint32_t>(options.maxSimSteps);
    params.tStart = static_cast<float>(options.tStart);
    params.tEnd = static_cast<float>(options.tEnd);
    params.baseSeed = options.baseSeed;

    const std::size_t stateBytes = batchSize * numSpecies * sizeof(int32_t);
    const std::size_t obsBytes = batchSize * numPoints * numObs * sizeof(float);
    const std::size_t eventBytes = batchSize * sizeof(uint32_t);
    const std::size_t timesBytes = numPoints * sizeof(float);

    metrics.memoryUsageBytes =
        impl_->staticMemoryBytes + stateBytes + obsBytes + eventBytes + timesBytes;

    // Host -> Device Transfer
    const auto tStartH2D = std::chrono::high_resolution_clock::now();

    id<MTLBuffer> bufParams = nil;
    id<MTLBuffer> bufOutputTimes = nil;
    id<MTLBuffer> bufStates = nil;
    id<MTLBuffer> bufObservables = nil;
    id<MTLBuffer> bufEventCounts = nil;

    @autoreleasepool {
        bufParams = [impl_->device newBufferWithBytes:&params length:sizeof(GpuSimParams) options:MTLResourceStorageModeShared];
        bufOutputTimes = [impl_->device newBufferWithBytes:h_outputTimes.data() length:timesBytes options:MTLResourceStorageModeShared];
        bufStates = [impl_->device newBufferWithLength:stateBytes options:MTLResourceStorageModeShared];
        bufObservables = [impl_->device newBufferWithLength:(obsBytes > 0 ? obsBytes : sizeof(float)) options:MTLResourceStorageModeShared];
        bufEventCounts = [impl_->device newBufferWithLength:eventBytes options:MTLResourceStorageModeShared];
    }

    const auto tEndH2D = std::chrono::high_resolution_clock::now();
    metrics.hostToDeviceTransferMs =
        std::chrono::duration<double, std::milli>(tEndH2D - tStartH2D).count();

    // GPU Simulation Execution
    const auto tStartSim = std::chrono::high_resolution_clock::now();

    @autoreleasepool {
        id<MTLCommandBuffer> cmdBuf = [impl_->commandQueue commandBuffer];
        id<MTLComputeCommandEncoder> enc = [cmdBuf computeCommandEncoder];

        [enc setComputePipelineState:impl_->pipelineState];
        [enc setBuffer:bufParams offset:0 atIndex:0];
        [enc setBuffer:impl_->bufRateConstants offset:0 atIndex:1];
        [enc setBuffer:impl_->bufReactantOffsets offset:0 atIndex:2];
        [enc setBuffer:impl_->bufReactantSpecies offset:0 atIndex:3];
        [enc setBuffer:impl_->bufReactantStoichOffsets offset:0 atIndex:4];
        [enc setBuffer:impl_->bufReactChangeOffsets offset:0 atIndex:5];
        [enc setBuffer:impl_->bufReactChangeSpecies offset:0 atIndex:6];
        [enc setBuffer:impl_->bufProdChangeOffsets offset:0 atIndex:7];
        [enc setBuffer:impl_->bufProdChangeSpecies offset:0 atIndex:8];
        [enc setBuffer:impl_->bufObsOffsets offset:0 atIndex:9];
        [enc setBuffer:impl_->bufObsSpecies offset:0 atIndex:10];
        [enc setBuffer:impl_->bufObsWeights offset:0 atIndex:11];
        [enc setBuffer:bufOutputTimes offset:0 atIndex:12];
        [enc setBuffer:impl_->bufInitialSpecies offset:0 atIndex:13];
        [enc setBuffer:bufStates offset:0 atIndex:14];
        [enc setBuffer:bufObservables offset:0 atIndex:15];
        [enc setBuffer:bufEventCounts offset:0 atIndex:16];

        MTLSize gridSize = MTLSizeMake(batchSize, 1, 1);
        const NSUInteger maxThreads = impl_->pipelineState.maxTotalThreadsPerThreadgroup;
        const NSUInteger threadGroupSize = (maxThreads < 64) ? maxThreads : 64;
        MTLSize tgSize = MTLSizeMake(threadGroupSize, 1, 1);

        [enc dispatchThreads:gridSize threadsPerThreadgroup:tgSize];
        [enc endEncoding];

        [cmdBuf commit];
        [cmdBuf waitUntilCompleted];
    }

    const auto tEndSim = std::chrono::high_resolution_clock::now();
    metrics.simulationTimeMs =
        std::chrono::duration<double, std::milli>(tEndSim - tStartSim).count();

    // Device -> Host Transfer
    const auto tStartD2H = std::chrono::high_resolution_clock::now();

    metrics.trajectoryEventCounts.resize(batchSize);
    std::memcpy(metrics.trajectoryEventCounts.data(), [bufEventCounts contents], eventBytes);

    metrics.finalSpecies.resize(batchSize * numSpecies);
    std::memcpy(metrics.finalSpecies.data(), [bufStates contents], stateBytes);

    std::vector<float> allObs;
    if (obsBytes > 0) {
        allObs.resize(batchSize * numPoints * numObs);
        std::memcpy(allObs.data(), [bufObservables contents], obsBytes);
        metrics.finalObservables.resize(batchSize * numObs, 0.0f);
        for (uint32_t b = 0; b < batchSize; ++b) {
            for (uint32_t g = 0; g < numObs; ++g) {
                metrics.finalObservables[b * numObs + g] =
                    allObs[b * numPoints * numObs + (numPoints - 1) * numObs + g];
            }
        }
    }

    const auto tEndD2H = std::chrono::high_resolution_clock::now();
    metrics.deviceToHostTransferMs =
        std::chrono::duration<double, std::milli>(tEndD2H - tStartD2H).count();

    const auto tEndTotal = std::chrono::high_resolution_clock::now();
    metrics.totalWallTimeMs =
        std::chrono::duration<double, std::milli>(tEndTotal - tStartTotal).count();

    uint64_t totalEvents = 0;
    for (uint32_t count : metrics.trajectoryEventCounts) {
        totalEvents += count;
    }
    metrics.totalEvents = totalEvents;

    metrics.trajectoriesPerSecSim = (options.batchSize / (metrics.simulationTimeMs / 1000.0));
    metrics.trajectoriesPerSecTotal = (options.batchSize / (metrics.totalWallTimeMs / 1000.0));
    metrics.eventsPerSecSim = (totalEvents / (metrics.simulationTimeMs / 1000.0));
    metrics.eventsPerSecTotal = (totalEvents / (metrics.totalWallTimeMs / 1000.0));

    metrics.observableMeans.resize(numPoints, std::vector<float>(numObs, 0.0f));
    metrics.observableStdDevs.resize(numPoints, std::vector<float>(numObs, 0.0f));

    if (numObs > 0) {
        const double N = static_cast<double>(batchSize);
        for (uint32_t step = 0; step < numPoints; ++step) {
            for (uint32_t g = 0; g < numObs; ++g) {
                double sum = 0.0;
                double sumSq = 0.0;
                for (uint32_t b = 0; b < batchSize; ++b) {
                    const double val = allObs[b * numPoints * numObs + step * numObs + g];
                    sum += val;
                    sumSq += val * val;
                }
                const double mean = sum / N;
                const double variance = std::max(0.0, (sumSq / N) - (mean * mean));
                metrics.observableMeans[step][g] = static_cast<float>(mean);
                metrics.observableStdDevs[step][g] = static_cast<float>(std::sqrt(variance));
            }
        }
    }
    detail::fillDoubleFields(metrics);
    return metrics;
}

} // anonymous namespace

GpuBackendProbe probeMetalBackend() {
    GpuBackendProbe probe;
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        if (!dev) {
            probe.failure = "no Metal device available on this system";
        } else {
            probe.device = [[dev name] UTF8String];
        }
    }
    return probe;
}

std::unique_ptr<GpuSsaBackend> makeMetalSsaBackend(const FlattenedReactionNetwork& net) {
    return std::make_unique<MetalSsaBackend>(net);
}

} // namespace bng::engine
