#include <string>
#include <vector>

#include <catch2/catch_test_macros.hpp>

#include "NFcore.hh"
#include "NFreactions/reactantLists/reactantTree.hh"
#include "NFreactions/transformations/transformationSet.hh"

TEST_CASE("NFsim ReactantTree preserves the compact one-leaf contract") {
    NFcore::System system("ReactantTree contract");
    std::vector<std::string> componentNames {"site"};
    auto* moleculeType = new NFcore::MoleculeType(
        "TreeTest", componentNames, &system);
    auto* templateMolecule = new NFcore::TemplateMolecule(moleculeType);
    std::vector<NFcore::TemplateMolecule*> templates {templateMolecule};
    NFcore::TransformationSet transformations(templates);
    transformations.finalize();

    NFcore::ReactantTree tree(0, &transformations, 1);
    CHECK(tree.getDepthOfTree() == 0);

    auto* first = tree.pushNextAvailableMappingSet();
    REQUIRE(first != nullptr);
    const unsigned int firstId = first->getId();
    tree.confirmPush(firstId, 2.0);
    CHECK(tree.size() == 1);
    CHECK(tree.getRateFactorSum() == 2.0);
    CHECK(tree.getRateFactor(0) == 2.0);

    NFcore::MappingSet* picked = nullptr;
    tree.pickReactantFromValue(picked, 1.0, 1.0);
    CHECK(picked == first);

    CHECK(tree.updateValue(firstId, 3.0));
    CHECK_FALSE(tree.updateValue(firstId, 3.0));
    tree.pickReactantFromValue(picked, 2.0, 1.0);
    CHECK(tree.getRateFactorSum() == 3.0);
    CHECK(tree.getRateFactor(0) == 3.0);
    CHECK(picked == first);

    auto* second = tree.pushNextAvailableMappingSet();
    REQUIRE(second != nullptr);
    const unsigned int secondId = second->getId();
    tree.confirmPush(secondId, 5.0);
    tree.pickReactantFromValue(picked, 4.0, 1.0);
    CHECK(tree.size() == 2);
    CHECK(tree.getRateFactorSum() == 8.0);
    CHECK(picked == second);

    tree.removeMappingSet(secondId);
    tree.pickReactantFromValue(picked, 2.0, 1.0);
    CHECK(tree.size() == 1);
    CHECK(tree.getRateFactorSum() == 3.0);
    CHECK(tree.getRateFactor(0) == 3.0);
    CHECK(picked == first);

    tree.removeMappingSet(firstId);
    CHECK(tree.size() == 0);
    CHECK(tree.getRateFactorSum() == 0.0);
}
