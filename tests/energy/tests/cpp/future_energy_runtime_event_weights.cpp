// RED CONTRACT: test physical-event weight parity independently of RNG stream shape.
#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include "compile/energy/EnergyContextWeights.hpp"

using namespace bng::compile::energy;

TEST_CASE("category aggregation preserves each physical pair's normalized selection weight") {
    EnergyCondition a, b;
    a.kind=ConditionKind::State; a.reactantIndex=0; a.moleculeType="A"; a.componentName="s"; a.expectedState="P";
    b.kind=ConditionKind::State; b.reactantIndex=1; b.moleculeType="B"; b.componentName="t"; b.expectedState="P";
    auto plan = EnergyDeltaPlan::factorized(0.25, {a,b}, {{2.0,3,0}, {-0.5,1,1}});
    REQUIRE(plan.has_value());

    const std::vector<std::uint64_t> left = {0,1,1,0};
    const std::vector<std::uint64_t> right = {0,2,2};
    EnergyContextWeights weights(*plan, 0.4, 2.478, true);
    const auto normalized = weights.literalPairProbabilities(left, right);
    const auto grouped = weights.expandedPairProbabilities(left, right);
    REQUIRE(normalized.size() == grouped.size());
    for (std::size_t i=0;i<normalized.size();++i)
        CHECK(grouped[i] == Catch::Approx(normalized[i]).epsilon(1e-12));
}
