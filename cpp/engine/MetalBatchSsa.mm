#include "MetalBatchSsa.hpp"
#include "ast/Model.hpp"

#import <Metal/Metal.h>
#import <Foundation/Foundation.h>

#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>
#include <numeric>
#include <thread>
#include <future>
#include <algorithm>

namespace bng::engine {

namespace {
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
} // anonymous namespace


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
            "Metal SSA prototype: unsupported rate law (model contains functional rates); failing closed."
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
                "Metal SSA prototype: unsupported rate law (reaction " + std::to_string(r) +
                " has functional rate expression); failing closed."
            );
        }

        // Fail-closed rule 3: TotalRate modifier
        if (rxn.isTotalRate) {
            throw std::runtime_error(
                "Metal SSA prototype: unsupported rate law (reaction " + std::to_string(r) +
                " specifies TotalRate); failing closed."
            );
        }

        // Fail-closed rule 4: invalid rate constants (negative, NaN, inf)
        if (rxn.rateConstant < 0.0 || std::isnan(rxn.rateConstant) || std::isinf(rxn.rateConstant)) {
            throw std::runtime_error(
                "Metal SSA prototype: unsupported rate law (reaction " + std::to_string(r) +
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
                throw std::runtime_error("Metal SSA prototype: reactant index out of range");
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
                throw std::runtime_error("Metal SSA prototype: product index out of range");
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
    fillDoubleFields(metrics);
    return metrics;
}

BatchSsaMetrics CpuBatchSsaSimulator::simulateMultiCore(const BatchSsaOptions& options, unsigned int numThreads) {
    auto tStartTotal = std::chrono::high_resolution_clock::now();

    auto tStartPrep = std::chrono::high_resolution_clock::now();
    if (numThreads == 0) {
        numThreads = std::thread::hardware_concurrency();
    }
    if (numThreads == 0) numThreads = 1;

    OdeIntegrator refIntegrator(model_, network_);
    const auto& compiledGroups = refIntegrator.getCompiledGroups();
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

        futures.push_back(std::async(std::launch::async, [this, &options, startIdx, endIdx, numPoints, numObs, numSpecies, &metrics]() {
            WorkerResult wRes;
            wRes.sumObs.resize(numPoints, std::vector<double>(numObs, 0.0));
            wRes.sumSqObs.resize(numPoints, std::vector<double>(numObs, 0.0));

            // Independent OdeIntegrator per thread for thread safety
            OdeIntegrator threadIntegrator(model_, network_);

            OdeOptions odeOpts;
            odeOpts.tStart = options.tStart;
            odeOpts.tEnd = options.tEnd;
            odeOpts.nSteps = options.nSteps;
            odeOpts.method = "ssa";
            odeOpts.maxSimSteps = options.maxSimSteps;

            for (std::size_t b = startIdx; b < endIdx; ++b) {
                odeOpts.seed = static_cast<unsigned int>(options.baseSeed + b);
                OdeResult res = threadIntegrator.integrate(odeOpts);

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
    metrics.memoryUsageBytes = (numThreads * sizeof(OdeIntegrator)) +
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
    fillDoubleFields(metrics);
    return metrics;
}

// ============================================================================
// Metal GPU Batch SSA Simulator
// ============================================================================

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

struct MetalBatchSsaSimulator::Impl {
    id<MTLDevice> device = nil;
    id<MTLCommandQueue> commandQueue = nil;
    id<MTLComputePipelineState> pipelineState = nil;

    // GPU Buffers for network structure
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

    Impl(const FlattenedReactionNetwork& fn) : flatNet(fn) {
        auto t0 = std::chrono::high_resolution_clock::now();
        @autoreleasepool {
            device = MTLCreateSystemDefaultDevice();
            if (!device) {
                throw std::runtime_error("MetalBatchSsaSimulator: No Metal device available on this system.");
            }
            commandQueue = [device newCommandQueue];

            NSError* error = nil;
            NSString* src = [NSString stringWithUTF8String:kMetalSsaShaderSource];
            id<MTLLibrary> library = [device newLibraryWithSource:src options:nil error:&error];
            if (!library) {
                std::string errStr = error ? [[error localizedDescription] UTF8String] : "Unknown error";
                throw std::runtime_error("MetalBatchSsaSimulator: Shader compile error: " + errStr);
            }

            id<MTLFunction> kernel = [library newFunctionWithName:@"metal_batch_direct_ssa"];
            pipelineState = [device newComputePipelineStateWithFunction:kernel error:&error];
            if (!pipelineState) {
                std::string errStr = error ? [[error localizedDescription] UTF8String] : "Unknown error";
                throw std::runtime_error("MetalBatchSsaSimulator: Pipeline state error: " + errStr);
            }

            // Create network buffers
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
        auto t1 = std::chrono::high_resolution_clock::now();
        modelPrepTimeMs = std::chrono::duration<double, std::milli>(t1 - t0).count();
    }
};

bool MetalBatchSsaSimulator::isMetalAvailable() {
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        return (dev != nil);
    }
}

MetalBatchSsaSimulator::MetalBatchSsaSimulator(const FlattenedReactionNetwork& flatNet)
    : impl_(std::make_unique<Impl>(flatNet)) {}

MetalBatchSsaSimulator::~MetalBatchSsaSimulator() = default;

struct SimParams {
    uint32_t numSpecies;
    uint32_t numReactions;
    uint32_t numObservables;
    uint32_t numOutputPoints;
    uint32_t batchSize;
    uint32_t maxSimSteps;
    float tStart;
    float tEnd;
    uint64_t baseSeed;
};

BatchSsaMetrics MetalBatchSsaSimulator::simulate(const BatchSsaOptions& options) {
    auto tStartTotal = std::chrono::high_resolution_clock::now();

    BatchSsaMetrics metrics;
    metrics.batchSize = options.batchSize;
    metrics.modelPrepTimeMs = impl_->modelPrepTimeMs;
    metrics.observableNames = impl_->flatNet.observableNames;

    uint32_t numPoints = options.nSteps + 1;
    uint32_t numSpecies = impl_->flatNet.numSpecies;
    uint32_t numObs = impl_->flatNet.numObservables;
    uint32_t batchSize = static_cast<uint32_t>(options.batchSize);

    // Compute uniform output times
    std::vector<float> h_outputTimes(numPoints);
    float dt = static_cast<float>((options.tEnd - options.tStart) / options.nSteps);
    for (uint32_t i = 0; i < numPoints; ++i) {
        h_outputTimes[i] = static_cast<float>(options.tStart + i * dt);
    }
    metrics.timePoints = h_outputTimes;

    SimParams params;
    params.numSpecies = numSpecies;
    params.numReactions = impl_->flatNet.numReactions;
    params.numObservables = numObs;
    params.numOutputPoints = numPoints;
    params.batchSize = batchSize;
    params.maxSimSteps = static_cast<uint32_t>(options.maxSimSteps);
    params.tStart = static_cast<float>(options.tStart);
    params.tEnd = static_cast<float>(options.tEnd);
    params.baseSeed = options.baseSeed;

    std::size_t stateBytes = batchSize * numSpecies * sizeof(int32_t);
    std::size_t obsBytes = batchSize * numPoints * numObs * sizeof(float);
    std::size_t eventBytes = batchSize * sizeof(uint32_t);
    std::size_t timesBytes = numPoints * sizeof(float);
    std::size_t dynamicMemoryBytes = stateBytes + obsBytes + eventBytes + timesBytes;

    metrics.memoryUsageBytes = impl_->staticMemoryBytes + dynamicMemoryBytes;

    // Host -> Device Transfer
    auto tStartH2D = std::chrono::high_resolution_clock::now();

    id<MTLBuffer> bufParams = nil;
    id<MTLBuffer> bufOutputTimes = nil;
    id<MTLBuffer> bufStates = nil;
    id<MTLBuffer> bufObservables = nil;
    id<MTLBuffer> bufEventCounts = nil;

    @autoreleasepool {
        bufParams = [impl_->device newBufferWithBytes:&params length:sizeof(SimParams) options:MTLResourceStorageModeShared];
        bufOutputTimes = [impl_->device newBufferWithBytes:h_outputTimes.data() length:timesBytes options:MTLResourceStorageModeShared];
        bufStates = [impl_->device newBufferWithLength:stateBytes options:MTLResourceStorageModeShared];
        bufObservables = [impl_->device newBufferWithLength:(obsBytes > 0 ? obsBytes : sizeof(float)) options:MTLResourceStorageModeShared];
        bufEventCounts = [impl_->device newBufferWithLength:eventBytes options:MTLResourceStorageModeShared];
    }

    auto tEndH2D = std::chrono::high_resolution_clock::now();
    double h2dMs = std::chrono::duration<double, std::milli>(tEndH2D - tStartH2D).count();
    metrics.hostToDeviceTransferMs = h2dMs;

    // GPU Simulation Execution
    auto tStartSim = std::chrono::high_resolution_clock::now();

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
        NSUInteger maxThreads = impl_->pipelineState.maxTotalThreadsPerThreadgroup;
        NSUInteger threadGroupSize = (maxThreads < 64) ? maxThreads : 64;
        MTLSize tgSize = MTLSizeMake(threadGroupSize, 1, 1);

        [enc dispatchThreads:gridSize threadsPerThreadgroup:tgSize];
        [enc endEncoding];

        [cmdBuf commit];
        [cmdBuf waitUntilCompleted];
    }

    auto tEndSim = std::chrono::high_resolution_clock::now();
    double simMs = std::chrono::duration<double, std::milli>(tEndSim - tStartSim).count();
    metrics.simulationTimeMs = simMs;

    // Device -> Host Transfer
    auto tStartD2H = std::chrono::high_resolution_clock::now();

    metrics.trajectoryEventCounts.resize(batchSize);
    std::memcpy(metrics.trajectoryEventCounts.data(), [bufEventCounts contents], eventBytes);

    metrics.finalSpecies.resize(batchSize * numSpecies);
    std::memcpy(metrics.finalSpecies.data(), [bufStates contents], stateBytes);

    std::vector<float> allObs;
    if (obsBytes > 0) {
        allObs.resize(batchSize * numPoints * numObs);
        std::memcpy(allObs.data(), [bufObservables contents], obsBytes);
    }

    if (obsBytes > 0) {
        metrics.finalObservables.resize(batchSize * numObs, 0.0f);
        for (uint32_t b = 0; b < batchSize; ++b) {
            for (uint32_t g = 0; g < numObs; ++g) {
                metrics.finalObservables[b * numObs + g] = allObs[b * numPoints * numObs + (numPoints - 1) * numObs + g];
            }
        }
    }
    auto tEndD2H = std::chrono::high_resolution_clock::now();
    double d2hMs = std::chrono::duration<double, std::milli>(tEndD2H - tStartD2H).count();
    metrics.deviceToHostTransferMs = d2hMs;

    auto tEndTotal = std::chrono::high_resolution_clock::now();
    double totalMs = std::chrono::duration<double, std::milli>(tEndTotal - tStartTotal).count();
    metrics.totalWallTimeMs = totalMs;

    // Compute total events
    uint64_t totalEvents = 0;
    for (uint32_t count : metrics.trajectoryEventCounts) {
        totalEvents += count;
    }
    metrics.totalEvents = totalEvents;

    metrics.trajectoriesPerSecSim = (options.batchSize / (simMs / 1000.0));
    metrics.trajectoriesPerSecTotal = (options.batchSize / (totalMs / 1000.0));
    metrics.eventsPerSecSim = (totalEvents / (simMs / 1000.0));
    metrics.eventsPerSecTotal = (totalEvents / (totalMs / 1000.0));

    // Compute observable trajectory means & stddevs
    metrics.observableMeans.resize(numPoints, std::vector<float>(numObs, 0.0f));
    metrics.observableStdDevs.resize(numPoints, std::vector<float>(numObs, 0.0f));

    if (numObs > 0) {
        double N = static_cast<double>(batchSize);
        for (uint32_t step = 0; step < numPoints; ++step) {
            for (uint32_t g = 0; g < numObs; ++g) {
                double sum = 0.0;
                double sumSq = 0.0;
                for (uint32_t b = 0; b < batchSize; ++b) {
                    double val = allObs[b * numPoints * numObs + step * numObs + g];
                    sum += val;
                    sumSq += val * val;
                }
                double mean = sum / N;
                double variance = std::max(0.0, (sumSq / N) - (mean * mean));
                metrics.observableMeans[step][g] = static_cast<float>(mean);
                metrics.observableStdDevs[step][g] = static_cast<float>(std::sqrt(variance));
            }
        }
    }
    fillDoubleFields(metrics);
    return metrics;
}

} // namespace bng::engine
