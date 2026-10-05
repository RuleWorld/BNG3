// NVIDIA CUDA backend for the batched direct-SSA kernel.
//
// One CUDA thread runs one trajectory. The kernel implements the same algorithm
// as the Metal Shading Language reference kernel
// (engine/gpu/MetalSsaBackend.mm): same PCG32 seeding and draw order, same
// two-pass propensity accumulation, same output-time recording.
//
// The two backends are NOT bit-identical. The same claim appears in
// MetalSsaBackend.mm and in docs/GPU_BATCH_SSA_EVALUATION.md, and nothing in
// this repository has ever compared the two backends. Seeding and draw order
// are integer-only and no compiler reassociates them, so trajectories provably
// agree up to the first floating-point divergence. After that they may differ,
// because:
//   * nvcc and the Metal compiler contract floating-point multiply-adds
//     independently. The propensity chain (prop *= eff), the prefix sum
//     (cum += ...) and observable accumulation (sum += ...) are all mul-add
//     shaped, and `cum` is order-sensitive, so one differing contraction can
//     change which reaction is selected and diverge the trajectory from there.
//   * -logf() lowers to nvcc's libdevice implementation while MSL's log() is a
//     different library with its own last-ulp behaviour.
// Everything here is float32, as it is in the Metal kernel, so results are
// never bit-identical to the float64 CPU pool either.
//
// Differences from the Metal kernel:
//   * the working population lives in the per-trajectory device slice rather
//     than in a 64-entry register array, because CUDA cannot keep a
//     dynamically indexed local array in registers;
//   * buffers are allocated with cudaMalloc/cudaMemcpy instead of
//     MTLResourceStorageModeShared, so device memory is not host-mapped;
//   * buffer index arithmetic is widened to size_t. The Metal shader computes
//     the same indices entirely in uint. The results agree until
//     batchSize * numOutputPoints * numObservables reaches 2^32 — about a
//     16 GiB observable buffer, past which Metal wraps and this does not.
//     Neither backend validates that product.
//   * resource lifetime: Metal uploads the static network arrays once in its
//     constructor and reuses them, whereas this backend allocates and uploads
//     all sixteen buffers inside every simulate() call. modelPrepTimeMs and
//     totalWallTimeMs are therefore NOT comparable between the two backends.
//
// When no device is visible the backend reports itself unavailable and the
// caller falls back to the CPU pool; it never approximates a result.

#include "engine/gpu/GpuSsaBackend.hpp"

#include <cuda_runtime.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

namespace bng::engine {

namespace {

const char* cudaErrorText(cudaError_t status) {
    const char* text = cudaGetErrorString(status);
    return text != nullptr ? text : "unknown CUDA error";
}

void checkCuda(cudaError_t status, const char* what) {
    if (status != cudaSuccess) {
        throw std::runtime_error(std::string("CUDA backend: ") + what + ": " +
                                 cudaErrorText(status));
    }
}

void checkCudaLast(const char* what) {
    checkCuda(cudaGetLastError(), what);
}

// Owning device allocation; released on every exit path, including throws.
class CudaBuffer {
public:
    CudaBuffer() = default;
    CudaBuffer(std::size_t bytes) { allocate(bytes); }
    ~CudaBuffer() { reset(); }

    CudaBuffer(const CudaBuffer&) = delete;
    CudaBuffer& operator=(const CudaBuffer&) = delete;

    CudaBuffer(CudaBuffer&& other) noexcept
        : ptr_(other.ptr_), bytes_(other.bytes_) {
        other.ptr_ = nullptr;
        other.bytes_ = 0;
    }

    void allocate(std::size_t bytes) {
        reset();
        // Zero-length allocations are legal in CUDA, but an empty vector gives
        // a null pointer that the kernel would still dereference, so keep one
        // byte of slack instead.
        const std::size_t request = (bytes > 0) ? bytes : 1;
        checkCuda(cudaMalloc(&ptr_, request), "cudaMalloc failed");
        bytes_ = request;
    }

