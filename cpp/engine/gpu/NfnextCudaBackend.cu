#include "engine/gpu/NfnextUnaryStateKernel.hpp"

#include <cuda_runtime.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace bng::engine::detail {
namespace {

void checkCuda(cudaError_t err, const char* context) {
    if (err != cudaSuccess) {
        throw std::runtime_error(std::string("NFnext CUDA backend: ") + context + ": " +
                                 cudaGetErrorString(err));
    }
}

class DeviceBuffer {
public:
    DeviceBuffer() = default;
    ~DeviceBuffer() { reset(); }

    DeviceBuffer(const DeviceBuffer&) = delete;
    DeviceBuffer& operator=(const DeviceBuffer&) = delete;

    void allocate(std::size_t bytes) {
        reset();
        const std::size_t request = bytes > 0 ? bytes : 1;
        checkCuda(cudaMalloc(&ptr_, request), "cudaMalloc failed");
        bytes_ = request;
    }

    void allocateAndUpload(const void* data, std::size_t bytes) {
        allocate(bytes);
        if (bytes > 0 && data != nullptr) {
            checkCuda(cudaMemcpy(ptr_, data, bytes, cudaMemcpyHostToDevice),
                      "host-to-device copy failed");
        }
    }

    void allocateZeroed(std::size_t bytes) {
        allocate(bytes);
        checkCuda(cudaMemset(ptr_, 0, bytes_), "cudaMemset failed");
    }

    void download(void* data, std::size_t bytes) const {
        if (bytes == 0 || data == nullptr) return;
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

    template <typename T>
    T* as() const {
        return static_cast<T*>(ptr_);
    }

private:
    void* ptr_{nullptr};
    std::size_t bytes_{0};
};

struct CudaEventGuard {
    cudaEvent_t event{nullptr};
    CudaEventGuard() { checkCuda(cudaEventCreate(&event), "cudaEventCreate failed"); }
    ~CudaEventGuard() {
        if (event != nullptr) cudaEventDestroy(event);
    }
    CudaEventGuard(const CudaEventGuard&) = delete;
    CudaEventGuard& operator=(const CudaEventGuard&) = delete;
};

struct __align__(8) Pcg32 {
    unsigned long long state;
    unsigned long long inc;

    __device__ void init(unsigned long long initstate, unsigned long long initseq) {
        state = 0ULL;
        inc = (initseq << 1ULL) | 1ULL;
        step();
        state += initstate;
        step();
    }

    __device__ void step() {
        state = state * 6364136223846793005ULL + inc;
    }

    __device__ unsigned int nextU32() {
        const unsigned long long oldstate = state;
        step();
        const unsigned long long xorshifted = ((oldstate >> 18u) ^ oldstate) >> 27u;
        const unsigned int rot = static_cast<unsigned int>(oldstate >> 59u);
        return (static_cast<unsigned int>(xorshifted) >> rot) |
               (static_cast<unsigned int>(xorshifted) << ((0u - rot) & 31u));
    }

    __device__ float nextFloat01() {
        const unsigned int v = nextU32();
        return (static_cast<float>(v >> 8) + 1.0f) / 16777218.0f;
    }
};

__device__ __forceinline__ unsigned long long splitmix64(unsigned long long value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30ULL)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27ULL)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31ULL);
}

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
static_assert(sizeof(SimParams) == 40, "SimParams ABI mismatch");

