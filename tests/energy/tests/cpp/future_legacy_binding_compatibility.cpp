// RED CONTRACT: old compact EnergyBindingContext is only a compatibility lowering.
#include <catch2/catch_test_macros.hpp>
#include "compile/energy/EnergyLoweringPlan.hpp"

using namespace bng::compile::energy;

TEST_CASE("plain occupancy predicate is legacy compact representable") {
    EnergyCondition c; c.kind=ConditionKind::Bond; c.reactantIndex=0; c.moleculeType="A"; c.componentName="c"; c.expectedBound=true;
    auto p=EnergyDeltaPlan::factorized(0,{c},{{1,1,0}}); REQUIRE(p);
    CHECK(isLegacyBindingContextRepresentable(*p));
}

TEST_CASE("state predicate is not legacy compact representable") {
    EnergyCondition c; c.kind=ConditionKind::State; c.reactantIndex=0; c.moleculeType="A"; c.componentName="s"; c.expectedState="P";
    auto p=EnergyDeltaPlan::factorized(0,{c},{{1,1,0}}); REQUIRE(p);
    CHECK_FALSE(isLegacyBindingContextRepresentable(*p));
}

TEST_CASE("partner-specific bond predicate is not legacy compact representable") {
    EnergyCondition c; c.kind=ConditionKind::Bond; c.reactantIndex=0; c.moleculeType="A"; c.componentName="c"; c.expectedBound=true; c.partnerType="C"; c.partnerComponent="x";
    auto p=EnergyDeltaPlan::factorized(0,{c},{{1,1,0}}); REQUIRE(p);
    CHECK_FALSE(isLegacyBindingContextRepresentable(*p));
}