    void upload(const void* data, std::size_t bytes) {
        if (bytes == 0) return;
        checkCuda(cudaMemcpy(ptr_, data, bytes, cudaMemcpyHostToDevice),
                  "host-to-device copy failed");
    }

    void download(void* data, std::size_t bytes) {
        if (bytes == 0) return;
        checkCuda(cudaMemcpy(data, ptr_, bytes, cudaMemcpyDeviceToHost),
                  "device-to-host copy failed");
    }

    void reset() {
        if (ptr_ != nullptr) {
            cudaFree(ptr_);
            ptr_ = nullptr;
            bytes_ = 0;
        }
    }

    void* get() const { return ptr_; }
    std::size_t bytes() const { return bytes_; }

private:
    void* ptr_ = nullptr;
    std::size_t bytes_ = 0;
};

// ---------------------------------------------------------------------------
// Device kernel
// ---------------------------------------------------------------------------

struct __align__(8) Pcg32 {
    unsigned long long state;
    unsigned long long inc;

    __host__ __device__ void init(unsigned long long initstate, unsigned long long initseq) {
        state = 0ULL;
        inc = (initseq << 1ULL) | 1ULL;
        step();
        state += initstate;
        step();
    }

    __host__ __device__ void step() {
        state = state * 6364136223846793005ULL + inc;
    }

    __host__ __device__ unsigned int next_u32() {
        const unsigned long long oldstate = state;
        step();
        const unsigned long long xorshifted = ((oldstate >> 18u) ^ oldstate) >> 27u;
        const unsigned int rot = static_cast<unsigned int>(oldstate >> 59u);
        return (static_cast<unsigned int>(xorshifted) >> rot) |
               (static_cast<unsigned int>(xorshifted) << ((0u - rot) & 31u));
    }

