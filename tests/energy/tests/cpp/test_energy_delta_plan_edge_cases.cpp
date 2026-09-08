#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "compile/energy/EnergyDeltaPlan.hpp"
#include "energy_test_helpers.hpp"

using bng::compile::energy::ConditionKind;
using bng::compile::energy::EnergyCondition;
using bng::compile::energy::EnergyDeltaPlan;
using bng::compile::energy::EnergyDeltaStrategy;
using bng::compile::energy::EnergyTerm;

namespace {
EnergyCondition bound_condition(int reactant, const char* molecule, const char* component) {
    EnergyCondition c;
    c.kind = ConditionKind::Bond;
    c.reactantIndex = reactant;
    c.moleculeType = molecule;
    c.componentName = component;
    c.expectedBound = true;
    return c;
}
}

TEST_CASE("constant EnergyDeltaPlan accepts only mask zero") {
    const auto plan = EnergyDeltaPlan::constant(2.25);
    REQUIRE(plan.isConstant());
    REQUIRE(plan.isExecutable());
    CHECK(plan.validConditionMask() == 0);
    CHECK(plan.maskIsValid(0));
    CHECK_FALSE(plan.maskIsValid(1));
    REQUIRE(plan.tryDeltaG(0).has_value());
    CHECK(*plan.tryDeltaG(0) == Catch::Approx(2.25));
    CHECK_FALSE(plan.tryDeltaG(1).has_value());
}

TEST_CASE("materialized fallback is never directly executable") {
    const auto plan = EnergyDeltaPlan::materializedFallback();
    CHECK(plan.strategy() == EnergyDeltaStrategy::MaterializedFallback);
    CHECK_FALSE(plan.isExecutable());
    CHECK_FALSE(plan.tryDeltaG(0).has_value());
    CHECK_FALSE(plan.tryArrheniusFactor(0, 0.5, 2.478, true).has_value());
    CHECK_FALSE(plan.buildArrheniusTable(0.5, 2.478, true).has_value());
}

TEST_CASE("factorized plan rejects zero and out-of-range term masks") {
    const auto c0 = bound_condition(0, "A", "x");
    const auto c1 = bound_condition(0, "A", "y");

    CHECK_FALSE(EnergyDeltaPlan::factorized(0.0, {c0, c1}, {{1.0, 0, 0}}).has_value());
    CHECK_FALSE(EnergyDeltaPlan::factorized(0.0, {c0, c1}, {{1.0, 4, 0}}).has_value());
}

TEST_CASE("factorized plan rejects nonfinite energy and excessive predicate count") {
    std::vector<EnergyCondition> conditions;
    for (int i = 0; i < 64; ++i) conditions.push_back(bound_condition(0, "A", "x"));

    CHECK_FALSE(EnergyDeltaPlan::factorized(
        std::numeric_limits<double>::infinity(), {}, {}).has_value());
    CHECK_FALSE(EnergyDeltaPlan::factorized(0.0, conditions, {{1.0, 1, 0}}, 63).has_value());
}

TEST_CASE("mixed-reactant predicates have no single reactant index") {
    auto c0 = bound_condition(0, "A", "x");
    auto c1 = bound_condition(1, "B", "y");
    auto plan = EnergyDeltaPlan::factorized(0.0, {c0, c1}, {{1.0, 1, 0}, {2.0, 2, 1}});
    REQUIRE(plan.has_value());
    CHECK_FALSE(plan->singleReactantIndex().has_value());
    CHECK(plan->predicateMaskForReactant(0) == 1);
    CHECK(plan->predicateMaskForReactant(1) == 2);
}

TEST_CASE("Arrhenius forward reverse factor ratio is exp(-deltaG/RT)") {
    auto c = bound_condition(0, "A", "x");
    auto plan = EnergyDeltaPlan::factorized(1.0, {c}, {{2.0, 1, 0}});
    REQUIRE(plan.has_value());

    for (std::uint64_t mask : {std::uint64_t{0}, std::uint64_t{1}}) {
        const double dg = *plan->tryDeltaG(mask);
        const double fwd = *plan->tryArrheniusFactor(mask, 0.37, 2.478, true);
        const double rev = *plan->tryArrheniusFactor(mask, 0.37, 2.478, false);
        CHECK(fwd / rev == Catch::Approx(std::exp(-dg / 2.478)).epsilon(1e-12));
    }
}

TEST_CASE("lookup table equals direct evaluation for every context") {
    std::vector<EnergyCondition> conditions;
    for (int i = 0; i < 5; ++i) conditions.push_back(bound_condition(0, "A", "s"));
    std::vector<EnergyTerm> terms = {
        {1.0, 1, 0}, {-0.5, 2, 1}, {2.0, 4, 2}, {3.0, 3, 3}, {-1.0, 0b10101, 4},
    };
    auto plan = EnergyDeltaPlan::factorized(0.25, conditions, terms);
    REQUIRE(plan.has_value());

    const auto table = plan->buildArrheniusTable(0.4, 2.0, true, 8);
    REQUIRE(table.has_value());
    REQUIRE(table->size() == 32);
    for (std::uint64_t mask = 0; mask < 32; ++mask) {
        REQUIRE(plan->tryArrheniusFactor(mask, 0.4, 2.0, true).has_value());
        CHECK((*table)[mask] == Catch::Approx(*plan->tryArrheniusFactor(mask, 0.4, 2.0, true)).epsilon(1e-12));
    }
}

