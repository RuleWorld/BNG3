#pragma once

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

    static FlattenedReactionNetwork fromModelAndNetwork(
        const ast::Model& model,
        const GeneratedNetwork& network
    );
};

// Metal GPU Batch SSA Simulator
class MetalBatchSsaSimulator {
public:
    static bool isMetalAvailable();

    explicit MetalBatchSsaSimulator(const FlattenedReactionNetwork& flatNet);
    ~MetalBatchSsaSimulator();

    BatchSsaMetrics simulate(const BatchSsaOptions& options);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// Existing CPU Batch SSA Simulator (baseline for benchmarking and statistical validation)
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

} // namespace bng::engine
