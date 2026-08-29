#include <cmath>
#include <map>
#include <string>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "NFinput_fromAst.hh"
#include "NFcore.hh"
#include "NFcore/energyPattern.hh"
#include "compartment.hh"
#include "NFfunction/NFfunction.hh"
#include "ast/Function.hpp"
#include "ast/Model.hpp"
#include "ast/MoleculeType.hpp"
#include "ast/Observable.hpp"
#include "ast/Parameter.hpp"
#include "ast/SeedSpecies.hpp"
#include "PatternGraphBuilder.hpp"
#include "BNGLexer.h"
#include "BNGParser.h"
#include <antlr4-runtime.h>
#include "io/XmlWriter.hpp"
#include "parser/BNGAstVisitor.hpp"

namespace {

BNGcore::PatternGraph parseSpeciesGraph(const std::string& text, bng::ast::Model& model) {
    antlr4::ANTLRInputStream input(text);
    BNGLexer lexer(&input);
    antlr4::CommonTokenStream tokens(&lexer);
    BNGParser parser(&tokens);
    auto* species = parser.species_def();
    REQUIRE(parser.getNumberOfSyntaxErrors() == 0);
    return bng::parser::buildPatternGraph(species, model, false);
}

} // namespace

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

TEST_CASE("NFsim AST adapter builds a direct no-rule system") {
    bng::ast::Model model;
    model.setModelName("direct");
    model.addMoleculeType(bng::ast::MoleculeType("A", {{"conf", {"R", "T"}}}));
    model.addSeedSpecies(bng::ast::SeedSpecies(
        "A(conf~R)", bng::ast::Expression::number(2.0), false, {},
        parseSpeciesGraph("A(conf~R)", model)));
    model.addObservable(bng::ast::Observable("A_R", "Molecules", {"A(conf~R)"}));
    model.addObservable(bng::ast::Observable("A_total", "Molecules", {"A()"}));

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getNumOfMolecules() == 2);
    REQUIRE(system->getObservableByName("A_R") != nullptr);
    REQUIRE(system->getObservableByName("A_total") != nullptr);
    system->prepareForSimulation();
    CHECK(system->getObservableByName("A_R")->getCount() == 2);
    CHECK(system->getObservableByName("A_total")->getCount() == 2);
    CHECK(suggestedTraversalLimit >= 2);
    delete system;
}

TEST_CASE("NFsim AST adapter counts a connected observable pattern once") {
    bng::ast::Model model;
    model.setModelName("connected-observable");
    model.addMoleculeType(bng::ast::MoleculeType("A", {{"x", {}}}));
    model.addMoleculeType(bng::ast::MoleculeType("B", {{"y", {}}}));
    model.addSeedSpecies(bng::ast::SeedSpecies(
        "A(x!1).B(y!1)", bng::ast::Expression::number(1.0), false, {},
        parseSpeciesGraph("A(x!1).B(y!1)", model)));
    model.addObservable(
        bng::ast::Observable("AB", "Molecules", {"A(x!1).B(y!1)"}));

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getNumOfMolecules() == 2);
    system->prepareForSimulation();
    CHECK(system->getObservableByName("AB")->getCount() == 1);
    CHECK(suggestedTraversalLimit >= 2);
    delete system;
}

TEST_CASE("NFsim AST adapter maps bare molecule stoichiometric observables") {
    auto model = bng::parser::parseModel(R"(
begin molecule types
    R(site)
end molecule types
begin seed species
    R(site!1).R(site!1) 1
end seed species
begin observables
    Species R2 R==2
    Species R3 R>=3
end observables
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    system->prepareForSimulation();
    CHECK(system->getObservableByName("R2")->getCount() == 1);
    CHECK(system->getObservableByName("R3")->getCount() == 0);
    delete system;
}

TEST_CASE("NFsim AST adapter maps direct state-change reaction rules") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(conf~R~T)
end molecule types
begin seed species
    A(conf~R) 20
end seed species
begin observables
    Molecules A_R A(conf~R)
    Molecules A_T A(conf~T)
end observables
begin reaction rules
    A(conf~R) -> A(conf~T) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getBaseRate() == Catch::Approx(1.0));
    system->prepareForSimulation();
    REQUIRE(system->getObservableByName("A_R") != nullptr);
    REQUIRE(system->getObservableByName("A_T") != nullptr);
    CHECK(system->getObservableByName("A_R")->getCount() == 20);
    CHECK(system->getObservableByName("A_T")->getCount() == 0);

    system->seedRNG(1);
    system->stepTo(100.0);
    CHECK(system->getObservableByName("A_R")->getCount() == 0);
    CHECK(system->getObservableByName("A_T")->getCount() == 20);
    delete system;
}

