#include <catch2/catch_test_macros.hpp>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <utility>

#include "../../cpp/ast/MacroBNGModel.hpp"
#include "../../cpp/engine/NetworkGenerator.hpp"
// Include implementation to exercise evaluateRateString in anonymous namespace.
#include "../../cpp/engine/NetworkGenerator.cpp"
#include "../../cpp/ast/SpeciesList.hpp"

using namespace bng::engine;

TEST_CASE("parseBooleanLike behaves correctly", "[NetworkGenerator]") {
    // Source-derived from akutuva21/bionetgen commit f30898b6: preserve the
    // accepted boolean spellings while avoiding a temporary lowercased copy.
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

    const bng::ast::Species probe = makeSpecies("CP");
    const auto exact = list.findExact(probe);

    REQUIRE(exact.has_value());
    REQUIRE(exact.value() == first.first);
    REQUIRE_FALSE(probe.getSpeciesGraph().getGraph().is_canonical());
    REQUIRE_FALSE(list.findExact(makeSpecies("MITO")).has_value());

    // Source-derived from akutuva21/bionetgen commit 70acc9e2: the exact key
    // can be returned by lookup and reused by a subsequent keyed insertion.
    std::string exactKey;
    const auto missing = list.findExact(makeSpecies("MITO"), exactKey);
    REQUIRE_FALSE(missing.has_value());
    REQUIRE_FALSE(exactKey.empty());
    const auto keyed = list.addWithExactKey(makeSpecies("MITO"), std::move(exactKey));
    REQUIRE(keyed.second);
    REQUIRE(list.size() == 3);
}

TEST_CASE("MacroBNGModel num_site preserves Perl dependency semantics", "[MacroBNGModel]") {
    // Source-derived from legacy/perl/Perl2/MacroBNGModel.pm:num_site:
    // duplicate sites are numbered from the molecule-site inventory, while
    // the activated site and its remaining dependencies are returned in the
    // original order.
    bng::ast::MacroBNGModel macro;
    std::map<std::string, int> siteCounts{{"Lig:l", 2}};
    std::vector<std::string> dependencies;

    const auto active = macro.num_site("Lig(l,l)", "Lig(l!1,l)", siteCounts, dependencies);

    REQUIRE(active == "l");
    REQUIRE(dependencies == std::vector<std::string>{"l", "l:2"});

    dependencies.clear();
    REQUIRE(macro.num_site("Lig(l,l)", "Lig(l,l)", siteCounts, dependencies) == "%");
    REQUIRE(dependencies == std::vector<std::string>{"l"});
}

TEST_CASE("MacroBNGModel pre_macr runs the species and rule transforms", "[MacroBNGModel]") {
    // Source-derived from MacroBNGModel.pm::pre_macr: rule dependencies are
    // prepared before trans_rec/trans_specie write the combined macro BNGL.
    const auto workdir = std::filesystem::temp_directory_path() /
                          ("bng3_macro_model_" +
                          std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directories(workdir);
    const auto original = std::filesystem::current_path();
    struct WorkingDirectoryGuard {
        std::filesystem::path original;
        std::filesystem::path temporary;
        ~WorkingDirectoryGuard() {
            std::error_code error;
            std::filesystem::current_path(original, error);
            std::filesystem::remove_all(temporary, error);
        }
    } guard{original, workdir};
    std::filesystem::current_path(workdir);

    std::ofstream input("macro_input.bngl");
    input << "begin parameters\n"
          << "  k 1\n"
          << "end parameters\n"
          << "begin species\n"
          << "  Lig(l,l) 10\n"
          << "end species\n"
          << "begin reaction_rules\n"
          << "  Lig(l,l) -> Lig(l!1,l) k\n"
          << "end reaction_rules\n"
          << "end model\n";
    input.close();

    bng::ast::MacroBNGModel macro;
    REQUIRE(macro.pre_macr("macro_input") == "");

    std::ifstream output("macr_macro_input.bngl");
    std::stringstream contents;
    contents << output.rdbuf();
    const auto generated = contents.str();

    REQUIRE(generated.find("begin species") != std::string::npos);
    REQUIRE(generated.find("Lig_l(l) 10") != std::string::npos);
    REQUIRE(generated.find("begin reaction_rules") != std::string::npos);
}
