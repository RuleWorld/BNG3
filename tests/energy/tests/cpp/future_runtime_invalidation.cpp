// RED CONTRACT: context-only changes must refresh weighted propensities without stale mappings.
#include <cstdlib>
#include <memory>
#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include "NFcore/NFcore.hh"
#include "NFinput/NFinput_fromAst.hh"
#include "parser/BNGAstVisitor.hpp"

namespace {
std::unique_ptr<NFcore::System> build(std::unique_ptr<bng::ast::Model>& model, bool generalized) {
#ifdef _WIN32
    _putenv_s("BNG_NFSIM_GENERAL_ENERGY", generalized?"1":"");
#else
    if(generalized) setenv("BNG_NFSIM_GENERAL_ENERGY","1",1); else unsetenv("BNG_NFSIM_GENERAL_ENERGY");
#endif
    int limit=-1;
    std::unique_ptr<NFcore::System> s(NFinput::buildSystemFromAst(*model,false,-1,false,limit,{}));
    REQUIRE(s); s->setUniversalTraversalLimit(limit); s->seedRNG(1); s->prepareForSimulation(); return s;
}
double total_a(const NFcore::System& s){double x=0;for(auto*r:s.getAllReactions())x+=r->get_a();return x;}
}

TEST_CASE("state-only context mutation refreshes generalized binding factor") {
    auto source=R"BNG(
begin model
begin parameters
 G 4
 phi 0.5
 Ea 1
end parameters
begin molecule types
 A(x,s~U~P)
 B(y)
end molecule types
begin seed species
 A(x,s~U) 1
 B(y) 10
end seed species
begin energy patterns
 A(x!1,s~P).B(y!1) G
end energy patterns
begin reaction rules
 A(x)+B(y)<->A(x!1).B(y!1) Arrhenius(phi,Ea)
end reaction rules
end model
)BNG";
    auto m0=bng::parser::parseModel(source); auto m1=bng::parser::parseModel(source);
    REQUIRE(m0); REQUIRE(m1);
    auto legacy=build(m0,false); auto general=build(m1,true);
    auto mutate=[](NFcore::System& s){
        auto* mt=s.getMoleculeTypeByName("A"); REQUIRE(mt);
        auto* m=mt->getMolecule(0); REQUIRE(m);
        const int ci=mt->getCompIndexFromName("s");
        m->setComponentState(ci,mt->getStateValueFromName(ci,"P"));
        mt->updateRxnMembership(m);
        s.updateAllReactionPropensities();
    };
    mutate(*legacy); mutate(*general);
    CHECK(total_a(*general)==Catch::Approx(total_a(*legacy)).epsilon(1e-12));
}

TEST_CASE("one-hop partner-state mutation refreshes owning reaction propensity") {
    auto source=R"BNG(
begin model
begin parameters
 G 4
 phi 0.5
 Ea 1
end parameters
begin molecule types
 A(x,c)
 B(y)
 C(z,s~U~P)
end molecule types
begin seed species
 A(x,c!1).C(z!1,s~U) 1
 B(y) 10
end seed species
begin energy patterns
 A(x!1,c!2).B(y!1).C(z!2,s~P) G
end energy patterns
begin reaction rules
 A(x)+B(y)<->A(x!1).B(y!1) Arrhenius(phi,Ea)
end reaction rules
end model
)BNG";
    auto m0=bng::parser::parseModel(source); auto m1=bng::parser::parseModel(source);
    REQUIRE(m0); REQUIRE(m1);
    auto legacy=build(m0,false); auto general=build(m1,true);
    auto mutate=[](NFcore::System& s){
        auto* mt=s.getMoleculeTypeByName("C"); REQUIRE(mt);
        auto* m=mt->getMolecule(0); REQUIRE(m);
        const int ci=mt->getCompIndexFromName("s");
        m->setComponentState(ci,mt->getStateValueFromName(ci,"P"));
        mt->updateRxnMembership(m);
        s.updateAllReactionPropensities();
    };
    mutate(*legacy); mutate(*general);
    CHECK(total_a(*general)==Catch::Approx(total_a(*legacy)).epsilon(1e-12));
}
