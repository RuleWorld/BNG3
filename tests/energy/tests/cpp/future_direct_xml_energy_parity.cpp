// RED/REGRESSION CONTRACT: direct AST and compatibility XML paths must interpret energy semantics identically.
#include <memory>
#include <numeric>
#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include "NFcore/NFcore.hh"
#include "NFinput/NFinput.hh"
#include "NFinput/NFinput_fromAst.hh"
#include "parser/BNGAstVisitor.hpp"

namespace {
double total_a(const NFcore::System& s) {
    double a=0; for (auto* r:s.getAllReactions()) a+=r->get_a(); return a;
}
}

TEST_CASE("direct AST and in-memory XML agree for energy state change") {
    auto model=bng::parser::parseModel(R"BNG(
begin model
begin parameters
 GU 0.5
 GP 2
 phi 0.4
 Ea 1
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin seed species
 A(s~U) 100
end seed species
begin energy patterns
 A(s~U) GU
 A(s~P) GP
end energy patterns
begin reaction rules
 A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model
)BNG");
    REQUIRE(model);
    int dlim=-1,xlim=-1;
    std::unique_ptr<NFcore::System> direct(NFinput::buildSystemFromAst(*model,false,-1,false,dlim,{}));
    std::unique_ptr<NFcore::System> xml(NFinput::initializeFromModel(model.get(),false,-1,false,xlim));
    REQUIRE(direct); REQUIRE(xml);
    direct->setUniversalTraversalLimit(dlim); xml->setUniversalTraversalLimit(xlim);
    direct->seedRNG(424242); xml->seedRNG(424242);
    direct->prepareForSimulation(); xml->prepareForSimulation();
    CHECK(direct->getAllReactions().size()==xml->getAllReactions().size());
    CHECK(total_a(*direct)==Catch::Approx(total_a(*xml)).epsilon(1e-12));
}
