// RED CONTRACT: energy compilation is defined for graph rewrites, not only special-case binding/state rules.
#include <algorithm>
#include <catch2/catch_test_macros.hpp>
#include "compile/CompiledModel.hpp"
#include "compile/energy/EnergyPatternCompiler.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("compound bond-plus-state rewrite exposes union mutation signature") {
    auto model=bng::parser::parseModel(R"BNG(
begin molecule types
 A(x,s~U~P)
 B(y)
end molecule types
begin seed species
 A(x,s~U) 1
 B(y) 1
end seed species
begin reaction rules
 r: A(x,s~U)+B(y) -> A(x!1,s~P).B(y!1) 1
end reaction rules
)BNG");
    REQUIRE(model);
    bng::compile::CompiledModel compiled(*model);
    REQUIRE(compiled.rules().size()==1);
    const auto& m=compiled.rules()[0].mutations();
    CHECK(std::any_of(m.begin(),m.end(),[](const auto& x){return x.kind==bng::compile::MutationKind::AddBond;}));
    CHECK(std::any_of(m.begin(),m.end(),[](const auto& x){return x.kind==bng::compile::MutationKind::ChangeState;}));
}

TEST_CASE("compound rewrite energy plan contains all factors affected by either edit") {
    auto model=bng::parser::parseModel(R"BNG(
begin parameters
 Gbind 1
 GP 2
end parameters
begin molecule types
 A(x,s~U~P)
 B(y)
end molecule types
begin seed species
 A(x,s~U) 1
 B(y) 1
end seed species
begin energy patterns
 A(x!1).B(y!1) Gbind
 A(s~P) GP
end energy patterns
begin reaction rules
 r: A(x,s~U)+B(y) -> A(x!1,s~P).B(y!1) 1
end reaction rules
)BNG");
    REQUIRE(model);
    auto plan=bng::compile::energy::EnergyPatternCompiler::fromModel(*model)
        .compileRule(model->getReactionRules().front());
    REQUIRE(plan.affectedFactorIndices().size()==2);
}
