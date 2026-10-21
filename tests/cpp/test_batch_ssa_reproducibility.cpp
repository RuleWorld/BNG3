// Reproducibility of the multi-worker CPU batch-SSA pool.
//
// The pool shares one OdeIntegrator across its worker threads.  The observable
// scratch that a state-dependent rate law resolves against therefore has to be
// per-worker: when it was a member of the shared integrator, one worker's
// rate expression could read another worker's trajectory state, and the
// ensemble produced for a fixed seed differed between runs of the same binary.
//
// The regression this file guards is a data race, so it is asserted the way a
// race shows up: two runs of the same binary with the same seed must produce
// the same ensemble, and the pool must agree with the single-worker pool,
// whose result is free of any cross-worker interference.

#include <catch2/catch_test_macros.hpp>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "engine/BatchSsa.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

namespace {

// The two models live under tests/fixtures/batch_ssa/ so that the benchmark
// driver (benchmarks/batch_ssa/bench_batch_ssa.cpp) can reproduce the same
// measurement outside the test binary.
std::string fixturePath(const std::string& name) {
    return std::string(BNG3_SOURCE_DIR) + "/tests/fixtures/batch_ssa/" + name;
}

// A model whose second reaction's rate law reads an observable, i.e. a
// state-dependent rate law.  The observable is the value the shared scratch
// used to carry between the workers of the batch pool.
std::unique_ptr<ast::Model> parseStateDependentRateModel() {
    return parser::parseModelFromFile(
        fixturePath("functional_rate_observable.bngl"));
}

// The same network without a state-dependent rate law: every rate is a
// constant, so the observable scratch is never touched.
std::unique_ptr<ast::Model> parseConstantRateModel() {
    return parser::parseModelFromFile(fixturePath("constant_rate.bngl"));
}

engine::BatchSsaOptions poolOptions(std::size_t batchSize) {
    engine::BatchSsaOptions options;
    options.tStart = 0.0;
    options.tEnd = 5.0;
    options.nSteps = 10;
    options.baseSeed = 42;
    options.batchSize = batchSize;
    return options;
}

// Every number the pool reports, compared exactly.  A reproducibility check
// that tolerates a rounding difference would not detect a race: the race
// changes which trajectory a rate law sees, not how a number is rounded.
void requireSameEnsemble(const engine::BatchSsaMetrics& left,
                         const engine::BatchSsaMetrics& right) {
    REQUIRE(left.batchSize == right.batchSize);
    REQUIRE(left.totalEvents == right.totalEvents);
    REQUIRE(left.observableNames == right.observableNames);
    REQUIRE(left.timePoints == right.timePoints);
    REQUIRE(left.trajectoryEventCounts == right.trajectoryEventCounts);
    REQUIRE(left.finalSpecies == right.finalSpecies);
    REQUIRE(left.finalObservables == right.finalObservables);
    REQUIRE(left.observableMeans == right.observableMeans);
    REQUIRE(left.observableStdDevs == right.observableStdDevs);
    REQUIRE(left.meanObservables == right.meanObservables);
    REQUIRE(left.stdObservables == right.stdObservables);
}

} // namespace

TEST_CASE("the multi-worker batch SSA pool is reproducible for a state-dependent rate law",
          "[BatchSsa][Reproducibility]") {
    auto model = parseStateDependentRateModel();
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();

    // The model must actually exercise the state-dependent path, otherwise
    // the assertions below would hold for the wrong reason.
    REQUIRE(engine::OdeIntegrator(*model, network).hasFunctionalRates());

    engine::CpuBatchSsaSimulator simulator(*model, network);
    const auto options = poolOptions(400);

    const auto first = simulator.simulateMultiCore(options, 4);
    const auto second = simulator.simulateMultiCore(options, 4);

    // The same binary, the same seed, the same batch: the same ensemble.
    requireSameEnsemble(first, second);
    REQUIRE(first.totalEvents > 0);
}

TEST_CASE("the multi-worker batch SSA pool agrees with the single-worker pool "
          "for a state-dependent rate law",
          "[BatchSsa][Reproducibility]") {
    auto model = parseStateDependentRateModel();
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();

    engine::CpuBatchSsaSimulator simulator(*model, network);
    const auto options = poolOptions(400);

    const auto multi = simulator.simulateMultiCore(options, 4);
    const auto single = simulator.simulateSingleWorker(options);

    // Every trajectory is seeded from (baseSeed, trajectory index), so the
    // worker that runs it must not change it.  A rate law that resolved
    // against a shared observable scratch would break this: the trajectory
    // would follow another worker's state.
    REQUIRE(single.trajectoryEventCounts == multi.trajectoryEventCounts);
    REQUIRE(single.finalSpecies == multi.finalSpecies);
    REQUIRE(single.finalObservables == multi.finalObservables);
}

TEST_CASE("the multi-worker batch SSA pool is reproducible for a constant rate model",
          "[BatchSsa][Reproducibility]") {
    auto model = parseConstantRateModel();
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();

    REQUIRE_FALSE(engine::OdeIntegrator(*model, network).hasFunctionalRates());

    engine::CpuBatchSsaSimulator simulator(*model, network);
    const auto options = poolOptions(400);

    const auto first = simulator.simulateMultiCore(options, 4);
    const auto second = simulator.simulateMultiCore(options, 4);

    requireSameEnsemble(first, second);
    REQUIRE(first.totalEvents > 0);
}
