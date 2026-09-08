// RED CONTRACT: pair-factorized energy propensity must retain NFsim molecularity checks.
#include <memory>
#include <catch2/catch_test_macros.hpp>
#include "NFcore/NFcore.hh"
#include "NFinput/NFinput_fromAst.hh"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("blockSameComplexBinding prevents intra-complex energy binding") {
    auto model=bng::parser::parseModel(R"BNG(
begin model
begin parameters
 G 2
 phi 0.5
 Ea 1
end parameters
begin molecule types
 A(x,c,s~U~P)
 B(y,d,t~U~P)
 C(a,b)
end molecule types
begin seed species
 A(x,c!1,s~P).C(a!1,b!2).B(y,d!2,t~P) 1
end seed species
begin energy patterns
 A(x!1,s~P).B(y!1,t~P) G
end energy patterns
begin reaction rules
 A(x)+B(y)<->A(x!1).B(y!1) Arrhenius(phi,Ea)
end reaction rules
end model
)BNG");
    REQUIRE(model);
#ifdef _WIN32
    _putenv_s("BNG_NFSIM_GENERAL_ENERGY","1");
#else
    setenv("BNG_NFSIM_GENERAL_ENERGY","1",1);
#endif
    int lim=-1; std::unique_ptr<NFcore::System> s(NFinput::buildSystemFromAst(*model,true,-1,false,lim,{}));
    REQUIRE(s); s->setUniversalTraversalLimit(lim); s->prepareForSimulation();
    double total=0; for(auto*r:s->getAllReactions()) total+=r->get_a();
    // Only reverse is impossible initially because A.x/B.y are unbound; forward
    // must also be blocked because both endpoints already belong to the same complex.
    CHECK(total==0.0);
}
