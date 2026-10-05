// Regression tests for three independently-fixed defects.
//
// Each test names the defect it pins and, where the behaviour is a semantic
// choice rather than an obvious bug, records which oracle settled it.
#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <numeric>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_set>
#include <vector>

#include "engine/BatchSsa.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

namespace {

std::unique_ptr<ast::Model> parse(const std::string& source) {
    return parser::parseModel(source);
}

// A()=10 and B()=3 with one observable per threshold, so a single run shows
// every count-filter spelling side by side.
const char* kCountFilterModel = R"(
begin species
  A() 10
  B() 3
end species
begin reaction rules
  A() -> B() 0.001
end reaction rules
begin observables
  Molecules Agt0 A()>0
  Molecules Agt5 A()>5
  Molecules Agt9 A()>9
  Molecules Agt10 A()>10
  Molecules Agt99 A()>99
  Molecules Bgt2 B()>2
  Molecules All A()
end observables
)";

std::vector<double> observableAtTimeZero(ast::Model& model, std::size_t obs) {
    engine::NetworkGenerator generator(model);
    auto network = generator.generateNative();
    engine::OdeIntegrator integrator(model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 1.0;
    options.nSteps = 1;
    options.seed = 1;
    const auto result = integrator.integrate(options);
    REQUIRE(result.observables.size() > 0);
    REQUIRE(result.observables[0].size() > obs);
    return result.observables[0];
}

std::vector<double> speciesAtTimeZero(ast::Model& model, std::size_t species) {
    engine::NetworkGenerator generator(model);
    auto network = generator.generateNative();
    engine::OdeIntegrator integrator(model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 1.0;
    options.nSteps = 1;
    options.seed = 1;
    const auto result = integrator.integrate(options);
    REQUIRE(result.concentrations.size() > 0);
    REQUIRE(result.concentrations[0].size() > species);
    return result.concentrations[0];
}

} // namespace

// ---------------------------------------------------------------------------
// Defect: a stoichiometric comparison on a Molecules observable was applied to
// the per-species EMBEDDING count, so `A()>5` on one species holding 10
// molecules compared 1 > 5 and reported 0.
//
// BNG2 2.9.3 is the oracle and it is unambiguous: Perl2/Observable.pm tests
// `$patt->Quantifier` only inside the `Type eq "Species"` branch (lines
// 278-292) and the `Molecules` branch (lines 241-256) never inspects it. So in
// BNG2 `Molecules Q A()>5` and `Molecules Q A()` are the same observable.
// Measured on BNG2 with A()=10, every threshold in this model returns 10.
// ---------------------------------------------------------------------------
TEST_CASE("Molecules count filters are inert, matching BNG2", "[correctness][observables]") {
    auto model = parse(kCountFilterModel);
    const auto values = observableAtTimeZero(*model, 0);

    // Column order follows the model's observables block.
    REQUIRE(model->getObservables().at(0).getName() == "Agt0");
    REQUIRE(model->getObservables().at(4).getName() == "Agt99");
    REQUIRE(model->getObservables().at(5).getName() == "Bgt2");
    REQUIRE(model->getObservables().at(6).getName() == "All");

    REQUIRE_THAT(values.at(0), Catch::Matchers::WithinAbs(10.0, 1e-9));  // A()>0
    REQUIRE_THAT(values.at(1), Catch::Matchers::WithinAbs(10.0, 1e-9));  // A()>5  was 0
    REQUIRE_THAT(values.at(2), Catch::Matchers::WithinAbs(10.0, 1e-9));  // A()>9  was 0
    REQUIRE_THAT(values.at(3), Catch::Matchers::WithinAbs(10.0, 1e-9));  // A()>10 was 0
    REQUIRE_THAT(values.at(4), Catch::Matchers::WithinAbs(10.0, 1e-9));  // A()>99 was 0
    REQUIRE_THAT(values.at(5), Catch::Matchers::WithinAbs(3.0, 1e-9));   // B()>2  was 0
    REQUIRE_THAT(values.at(6), Catch::Matchers::WithinAbs(10.0, 1e-9));  // A()
}

// The Species branch DOES honour the comparison in BNG2, and this engine
// already matched it. That path must not change with the fix above, so it is
// pinned rather than assumed: Species A()>0 is 1, A()>99 is 0, plain A() is 1.
//
// Observable indices: 0 = Species Agt0, 1 = Species Agt99, 2 = Species All.
TEST_CASE("Species count filters keep honouring the comparison", "[correctness][observables]") {
    auto model = parse(R"(
begin species
  A() 10
  B() 3
end species
begin reaction rules
  A() -> B() 0.001
end reaction rules
begin observables
  Species Agt0 A()>0
  Species Agt99 A()>99
  Species All A()
end observables
)");
    // Measured against BNG2 2.9.3 on the same model: 10, 0, 10 -- identical.
    // The Species branch contributes the molecule count of a species whose
    // embedding count satisfies the comparison, not a clamped 1.
    const auto values = observableAtTimeZero(*model, 0);
    REQUIRE_THAT(values.at(0), Catch::Matchers::WithinAbs(10.0, 1e-9));
    REQUIRE_THAT(values.at(1), Catch::Matchers::WithinAbs(0.0, 1e-9));
    REQUIRE_THAT(values.at(2), Catch::Matchers::WithinAbs(10.0, 1e-9));
}

// ---------------------------------------------------------------------------
// Defect: batch-SSA per-trajectory seeds were `base + traj`, so two batch runs
// whose base seeds differ by delta shared B - delta of their trajectories.
//
// Acceptance, from the reporter's measurement on the Bernoulli reproducer
// (alpha=0.4, beta=0.1, t_end=200, B=20000; exact stationary mean 0.8):
//   (a) adjacent base seeds stop agreeing exactly
//   (b) the across-seed spread of near-adjacent base seeds reaches the spread
//       of far-apart base seeds
//   (c) the reported per-batch sd stays at the analytic 0.4
//
// (a) and (b) are the defect; (c) is the guard that a decorrelation "fix" did
// not achieve it by breaking within-batch independence.
// ---------------------------------------------------------------------------
namespace {

// Two-state reversible Markov chain. The stationary open fraction is exactly
// beta/(alpha+beta) = 0.1/0.5 = 0.2... expressed as a molecule observable it is
// the population, whose stationary mean is 0.8 of the single conserved pool.
const char* kBernoulliModel = R"(
begin species
  C(s~c) 1
  O(s~o) 0
end species
begin reaction rules
  C(s~c) -> O(s~o) 0.4
  O(s~o) -> C(s~c) 0.1
end reaction rules
begin observables
  Molecules Nopen O(s~o)
end observables
)";

double batchMean(unsigned int seed) {
    auto model = parse(kBernoulliModel);
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);

    engine::OdeOptions options;
    options.method = "ssa";
    options.tStart = 0.0;
    options.tEnd = 200.0;
    options.nSteps = 1;
    options.batchSize = 2000;
    options.seed = seed;
    const auto result = integrator.integrate(options);
    REQUIRE(result.observables.size() > 0);
    REQUIRE(result.observables.back().size() > 0);
    return result.observables.back().front();
}

