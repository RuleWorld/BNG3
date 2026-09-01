#include <catch2/catch_test_macros.hpp>
#include <utility>

#include "../../cpp/engine/NetworkGenerator.hpp"
// Include implementation to exercise evaluateRateString in anonymous namespace.
#include "../../cpp/engine/NetworkGenerator.cpp"
#include "../../cpp/ast/SpeciesList.hpp"

using namespace bng::engine;

TEST_CASE("parseBooleanLike behaves correctly", "[NetworkGenerator]") {
    // positive cases
    REQUIRE(parseBooleanLike("1") == true);
    REQUIRE(parseBooleanLike("true") == true);
    REQUIRE(parseBooleanLike("yes") == true);
    REQUIRE(parseBooleanLike("on") == true);

    // case insensitivity
    REQUIRE(parseBooleanLike("TRUE") == true);
    REQUIRE(parseBooleanLike("YeS") == true);
    REQUIRE(parseBooleanLike("ON") == true);

    // negative cases
    REQUIRE(parseBooleanLike("0") == false);
    REQUIRE(parseBooleanLike("false") == false);
    REQUIRE(parseBooleanLike("no") == false);
    REQUIRE(parseBooleanLike("off") == false);

    // empty string and invalid
    REQUIRE(parseBooleanLike("") == false);
    REQUIRE(parseBooleanLike("asdf") == false);
    REQUIRE(parseBooleanLike("2") == false);
}

TEST_CASE("SpeciesList preserves compartment-aware deduplication", "[SpeciesList]") {
    // Source-derived from akutuva21/bionetgen commit 5291159d: exact-key
    // fast paths must not merge per-molecule compartments under one species
    // compartment.
    BNGcore::EntityType moleculeType("M", BNGcore::ENTITY_NODE_TYPE, BNGcore::NULL_STATE_TYPE);
    BNGcore::EntityType componentType("site", BNGcore::COMPONENT_NODE_TYPE, BNGcore::NULL_STATE_TYPE);

    auto makeSpecies = [&](const std::string& moleculeCompartment) {
        BNGcore::PatternGraph graph;
        BNGcore::Node molecule(moleculeType);
        BNGcore::Node component(componentType);
        auto* moleculeNode = graph.add_node(molecule);
        auto* componentNode = graph.add_node(component);
        moleculeNode->set_compartment(moleculeCompartment);
        graph.add_edge(moleculeNode, componentNode);
        return bng::ast::Species(
            bng::ast::SpeciesGraph(std::move(graph), "NM"),
            0.0,
            false,
            "NM");
    };

    bng::ast::Species cytosolic = makeSpecies("CP");
    bng::ast::Species nuclear = makeSpecies("NU");
    bng::ast::SpeciesList list;

    const auto first = list.add(cytosolic);
    const auto second = list.add(nuclear);
    const auto duplicate = list.add(cytosolic);

    REQUIRE(first.second);
    REQUIRE(second.second);
    REQUIRE_FALSE(duplicate.second);
    REQUIRE(duplicate.first == first.first);
    REQUIRE(list.size() == 2);
}