TEST_CASE("factorized plan validates predicate payloads rather than weakening them") {
    EnergyCondition badBond = bound_condition(0, "A", "x");
    badBond.partnerType = "B"; // missing partner component
    CHECK_FALSE(EnergyDeltaPlan::factorized(0.0, {badBond}, {{1.0,1,0}}).has_value());

    EnergyCondition badState;
    badState.kind = ConditionKind::State;
    badState.reactantIndex = 0;
    badState.moleculeType = "A";
    badState.componentName = "s";
    CHECK_FALSE(EnergyDeltaPlan::factorized(0.0, {badState}, {{1.0,1,0}}).has_value());

    EnergyCondition badReactant = bound_condition(-1, "A", "x");
    CHECK_FALSE(EnergyDeltaPlan::factorized(0.0, {badReactant}, {{1.0,1,0}}).has_value());
}

TEST_CASE("Arrhenius evaluation rejects invalid thermodynamic numerics") {
    auto c = bound_condition(0, "A", "x");
    auto plan = EnergyDeltaPlan::factorized(0.0, {c}, {{1.0,1,0}});
    REQUIRE(plan);
    CHECK_FALSE(plan->tryArrheniusFactor(0, 0.5, 0.0, true).has_value());
    CHECK_FALSE(plan->tryArrheniusFactor(0, 0.5, -1.0, true).has_value());
    CHECK_FALSE(plan->tryArrheniusFactor(0, std::numeric_limits<double>::infinity(), 1.0, true).has_value());
}

TEST_CASE("Arrhenius overflow fails closed rather than returning infinity") {
    auto c = bound_condition(0, "A", "x");
    auto plan = EnergyDeltaPlan::factorized(-1e308, {c}, {{1.0,1,0}});
    REQUIRE(plan);
    CHECK_FALSE(plan->tryArrheniusFactor(1, 1.0, 1e-300, true).has_value());
}

TEST_CASE("lookup table obeys explicit local-context size budget") {
    std::vector<EnergyCondition> conditions;
    for (int i=0;i<9;++i) conditions.push_back(bound_condition(0,"A","x"));
    auto plan = EnergyDeltaPlan::factorized(0.0, conditions, {{1.0,1,0}});
    REQUIRE(plan);
    CHECK_FALSE(plan->buildArrheniusTable(0.5,1.0,true,8).has_value());
    CHECK(plan->buildArrheniusTable(0.5,1.0,true,9).has_value());
}

TEST_CASE("nonfinite constant energy becomes materialized fallback") {
    const auto inf = EnergyDeltaPlan::constant(std::numeric_limits<double>::infinity());
    const auto nan = EnergyDeltaPlan::constant(std::numeric_limits<double>::quiet_NaN());
    CHECK_FALSE(inf.isExecutable());
    CHECK_FALSE(nan.isExecutable());
}

TEST_CASE("empty factorized term list collapses to constant plan") {
    auto plan = EnergyDeltaPlan::factorized(1.25, {}, {});
    REQUIRE(plan.has_value());
    CHECK(plan->isConstant());
    CHECK(plan->tryDeltaG(0).value() == Catch::Approx(1.25));
}

TEST_CASE("predicate mask for absent reactant is zero") {
    auto c = bound_condition(0, "A", "x");
    auto plan = EnergyDeltaPlan::factorized(0.0, {c}, {{1.0,1,0}});
    REQUIRE(plan);
    CHECK(plan->predicateMaskForReactant(42) == 0);
}

TEST_CASE("phi limiting cases have expected Arrhenius behavior") {
    auto c = bound_condition(0, "A", "x");
    auto plan = EnergyDeltaPlan::factorized(0.0, {c}, {{2.0,1,0}});
    REQUIRE(plan);
    // phi=0 assigns all delta-G dependence to the reverse barrier.
    CHECK(plan->tryArrheniusFactor(1, 0.0, 1.0, true).value() == Catch::Approx(1.0));
    CHECK(plan->tryArrheniusFactor(1, 0.0, 1.0, false).value() == Catch::Approx(std::exp(2.0)));
    // phi=1 assigns all delta-G dependence to the forward barrier.
    CHECK(plan->tryArrheniusFactor(1, 1.0, 1.0, true).value() == Catch::Approx(std::exp(-2.0)));
    CHECK(plan->tryArrheniusFactor(1, 1.0, 1.0, false).value() == Catch::Approx(1.0));
}

TEST_CASE("negative deltaG favors forward rate in correct ratio") {
    auto c = bound_condition(0, "A", "x");
    auto plan = EnergyDeltaPlan::factorized(0.0, {c}, {{-3.0,1,0}});
    REQUIRE(plan);
    const auto f=plan->tryArrheniusFactor(1,0.5,1.0,true);
    const auto r=plan->tryArrheniusFactor(1,0.5,1.0,false);
    REQUIRE(f); REQUIRE(r);
    CHECK(*f / *r == Catch::Approx(std::exp(3.0)).epsilon(1e-12));
}

TEST_CASE("finite energy terms whose sum overflows are rejected") {
    auto c = bound_condition(0, "A", "x");
    auto plan = EnergyDeltaPlan::factorized(1e308, {c}, {{1e308, 1, 0}});
    REQUIRE(plan);
    CHECK_FALSE(plan->tryDeltaG(1).has_value());
}

TEST_CASE("unknown predicate kind cannot become executable") {
    auto c = bound_condition(0, "A", "x");
    c.kind = static_cast<ConditionKind>(42);
    CHECK_FALSE(EnergyDeltaPlan::factorized(0, {c}, {{1, 1, 0}}));
}