double batchStdDev(unsigned int seed) {
    auto model = parse(kBernoulliModel);
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);

    engine::OdeOptions options;
    options.method = "ssa";
    options.tStart = 0.0;
    options.tEnd = 200.0;
    options.nSteps = 1;
    options.batchSize = 2000;
    options.seed = seed;
    const auto result = integrator.integrate(options);
    REQUIRE(result.batchObsStdDevs.size() > 0);
    REQUIRE(result.batchObsStdDevs.back().size() > 0);
    return result.batchObsStdDevs.back().front();
}

} // namespace

TEST_CASE("adjacent batch base seeds do not produce identical batches",
          "[correctness][batch-ssa]") {
    // Before the fix these three were equal to every digit, because base+traj
    // overlapped by all but one trajectory out of 2000.
    const double a = batchMean(5000);
    const double b = batchMean(5001);
    const double c = batchMean(5002);
    REQUIRE((a != b || b != c));
}

TEST_CASE("adjacent batch base seeds do not reuse trajectory RNG keys",
          "[correctness][batch-ssa]") {
    constexpr uint64_t baseSeed = 5000;
    constexpr std::size_t batchSize = 512;

    // The simulation consumes the low 32 bits and maps zero to one. Under the
    // old `base + trajectory` derivation, adjacent bases share 511 of these
    // 512 keys. Check key reuse directly instead of inferring it from the
    // noisy difference between two small samples of batch means.
    std::unordered_set<uint32_t> firstBatch;
    std::unordered_set<uint32_t> secondBatch;
    for (std::size_t trajectory = 0; trajectory < batchSize; ++trajectory) {
        firstBatch.insert(engine::batchTrajectoryEngineSeed(baseSeed, trajectory));
        secondBatch.insert(engine::batchTrajectoryEngineSeed(baseSeed + 1, trajectory));
    }

    std::size_t sharedSeeds = 0;
    for (const auto seed : firstBatch) {
        if (secondBatch.count(seed) != 0) ++sharedSeeds;
    }

    INFO("shared trajectory RNG keys " << sharedSeeds << " / " << batchSize);
    REQUIRE(firstBatch.size() == batchSize);
    REQUIRE(secondBatch.size() == batchSize);
    REQUIRE(sharedSeeds == 0);
}

