#include <algorithm>
#include <catch2/catch_test_macros.hpp>

#include "compile/CompiledModel.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("CompiledModel preserves source rule ordering and energy-factor provenance") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
  e1 1
  e2 2
end parameters
begin molecule types
  A(x~U~P,y)
  B(z)
end molecule types
begin energy patterns
  ep1: A(x~P) e1
  ep2: A(y!1).B(z!1) e2
end energy patterns
begin seed species
  A(x~U,y) 10
  B(z) 10
end seed species
begin reaction rules
  phos: A(x~U) -> A(x~P) 1
  bind: A(y) + B(z) -> A(y!1).B(z!1) 2
end reaction rules
)BNG");
    REQUIRE(model != nullptr);
    const bng::compile::CompiledModel compiled(*model);
    REQUIRE(compiled.rules().size() == 2);
    CHECK(compiled.rules()[0].name() == model->getReactionRules()[0].getRuleName());
    CHECK(compiled.rules()[0].label() == "phos:");
    CHECK(compiled.rules()[1].name() == model->getReactionRules()[1].getRuleName());
    CHECK(compiled.rules()[1].label() == "bind:");
    REQUIRE(compiled.energyFactors().size() == 2);
    CHECK(compiled.energyFactors()[0].label == "ep1");
    CHECK(compiled.energyFactors()[1].label == "ep2");
    CHECK_FALSE(compiled.energyFactors()[0].structuralFingerprint.empty());
    CHECK_FALSE(compiled.energyFactors()[1].structuralFingerprint.empty());
}

TEST_CASE("CompiledRule reports both endpoints of a bond mutation") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
  A(x)
  B(y)
end molecule types
begin seed species
  A(x) 1
  B(y) 1
end seed species
begin reaction rules
  r: A(x) + B(y) -> A(x!1).B(y!1) 1
end reaction rules
)BNG");
    REQUIRE(model != nullptr);
    const bng::compile::CompiledModel compiled(*model);
    REQUIRE(compiled.rules().size() == 1);
    CHECK(compiled.rules()[0].affectedComponents().size() == 2);
}

TEST_CASE("state change contributes exactly one affected component") {
    auto model=bng::parser::parseModel(R"BNG(
begin molecule types
 A(s~U~P)
end molecule types
begin seed species
 A(s~U) 1
end seed species
begin reaction rules
 flip: A(s~U)->A(s~P) 1
end reaction rules
)BNG");
    REQUIRE(model);
    bng::compile::CompiledModel c(*model);
    REQUIRE(c.rules().size()==1);
    REQUIRE(c.rules()[0].mutations().size()==1);
    CHECK(c.rules()[0].mutations()[0].kind==bng::compile::MutationKind::ChangeState);
    CHECK(c.rules()[0].affectedComponents().size()==1);
}

TEST_CASE("unbinding reports both affected bond endpoints") {
    auto model=bng::parser::parseModel(R"BNG(
begin molecule types
 A(x)
 B(y)
end molecule types
begin seed species
 A(x!1).B(y!1) 1
end seed species
begin reaction rules
 unbind: A(x!1).B(y!1)->A(x)+B(y) 1
end reaction rules
)BNG");
    REQUIRE(model);
    bng::compile::CompiledModel c(*model);
    const auto& r=c.rules().front();
    CHECK(std::any_of(r.mutations().begin(),r.mutations().end(),[](const auto&m){return m.kind==bng::compile::MutationKind::DeleteBond;}));
    CHECK(r.affectedComponents().size()==2);
}

TEST_CASE("implicit whole-species deletion requires conservative invalidation") {
    auto model=bng::parser::parseModel(R"BNG(
begin molecule types
 A(x)
end molecule types
begin seed species
 A(x) 1
end seed species
begin reaction rules
 die: A(x)->0 1
end reaction rules
)BNG");
    REQUIRE(model);
    bng::compile::CompiledModel c(*model);
    const auto& r=c.rules().front();
    // ReactionRule::initialize returns before operations for A -> 0.
    // The native adapter handles whole-species deletion separately.
    CHECK(r.mutations().empty());
    CHECK(r.requiresConservativeInvalidation());
}

TEST_CASE("bidirectional source rule remains marked bidirectional and retains both rates") {
    auto model=bng::parser::parseModel(R"BNG(
begin molecule types
 A(s~U~P)
end molecule types
begin seed species
 A(s~U) 1
end seed species
begin reaction rules
 flip: A(s~U)<->A(s~P) 1,2
end reaction rules
)BNG");
    REQUIRE(model);
    bng::compile::CompiledModel c(*model);
    REQUIRE(c.rules().size()==1);
    CHECK(c.rules()[0].isBidirectional());
    CHECK(c.rules()[0].rateLaws().size()==2);
}
