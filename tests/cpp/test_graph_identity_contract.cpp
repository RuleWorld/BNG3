// Differential regression coverage for the shared identity contract of
// issue #142.  The contract lives in cpp/core/IdentityContract.hpp; this test
// keeps every surface that uses it honest:
//
//   * the structural decision agrees with the labeled-graph relation,
//   * the network canonical label decides the structure layer,
//   * the NFsim complex canonical label decides the structure and
//     compartment layers, and
//   * the network species identity decides the species layer.
//
// The independent isomorphism oracle used by the qualification harness is
// tests/validation/graph_identity_contract.py; this test guards the native
// side of the same contract.

#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <filesystem>
#include <string>
#include <vector>

#include "ast/SpeciesGraph.hpp"
#include "ast/SpeciesList.hpp"
#include "core/IdentityContract.hpp"
#include "NFcore.hh"
#include "NFinput_fromAst.hh"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

namespace {

std::unique_ptr<ast::Model> parseModel(const std::string& bngl) {
    return parser::parseModel(bngl);
}

// The canonical label of the one complex the seed species forms.  A model with
// a single seed species has exactly one complex that holds its molecules, so
// no association is needed.
std::string complexLabelOf(const std::string& bngl) {
    const auto model = parseModel(bngl);
    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    std::string unavailableReason;
    auto* system = NFinput::buildSystemFromAst(
        *model, true, false, 100, false, suggestedTraversalLimit, {},
        &unavailableReason);
    INFO(unavailableReason);
    REQUIRE(system != nullptr);
    NFcore::Complex* complex = nullptr;
    for (int index = 0;
         index < system->getNumOfMoleculeTypes() && complex == nullptr;
         ++index) {
        auto* type = system->getMoleculeType(index);
        if (type->getMoleculeCount() > 0) {
            complex = type->getMolecule(0)->getComplex();
        }
    }
    REQUIRE(complex != nullptr);
    const std::string label = complex->getCanonicalLabel();
    delete system;
    return label;
}

} // namespace

TEST_CASE("Issue 142 identity contract names the layers it decides",
          "[issue-142][identity-contract]") {
    CHECK(std::string(bng::identity::layerName(bng::identity::Layer::Structure)) ==
          "structure");
    CHECK(std::string(bng::identity::layerName(bng::identity::Layer::Compartment)) ==
          "structure+compartment");
    CHECK(std::string(bng::identity::layerName(bng::identity::Layer::Species)) ==
          "species");

    CHECK(bng::identity::layerIncludes(bng::identity::Layer::Compartment,
                                       bng::identity::Layer::Structure));
    CHECK(bng::identity::layerIncludes(bng::identity::Layer::Species,
                                       bng::identity::Layer::Compartment));
    CHECK(bng::identity::layerIncludes(bng::identity::Layer::Species,
                                       bng::identity::Layer::Structure));
    CHECK_FALSE(bng::identity::layerIncludes(bng::identity::Layer::Structure,
                                             bng::identity::Layer::Compartment));
    CHECK_FALSE(bng::identity::layerIncludes(bng::identity::Layer::Compartment,
                                             bng::identity::Layer::Species));

    // Every surface states the layer it decides.
    CHECK(std::string(bng::ast::SpeciesGraph::identityLayer()) == "structure");
    CHECK(std::string(NFcore::Complex::identityLayer()) ==
          "structure+compartment");
    CHECK(std::string(bng::ast::SpeciesList::identityLayer()) == "species");
}

TEST_CASE("Issue 142 structural decision keeps the labeled-graph relation",
          "[issue-142][identity-contract]") {
    const auto model = parseModel(R"(
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

    const std::vector<std::tuple<std::size_t, std::size_t, bool>> cases{
        {0, 1, true},   // symmetric molecule/site ordering and bond labels
        {2, 3, false},  // state differs
        {4, 5, false},  // the B/C bond topology differs
        {6, 7, true},   // same per-molecule compartments under reordering
        {6, 8, false},  // the per-molecule compartments differ
        {9, 10, true},  // outer species compartments belong to the owner
        {11, 12, false},// wildcard state is not exact identity
    };
    for (const auto& [leftIndex, rightIndex, expected] : cases) {
        const auto& left = seeds[leftIndex].getGraph();
        const auto& right = seeds[rightIndex].getGraph();
        CHECK(bng::identity::sameMoleculeGraph(left, right) == expected);
        // The species graph uses the same decision.
        CHECK(bng::ast::SpeciesGraph(left).graphIsomorphicTo(right) == expected);
    }

    // The canonical label decides the structure layer, so it cannot separate
    // species that differ only in their compartments.
    CHECK(seeds[6].getCanonicalLabel() == seeds[7].getCanonicalLabel());
    CHECK(seeds[6].getCanonicalLabel() == seeds[8].getCanonicalLabel());
    CHECK(seeds[6].getCanonicalLabel() == seeds[4].getCanonicalLabel());
    // It does separate species that differ in structure or state.
    CHECK(seeds[2].getCanonicalLabel() != seeds[3].getCanonicalLabel());
    CHECK(seeds[4].getCanonicalLabel() != seeds[5].getCanonicalLabel());
}

TEST_CASE("Issue 142 NFsim complex label decides the compartment layer",
          "[issue-142][identity-contract][NFsim]") {
    const std::string compartments = R"(
begin compartments
    PM 2 1.0
    CP 3 1.0 PM
end compartments
)";
    const std::string moleculeTypes = R"(
begin molecule types
    A(x,y)
    B(x)
end molecule types
)";
    const std::string plain =
        compartments + moleculeTypes +
        R"(
begin seed species
    A(x!1,y)@PM.B(x!1)@PM 1
end seed species
)";
    // The same complex with renumbered bonds, reversed traversal order and a
    // swapped site order.
    const std::string permuted =
        compartments + moleculeTypes +
        R"(
begin seed species
    B(x!7)@PM.A(x!7,y)@PM 1
end seed species
)";
    // The same structure with a different molecule compartment.
    const std::string otherCompartment =
        compartments + moleculeTypes +
        R"(
begin seed species
    A(x!1,y!2)@PM.B(x!1)@CP 1
end seed species
)";

    const std::string plainLabel = complexLabelOf(plain);
    const std::string permutedLabel = complexLabelOf(permuted);
    const std::string otherLabel = complexLabelOf(otherCompartment);

    // The label is a canonical form: node labelling and traversal order do
    // not change it.
    CHECK(plainLabel == permutedLabel);
    // The compartment is part of the label, so the NFsim encoding decides the
    // structure and compartment layers.
    CHECK(plainLabel != otherLabel);
}