    __host__ __device__ float next_float01() {
        const unsigned int v = next_u32();
        return (static_cast<float>(v >> 8) + 1.0f) / 16777218.0f;
    }
};

__device__ __forceinline__ float computePropensity(
    unsigned int r,
    const float* __restrict__ rateConstants,
    const unsigned int* __restrict__ reactantOffsets,
    const unsigned int* __restrict__ reactantSpecies,
    const float* __restrict__ reactantStoichOffsets,
    const int* __restrict__ y
) {
    float prop = rateConstants[r];
    const unsigned int rStart = reactantOffsets[r];
    const unsigned int rEnd = reactantOffsets[r + 1];
    for (unsigned int i = rStart; i < rEnd; ++i) {
        const int pop = y[reactantSpecies[i]];
        const float offset = reactantStoichOffsets[i];
        const float eff = fmaxf(0.0f, static_cast<float>(pop) - offset);
        prop *= eff;
    }
    return prop;
}

__device__ void recordObservables(
    unsigned int trajId,
    unsigned int timeIdx,
    const GpuSimParams& params,
    const unsigned int* __restrict__ obsOffsets,
    const unsigned int* __restrict__ obsSpecies,
    const float* __restrict__ obsWeights,
    const int* __restrict__ y,
    float* __restrict__ trajectoryObservables
) {
    if (params.numObservables == 0) return;
    float* obsOut = trajectoryObservables +
        (static_cast<size_t>(trajId) * params.numOutputPoints + timeIdx) *
            params.numObservables;
    for (unsigned int g = 0; g < params.numObservables; ++g) {
        float sum = 0.0f;
        const unsigned int start = obsOffsets[g];
        const unsigned int end = obsOffsets[g + 1];
        for (unsigned int i = start; i < end; ++i) {
            sum += obsWeights[i] * static_cast<float>(y[obsSpecies[i]]);
        }
        obsOut[g] = sum;
    }
}

__global__ void cuda_batch_direct_ssa(
    GpuSimParams params,
    const float* __restrict__ rateConstants,
    const unsigned int* __restrict__ reactantOffsets,
    const unsigned int* __restrict__ reactantSpecies,
    const float* __restrict__ reactantStoichOffsets,
    const unsigned int* __restrict__ reactChangeOffsets,
    const unsigned int* __restrict__ reactChangeSpecies,
    const unsigned int* __restrict__ prodChangeOffsets,
    const unsigned int* __restrict__ prodChangeSpecies,
    const unsigned int* __restrict__ obsOffsets,
    const unsigned int* __restrict__ obsSpecies,
    const float* __restrict__ obsWeights,
    const float* __restrict__ outputTimes,
    const int* __restrict__ initialSpecies,
    int* __restrict__ trajectoryStates,
    float* __restrict__ trajectoryObservables,
    unsigned int* __restrict__ trajectoryEventCounts
) {
    const unsigned int trajId = blockIdx.x * blockDim.x + threadIdx.x;
    if (trajId >= params.batchSize) return;

    int* y = trajectoryStates + static_cast<size_t>(trajId) * params.numSpecies;
    for (unsigned int s = 0; s < params.numSpecies; ++s) {
        y[s] = initialSpecies[s];
    }

    Pcg32 rng;
    rng.init(123456789ULL + params.baseSeed, static_cast<unsigned long long>(trajId));

    float t = params.tStart;
    unsigned int nextOutputTime = 0;
    unsigned int ssaStepCount = 0;

    // Initial state output
    while (nextOutputTime < params.numOutputPoints &&
           outputTimes[nextOutputTime] <= t + 1e-6f) {
        recordObservables(trajId, nextOutputTime, params, obsOffsets, obsSpecies, obsWeights,
                          y, trajectoryObservables);
        ++nextOutputTime;
    }

    // Direct SSA main loop
    while (t < params.tEnd) {
        while (nextOutputTime < params.numOutputPoints &&
               outputTimes[nextOutputTime] <= t + 1e-6f) {
            recordObservables(trajId, nextOutputTime, params, obsOffsets, obsSpecies, obsWeights,
                              y, trajectoryObservables);
            ++nextOutputTime;
        }

        if (params.maxSimSteps > 0 && ssaStepCount >= params.maxSimSteps) {
            break;
        }

        // Pass 1: compute total propensity
        float totalPropensity = 0.0f;
        for (unsigned int r = 0; r < params.numReactions; ++r) {
            totalPropensity += computePropensity(r, rateConstants,
                                                 reactantOffsets, reactantSpecies,
                                                 reactantStoichOffsets, y);
        }

        if (totalPropensity <= 0.0f) {
            t = params.tEnd;
            break;
        }

        const float r1 = rng.next_float01();
        const float tau = -logf(r1) / totalPropensity;

        if (t + tau > params.tEnd) {
            t = params.tEnd;
            break;
        }

        const float eventTime = t + tau;
        while (nextOutputTime < params.numOutputPoints &&
               outputTimes[nextOutputTime] < eventTime - 1e-6f) {
            recordObservables(trajId, nextOutputTime, params, obsOffsets, obsSpecies, obsWeights,
                              y, trajectoryObservables);
            ++nextOutputTime;
        }

        t = eventTime;

        // Pass 2: reaction selection
        const float r2 = rng.next_float01();
        const float target = r2 * totalPropensity;
        float cum = 0.0f;
        unsigned int selected = params.numReactions - 1;
        for (unsigned int r = 0; r < params.numReactions; ++r) {
            cum += computePropensity(r, rateConstants, reactantOffsets,
                                     reactantSpecies, reactantStoichOffsets, y);
            if (cum >= target) {
                selected = r;
                break;
            }
        }

        // Fire reaction
        const unsigned int rcStart = reactChangeOffsets[selected];
        const unsigned int rcEnd = reactChangeOffsets[selected + 1];
        for (unsigned int i = rcStart; i < rcEnd; ++i) {
            const unsigned int s = reactChangeSpecies[i];
            if (y[s] > 0) y[s] -= 1;
        }

        const unsigned int pcStart = prodChangeOffsets[selected];
        const unsigned int pcEnd = prodChangeOffsets[selected + 1];
        for (unsigned int i = pcStart; i < pcEnd; ++i) {
            y[prodChangeSpecies[i]] += 1;
        }

        ++ssaStepCount;

        while (nextOutputTime < params.numOutputPoints &&
               outputTimes[nextOutputTime] <= t + 1e-6f) {
            recordObservables(trajId, nextOutputTime, params, obsOffsets, obsSpecies, obsWeights,
                              y, trajectoryObservables);
            ++nextOutputTime;
        }
    }

    // Fill remaining output points through tEnd
    while (nextOutputTime < params.numOutputPoints) {
        recordObservables(trajId, nextOutputTime, params, obsOffsets, obsSpecies, obsWeights,
                          y, trajectoryObservables);
        ++nextOutputTime;
    }

    trajectoryEventCounts[trajId] = ssaStepCount;
}

// ---------------------------------------------------------------------------
// Host-side backend
// ---------------------------------------------------------------------------

class CudaSsaBackend final : public GpuSsaBackend {
public:
    explicit CudaSsaBackend(const FlattenedReactionNetwork& net) : net_(net) {
        int deviceCount = 0;
        const cudaError_t status = cudaGetDeviceCount(&deviceCount);
        if (status != cudaSuccess || deviceCount == 0) {
            throw std::runtime_error(
                "CUDA backend: no CUDA device available on this system");
        }
        checkCuda(cudaSetDevice(0), "cudaSetDevice failed");
    }

