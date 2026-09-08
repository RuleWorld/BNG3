// RED CONTRACT: backend-neutral lowering selector.
#include <catch2/catch_test_macros.hpp>
#include "compile/energy/EnergyLoweringPlan.hpp"

using namespace bng::compile::energy;

TEST_CASE("constant deltaG selects constant lowering") {
    auto plan = EnergyDeltaPlan::constant(1.0);
    CHECK(selectEnergyLowering(plan, EnergyTopology::StateChange) ==
          EnergyLoweringKind::Constant);
}

TEST_CASE("one-reactant context selects mapping-local lowering") {
    EnergyCondition c;
    c.kind = ConditionKind::State;
    c.reactantIndex = 0;
    c.moleculeType = "A";
    c.componentName = "s";
    c.expectedState = "P";
    auto plan = EnergyDeltaPlan::factorized(0.0, {c}, {{1.0, 1, 0}});
    REQUIRE(plan.has_value());
    CHECK(selectEnergyLowering(*plan, EnergyTopology::StateChange) ==
          EnergyLoweringKind::MappingLocal);
}

TEST_CASE("mixed disconnected binding context selects pair aggregation") {
    EnergyCondition a, b;
    a.kind = ConditionKind::State; a.reactantIndex = 0; a.moleculeType = "A"; a.componentName = "s"; a.expectedState = "P";
    b.kind = ConditionKind::State; b.reactantIndex = 1; b.moleculeType = "B"; b.componentName = "t"; b.expectedState = "P";
    auto plan = EnergyDeltaPlan::factorized(0.0, {a,b}, {{2.0, 3, 0}});
    REQUIRE(plan.has_value());
    CHECK(selectEnergyLowering(*plan, EnergyTopology::DisconnectedBinding) ==
          EnergyLoweringKind::PairFactorized);
}

TEST_CASE("unrepresentable topology always selects materialized fallback") {
    CHECK(selectEnergyLowering(EnergyDeltaPlan::materializedFallback(), EnergyTopology::DisconnectedBinding) ==
          EnergyLoweringKind::Materialized);
}

TEST_CASE("63 predicates remain factorized but policy may reject expensive table lowering") {
    std::vector<EnergyCondition> cs;
    for(int i=0;i<63;++i){EnergyCondition c;c.kind=ConditionKind::Bond;c.reactantIndex=0;c.moleculeType="A";c.componentName="c"+std::to_string(i);cs.push_back(c);}
    auto p=EnergyDeltaPlan::factorized(0,cs,{{1,1,0}});REQUIRE(p);
    CHECK(selectEnergyLowering(*p,EnergyTopology::StateChange)==EnergyLoweringKind::MappingLocal);
    CHECK_FALSE(p->buildArrheniusTable(0.5,1,true,8).has_value());
}

TEST_CASE("same-type disconnected binding is never sent to unsafe orientation-dependent lowering") {
    EnergyCondition c;c.kind=ConditionKind::State;c.reactantIndex=0;c.moleculeType="A";c.componentName="s";c.expectedState="P";
    auto p=EnergyDeltaPlan::factorized(0,{c},{{1,1,0}});REQUIRE(p);
    const auto decision=selectEnergyLowering(*p,EnergyTopology::SameTypeDisconnectedBinding);
    CHECK((decision==EnergyLoweringKind::PairFactorized || decision==EnergyLoweringKind::Materialized));
}

TEST_CASE("connected reverse topology never uses disconnected pair counting") {
    EnergyCondition a,b;
    a.kind=ConditionKind::State;a.reactantIndex=0;a.moleculeType="A";a.componentName="s";a.expectedState="P";
    b.kind=ConditionKind::State;b.reactantIndex=1;b.moleculeType="B";b.componentName="t";b.expectedState="P";
    auto p=EnergyDeltaPlan::factorized(0,{a,b},{{1,3,0}});REQUIRE(p);
    CHECK(selectEnergyLowering(*p,EnergyTopology::ConnectedUnbinding)!=EnergyLoweringKind::PairFactorized);
}
