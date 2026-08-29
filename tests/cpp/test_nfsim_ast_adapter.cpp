#include <map>

#include <catch2/catch_test_macros.hpp>

#include "NFinput_fromAst.hh"
#include "NFcore.hh"
#include "compartment.hh"
#include "ast/Model.hpp"
#include "ast/MoleculeType.hpp"

TEST_CASE("NFsim AST adapter preserves molecule-type state and symmetry metadata") {
    bng::ast::Model model;
    model.addMoleculeType(bng::ast::MoleculeType(
        "A", {{"site", {"u", "p"}}, {"site", {"0", "2"}}}));

    NFcore::System system("adapter", false, 100);
    std::map<std::string, int> allowedStates;
    REQUIRE(NFinput::addMoleculeTypesFromAst(model, &system, allowedStates, false));
    REQUIRE(system.getNumOfMoleculeTypes() == 1);

    auto* moleculeType = system.getMoleculeType(0);
    REQUIRE(moleculeType->getNumOfComponents() == 2);
    CHECK(moleculeType->getComponentName(0) == "site1");
    CHECK(moleculeType->getComponentName(1) == "site2");
    CHECK(moleculeType->getNumOfEquivalencyClasses() == 1);
    const auto possibleStates = moleculeType->getPossibleCompStates();
    CHECK(possibleStates.at(1).size() == 3);
    CHECK(moleculeType->isIntegerComponent(1));
    CHECK(allowedStates.at("A_site1_u") == 0);
    CHECK(allowedStates.at("A_site1_p") == 1);
    CHECK(allowedStates.at("A_site2_0") == 0);
    CHECK(allowedStates.at("A_site2_1") == 1);
    CHECK(allowedStates.at("A_site2_2") == 2);
}

TEST_CASE("NFsim AST adapter installs compartment parents in a second pass") {
    bng::ast::Model model;
    model.addCompartment(bng::ast::Compartment("membrane", 1.0, 2, "cytosol"));
    model.addCompartment(bng::ast::Compartment("cytosol", 10.0, 3));

    NFcore::System system("adapter", false, 100);
    REQUIRE(NFinput::addCompartmentsFromAst(model, &system, false));
    REQUIRE(system.getNumCompartments() == 2);
    REQUIRE(system.getCompartment("membrane") != nullptr);
    REQUIRE(system.getCompartment("cytosol") != nullptr);
    CHECK(system.getCompartment("membrane")->getParent()->getId() == "cytosol");
    CHECK(system.getDefaultCompartment() == nullptr);
}

TEST_CASE("NFsim AST adapter rejects population molecule types with components") {
    bng::ast::Model model;
    model.addMoleculeType(
        bng::ast::MoleculeType("population", {{"site", {}}}, true));

    NFcore::System system("adapter", false, 100);
    std::map<std::string, int> allowedStates;
    CHECK_FALSE(NFinput::addMoleculeTypesFromAst(model, &system, allowedStates, false));
}