TEST_CASE("NFsim AST adapter maps direct compartment transport") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin compartments
    c1 3 1.0
    c2 3 1.0
end compartments
begin molecule types
    A(site)
end molecule types
begin seed species
    @c1:A(site) 1
end seed species
begin observables
    Molecules in_c1 @c1:A(site)
    Molecules in_c2 @c2:A(site)
end observables
begin reaction rules
    @c1:A(site) -> @c2:A(site) k
    end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    CHECK(system->getObservableByName("in_c1")->getCount() == 1);
    CHECK(system->getObservableByName("in_c2")->getCount() == 0);
    system->seedRNG(5);
    system->stepTo(100.0);
    CHECK(system->getObservableByName("in_c1")->getCount() == 0);
    CHECK(system->getObservableByName("in_c2")->getCount() == 1);
    delete system;
}

TEST_CASE("NFsim AST adapter maps direct binding reaction rules") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 1
    B(a) 1
end seed species
begin observables
    Species AB A(b!1).B(a!1)
end observables
begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    CHECK(system->getObservableByName("AB")->getCount() == 0);
    system->seedRNG(2);
    system->stepTo(100.0);
    CHECK(system->getObservableByName("AB")->getCount() == 1);
    delete system;
}

TEST_CASE("NFsim AST adapter maps a product molecule bound to a reactant") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 1
end seed species
begin observables
    Species AB A(b!1).B(a!1)
end observables
begin reaction rules
    A(b) -> A(b!1).B(a!1) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    CHECK(system->getObservableByName("AB")->getCount() == 0);
    system->seedRNG(4);
    system->stepTo(100.0);
    CHECK(system->getObservableByName("AB")->getCount() == 1);
    CHECK(system->getNumOfMolecules() == 2);
    delete system;
}

TEST_CASE("NFsim AST adapter maps direct unbinding reaction rules") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b!1).B(a!1) 1
end seed species
begin observables
    Species AB A(b!1).B(a!1)
    Species FreeA A(b)
    Species FreeB B(a)
end observables
begin reaction rules
    A(b!1).B(a!1) -> A(b) + B(a) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    CHECK(system->getObservableByName("AB")->getCount() == 1);
    system->seedRNG(3);
    system->stepTo(100.0);
    CHECK(system->getObservableByName("AB")->getCount() == 0);
    CHECK(system->getObservableByName("FreeA")->getCount() == 1);
    CHECK(system->getObservableByName("FreeB")->getCount() == 1);
    delete system;
}

TEST_CASE("NFsim AST adapter creates direct standalone product molecules") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    Source()
    Product(site~U~P)
end molecule types
begin seed species
    Source() 1
end seed species
begin observables
    Molecules source_total Source()
    Molecules product_P Product(site~P)
end observables
begin reaction rules
    Source() -> Source() + Product(site~P) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    REQUIRE(system->getObservableByName("source_total") != nullptr);
    REQUIRE(system->getObservableByName("product_P") != nullptr);
    CHECK(system->getObservableByName("source_total")->getCount() == 1);
    CHECK(system->getObservableByName("product_P")->getCount() == 0);

    system->seedRNG(4);
    system->stepTo(100.0);
    CHECK(system->getObservableByName("source_total")->getCount() == 1);
    CHECK(system->getObservableByName("product_P")->getCount() > 0);
    delete system;
}

TEST_CASE("NFsim AST adapter binds direct product molecules to each other") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    Source()
    B(site)
    C(site)
end molecule types
begin seed species
    Source() 1
end seed species
begin observables
    Species BC B(site!1).C(site!1)
end observables
begin reaction rules
    Source() -> B(site!1).C(site!1) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    CHECK(system->getObservableByName("BC")->getCount() == 0);
    system->seedRNG(6);
    system->stepTo(100.0);
    CHECK(system->getObservableByName("BC")->getCount() == 1);
    delete system;
}

TEST_CASE("NFsim AST adapter expands direct reversible reaction rules") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k_forward 1.0
    k_reverse 1.0
end parameters
begin molecule types
    A(conf~R~T)
end molecule types
begin seed species
    A(conf~T) 1
end seed species
begin observables
    Molecules A_R A(conf~R)
    Molecules A_T A(conf~T)
end observables
begin reaction rules
    A(conf~R) <-> A(conf~T) k_forward, k_reverse
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 2);
    CHECK(system->getReaction(0)->getBaseRate() == Catch::Approx(1.0));
    CHECK(system->getReaction(1)->getBaseRate() == Catch::Approx(1.0));
    system->prepareForSimulation();
    CHECK(system->getObservableByName("A_R")->getCount() == 0);
    CHECK(system->getObservableByName("A_T")->getCount() == 1);
    system->singleStep();
    CHECK(system->getObservableByName("A_R")->getCount() == 1);
    CHECK(system->getObservableByName("A_T")->getCount() == 0);
    delete system;
}

