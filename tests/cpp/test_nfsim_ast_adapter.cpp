#include <map>
#include <string>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "NFinput_fromAst.hh"
#include "NFcore.hh"
#include "compartment.hh"
#include "NFfunction/NFfunction.hh"
#include "ast/Function.hpp"
#include "ast/Model.hpp"
#include "ast/MoleculeType.hpp"
#include "ast/Observable.hpp"
#include "ast/Parameter.hpp"
#include "io/XmlWriter.hpp"

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

TEST_CASE("NFsim AST adapter applies the concentration conversion option") {
    bng::ast::Model model;
    model.setOption("NumberPerQuantityUnit", "6.022e23");

    NFcore::System system("adapter", false, 100);
    REQUIRE(NFinput::addOptionsFromAst(model, &system, false));
    CHECK(system.getNumberPerQuantityUnit() == Catch::Approx(6.022e23));
    CHECK(bng::io::XmlWriter::write(model).find(
              "NumberPerQuantityUnit=\"6.022e23\"") != std::string::npos);
}

TEST_CASE("NFsim AST adapter rejects malformed concentration conversion options") {
    bng::ast::Model model;
    model.setOption("NumberPerQuantityUnit", "not-a-number");

    NFcore::System system("adapter", false, 100);
    CHECK_FALSE(NFinput::addOptionsFromAst(model, &system, false));
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

TEST_CASE("NFsim AST adapter maps parameter-backed global functions") {
    bng::ast::Model model;
    model.addParameter(bng::ast::Parameter("k", bng::ast::Expression::number(3.0)));
    model.addFunction(bng::ast::Function(
        "rate", {},
        bng::ast::Expression::binary(
            "+", bng::ast::Expression::binary(
                     "*", bng::ast::Expression::identifier("k"),
                     bng::ast::Expression::number(2.0)),
            bng::ast::Expression::number(1.0))));

    NFcore::System system("adapter", false, 100);
    std::map<std::string, double> parameters;
    REQUIRE(NFinput::addParametersFromAst(model, &system, parameters, false));
    REQUIRE(NFinput::addFunctionsFromAst(model, &system, parameters, false));

    auto* function = system.getGlobalFunctionByName("rate");
    REQUIRE(function != nullptr);
    CHECK(function->getNumOfVarRefs() == 0);
    function->prepareForSimulation(&system);
    CHECK(NFcore::FuncFactory::Eval(function->p) == Catch::Approx(7.0));
}

TEST_CASE("NFsim AST adapter maps observable-backed global functions") {
    bng::ast::Model model;
    model.addObservable(bng::ast::Observable("A_total", "Molecules", {"A()"}));
    model.addFunction(bng::ast::Function(
        "scaled", {},
        bng::ast::Expression::binary(
            "*", bng::ast::Expression::observableRef("A_total", {}),
            bng::ast::Expression::number(2.0))));

    NFcore::System system("adapter", false, 100);
    std::map<std::string, double> parameters;
    REQUIRE(NFinput::addFunctionsFromAst(model, &system, parameters, false));
    auto* function = system.getGlobalFunctionByName("scaled");
    REQUIRE(function != nullptr);
    REQUIRE(function->getNumOfVarRefs() == 1);
    CHECK(function->getVarRefName(0) == "A_total");
    CHECK(function->getVarRefType(0) == "Observable");
}

TEST_CASE("NFsim AST adapter rejects incomplete global-function references") {
    bng::ast::Model model;
    model.addFunction(bng::ast::Function(
        "bad", {}, bng::ast::Expression::observableRef("missing", {})));

    NFcore::System system("adapter", false, 100);
    std::map<std::string, double> parameters;
    CHECK_FALSE(NFinput::addFunctionsFromAst(model, &system, parameters, false));
    CHECK(system.getGlobalFunctionByName("bad") == nullptr);
}

TEST_CASE("NFsim AST adapter keeps local functions on the compatibility path") {
    bng::ast::Model model;
    model.addFunction(bng::ast::Function(
        "local", {"x"}, bng::ast::Expression::identifier("x")));

    NFcore::System system("adapter", false, 100);
    std::map<std::string, double> parameters;
    CHECK_FALSE(NFinput::addFunctionsFromAst(model, &system, parameters, false));
    CHECK(system.getGlobalFunctionByName("local") == nullptr);
}
