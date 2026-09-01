#include <map>
#include <string>
#include <vector>

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include "NFcore.hh"
#include "NFreactions/reactantLists/reactantTree.hh"
#include "NFreactions/transformations/transformationSet.hh"

TEST_CASE("NFsim System rejects unsafe output names") {
    // Source-derived from NFsim commit 3527edb and its System constructor
    // regression test.  System names become output-file prefixes, so all
    // constructor overloads must reject path-like input.
    const std::vector<std::string> invalidNames {
        "../escape", "/absolute", "C:\\escape", "C:escape",
        "nested/name", "nested\\name", "contains..dots"
    };

    for (const auto& name : invalidNames) {
        for (int constructor = 0; constructor < 3; ++constructor) {
            const auto construct = [&name, constructor]() {
                if (constructor == 0) {
                    NFcore::System system(name);
                } else if (constructor == 1) {
                    NFcore::System system(name, true);
                } else {
                    NFcore::System system(name, true, 100);
                }
            };
            CHECK_THROWS_WITH(construct(),
                              "Path traversal detected in System name.");
        }
    }
}

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

TEST_CASE("NFsim ReactantTree preserves weights across repeated expansion") {
    /* Source-derived from ReactantTree::expandTree: active MappingSets are
     * reinserted by stable id when the complete tree grows, then cleared
     * slots are reused without losing weighted selection state. */
    NFcore::System system("ReactantTree expansion contract");
    std::vector<std::string> componentNames {"site"};
    auto* moleculeType = new NFcore::MoleculeType(
        "ExpansionTree", componentNames, &system);
    auto* templateMolecule = new NFcore::TemplateMolecule(moleculeType);
    std::vector<NFcore::TemplateMolecule*> templates {templateMolecule};
    NFcore::TransformationSet transformations(templates);
    transformations.finalize();

    NFcore::ReactantTree tree(0, &transformations, 1);
    const std::vector<double> rates {2.0, 5.0, 7.0, 11.0, 13.0};
    std::map<unsigned int, double> expected;

    for (const double rate : rates) {
        auto* mapping = tree.pushNextAvailableMappingSet();
        REQUIRE(mapping != nullptr);
        expected.emplace(mapping->getId(), rate);
        tree.confirmPush(mapping->getId(), rate);
    }

    CHECK(tree.getDepthOfTree() == 3);
    CHECK(tree.size() == static_cast<int>(rates.size()));
    CHECK(tree.getRateFactorSum() == 38.0);
    for (int index = 0; index < tree.size(); ++index) {
        auto* mapping = tree.getMappingSetByIndex(static_cast<unsigned int>(index));
        REQUIRE(mapping != nullptr);
        CHECK(tree.getRateFactor(index) == expected.at(mapping->getId()));
    }

    tree.removeMappingSet(1);
    expected.erase(1);
    CHECK(tree.size() == 4);
    CHECK(tree.getRateFactorSum() == 33.0);
    for (int index = 0; index < tree.size(); ++index) {
        auto* mapping = tree.getMappingSetByIndex(static_cast<unsigned int>(index));
        REQUIRE(mapping != nullptr);
        CHECK(tree.getRateFactor(index) == expected.at(mapping->getId()));
    }

    auto* recycled = tree.pushNextAvailableMappingSet();
    REQUIRE(recycled != nullptr);
    const unsigned int recycledId = recycled->getId();
    tree.confirmPush(recycledId, 17.0);
    expected[recycledId] = 17.0;
    CHECK(tree.size() == 5);
    CHECK(tree.getRateFactorSum() == 50.0);
    for (int index = 0; index < tree.size(); ++index) {
        auto* mapping = tree.getMappingSetByIndex(static_cast<unsigned int>(index));
        REQUIRE(mapping != nullptr);
        CHECK(tree.getRateFactor(index) == expected.at(mapping->getId()));
    }
}

TEST_CASE("NFsim CompactPartnerPool preserves source swap-removal indexing") {
    NFcore::System system("CompactPartnerPool contract");
    std::vector<std::string> componentNames {"site"};
    auto* moleculeType = new NFcore::MoleculeType(
        "PoolMolecule", componentNames, &system);
    auto* first = moleculeType->genDefaultMolecule();
    auto* second = moleculeType->genDefaultMolecule();
    auto* third = moleculeType->genDefaultMolecule();

    NFcore::CompactPartnerPool pool;
    const auto firstId = static_cast<unsigned int>(first->getMolListId());
    const auto secondId = static_cast<unsigned int>(second->getMolListId());
    const auto thirdId = static_cast<unsigned int>(third->getMolListId());

    CHECK(pool.size() == 0);
    CHECK(pool.add(first, firstId));
    CHECK(pool.add(second, secondId));
    CHECK(pool.add(third, thirdId));
    CHECK_FALSE(pool.add(first, firstId));

    CHECK(pool.remove(first, firstId));
    CHECK_FALSE(pool.contains(first, firstId));
    CHECK(pool.contains(second, secondId));
    CHECK(pool.contains(third, thirdId));
    CHECK(pool.getByIndex(0) == third);
    CHECK(pool.size() == 2);
}

TEST_CASE("NFsim MoleculeType retains pooled molecules across bulk removal") {
    /* Source-derived from MoleculeList ownership: removeAllMolecules removes
     * live entries from the fixed-capacity list, while MoleculeList remains
     * responsible for deleting every preallocated object at destruction. */
    NFcore::System system("MoleculeType bulk removal contract");
    std::vector<std::string> componentNames {"site"};
    auto* moleculeType = new NFcore::MoleculeType(
        "BulkRemoval", componentNames, &system);

    auto* first = moleculeType->genDefaultMolecule();
    auto* second = moleculeType->genDefaultMolecule();
    REQUIRE(first != nullptr);
    REQUIRE(second != nullptr);
    CHECK(moleculeType->getMoleculeCount() == 2);

    moleculeType->removeAllMolecules();
    CHECK(moleculeType->getMoleculeCount() == 0);

    auto* recycled = moleculeType->genDefaultMolecule();
    REQUIRE(recycled != nullptr);
    CHECK(moleculeType->getMoleculeCount() == 1);
    CHECK(recycled == first);
}

TEST_CASE("NFsim MoleculeType exposes one compact pool per component") {
    NFcore::System system("MoleculeType compact pool contract");
    std::vector<std::string> componentNames {"left", "right"};
    auto* moleculeType = new NFcore::MoleculeType(
        "PoolOwner", componentNames, &system);

    auto* left = moleculeType->getOrCreateCompactPartnerPool(0);
    auto* leftAgain = moleculeType->getOrCreateCompactPartnerPool(0);
    auto* right = moleculeType->getOrCreateCompactPartnerPool(1);

    REQUIRE(left != nullptr);
    CHECK(leftAgain == left);
    REQUIRE(right != nullptr);
    CHECK(right != left);
    CHECK(moleculeType->getOrCreateCompactPartnerPool(-1) == nullptr);
    CHECK(moleculeType->getOrCreateCompactPartnerPool(2) == nullptr);
}