TEST_CASE("NFsim AST adapter maps static Michaelis-Menten rate constants") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    kcat 1.0
    Km 1.0
end parameters
begin molecule types
    S()
    E()
    P()
end molecule types
begin seed species
    S() 100
    E() 100
end seed species
begin observables
    Molecules S_total S()
    Molecules P_total P()
end observables
begin reaction rules
    S() + E() -> P() + E() MM(kcat,Km)
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    REQUIRE(system->getReaction(0)->get_a() > 0.0);
    CHECK(system->getObservableByName("S_total")->getCount() == 100);
    CHECK(system->getObservableByName("P_total")->getCount() == 0);
    system->singleStep();
    CHECK(system->getObservableByName("S_total")->getCount() == 99);
    CHECK(system->getObservableByName("P_total")->getCount() == 1);
    delete system;
}

TEST_CASE("NFsim AST adapter maps zero-order product synthesis") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin molecule types
    Product(site~U~P)
end molecule types
begin observables
    Molecules product_P Product(site~P)
end observables
begin reaction rules
    0 -> Product(site~P) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(2.0));
    CHECK(system->getObservableByName("product_P")->getCount() == 0);
    system->singleStep();
    CHECK(system->getObservableByName("product_P")->getCount() == 1);
    delete system;
}

TEST_CASE("NFsim AST adapter maps zero-argument functional reaction rates") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules A_total A()
    Molecules B_total B()
end observables
begin functions
    rate k
end functions
begin reaction rules
    A() -> B() rate
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getRxnType() == NFcore::ReactionClass::OBS_DEPENDENT_RXN);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(1.0));
    system->singleStep();
    CHECK(system->getObservableByName("A_total")->getCount() == 0);
    CHECK(system->getObservableByName("B_total")->getCount() == 1);
    delete system;
}

TEST_CASE("NFsim AST adapter expands direct Arrhenius binding with energy patterns") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
    Ea 0.0
    Gbind 1.0
    RT 1.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 1
    B(a) 1
end seed species
begin energy patterns
    A(b!1).B(a!1) Gbind
end energy patterns
begin reaction rules
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,Ea)
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getEnergyFunction() != nullptr);
    CHECK(system->getEnergyFunction()->getNumPatterns() == 1);
    REQUIRE(system->getAllReactions().size() == 2);
    CHECK(system->getReaction(0)->getBaseRate() == Catch::Approx(std::exp(-0.5)));
    CHECK(system->getReaction(1)->getBaseRate() == Catch::Approx(std::exp(0.5)));
    CHECK(suggestedTraversalLimit >= 2);
    delete system;
}

TEST_CASE("NFsim AST adapter expands direct Arrhenius state changes") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
    Ea 0.0
    Gup 1.0
    Gdn 0.0
    RT 1.0
end parameters
begin molecule types
    A(conf~dn~up)
end molecule types
begin seed species
    A(conf~dn) 1
end seed species
begin energy patterns
    A(conf~up) Gup
    A(conf~dn) Gdn
end energy patterns
begin reaction rules
    A(conf~dn) <-> A(conf~up) Arrhenius(phi,Ea)
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getEnergyFunction() != nullptr);
    CHECK(system->getEnergyFunction()->getNumPatterns() == 2);
    REQUIRE(system->getAllReactions().size() == 2);
    CHECK(system->getReaction(0)->getBaseRate() == Catch::Approx(std::exp(-0.5)));
    CHECK(system->getReaction(1)->getBaseRate() == Catch::Approx(std::exp(0.5)));
    CHECK(suggestedTraversalLimit >= 1);
    delete system;
}

TEST_CASE("NFsim AST adapter expands Arrhenius binding context variants") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
    Ea 0.0
    Gcontext 1.0
    RT 1.0
end parameters
begin molecule types
    A(b,c)
    B(a)
    C(x)
end molecule types
begin seed species
    A(b,c!1).C(x!1) 1
    B(a) 1
end seed species
begin energy patterns
    A(b!1,c!2).B(a!1).C(x!2) Gcontext
end energy patterns
begin reaction rules
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 4);
    CHECK(system->getReaction(0)->getBaseRate() == Catch::Approx(1.0));
    CHECK(system->getReaction(1)->getBaseRate() == Catch::Approx(1.0));
    CHECK(system->getReaction(2)->getBaseRate() == Catch::Approx(std::exp(-0.5)));
    CHECK(system->getReaction(3)->getBaseRate() == Catch::Approx(std::exp(0.5)));
    delete system;
}
