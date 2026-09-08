#include <catch2/catch_test_macros.hpp>

#include "compile/Pattern.hpp"
#include "compile/PatternLowering.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("PatternDescriptor compiles a resolved SpeciesGraph without reparsing") {
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
    const auto& rule = model->getReactionRules().front();
    REQUIRE_FALSE(rule.getReactantPatterns().empty());
    const auto descriptor = bng::compile::PatternDescriptor::fromSpeciesGraph(
        rule.getReactantPatterns().front());
    CHECK(descriptor.moleculeCount() == 1);
    CHECK(descriptor.hasSite("A", "x"));
    CHECK(descriptor.hasSite("A", "y"));
    CHECK(descriptor.stateConstraint("A", "x") == "U");
}

TEST_CASE("Pattern can copy a parsed graph without retaining graph ownership") {
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
    const auto& graph = model->getReactionRules().front().getProductPatterns().front();
    const auto descriptor = bng::compile::Pattern::fromPatternGraph(
        graph.getGraph(), graph.getCompartment());
    CHECK(descriptor.sourceText().empty());
    CHECK(descriptor.moleculeCount() == 2);
    CHECK(descriptor.hasSite("A", "x"));
    CHECK(descriptor.hasSite("B", "z"));
}

TEST_CASE("PatternDescriptor parser preserves state and bond constraints") {
    const auto descriptor = bng::compile::Pattern::parse(
        "A(x~P!1,y!+).B(z!1)");
    REQUIRE(descriptor.moleculeCount() == 2);
    CHECK(descriptor.hasSite("A", "x"));
    CHECK(descriptor.stateConstraint("A", "x") == "P");
    REQUIRE(descriptor.molecules().front().sites.size() == 2);
    CHECK(descriptor.molecules().front().sites[0].bondConstraint == "1");
    CHECK(descriptor.molecules().front().sites[1].bondConstraint == "+");
}

TEST_CASE("PatternDescriptor assigns stable occurrence identities and bond groups") {
    const auto descriptor = bng::compile::PatternDescriptor::parse(
        "A(x!1,y!1).A(x!2,y!2)");
    REQUIRE(descriptor.molecules().size() == 2);

    CHECK(descriptor.molecules()[0].occurrence.value == 0);
    CHECK(descriptor.molecules()[1].occurrence.value == 1);
    CHECK(descriptor.molecules()[0].sites[0].occurrence.value == 0);
    CHECK(descriptor.molecules()[0].sites[1].occurrence.value == 1);
    CHECK(descriptor.molecules()[0].sites[0].bondKind ==
          bng::compile::BondConstraintKind::Exact);
    CHECK(descriptor.molecules()[0].sites[0].bondGroup.value == 1);
    CHECK(descriptor.molecules()[1].sites[0].bondGroup.value == 2);
}

TEST_CASE("PatternDescriptor distinguishes wildcard bond constraints") {
    const auto descriptor = bng::compile::PatternDescriptor::parse(
        "A(x!+,y!?,z)");
    REQUIRE(descriptor.molecules().front().sites.size() == 3);
    CHECK(descriptor.molecules().front().sites[0].bondKind ==
          bng::compile::BondConstraintKind::Bound);
    CHECK(descriptor.molecules().front().sites[1].bondKind ==
          bng::compile::BondConstraintKind::Any);
    CHECK(descriptor.molecules().front().sites[2].bondKind ==
          bng::compile::BondConstraintKind::Unspecified);
}

TEST_CASE("PatternDescriptor preserves multiple bonds on one component") {
    const auto descriptor = bng::compile::Pattern::parse(
        "A(x!1!2).B(y!1).C(z!2)");
    REQUIRE(descriptor.molecules().front().sites.size() == 1);
    const auto& bonds = descriptor.molecules().front().sites.front().bondConstraints;
    REQUIRE(bonds.size() == 2);
    CHECK(bonds[0].kind == bng::compile::BondConstraintKind::Exact);
    CHECK(bonds[1].kind == bng::compile::BondConstraintKind::Exact);
    CHECK(bonds[0].group.value != bonds[1].group.value);
    CHECK(descriptor.molecules().front().sites.front().bondConstraint == "1");
}

TEST_CASE("Pattern BNGcore lowering retains multiple explicit bonds") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
 A(x)
 B(y)
 C(z)
end molecule types
)BNG");
    REQUIRE(model);
    const auto pattern = bng::compile::Pattern::parse(
        "A(x!1!2).B(y!1).C(z!2)");
    const auto graph = bng::compile::lowerPatternToBNGcore(pattern, *model);
    // 3 molecule nodes + 3 component nodes + 2 shared bond nodes.
    CHECK(graph.size() == 8);
    CHECK_FALSE(graph.computeFingerprint().empty());
}

TEST_CASE("Pattern semantic equality ignores source bond numbering") {
    const auto first = bng::compile::Pattern::parse("A(x!1).B(y!1)");
    const auto second = bng::compile::Pattern::parse("A(x!17).B(y!17)");
    const auto different = bng::compile::Pattern::parse("A(x!1).B(y!2)");
    CHECK(first == second);
    CHECK(first != different);
    CHECK(first.sourceText() != second.sourceText());
}

TEST_CASE("Pattern lowers to an independent BNGcore graph") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
 A(x~U~P)
 B(y)
end molecule types
begin seed species
 A(x~P) 1
 B(y) 1
end seed species
begin reaction rules
 r: A(x~P!1).B(y!1) -> A(x~P!1).B(y!1) 1
end reaction rules
)BNG");
    REQUIRE(model);

    const auto pattern = bng::compile::Pattern::parse("A(x~P!1).B(y!1)");
    const auto graph = bng::compile::lowerPatternToBNGcore(pattern, *model);
    CHECK(graph.size() == 5);
    CHECK_FALSE(graph.computeFingerprint().empty());
    REQUIRE(model->getReactionRules().size() == 1);
    CHECK(graph.computeFingerprint() ==
          model->getReactionRules().front().getReactantPatterns().front().getGraph()
              .computeFingerprint());
}
