// RED CONTRACT: backend-neutral evaluation of compiled local predicates.
#include <catch2/catch_test_macros.hpp>
#include "compile/energy/EnergyContextEvaluator.hpp"

using namespace bng::compile::energy;

TEST_CASE("state predicate evaluates selected reactant state") {
    LocalContextSnapshot s;
    s.setState(0,"A","x","P");
    EnergyCondition c; c.kind=ConditionKind::State;c.reactantIndex=0;c.moleculeType="A";c.componentName="x";c.expectedState="P";
    CHECK(evaluateCondition(c,s));
    c.expectedState="U";CHECK_FALSE(evaluateCondition(c,s));
}

TEST_CASE("occupancy-only bond predicate ignores partner identity") {
    LocalContextSnapshot s;
    s.setBond(0,"A","x","C","z");
    EnergyCondition c;c.kind=ConditionKind::Bond;c.reactantIndex=0;c.moleculeType="A";c.componentName="x";c.expectedBound=true;
    CHECK(evaluateCondition(c,s));
    c.expectedBound=false;CHECK_FALSE(evaluateCondition(c,s));
}

TEST_CASE("partner-specific bond predicate requires exact type and component") {
    LocalContextSnapshot s;s.setBond(0,"A","x","C","z");
    EnergyCondition c;c.kind=ConditionKind::Bond;c.reactantIndex=0;c.moleculeType="A";c.componentName="x";c.expectedBound=true;c.partnerType="C";c.partnerComponent="z";
    CHECK(evaluateCondition(c,s));
    c.partnerComponent="other";CHECK_FALSE(evaluateCondition(c,s));
}

TEST_CASE("unbound predicate is true only for an open site") {
    LocalContextSnapshot s;s.setUnbound(0,"A","x");
    EnergyCondition c;c.kind=ConditionKind::Bond;c.reactantIndex=0;c.moleculeType="A";c.componentName="x";c.expectedBound=false;
    CHECK(evaluateCondition(c,s));
}

TEST_CASE("one-hop partner-state predicate evaluates bonded molecule state") {
    LocalContextSnapshot s;
    s.setBond(0,"A","x","C","z");
    s.setPartnerState(0,"A","x","C","q","P");
    EnergyCondition c;c.kind=ConditionKind::Bond;c.reactantIndex=0;c.moleculeType="A";c.componentName="x";c.expectedBound=true;c.partnerType="C";c.partnerComponent="z";c.expectedState="P";
    CHECK(evaluateCondition(c,s));
}

TEST_CASE("missing molecule or component never weakens predicate to true") {
    LocalContextSnapshot s;
    EnergyCondition c;c.kind=ConditionKind::State;c.reactantIndex=0;c.moleculeType="A";c.componentName="x";c.expectedState="P";
    CHECK_FALSE(evaluateCondition(c,s));
}

TEST_CASE("context mask bit ordering follows compiled condition ordering exactly") {
    LocalContextSnapshot s;s.setState(0,"A","x","P");s.setUnbound(1,"B","y");
    EnergyCondition a;a.kind=ConditionKind::State;a.reactantIndex=0;a.moleculeType="A";a.componentName="x";a.expectedState="P";
    EnergyCondition b;b.kind=ConditionKind::Bond;b.reactantIndex=1;b.moleculeType="B";b.componentName="y";b.expectedBound=false;
    CHECK(evaluateContextMask({a,b},s)==0b11);
    b.expectedBound=true;CHECK(evaluateContextMask({a,b},s)==0b01);
}