    const char* name() const noexcept override { return "cuda"; }

    BatchSsaMetrics simulate(const FlattenedReactionNetwork& net,
                             const BatchSsaOptions& options) override;

private:
    const FlattenedReactionNetwork& net_;
};

BatchSsaMetrics CudaSsaBackend::simulate(const FlattenedReactionNetwork& net,
                                         const BatchSsaOptions& options) {
    if (&net != &net_) {
        throw std::runtime_error(
            "CUDA backend: simulate() was given a different network than the one this "
            "backend was constructed with");
    }

    const auto tStartTotal = std::chrono::high_resolution_clock::now();

    BatchSsaMetrics metrics;
    metrics.batchSize = options.batchSize;
    metrics.observableNames = net.observableNames;

    const std::size_t numPoints = static_cast<std::size_t>(options.nSteps) + 1;
    const std::size_t numSpecies = net.numSpecies;
    const std::size_t numObs = net.numObservables;
    const std::size_t batchSize = options.batchSize;

    if (batchSize > UINT32_MAX || numPoints > UINT32_MAX) {
        throw std::runtime_error("CUDA backend: batch exceeds addressable trajectory count");
    }

    std::vector<float> outputTimes = detail::batchOutputTimes(options);
    metrics.timePoints = outputTimes;

    GpuSimParams params;
    params.numSpecies = static_cast<uint32_t>(numSpecies);
    params.numReactions = net.numReactions;
    params.numObservables = static_cast<uint32_t>(numObs);
    params.numOutputPoints = static_cast<uint32_t>(numPoints);
    params.batchSize = static_cast<uint32_t>(batchSize);
    params.maxSimSteps = static_cast<uint32_t>(options.maxSimSteps);
    params.tStart = static_cast<float>(options.tStart);
    params.tEnd = static_cast<float>(options.tEnd);
    params.baseSeed = options.baseSeed;

    const std::size_t stateBytes = batchSize * numSpecies * sizeof(int32_t);
    const std::size_t obsBytes = batchSize * numPoints * numObs * sizeof(float);
    const std::size_t eventBytes = batchSize * sizeof(uint32_t);
    const std::size_t timesBytes = numPoints * sizeof(float);

    const auto tStartPrep = std::chrono::high_resolution_clock::now();
    CudaBuffer dRateConstants(net.rateConstants.size() * sizeof(float));
    CudaBuffer dReactantOffsets(net.reactantOffsets.size() * sizeof(uint32_t));
    CudaBuffer dReactantSpecies(net.reactantSpecies.size() * sizeof(uint32_t));
    CudaBuffer dReactantStoichOffsets(net.reactantStoichOffsets.size() * sizeof(float));
    CudaBuffer dReactChangeOffsets(net.reactChangeOffsets.size() * sizeof(uint32_t));
    CudaBuffer dReactChangeSpecies(net.reactChangeSpecies.size() * sizeof(uint32_t));
    CudaBuffer dProdChangeOffsets(net.prodChangeOffsets.size() * sizeof(uint32_t));
    CudaBuffer dProdChangeSpecies(net.prodChangeSpecies.size() * sizeof(uint32_t));
    CudaBuffer dObsOffsets(net.obsOffsets.size() * sizeof(uint32_t));
    CudaBuffer dObsSpecies(net.obsSpecies.size() * sizeof(uint32_t));
    CudaBuffer dObsWeights(net.obsWeights.size() * sizeof(float));
    CudaBuffer dInitialSpecies(net.initialSpecies.size() * sizeof(int32_t));
    CudaBuffer dOutputTimes(timesBytes);
    CudaBuffer dStates(stateBytes);
    CudaBuffer dObservables(obsBytes);
    CudaBuffer dEventCounts(eventBytes);
    const auto tEndPrep = std::chrono::high_resolution_clock::now();
    metrics.modelPrepTimeMs =
        std::chrono::duration<double, std::milli>(tEndPrep - tStartPrep).count();

    const std::size_t staticBytes = dRateConstants.bytes() + dReactantOffsets.bytes() +
        dReactantSpecies.bytes() + dReactantStoichOffsets.bytes() +
        dReactChangeOffsets.bytes() + dReactChangeSpecies.bytes() +
        dProdChangeOffsets.bytes() + dProdChangeSpecies.bytes() + dObsOffsets.bytes() +
        dObsSpecies.bytes() + dObsWeights.bytes() + dInitialSpecies.bytes();
    metrics.memoryUsageBytes =
        staticBytes + dOutputTimes.bytes() + dStates.bytes() + dObservables.bytes() +
        dEventCounts.bytes();

    // Host -> Device
    const auto tStartH2D = std::chrono::high_resolution_clock::now();
    dRateConstants.upload(net.rateConstants.data(), net.rateConstants.size() * sizeof(float));
    dReactantOffsets.upload(net.reactantOffsets.data(), net.reactantOffsets.size() * sizeof(uint32_t));
    dReactantSpecies.upload(net.reactantSpecies.data(), net.reactantSpecies.size() * sizeof(uint32_t));
    dReactantStoichOffsets.upload(net.reactantStoichOffsets.data(), net.reactantStoichOffsets.size() * sizeof(float));
    dReactChangeOffsets.upload(net.reactChangeOffsets.data(), net.reactChangeOffsets.size() * sizeof(uint32_t));
    dReactChangeSpecies.upload(net.reactChangeSpecies.data(), net.reactChangeSpecies.size() * sizeof(uint32_t));
    dProdChangeOffsets.upload(net.prodChangeOffsets.data(), net.prodChangeOffsets.size() * sizeof(uint32_t));
    dProdChangeSpecies.upload(net.prodChangeSpecies.data(), net.prodChangeSpecies.size() * sizeof(uint32_t));
    dObsOffsets.upload(net.obsOffsets.data(), net.obsOffsets.size() * sizeof(uint32_t));
    dObsSpecies.upload(net.obsSpecies.data(), net.obsSpecies.size() * sizeof(uint32_t));
    dObsWeights.upload(net.obsWeights.data(), net.obsWeights.size() * sizeof(float));
    dInitialSpecies.upload(net.initialSpecies.data(), net.initialSpecies.size() * sizeof(int32_t));
    dOutputTimes.upload(outputTimes.data(), timesBytes);
    checkCudaLast("device setup failed");
    const auto tEndH2D = std::chrono::high_resolution_clock::now();
    metrics.hostToDeviceTransferMs =
        std::chrono::duration<double, std::milli>(tEndH2D - tStartH2D).count();

    // Launch
    const auto tStartSim = std::chrono::high_resolution_clock::now();
    const unsigned int blockSize = 64;
    const unsigned int blocks = static_cast<unsigned int>((batchSize + blockSize - 1) / blockSize);
    cuda_batch_direct_ssa<<<blocks, blockSize>>>(
        params,
        static_cast<const float*>(dRateConstants.get()),
        static_cast<const unsigned int*>(dReactantOffsets.get()),
        static_cast<const unsigned int*>(dReactantSpecies.get()),
        static_cast<const float*>(dReactantStoichOffsets.get()),
        static_cast<const unsigned int*>(dReactChangeOffsets.get()),
        static_cast<const unsigned int*>(dReactChangeSpecies.get()),
        static_cast<const unsigned int*>(dProdChangeOffsets.get()),
        static_cast<const unsigned int*>(dProdChangeSpecies.get()),
        static_cast<const unsigned int*>(dObsOffsets.get()),
        static_cast<const unsigned int*>(dObsSpecies.get()),
        static_cast<const float*>(dObsWeights.get()),
        static_cast<const float*>(dOutputTimes.get()),
        static_cast<const int*>(dInitialSpecies.get()),
        static_cast<int*>(dStates.get()),
        static_cast<float*>(dObservables.get()),
        static_cast<unsigned int*>(dEventCounts.get()));
    checkCudaLast("kernel launch failed");
    checkCuda(cudaDeviceSynchronize(), "kernel execution failed");
    const auto tEndSim = std::chrono::high_resolution_clock::now();
    metrics.simulationTimeMs =
        std::chrono::duration<double, std::milli>(tEndSim - tStartSim).count();

    // Device -> Host
    const auto tStartD2H = std::chrono::high_resolution_clock::now();
    metrics.trajectoryEventCounts.resize(batchSize);
    dEventCounts.download(metrics.trajectoryEventCounts.data(), eventBytes);

    metrics.finalSpecies.resize(batchSize * numSpecies);
    dStates.download(metrics.finalSpecies.data(), stateBytes);

    std::vector<float> allObs;
    if (obsBytes > 0) {
        allObs.resize(batchSize * numPoints * numObs);
        dObservables.download(allObs.data(), obsBytes);
        metrics.finalObservables.resize(batchSize * numObs, 0.0f);
        for (std::size_t b = 0; b < batchSize; ++b) {
            for (std::size_t g = 0; g < numObs; ++g) {
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
        for (std::size_t step = 0; step < numPoints; ++step) {
            for (std::size_t g = 0; g < numObs; ++g) {
                double sum = 0.0;
                double sumSq = 0.0;
                for (std::size_t b = 0; b < batchSize; ++b) {
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

GpuBackendProbe probeCudaBackend() {
    GpuBackendProbe probe;
    int deviceCount = 0;
    const cudaError_t status = cudaGetDeviceCount(&deviceCount);
    if (status != cudaSuccess) {
        probe.failure = std::string("CUDA runtime error: ") + cudaErrorText(status);
        return probe;
    }
    if (deviceCount == 0) {
        probe.failure = "no CUDA device available on this system";
        return probe;
    }
    cudaDeviceProp props{};
    if (cudaGetDeviceProperties(&props, 0) != cudaSuccess) {
        probe.failure = "CUDA device present but its properties could not be read";
        return probe;
    }
    probe.device = props.name;
    return probe;
}

std::unique_ptr<GpuSsaBackend> makeCudaSsaBackend(const FlattenedReactionNetwork& net) {
    return std::make_unique<CudaSsaBackend>(net);
}

} // namespace bng::engine
