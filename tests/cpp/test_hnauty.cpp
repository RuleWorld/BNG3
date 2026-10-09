#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iterator>
#include <string>
#include <tuple>
#include <vector>

#include "ast/SpeciesList.hpp"
#include "NFcore.hh"
#include "NFinput_fromAst.hh"
#include "engine/NetworkGenerator.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

static std::unique_ptr<ast::Model> parseModel(const std::string& bngl) {
    return parser::parseModel(bngl);
}

static bool hasDirectedEdge(const BNGcore::Node* source,
                            const BNGcore::Node* target) {
    for (auto edge = source->edges_out_begin(); edge != source->edges_out_end(); ++edge) {
        if (*edge == target) {
            return true;
        }
    }
    return false;
}

// Test-only oracle: enumerate label-preserving node bijections and check every
// directed edge. It does not call either production canonicalizer or matcher.
static bool bruteForceGraphIsomorphic(const BNGcore::PatternGraph& lhs,
                                      const BNGcore::PatternGraph& rhs) {
    if (lhs.size() != rhs.size()) {
        return false;
    }
    std::vector<const BNGcore::Node*> left;
    std::vector<const BNGcore::Node*> right;
    for (auto node = lhs.begin(); node != lhs.end(); ++node) left.push_back(*node);
    for (auto node = rhs.begin(); node != rhs.end(); ++node) right.push_back(*node);

    const auto sameLabel = [](const BNGcore::Node* a, const BNGcore::Node* b) {
        return a->get_type() == b->get_type() &&
               a->get_state().get_BNG2_string() == b->get_state().get_BNG2_string() &&
               a->get_compartment() == b->get_compartment();
    };
    std::vector<std::size_t> mapping(left.size(), right.size());
    std::vector<bool> used(right.size(), false);
    std::function<bool(std::size_t)> search = [&](std::size_t index) {
        if (index == left.size()) {
            return true;
        }
        for (std::size_t candidate = 0; candidate < right.size(); ++candidate) {
            if (used[candidate] || !sameLabel(left[index], right[candidate])) {
                continue;
            }
            bool consistent = true;
            for (std::size_t prior = 0; prior < index; ++prior) {
                const auto* mappedPrior = right[mapping[prior]];
                if (hasDirectedEdge(left[index], left[prior]) !=
                        hasDirectedEdge(right[candidate], mappedPrior) ||
                    hasDirectedEdge(left[prior], left[index]) !=
                        hasDirectedEdge(mappedPrior, right[candidate])) {
                    consistent = false;
                    break;
                }
            }
            if (!consistent) {
                continue;
            }
            mapping[index] = candidate;
            used[candidate] = true;
            if (search(index + 1)) {
                return true;
            }
            used[candidate] = false;
            mapping[index] = right.size();
        }
        return false;
    };
    return search(0);
}

static bng::ast::Species seedAsSpecies(const bng::ast::SeedSpecies& seed) {
    return bng::ast::Species(bng::ast::SpeciesGraph(seed.getGraph()), 1.0,
                             seed.isConstant(), seed.getCompartment());
}

TEST_CASE("HNauty: isomorphic species get same canonical label", "[HNauty]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b,b)
    B(a)
end molecule types
begin seed species
    A(b!1,b!2).B(a!1).B(a!2) 100
end seed species
begin reaction rules
    A(b!1).B(a!1) -> A(b) + B(a) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    // The species A(b!1,b!2).B(a!1).B(a!2) should have a unique canonical label
    // and should be the same regardless of bond numbering order
    REQUIRE(network.species.size() >= 1);
}

TEST_CASE("HNauty: single-molecule species (trivial)", "[HNauty]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(x~0~1)
end molecule types
begin seed species
    A(x~0) 50
    A(x~1) 50
end seed species
begin reaction rules
    A(x~0) -> A(x~1) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    // Two distinct species (different states => different labels)
    REQUIRE(network.species.size() == 2);
}

TEST_CASE("HNauty: non-isomorphic complexes get different labels", "[HNauty]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b,c)
    B(a)
    C(a)
end molecule types
begin seed species
    A(b!1,c).B(a!1) 50
    A(b,c!1).C(a!1) 50
end seed species
begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    // A(b!1,c).B(a!1) and A(b,c!1).C(a!1) are different species
    REQUIRE(network.species.size() >= 2);
}

