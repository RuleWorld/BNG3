#include "engine/gpu/NfnextUnaryStateKernel.hpp"
#include "engine/gpu/NfnextGraphKernel.hpp"

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

namespace {

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
static_assert(sizeof(GraphSimParams) == 48, "GraphSimParams ABI mismatch");

__device__ __forceinline__ std::uint32_t nextBounded(Pcg32& rng, std::uint32_t bound) {
    if (bound <= 1u) return 0u;
    return rng.nextU32() % bound;
}

__device__ bool nodeMatchesConstraintsCuda(
    std::uint32_t pBase,
    std::uint32_t maxSites,
    std::int32_t mol,
    std::uint32_t cOff,
    std::uint32_t cCnt,
    const GpuSiteConstraint* __restrict__ constraints,
    const std::int32_t* __restrict__ siteState,
    const std::int32_t* __restrict__ siteBondMol)
{
    const std::uint32_t sBase = (pBase + static_cast<std::uint32_t>(mol)) * maxSites;
    for (std::uint32_t i = 0; i < cCnt; ++i) {
        const GpuSiteConstraint c = constraints[cOff + i];
        const std::uint32_t idx = sBase + static_cast<std::uint32_t>(c.site);
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

__device__ bool particleMatchesListCuda(
    std::uint32_t pBase,
    std::uint32_t maxSites,
    std::int32_t mol,
    GpuMatchListDef ml,
    const GpuSiteConstraint* __restrict__ constraints,
    const std::int8_t* __restrict__ alive,
    const std::int32_t* __restrict__ molType,
    const std::int32_t* __restrict__ siteState,
    const std::int32_t* __restrict__ siteBondMol,
    const std::int32_t* __restrict__ siteBondSite)
{
    if (alive[pBase + static_cast<std::uint32_t>(mol)] == 0) return false;
    if (molType[pBase + static_cast<std::uint32_t>(mol)] != ml.anchorType) return false;
    if (!nodeMatchesConstraintsCuda(pBase, maxSites, mol,
                                    ml.node0ConstraintOffset, ml.node0ConstraintCount,
                                    constraints, siteState, siteBondMol)) {
        return false;
    }
    if (ml.partnerType < 0) return true;
    const std::uint32_t sIdx = (pBase + static_cast<std::uint32_t>(mol)) * maxSites +
                               static_cast<std::uint32_t>(ml.bondSite0);
    const std::int32_t partner = siteBondMol[sIdx];
    if (partner < 0 || partner == mol) return false;
    if (siteBondSite[sIdx] != static_cast<std::int32_t>(ml.bondSite1)) return false;
    if (alive[pBase + static_cast<std::uint32_t>(partner)] == 0) return false;
    if (molType[pBase + static_cast<std::uint32_t>(partner)] != ml.partnerType) return false;
    return nodeMatchesConstraintsCuda(pBase, maxSites, partner,
                                      ml.node1ConstraintOffset, ml.node1ConstraintCount,
                                      constraints, siteState, siteBondMol);
}

__device__ void updateMatchListForMolCuda(
    std::uint32_t traj,
    GraphSimParams params,
    std::uint32_t mlIdx,
    std::int32_t mol,
    bool shouldContain,
    const std::uint32_t* __restrict__ typeOffsets,
    const GpuMatchListDef* __restrict__ matchLists,
    std::int32_t* __restrict__ mlItems,
    std::int32_t* __restrict__ mlPos,
    std::uint32_t* __restrict__ mlCounts)
{
    const GpuMatchListDef ml = matchLists[mlIdx];
    const std::uint32_t localIdx =
        static_cast<std::uint32_t>(mol) - typeOffsets[static_cast<std::uint32_t>(ml.anchorType)];
    const std::uint32_t mlBase = traj * params.totalMatchListSlots + ml.listOffset;
    const std::uint32_t cntIdx = traj * params.numMatchLists + mlIdx;
    const std::int32_t pos = mlPos[mlBase + localIdx];
    if (shouldContain) {
        if (pos < 0) {
            const std::uint32_t n = mlCounts[cntIdx];
            mlItems[mlBase + n] = mol;
            mlPos[mlBase + localIdx] = static_cast<std::int32_t>(n);
            mlCounts[cntIdx] = n + 1u;
        }
    } else {
        if (pos >= 0) {
            const std::uint32_t lastIdx = mlCounts[cntIdx] - 1u;
            const std::int32_t lastMol = mlItems[mlBase + lastIdx];
            mlItems[mlBase + static_cast<std::uint32_t>(pos)] = lastMol;
            const std::uint32_t lastLocal =
                static_cast<std::uint32_t>(lastMol) -
                typeOffsets[static_cast<std::uint32_t>(ml.anchorType)];
            mlPos[mlBase + lastLocal] = pos;
            mlPos[mlBase + localIdx] = -1;
            mlCounts[cntIdx] = lastIdx;
        }
    }
}

__device__ void refreshMoleculeCuda(
    std::uint32_t traj,
    std::uint32_t pBase,
    std::int32_t mol,
    std::int32_t slotType,
    GraphSimParams params,
    const std::uint32_t* __restrict__ typeOffsets,
    const GpuSiteConstraint* __restrict__ constraints,
    const GpuMatchListDef* __restrict__ matchLists,
    const std::int8_t* __restrict__ alive,
    const std::int32_t* __restrict__ molType,
    const std::int32_t* __restrict__ siteState,
    const std::int32_t* __restrict__ siteBondMol,
    const std::int32_t* __restrict__ siteBondSite,
    std::int32_t* __restrict__ mlItems,
    std::int32_t* __restrict__ mlPos,
    std::uint32_t* __restrict__ mlCounts)
{
    for (std::uint32_t mlIdx = 0; mlIdx < params.numMatchLists; ++mlIdx) {
        const GpuMatchListDef ml = matchLists[mlIdx];
        if (ml.anchorType != slotType) continue;
        const bool ok = particleMatchesListCuda(
            pBase, params.maxSites, mol, ml, constraints,
            alive, molType, siteState, siteBondMol, siteBondSite);
        updateMatchListForMolCuda(
            traj, params, mlIdx, mol, ok, typeOffsets, matchLists,
            mlItems, mlPos, mlCounts);
    }
}

__device__ std::int32_t findSlotTypeCuda(
    std::int32_t mol,
    std::uint32_t numTypes,
    const std::uint32_t* __restrict__ typeOffsets,
    const std::uint32_t* __restrict__ typeCaps)
{
    const std::uint32_t m = static_cast<std::uint32_t>(mol);
    for (std::uint32_t t = 0; t < numTypes; ++t) {
        if (m >= typeOffsets[t] && m < typeOffsets[t] + typeCaps[t]) {
            return static_cast<std::int32_t>(t);
        }
    }
    return -1;
}

__device__ bool matchObsTermFromRootCuda(
    std::uint32_t pBase,
    std::uint32_t maxSites,
    std::int32_t rootMol,
    GpuObsTermDef term,
    const GpuObsPatternNode* __restrict__ obsNodes,
    const GpuObsPatternBond* __restrict__ obsBonds,
    const GpuSiteConstraint* __restrict__ constraints,
    const std::uint32_t* __restrict__ typeSiteCounts,
    const std::int8_t* __restrict__ alive,
    const std::int32_t* __restrict__ molType,
    const std::int32_t* __restrict__ siteState,
    const std::int32_t* __restrict__ siteBondMol,
    const std::int32_t* __restrict__ siteBondSite,
    bool requireWholeComplex)
{
    const GpuObsPatternNode n0 = obsNodes[term.nodeOffset];
    if (alive[pBase + static_cast<std::uint32_t>(rootMol)] == 0) return false;
    if (molType[pBase + static_cast<std::uint32_t>(rootMol)] != n0.molType) return false;
    if (!nodeMatchesConstraintsCuda(pBase, maxSites, rootMol,
                                    n0.constraintOffset, n0.constraintCount,
                                    constraints, siteState, siteBondMol)) {
        return false;
    }
    std::int32_t assigned[4] = {-1, -1, -1, -1};
    assigned[0] = rootMol;

    for (std::uint32_t pass = 0; pass < term.nodeCount; ++pass) {
        bool progressed = false;
        for (std::uint32_t bi = 0; bi < term.bondCount; ++bi) {
            const GpuObsPatternBond b = obsBonds[term.bondOffset + bi];
            const std::int32_t a = assigned[b.firstNode];
            const std::int32_t c = assigned[b.secondNode];
            if (a >= 0 && c < 0) {
                const std::uint32_t idx =
                    (pBase + static_cast<std::uint32_t>(a)) * maxSites +
                    static_cast<std::uint32_t>(b.firstSite);
                const std::int32_t partner = siteBondMol[idx];
                if (partner < 0 || siteBondSite[idx] != static_cast<std::int32_t>(b.secondSite)) {
                    return false;
                }
                assigned[b.secondNode] = partner;
                progressed = true;
            } else if (c >= 0 && a < 0) {
                const std::uint32_t idx =
                    (pBase + static_cast<std::uint32_t>(c)) * maxSites +
                    static_cast<std::uint32_t>(b.secondSite);
                const std::int32_t partner = siteBondMol[idx];
                if (partner < 0 || siteBondSite[idx] != static_cast<std::int32_t>(b.firstSite)) {
                    return false;
                }
                assigned[b.firstNode] = partner;
                progressed = true;
            }
        }
        if (!progressed) break;
    }

    for (std::uint32_t ni = 0; ni < term.nodeCount; ++ni) {
        const std::int32_t m = assigned[ni];
        if (m < 0 || alive[pBase + static_cast<std::uint32_t>(m)] == 0) return false;
        for (std::uint32_t nj = 0; nj < ni; ++nj) {
            if (assigned[nj] == m) return false;
        }
        const GpuObsPatternNode nd = obsNodes[term.nodeOffset + ni];
        if (molType[pBase + static_cast<std::uint32_t>(m)] != nd.molType) return false;
        if (!nodeMatchesConstraintsCuda(pBase, maxSites, m,
                                        nd.constraintOffset, nd.constraintCount,
                                        constraints, siteState, siteBondMol)) {
            return false;
        }
    }
    for (std::uint32_t bi = 0; bi < term.bondCount; ++bi) {
        const GpuObsPatternBond b = obsBonds[term.bondOffset + bi];
        const std::int32_t a = assigned[b.firstNode];
        const std::int32_t c = assigned[b.secondNode];
        const std::uint32_t idx =
            (pBase + static_cast<std::uint32_t>(a)) * maxSites +
            static_cast<std::uint32_t>(b.firstSite);
        if (siteBondMol[idx] != c || siteBondSite[idx] != static_cast<std::int32_t>(b.secondSite)) {
            return false;
        }
    }
    if (requireWholeComplex) {
        for (std::uint32_t ni = 1; ni < term.nodeCount; ++ni) {
            if (obsNodes[term.nodeOffset + ni].molType == n0.molType &&
                assigned[ni] < rootMol) {
                return false;
            }
        }
        for (std::uint32_t ni = 0; ni < term.nodeCount; ++ni) {
            const std::int32_t m = assigned[ni];
            const std::uint32_t sc =
                typeSiteCounts[static_cast<std::uint32_t>(molType[pBase + static_cast<std::uint32_t>(m)])];
            for (std::uint32_t s = 0; s < sc; ++s) {
                const std::int32_t p =
                    siteBondMol[(pBase + static_cast<std::uint32_t>(m)) * maxSites + s];
                if (p < 0) continue;
                bool inSet = false;
                for (std::uint32_t nj = 0; nj < term.nodeCount; ++nj) {
                    if (assigned[nj] == p) { inSet = true; break; }
                }
                if (!inSet) return false;
            }
        }
    }
    return true;
}

__device__ float evalObservableCuda(
    std::uint32_t pBase,
    std::uint32_t obsIdx,
    GraphSimParams params,
    const std::uint32_t* __restrict__ typeOffsets,
    const std::uint32_t* __restrict__ typeCaps,
    const std::uint32_t* __restrict__ typeSiteCounts,
    const GpuSiteConstraint* __restrict__ constraints,
    const GpuObsPatternNode* __restrict__ obsNodes,
    const GpuObsPatternBond* __restrict__ obsBonds,
    const GpuObsTermDef* __restrict__ obsTerms,
    const GpuObsDef* __restrict__ observables,
    const std::int8_t* __restrict__ alive,
    const std::int32_t* __restrict__ molType,
    const std::int32_t* __restrict__ siteState,
    const std::int32_t* __restrict__ siteBondMol,
    const std::int32_t* __restrict__ siteBondSite)
{
    const GpuObsDef obs = observables[obsIdx];
    std::uint32_t total = 0u;
    if (obs.isSpecies == 0u) {
        for (std::uint32_t ti = 0; ti < obs.termCount; ++ti) {
            const GpuObsTermDef term = obsTerms[obs.termOffset + ti];
            const std::uint32_t t0 = static_cast<std::uint32_t>(obsNodes[term.nodeOffset].molType);
            const std::uint32_t start = typeOffsets[t0];
            const std::uint32_t end = start + typeCaps[t0];
            std::uint32_t matches = 0u;
            for (std::uint32_t m = start; m < end; ++m) {
                if (matchObsTermFromRootCuda(
                        pBase, params.maxSites, static_cast<std::int32_t>(m), term,
                        obsNodes, obsBonds, constraints, typeSiteCounts,
                        alive, molType, siteState, siteBondMol, siteBondSite, false)) {
                    ++matches;
                }
            }
            total += matches * term.weight;
        }
    } else if (obs.termCount > 0u) {
        const std::uint32_t t0 =
            static_cast<std::uint32_t>(obsNodes[obsTerms[obs.termOffset].nodeOffset].molType);
        const std::uint32_t start = typeOffsets[t0];
        const std::uint32_t end = start + typeCaps[t0];
        for (std::uint32_t m = start; m < end; ++m) {
            if (alive[pBase + m] == 0) continue;
            bool matchedAny = false;
            for (std::uint32_t ti = 0; ti < obs.termCount; ++ti) {
                if (matchObsTermFromRootCuda(
                        pBase, params.maxSites, static_cast<std::int32_t>(m),
                        obsTerms[obs.termOffset + ti],
                        obsNodes, obsBonds, constraints, typeSiteCounts,
                        alive, molType, siteState, siteBondMol, siteBondSite, true)) {
                    matchedAny = true;
                    break;
                }
            }
            if (matchedAny) ++total;
        }
    }
    return static_cast<float>(total);
}

__device__ float evalVmCuda(
    std::uint32_t vmOffset,
    std::uint32_t vmLen,
    const GpuVmInstr* __restrict__ vmCode,
    const float* obsValues,
    bool& ok)
{
    float stack[32];
    std::uint32_t top = 0u;
    std::uint32_t pc = 0u;
    while (pc < vmLen) {
        const GpuVmInstr ins = vmCode[vmOffset + pc++];
        const std::uint8_t op = ins.op;
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
            float b = stack[--top]; stack[top - 1u] = powf(stack[top - 1u], b);
        } else if (op == 7u) {
            stack[top - 1u] = -stack[top - 1u];
        } else if (op == 8u) {
            stack[top - 1u] = expf(stack[top - 1u]);
        } else if (op == 9u) {
            stack[top - 1u] = logf(stack[top - 1u]);
        } else if (op == 10u) {
            stack[top - 1u] = sqrtf(stack[top - 1u]);
        } else if (op == 11u) {
            stack[top - 1u] = sinf(stack[top - 1u]);
        } else if (op == 12u) {
            stack[top - 1u] = cosf(stack[top - 1u]);
        } else if (op == 13u) {
            stack[top - 1u] = tanf(stack[top - 1u]);
        } else if (op == 14u) {
            stack[top - 1u] = fabsf(stack[top - 1u]);
        } else if (op == 15u) {
            float b = stack[--top]; stack[top - 1u] = fminf(stack[top - 1u], b);
        } else if (op == 16u) {
            float b = stack[--top]; stack[top - 1u] = fmaxf(stack[top - 1u], b);
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

__device__ void addTouchedCuda(std::int32_t* touched, std::uint32_t& touchedCount, std::int32_t mol) {
    if (mol < 0) return;
    for (std::uint32_t i = 0; i < touchedCount; ++i) {
        if (touched[i] == mol) return;
    }
    if (touchedCount < 32u) touched[touchedCount++] = mol;
}

__global__ void nfnextGraphBatchKernel(
    GraphSimParams params,
    const std::uint32_t* __restrict__ typeOffsets,
    const std::uint32_t* __restrict__ typeCaps,
    const std::uint32_t* __restrict__ typeSiteCounts,
    const std::int8_t* __restrict__ initAlive,
    const std::int32_t* __restrict__ initMolType,
    const std::int32_t* __restrict__ initSiteState,
    const std::int32_t* __restrict__ initSiteBondMol,
    const std::int32_t* __restrict__ initSiteBondSite,
    const GpuSiteConstraint* __restrict__ constraints,
    const GpuMatchListDef* __restrict__ matchLists,
    const GpuRuleAction* __restrict__ actions,
    const GpuGraphRule* __restrict__ rules,
    const GpuVmInstr* __restrict__ vmCode,
    const GpuObsPatternNode* __restrict__ obsNodes,
    const GpuObsPatternBond* __restrict__ obsBonds,
    const GpuObsTermDef* __restrict__ obsTerms,
    const GpuObsDef* __restrict__ observables,
    const float* __restrict__ sampleTimes,
    std::int8_t* __restrict__ alive,
    std::int32_t* __restrict__ molType,
    std::int32_t* __restrict__ siteState,
    std::int32_t* __restrict__ siteBondMol,
    std::int32_t* __restrict__ siteBondSite,
    std::int32_t* __restrict__ mlItems,
    std::int32_t* __restrict__ mlPos,
    std::uint32_t* __restrict__ mlCounts,
    float* __restrict__ outputs,
    unsigned long long* __restrict__ eventCounts,
    std::uint32_t* __restrict__ errorFlags,
    const GpuRuleFilter* __restrict__ ruleFilters)
{
    const std::uint32_t trajectory = blockIdx.x * blockDim.x + threadIdx.x;
    if (trajectory >= params.batchSize) return;

    const std::uint32_t pBase = trajectory * params.totalCapacity;
    const std::uint32_t sBase = pBase * params.maxSites;
    for (std::uint32_t m = 0; m < params.totalCapacity; ++m) {
        alive[pBase + m] = initAlive[m];
        molType[pBase + m] = initMolType[m];
        for (std::uint32_t s = 0; s < params.maxSites; ++s) {
            const std::uint32_t idx = m * params.maxSites + s;
            siteState[sBase + idx] = initSiteState[idx];
            siteBondMol[sBase + idx] = initSiteBondMol[idx];
            siteBondSite[sBase + idx] = initSiteBondSite[idx];
        }
    }
    const std::uint32_t mlBaseAll = trajectory * params.totalMatchListSlots;
    for (std::uint32_t i = 0; i < params.totalMatchListSlots; ++i) {
        mlPos[mlBaseAll + i] = -1;
    }
    for (std::uint32_t mlIdx = 0; mlIdx < params.numMatchLists; ++mlIdx) {
        mlCounts[trajectory * params.numMatchLists + mlIdx] = 0u;
    }
    for (std::uint32_t m = 0; m < params.totalCapacity; ++m) {
        if (alive[pBase + m] == 0) continue;
        refreshMoleculeCuda(trajectory, pBase, static_cast<std::int32_t>(m), molType[pBase + m],
                            params, typeOffsets, constraints, matchLists, alive, molType,
                            siteState, siteBondMol, siteBondSite, mlItems, mlPos, mlCounts);
    }

    Pcg32 rng;
    const unsigned long long key = params.baseSeed + static_cast<unsigned long long>(trajectory) * 2ULL;
    rng.init(splitmix64(key), splitmix64(key + 1ULL));

    bool hasDynamicRules = false;
    for (std::uint32_t r = 0; r < params.numRules; ++r) {
        if (rules[r].isDynamicRate != 0u) { hasDynamicRules = true; break; }
    }

    float ruleProps[256];
    float obsValues[32];
    unsigned long long events = 0ULL;
    float time = 0.0f;

    for (std::uint32_t outIdx = 0; outIdx < params.numOutputs; ++outIdx) {
        const float targetTime = sampleTimes[outIdx];
        for (;;) {
            if (hasDynamicRules) {
                for (std::uint32_t oi = 0; oi < params.numObservables && oi < 32u; ++oi) {
                    obsValues[oi] = evalObservableCuda(
                        pBase, oi, params, typeOffsets, typeCaps, typeSiteCounts,
                        constraints, obsNodes, obsBonds, obsTerms, observables,
                        alive, molType, siteState, siteBondMol, siteBondSite);
                }
            }
            float total = 0.0f;
            for (std::uint32_t r = 0; r < params.numRules; ++r) {
                const GpuGraphRule rule = rules[r];
                float rate = rule.rate;
                if (rule.isDynamicRate != 0u) {
                    bool ok = true;
                    rate = evalVmCuda(rule.vmOffset, rule.vmLen, vmCode, obsValues, ok);
                    if (!ok) {
                        errorFlags[trajectory] = 3u;
                        eventCounts[trajectory] = events;
                        return;
                    }
                }
                const std::uint32_t c0 = mlCounts[trajectory * params.numMatchLists + rule.matchList0];
                float countF = 0.0f;
                if (rule.isTwoComponent == 0u) {
                    countF = static_cast<float>(c0);
                } else if (rule.isInterchangeable != 0u) {
                    countF = (c0 > 1u) ? (0.5f * static_cast<float>(c0) * static_cast<float>(c0 - 1u)) : 0.0f;
                } else {
                    const std::uint32_t c1 = mlCounts[trajectory * params.numMatchLists + rule.matchList1];
                    countF = static_cast<float>(c0) * static_cast<float>(c1);
                }
                const float prop = (rule.isTotalRate != 0u)
                    ? ((countF > 0.0f) ? rate : 0.0f)
                    : (rate * countF);
                ruleProps[r] = prop;
                total += prop;
            }
            if (!(total > 0.0f)) {
                time = targetTime;
                break;
            }
            const float u1 = rng.nextFloat01();
            const float dt = -logf(u1) / total;
            if (time + dt > targetTime) {
                time = targetTime;
                break;
            }
            time += dt;
            if (events >= static_cast<unsigned long long>(params.maxEvents)) {
                errorFlags[trajectory] = 1u;
                eventCounts[trajectory] = events;
                return;
            }

            const float pick = rng.nextFloat01() * total;
            float cum = 0.0f;
            std::uint32_t selectedRule = params.numRules - 1u;
            for (std::uint32_t r = 0; r < params.numRules; ++r) {
                cum += ruleProps[r];
                if (cum >= pick) { selectedRule = r; break; }
            }
            const GpuGraphRule rule = rules[selectedRule];
            const GpuMatchListDef ml0 = matchLists[rule.matchList0];
            const std::uint32_t c0 = mlCounts[trajectory * params.numMatchLists + rule.matchList0];
            if (c0 == 0u) continue;
            const std::int32_t m0 = mlItems[mlBaseAll + ml0.listOffset + nextBounded(rng, c0)];

            std::int32_t nodes[4] = {-1, -1, -1, -1};
            nodes[0] = m0;
            if (rule.isTwoComponent != 0u) {
                const GpuMatchListDef ml1 = matchLists[rule.matchList1];
                const std::uint32_t c1 = mlCounts[trajectory * params.numMatchLists + rule.matchList1];
                if (c1 == 0u) continue;
                std::int32_t m1 = mlItems[mlBaseAll + ml1.listOffset + nextBounded(rng, c1)];
                if (m1 == m0) {
                    if (rule.isInterchangeable != 0u && c1 > 1u) {
                        const std::uint32_t idx0 = static_cast<std::uint32_t>(
                            mlPos[mlBaseAll + ml0.listOffset +
                                  (static_cast<std::uint32_t>(m0) -
                                   typeOffsets[static_cast<std::uint32_t>(ml0.anchorType)])]);
                        std::uint32_t idx1 = nextBounded(rng, c1 - 1u);
                        if (idx1 >= idx0) ++idx1;
                        m1 = mlItems[mlBaseAll + ml1.listOffset + idx1];
                    } else {
                        continue;
                    }
                }
                nodes[1] = m1;
            } else if (ml0.partnerType >= 0) {
                nodes[1] = siteBondMol[(pBase + static_cast<std::uint32_t>(m0)) * params.maxSites +
                                       static_cast<std::uint32_t>(ml0.bondSite0)];
            }

            if (rule.filterCount > 0u) {
                bool filterPassed = true;
                for (std::uint32_t fi = 0u; fi < static_cast<std::uint32_t>(rule.filterCount); ++fi) {
                    const GpuRuleFilter filt = ruleFilters[rule.filterOffset + fi];
                    const std::int32_t root = nodes[filt.reactantNode];
                    if (root < 0) { filterPassed = false; break; }
                    std::int32_t comp[32];
                    std::uint32_t compHead = 0u, compTail = 0u;
                    comp[compTail++] = root;
                    while (compHead < compTail) {
                        const std::int32_t cur = comp[compHead++];
                        const std::uint32_t sc = typeSiteCounts[static_cast<std::uint32_t>(
                            molType[pBase + static_cast<std::uint32_t>(cur)])];
                        for (std::uint32_t s = 0u; s < sc; ++s) {
                            const std::int32_t p = siteBondMol[(pBase + static_cast<std::uint32_t>(cur)) * params.maxSites + s];
                            if (p < 0 || alive[pBase + static_cast<std::uint32_t>(p)] == 0) continue;
                            bool seen = false;
                            for (std::uint32_t k = 0u; k < compTail; ++k) {
                                if (comp[k] == p) { seen = true; break; }
                            }
                            if (!seen) {
                                if (compTail >= 32u) {
                                    errorFlags[trajectory] = 4u;
                                    eventCounts[trajectory] = events;
                                    return;
                                }
                                comp[compTail++] = p;
                            }
                        }
                    }
                    bool anyMatched = false;
                    for (std::uint32_t ti = 0u; ti < filt.termCount; ++ti) {
                        const GpuObsTermDef term = obsTerms[filt.termOffset + ti];
                        for (std::uint32_t ci = 0u; ci < compTail; ++ci) {
                            if (matchObsTermFromRootCuda(pBase, params.maxSites, comp[ci], term,
                                                         obsNodes, obsBonds, constraints, typeSiteCounts,
                                                         alive, molType, siteState, siteBondMol, siteBondSite,
                                                         false)) {
                                anyMatched = true;
                                break;
                            }
                        }
                        if (anyMatched) break;
                    }
                    if ((filt.include != 0u && !anyMatched) || (filt.include == 0u && anyMatched)) {
                        filterPassed = false;
                        break;
                    }
                }
                if (!filterPassed) continue;
            }

            std::int32_t touched[32];
            std::uint32_t touchedCount = 0u;
            for (std::uint32_t ni = 0; ni < 2u; ++ni) {
                if (nodes[ni] < 0) continue;
                addTouchedCuda(touched, touchedCount, nodes[ni]);
                const std::uint32_t sc =
                    typeSiteCounts[static_cast<std::uint32_t>(molType[pBase + static_cast<std::uint32_t>(nodes[ni])])];
                for (std::uint32_t s = 0; s < sc; ++s) {
                    addTouchedCuda(
                        touched, touchedCount,
                        siteBondMol[(pBase + static_cast<std::uint32_t>(nodes[ni])) * params.maxSites + s]);
                }
            }

            for (std::uint32_t ai = 0; ai < rule.actionCount; ++ai) {
                const GpuRuleAction act = actions[rule.actionOffset + ai];
                if (act.kind == 3u) {
                    const std::uint32_t t = static_cast<std::uint32_t>(act.value);
                    const std::uint32_t start = typeOffsets[t];
                    const std::uint32_t end = start + typeCaps[t];
                    std::int32_t slot = -1;
                    for (std::uint32_t cand = start; cand < end; ++cand) {
                        if (alive[pBase + cand] == 0) { slot = static_cast<std::int32_t>(cand); break; }
                    }
                    if (slot < 0) {
                        errorFlags[trajectory] = 2u;
                        eventCounts[trajectory] = events;
                        return;
                    }
                    alive[pBase + static_cast<std::uint32_t>(slot)] = 1;
                    molType[pBase + static_cast<std::uint32_t>(slot)] = static_cast<std::int32_t>(t);
                    for (std::uint32_t s = 0; s < params.maxSites; ++s) {
                        const std::uint32_t sIdx = (pBase + static_cast<std::uint32_t>(slot)) * params.maxSites + s;
                        siteState[sIdx] = 0;
                        siteBondMol[sIdx] = -1;
                        siteBondSite[sIdx] = -1;
                    }
                    nodes[act.targetNode] = slot;
                    addTouchedCuda(touched, touchedCount, slot);
                }
            }
            for (std::uint32_t ai = 0; ai < rule.actionCount; ++ai) {
                const GpuRuleAction act = actions[rule.actionOffset + ai];
                if (act.kind == 0u) {
                    const std::int32_t m = nodes[act.targetNode];
                    siteState[(pBase + static_cast<std::uint32_t>(m)) * params.maxSites +
                              static_cast<std::uint32_t>(act.site)] = act.value;
                } else if (act.kind == 1u) {
                    const std::int32_t mA = nodes[act.targetNode];
                    const std::int32_t mB = nodes[act.partnerNode];
                    const std::uint32_t iA = (pBase + static_cast<std::uint32_t>(mA)) * params.maxSites +
                                             static_cast<std::uint32_t>(act.site);
                    const std::uint32_t iB = (pBase + static_cast<std::uint32_t>(mB)) * params.maxSites +
                                             static_cast<std::uint32_t>(act.partnerSite);
                    siteBondMol[iA] = mB;
                    siteBondSite[iA] = static_cast<std::int32_t>(act.partnerSite);
                    siteBondMol[iB] = mA;
                    siteBondSite[iB] = static_cast<std::int32_t>(act.site);
                } else if (act.kind == 2u) {
                    const std::int32_t mA = nodes[act.targetNode];
                    const std::int32_t mB = nodes[act.partnerNode];
                    const std::uint32_t iA = (pBase + static_cast<std::uint32_t>(mA)) * params.maxSites +
                                             static_cast<std::uint32_t>(act.site);
                    const std::uint32_t iB = (pBase + static_cast<std::uint32_t>(mB)) * params.maxSites +
                                             static_cast<std::uint32_t>(act.partnerSite);
                    siteBondMol[iA] = -1;
                    siteBondSite[iA] = -1;
                    siteBondMol[iB] = -1;
                    siteBondSite[iB] = -1;
                } else if (act.kind == 4u) {
                    const std::int32_t m = nodes[act.targetNode];
                    const std::uint32_t sc =
                        typeSiteCounts[static_cast<std::uint32_t>(molType[pBase + static_cast<std::uint32_t>(m)])];
                    for (std::uint32_t s = 0; s < sc; ++s) {
                        const std::uint32_t iM = (pBase + static_cast<std::uint32_t>(m)) * params.maxSites + s;
                        const std::int32_t p = siteBondMol[iM];
                        const std::int32_t ps = siteBondSite[iM];
                        if (p >= 0 && ps >= 0) {
                            const std::uint32_t iP =
                                (pBase + static_cast<std::uint32_t>(p)) * params.maxSites +
                                static_cast<std::uint32_t>(ps);
                            siteBondMol[iP] = -1;
                            siteBondSite[iP] = -1;
                            addTouchedCuda(touched, touchedCount, p);
                        }
                        siteBondMol[iM] = -1;
                        siteBondSite[iM] = -1;
                    }
                    alive[pBase + static_cast<std::uint32_t>(m)] = 0;
                } else if (act.kind == 5u) {
                    std::int32_t dq[32];
                    std::uint32_t dqh = 0u, dqt = 0u;
                    const std::int32_t root = nodes[act.targetNode];
                    if (root >= 0 && alive[pBase + static_cast<std::uint32_t>(root)] != 0) {
                        dq[dqt++] = root;
                        alive[pBase + static_cast<std::uint32_t>(root)] = 0;
                        addTouchedCuda(touched, touchedCount, root);
                        while (dqh < dqt) {
                            const std::int32_t cur = dq[dqh++];
                            const std::uint32_t sc = typeSiteCounts[static_cast<std::uint32_t>(
                                molType[pBase + static_cast<std::uint32_t>(cur)])];
                            for (std::uint32_t s = 0; s < sc; ++s) {
                                const std::uint32_t iM =
                                    (pBase + static_cast<std::uint32_t>(cur)) * params.maxSites + s;
                                const std::int32_t p = siteBondMol[iM];
                                const std::int32_t ps = siteBondSite[iM];
                                siteBondMol[iM] = -1;
                                siteBondSite[iM] = -1;
                                if (p >= 0 && ps >= 0) {
                                    const std::uint32_t iP =
                                        (pBase + static_cast<std::uint32_t>(p)) * params.maxSites +
                                        static_cast<std::uint32_t>(ps);
                                    siteBondMol[iP] = -1;
                                    siteBondSite[iP] = -1;
                                    if (alive[pBase + static_cast<std::uint32_t>(p)] != 0) {
                                        if (dqt >= 32u) {
                                            errorFlags[trajectory] = 4u;
                                            eventCounts[trajectory] = events;
                                            return;
                                        }
                                        alive[pBase + static_cast<std::uint32_t>(p)] = 0;
                                        dq[dqt++] = p;
                                        addTouchedCuda(touched, touchedCount, p);
                                    }
                                }
                            }
                        }
                    }
                }
            }

            for (std::uint32_t ti = 0; ti < touchedCount; ++ti) {
                const std::int32_t m = touched[ti];
                const std::int32_t st = findSlotTypeCuda(m, params.numTypes, typeOffsets, typeCaps);
                if (st >= 0) {
                    refreshMoleculeCuda(trajectory, pBase, m, st, params, typeOffsets,
                                        constraints, matchLists, alive, molType, siteState,
                                        siteBondMol, siteBondSite, mlItems, mlPos, mlCounts);
                }
            }
            ++events;
        }

        for (std::uint32_t oi = 0; oi < params.numObservables; ++oi) {
            const float val = evalObservableCuda(
                pBase, oi, params, typeOffsets, typeCaps, typeSiteCounts,
                constraints, obsNodes, obsBonds, obsTerms, observables,
                alive, molType, siteState, siteBondMol, siteBondSite);
            const std::size_t outFlat =
                (static_cast<std::size_t>(trajectory) * params.numOutputs + outIdx) *
                    params.numObservables +
                oi;
            outputs[outFlat] = val;
        }
    }
    eventCounts[trajectory] = events;
}

} // namespace

NfnextDeviceOutput simulateNfnextGraphCuda(
    const NfnextGraphPlan& plan, const NfnextGpuRequest& request) {
    const auto wallStart = std::chrono::steady_clock::now();
    int deviceId = 0;
    checkCuda(cudaGetDevice(&deviceId), "cudaGetDevice failed");
    cudaDeviceProp props{};
    checkCuda(cudaGetDeviceProperties(&props, deviceId), "cudaGetDeviceProperties failed");

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

    const std::size_t typeOffBytes = checkedBytes(plan.typeOffsets.size(), sizeof(std::uint32_t));
    const std::size_t typeCapBytes = checkedBytes(plan.typeCapacities.size(), sizeof(std::uint32_t));
    const std::size_t typeSiteBytes = checkedBytes(plan.typeSiteCounts.size(), sizeof(std::uint32_t));
    const std::size_t initAliveBytes = checkedBytes(plan.initAlive.size(), sizeof(std::int8_t));
    const std::size_t initTypeBytes = checkedBytes(plan.initMolType.size(), sizeof(std::int32_t));
    const std::size_t initSiteBytes = checkedBytes(plan.initSiteState.size(), sizeof(std::int32_t));
    const std::size_t cBytes = checkedBytes(plan.constraints.size(), sizeof(GpuSiteConstraint));
    const std::size_t mlDefBytes = checkedBytes(plan.matchLists.size(), sizeof(GpuMatchListDef));
    const std::size_t actBytes = checkedBytes(plan.actions.size(), sizeof(GpuRuleAction));
    const std::size_t ruleBytes = checkedBytes(plan.rules.size(), sizeof(GpuGraphRule));
    const std::size_t filterBytes = checkedBytes(plan.ruleFilters.size(), sizeof(GpuRuleFilter));
    const std::size_t vmBytes = checkedBytes(plan.vmCode.size(), sizeof(GpuVmInstr));
    const std::size_t oNodeBytes = checkedBytes(plan.obsNodes.size(), sizeof(GpuObsPatternNode));
    const std::size_t oBondBytes = checkedBytes(plan.obsBonds.size(), sizeof(GpuObsPatternBond));
    const std::size_t oTermBytes = checkedBytes(plan.obsTerms.size(), sizeof(GpuObsTermDef));
    const std::size_t oDefBytes = checkedBytes(plan.observables.size(), sizeof(GpuObsDef));
    const std::size_t timeBytes = checkedBytes(sampleTimes.size(), sizeof(float));
    const std::size_t aliveBytes = checkedBytes(totalParticleSlots, sizeof(std::int8_t));
    const std::size_t molTypeBytes = checkedBytes(totalParticleSlots, sizeof(std::int32_t));
    const std::size_t siteArrBytes = checkedBytes(totalSiteSlots, sizeof(std::int32_t));
    const std::size_t mlSlotBytes = checkedBytes(totalMlSlots, sizeof(std::int32_t));
    const std::size_t mlCntBytes = checkedBytes(totalMlCounts, sizeof(std::uint32_t));
    const std::size_t outputBytes = checkedBytes(outputValues, sizeof(float));
    const std::size_t eventBytes = checkedBytes(request.batchSize, sizeof(unsigned long long));
    const std::size_t flagBytes = checkedBytes(request.batchSize, sizeof(std::uint32_t));

    DeviceBuffer dTypeOff, dTypeCap, dTypeSite, dInitAlive, dInitType, dInitState, dInitBondMol,
        dInitBondSite, dConstraints, dMatchLists, dActions, dRules, dRuleFilters, dVmCode, dObsNodes, dObsBonds,
        dObsTerms, dObsDefs, dSampleTimes, dAlive, dMolType, dSiteState, dSiteBondMol,
        dSiteBondSite, dMlItems, dMlPos, dMlCounts, dOutputs, dEvents, dFlags;

    dTypeOff.allocateAndUpload(plan.typeOffsets.data(), typeOffBytes);
    dTypeCap.allocateAndUpload(plan.typeCapacities.data(), typeCapBytes);
    dTypeSite.allocateAndUpload(plan.typeSiteCounts.data(), typeSiteBytes);
    dInitAlive.allocateAndUpload(plan.initAlive.data(), initAliveBytes);
    dInitType.allocateAndUpload(plan.initMolType.data(), initTypeBytes);
    dInitState.allocateAndUpload(plan.initSiteState.data(), initSiteBytes);
    dInitBondMol.allocateAndUpload(plan.initSiteBondMol.data(), initSiteBytes);
    dInitBondSite.allocateAndUpload(plan.initSiteBondSite.data(), initSiteBytes);
    dConstraints.allocateAndUpload(plan.constraints.data(), cBytes);
    dMatchLists.allocateAndUpload(plan.matchLists.data(), mlDefBytes);
    dActions.allocateAndUpload(plan.actions.data(), actBytes);
    dRules.allocateAndUpload(plan.rules.data(), ruleBytes);
    dRuleFilters.allocateAndUpload(plan.ruleFilters.data(), filterBytes);
    dVmCode.allocateAndUpload(plan.vmCode.data(), vmBytes);
    dObsNodes.allocateAndUpload(plan.obsNodes.data(), oNodeBytes);
    dObsBonds.allocateAndUpload(plan.obsBonds.data(), oBondBytes);
    dObsTerms.allocateAndUpload(plan.obsTerms.data(), oTermBytes);
    dObsDefs.allocateAndUpload(plan.observables.data(), oDefBytes);
    dSampleTimes.allocateAndUpload(sampleTimes.data(), timeBytes);
    dAlive.allocate(aliveBytes);
    dMolType.allocate(molTypeBytes);
    dSiteState.allocate(siteArrBytes);
    dSiteBondMol.allocate(siteArrBytes);
    dSiteBondSite.allocate(siteArrBytes);
    dMlItems.allocate(mlSlotBytes);
    dMlPos.allocate(mlSlotBytes);
    dMlCounts.allocate(mlCntBytes);
    dOutputs.allocate(outputBytes);
    dEvents.allocate(eventBytes);
    dFlags.allocateZeroed(flagBytes);

    CudaEventGuard stopEvent;
    const auto setupEnd = std::chrono::steady_clock::now();

    const auto dispatchStart = std::chrono::steady_clock::now();
    const unsigned int blockSize = 64u;
    const unsigned int gridSize = (batchSize + blockSize - 1u) / blockSize;
    nfnextGraphBatchKernel<<<gridSize, blockSize>>>(
        params,
        dTypeOff.as<std::uint32_t>(),
        dTypeCap.as<std::uint32_t>(),
        dTypeSite.as<std::uint32_t>(),
        dInitAlive.as<std::int8_t>(),
        dInitType.as<std::int32_t>(),
        dInitState.as<std::int32_t>(),
        dInitBondMol.as<std::int32_t>(),
        dInitBondSite.as<std::int32_t>(),
        dConstraints.as<GpuSiteConstraint>(),
        dMatchLists.as<GpuMatchListDef>(),
        dActions.as<GpuRuleAction>(),
        dRules.as<GpuGraphRule>(),
        dVmCode.as<GpuVmInstr>(),
        dObsNodes.as<GpuObsPatternNode>(),
        dObsBonds.as<GpuObsPatternBond>(),
        dObsTerms.as<GpuObsTermDef>(),
        dObsDefs.as<GpuObsDef>(),
        dSampleTimes.as<float>(),
        dAlive.as<std::int8_t>(),
        dMolType.as<std::int32_t>(),
        dSiteState.as<std::int32_t>(),
        dSiteBondMol.as<std::int32_t>(),
        dSiteBondSite.as<std::int32_t>(),
        dMlItems.as<std::int32_t>(),
        dMlPos.as<std::int32_t>(),
        dMlCounts.as<std::uint32_t>(),
        dOutputs.as<float>(),
        dEvents.as<unsigned long long>(),
        dFlags.as<std::uint32_t>(),
        dRuleFilters.as<GpuRuleFilter>());
    checkCuda(cudaGetLastError(), "graph kernel launch failed");
    checkCuda(cudaEventRecord(stopEvent.event), "cudaEventRecord failed");
    checkCuda(cudaEventSynchronize(stopEvent.event), "graph kernel synchronization failed");
    const auto dispatchEnd = std::chrono::steady_clock::now();

    std::vector<std::uint32_t> flags(request.batchSize, 0u);
    dFlags.download(flags.data(), flagBytes);
    for (std::size_t t = 0; t < request.batchSize; ++t) {
        if (flags[t] == 1u)
            throw std::runtime_error("NFnext CUDA graph backend: max_events exceeded in trajectory " + std::to_string(t));
        if (flags[t] == 2u)
            throw std::runtime_error("NFnext CUDA graph backend: particle capacity exceeded in trajectory " + std::to_string(t));
        if (flags[t] == 3u)
            throw std::runtime_error("NFnext CUDA graph backend: invalid dynamic rate in trajectory " + std::to_string(t));
        if (flags[t] == 4u)
            throw std::runtime_error("NFnext CUDA graph backend: complex size exceeded bounded BFS limit in trajectory " + std::to_string(t));
    }

    NfnextDeviceOutput output;
    output.device = props.name;
    output.observables.resize(outputValues);
    dOutputs.download(output.observables.data(), outputBytes);
    output.eventCounts.resize(request.batchSize);
    dEvents.download(output.eventCounts.data(), eventBytes);
    output.dispatchWaitTimeMs =
        std::chrono::duration<double, std::milli>(dispatchEnd - dispatchStart).count();
    output.setupTimeMs =
        std::chrono::duration<double, std::milli>(setupEnd - wallStart).count();
    output.deviceMemoryBytes =
        sizeof(params) + typeOffBytes + typeCapBytes + typeSiteBytes + initAliveBytes +
        initTypeBytes + 3 * initSiteBytes + cBytes + mlDefBytes + actBytes + ruleBytes +
        filterBytes + vmBytes + oNodeBytes + oBondBytes + oTermBytes + oDefBytes + timeBytes +
        aliveBytes + molTypeBytes + 3 * siteArrBytes + 2 * mlSlotBytes + mlCntBytes +
        outputBytes + eventBytes + flagBytes;
    output.wallTimeMs =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - wallStart)
            .count();
    return output;
}

} // namespace bng::engine::detail
