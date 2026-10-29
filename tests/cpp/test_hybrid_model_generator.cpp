#include <catch2/catch_all.hpp>
#include "../../cpp/engine/HybridModelGenerator.hpp"
#include "../../cpp/ast/Model.hpp"
#include "../../cpp/ast/RefineRule.hpp"
#include "../../cpp/engine/NetworkGenerator.hpp"
#include "../../cpp/parser/BNGAstVisitor.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <vector>

using namespace bng::engine;
using namespace bng::ast;

namespace bng::engine {
class HybridModelGeneratorTest {
public:
    static bool callIsIsomorphic(const HybridModelGenerator& generator, const std::string& pattern1, const std::string& pattern2) {
        return generator.isIsomorphic(pattern1, pattern2);
    }
};
}

TEST_CASE("HybridModelGenerator tests", "[hybrid]") {
    SECTION("Empty model should throw due to missing definitions") {
        Model model;
        PopulationMap pmap;
        pmap.label = "map1";
        pmap.patternText = "A()";
        pmap.populationFunction = "pop_A";
        model.addPopulationMap(pmap);

        model.addMoleculeType(MoleculeType("A", {}));

        HybridModelGenerator generator(model);
        HybridModelGenerator::Options opts;
        opts.prefix = "test_empty";
        opts.overwrite = true;

        REQUIRE_THROWS_AS(generator.generate("dummy_source.bngl", opts), std::runtime_error);
    }

    SECTION("Model with population map generates proper rules") {
        Model model;
        PopulationMap pmap;
        pmap.label = "map1";
        pmap.patternText = "A()";
        pmap.populationFunction = "pop_A";
        model.addPopulationMap(pmap);

        model.addCompartment(Compartment("C", 3, 1.0));
        model.addMoleculeType(MoleculeType("A", {}));
        model.addSeedSpecies(SeedSpecies("A()", Expression::number(100)));
        model.addReactionRule(ReactionRule("rule1", "r1", {"A()"}, {}, {Expression::number(1)}, {}, false));
        model.addObservable(Observable("obs1", "Molecules", {"A()"}));

        HybridModelGenerator generator(model);
        HybridModelGenerator::Options opts;
        opts.prefix = "test_model";
        opts.overwrite = true;

        auto result = generator.generate("dummy_source.bngl", opts);

        REQUIRE(result.hybridModelName == "test_model_hpp");
        REQUIRE(result.nPopulationMaps == 1);
        REQUIRE(result.nMoleculeTypes == 2);
        REQUIRE(result.nSeedSpecies == 1);
        REQUIRE(result.nZeroPopulations == 0);
        REQUIRE(result.nRules >= 1);
    }

    SECTION("Rule expansion should correctly copy or specialize rules") {
        Model model;
        PopulationMap pmap;
        pmap.label = "map1";
        pmap.patternText = "A()";
        pmap.populationFunction = "pop_A";
        model.addPopulationMap(pmap);

        model.addMoleculeType(MoleculeType("A", {}));
        model.addMoleculeType(MoleculeType("B", {}));
        model.addSeedSpecies(SeedSpecies("A()", Expression::number(100)));
        model.addSeedSpecies(SeedSpecies("B()", Expression::number(10)));

        model.addReactionRule(ReactionRule("rule_B", "rB", {"B()"}, {}, {Expression::number(1)}, {}, false));
        model.addReactionRule(ReactionRule("rule_A", "rA", {"A()"}, {}, {Expression::number(1)}, {}, false));

        HybridModelGenerator generator(model);
        HybridModelGenerator::Options opts;
        opts.prefix = "test_rules";
        opts.overwrite = true;
        opts.safe = false;

        auto result = generator.generate("dummy_source.bngl", opts);

        REQUIRE(result.nRules == 2);

        std::ifstream bngl("test_rules_hpp.bngl");
        std::string content((std::istreambuf_iterator<char>(bngl)), std::istreambuf_iterator<char>());

        REQUIRE(content.find("rule_B:") != std::string::npos);
        REQUIRE(content.find("rule_A:") != std::string::npos);
        REQUIRE(content.find("rule_A_pop:") != std::string::npos);
        REQUIRE(content.find("_map_pop_A:") != std::string::npos);
    }

    SECTION("Preconditions validation") {
        Model model;
        HybridModelGenerator generator(model);
        HybridModelGenerator::Options opts;

        REQUIRE_THROWS_AS(generator.generate("dummy", opts), std::runtime_error);
    }

    SECTION("isIsomorphic replaces isomorphic population equivalents correctly") {
        Model model;
        PopulationMap pmap;
        pmap.label = "map1";
        pmap.patternText = "A(b!1).B(a!1)";
        pmap.populationFunction = "pop_AB";
        model.addPopulationMap(pmap);

        model.addMoleculeType(MoleculeType("A", {{"b"}}));
        model.addMoleculeType(MoleculeType("B", {{"a"}}));

        model.addSeedSpecies(SeedSpecies("B(a!1).A(b!1)", Expression::number(100)));
        model.addSeedSpecies(SeedSpecies("A(b)", Expression::number(50)));
        // Add a dummy reaction rule to bypass the throw
        model.addReactionRule(ReactionRule("rule1", "r1", {"A()"}, {}, {Expression::number(1)}, {}, false));

        HybridModelGenerator generator(model);
        HybridModelGenerator::Options opts;
        opts.prefix = "test_isomorphic";
        opts.overwrite = true;

        auto result = generator.generate("dummy_source.bngl", opts);

        std::ifstream bngl("test_isomorphic_hpp.bngl");
        std::string content((std::istreambuf_iterator<char>(bngl)), std::istreambuf_iterator<char>());

        REQUIRE(content.find("pop_AB() 100") != std::string::npos);
        REQUIRE(content.find("A(b) 50") != std::string::npos);
        REQUIRE(content.find("B(a!1).A(b!1) 100") == std::string::npos);
    }

    SECTION("countMatches correctly counts matches in observable") {
        Model model;
        PopulationMap pmap;
        pmap.label = "map1";
        pmap.patternText = "A(b!1).B(a!1)"; // This pattern forms pop_AB
        pmap.populationFunction = "pop_AB";
        model.addPopulationMap(pmap);

        model.addMoleculeType(MoleculeType("A", {{"b"}}));
        model.addMoleculeType(MoleculeType("B", {{"a"}}));

        // Let's add observables matching parts
        model.addObservable(Observable("obs_A", "Molecules", {"A()"}));
        model.addObservable(Observable("obs_B", "Molecules", {"B()"}));

        // Seed species
        model.addSeedSpecies(SeedSpecies("A(b!1).B(a!1)", Expression::number(100)));
        model.addReactionRule(ReactionRule("rule1", "r1", {"A()"}, {}, {Expression::number(1)}, {}, false));

        HybridModelGenerator generator(model);
        HybridModelGenerator::Options opts;
        opts.prefix = "test_matches";
        opts.overwrite = true;

        auto result = generator.generate("dummy_source.bngl", opts);

        std::ifstream bngl("test_matches_hpp.bngl");
        std::string content((std::istreambuf_iterator<char>(bngl)), std::istreambuf_iterator<char>());

        // obs_A and obs_B should both now include pop_AB() because A() and B() both match inside pop_AB()
        bool contains_A = content.find("obs_A A(),pop_AB()") != std::string::npos || content.find("obs_A Molecules A(),pop_AB()") != std::string::npos;
        REQUIRE(contains_A);
    }
}

