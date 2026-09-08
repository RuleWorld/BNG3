// RED CONTRACT: inverted energy-factor index must be complete and selective.
#include <set>
#include <catch2/catch_test_macros.hpp>
#include "compile/energy/EnergyPatternStore.hpp"

using namespace bng::compile::energy;

TEST_CASE("binding-center index returns same candidates independent of endpoint order") {
    EnergyPatternStore s;
    s.addFactor(PatternDescriptor::parse("A(x!1).B(y!1)"),1,"ab");
    s.addFactor(PatternDescriptor::parse("A(z!1).C(q!1)"),2,"ac");
    CHECK(s.candidateFactorsForBinding("A","x","B","y")==
          s.candidateFactorsForBinding("B","y","A","x"));
}

TEST_CASE("binding-center index excludes unrelated factors") {
    EnergyPatternStore s;
    for (int i=0;i<1000;++i)
        s.addFactor(PatternDescriptor::parse("X"+std::to_string(i)+"(a!1).Y"+std::to_string(i)+"(b!1)"),1,"noise");
    s.addFactor(PatternDescriptor::parse("A(x!1).B(y!1)"),1,"target");
    const auto candidates=s.candidateFactorsForBinding("A","x","B","y");
    REQUIRE(candidates.size()==1);
    CHECK(s.factor(candidates[0]).label=="target");
}

TEST_CASE("duplicate center occurrence does not duplicate candidate factor") {
    EnergyPatternStore s;
    s.addFactor(PatternDescriptor::parse("A(x!1,x!2).B(y!1,y!2)"),1,"multi");
    const auto candidates=s.candidateFactorsForBinding("A","x","B","y");
    CHECK(candidates.size()==1);
}
