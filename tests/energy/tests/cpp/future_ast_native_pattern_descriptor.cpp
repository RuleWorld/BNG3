// RED CONTRACT: canonical AST graph must be the primary dependency source.
#include <catch2/catch_test_macros.hpp>
#include "compile/PatternDescriptor.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("PatternDescriptor is constructed from SpeciesGraph without reparsing source text") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
 A(x~U~P,y)
 B(z)
end molecule types
begin seed species
 A(x~U,y) 1
 B(z) 1
end seed species
begin reaction rules
 r: A(x~U,y) + B(z) -> A(x~P,y!1).B(z!1) 1
end reaction rules
)BNG");
    REQUIRE(model);
    const auto& rule = model->getReactionRules().all().front();
    REQUIRE_FALSE(rule.getReactantPatterns().empty());
    const auto descriptor = bng::compile::PatternDescriptor::fromSpeciesGraph(
        rule.getReactantPatterns().front());
    CHECK(descriptor.moleculeCount() == 1);
    CHECK(descriptor.hasSite("A","x"));
    CHECK(descriptor.hasSite("A","y"));
    CHECK(descriptor.stateConstraint("A","x") == "U");
}