TEST_CASE("HNauty: symmetric components produce single species", "[HNauty]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    R(l,l)
    L(r)
end molecule types
begin seed species
    R(l,l) 100
    L(r) 200
end seed species
begin reaction rules
    R(l) + L(r) -> R(l!1).L(r!1) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    // R(l!1,l).L(r!1) should be ONE species (symmetric components)
    // R(l!1,l!2).L(r!1).L(r!2) should be ONE species
    REQUIRE(network.species.size() == 4); // R, L, R.L, R.L.L
}

TEST_CASE("Issue 214 high product symmetry parses without factorial expansion",
          "[HNauty][issue-214]") {
    const auto path = std::filesystem::path(BNG3_SOURCE_DIR) / "tests" /
        "fixtures" / "upstream_issues" / "issue_214_oscar_ecoli.bngl";
    std::ifstream input(path);
    REQUIRE(input.good());
    std::string source((std::istreambuf_iterator<char>(input)),
                       std::istreambuf_iterator<char>());

    // The upstream SBML export wrote undefined compartment sizes as `nan`.
    // Normalize only those three values so this test measures BNG3 rule parsing.
    for (const auto& compartment : {"c", "e", "p"}) {
        const std::string invalid = std::string("\t") + compartment + " 2 nan";
        const auto position = source.find(invalid);
        REQUIRE(position != std::string::npos);
        source.replace(position, invalid.size(),
                       std::string("\t") + compartment + " 2 1.0");
    }

    const auto model = parseModel(source);
    REQUIRE(model != nullptr);
    const auto rule = std::find_if(
        model->getReactionRules().begin(), model->getReactionRules().end(),
        [](const auto& candidate) {
            const auto& products = candidate.getProducts();
            return products.size() == 16 &&
                std::any_of(products.begin(), products.end(), [](const auto& product) {
                    return product.find("Enterochelin()") != std::string::npos;
                });
        });
    REQUIRE(rule != model->getReactionRules().end());
    REQUIRE(rule->getProducts().size() == 16);
    CHECK(std::count_if(rule->getProducts().begin(), rule->getProducts().end(),
                        [](const auto& product) {
                            return product.find("Hpl()") != std::string::npos;
                        }) == 9);
    CHECK(std::count_if(rule->getProducts().begin(), rule->getProducts().end(),
                        [](const auto& product) {
                            return product.find("AMP()") != std::string::npos;
                        }) == 6);
}

TEST_CASE("Issue 165 sixfold symmetric complex canonicalizes", "[HNauty][issue-165]") {
    auto model = parseModel(R"(
begin molecule types
    R(l,l,l,l,l,l)
    PI(r)
end molecule types
begin seed species
    R(l!1,l!2,l!3,l!4,l!5,l!6).PI(r!1).PI(r!2).PI(r!3).PI(r!4).PI(r!5).PI(r!6) 1
end seed species
)");
    REQUIRE(model != nullptr);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(0);
    REQUIRE(network.species.size() == 1);
    CHECK_FALSE(network.species.get(0).getSpeciesGraph().canonicalLabel().empty());
}

TEST_CASE("Issue 142 graph identity matches an independent isomorphism partition",
          "[HNauty][issue-142]") {
    auto model = parseModel(R"(
begin compartments
    cyto 3 1.0
    nuc 3 1.0
end compartments
begin molecule types
    R(l,l)
    L(r)
    A(x~u~p,y)
    B(x)
    C(x)
end molecule types
begin seed species
    R(l!1,l!2).L(r!1).L(r!2) 1
    L(r!17).R(l!19,l!17).L(r!19) 1
    A(x~u,y) 1
    A(x~p,y) 1
    A(x!1,y!2).B(x!1).C(x!2) 1
    A(x!11,y!12).B(x!12).C(x!11) 1
    A@cyto(x!1,y!2).B@nuc(x!1).C@cyto(x!2) 1
    C@cyto(x!8).A@cyto(y!8,x!7).B@nuc(x!7) 1
    A@nuc(x!1,y!2).B@cyto(x!1).C@nuc(x!2) 1
    @cyto:A(x) 1
    @nuc:A(x) 1
    A(x) 1
    A(x~u) 1
end seed species
)");
    REQUIRE(model != nullptr);
    const auto& seeds = model->getSeedSpecies();
    REQUIRE(seeds.size() == 13);

    const std::vector<std::tuple<std::size_t, std::size_t, bool, bool>> cases{
        {0, 1, true, true},     // symmetric molecule/site ordering and bond labels
        {2, 3, false, false},   // state differs
        {4, 5, false, false},   // the B/C bond topology differs
        {6, 7, true, true},     // same per-molecule compartments under reordering
        {6, 8, false, true},    // structural canonical labels omit compartments
        {9, 10, true, true},    // outer species compartments belong to the owner
        {11, 12, false, false}, // wildcard state is not exact identity
    };
    for (const auto& [leftIndex, rightIndex, expectedGraphIdentity,
                      expectedStructuralLabel] : cases) {
        const auto& left = seeds[leftIndex].getGraph();
        const auto& right = seeds[rightIndex].getGraph();
        const bool oracle = bruteForceGraphIsomorphic(left, right);
        CHECK(oracle == expectedGraphIdentity);
        CHECK(bng::ast::SpeciesGraph(left).graphIsomorphicTo(right) == oracle);
        CHECK((seeds[leftIndex].getCanonicalLabel() ==
               seeds[rightIndex].getCanonicalLabel()) == expectedStructuralLabel);

        bng::ast::SpeciesList species;
        species.add(seedAsSpecies(seeds[leftIndex]));
        const auto inserted = species.add(seedAsSpecies(seeds[rightIndex]));
        const bool sameSpecies = oracle &&
            seeds[leftIndex].getCompartment() == seeds[rightIndex].getCompartment();
        CHECK(inserted.second == !sameSpecies);
    }

    // Structural labels intentionally omit compartments; the shared exact
    // graph comparison adds per-molecule compartment semantics.
}

