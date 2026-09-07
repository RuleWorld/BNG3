// RED CONTRACT: aggregation math remains numerically stable across sparse/large pools.
#include <cmath>
#include <catch2/catch_test_macros.hpp>
#include "compile/energy/EnergyContextWeights.hpp"

using namespace bng::compile::energy;

TEST_CASE("empty mapping pool has zero propensity") {
    EnergyCondition c;c.kind=ConditionKind::State;c.reactantIndex=0;c.moleculeType="A";c.componentName="s";c.expectedState="P";
    auto p=EnergyDeltaPlan::factorized(0,{c},{{1,1,0}});REQUIRE(p);
    EnergyContextWeights w(*p,0.5,1,true);
    CHECK(w.mappingSum({})==0.0);
    CHECK(w.pairPropensity({}, {0,1},1.0)==0.0);
}

TEST_CASE("large category counts use wide arithmetic and finite double propensity") {
    EnergyCondition a,b;a.kind=ConditionKind::State;a.reactantIndex=0;a.moleculeType="A";a.componentName="s";a.expectedState="P";b=a;b.reactantIndex=1;b.moleculeType="B";b.componentName="t";
    auto p=EnergyDeltaPlan::factorized(0,{a,b},{{1,3,0}});REQUIRE(p);
    EnergyContextWeights w(*p,0.5,2,true);
    std::vector<ContextCategory> left={{0,3000000000ULL},{1,2000000000ULL}};
    std::vector<ContextCategory> right={{0,4000000000ULL},{2,1000000000ULL}};
    const double value=w.pairPropensityFromCategories(left,right,1e-12);
    CHECK(std::isfinite(value));
    CHECK(value>0);
}

TEST_CASE("zero base rate remains zero regardless of energy factor") {
    EnergyCondition c;c.kind=ConditionKind::State;c.reactantIndex=0;c.moleculeType="A";c.componentName="s";c.expectedState="P";
    auto p=EnergyDeltaPlan::factorized(-100,{c},{{-100,1,0}});REQUIRE(p);
    EnergyContextWeights w(*p,0.5,1,true);
    CHECK(w.pairPropensity({1},{0},0.0)==0.0);
}
