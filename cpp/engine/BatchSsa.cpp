#include "engine/BatchSsa.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <future>
#include <stdexcept>
#include <string>
#include <thread>

namespace bng::engine {

namespace detail {

std::vector<float> batchOutputTimes(const BatchSsaOptions& options) {
    const std::size_t numPoints = static_cast<std::size_t>(options.nSteps) + 1;
    std::vector<float> times(numPoints);
    const double step = (options.nSteps > 0)
        ? (options.tEnd - options.tStart) / options.nSteps
        : 0.0;
    for (std::size_t i = 0; i < numPoints; ++i) {
        times[i] = static_cast<float>(options.tStart + static_cast<double>(i) * step);
    }
    return times;
}

// Populate the double-precision mean/std fields in BatchSsaMetrics from the
// float observableMeans/StdDevs already computed, so OdeIntegrator can consume
// them directly without a redundant conversion loop at the call site.
void fillDoubleFields(BatchSsaMetrics& m) {
    const std::size_t T = m.timePoints.size();
    const std::size_t G = m.observableMeans.empty() ? 0 : m.observableMeans[0].size();

    m.timePointsDouble.resize(T);
    for (std::size_t t = 0; t < T; ++t)
        m.timePointsDouble[t] = static_cast<double>(m.timePoints[t]);

    m.meanObservables.resize(T, std::vector<double>(G));
    m.stdObservables.resize(T, std::vector<double>(G));
    for (std::size_t t = 0; t < T; ++t)
        for (std::size_t g = 0; g < G; ++g) {
            m.meanObservables[t][g] = static_cast<double>(m.observableMeans[t][g]);
            m.stdObservables[t][g]  = static_cast<double>(m.observableStdDevs[t][g]);
        }

    // meanSpecies/stdSpecies: if finalSpecies is available, compute from it;
    // otherwise leave empty (OdeResult concentrations field stays zero-sized).
    if (!m.finalSpecies.empty() && m.batchSize > 0) {
        const std::size_t S = m.finalSpecies.size() / m.batchSize;
        // We only have final-state species — build a single time-point vector.
        m.meanSpecies.assign(1, std::vector<double>(S, 0.0));
        m.stdSpecies.assign(1, std::vector<double>(S, 0.0));
        double N = static_cast<double>(m.batchSize);
        std::vector<double> sum(S, 0.0), sumSq(S, 0.0);
        for (std::size_t b = 0; b < m.batchSize; ++b)
            for (std::size_t s = 0; s < S; ++s) {
                double v = static_cast<double>(m.finalSpecies[b * S + s]);
                sum[s]   += v;
                sumSq[s] += v * v;
            }
        for (std::size_t s = 0; s < S; ++s) {
            double mean = sum[s] / N;
            m.meanSpecies[0][s] = mean;
            m.stdSpecies[0][s]  = std::sqrt(std::max(0.0, sumSq[s] / N - mean * mean));
        }
    }
}

} // namespace detail



// ============================================================================
// Network Flattening & Validation (Fail-closed on non-mass-action)
// ============================================================================

FlattenedReactionNetwork FlattenedReactionNetwork::fromModelAndNetwork(
    const ast::Model& model,
    const GeneratedNetwork& network
) {
    FlattenedReactionNetwork flat;
    OdeIntegrator integrator(model, network);

    // Fail-closed rule 1: functional rate expressions in integrator
    if (integrator.hasFunctionalRates()) {
        throw std::runtime_error(
            "Batch SSA: unsupported rate law (model contains functional rates); failing closed."
        );
    }

    const auto& compiledRxns = integrator.getCompiledReactions();
    const auto& compiledGroups = integrator.getCompiledGroups();

    flat.numSpecies = static_cast<uint32_t>(network.species.size());
    flat.numReactions = static_cast<uint32_t>(compiledRxns.size());
    flat.numObservables = static_cast<uint32_t>(compiledGroups.size());

    // Initial species populations (exact integers)
    flat.initialSpecies.resize(flat.numSpecies);
    for (std::size_t i = 0; i < flat.numSpecies; ++i) {
        double amt = network.species.get(i).getAmount();
        flat.initialSpecies[i] = static_cast<int32_t>(std::max(0.0, std::round(amt)));
    }

    // Reaction arrays
    flat.rateConstants.resize(flat.numReactions);
    flat.reactantOffsets.reserve(flat.numReactions + 1);
    flat.reactChangeOffsets.reserve(flat.numReactions + 1);
    flat.prodChangeOffsets.reserve(flat.numReactions + 1);

    flat.reactantOffsets.push_back(0);
    flat.reactChangeOffsets.push_back(0);
    flat.prodChangeOffsets.push_back(0);

    for (std::size_t r = 0; r < flat.numReactions; ++r) {
        const auto& rxn = compiledRxns[r];

        // Fail-closed rule 2: per-reaction functional rate laws
        if (rxn.isFunctional) {
            throw std::runtime_error(
                "Batch SSA: unsupported rate law (reaction " + std::to_string(r) +
                " has functional rate expression); failing closed."
            );
        }

        // Fail-closed rule 3: TotalRate modifier
        if (rxn.isTotalRate) {
            throw std::runtime_error(
                "Batch SSA: unsupported rate law (reaction " + std::to_string(r) +
                " specifies TotalRate); failing closed."
            );
        }

        // Fail-closed rule 4: invalid rate constants (negative, NaN, inf)
        if (rxn.rateConstant < 0.0 || std::isnan(rxn.rateConstant) || std::isinf(rxn.rateConstant)) {
            throw std::runtime_error(
                "Batch SSA: unsupported rate law (reaction " + std::to_string(r) +
                " has non-positive or non-finite rate constant: " + std::to_string(rxn.rateConstant) +
                "); failing closed."
            );
        }

        flat.rateConstants[r] = static_cast<float>(rxn.rateConstant);

        // Reactants (with offset for identical reactants: A + A -> offset 0 for 1st, 1 for 2nd)
        float currentOffset = 0.0f;
        for (std::size_t i = 0; i < rxn.reactantIndices.size(); ++i) {
            std::size_t sIdx = rxn.reactantIndices[i];
            if (sIdx >= flat.numSpecies) {
                throw std::runtime_error("Batch SSA: reactant index out of range");
            }
            if (i > 0 && rxn.reactantIndices[i] == rxn.reactantIndices[i - 1]) {
                currentOffset += 1.0f;
            } else {
                currentOffset = 0.0f;
            }
            flat.reactantSpecies.push_back(static_cast<uint32_t>(sIdx));
            flat.reactantStoichOffsets.push_back(currentOffset);
            flat.reactChangeSpecies.push_back(static_cast<uint32_t>(sIdx));
        }
        flat.reactantOffsets.push_back(static_cast<uint32_t>(flat.reactantSpecies.size()));
        flat.reactChangeOffsets.push_back(static_cast<uint32_t>(flat.reactChangeSpecies.size()));

        // Products
        for (std::size_t pIdx : rxn.productIndices) {
            if (pIdx >= flat.numSpecies) {
                throw std::runtime_error("Batch SSA: product index out of range");
            }
            flat.prodChangeSpecies.push_back(static_cast<uint32_t>(pIdx));
        }
        flat.prodChangeOffsets.push_back(static_cast<uint32_t>(flat.prodChangeSpecies.size()));
    }

    // Observables
    flat.obsOffsets.reserve(flat.numObservables + 1);
    flat.obsOffsets.push_back(0);
    for (const auto& group : compiledGroups) {
        flat.observableNames.push_back(group.name);
        for (const auto& entry : group.entries) {
            flat.obsSpecies.push_back(static_cast<uint32_t>(entry.first));
            flat.obsWeights.push_back(static_cast<float>(entry.second));
        }
        flat.obsOffsets.push_back(static_cast<uint32_t>(flat.obsSpecies.size()));
    }

    return flat;
}

// ============================================================================
// CPU Batch SSA Simulator (Single Worker & Multi-core)
// ============================================================================

CpuBatchSsaSimulator::CpuBatchSsaSimulator(const ast::Model& model, const GeneratedNetwork& network)
    : model_(model), network_(network) {}

BatchSsaMetrics CpuBatchSsaSimulator::simulateSingleWorker(const BatchSsaOptions& options) {
    auto tStartTotal = std::chrono::high_resolution_clock::now();

    auto tStartPrep = std::chrono::high_resolution_clock::now();
    OdeIntegrator integrator(model_, network_);
    const auto& compiledGroups = integrator.getCompiledGroups();
    std::size_t numObs = compiledGroups.size();
    std::size_t numPoints = options.nSteps + 1;
    std::size_t numSpecies = network_.species.size();

    auto tEndPrep = std::chrono::high_resolution_clock::now();
    double prepMs = std::chrono::duration<double, std::milli>(tEndPrep - tStartPrep).count();

    BatchSsaMetrics metrics;
    metrics.batchSize = options.batchSize;
    metrics.modelPrepTimeMs = prepMs;
    metrics.observableNames.reserve(numObs);
    for (const auto& g : compiledGroups) {
        metrics.observableNames.push_back(g.name);
    }
    metrics.trajectoryEventCounts.resize(options.batchSize, 0);
    metrics.finalSpecies.resize(options.batchSize * numSpecies, 0);
    metrics.finalObservables.resize(options.batchSize * numObs, 0.0f);

    std::vector<std::vector<double>> sumObs(numPoints, std::vector<double>(numObs, 0.0));
    std::vector<std::vector<double>> sumSqObs(numPoints, std::vector<double>(numObs, 0.0));

    auto tStartSim = std::chrono::high_resolution_clock::now();

    OdeOptions odeOpts;
    odeOpts.tStart = options.tStart;
    odeOpts.tEnd = options.tEnd;
    odeOpts.nSteps = options.nSteps;
    odeOpts.method = "ssa";
    odeOpts.maxSimSteps = options.maxSimSteps;

    uint64_t totalEvents = 0;

    for (std::size_t b = 0; b < options.batchSize; ++b) {
        odeOpts.seed = static_cast<unsigned int>(options.baseSeed + b);
        OdeResult res = integrator.integrate(odeOpts);

        if (b == 0) {
            metrics.timePoints.resize(res.timePoints.size());
            for (std::size_t i = 0; i < res.timePoints.size(); ++i) {
                metrics.timePoints[i] = static_cast<float>(res.timePoints[i]);
            }
        }

        totalEvents += res.eventCount;
        metrics.trajectoryEventCounts[b] = static_cast<uint32_t>(res.eventCount);

        // Record final species
        if (!res.concentrations.empty()) {
            const auto& finalConc = res.concentrations.back();
            for (std::size_t s = 0; s < numSpecies && s < finalConc.size(); ++s) {
                metrics.finalSpecies[b * numSpecies + s] = static_cast<int32_t>(std::round(finalConc[s]));
            }
        }

        // Record observables
        for (std::size_t step = 0; step < numPoints && step < res.observables.size(); ++step) {
            for (std::size_t g = 0; g < numObs && g < res.observables[step].size(); ++g) {
                double val = res.observables[step][g];
                sumObs[step][g] += val;
                sumSqObs[step][g] += val * val;
                if (step == numPoints - 1) {
                    metrics.finalObservables[b * numObs + g] = static_cast<float>(val);
                }
            }
        }
    }

    auto tEndSim = std::chrono::high_resolution_clock::now();
    double simMs = std::chrono::duration<double, std::milli>(tEndSim - tStartSim).count();
    auto tEndTotal = std::chrono::high_resolution_clock::now();
    double totalMs = std::chrono::duration<double, std::milli>(tEndTotal - tStartTotal).count();

    metrics.simulationTimeMs = simMs;
    metrics.totalWallTimeMs = totalMs;
    metrics.totalEvents = totalEvents;

    metrics.trajectoriesPerSecSim = (options.batchSize / (simMs / 1000.0));
    metrics.trajectoriesPerSecTotal = (options.batchSize / (totalMs / 1000.0));
    metrics.eventsPerSecSim = (totalEvents / (simMs / 1000.0));
    metrics.eventsPerSecTotal = (totalEvents / (totalMs / 1000.0));
    metrics.memoryUsageBytes = sizeof(OdeIntegrator) + options.batchSize * (numSpecies * sizeof(int32_t) + numObs * sizeof(float));

    // Compute means and standard deviations
    metrics.observableMeans.resize(numPoints, std::vector<float>(numObs, 0.0f));
    metrics.observableStdDevs.resize(numPoints, std::vector<float>(numObs, 0.0f));
    double N = static_cast<double>(options.batchSize);
    for (std::size_t step = 0; step < numPoints; ++step) {
        for (std::size_t g = 0; g < numObs; ++g) {
            double mean = sumObs[step][g] / N;
            double variance = std::max(0.0, (sumSqObs[step][g] / N) - (mean * mean));
            metrics.observableMeans[step][g] = static_cast<float>(mean);
            metrics.observableStdDevs[step][g] = static_cast<float>(std::sqrt(variance));
        }
    }
    detail::fillDoubleFields(metrics);
    return metrics;
}

BatchSsaMetrics CpuBatchSsaSimulator::simulateMultiCore(const BatchSsaOptions& options, unsigned int numThreads) {
    auto tStartTotal = std::chrono::high_resolution_clock::now();

    auto tStartPrep = std::chrono::high_resolution_clock::now();
    if (numThreads == 0) {
        numThreads = std::thread::hardware_concurrency();
    }
    if (numThreads == 0) numThreads = 1;

    // One compiled model for the whole pool. Constructing an OdeIntegrator
    // recompiles every reaction and observable from the AST, so the previous
    // one-per-worker layout paid numThreads+1 model compiles per batch (15+1
    // here) and held numThreads copies of the compiled network alive at once.
    //
    // Sharing is safe because the SSA path is re-entrant on this class:
    // integrate() dispatches to integrateSSA(), which reads only the compiled
    // reaction/group tables and writes exclusively to its own locals and the
    // OdeResult it returns. Every helper it reaches (outputTimes, parseStopIf,
    // updateGroups, stopConditionMet, computePropensity) is const and takes
    // its output through an out-parameter. The one mutable member,
    // groupValues_, is scratch for derivs(), which the SSA path never calls.
    OdeIntegrator integrator(model_, network_);
    const auto& compiledGroups = integrator.getCompiledGroups();
    std::size_t numObs = compiledGroups.size();
    std::size_t numPoints = options.nSteps + 1;
    std::size_t numSpecies = network_.species.size();

    auto tEndPrep = std::chrono::high_resolution_clock::now();
    double prepMs = std::chrono::duration<double, std::milli>(tEndPrep - tStartPrep).count();

    BatchSsaMetrics metrics;
    metrics.batchSize = options.batchSize;
    metrics.modelPrepTimeMs = prepMs;
    metrics.observableNames.reserve(numObs);
    for (const auto& g : compiledGroups) {
        metrics.observableNames.push_back(g.name);
    }
    metrics.trajectoryEventCounts.resize(options.batchSize, 0);
    metrics.finalSpecies.resize(options.batchSize * numSpecies, 0);
    metrics.finalObservables.resize(options.batchSize * numObs, 0.0f);

    struct WorkerResult {
        uint64_t workerEvents = 0;
        std::vector<std::vector<double>> sumObs;
        std::vector<std::vector<double>> sumSqObs;
        std::vector<float> timePoints;
    };

    auto tStartSim = std::chrono::high_resolution_clock::now();

    std::size_t batchSize = options.batchSize;
    std::size_t chunkSize = (batchSize + numThreads - 1) / numThreads;

    std::vector<std::future<WorkerResult>> futures;
    futures.reserve(numThreads);

    for (unsigned int t = 0; t < numThreads; ++t) {
        std::size_t startIdx = t * chunkSize;
        std::size_t endIdx = std::min(startIdx + chunkSize, batchSize);
        if (startIdx >= endIdx) continue;

        futures.push_back(std::async(std::launch::async, [this, &options, &integrator, startIdx, endIdx, numPoints, numObs, numSpecies, &metrics]() {
            WorkerResult wRes;
            wRes.sumObs.resize(numPoints, std::vector<double>(numObs, 0.0));
            wRes.sumSqObs.resize(numPoints, std::vector<double>(numObs, 0.0));

            OdeOptions odeOpts;
            odeOpts.tStart = options.tStart;
            odeOpts.tEnd = options.tEnd;
            odeOpts.nSteps = options.nSteps;
            odeOpts.method = "ssa";
            odeOpts.maxSimSteps = options.maxSimSteps;

            for (std::size_t b = startIdx; b < endIdx; ++b) {
                odeOpts.seed = static_cast<unsigned int>(options.baseSeed + b);
                OdeResult res = integrator.integrate(odeOpts);

                if (wRes.timePoints.empty() && !res.timePoints.empty()) {
                    wRes.timePoints.resize(res.timePoints.size());
                    for (std::size_t i = 0; i < res.timePoints.size(); ++i) {
                        wRes.timePoints[i] = static_cast<float>(res.timePoints[i]);
                    }
                }

                wRes.workerEvents += res.eventCount;
                metrics.trajectoryEventCounts[b] = static_cast<uint32_t>(res.eventCount);

                if (!res.concentrations.empty()) {
                    const auto& finalConc = res.concentrations.back();
                    for (std::size_t s = 0; s < numSpecies && s < finalConc.size(); ++s) {
                        metrics.finalSpecies[b * numSpecies + s] = static_cast<int32_t>(std::round(finalConc[s]));
                    }
                }

                for (std::size_t step = 0; step < numPoints && step < res.observables.size(); ++step) {
                    for (std::size_t g = 0; g < numObs && g < res.observables[step].size(); ++g) {
                        double val = res.observables[step][g];
                        wRes.sumObs[step][g] += val;
                        wRes.sumSqObs[step][g] += val * val;
                        if (step == numPoints - 1) {
                            metrics.finalObservables[b * numObs + g] = static_cast<float>(val);
                        }
                    }
                }
            }
            return wRes;
        }));
    }

    uint64_t totalEvents = 0;
    std::vector<std::vector<double>> totalSumObs(numPoints, std::vector<double>(numObs, 0.0));
    std::vector<std::vector<double>> totalSumSqObs(numPoints, std::vector<double>(numObs, 0.0));

    for (auto& f : futures) {
        WorkerResult wRes = f.get();
        totalEvents += wRes.workerEvents;
        if (metrics.timePoints.empty() && !wRes.timePoints.empty()) {
            metrics.timePoints = std::move(wRes.timePoints);
        }
        for (std::size_t step = 0; step < numPoints; ++step) {
            for (std::size_t g = 0; g < numObs; ++g) {
                totalSumObs[step][g] += wRes.sumObs[step][g];
                totalSumSqObs[step][g] += wRes.sumSqObs[step][g];
            }
        }
    }

    auto tEndSim = std::chrono::high_resolution_clock::now();
    double simMs = std::chrono::duration<double, std::milli>(tEndSim - tStartSim).count();
    auto tEndTotal = std::chrono::high_resolution_clock::now();
    double totalMs = std::chrono::duration<double, std::milli>(tEndTotal - tStartTotal).count();

    metrics.simulationTimeMs = simMs;
    metrics.totalWallTimeMs = totalMs;
    metrics.totalEvents = totalEvents;

    metrics.trajectoriesPerSecSim = (options.batchSize / (simMs / 1000.0));
    metrics.trajectoriesPerSecTotal = (options.batchSize / (totalMs / 1000.0));
    metrics.eventsPerSecSim = (totalEvents / (simMs / 1000.0));
    metrics.eventsPerSecTotal = (totalEvents / (totalMs / 1000.0));
    // One compiled model backs the whole pool, not one per worker.
    metrics.memoryUsageBytes = sizeof(OdeIntegrator) +
                              options.batchSize * (numSpecies * sizeof(int32_t) + numObs * sizeof(float));

    metrics.observableMeans.resize(numPoints, std::vector<float>(numObs, 0.0f));
    metrics.observableStdDevs.resize(numPoints, std::vector<float>(numObs, 0.0f));
    double N = static_cast<double>(options.batchSize);
    for (std::size_t step = 0; step < numPoints; ++step) {
        for (std::size_t g = 0; g < numObs; ++g) {
            double mean = totalSumObs[step][g] / N;
            double variance = std::max(0.0, (totalSumSqObs[step][g] / N) - (mean * mean));
            metrics.observableMeans[step][g] = static_cast<float>(mean);
            metrics.observableStdDevs[step][g] = static_cast<float>(std::sqrt(variance));
        }
    }
    detail::fillDoubleFields(metrics);
    return metrics;
}

} // namespace bng::engine