TEST_CASE("HybridModelGenerator isIsomorphic error handling", "[HybridModelGenerator]") {
    bng::ast::Model model;
    bng::engine::HybridModelGenerator generator(model);

    REQUIRE(bng::engine::HybridModelGeneratorTest::callIsIsomorphic(generator, "A(x~1, x~2)", "A()") == false);
    REQUIRE(bng::engine::HybridModelGeneratorTest::callIsIsomorphic(generator, "\x01", "A()") == false);
    REQUIRE(bng::engine::HybridModelGeneratorTest::callIsIsomorphic(generator, "!!InvalidBNGL!!", "A()") == false);
    REQUIRE(bng::engine::HybridModelGeneratorTest::callIsIsomorphic(generator, "A(x!1)) garbage", "A()") == false);
}

TEST_CASE("Hybrid self embeddings are rebound to the owned target graph", "[hybrid][RefineRule]") {
    auto model = bng::parser::parseModel(R"(
begin molecule types
    A(x~u~p)
end molecule types
begin reaction rules
    convert: A(x~u) -> A(x~p) 1
end reaction rules
)");
    Model hybridModel;
    bng::ast::RefineRuleParams params;
    params.safe = true;

    const auto refined = bng::ast::expandRule(
        model->getReactionRules().front(), {}, *model, hybridModel, params);

    REQUIRE(refined.error.empty());
    REQUIRE(refined.childRules.size() == 1);
    REQUIRE(refined.childRules.front().getProducts().size() == 1);
    CHECK(refined.childRules.front().getProducts().front().find("x~p") !=
          std::string::npos);
}

