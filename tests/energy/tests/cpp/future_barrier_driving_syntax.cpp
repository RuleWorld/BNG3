// RED CONTRACT: parser/API semantics for future thermodynamic language extensions.
// Keep disabled until syntax is deliberately chosen and documented.
#include <catch2/catch_test_macros.hpp>
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("barrier pattern parses as transition-state contribution, not state free energy") {
    auto model = bng::parser::parseModel(R"BNG(
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
}

TEST_CASE("driving reservoir annotates reversible rule with signed chemical work") {
    auto model = bng::parser::parseModel(R"BNG(
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
    CHECK(model->getReactionRules()[0].drivingWorkExpression().toString() == "muATP");
}