TEST_CASE("batch trajectory RNG keys preserve the 32-bit nonzero seed contract",
          "[correctness][batch-ssa]") {
    REQUIRE(engine::batchEngineSeed(0ULL) == 1u);
    REQUIRE(engine::batchEngineSeed(0x0000000100000000ULL) == 1u);
    REQUIRE(engine::batchEngineSeed(0x12345678ABCDEF01ULL) == 0xABCDEF01u);

    const engine::BatchSsaOptions defaults;
    REQUIRE(defaults.baseSeed == 42u);
    REQUIRE(engine::batchTrajectoryEngineSeed(defaults.baseSeed, 0) == 0x2FEB6E95u);
    REQUIRE(engine::batchTrajectoryEngineSeed(0, 0) == 0x7B1DCDAFu);
}

TEST_CASE("per-batch std dev still matches the analytic value", "[correctness][batch-ssa]") {
    // batchObsStdDevs is the spread of the PER-TRAJECTORY observable values,
    // whose sd is the Bernoulli(0.8) sd sqrt(0.8*0.2) = 0.4. Before the fix this
    // also held -- the defect was in seed-to-seed decorrelation, not in
    // within-batch sampling -- so this is the guard against a fix that buys
    // decorrelation by thinning the effective batch.
    const double expected = std::sqrt(0.8 * 0.2);
    for (unsigned int seed : {11u, 99u, 4242u}) {
        INFO("seed " << seed);
        REQUIRE_THAT(batchStdDev(seed), Catch::Matchers::WithinRel(expected, 0.05));
    }
}

// ---------------------------------------------------------------------------
// The seed derivation itself, checked directly rather than only through a
// batch. This is the property the CPU pool and the GPU kernels must share:
// tests/test_batch_ssa_statistical_parity.py compares the two at the same base
// seed, so the derivation has to be a pure function of (baseSeed, trajectory).
// ---------------------------------------------------------------------------
TEST_CASE("batchTrajectorySeed decorrelates adjacent base seeds", "[correctness][batch-ssa]") {
    std::vector<uint64_t> seeds;
    for (uint64_t base = 5000; base < 5003; ++base) {
        for (std::size_t traj = 0; traj < 8; ++traj) {
            seeds.push_back(engine::batchTrajectorySeed(base, traj));
        }
    }
    const auto distinct = std::unordered_set<uint64_t>(seeds.begin(), seeds.end());
    REQUIRE(distinct.size() == seeds.size());

    // Deterministic: the same inputs must give the same seed every time, or a
    // base seed would no longer pin a batch.
    REQUIRE(engine::batchTrajectorySeed(5000, 0) == engine::batchTrajectorySeed(5000, 0));
    REQUIRE(engine::batchTrajectorySeed(5000, 0) != engine::batchTrajectorySeed(5000, 1));

    // No low-entropy collisions across a realistic range of bases.
    std::unordered_set<uint64_t> wide;
    for (uint64_t base = 1; base <= 256; ++base) {
        for (std::size_t traj = 0; traj < 64; ++traj) {
            wide.insert(engine::batchTrajectorySeed(base * 1000, traj));
        }
    }
    REQUIRE(wide.size() == 256 * 64);
}
