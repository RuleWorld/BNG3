#include <map>
#include <sstream>
#include <string>
#include <vector>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include "NFcore.hh"
#include "NFinput/NFinput_fromAst.hh"
#include "NFreactions/reactantLists/reactantTree.hh"
#include "NFreactions/transformations/transformationSet.hh"
#include "parser/BNGAstVisitor.hpp"

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

TEST_CASE("NFsim stepTo preserves continuous simulation checkpoints") {
    // Source-derived from NFsim commit e3ef4a0 and
    // validate/basicModels/step_to_cache.xml.  A pending event that falls
    // after an output boundary must be retained, so chunked stepTo calls and
    // one continuous sim consume the same event stream.
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
    k 10
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
end seed species
begin observables
    Molecules B_total B()
end observables
begin reaction rules
    A() -> A() + B() k
end reaction rules
)BNG");
    REQUIRE(model != nullptr);

    int continuousTraversalLimit = 0;
    auto* continuous = NFinput::buildSystemFromAst(
        *model, false, 20000, false, continuousTraversalLimit);
    REQUIRE(continuous != nullptr);
    continuous->seedRNG(1);
    continuous->prepareForSimulation();
    continuous->getOutputFileStream().setUseFile(false);
    continuous->sim(10.0, 10, false);

    std::vector<double> continuousTimes;
    std::vector<double> continuousCounts;
    std::istringstream continuousOutput(continuous->getOutputFileStream().str());
    std::string outputLine;
    while (std::getline(continuousOutput, outputLine)) {
        if (outputLine.empty() || outputLine.front() == '#') continue;
        std::istringstream row(outputLine);
        double time = 0.0;
        double count = 0.0;
        if (row >> time >> count) {
            continuousTimes.push_back(time);
            continuousCounts.push_back(count);
        }
    }
    REQUIRE(continuousTimes.size() == 11);
    REQUIRE(continuousCounts.size() == 11);

    int chunkedTraversalLimit = 0;
    auto* chunked = NFinput::buildSystemFromAst(
        *model, false, 20000, false, chunkedTraversalLimit);
    REQUIRE(chunked != nullptr);
    chunked->seedRNG(1);
    chunked->prepareForSimulation();
    std::vector<int> chunkedCounts;
    for (int checkpoint = 1; checkpoint <= 10; ++checkpoint) {
        CHECK(chunked->stepTo(static_cast<double>(checkpoint)) ==
              Catch::Approx(static_cast<double>(checkpoint)));
        chunkedCounts.push_back(
            chunked->getObservableByName("B_total")->getCount());
    }

    CHECK(chunked->getCurrentTime() == Catch::Approx(10.0));
    REQUIRE(chunkedCounts.size() == 10);
    for (std::size_t index = 0; index < chunkedCounts.size(); ++index) {
        CHECK(continuousTimes[index + 1] ==
              Catch::Approx(static_cast<double>(index + 1)));
        CHECK(chunkedCounts[index] ==
              static_cast<int>(continuousCounts[index + 1]));
    }

    delete chunked;
    delete continuous;
}

TEST_CASE("NFsim stepTo advances zero-propensity checkpoints") {
    // Source-derived from NFsim commit e3ef4a0 and
    // validate/basicModels/step_to_zero_propensity.xml.  A system with no
    // available reactants must still advance each requested output boundary.
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
    k 1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 0
    B() 1
end seed species
begin observables
    Molecules B_total B()
end observables
begin reaction rules
    A() -> A() + B() k
end reaction rules
)BNG");
    REQUIRE(model != nullptr);

    int continuousTraversalLimit = 0;
    auto* continuous = NFinput::buildSystemFromAst(
        *model, false, 100, false, continuousTraversalLimit);
    REQUIRE(continuous != nullptr);
    continuous->prepareForSimulation();
    continuous->getOutputFileStream().setUseFile(false);
    continuous->sim(2.0, 2, false);

    int chunkedTraversalLimit = 0;
    auto* chunked = NFinput::buildSystemFromAst(
        *model, false, 100, false, chunkedTraversalLimit);
    REQUIRE(chunked != nullptr);
    chunked->prepareForSimulation();
    CHECK(chunked->stepTo(1.0) == Catch::Approx(1.0));
    CHECK(chunked->stepTo(2.0) == Catch::Approx(2.0));
    CHECK(chunked->getObservableByName("B_total")->getCount() == 1);

    std::vector<double> continuousTimes;
    std::vector<double> continuousCounts;
    std::istringstream continuousOutput(continuous->getOutputFileStream().str());
    std::string outputLine;
    while (std::getline(continuousOutput, outputLine)) {
        if (outputLine.empty() || outputLine.front() == '#') continue;
        std::istringstream row(outputLine);
        double time = 0.0;
        double count = 0.0;
        if (row >> time >> count) {
            continuousTimes.push_back(time);
            continuousCounts.push_back(count);
        }
    }
    REQUIRE(continuousTimes.size() == 3);
    REQUIRE(continuousCounts.size() == 3);
    CHECK(continuousTimes[1] == Catch::Approx(1.0));
    CHECK(continuousTimes[2] == Catch::Approx(2.0));
    CHECK(continuousCounts[0] == 1.0);
    CHECK(continuousCounts[1] == 1.0);
    CHECK(continuousCounts[2] == 1.0);

    delete chunked;
    delete continuous;
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
