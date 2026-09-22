// Parser/API semantics for the thermodynamic language extensions.
//
// Promoted from a RED contract: `begin barrier patterns` and `driven_by()` are
// now normalized before ANTLR and lowered into ast::BarrierPattern /
// ReactionRule driving-work metadata.
//
// Both fixtures originally opened a model with `end model` and no `begin
// model`, which the `prog` grammar rule cannot accept; that is corrected here.
#include <catch2/catch_test_macros.hpp>
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("barrier pattern parses as transition-state contribution, not state free energy") {
    auto model = bng::parser::parseModel(R"BNG(
begin model
begin parameters
 Gbar 2
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin barrier patterns
 A(s~U) -> A(s~P) Gbar
end barrier patterns
end model
)BNG");
    REQUIRE(model);
    REQUIRE(model->getBarrierPatterns().size() == 1);
    CHECK(model->getBarrierPatterns()[0].expression().toString() == "Gbar");
    // A barrier pattern is not an ordinary rule: it must not appear in the
    // model's reaction rules.
    CHECK(model->getReactionRules().empty());
}

TEST_CASE("driving reservoir annotates reversible rule with signed chemical work") {
    auto model = bng::parser::parseModel(R"BNG(
begin model
begin parameters
 muATP 20
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin reaction rules
 A(s~U) <-> A(s~P) Arrhenius(0.5,1) driven_by(muATP)
end reaction rules
end model
)BNG");
    REQUIRE(model);
    REQUIRE(model->getReactionRules().size() == 1);
    CHECK(model->getReactionRules()[0].hasDrivingWork());
    CHECK(model->getReactionRules()[0].drivingWorkExpression().toString() == "muATP");
}

TEST_CASE("an ordinary model carries no barrier or driving-work metadata") {
    auto model = bng::parser::parseModel(R"BNG(
begin model
begin parameters
 k1 1
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin reaction rules
 A(s~U) -> A(s~P) k1
end reaction rules
end model
)BNG");
    REQUIRE(model);
    CHECK(model->getBarrierPatterns().empty());
    REQUIRE(model->getReactionRules().size() == 1);
    CHECK_FALSE(model->getReactionRules()[0].hasDrivingWork());
}

TEST_CASE("barrier patterns are removed from the rule list and rules renumbered") {
    auto model = bng::parser::parseModel(R"BNG(
begin model
begin parameters
 Gbar 2
 phi 0.5
 Ea 1
 GU 0
 GP 1
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin energy patterns
 A(s~U) GU
 A(s~P) GP
end energy patterns
begin barrier patterns
 A(s~U) -> A(s~P) Gbar
end barrier patterns
begin reaction rules
 A(s~U) <-> A(s~P) Arrhenius(phi,Ea) driven_by(Gbar)
end reaction rules
end model
)BNG");
    REQUIRE(model);
    REQUIRE(model->getBarrierPatterns().size() == 1);
    REQUIRE(model->getReactionRules().size() == 1);
    // Renumbering makes the surviving rule indistinguishable from one written
    // without a barrier patterns block, even though the synthetic barrier rule
    // consumed a name during parsing.
    CHECK(model->getReactionRules()[0].getRuleName() == "R1");
    CHECK(model->getReactionRules()[0].hasDrivingWork());
}

TEST_CASE("a labelled barrier pattern keeps its label") {
    auto model = bng::parser::parseModel(R"BNG(
begin model
begin parameters
 Gbar 2
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin barrier patterns
 slow: A(s~U) -> A(s~P) Gbar
end barrier patterns
end model
)BNG");
    REQUIRE(model);
    REQUIRE(model->getBarrierPatterns().size() == 1);
    CHECK(model->getBarrierPatterns()[0].getLabel() == "slow");
}
