// RED CONTRACT: backend-neutral aggregation math used by EnergyPairRxnClass.
#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include "compile/energy/EnergyContextWeights.hpp"

using namespace bng::compile::energy;

TEST_CASE("pair-context aggregate propensity equals literal pair sum") {
    EnergyCondition a, b;
    a.kind = ConditionKind::State; a.reactantIndex = 0; a.moleculeType="A"; a.componentName="s"; a.expectedState="P";
    b.kind = ConditionKind::State; b.reactantIndex = 1; b.moleculeType="B"; b.componentName="t"; b.expectedState="P";
    auto p = EnergyDeltaPlan::factorized(0.0, {a,b}, {{2.0, 3, 0}});
    REQUIRE(p.has_value());

    // Three A mappings: two masks 0, one mask 1. Four B mappings: one mask 0, three mask 2.
    const std::vector<std::uint64_t> left = {0,0,1};
    const std::vector<std::uint64_t> right = {0,2,2,2};
    const double base_rate = 0.7;
    EnergyContextWeights weights(*p, 0.5, 1.0, true);
    const double aggregate = weights.pairPropensity(left, right, base_rate);

    double literal = 0.0;
    for (auto l : left) for (auto r : right)
        literal += base_rate * *p->tryArrheniusFactor(l | r, 0.5, 1.0, true);
    CHECK(aggregate == Catch::Approx(literal).epsilon(1e-12));
}

TEST_CASE("mapping-local aggregate equals literal weighted mapping sum") {
    EnergyCondition a;
    a.kind = ConditionKind::State; a.reactantIndex=0; a.moleculeType="A"; a.componentName="s"; a.expectedState="P";
    auto p = EnergyDeltaPlan::factorized(1.0, {a}, {{2.0,1,0}});
    REQUIRE(p.has_value());
    const std::vector<std::uint64_t> mappings = {0,1,1,0,1};
    EnergyContextWeights weights(*p, 0.3, 2.0, true);
    double literal = 0.0;
    for (auto mask : mappings) literal += *p->tryArrheniusFactor(mask, 0.3, 2.0, true);
    CHECK(weights.mappingSum(mappings) == Catch::Approx(literal).epsilon(1e-12));
}
