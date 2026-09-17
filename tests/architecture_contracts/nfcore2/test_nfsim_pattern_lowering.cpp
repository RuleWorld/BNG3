#include "test_harness.hh"
#include "nfsim_pattern_lowering.hh"

#include "NFcore.hh"
#include "compartment.hh"
#include "templateMolecule.hh"

#include <memory>

namespace {

std::unique_ptr<NFcore::System> patternSystem() {
    auto system = std::make_unique<NFcore::System>("pattern", false, 100);

    std::vector<std::string> aComponents{"s", "b"};
    std::vector<std::string> aDefaults{"U", "NO_STATE"};
    std::vector<std::vector<std::string>> aStates{{"U", "P"}, {}};
    std::vector<bool> aInteger{false, false};
    new NFcore::MoleculeType("A", aComponents, aDefaults, aStates,
                             aInteger, false, system.get());

    std::vector<std::string> bComponents{"a"};
    std::vector<std::string> bDefaults{"NO_STATE"};
    std::vector<std::vector<std::string>> bStates{{}};
    std::vector<bool> bInteger{false};
    new NFcore::MoleculeType("B", bComponents, bDefaults, bStates,
                             bInteger, false, system.get());

    std::vector<std::string> cComponents{"a"};
    std::vector<std::string> cDefaults{"NO_STATE"};
    std::vector<std::vector<std::string>> cStates{{}};
    std::vector<bool> cInteger{false};
    new NFcore::MoleculeType("C", cComponents, cDefaults, cStates,
                             cInteger, false, system.get());

    system->addCompartment(new NFcore::Compartment("cell", 3, 1.0));
    return system;
}

}

TEST(NFsimPatternLowering_MapsStatesBondsAndCompartments) {
    auto system = patternSystem();
    const auto pattern = bng::compile::Pattern::parse(
        "A(s~U,b!1)@cell.B(a!1)@cell");
    std::vector<NFcore::TemplateMolecule*> templates;
    bool hasDisjointSets = false;
    int traversalLimit = 0;
    std::string diagnostic;

    EXPECT_TRUE(NFcore2::lowerPatternToNFsim(
        pattern, *system, templates, hasDisjointSets, traversalLimit, diagnostic));
    EXPECT_TRUE(diagnostic.empty());
    EXPECT_EQ(templates.size(), 2u);
    EXPECT_FALSE(hasDisjointSets);
    EXPECT_EQ(traversalLimit, 3);
    EXPECT_EQ(templates[0]->getCompartmentId(), std::string("cell"));

    NFcore::TemplateMolecule::RootLocalConstraints constraints;
    EXPECT_TRUE(templates[0]->collectRootLocalConstraints(constraints));
    EXPECT_EQ(constraints.states.size(), 1u);
    EXPECT_EQ(constraints.states[0].first, 0);
    EXPECT_EQ(constraints.states[0].second, 0);
    EXPECT_EQ(constraints.bonds.size(), 1u);
    EXPECT_EQ(constraints.bonds[0].component, 1);
    EXPECT_EQ(constraints.bonds[0].partner, templates[1]);
    EXPECT_EQ(constraints.bonds[0].partner_component, 0);
}

TEST(NFsimPatternLowering_PreservesDotSeparatedPatternConnectivity) {
    auto system = patternSystem();
    const auto pattern = bng::compile::Pattern::parse("A(b).B(a)");
    std::vector<NFcore::TemplateMolecule*> templates;
    bool hasDisjointSets = false;
    int traversalLimit = 0;
    std::string diagnostic;

    EXPECT_TRUE(NFcore2::lowerPatternToNFsim(
        pattern, *system, templates, hasDisjointSets, traversalLimit, diagnostic));
    EXPECT_TRUE(hasDisjointSets);
    EXPECT_EQ(templates.size(), 2u);
    EXPECT_EQ(templates[0]->getN_connectedTo(), 1);
    EXPECT_EQ(templates[1]->getN_connectedTo(), 1);
    NFcore::TemplateMolecule::RootLocalConstraints constraints;
    EXPECT_TRUE(templates[0]->collectRootLocalConstraints(constraints));
    EXPECT_EQ(constraints.empty.size(), 1u);
    EXPECT_EQ(constraints.connected_to.size(), 1u);
    EXPECT_EQ(constraints.connected_to[0], templates[1]);
}

TEST(NFsimPatternLowering_RejectsUnknownSemanticReferences) {
    auto system = patternSystem();
    std::vector<NFcore::TemplateMolecule*> templates;
    bool hasDisjointSets = false;
    int traversalLimit = 0;
    std::string diagnostic;

    EXPECT_FALSE(NFcore2::lowerPatternToNFsim(
        bng::compile::Pattern::parse("A(s~missing)"), *system,
        templates, hasDisjointSets, traversalLimit, diagnostic));
    EXPECT_TRUE(!diagnostic.empty());
    EXPECT_FALSE(NFcore2::lowerPatternToNFsim(
        bng::compile::Pattern::parse("A(s!9)"), *system,
        templates, hasDisjointSets, traversalLimit, diagnostic));
    EXPECT_TRUE(!diagnostic.empty());
    EXPECT_FALSE(NFcore2::lowerPatternToNFsim(
        bng::compile::Pattern::parse("Missing()"), *system,
        templates, hasDisjointSets, traversalLimit, diagnostic));
    EXPECT_TRUE(!diagnostic.empty());
}

TEST(NFsimPatternLowering_RejectsMultipleBondsOnOneSite) {
    auto system = patternSystem();
    const auto pattern = bng::compile::Pattern::parse(
        "A(b!1!2).B(a!1).C(a!2)");
    std::vector<NFcore::TemplateMolecule*> templates;
    bool hasDisjointSets = false;
    int traversalLimit = 0;
    std::string diagnostic;

    EXPECT_FALSE(NFcore2::lowerPatternToNFsim(
        pattern, *system, templates, hasDisjointSets, traversalLimit, diagnostic));
    EXPECT_TRUE(!diagnostic.empty());
}

TEST(NFsimPatternLowering_AllowsMultipleBondsOnEquivalentSiteOrbit) {
    auto system = patternSystem();
    std::vector<std::string> components{"x1", "x"};
    std::vector<std::string> defaults{"NO_STATE", "NO_STATE"};
    std::vector<std::vector<std::string>> states{{}, {}};
    std::vector<bool> integerStates{false, false};
    new NFcore::MoleculeType("X", components, defaults, states,
                             integerStates, false, system.get());
    std::vector<std::vector<std::string>> equivalentComponents{{"x1", "x"}};
    system->getMoleculeTypeByName("X")->addEquivalentComponents(equivalentComponents);
    const auto equivalent = bng::compile::Pattern::parse(
        "X(x!1!2).B(a!1).C(a!2)");
    std::vector<NFcore::TemplateMolecule*> templates;
    bool hasDisjointSets = false;
    int traversalLimit = 0;
    std::string diagnostic;

    const bool lowered = NFcore2::lowerPatternToNFsim(
        equivalent, *system, templates, hasDisjointSets, traversalLimit,
        diagnostic);
    EXPECT_TRUE(lowered);
    EXPECT_TRUE(diagnostic.empty());
    EXPECT_EQ(templates.size(), 3u);
    NFcore::TemplateMolecule::RootLocalConstraints constraints;
    EXPECT_TRUE(templates[0]->collectRootLocalConstraints(constraints));
    EXPECT_EQ(constraints.symmetric.size(), 2u);
}
