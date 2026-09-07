#include <cassert>
#include <cmath>
#include <cstdint>
#include <vector>
#include "compile/energy/EnergyDeltaPlan.hpp"

int main() {
    using namespace bng::compile::energy;
    EnergyCondition a; a.kind=ConditionKind::Bond; a.reactantIndex=0; a.moleculeType="A"; a.componentName="x";
    EnergyCondition b=a; b.kind=ConditionKind::State; b.componentName="s"; b.expectedState="P";
    auto plan=EnergyDeltaPlan::factorized(0.5,{a,b},{{1.0,1,0},{2.0,2,1},{4.0,3,2}});
    assert(plan && plan->isFactorized());
    assert(std::fabs(*plan->tryDeltaG(0)-0.5)<1e-12);
    assert(std::fabs(*plan->tryDeltaG(1)-1.5)<1e-12);
    assert(std::fabs(*plan->tryDeltaG(2)-2.5)<1e-12);
    assert(std::fabs(*plan->tryDeltaG(3)-7.5)<1e-12);
    const auto table=plan->buildArrheniusTable(0.5,1.0,true,8);
    assert(table && table->size()==4);
    assert(std::fabs((*table)[3]-std::exp(-3.75))<1e-12);
    return 0;
}