__device__ void scheduleForState(
    std::uint32_t index,
    std::int32_t state,
    float now,
    const std::uint32_t* __restrict__ transitionOffsets,
    const std::int32_t* __restrict__ transitionDestinations,
    const float* __restrict__ transitionRates,
    float* __restrict__ nextTimes,
    std::int32_t* __restrict__ nextDestinations,
    unsigned long long* __restrict__ rngStates,
    const unsigned long long* __restrict__ rngIncrements)
{
    Pcg32 rng;
    rng.state = rngStates[index];
    rng.inc = rngIncrements[index];
    const std::uint32_t begin = transitionOffsets[static_cast<std::uint32_t>(state)];
    const std::uint32_t end = transitionOffsets[static_cast<std::uint32_t>(state) + 1u];
    float total = 0.0f;
    for (std::uint32_t i = begin; i < end; ++i) {
        total += transitionRates[i];
    }
    if (!(total > 0.0f)) {
        nextTimes[index] = INFINITY;
        nextDestinations[index] = -1;
        rngStates[index] = rng.state;
        return;
    }
    const float waitDraw = rng.nextFloat01();
    const float target = rng.nextFloat01() * total;
    const float wait = -logf(waitDraw) / total;
    float cumulative = 0.0f;
    std::int32_t destination = transitionDestinations[end - 1u];
    for (std::uint32_t i = begin; i < end; ++i) {
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

__global__ void nfnextUnaryStateBatchKernel(
    SimParams params,
    const std::uint32_t* __restrict__ transitionOffsets,
    const std::int32_t* __restrict__ transitionDestinations,
    const float* __restrict__ transitionRates,
    const std::int32_t* __restrict__ initialStates,
    const std::int32_t* __restrict__ observableStates,
    const float* __restrict__ sampleTimes,
    std::int32_t* __restrict__ particleStates,
    float* __restrict__ outputs,
    unsigned long long* __restrict__ eventCounts,
    std::uint32_t* __restrict__ errorFlags,
    float* __restrict__ nextTimes,
    std::int32_t* __restrict__ nextDestinations,
    unsigned long long* __restrict__ rngStates,
    unsigned long long* __restrict__ rngIncrements)
{
    const std::uint32_t trajectory = blockIdx.x * blockDim.x + threadIdx.x;
    if (trajectory >= params.batchSize) return;

    const std::uint32_t particleBase = trajectory * params.numParticles;
    for (std::uint32_t particle = 0; particle < params.numParticles; ++particle) {
        const std::uint32_t index = particleBase + particle;
        particleStates[index] = initialStates[particle];
        Pcg32 rng;
        const unsigned long long stream =
            static_cast<unsigned long long>(trajectory) *
                static_cast<unsigned long long>(params.numParticles) +
            static_cast<unsigned long long>(particle);
        const unsigned long long key = params.baseSeed + stream * 2ULL;
        rng.init(splitmix64(key), splitmix64(key + 1ULL));
        rngStates[index] = rng.state;
        rngIncrements[index] = rng.inc;
        scheduleForState(index, particleStates[index], 0.0f,
                         transitionOffsets, transitionDestinations, transitionRates,
                         nextTimes, nextDestinations, rngStates, rngIncrements);
    }

    unsigned long long events = 0ULL;
    for (std::uint32_t output = 0; output < params.numOutputs; ++output) {
        const float sampleTime = sampleTimes[output];
        for (;;) {
            float earliest = INFINITY;
            std::int32_t selected = -1;
            for (std::uint32_t particle = 0; particle < params.numParticles; ++particle) {
                const std::uint32_t index = particleBase + particle;
                if (nextTimes[index] < earliest) {
                    earliest = nextTimes[index];
                    selected = static_cast<std::int32_t>(particle);
                }
            }
            if (selected < 0 || earliest > sampleTime) break;
            if (events >= static_cast<unsigned long long>(params.maxEvents)) {
                errorFlags[trajectory] = 1U;
                eventCounts[trajectory] = events;
                return;
            }
            const std::uint32_t index = particleBase + static_cast<std::uint32_t>(selected);
            particleStates[index] = nextDestinations[index];
            ++events;
            scheduleForState(index, particleStates[index], earliest,
                             transitionOffsets, transitionDestinations, transitionRates,
                             nextTimes, nextDestinations, rngStates, rngIncrements);
        }
        for (std::uint32_t observable = 0; observable < params.numObservables; ++observable) {
            std::uint32_t count = 0U;
            const std::int32_t targetState = observableStates[observable];
            for (std::uint32_t particle = 0; particle < params.numParticles; ++particle) {
                const std::int32_t state = particleStates[particleBase + particle];
                if (targetState < 0 || state == targetState) ++count;
            }
            const std::size_t outIdx =
                (static_cast<std::size_t>(trajectory) * params.numOutputs + output) *
                    params.numObservables +
                observable;
            outputs[outIdx] = static_cast<float>(count);
        }
    }
    eventCounts[trajectory] = events;
}

std::size_t checkedBytes(std::size_t count, std::size_t itemSize) {
    if (count != 0 && itemSize > std::numeric_limits<std::size_t>::max() / count) {
        throw std::runtime_error("NFnext CUDA backend: device buffer size overflow");
    }
    return count * itemSize;
}

} // namespace

NfnextDeviceOutput simulateNfnextUnaryStateCuda(
    const NfnextUnaryStatePlan& plan, const NfnextGpuRequest& request) {
    const auto wallStart = std::chrono::steady_clock::now();
    if (request.sampleTimes.size() > std::numeric_limits<std::uint32_t>::max() ||
        plan.observableNames.size() > std::numeric_limits<std::uint32_t>::max() ||
        plan.transitionRates.size() > std::numeric_limits<std::uint32_t>::max() ||
        plan.initialStates.size() > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("NFnext CUDA backend: model dimensions exceed kernel index capacity");
    }

    int deviceId = 0;
    checkCuda(cudaGetDevice(&deviceId), "cudaGetDevice failed");
    cudaDeviceProp props{};
    checkCuda(cudaGetDeviceProperties(&props, deviceId), "cudaGetDeviceProperties failed");

    const auto batchSize = static_cast<std::uint32_t>(request.batchSize);
    const auto particleCount = static_cast<std::uint32_t>(plan.initialStates.size());
    const auto outputCount = static_cast<std::uint32_t>(request.sampleTimes.size());
    const auto observableCount = static_cast<std::uint32_t>(plan.observableNames.size());
    const std::size_t particleSlots = checkedBytes(request.batchSize, plan.initialStates.size());
    if (particleSlots > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("NFnext CUDA backend: particle workspace exceeds kernel index capacity");
    }
    const std::size_t outputValues = checkedBytes(
        checkedBytes(request.batchSize, request.sampleTimes.size()),
        plan.observableNames.size());

    const std::size_t offsetBytes = checkedBytes(plan.transitionOffsets.size(), sizeof(std::uint32_t));
    const std::size_t destBytes = checkedBytes(plan.transitionDestinations.size(), sizeof(std::int32_t));
    const std::size_t rateBytes = checkedBytes(plan.transitionRates.size(), sizeof(float));
    const std::size_t initBytes = checkedBytes(plan.initialStates.size(), sizeof(std::int32_t));
    const std::size_t obsStateBytes = checkedBytes(plan.observableStates.size(), sizeof(std::int32_t));
    const std::size_t stateBytes = checkedBytes(particleSlots, sizeof(std::int32_t));
    const std::size_t timeBytes = checkedBytes(request.sampleTimes.size(), sizeof(float));
    const std::size_t outputBytes = checkedBytes(outputValues, sizeof(float));
    const std::size_t eventBytes = checkedBytes(request.batchSize, sizeof(unsigned long long));
    const std::size_t flagBytes = checkedBytes(request.batchSize, sizeof(std::uint32_t));
    const std::size_t nextTimeBytes = checkedBytes(particleSlots, sizeof(float));
    const std::size_t nextDestBytes = checkedBytes(particleSlots, sizeof(std::int32_t));
    const std::size_t rngBytes = checkedBytes(particleSlots, sizeof(unsigned long long));

    std::vector<float> sampleTimes;
    sampleTimes.reserve(request.sampleTimes.size());
    for (const double time : request.sampleTimes) {
        sampleTimes.push_back(static_cast<float>(time));
    }

    SimParams params{};
    params.numStates = static_cast<std::uint32_t>(plan.transitionOffsets.size() - 1);
    params.numTransitions = static_cast<std::uint32_t>(plan.transitionRates.size());
    params.numObservables = observableCount;
    params.numOutputs = outputCount;
    params.batchSize = batchSize;
    params.numParticles = particleCount;
    params.maxEvents = static_cast<std::uint32_t>(request.maxEvents);
    params.baseSeed = request.seed;

    DeviceBuffer dOffsets;
    DeviceBuffer dDestinations;
    DeviceBuffer dRates;
    DeviceBuffer dInitialStates;
    DeviceBuffer dObservableStates;
    DeviceBuffer dSampleTimes;
    DeviceBuffer dParticleStates;
    DeviceBuffer dOutputs;
    DeviceBuffer dEventCounts;
    DeviceBuffer dErrorFlags;
    DeviceBuffer dNextTimes;
    DeviceBuffer dNextDestinations;
    DeviceBuffer dRngStates;
    DeviceBuffer dRngIncrements;

    dOffsets.allocateAndUpload(plan.transitionOffsets.data(), offsetBytes);
    dDestinations.allocateAndUpload(plan.transitionDestinations.data(), destBytes);
    dRates.allocateAndUpload(plan.transitionRates.data(), rateBytes);
    dInitialStates.allocateAndUpload(plan.initialStates.data(), initBytes);
    dObservableStates.allocateAndUpload(plan.observableStates.data(), obsStateBytes);
    dSampleTimes.allocateAndUpload(sampleTimes.data(), timeBytes);
    dParticleStates.allocate(stateBytes);
    dOutputs.allocate(outputBytes);
    dEventCounts.allocate(eventBytes);
    dErrorFlags.allocateZeroed(flagBytes);
    dNextTimes.allocate(nextTimeBytes);
    dNextDestinations.allocate(nextDestBytes);
    dRngStates.allocate(rngBytes);
    dRngIncrements.allocate(rngBytes);

    CudaEventGuard stopEvent;
    const auto setupEnd = std::chrono::steady_clock::now();

    const auto dispatchStart = std::chrono::steady_clock::now();
    const unsigned int blockSize = 64u;
    const unsigned int gridSize = (batchSize + blockSize - 1u) / blockSize;
    nfnextUnaryStateBatchKernel<<<gridSize, blockSize>>>(
        params,
        dOffsets.as<std::uint32_t>(),
        dDestinations.as<std::int32_t>(),
        dRates.as<float>(),
        dInitialStates.as<std::int32_t>(),
        dObservableStates.as<std::int32_t>(),
        dSampleTimes.as<float>(),
        dParticleStates.as<std::int32_t>(),
        dOutputs.as<float>(),
        dEventCounts.as<unsigned long long>(),
        dErrorFlags.as<std::uint32_t>(),
        dNextTimes.as<float>(),
        dNextDestinations.as<std::int32_t>(),
        dRngStates.as<unsigned long long>(),
        dRngIncrements.as<unsigned long long>());
    checkCuda(cudaGetLastError(), "kernel launch failed");
    checkCuda(cudaEventRecord(stopEvent.event), "cudaEventRecord failed");
    checkCuda(cudaEventSynchronize(stopEvent.event), "kernel synchronization failed");
    const auto dispatchEnd = std::chrono::steady_clock::now();

    std::vector<std::uint32_t> flags(request.batchSize, 0u);
    dErrorFlags.download(flags.data(), flagBytes);
    for (std::size_t trajectory = 0; trajectory < request.batchSize; ++trajectory) {
        if (flags[trajectory] != 0u) {
            throw std::runtime_error("NFnext CUDA backend: max_events exceeded in trajectory " +
                                     std::to_string(trajectory));
        }
    }

    static_assert(sizeof(unsigned long long) == sizeof(std::uint64_t),
                  "unsigned long long width mismatch");
    NfnextDeviceOutput output;
    output.device = props.name;
    output.observables.resize(outputValues);
    dOutputs.download(output.observables.data(), outputBytes);
    output.eventCounts.resize(request.batchSize);
    dEventCounts.download(output.eventCounts.data(), eventBytes);
    output.dispatchWaitTimeMs =
        std::chrono::duration<double, std::milli>(dispatchEnd - dispatchStart).count();
    output.setupTimeMs =
        std::chrono::duration<double, std::milli>(setupEnd - wallStart).count();
    output.deviceMemoryBytes =
        sizeof(params) + offsetBytes + destBytes + rateBytes + initBytes + obsStateBytes +
        timeBytes + stateBytes + outputBytes + eventBytes + flagBytes + nextTimeBytes +
        nextDestBytes + 2 * rngBytes;
    output.wallTimeMs =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - wallStart)
            .count();
    return output;
}

} // namespace bng::engine::detail
