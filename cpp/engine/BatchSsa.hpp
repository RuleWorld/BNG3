#pragma once

// Backend-agnostic batched direct-SSA support.
//
// This header owns the pieces every execution backend needs: the batch options,
// the aggregated metrics, the flattened reaction network, and the CPU pool
// simulator. Accelerator-specific code lives under engine/gpu/ and is reached
// through the GpuSsaBackend interface, so a new backend never has to touch this
// file.

#include "NetworkGenerator.hpp"
#include "OdeIntegrator.hpp"

namespace bng::ast { class Model; }
#include <vector>
#include <string>
#include <memory>
#include <cstdint>

namespace bng::engine {

struct BatchSsaOptions {
    double tStart = 0.0;
    double tEnd = 10.0;
    int nSteps = 10;
    uint64_t baseSeed = 42;
    std::size_t batchSize = 1000;
    std::size_t maxSimSteps = 0; // 0 = unlimited
};

struct BatchSsaMetrics {
    std::size_t batchSize = 0;
    uint64_t totalEvents = 0;

    // Detailed timing breakdown (milliseconds)
    double modelPrepTimeMs = 0.0;
    double hostToDeviceTransferMs = 0.0;
    double simulationTimeMs = 0.0;
    double deviceToHostTransferMs = 0.0;
    double totalWallTimeMs = 0.0;

    // Throughput
    double trajectoriesPerSecSim = 0.0;
    double trajectoriesPerSecTotal = 0.0;
    double eventsPerSecSim = 0.0;
    double eventsPerSecTotal = 0.0;

    // Memory usage in bytes
    std::size_t memoryUsageBytes = 0;

    // Output distributions and means for statistical validation
    std::vector<float> timePoints;
    std::vector<std::string> observableNames;
    // [timeStep][groupIndex]
    std::vector<std::vector<float>> observableMeans;
    std::vector<std::vector<float>> observableStdDevs;

    // Trajectory final observable values: [batchSize * numObservables]
    std::vector<float> finalObservables;
    // Trajectory final species values: [batchSize * numSpecies]
    std::vector<int32_t> finalSpecies;
    // Per-trajectory event counts: [batchSize]
    std::vector<uint32_t> trajectoryEventCounts;

    // Mean and std-dev trajectories over the full time grid (for OdeResult conversion)
    // [timeIndex][speciesIndex] — double precision for downstream use
    std::vector<std::vector<double>> meanSpecies;
    std::vector<std::vector<double>> stdSpecies;
    std::vector<std::vector<double>> meanObservables;
    std::vector<std::vector<double>> stdObservables;
    std::vector<double> timePointsDouble;
};

// Flattened representation of a generated reaction network for GPU execution
struct FlattenedReactionNetwork {
    uint32_t numSpecies = 0;
    uint32_t numReactions = 0;
    uint32_t numObservables = 0;

    std::vector<int32_t> initialSpecies;
    std::vector<float> rateConstants;

    // Reactants (CSR)
    std::vector<uint32_t> reactantOffsets;
    std::vector<uint32_t> reactantSpecies;
    std::vector<float> reactantStoichOffsets;

    // State changes: reactants consumed (CSR)
    std::vector<uint32_t> reactChangeOffsets;
    std::vector<uint32_t> reactChangeSpecies;

    // State changes: products produced (CSR)
    std::vector<uint32_t> prodChangeOffsets;
    std::vector<uint32_t> prodChangeSpecies;

    // Observables (CSR)
    std::vector<std::string> observableNames;
    std::vector<uint32_t> obsOffsets;
    std::vector<uint32_t> obsSpecies;
    std::vector<float> obsWeights;

    // Fails closed on any model the direct method cannot reproduce exactly
    // (functional rates, TotalRate rules, non-finite rate constants).
    static FlattenedReactionNetwork fromModelAndNetwork(
        const ast::Model& model,
        const GeneratedNetwork& network
    );
};

// Per-trajectory RNG seed for a batch run.
//
// This lives here, rather than in any one backend, because every backend must
// derive the same seed for the same (baseSeed, trajectory) pair: the CPU/GPU
// parity harness in tests/test_batch_ssa_statistical_parity.py compares the two
// at the SAME base seed, so a derivation that differs per backend silently
// invalidates that comparison. It is a pure function of its two arguments — no
// thread id, no device id, no loop order — so the result cannot depend on how
// the batch was partitioned across workers.
//
// The derivation is a SplitMix64 finalizer over the pair, not `base + traj`.
// Addition aliases: batch runs whose base seeds differ by delta share their
// B - delta trajectories, so base seeds 5000, 5001 and 5002 produced
// near-identical batch means and an across-seed spread ~19x too small to be a
// sampling distribution. Mixing both words through one avalanche makes
// adjacent base seeds and adjacent trajectory indices decorrelate, which is the
// same property the GPU backends already had via their counter-based PCG32
// (gpu/MetalSsaBackend.mm, gpu/CudaSsaBackend.cu: keyed on trajId).
inline uint64_t batchTrajectorySeed(uint64_t baseSeed, std::size_t trajectory) {
    uint64_t z = baseSeed + 0x9E3779B97F4A7C15ULL * (trajectory + 1);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

// CPU Batch SSA Simulator: reference implementation and fallback backend.
class CpuBatchSsaSimulator {
public:
    CpuBatchSsaSimulator(const ast::Model& model, const GeneratedNetwork& network);

    // 1 worker (single core)
    BatchSsaMetrics simulateSingleWorker(const BatchSsaOptions& options);

    // Multi-core (using available hardware concurrency)
    BatchSsaMetrics simulateMultiCore(const BatchSsaOptions& options, unsigned int numThreads = 0);

private:
    const ast::Model& model_;
    const GeneratedNetwork& network_;
};

namespace detail {

// Populate the double-precision mean/std fields in BatchSsaMetrics from the
// float observableMeans/StdDevs already computed, so OdeIntegrator can consume
// them directly without a redundant conversion loop at the call site. Shared by
// every backend, hence declared here rather than kept in a translation unit.
void fillDoubleFields(BatchSsaMetrics& m);

// Uniform output grid a batch of trajectories samples at, shared by all
// backends so GPU and CPU results line up on the same time points.
std::vector<float> batchOutputTimes(const BatchSsaOptions& options);

} // namespace detail

} // namespace bng::engine