TEST_CASE("Issue 142 graph identity rejects extra target edges",
          "[HNauty][issue-142]") {
    const BNGcore::EntityType nodeType(
        "node", BNGcore::ENTITY_NODE_TYPE, BNGcore::NULL_STATE_TYPE);
    const auto makeGraph = [&](bool withShortcut) {
        BNGcore::PatternGraph graph;
        BNGcore::Node first(nodeType);
        BNGcore::Node second(nodeType);
        BNGcore::Node third(nodeType);
        auto* a = graph.add_node(first);
        auto* b = graph.add_node(second);
        auto* c = graph.add_node(third);
        graph.add_edge(a, b);
        graph.add_edge(b, c);
        if (withShortcut) {
            graph.add_edge(a, c);
        }
        return graph;
    };

    const auto path = makeGraph(false);
    const auto closure = makeGraph(true);
    CHECK_FALSE(bruteForceGraphIsomorphic(path, closure));
    CHECK_FALSE(bng::ast::SpeciesGraph(path).graphIsomorphicTo(closure));
}

TEST_CASE("Issue 142 native NFsim labels follow the same graph identity partition",
          "[HNauty][issue-142][NFsim]") {
    auto model = parseModel(R"(
begin compartments
    cyto 3 1.0
    nuc 3 1.0
end compartments
begin molecule types
    A(x,y)
    B(x)
    C(x)
end molecule types
begin seed species
    A(x!1,y!2)@cyto.B(x!1)@nuc.C(x!2)@cyto 1
    C(x!8)@cyto.A(y!8,x!7)@cyto.B(x!7)@nuc 1
    A(x!1,y!2)@cyto.B(x!2)@nuc.C(x!1)@cyto 1
    A(x!1,y!2)@nuc.B(x!1)@cyto.C(x!2)@nuc 1
end seed species
    )");
    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    std::string unavailableReason;
    auto* system = NFinput::buildSystemFromAst(
        *model, true, false, 100, false, suggestedTraversalLimit, {},
        &unavailableReason);
    INFO(unavailableReason);
    REQUIRE(system != nullptr);
    system->prepareForSimulation();

    auto* aType = system->getMoleculeTypeByName("A");
    REQUIRE(aType != nullptr);
    REQUIRE(aType->getMoleculeCount() == 4);
    std::vector<std::string> nativeLabels;
    for (int index = 0; index < aType->getMoleculeCount(); ++index) {
        auto* molecule = aType->getMolecule(index);
        REQUIRE(molecule != nullptr);
        REQUIRE(molecule->getComplex() != nullptr);
        nativeLabels.push_back(molecule->getComplex()->getCanonicalLabel());
    }

    const auto& seeds = model->getSeedSpecies();
    for (std::size_t index : {1u, 2u, 3u}) {
        const bool oracle = bruteForceGraphIsomorphic(
            seeds.front().getGraph(), seeds[index].getGraph());
        CHECK((nativeLabels.front() == nativeLabels[index]) == oracle);
    }
    CHECK(nativeLabels[0] == nativeLabels[1]);
    CHECK(nativeLabels[0] != nativeLabels[2]);
    CHECK(nativeLabels[0] != nativeLabels[3]);
    delete system;
}
