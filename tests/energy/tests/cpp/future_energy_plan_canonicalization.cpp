// RED CONTRACT: canonical energy plans for stable caching/provenance.
#include <algorithm>
#include <catch2/catch_test_macros.hpp>
#include "compile/energy/EnergyPlanCanonicalizer.hpp"

using namespace bng::compile::energy;

namespace {
EnergyCondition state(int r,const char* m,const char* c,const char* v){EnergyCondition x;x.kind=ConditionKind::State;x.reactantIndex=r;x.moleculeType=m;x.componentName=c;x.expectedState=v;return x;}
}

TEST_CASE("duplicate terms with same predicate mask combine by energy sum") {
    auto p=EnergyDeltaPlan::factorized(0,{state(0,"A","s","P")},{{1,1,0},{2,1,1}});REQUIRE(p);
    auto c=canonicalizeEnergyPlan(*p);
    REQUIRE(c.terms().size()==1);
    CHECK(c.terms()[0].energyValue==3.0);
}

TEST_CASE("zero-energy terms are removed") {
    auto p=EnergyDeltaPlan::factorized(0,{state(0,"A","s","P")},{{0,1,0},{2,1,1}});REQUIRE(p);
    auto c=canonicalizeEnergyPlan(*p);
    REQUIRE(c.terms().size()==1);
    CHECK(c.terms()[0].energyValue==2.0);
}

TEST_CASE("unused predicates are pruned and masks remapped") {
    auto p=EnergyDeltaPlan::factorized(0,{state(0,"A","a","P"),state(0,"A","b","P"),state(0,"A","c","P")},{{2,0b101,0}});REQUIRE(p);
    auto c=canonicalizeEnergyPlan(*p);
    CHECK(c.conditions().size()==2);
    REQUIRE(c.terms().size()==1);
    CHECK(c.terms()[0].conditionMask==0b11);
}

TEST_CASE("predicate ordering is deterministic by semantic key") {
    auto a=state(1,"B","z","P"),b=state(0,"A","x","U");
    auto p1=EnergyDeltaPlan::factorized(0,{a,b},{{1,1,0},{2,2,1}});REQUIRE(p1);
    auto p2=EnergyDeltaPlan::factorized(0,{b,a},{{2,1,1},{1,2,0}});REQUIRE(p2);
    CHECK(energyPlanFingerprint(canonicalizeEnergyPlan(*p1))==energyPlanFingerprint(canonicalizeEnergyPlan(*p2)));
}

TEST_CASE("factor provenance does not alter semantic execution fingerprint") {
    auto c=state(0,"A","s","P");c.sourceFactorIndices={1,2};
    auto d=c;d.sourceFactorIndices={8,9};
    auto p1=EnergyDeltaPlan::factorized(0,{c},{{2,1,1}});auto p2=EnergyDeltaPlan::factorized(0,{d},{{2,1,9}});
    REQUIRE(p1);REQUIRE(p2);
    CHECK(energyExecutionFingerprint(*p1)==energyExecutionFingerprint(*p2));
    CHECK(energyProvenanceFingerprint(*p1)!=energyProvenanceFingerprint(*p2));
}