namespace {

std::unique_ptr<Model> parseHybridSource() {
    // tests/validation/Validate/hybrid_test.bngl with its rules labelled.
    return bng::parser::parseModel(R"(
begin model
begin parameters
    koff  0.01
    kp1   2
    kp2   5
    k_gather 100000
end parameters
begin molecule types
    R(l,l)
    L(r,r,r)
end molecule types
begin seed species
    R(l,l)    3000
    L(r,r,r)  50000
end seed species
begin observables
    Molecules Rfree R(l,l)
    Molecules Lfree L(r,r,r)
end observables
begin reaction rules
    R1: R(l!1).L(r!1) -> R(l) + L(r) koff
    R2: L(r,r,r) + R(l) -> L(r!1,r,r).R(l!1) kp1
    R3: L(r,r,r!+) + R(l) -> L(r!1,r,r!+).R(l!1) kp2
    R4: L(r,r!+,r!+) + R(l) -> L(r!1,r!+,r!+).R(l!1) kp2
end reaction rules
begin population maps
    L(r,r,r) -> L_pop() k_gather
    R(l,l) -> R_pop() k_gather
end population maps
end model
)");
}

std::string slurp(const std::string& path) {
    std::ifstream in(path);
    return std::string((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

} // namespace

TEST_CASE("hybrid children carry BNG2's reaction-center multiplicities",
          "[hybrid][RefineRule]") {
    // Pinned BNG2 (RuleWorld/bionetgen@9601746f) gives the association
    // children of hybrid_test.bngl the rate multipliers 3 and 6 (R2), 1 and
    // 2 (R3), 1 and 2 (R4): the number of distinct reaction-center images of
    // each reactant pattern in the population species L(r,r,r) and R(l,l),
    // as find_embeddings/filter_identical_by_rxn_center count them.  The R4
    // population child used to get 1, because its two equivalent r!+
    // context sites were divided out as a product-pattern symmetry.
    auto model = parseHybridSource();
    REQUIRE(model != nullptr);
    HybridModelGenerator generator(*model);
    HybridModelGenerator::Options opts;
    opts.prefix = "test_hybrid_multiplicity";
    opts.overwrite = true;
    opts.safe = false;
    generator.generate("test_hybrid_multiplicity.bngl", opts);

    auto hybrid = bng::parser::parseModel(slurp("test_hybrid_multiplicity_hpp.bngl"));
    REQUIRE(hybrid != nullptr);
    const auto& parameters = hybrid->getParameters();
    std::map<std::string, std::pair<std::string, double>> children;
    for (const auto& rule : hybrid->getReactionRules()) {
        const auto& rate = rule.getRates().front().toString();
        children[rule.getRuleName()] = {rate, parameters.evaluate(rate)};
    }
    const std::map<std::string, double> expected{
        {"R2_v1", 3 * 2.0}, {"R2_v2", 6 * 2.0},
        {"R3_v1", 1 * 5.0}, {"R3_v2", 2 * 5.0},
        {"R4_v1", 1 * 5.0}, {"R4_v2", 2 * 5.0},
    };
    for (const auto& [name, value] : expected) {
        INFO(name);
        REQUIRE(children.count(name) == 1);
        CHECK(children[name].second == Catch::Approx(value).epsilon(1e-12));
    }
}

TEST_CASE("hybrid child rules keep the source's bound-to-anything context",
          "[hybrid][RefineRule]") {
    // A bound site with no partner (!+) used to be written as a numbered
    // dangling bond, so the authored R3/R4 children lost the context the
    // source rules require.
    auto model = parseHybridSource();
    REQUIRE(model != nullptr);
    HybridModelGenerator generator(*model);
    HybridModelGenerator::Options opts;
    opts.prefix = "test_hybrid_context";
    opts.overwrite = true;
    opts.safe = false;
    generator.generate("test_hybrid_context.bngl", opts);

    auto hybrid = bng::parser::parseModel(slurp("test_hybrid_context_hpp.bngl"));
    REQUIRE(hybrid != nullptr);
    for (const auto& rule : hybrid->getReactionRules()) {
        const auto& name = rule.getRuleName();
        if (name.rfind("R3_", 0) != 0 && name.rfind("R4_", 0) != 0) continue;
        INFO(name);
        std::size_t wildcards = 0;
        for (const auto& reactant : rule.getReactants()) {
            for (std::size_t at = reactant.find("!+"); at != std::string::npos;
                 at = reactant.find("!+", at + 2)) {
                ++wildcards;
            }
        }
        CHECK(wildcards == (name.rfind("R3_", 0) == 0 ? 1u : 2u));
    }
}

TEST_CASE("a component tag pins its reactant component before order matching",
          "[RefineRule][ReactionRule]") {
    // BNG2 writes refined children with a correspondence tag only where the
    // order alone is ambiguous: here the bound r%T1 is listed first on the
    // left and second on the right.  The untagged r!1 on the right must take
    // a free r on the left; mapping it onto the tagged component made a
    // second bond on an already bound site (r!1!2).
    const char* seeds = R"(
begin seed species
    L(r!1,r,r).R(l!1,l)  1
    R(l,l)               1
end seed species
)";
    auto network = [&](const std::string& rule) {
        auto model = bng::parser::parseModel(std::string(R"(
begin model
begin parameters
    kp2 1
end parameters
begin molecule types
    R(l,l)
    L(r,r,r)
end molecule types
)") + seeds + "begin reaction rules\n    " + rule + "\nend reaction rules\nend model\n");
        REQUIRE(model != nullptr);
        bng::engine::NetworkGenerator generator(*model);
        auto generated = generator.generateNative(2);
        std::vector<std::string> species;
        for (std::size_t i = 0; i < generated.species.size(); ++i) {
            species.push_back(generated.species.get(i).getSpeciesGraph().toString());
        }
        std::sort(species.begin(), species.end());
        return species;
    };
    const auto tagged = network("L(r%T1!+,r,r) + R(l) -> L(r!1,r%T1!+,r).R(l!1) kp2");
    const auto source = network("L(r,r,r!+) + R(l) -> L(r!1,r,r!+).R(l!1) kp2");
    CHECK(tagged == source);
    for (const auto& name : tagged) {
        INFO(name);
        CHECK(name.find("!1!") == std::string::npos);
        CHECK(name.find("!2!") == std::string::npos);
    }
}
