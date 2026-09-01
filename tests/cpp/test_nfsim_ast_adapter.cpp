#include <cmath>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>
#include <vector>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "NFinput_fromAst.hh"
#include "NFinput.hh"
#include "NFcore.hh"
#include "NFcore/energyPattern.hh"
#include "NFcore/reactionSelector/reactionSelector.hh"
#include "NFreactions/reactions/reaction.hh"
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

TEST_CASE("BNGL parser preserves inline and file TFUN metadata") {
    const auto linear = bng::parser::parseExpression(
        "TFUN([0, 1, 2], [0, 10, 20], time)");
    REQUIRE(linear.kind() == bng::ast::ExpressionKind::TableFunction);
    CHECK(linear.tableXValues() == std::vector<double> {0.0, 1.0, 2.0});
    CHECK(linear.tableYValues() == std::vector<double> {0.0, 10.0, 20.0});
    CHECK(linear.tableMethod() == "linear");
    CHECK(linear.evaluate([](const std::string&) { return 0.0; }, 0.5) ==
          Catch::Approx(5.0));

    const auto step = bng::parser::parseExpression(
        "tfun([0, 1, 2], [0, 10, 20], time, method=>\"step\")");
    REQUIRE(step.kind() == bng::ast::ExpressionKind::TableFunction);
    CHECK(step.tableMethod() == "step");
    CHECK(step.evaluate([](const std::string&) { return 0.0; }, 1.5) ==
          Catch::Approx(10.0));

    const auto file = bng::parser::parseExpression(
        "tfun('data file.tfun', time)");
    REQUIRE(file.kind() == bng::ast::ExpressionKind::TableFunction);
    CHECK(file.tableFilePath() == "data file.tfun");
    CHECK(file.tableFileKey() == "file_hex_646174612066696c652e7466756e");

    const auto product = bng::parser::parseExpression(
        R"BNG(FunctionProduct("left(x)", "right(y)"))BNG");
    REQUIRE(product.kind() == bng::ast::ExpressionKind::Function);
    REQUIRE(product.name() == "functionproduct");
    REQUIRE(product.args().size() == 2);
    CHECK(product.args()[0].kind() == bng::ast::ExpressionKind::ObservableRef);
    CHECK(product.args()[0].name() == "left");
    CHECK(product.args()[0].args().size() == 1);
    CHECK(product.args()[0].args()[0].name() == "x");
    CHECK(product.args()[1].kind() == bng::ast::ExpressionKind::ObservableRef);
    CHECK(product.args()[1].name() == "right");
    CHECK(product.args()[1].args().size() == 1);
    CHECK(product.args()[1].args()[0].name() == "y");
}

TEST_CASE("BNGL parser accepts singular molecule type blocks") {
    auto model = bng::parser::parseModel(R"(
begin molecule type
    A(site~0~1)
end molecule type
begin seed species
    A(site~0) 1
end seed species
)");

    REQUIRE(model != nullptr);
    REQUIRE(model->getMoleculeTypes().size() == 1);
    CHECK(model->getMoleculeTypes().front().getName() == "A");
    REQUIRE(model->getSeedSpecies().size() == 1);
}

TEST_CASE("BNGL infers numeric molecule states from all patterns") {
    // Native BNG2/NFsim accepts models without a molecule-types block and
    // derives the complete integer range from every later pattern.  This is
    // distilled from nfsim/test/testSuite/t_dor2.bngl: the seed introduces
    // m~1, while observables and rules reference m~0, m~2, and m~3.
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1
end parameters
begin seed species
    A(m~1) 1
end seed species
begin observables
    Molecules A0 A(m~0)
    Molecules A2 A(m~2)
    Molecules A3 A(m~3)
end observables
begin reaction rules
    A(m~1) -> A(m~3) k
end reaction rules
)");

    REQUIRE(model != nullptr);
    REQUIRE(model->getMoleculeTypes().size() == 1);
    REQUIRE(model->getMoleculeTypes().front().getComponents().size() == 1);
    CHECK(model->getMoleculeTypes().front().getComponents().front().allowedStates ==
          std::vector<std::string> {"1", "0", "2", "3"});

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    auto* moleculeType = system->getMoleculeTypeByName("A");
    REQUIRE(moleculeType != nullptr);
    CHECK(moleculeType->isIntegerComponent(0));
    CHECK(moleculeType->getStateValueFromName(0, "0") == 0);
    CHECK(moleculeType->getStateValueFromName(0, "3") == 3);
    delete system;
}

TEST_CASE("XML writer preserves the first explicit bond") {
    auto model = bng::parser::parseModel(R"(
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b!1).B(a!1) 1
end seed species
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("<ListOfBonds>") != std::string::npos);
    CHECK(xml.find("site1=") != std::string::npos);
    CHECK(xml.find("site2=") != std::string::npos);
}

TEST_CASE("NFsim AST adapter maps an inline time-backed TFUN directly") {
    auto model = bng::parser::parseModel(R"(
begin parameters
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 0
end seed species
begin observables
    Molecules X_total X()
end observables
begin functions
    rate() = tfun([0, 1, 2], [0, 10, 20], time)
end functions
begin reaction rules
    0 -> X() rate
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    auto* function = system->getGlobalFunctionByName("rate");
    REQUIRE(function != nullptr);
    CHECK(function->fileFunc);
    CHECK(function->getCtrType() == "System");
    system->prepareForSimulation();
    function->fileUpdate(1.5);
    CHECK(NFcore::FuncFactory::Eval(function->p) == Catch::Approx(15.0));
    delete system;
}

TEST_CASE("NFsim AST adapter resolves file-backed TFUN beside the BNGL source") {
    const auto token = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto tablePath = std::filesystem::temp_directory_path() /
                           ("bng3-direct-tfun-" + std::to_string(token) + ".dat");
    std::ofstream tableFile(tablePath);
    REQUIRE(tableFile.good());
    tableFile << "0 1\n"
              << "1 2\n"
              << "2 4\n";
    tableFile.close();

    auto model = bng::parser::parseModel(
        "begin molecule types\n"
        "    X()\n"
        "end molecule types\n"
        "begin seed species\n"
        "    X() 0\n"
        "end seed species\n"
        "begin observables\n"
        "    Molecules X_total X()\n"
        "end observables\n"
        "begin functions\n"
        "    rate() = tfun('" + tablePath.filename().string() + "', time)\n"
        "end functions\n"
        "begin reaction rules\n"
        "    0 -> X() rate\n"
        "end reaction rules\n");

    const auto sourcePath = tablePath.parent_path() / "model.bngl";
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit, sourcePath);
    REQUIRE(system != nullptr);
    REQUIRE(system->getHasTimeDependentFunctions());
    auto* function = system->getGlobalFunctionByName("rate");
    REQUIRE(function != nullptr);
    CHECK(function->fileFunc);
    CHECK(function->getCtrType() == "System");
    system->prepareForSimulation();
    function->fileUpdate(1.5);
    CHECK(NFcore::FuncFactory::Eval(function->p) == Catch::Approx(3.0));
    delete system;

    std::error_code error;
    std::filesystem::remove(tablePath, error);
}

TEST_CASE("NFsim XML bridge preserves inline TFUN metadata") {
    auto model = bng::parser::parseModel(R"(
begin molecule types
    X()
end molecule types
begin seed species
    X() 0
end seed species
begin observables
    Molecules X_total X()
end observables
begin functions
    rate() = tfun([0, 1, 2], [0, 10, 20], time, method=>"step")
end functions
begin reaction rules
    0 -> X() rate
end reaction rules
)");

    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("type=\"TFUN\"") != std::string::npos);
    CHECK(xml.find("mode=\"inline\"") != std::string::npos);
    CHECK(xml.find("method=\"step\"") != std::string::npos);
    CHECK(xml.find("<Expression>__TFUN_VAL__</Expression>") != std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    auto* function = system->getGlobalFunctionByName("rate");
    REQUIRE(function != nullptr);
    system->prepareForSimulation();
    function->fileUpdate(1.5);
    CHECK(NFcore::FuncFactory::Eval(function->p) == Catch::Approx(10.0));
    delete system;
}

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

TEST_CASE("NFsim AST adapter maps time-dependent global functions") {
    auto model = bng::parser::parseModel(R"(
begin parameters
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
    rate() = 1.0 + time()
end functions
begin reaction rules
    A() -> B() rate
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getHasTimeDependentFunctions());
    auto* function = system->getGlobalFunctionByName("rate");
    REQUIRE(function != nullptr);
    system->prepareForSimulation();
    CHECK(NFcore::FuncFactory::Eval(function->p) == Catch::Approx(1.0));
    system->singleStep();
    CHECK(NFcore::FuncFactory::Eval(function->p) ==
          Catch::Approx(1.0 + system->getCurrentTime()));
    delete system;
}

TEST_CASE("NFsim XML bridge preserves time and parameter function references") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
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
    rate() = k + time()
end functions
begin reaction rules
    A() -> B() rate
end reaction rules
)");

    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("<Reference name=\"k\" type=\"Constant\"/>") != std::string::npos);
    CHECK(xml.find("<Reference name=\"time\" type=\"Time\"/>") != std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getHasTimeDependentFunctions());
    auto* function = system->getGlobalFunctionByName("rate");
    REQUIRE(function != nullptr);
    system->prepareForSimulation();
    CHECK(NFcore::FuncFactory::Eval(function->p) == Catch::Approx(2.0));
    system->singleStep();
    CHECK(NFcore::FuncFactory::Eval(function->p) ==
          Catch::Approx(2.0 + system->getCurrentTime()));
    delete system;
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

TEST_CASE("NFsim AST adapter accepts legacy single-ended seed bond metadata") {
    // BNG2's XML species reader preserves a numeric seed bond's
    // numberOfBonds="1" metadata even when the source bond label has no
    // second endpoint.  It creates the molecule without an actual runtime
    // bond; this is the compatibility behavior used by the RNA NFsim
    // fixture, so the direct AST path must not reject that seed.
    auto model = bng::parser::parseModel(R"(
begin molecule types
    DNA(three)
end molecule types
begin seed species
    DNA(three!1) 1
end seed species
begin observables
    Molecules DNA_total DNA()
end observables
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getNumOfMolecules() == 1);
    auto* moleculeType = system->getMoleculeTypeByName("DNA");
    REQUIRE(moleculeType != nullptr);
    const auto componentIndex = moleculeType->getCompIndexFromName("three");
    CHECK(moleculeType->getMolecule(0)->isBindingSiteOpen(componentIndex));
    delete system;
}

TEST_CASE("NFsim AST adapter consumes Null discard seeds") {
    auto model = bng::parser::parseModel(R"(
begin molecule types
    A()
    Null()
end molecule types
begin seed species
    A() 1
    $Null() 0
end seed species
begin observables
    Molecules A_total A()
end observables
begin reaction rules
    A() -> Null() 1
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    CHECK(system->getNumOfMoleculeTypes() == 1);
    CHECK(system->getNumOfMolecules() == 1);
    CHECK(system->getAllReactions().size() == 1);
    delete system;
}

TEST_CASE("NFsim AST adapter creates products with symmetric components") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k_bind 2
    k_unbind 1
end parameters
begin molecule types
    D(x,x)
    C(n~0~1~2~3)
end molecule types
begin seed species
    D(x,x) 2
    C(n~3) 0
end seed species
begin observables
    Species D1 D(x,x)
    Species D2 D(x,x!0).D(x!0,x)
    Species D3 D(x,x!0).D(x!0,x!1).D(x!1,x)
    Species D3c D(x!2,x!0).D(x!0,x!1).D(x!1,x!2)
end observables
begin reaction rules
    C(n~3) -> D(x,x) 1
    D(x,x) + D(x,x) <-> D(x!0,x).D(x!0,x) k_bind, k_unbind
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() > 1);
    const auto directReactionCount = direct->getAllReactions().size();
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xml = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xml != nullptr);
    CHECK(xml->getAllReactions().size() == directReactionCount);
    delete xml;
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

TEST_CASE("NFsim AST adapter counts a pure context homodimer once per complex") {
    // Source-derived from akutuva21/nfsim commit 9b2fff8: a reactant that the
    // rule never transforms contributes one reaction instance per matching
    // complex, not one per matching molecule in that complex.  The two C
    // molecules are two independent reaction choices; the A homodimer is one
    // context choice, so the propensity is 2*k rather than 4*k.
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(x)
    C(s~0~1)
end molecule types
begin seed species
    A(x!1).A(x!1) 1
    C(s~0) 2
end seed species
begin reaction rules
    A(x!1).A(x!1) + C(s~0) -> A(x!1).A(x!1) + C(s~1) k
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(
        *model, true, false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(2.0));
    delete system;
}

TEST_CASE("NFsim AST adapter counts pure context trimer and scaffold once") {
    // Source-derived from akutuva21/nfsim commit 9b2fff8.  A single-molecule
    // context pattern must collapse all embeddings in one complex, independent
    // of pattern or species automorphisms: the trimer distinguishes a factor
    // of three, while the scaffold has two distinguishable copies.
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    C(s~0~1)
    T(a,b)
    Vx(d,t)
    Vs(p,q)
end molecule types
begin seed species
    C(s~0) 1
    T(a!1,b!3).T(a!2,b!1).T(a!3,b!2) 1
    Vx(d,t!1).Vs(p!1,q!2).Vx(d,t!2) 1
end seed species
begin reaction rules
    C(s~0) + T(a!1,b!3).T(a!2,b!1).T(a!3,b!2) -> C(s~1) + T(a!1,b!3).T(a!2,b!1).T(a!3,b!2) k
    C(s~0) + Vx(d) -> C(s~1) + Vx(d) k
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(
        *model, true, false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 2);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(1.0));
    CHECK(system->getReaction(1)->get_a() == Catch::Approx(1.0));
    delete system;
}

TEST_CASE("NFsim AST adapter preserves transformed homodimer binding multiplicity") {
    // Source-derived from akutuva21/nfsim commit 9b2fff8 and its context
    // symmetry fixture.  The homodimer is a reaction center here: either half
    // can bind B, so the propensity remains 2*k.  In particular, the EMPTY
    // transform on the second binding partner must not make this pure context.
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    B(b)
    H(d,c)
end molecule types
begin seed species
    B(b) 1
    H(d!1,c).H(d!1,c) 1
end seed species
begin reaction rules
    B(b) + H(d!1,c).H(d!1,c) -> B(b!2).H(d!1,c!2).H(d!1,c) k
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(
        *model, true, false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(2.0));
    delete system;
}

TEST_CASE("NFsim AST adapter counts pure DOR context once per complex") {
    // Source-derived from akutuva21/nfsim commit 9b2fff8 and its
    // context_symmetry.bngl R_dor_sym/R_dor_asym pair.  The locally scoped
    // homodimer is a pure context for the state-changing C molecule, so the
    // DOR tree must contribute one matching complex rather than two matching
    // embeddings.
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    Src()
    C(s~0~1)
    W(d)
end molecule types
begin seed species
    Src() 1
    C(s~0) 1
    W(d!1).W(d!1) 1
end seed species
begin observables
    Molecules Obs_Src Src()
    Molecules Cnt_W W()
end observables
begin functions
    locs(x) = k*Obs_Src + 0*Cnt_W(x)
end functions
begin reaction rules
    C(s~0) + W(d!1)%x.W(d!1) -> C(s~1) + W(d!1)%x.W(d!1) locs(x)
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(
        *model, true, false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getRxnType() == NFcore::ReactionClass::DOR_RXN);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(1.0));
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

TEST_CASE("NFsim AST adapter maps MoveConnected compartment transport") {
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
    B(site)
end molecule types
begin seed species
    A(site!1)@c1.B(site!1)@c1 1
end seed species
begin reaction rules
    A(site!1)@c1.B(site!1)@c1 -> A(site!1)@c2.B(site!1)@c1 k MoveConnected
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("moveConnected=\"1\"") != std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    direct->prepareForSimulation();
    direct->seedRNG(17);
    direct->stepTo(100.0);
    CHECK(direct->getMoleculeTypeByName("A")->getMolecule(0)->getCompartmentId() == "c2");
    CHECK(direct->getMoleculeTypeByName("B")->getMolecule(0)->getCompartmentId() == "c2");
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == 1);
    REQUIRE(xmlSystem->getMoleculeTypeByName("A")->getMoleculeCount() == 1);
    REQUIRE(xmlSystem->getMoleculeTypeByName("B")->getMoleculeCount() == 1);
    CHECK(xmlSystem->getMoleculeTypeByName("A")->getMolecule(0)->getCompartmentId() == "c1");
    CHECK(xmlSystem->getMoleculeTypeByName("B")->getMolecule(0)->getCompartmentId() == "c1");
    xmlSystem->prepareForSimulation();
    xmlSystem->seedRNG(17);
    xmlSystem->stepTo(100.0);
    REQUIRE(xmlSystem->getMoleculeTypeByName("A")->getMoleculeCount() == 1);
    REQUIRE(xmlSystem->getMoleculeTypeByName("B")->getMoleculeCount() == 1);
    CHECK(xmlSystem->getMoleculeTypeByName("A")->getMolecule(0)->getCompartmentId() == "c2");
    CHECK(xmlSystem->getMoleculeTypeByName("B")->getMolecule(0)->getCompartmentId() == "c2");
    delete xmlSystem;
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

TEST_CASE("NFsim AST adapter preserves multi-rule propensities") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    kon 10.0
    koff 5.0
    kcat 0.7
    dephos 0.5
end parameters
begin molecule types
    X(y,p~0~1)
    Y(x)
end molecule types
begin seed species
    X(y,p~0) 5000
    X(y,p~1) 0
    Y(x) 500
end seed species
begin observables
    Molecules X_free X(p~0,y)
    Molecules X_p_total X(p~1)
    Molecules Xp_free X(p~1,y)
    Molecules XY X(y!1).Y(x!1)
    Molecules Ytotal Y()
    Molecules Xtotal X()
end observables
begin reaction rules
    X(y,p~0) + Y(x) -> X(y!1,p~0).Y(x!1) kon
    X(y!1,p~0).Y(x!1) -> X(y,p~0) + Y(x) koff
    X(y!1,p~0).Y(x!1) -> X(y,p~1) + Y(x) kcat
    X(p~1) -> X(p~0) dephos
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 10000, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 4);
    direct->prepareForSimulation();

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 10000, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == direct->getAllReactions().size());
    xmlSystem->prepareForSimulation();
    for (std::size_t index = 0; index < direct->getAllReactions().size(); ++index) {
        CHECK(direct->getAllReactions()[index]->getName() ==
              xmlSystem->getAllReactions()[index]->getName());
        CHECK(direct->getAllReactions()[index]->get_a() ==
              Catch::Approx(xmlSystem->getAllReactions()[index]->get_a()));
    }
    delete direct;
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter expands symmetric state-change reaction centers") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b~0~1,b~0~1)
end molecule types
begin seed species
    A(b~0) 1
end seed species
begin reaction rules
    A(b~0) -> A(b~1) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 2);
    CHECK(direct->getAllReactions()[0]->getName() == "R1_sym1");
    CHECK(direct->getAllReactions()[1]->getName() == "R1_sym2");
    direct->prepareForSimulation();
    direct->seedRNG(7);
    direct->stepTo(100.0);
    auto* directA = direct->getMoleculeTypeByName("A")->getMolecule(0);
    const auto directB1 = directA->getMoleculeType()->getCompIndexFromName("b1");
    const auto directB2 = directA->getMoleculeType()->getCompIndexFromName("b2");
    CHECK((directA->getComponentState(directB1) == 1 ||
           directA->getComponentState(directB2) == 1));
    const auto directReactionCount = direct->getAllReactions().size();
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    CHECK(xmlSystem->getAllReactions().size() == directReactionCount);
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter keeps dynamic symmetric state changes live") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin molecule types
    A(b~0~1,b~0~1)
end molecule types
begin seed species
    A(b~0) 1
end seed species
begin observables
    Molecules A_total A()
end observables
begin reaction rules
    A(b~0) -> A(b~1) k + time()
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 2);
    REQUIRE(direct->getGlobalFunctionByName("__bng3_reaction_rate_1") != nullptr);
    CHECK(direct->getHasTimeDependentFunctions());
    CHECK(direct->getReaction(0)->getRxnType() ==
          NFcore::ReactionClass::OBS_DEPENDENT_RXN);
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(2.0));
    *direct->getCurrentTimePtr() = 2.0;
    CHECK(direct->getReaction(0)->update_a() == Catch::Approx(4.0));
    direct->seedRNG(11);
    direct->stepTo(100.0);
    auto* directA = direct->getMoleculeTypeByName("A")->getMolecule(0);
    const auto directB1 = directA->getMoleculeType()->getCompIndexFromName("b1");
    const auto directB2 = directA->getMoleculeType()->getCompIndexFromName("b2");
    CHECK((directA->getComponentState(directB1) == 1 ||
           directA->getComponentState(directB2) == 1));
    const auto directReactionCount = direct->getAllReactions().size();
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == directReactionCount);
    CHECK(xmlSystem->getHasTimeDependentFunctions());
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(2.0));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter expands multiple symmetric state centers") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b~0~1,b~0~1)
end molecule types
begin seed species
    A(b~0,b~0) 1
end seed species
begin reaction rules
    A(b~0,b~0) -> A(b~1,b~1) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 2);
    direct->prepareForSimulation();
    direct->seedRNG(17);
    direct->stepTo(100.0);
    auto* directA = direct->getMoleculeTypeByName("A")->getMolecule(0);
    const auto directB1 = directA->getMoleculeType()->getCompIndexFromName("b1");
    const auto directB2 = directA->getMoleculeType()->getCompIndexFromName("b2");
    CHECK(directA->getComponentState(directB1) == 1);
    CHECK(directA->getComponentState(directB2) == 1);
    const auto directReactionCount = direct->getAllReactions().size();
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    CHECK(xmlSystem->getAllReactions().size() == directReactionCount);
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter expands symmetric state context with a center") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b~0~1,b~0~1)
end molecule types
begin seed species
    A(b~0,b~0) 1
end seed species
begin reaction rules
    A(b~0,b~0) -> A(b~1,b~0) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 2);
    direct->prepareForSimulation();
    direct->seedRNG(19);
    direct->stepTo(100.0);
    auto* directA = direct->getMoleculeTypeByName("A")->getMolecule(0);
    const auto directB1 = directA->getMoleculeType()->getCompIndexFromName("b1");
    const auto directB2 = directA->getMoleculeType()->getCompIndexFromName("b2");
    CHECK((directA->getComponentState(directB1) == 1) !=
          (directA->getComponentState(directB2) == 1));
    const auto directReactionCount = direct->getAllReactions().size();
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    CHECK(xmlSystem->getAllReactions().size() == directReactionCount);
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter expands symmetric binding reaction centers") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b~0~1,b~0~1)
    B(a)
end molecule types
begin seed species
    A(b) 1
    B(a) 1
end seed species
begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 2);
    CHECK(direct->getAllReactions()[0]->getName() == "R1_sym1");
    CHECK(direct->getAllReactions()[1]->getName() == "R1_sym2");
    direct->prepareForSimulation();
    direct->seedRNG(7);
    direct->stepTo(100.0);
    auto* directA = direct->getMoleculeTypeByName("A")->getMolecule(0);
    const auto directB1 = directA->getMoleculeType()->getCompIndexFromName("b1");
    const auto directB2 = directA->getMoleculeType()->getCompIndexFromName("b2");
    CHECK((directA->isBindingSiteBonded(directB1) ||
           directA->isBindingSiteBonded(directB2)));
    const auto directReactionCount = direct->getAllReactions().size();
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    CHECK(xmlSystem->getAllReactions().size() == directReactionCount);
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter keeps dynamic symmetric binding live") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin molecule types
    A(b~0~1,b~0~1)
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
    A(b) + B(a) -> A(b!1).B(a!1) k + time()
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 2);
    CHECK(direct->getHasTimeDependentFunctions());
    CHECK(direct->getReaction(0)->getRxnType() ==
          NFcore::ReactionClass::OBS_DEPENDENT_RXN);
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(2.0));
    *direct->getCurrentTimePtr() = 2.0;
    CHECK(direct->getReaction(0)->update_a() == Catch::Approx(4.0));
    direct->seedRNG(13);
    direct->stepTo(100.0);
    auto* directA = direct->getMoleculeTypeByName("A")->getMolecule(0);
    const auto directB1 = directA->getMoleculeType()->getCompIndexFromName("b1");
    const auto directB2 = directA->getMoleculeType()->getCompIndexFromName("b2");
    CHECK((directA->isBindingSiteBonded(directB1) ||
           directA->isBindingSiteBonded(directB2)));
    const auto directReactionCount = direct->getAllReactions().size();
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == directReactionCount);
    CHECK(xmlSystem->getHasTimeDependentFunctions());
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(2.0));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter expands symmetric bond context with a center") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b~0~1,b~0~1)
    B(a)
end molecule types
begin seed species
    A(b~0,b~0) 1
    B(a) 1
end seed species
begin reaction rules
    A(b~0,b~0) + B(a) -> A(b~0,b~0!1).B(a!1) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 2);
    direct->prepareForSimulation();
    direct->seedRNG(23);
    direct->stepTo(100.0);
    auto* directA = direct->getMoleculeTypeByName("A")->getMolecule(0);
    const auto directB1 = directA->getMoleculeType()->getCompIndexFromName("b1");
    const auto directB2 = directA->getMoleculeType()->getCompIndexFromName("b2");
    CHECK((directA->isBindingSiteBonded(directB1) !=
           directA->isBindingSiteBonded(directB2)));
    const auto directReactionCount = direct->getAllReactions().size();
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    CHECK(xmlSystem->getAllReactions().size() == directReactionCount);
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter expands symmetric unbinding reaction centers") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b~0~1,b~0~1)
    B(a)
end molecule types
begin seed species
    A(b!1).B(a!1) 1
end seed species
begin reaction rules
    A(b!1).B(a!1) -> A(b) + B(a) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 2);
    auto* initialA = direct->getMoleculeTypeByName("A")->getMolecule(0);
    const auto initialB1 = initialA->getMoleculeType()->getCompIndexFromName("b1");
    const auto initialB2 = initialA->getMoleculeType()->getCompIndexFromName("b2");
    CHECK(initialA->isBindingSiteBonded(initialB1) !=
          initialA->isBindingSiteBonded(initialB2));
    CHECK(direct->getAllReactions()[0]->getName() == "R1_sym1");
    CHECK(direct->getAllReactions()[1]->getName() == "R1_sym2");
    direct->prepareForSimulation();
    direct->seedRNG(7);
    direct->stepTo(100.0);
    auto* directA = direct->getMoleculeTypeByName("A")->getMolecule(0);
    const auto directB1 = directA->getMoleculeType()->getCompIndexFromName("b1");
    const auto directB2 = directA->getMoleculeType()->getCompIndexFromName("b2");
    CHECK_FALSE(directA->isBindingSiteBonded(directB1));
    CHECK_FALSE(directA->isBindingSiteBonded(directB2));
    const auto directReactionCount = direct->getAllReactions().size();
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    CHECK(xmlSystem->getAllReactions().size() == directReactionCount);
    delete xmlSystem;
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
    auto* initialA = system->getMoleculeTypeByName("A")->getMolecule(0);
    const auto initialB = initialA->getMoleculeType()->getCompIndexFromName("b");
    CHECK(initialA->isBindingSiteBonded(initialB));
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

TEST_CASE("NFsim AST adapter maps intramolecular product bonds") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    Source()
    A(x,x)
end molecule types
begin seed species
    Source() 1
end seed species
begin observables
    Species A_ring A(x!1,x!1)
end observables
begin reaction rules
    Source() -> Source() + A(x!1,x!1) k
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    CHECK(system->getObservableByName("A_ring")->getCount() == 0);
    system->seedRNG(8);
    system->stepTo(100.0);
    CHECK(system->getObservableByName("A_ring")->getCount() > 0);
    auto* moleculeType = system->getMoleculeTypeByName("A");
    REQUIRE(moleculeType != nullptr);
    REQUIRE(moleculeType->getMolecule(0) != nullptr);
    const auto x1 = moleculeType->getCompIndexFromName("x1");
    const auto x2 = moleculeType->getCompIndexFromName("x2");
    CHECK(moleculeType->getMolecule(0)->isBindingSiteBonded(x1));
    CHECK(moleculeType->getMolecule(0)->isBindingSiteBonded(x2));
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

TEST_CASE("NFsim Michaelis-Menten propensity remains stable for tiny Km") {
    // Regression distilled from NFsim/test/MM/mm_small_km.bngl. With enzyme
    // in excess and Km far below one, the naive quadratic-root expression
    // loses the small positive substrate root to floating-point cancellation.
    auto model = bng::parser::parseModel(R"(
begin parameters
    kcat 1.0
    Km 1e-15
end parameters
begin molecule types
    S()
    E()
    P()
end molecule types
begin seed species
    S() 100
    E() 200
    P() 0
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
    auto* system = NFinput::buildSystemFromAst(
        *model, false, 1000, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(100.0));
    system->singleStep();
    CHECK(system->getObservableByName("S_total")->getCount() == 99);
    CHECK(system->getObservableByName("P_total")->getCount() == 1);
    delete system;
}

TEST_CASE("NFsim AST adapter maps Sat rates directly and through XML") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    kcat 1.0
    Km 10.0
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
    S() + E() -> P() + E() Sat(kcat,Km)
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("type=\"Sat\"") != std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(100.0 * 100.0 / 110.0));
    direct->singleStep();
    CHECK(direct->getObservableByName("S_total")->getCount() == 99);
    CHECK(direct->getObservableByName("P_total")->getCount() == 1);
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == 1);
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(100.0 * 100.0 / 110.0));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter maps Hill rates directly and through XML") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    Vmax 2.0
    Kh 10.0
    n 2.0
end parameters
begin molecule types
    S()
    P()
end molecule types
begin seed species
    S() 100
end seed species
begin observables
    Molecules S_total S()
    Molecules P_total P()
end observables
begin reaction rules
    S() -> P() Hill(Vmax,Kh,n)
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("type=\"Hill\"") != std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    direct->prepareForSimulation();
    const double expected = 2.0 * 100.0 * 100.0 / (10.0 * 10.0 + 100.0 * 100.0);
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(expected));
    direct->singleStep();
    CHECK(direct->getObservableByName("S_total")->getCount() == 99);
    CHECK(direct->getObservableByName("P_total")->getCount() == 1);
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == 1);
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(expected));
    delete xmlSystem;
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

TEST_CASE("NFsim AST adapter applies zero-order compartment volume conversion") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin compartments
    cell 3 4
end compartments
begin molecule types
    Product(site~U~P)
end molecule types
begin observables
    Molecules product_P Product@cell(site~P)
end observables
begin reaction rules
    0 -> Product@cell(site~P) k
end reaction rules
)");
    REQUIRE(model != nullptr);
    model->setOption("NumberPerQuantityUnit", "10");

    int directTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, directTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(80.0));
    delete direct;

    int xmlTraversalLimit = 0;
    auto* xml = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, xmlTraversalLimit);
    REQUIRE(xml != nullptr);
    REQUIRE(xml->getAllReactions().size() == 1);
    xml->prepareForSimulation();
    CHECK(xml->getReaction(0)->get_a() == Catch::Approx(80.0));
    delete xml;
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

TEST_CASE("NFsim AST adapter maps dynamic observable reaction rates directly and through XML") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin molecule types
    A()
    X()
    B()
end molecule types
begin seed species
    A() 1
    X() 1
end seed species
begin observables
    Molecules atotal A()
end observables
begin reaction rules
    X() -> X() + B() k*atotal()
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("__bng3_reaction_rate_RR1") != std::string::npos);
    CHECK(xml.find("<Reference name=\"atotal\" type=\"Observable\"/>") !=
          std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    CHECK(direct->getReaction(0)->getRxnType() ==
          NFcore::ReactionClass::OBS_DEPENDENT_RXN);
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(2.0));
    direct->addConcentration("A()", 1);
    CHECK(direct->getObservableByName("atotal")->getCount() == 2);
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(4.0));
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == 1);
    CHECK(xmlSystem->getReaction(0)->getRxnType() ==
          NFcore::ReactionClass::OBS_DEPENDENT_RXN);
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(2.0));
    xmlSystem->addConcentration("A()", 1);
    CHECK(xmlSystem->getObservableByName("atotal")->getCount() == 2);
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(4.0));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter keeps time-dependent reaction rates live") {
    auto model = bng::parser::parseModel(R"(
begin molecule types
    X()
end molecule types
begin seed species
    X() 0
end seed species
begin reaction rules
    0 -> X() 1 + time()
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    REQUIRE(direct->getHasTimeDependentFunctions());
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(1.0));
    *direct->getCurrentTimePtr() = 2.5;
    CHECK(direct->getReaction(0)->update_a() == Catch::Approx(3.5));
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == 1);
    REQUIRE(xmlSystem->getHasTimeDependentFunctions());
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(1.0));
    *xmlSystem->getCurrentTimePtr() = 2.5;
    CHECK(xmlSystem->getReaction(0)->update_a() == Catch::Approx(3.5));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter maps dynamic rates through base global functions") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules atotal A()
end observables
begin functions
    base k + atotal
end functions
begin reaction rules
    A() -> B() k * base()
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("__bng3_reaction_rate_RR1") != std::string::npos);
    CHECK(xml.find("<Reference name=\"base\" type=\"Function\"/>") !=
          std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    auto* directRate = direct->getCompositeFunctionByName("__bng3_reaction_rate_1");
    REQUIRE(directRate != nullptr);
    REQUIRE(direct->getGlobalFunctionByName("base") != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(6.0));
    direct->addConcentration("A()", 1);
    CHECK(direct->getObservableByName("atotal")->getCount() == 2);
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(16.0));
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    auto* xmlRate = xmlSystem->getCompositeFunctionByName("__bng3_reaction_rate_RR1");
    REQUIRE(xmlRate != nullptr);
    REQUIRE(xmlSystem->getGlobalFunctionByName("base") != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == 1);
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(6.0));
    xmlSystem->addConcentration("A()", 1);
    CHECK(xmlSystem->getObservableByName("atotal")->getCount() == 2);
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(16.0));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter expands composite functions in dynamic reaction rates") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules atotal A()
end observables
begin functions
    base k + atotal
    composite base() + 1
    top composite() + 1
end functions
begin reaction rules
    A() -> B() k * top()
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("__bng3_reaction_rate_RR1") != std::string::npos);
    CHECK(xml.find("<Reference name=\"atotal\" type=\"Observable\"/>") !=
          std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getCompositeFunctionByName("top") != nullptr);
    REQUIRE(direct->getCompositeFunctionByName("__bng3_reaction_rate_1") != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(10.0));
    direct->addConcentration("A()", 1);
    CHECK(direct->getObservableByName("atotal")->getCount() == 2);
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(24.0));
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getCompositeFunctionByName("top") != nullptr);
    REQUIRE(xmlSystem->getCompositeFunctionByName("__bng3_reaction_rate_RR1") != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == 1);
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(10.0));
    xmlSystem->addConcentration("A()", 1);
    CHECK(xmlSystem->getObservableByName("atotal")->getCount() == 2);
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(24.0));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter mixes direct observables with base global reaction rates") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules atotal A()
end observables
begin functions
    base k
end functions
begin reaction rules
    A() -> B() k * base() + atotal()
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("__bng3_reaction_observable_RR1_1") != std::string::npos);
    CHECK(xml.find("<Reference name=\"__bng3_reaction_observable_RR1_1\" type=\"Function\"/>") !=
          std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getCompositeFunctionByName("__bng3_reaction_rate_1") != nullptr);
    REQUIRE(direct->getGlobalFunctionByName("__bng3_reaction_observable_1_1") != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(5.0));
    direct->addConcentration("A()", 1);
    CHECK(direct->getObservableByName("atotal")->getCount() == 2);
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(12.0));
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getCompositeFunctionByName("__bng3_reaction_rate_RR1") != nullptr);
    REQUIRE(xmlSystem->getGlobalFunctionByName("__bng3_reaction_observable_RR1_1") != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == 1);
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(5.0));
    xmlSystem->addConcentration("A()", 1);
    CHECK(xmlSystem->getObservableByName("atotal")->getCount() == 2);
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(12.0));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter maps zero-argument composite function rates") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
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
    base k
    rate base() + 1
end functions
begin reaction rules
    A() -> B() rate
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("<Reference name=\"base\" type=\"Function\"/>") !=
          std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getGlobalFunctionByName("base") != nullptr);
    REQUIRE(system->getCompositeFunctionByName("rate") != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getRxnType() ==
          NFcore::ReactionClass::OBS_DEPENDENT_RXN);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(3.0));
    system->singleStep();
    CHECK(system->getObservableByName("A_total")->getCount() == 0);
    CHECK(system->getObservableByName("B_total")->getCount() == 1);
    delete system;
}

TEST_CASE("NFsim AST adapter maps a scoped local function rate") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin molecule types
    A()
    C()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules atotal A()
    Molecules ctotal C()
end observables
begin functions
    f(x) = k*atotal(x)
end functions
begin reaction rules
    %x::A() -> %x::A() + C() f(x)
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getLocalFunctionByName("f") != nullptr);
    REQUIRE(system->getCompositeFunctionByName("f") != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getRxnType() == NFcore::ReactionClass::DOR_RXN);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(2.0));
    delete system;
}

TEST_CASE("NFsim AST adapter maps arithmetic around a scoped local function rate") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules atotal A()
end observables
begin functions
    f(x) = atotal(x)
end functions
begin reaction rules
    %x::A() -> %x::A() + B() k + f(x)
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getCompositeFunctionByName("__bng3_reaction_rate_1") != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    CHECK(direct->getReaction(0)->getRxnType() == NFcore::ReactionClass::DOR_RXN);
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(3.0));
    delete direct;
}

TEST_CASE("NFsim XML bridge maps arithmetic around a scoped local function rate") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules atotal A()
end observables
begin functions
    f(x) = atotal(x)
end functions
begin reaction rules
    %x::A() -> %x::A() + B() k + f(x)
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("<Function id=\"__bng3_reaction_rate_RR1\"") !=
          std::string::npos);
    CHECK(xml.find("<Argument id=\"x\"/>") != std::string::npos);
    CHECK(xml.find("<Expression>(k + f(x))</Expression>") !=
          std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getCompositeFunctionByName("__bng3_reaction_rate_RR1") != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(3.0));
    delete system;
}

TEST_CASE("NFsim AST adapter maps a bounded nested local function rate") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 2.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules atotal A()
end observables
begin functions
    g(x) = k * atotal(x)
    f(x) = g(x) + 1
end functions
begin reaction rules
    %x::A() -> %x::A() + B() f(x)
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("<Reference name=\"g\" type=\"Function\"/>") !=
          std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getLocalFunctionByName("g") != nullptr);
    CHECK(direct->getLocalFunctionByName("f") == nullptr);
    REQUIRE(direct->getCompositeFunctionByName("f") != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(3.0));
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getLocalFunctionByName("g") != nullptr);
    CHECK(xmlSystem->getLocalFunctionByName("f") == nullptr);
    REQUIRE(xmlSystem->getCompositeFunctionByName("f") != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == 1);
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(3.0));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter updates time-dependent local rates") {
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
    Molecules atotal A()
end observables
begin functions
    f(x) = k + atotal(x) + time()
end functions
begin reaction rules
    %x::A() -> %x::A() + B() f(x)
end reaction rules
)");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getLocalFunctionByName("f") != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    REQUIRE(system->getHasTimeDependentFunctions());
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(2.0));

    *system->getCurrentTimePtr() = 2.5;
    CHECK(system->getReaction(0)->update_a() == Catch::Approx(4.5));
    delete system;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getLocalFunctionByName("f") != nullptr);
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(2.0));
    *xmlSystem->getCurrentTimePtr() = 2.5;
    CHECK(xmlSystem->getReaction(0)->update_a() == Catch::Approx(4.5));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter maps time-backed local TFUN rates") {
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
    Molecules atotal A()
end observables
begin functions
    f(x) = TFUN([0, 1], [2, 4], time) + atotal(x)
end functions
begin reaction rules
    %x::A() -> %x::A() + B() f(x)
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("type=\"TFUN\"") != std::string::npos);
    CHECK(xml.find("__TFUN_VAL__") != std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getLocalFunctionByName("f") != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    REQUIRE(direct->getHasTimeDependentFunctions());
    direct->prepareForSimulation();
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(3.0));
    *direct->getCurrentTimePtr() = 0.5;
    CHECK(direct->getReaction(0)->update_a() == Catch::Approx(4.0));
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getLocalFunctionByName("f") != nullptr);
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(3.0));
    *xmlSystem->getCurrentTimePtr() = 0.5;
    CHECK(xmlSystem->getReaction(0)->update_a() == Catch::Approx(4.0));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter maps observable-backed local TFUN rates") {
    auto model = bng::parser::parseModel(R"(
begin molecule types
    A()
    X()
    B()
end molecule types
begin seed species
    A() 1
    X() 1
end seed species
begin observables
    Molecules atotal A()
end observables
begin functions
    f(x) = TFUN([0, 1, 2], [2, 4, 6], atotal)
end functions
begin reaction rules
    %x::X() -> %x::X() + B() f(x)
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("type=\"TFUN\"") != std::string::npos);
    CHECK(xml.find("ctrName=\"atotal\"") != std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    auto* directLocal = direct->getLocalFunctionByName("f");
    REQUIRE(directLocal != nullptr);
    direct->prepareForSimulation();
    CHECK(directLocal->getCounterValue() == Catch::Approx(1.0));
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(4.0));
    direct->addConcentration("A()", 1);
    CHECK(direct->getObservableByName("atotal")->getCount() == 2);
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(6.0));
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    auto* xmlLocal = xmlSystem->getLocalFunctionByName("f");
    REQUIRE(xmlLocal != nullptr);
    xmlSystem->prepareForSimulation();
    CHECK(xmlLocal->getCounterValue() == Catch::Approx(1.0));
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(4.0));
    xmlSystem->addConcentration("A()", 1);
    CHECK(xmlSystem->getObservableByName("atotal")->getCount() == 2);
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(6.0));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter maps function-counter TFUN rates") {
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
begin functions
    base k
    f(x) = TFUN([0, 1, 2], [2, 4, 6], base)
end functions
begin reaction rules
    %x::A() -> %x::A() + B() f(x)
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("type=\"TFUN\"") != std::string::npos);
    CHECK(xml.find("ctrName=\"base\"") != std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    CHECK(direct->getLocalFunctionByName("f") == nullptr);
    auto* directComposite = direct->getCompositeFunctionByName("f");
    REQUIRE(directComposite != nullptr);
    REQUIRE(direct->getGlobalFunctionByName("base") != nullptr);
    REQUIRE(direct->getAllReactions().size() == 1);
    direct->prepareForSimulation();
    CHECK(directComposite->getCounterValue() == Catch::Approx(1.0));
    CHECK(direct->getReaction(0)->get_a() == Catch::Approx(4.0));
    direct->setParameter("k", 2.0);
    direct->updateSystemWithNewParameters();
    CHECK(directComposite->getCounterValue() == Catch::Approx(2.0));
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    CHECK(xmlSystem->getLocalFunctionByName("f") == nullptr);
    auto* xmlComposite = xmlSystem->getCompositeFunctionByName("f");
    REQUIRE(xmlComposite != nullptr);
    REQUIRE(xmlSystem->getGlobalFunctionByName("base") != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == 1);
    xmlSystem->prepareForSimulation();
    CHECK(xmlComposite->getCounterValue() == Catch::Approx(1.0));
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(4.0));
    xmlSystem->setParameter("k", 2.0);
    xmlSystem->updateSystemWithNewParameters();
    CHECK(xmlComposite->getCounterValue() == Catch::Approx(2.0));
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter maps a legacy molecule-label local scope") {
    auto model = bng::parser::parseModel(R"(
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules atotal A()
end observables
begin functions
    f(x) = atotal(x)
end functions
begin reaction rules
    A()%x -> A()%x f(x)
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getRxnType() == NFcore::ReactionClass::DOR_RXN);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(1.0));
    delete system;
}

TEST_CASE("NFsim AST adapter maps species-scoped local rates") {
    auto model = bng::parser::parseModel(R"(
begin molecule types
    A(b~u~p)
    I(i)
end molecule types
begin seed species
    A(b~u!1).I(i!1) 1
end seed species
begin observables
    Molecules I_total I()
    Molecules A_phosphorylated A(b~p!?)
end observables
begin functions
    f(x) = I_total(x)
end functions
begin reaction rules
    %x::A(b~u!1).I(i!1) -> %x::A(b~p!1).I(i!1) f(x)
end reaction rules
)");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("<Argument id=\"x\" type=\"ObjectReference\" value=\"RR1_RP1\"/>") !=
          std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* directSystem = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(directSystem != nullptr);
    REQUIRE(directSystem->getAllReactions().size() == 1);
    directSystem->prepareForSimulation();
    CHECK(directSystem->getReaction(0)->get_a() == Catch::Approx(1.0));
    directSystem->singleStep();
    CHECK(directSystem->getObservableByName("A_phosphorylated")->getCount() == 1);
    delete directSystem;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    xmlSystem->prepareForSimulation();
    CHECK(xmlSystem->getReaction(0)->get_a() == Catch::Approx(1.0));
    xmlSystem->singleStep();
    CHECK(xmlSystem->getObservableByName("A_phosphorylated")->getCount() == 1);
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter enforces reactant include and exclude filters") {
    const auto makeModel = [](const std::string& modifier) {
        std::string source = R"BNG(
begin molecule types
    A(b)
    I(i)
    B()
end molecule types
begin seed species
    A(b!1).I(i!1) 1
end seed species
begin observables
    Molecules B_total B()
end observables
begin reaction rules
    A(b!+) -> A(b!+) + B() 1 __MODIFIER__
end reaction rules
)BNG";
        const auto marker = source.find("__MODIFIER__");
        source.replace(marker, std::string("__MODIFIER__").size(), modifier);
        return bng::parser::parseModel(source);
    };

    auto excludedModel = makeModel("exclude_reactants(1,I())");
    REQUIRE(excludedModel != nullptr);
    int suggestedTraversalLimit = 0;
    auto* excludedSystem = NFinput::buildSystemFromAst(
        *excludedModel, false, 100, false, suggestedTraversalLimit);
    REQUIRE(excludedSystem != nullptr);
    excludedSystem->prepareForSimulation();
    CHECK(excludedSystem->getObservableByName("B_total")->getCount() == 0);
    excludedSystem->singleStep();
    CHECK(excludedSystem->getObservableByName("B_total")->getCount() == 0);
    delete excludedSystem;

    auto includedModel = makeModel("include_reactants(1,I())");
    REQUIRE(includedModel != nullptr);
    suggestedTraversalLimit = 0;
    auto* includedSystem = NFinput::buildSystemFromAst(
        *includedModel, false, 100, false, suggestedTraversalLimit);
    REQUIRE(includedSystem != nullptr);
    includedSystem->prepareForSimulation();
    CHECK(includedSystem->getObservableByName("B_total")->getCount() == 0);
    includedSystem->singleStep();
    CHECK(includedSystem->getObservableByName("B_total")->getCount() == 1);
    delete includedSystem;
}

TEST_CASE("NFsim XML bridge preserves reactant filters") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
    A(b)
    I(i)
    B()
end molecule types
begin seed species
    A(b!1).I(i!1) 1
end seed species
begin observables
    Molecules B_total B()
end observables
begin reaction rules
    A(b!+) -> A(b!+) + B() 1 exclude_reactants(1,I())
end reaction rules
)BNG");
    REQUIRE(model != nullptr);

    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("<ListOfExcludeReactants id=\"RR1_RP1\">") != std::string::npos);
    CHECK(xml.find("<Pattern id=\"RR1_RP1_P1\">") != std::string::npos);
    CHECK(xml.find("name=\"I\"") != std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    system->prepareForSimulation();
    CHECK(system->getObservableByName("B_total")->getCount() == 0);
    system->singleStep();
    CHECK(system->getObservableByName("B_total")->getCount() == 0);
    delete system;
}

TEST_CASE("NFsim AST adapter enforces bounded product filters") {
    const auto makeModel = [](const std::string& modifier) {
        std::string source = R"BNG(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules B_total B()
end observables
begin reaction rules
    A() -> B() 1 __MODIFIER__
end reaction rules
)BNG";
        const auto marker = source.find("__MODIFIER__");
        source.replace(marker, std::string("__MODIFIER__").size(), modifier);
        return bng::parser::parseModel(source);
    };

    auto includedModel = makeModel("include_products(1,B())");
    REQUIRE(includedModel != nullptr);
    const auto includedXml = bng::io::XmlWriter::write(*includedModel);
    CHECK(includedXml.find("<ListOfIncludeProducts id=\"RR1_PP1\">") !=
          std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* includedDirect = NFinput::buildSystemFromAst(
        *includedModel, false, 100, false, suggestedTraversalLimit);
    REQUIRE(includedDirect != nullptr);
    REQUIRE(includedDirect->getAllReactions().size() == 1);
    includedDirect->prepareForSimulation();
    includedDirect->singleStep();
    CHECK(includedDirect->getObservableByName("B_total")->getCount() == 1);
    delete includedDirect;

    suggestedTraversalLimit = 0;
    auto* includedXmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(includedModel.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(includedXmlSystem != nullptr);
    REQUIRE(includedXmlSystem->getAllReactions().size() == 1);
    includedXmlSystem->prepareForSimulation();
    includedXmlSystem->singleStep();
    CHECK(includedXmlSystem->getObservableByName("B_total")->getCount() == 1);
    delete includedXmlSystem;

    auto excludedModel = makeModel("exclude_products(1,B())");
    REQUIRE(excludedModel != nullptr);

    suggestedTraversalLimit = 0;
    auto* excludedDirect = NFinput::buildSystemFromAst(
        *excludedModel, false, 100, false, suggestedTraversalLimit);
    REQUIRE(excludedDirect != nullptr);
    CHECK(excludedDirect->getAllReactions().empty());
    delete excludedDirect;

    suggestedTraversalLimit = 0;
    auto* excludedXmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(excludedModel.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(excludedXmlSystem != nullptr);
    CHECK(excludedXmlSystem->getAllReactions().empty());
    delete excludedXmlSystem;
}

TEST_CASE("NFsim AST adapter swaps bounded filters for reversible rules") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
    k_forward 1.0
    k_reverse 1.0
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
begin reaction rules
    A() <-> B() k_forward, k_reverse include_reactants(1,A())
end reaction rules
)BNG");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("<ListOfIncludeReactants id=\"RR1_RP1\">") !=
          std::string::npos);
    CHECK(xml.find("<ListOfIncludeProducts id=\"RR1r_PP1\">") !=
          std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* direct = NFinput::buildSystemFromAst(
        *model, false, 100, false, suggestedTraversalLimit);
    REQUIRE(direct != nullptr);
    REQUIRE(direct->getAllReactions().size() == 2);
    direct->prepareForSimulation();
    direct->singleStep();
    CHECK(direct->getObservableByName("A_total")->getCount() == 0);
    CHECK(direct->getObservableByName("B_total")->getCount() == 1);
    direct->singleStep();
    CHECK(direct->getObservableByName("A_total")->getCount() == 1);
    CHECK(direct->getObservableByName("B_total")->getCount() == 0);
    delete direct;

    suggestedTraversalLimit = 0;
    auto* xmlSystem = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(xmlSystem != nullptr);
    REQUIRE(xmlSystem->getAllReactions().size() == 2);
    xmlSystem->prepareForSimulation();
    xmlSystem->singleStep();
    CHECK(xmlSystem->getObservableByName("A_total")->getCount() == 0);
    CHECK(xmlSystem->getObservableByName("B_total")->getCount() == 1);
    xmlSystem->singleStep();
    CHECK(xmlSystem->getObservableByName("A_total")->getCount() == 1);
    CHECK(xmlSystem->getObservableByName("B_total")->getCount() == 0);
    delete xmlSystem;
}

TEST_CASE("NFsim AST adapter maps a bounded FunctionProduct rate") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
    B() 1
end seed species
begin observables
    Molecules atotal A()
    Molecules btotal B()
end observables
begin functions
    fA(x) = atotal(x)
    fB(y) = btotal(y)
end functions
begin reaction rules
    %x::A() + %y::B() -> %x::A() + %y::B() FunctionProduct("fA(x)", "fB(y)")
end reaction rules
)BNG");

    REQUIRE(model != nullptr);
    REQUIRE(model->getReactionRules().size() == 1);
    const auto& rate = model->getReactionRules().front().getRates().front();
    REQUIRE(rate.name() == "functionproduct");
    REQUIRE(rate.args().size() == 2);
    CHECK(rate.args()[0].name() == "fA");
    CHECK(rate.args()[1].name() == "fB");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getRxnType() == NFcore::ReactionClass::DOR2_RXN);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(1.0));
    delete system;
}

TEST_CASE("NFsim AST adapter maps a raw local-function product rate") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
    B() 1
end seed species
begin observables
    Molecules atotal A()
    Molecules btotal B()
end observables
begin functions
    fA(x) = atotal(x)
    fB(y) = btotal(y)
end functions
begin reaction rules
    %x::A() + %y::B() -> %x::A() + %y::B() fA(x)*fB(y)
end reaction rules
)BNG");

    REQUIRE(model != nullptr);
    REQUIRE(model->getReactionRules().size() == 1);
    const auto& rate = model->getReactionRules().front().getRates().front();
    REQUIRE(rate.kind() == bng::ast::ExpressionKind::Binary);
    CHECK(rate.name() == "*");
    REQUIRE(rate.args().size() == 2);
    CHECK(rate.args()[0].name() == "fA");
    CHECK(rate.args()[1].name() == "fB");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getRxnType() == NFcore::ReactionClass::DOR2_RXN);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(1.0));
    delete system;
}

TEST_CASE("NFsim AST adapter maps legacy-tagged raw local-function products") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
    B() 1
end seed species
begin observables
    Molecules atotal A()
    Molecules btotal B()
end observables
begin functions
    fA(x) = atotal(x)
    fB(y) = btotal(y)
end functions
begin reaction rules
    A%x() + B%y() -> A%x() + B%y() fA(x)*fB(y)
end reaction rules
)BNG");

    REQUIRE(model != nullptr);
    REQUIRE(model->getReactionRules().size() == 1);
    const auto& rule = model->getReactionRules().front();
    REQUIRE(rule.getReactants().size() == 2);
    CHECK(rule.getReactants()[0] == "A%x()");
    CHECK(rule.getReactants()[1] == "B%y()");

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getRxnType() == NFcore::ReactionClass::DOR2_RXN);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(1.0));
    delete system;
}

TEST_CASE("NFsim XML bridge preserves raw local-function products") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
    B() 1
end seed species
begin observables
    Molecules atotal A()
    Molecules btotal B()
end observables
begin functions
    fA(x) = atotal(x)
    fB(y) = btotal(y)
end functions
begin reaction rules
    A%x() + B%y() -> A%x() + B%y() fA(x)*fB(y)
end reaction rules
)BNG");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("type=\"FunctionProduct\"") != std::string::npos);
    CHECK(xml.find("name1=\"fA\"") != std::string::npos);
    CHECK(xml.find("name2=\"fB\"") != std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getRxnType() == NFcore::ReactionClass::DOR2_RXN);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(1.0));
    delete system;
}

TEST_CASE("NFsim XML bridge reads legacy composite DOR2 rate laws") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
    B() 1
end seed species
begin observables
    Molecules atotal A()
    Molecules btotal B()
end observables
begin functions
    fA(x) = atotal(x)
    fB(y) = btotal(y)
end functions
begin reaction rules
    A%x() + B%y() -> A%x() + B%y() fA(x)*fB(y)
end reaction rules
)BNG");

    REQUIRE(model != nullptr);
    auto xml = bng::io::XmlWriter::write(*model);
    const auto rateStart = xml.find("        <RateLaw id=\"RR1_RateLaw\"");
    REQUIRE(rateStart != std::string::npos);
    const std::string rateEndMarker = "        </RateLaw>\n";
    const auto rateEnd = xml.find(rateEndMarker, rateStart);
    REQUIRE(rateEnd != std::string::npos);
    const std::string legacyRate = R"XML(        <RateLaw id="RR1_RateLaw" type="Function" name="_rateLaw1" totalrate="0">
          <ListOfArguments>
            <Argument id="x" type="ObjectReference" value="RR1_RP1_M1"/>
            <Argument id="y" type="ObjectReference" value="RR1_RP2_M1"/>
          </ListOfArguments>
        </RateLaw>
)XML";
    xml.replace(rateStart, rateEnd + rateEndMarker.size() - rateStart, legacyRate);

    const auto functionsEnd = xml.find("    </ListOfFunctions>");
    REQUIRE(functionsEnd != std::string::npos);
    const std::string legacyComposite = R"XML(      <Function id="_rateLaw1">
        <ListOfArguments>
          <Argument id="x"/>
          <Argument id="y"/>
        </ListOfArguments>
        <ListOfReferences>
          <Reference name="fA" type="Function"/>
          <Reference name="fB" type="Function"/>
          <Reference name="x" type="Local"/>
          <Reference name="y" type="Local"/>
        </ListOfReferences>
        <Expression>fA(x)*fB(y)</Expression>
      </Function>
)XML";
    xml.insert(functionsEnd, legacyComposite);

    const auto token = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto xmlPath = std::filesystem::temp_directory_path() /
                         ("bng3-legacy-dor2-" + std::to_string(token) + ".xml");
    std::ofstream xmlFile(xmlPath);
    REQUIRE(xmlFile.good());
    xmlFile << xml;
    xmlFile.close();

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::initializeFromXML(
        xmlPath.string(), false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getRxnType() == NFcore::ReactionClass::DOR2_RXN);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(1.0));
    delete system;

    std::error_code error;
    std::filesystem::remove(xmlPath, error);
}

TEST_CASE("NFsim XML bridge preserves bounded FunctionProduct rates") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
    B() 1
end seed species
begin observables
    Molecules atotal A()
    Molecules btotal B()
end observables
begin functions
    fA(x) = atotal(x)
    fB(y) = btotal(y)
end functions
begin reaction rules
    A()%x + B()%y -> A()%x + B()%y FunctionProduct("fA(x)", "fB(y)")
end reaction rules
)BNG");

    REQUIRE(model != nullptr);
    const auto xml = bng::io::XmlWriter::write(*model);
    CHECK(xml.find("type=\"FunctionProduct\"") != std::string::npos);
    CHECK(xml.find("name1=\"fA\"") != std::string::npos);
    CHECK(xml.find("name2=\"fB\"") != std::string::npos);
    CHECK(xml.find("<ListOfArguments1>") != std::string::npos);
    CHECK(xml.find("<ListOfArguments2>") != std::string::npos);

    int suggestedTraversalLimit = 0;
    auto* system = NFinput::initializeFromModel(
        static_cast<void*>(model.get()), false, 100, false, suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    REQUIRE(system->getAllReactions().size() == 1);
    CHECK(system->getReaction(0)->getRxnType() == NFcore::ReactionClass::DOR2_RXN);
    system->prepareForSimulation();
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(1.0));
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

TEST_CASE("NFsim AST adapter retains materialized expansion for non-factorized contexts") {
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
    A(b!1).A(c!2).B(a!1).C(x!2) Gcontext
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

TEST_CASE("NFsim energy function exposes compact binding context") {
    NFcore::EnergyFunction energy(0.5, 1.0);

    NFcore::EnergyPatternInfo pattern;
    pattern.id = "A_context_B";
    pattern.energyValue = 2.0;

    NFcore::EpMolecule moleculeA;
    moleculeA.typeName = "A";
    moleculeA.xmlId = "a";
    moleculeA.components.push_back({"b", "b", true, ""});
    moleculeA.components.push_back({"c", "c", true, ""});

    NFcore::EpMolecule moleculeB;
    moleculeB.typeName = "B";
    moleculeB.xmlId = "b";
    moleculeB.components.push_back({"a", "a", true, ""});

    NFcore::EpMolecule moleculeC;
    moleculeC.typeName = "C";
    moleculeC.xmlId = "c";
    moleculeC.components.push_back({"x", "x", true, ""});

    pattern.molecules = {moleculeA, moleculeB, moleculeC};
    pattern.bonds.push_back({0, 0, 1, 0});
    pattern.bonds.push_back({0, 1, 2, 0});
    energy.addEnergyPattern(pattern);

    NFcore::EnergyBindingContext context;
    REQUIRE(energy.getBindingContext("A", "b", "B", "a", context));
    CHECK(context.baseEnergy == Catch::Approx(0.0));
    REQUIRE(context.conditions.size() == 1);
    CHECK(context.conditions.front().reactantIdx == 0);
    CHECK(context.conditions.front().molType == "A");
    CHECK(context.conditions.front().compName == "c");
    CHECK(context.conditions.front().partnerType == "C");
    CHECK(context.conditions.front().partnerComp == "x");
    REQUIRE(context.conditionalTerms.size() == 1);
    CHECK(context.conditionalTerms.front().energyValue == Catch::Approx(2.0));
    CHECK(context.conditionalTerms.front().conditionMask == 1);
}

TEST_CASE("NFsim energy function rejects non-factorized compact contexts") {
    NFcore::EnergyFunction energy(0.5, 1.0);

    NFcore::EnergyPatternInfo pattern;
    pattern.id = "A_duplicate_context_B";
    pattern.energyValue = 1.0;

    NFcore::EpMolecule firstA;
    firstA.typeName = "A";
    firstA.xmlId = "a1";
    firstA.components.push_back({"b", "b", true, ""});

    NFcore::EpMolecule secondA;
    secondA.typeName = "A";
    secondA.xmlId = "a2";
    secondA.components.push_back({"c", "c", true, ""});

    NFcore::EpMolecule moleculeB;
    moleculeB.typeName = "B";
    moleculeB.xmlId = "b";
    moleculeB.components.push_back({"a", "a1", true, ""});

    NFcore::EpMolecule moleculeC;
    moleculeC.typeName = "C";
    moleculeC.xmlId = "c";
    moleculeC.components.push_back({"x", "x", true, ""});

    pattern.molecules = {firstA, secondA, moleculeB, moleculeC};
    pattern.bonds.push_back({0, 0, 2, 0});
    pattern.bonds.push_back({1, 0, 3, 0});
    energy.addEnergyPattern(pattern);

    NFcore::EnergyBindingContext context;
    CHECK_FALSE(energy.getBindingContext("A", "b", "B", "a", context));
    CHECK(context.conditionalTerms.empty());
}

TEST_CASE("NFsim AST adapter uses compact factorized energy evaluation") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
    Gcontext 1.0
    RT 1.0
end parameters
begin molecule types
    A(b,c,d)
    B(a)
    C(x)
    D(x)
end molecule types
begin seed species
    A(b,c!1,d!2).C(x!1).D(x!2) 1
    A(b,c!3).C(x!3) 1
    A(b) 1
    B(a) 1
end seed species
begin energy patterns
    A(b!1,c!2,d!3).B(a!1).C(x!2).D(x!3) Gcontext
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
    REQUIRE(system->getAllReactions().size() == 2);
    CHECK(system->getReaction(0)->getRxnType() == NFcore::ReactionClass::DOR_RXN);
    auto* compactReaction =
        dynamic_cast<NFcore::EnergyRxnClass*>(system->getReaction(0));
    REQUIRE(compactReaction != nullptr);
    CHECK(compactReaction->usesIncrementalMembership());
    CHECK(compactReaction->supportsSparseSelection());
    CHECK(compactReaction->membershipDecisionIsTypeInvariant());
    REQUIRE(compactReaction->getCompactPartnerPool() != nullptr);
    system->turnOff_OnTheFlyObs();
    CHECK(compactReaction->canUseDirectProductList());
    NFcore::IncrementalMembershipChange membershipChange;
    REQUIRE(compactReaction->getIncrementalMembershipChange(membershipChange));
    CHECK(membershipChange.moleculeType1 == system->getMoleculeTypeByName("A"));
    CHECK(membershipChange.componentIndex1 ==
          system->getMoleculeTypeByName("A")->getCompIndexFromName("b"));
    CHECK(membershipChange.isBoundAfter1);
    CHECK(membershipChange.moleculeType2 == system->getMoleculeTypeByName("B"));
    CHECK(membershipChange.componentIndex2 ==
          system->getMoleculeTypeByName("B")->getCompIndexFromName("a"));
    CHECK(membershipChange.isBoundAfter2);
    int reactionCenterComponent = -1;
    std::uint64_t contextComponentMask = 0;
    unsigned int minimumContextComponents = 0;
    REQUIRE(compactReaction->getCompactMembershipIndexInfo(
        0, reactionCenterComponent, contextComponentMask,
        minimumContextComponents));
    CHECK(reactionCenterComponent == membershipChange.componentIndex1);
    const int contextC = system->getMoleculeTypeByName("A")
                             ->getCompIndexFromName("c");
    const int contextD = system->getMoleculeTypeByName("A")
                             ->getCompIndexFromName("d");
    CHECK((contextComponentMask & (std::uint64_t(1) << contextC)) != 0);
    CHECK((contextComponentMask & (std::uint64_t(1) << contextD)) != 0);
    CHECK(minimumContextComponents >= 1);
    auto* weightedMolecule = system->getMoleculeTypeByName("A")->getMolecule(0);
    auto* partnerMolecule = system->getMoleculeTypeByName("B")->getMolecule(0);
    auto* indirectMolecule = system->getMoleculeTypeByName("C")->getMolecule(0);
    REQUIRE(weightedMolecule != nullptr);
    REQUIRE(partnerMolecule != nullptr);
    REQUIRE(indirectMolecule != nullptr);
    CHECK(compactReaction->shouldUpdateMembership(
        weightedMolecule, compactReaction, true));
    CHECK(compactReaction->shouldUpdateMembership(
        partnerMolecule, compactReaction, true));
    CHECK_FALSE(compactReaction->shouldUpdateMembership(
        indirectMolecule, compactReaction, true));
    CHECK_FALSE(compactReaction->shouldUpdateMembership(
        weightedMolecule, compactReaction, false));
    CHECK(compactReaction->shouldUpdateMembershipForChange(
        weightedMolecule, membershipChange));
    CHECK(compactReaction->shouldUpdateMembershipForChange(
        partnerMolecule, membershipChange));
    CHECK_FALSE(compactReaction->shouldUpdateMembershipForChange(
        indirectMolecule, membershipChange));
    NFcore::IncrementalMembershipChange contextChange = membershipChange;
    contextChange.componentIndex1 = contextC;
    contextChange.isBoundAfter1 = true;
    CHECK(compactReaction->shouldUpdateMembershipForChange(
        weightedMolecule, contextChange));
    CHECK(compactReaction->canSkipIndirectMembership(compactReaction));
    CHECK(compactReaction->getCompactPartnerPool()->getRegisteredReactions().size() == 1);
    CHECK(compactReaction->getCompactPartnerPool()->getRegisteredReactions().front() == compactReaction);

    system->prepareForSimulation();
    CHECK(compactReaction->getCompactPartnerPool()->size() == 1);
    CHECK(system->getReaction(0)->get_a() == Catch::Approx(2.0 + std::exp(-0.5)));
    CHECK(system->getReaction(1)->get_a() == Catch::Approx(0.0));

    compactReaction->setUseRuleMonkey(true);
    CHECK(compactReaction->update_a() == Catch::Approx(2.0 + std::exp(-0.5)));
    compactReaction->setUseRuleMonkey(false);
    compactReaction->fire(0.1);
    CHECK_FALSE(system->isDeferringMembershipPropensityUpdates());
    int directWeightedCount = 0;
    for (int i = 0; i < system->getMoleculeTypeByName("A")->getMoleculeCount(); ++i)
        directWeightedCount += compactReaction->isDirectProductMolecule(
            system->getMoleculeTypeByName("A")->getMolecule(i)) ? 1 : 0;
    CHECK(directWeightedCount == 1);
    CHECK(compactReaction->isDirectProductMolecule(
        system->getMoleculeTypeByName("B")->getMolecule(0)));
    for (int i = 0; i < system->getMoleculeTypeByName("C")->getMoleculeCount(); ++i)
        CHECK_FALSE(compactReaction->isDirectProductMolecule(
            system->getMoleculeTypeByName("C")->getMolecule(i)));
    for (int i = 0; i < system->getMoleculeTypeByName("D")->getMoleculeCount(); ++i)
        CHECK_FALSE(compactReaction->isDirectProductMolecule(
            system->getMoleculeTypeByName("D")->getMolecule(i)));
    delete system;
}

TEST_CASE("NFsim compact energy partner memberships avoid mapping storage") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
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
    A(b) 1
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
    auto* aType = system->getMoleculeTypeByName("A");
    auto* bType = system->getMoleculeTypeByName("B");
    REQUIRE(aType != nullptr);
    REQUIRE(bType != nullptr);
    REQUIRE(aType->getReactionCount() == 2);
    REQUIRE(bType->getReactionCount() == 1);

    CHECK(aType->getReactionMappingCount() == 2);
    CHECK(aType->getReactionMappingIndex(0) >= 0);
    CHECK(aType->getReactionMappingIndex(1) >= 0);
    CHECK(bType->getReactionMappingCount() == 0);
    CHECK(bType->getReactionMappingIndex(0) == -1);

    system->prepareForSimulation();
    auto* partner = bType->getMolecule(0);
    REQUIRE(partner != nullptr);
    CHECK(partner->getRxnListMappingId(0) == -1);
    delete system;
}

TEST_CASE("NFsim compact energy caches multi-term factors") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
    Gc 1.0
    Gd 2.0
    RT 1.0
end parameters
begin molecule types
    A(b,c,d)
    B(a)
    C(x)
    D(x)
end molecule types
begin seed species
    A(b,c!1,d!2).C(x!1).D(x!2) 1
    A(b,c!3).C(x!3) 1
    A(b) 1
    B(a) 1
end seed species
begin energy patterns
    A(b!1,c!2).B(a!1).C(x!2) Gc
    A(b!1,d!2).B(a!1).D(x!2) Gd
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
    REQUIRE(system->getAllReactions().size() == 2);
    auto* compactReaction =
        dynamic_cast<NFcore::EnergyRxnClass*>(system->getReaction(0));
    REQUIRE(compactReaction != nullptr);
    REQUIRE(compactReaction->usesIncrementalMembership());
    system->turnOff_OnTheFlyObs();
    REQUIRE(compactReaction->canUseDirectProductList());
    system->prepareForSimulation();
    CHECK(compactReaction->get_a() == Catch::Approx(
        1.0 + std::exp(-0.5) + std::exp(-1.5)));
    delete system;
}

TEST_CASE("NFsim compact energy refreshes rate factor after endpoint change") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
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
    A(b) 1
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
    auto* reaction = dynamic_cast<NFcore::EnergyRxnClass*>(
        system->getReaction(0));
    REQUIRE(reaction != nullptr);
    auto* aType = system->getMoleculeTypeByName("A");
    REQUIRE(aType != nullptr);
    auto* weighted = aType->getMolecule(0);
    REQUIRE(weighted != nullptr);

    system->prepareForSimulation();
    const int reactionIndex = aType->getRxnIndex(reaction, 0);
    const int mappingId = weighted->getRxnListMappingId(reactionIndex);
    REQUIRE(mappingId >= 0);
    CHECK(reaction->get_a() == Catch::Approx(1.0 + std::exp(-0.5)));

    const double oldA = reaction->get_a();
    NFcore::Molecule::unbind(weighted, aType->getCompIndexFromName("c"));
    reaction->notifyRateFactorChange(weighted, 0, mappingId);
    const double newA = reaction->update_a();
    system->update_A_tot(reaction, oldA, newA);

    CHECK(newA == Catch::Approx(2.0));
    CHECK(reaction->getCompactPartnerPoolCoefficient() == Catch::Approx(2.0));
    CHECK(reaction->get_a() == Catch::Approx(newA));
    delete system;
}

TEST_CASE("NFsim compact reverse energy uses the weighted propensity factor") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
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
    REQUIRE(system->getAllReactions().size() == 2);
    auto* forward = dynamic_cast<NFcore::EnergyRxnClass*>(
        system->getReaction(0));
    auto* reverse = dynamic_cast<NFcore::EnergyRxnClass*>(
        system->getReaction(1));
    REQUIRE(forward != nullptr);
    REQUIRE(reverse != nullptr);

    system->turnOff_OnTheFlyObs();
    system->prepareForSimulation();
    CHECK(forward->get_a() == Catch::Approx(std::exp(-0.5)));
    CHECK(reverse->get_a() == Catch::Approx(0.0));

    forward->fire(0.0);

    CHECK(reverse->update_a() == Catch::Approx(std::exp(0.5)));
    CHECK(reverse->get_a() == Catch::Approx(std::exp(0.5)));
    delete system;
}

TEST_CASE("NFsim compact partner refresh preserves mixed reaction memberships") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
    Gcontext 1.0
    RT 1.0
end parameters
begin molecule types
    A(b,c)
    B(a,u)
    C(x)
    D(y)
end molecule types
begin seed species
    A(b,c!1).C(x!1) 1
    A(b) 1
    B(a) 2
    C(x) 1
    D(y) 1
end seed species
begin energy patterns
    A(b!1,c!2).B(a!1).C(x!2) Gcontext
end energy patterns
begin reaction rules
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    B(u) + D(y) -> B(u!1).D(y!1) 1
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    std::vector<NFcore::EnergyRxnClass*> compactReactions;
    NFcore::ReactionClass* ordinaryReaction = nullptr;
    for (auto* reaction : system->getAllReactions()) {
        auto* energyReaction = dynamic_cast<NFcore::EnergyRxnClass*>(reaction);
        if (energyReaction != nullptr &&
                energyReaction->getCompactPartnerPool() != nullptr)
            compactReactions.push_back(energyReaction);
        else if (energyReaction == nullptr)
            ordinaryReaction = reaction;
    }
    REQUIRE(compactReactions.size() == 2);
    REQUIRE(ordinaryReaction != nullptr);

    system->turnOff_OnTheFlyObs();
    system->prepareForSimulation();
    auto* bType = system->getMoleculeTypeByName("B");
    auto* cType = system->getMoleculeTypeByName("C");
    REQUIRE(bType != nullptr);
    REQUIRE(cType != nullptr);
    auto* partner = bType->getMolecule(0);
    NFcore::Molecule* freeContext = nullptr;
    const int contextComponent = cType->getCompIndexFromName("x");
    for (int i = 0; i < cType->getMoleculeCount(); ++i) {
        auto* candidate = cType->getMolecule(i);
        if (candidate->isBindingSiteOpen(contextComponent)) {
            freeContext = candidate;
            break;
        }
    }
    REQUIRE(partner != nullptr);
    REQUIRE(freeContext != nullptr);
    REQUIRE(compactReactions.front()->getCompactPartnerPool() != nullptr);
    CHECK(compactReactions.front()->getCompactPartnerPool()->size() == 2);
    CHECK(compactReactions.back()->getCompactPartnerPool() ==
          compactReactions.front()->getCompactPartnerPool());
    CHECK(ordinaryReaction->get_a() == Catch::Approx(2.0));

    const double ordinaryBefore = ordinaryReaction->get_a();
    NFcore::Molecule::bind(partner, "a", freeContext, "x");
    bType->updateRxnMembership(partner);

    CHECK(compactReactions.front()->getCompactPartnerPool()->size() == 1);
    CHECK(compactReactions.back()->get_a() == Catch::Approx(
        compactReactions.front()->get_a()));
    CHECK(ordinaryReaction->get_a() == Catch::Approx(ordinaryBefore));
    delete system;
}

TEST_CASE("NFsim compact energy stale binding is a null event") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
    Gcontext 1.0
    RT 1.0
end parameters
begin molecule types
    A(b,c)
    B(a)
    C(x)
end molecule types
begin seed species
    A(b,c) 1
    B(a) 1
    C(x) 1
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
    auto* compactReaction =
        dynamic_cast<NFcore::EnergyRxnClass*>(system->getReaction(0));
    REQUIRE(compactReaction != nullptr);
    system->turnOff_OnTheFlyObs();
    system->prepareForSimulation();

    auto* aType = system->getMoleculeTypeByName("A");
    auto* bType = system->getMoleculeTypeByName("B");
    auto* cType = system->getMoleculeTypeByName("C");
    REQUIRE(aType != nullptr);
    REQUIRE(bType != nullptr);
    REQUIRE(cType != nullptr);
    auto* a = aType->getMolecule(0);
    auto* b = bType->getMolecule(0);
    auto* c = cType->getMolecule(0);
    REQUIRE(a != nullptr);
    REQUIRE(b != nullptr);
    REQUIRE(c != nullptr);

    /* Simulate a concurrent endpoint change after membership selection.  The
     * stale compact mapping must retain BindingTransform's null-event
     * semantics and must not create an A-B bond. */
    const int aBindingComponent = aType->getCompIndexFromName("b");
    const int bBindingComponent = bType->getCompIndexFromName("a");
    NFcore::Molecule::bind(a, aBindingComponent, c, 0);
    NFcore::System::NULL_EVENT_COUNTER = 0;
    compactReaction->fire(0.0);

    CHECK(NFcore::System::NULL_EVENT_COUNTER == 1);
    CHECK(a->getBondedMolecule(aBindingComponent) == c);
    CHECK_FALSE(b->isBindingSiteBonded(bBindingComponent));
    CHECK_FALSE(a->getBondedMolecule(aBindingComponent) == b);

    NFcore::Molecule::unbind(a, aBindingComponent);
    delete system;
}

TEST_CASE("NFsim compact partner pool batches shared propensity changes") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
    Gcontext 1.0
    RT 1.0
end parameters
begin molecule types
    A(b,c,d)
    B(a)
    C(x)
    D(x)
end molecule types
begin seed species
    A(b,c!1,d!2).C(x!1).D(x!2) 1
    A(b,c!3).C(x!3) 1
    A(b) 1
    B(a) 2
    C(x) 1
    D(x) 1
end seed species
begin energy patterns
    A(b!1,c!2,d!3).B(a!1).C(x!2).D(x!3) Gcontext
end energy patterns
begin reaction rules
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);

    std::vector<NFcore::EnergyRxnClass*> compactReactions;
    for (auto* reaction : system->getAllReactions()) {
        auto* energyReaction = dynamic_cast<NFcore::EnergyRxnClass*>(reaction);
        if (energyReaction != nullptr &&
                energyReaction->getCompactPartnerPool() != nullptr)
            compactReactions.push_back(energyReaction);
    }
    REQUIRE(compactReactions.size() == 2);
    auto* pool = compactReactions.front()->getCompactPartnerPool();
    REQUIRE(pool != nullptr);
    CHECK(compactReactions.back()->getCompactPartnerPool() == pool);
    CHECK(pool->getRegisteredReactions().size() == 2);

    system->prepareForSimulation();
    REQUIRE(pool->size() == 2);
    auto allReactions = system->getAllReactions();
    auto sumPropensities = [&]() {
        double total = 0.0;
        for (auto* reaction : system->getAllReactions())
            total += reaction->get_a();
        return total;
    };

    auto* bType = system->getMoleculeTypeByName("B");
    auto* cType = system->getMoleculeTypeByName("C");
    REQUIRE(bType != nullptr);
    REQUIRE(cType != nullptr);
    auto* partner = bType->getMolecule(0);
    auto* context = static_cast<NFcore::Molecule*>(nullptr);
    const int contextComponent = cType->getCompIndexFromName("x");
    for (int i = 0; i < cType->getMoleculeCount(); ++i) {
        auto* candidate = cType->getMolecule(i);
        if (candidate->isBindingSiteOpen(contextComponent)) {
            context = candidate;
            break;
        }
    }
    REQUIRE(partner != nullptr);
    REQUIRE(context != nullptr);

    const int deferredOldPoolSize = pool->size();
    const double deferredInitialPropensity = sumPropensities();
    system->beginDeferredMembershipPropensityUpdates();
    CHECK(system->isDeferringMembershipPropensityUpdates());
    NFcore::Molecule::bind(partner, "a", context, "x");
    bType->updateRxnMembership(partner);
    CHECK(pool->size() == deferredOldPoolSize - 1);
    system->endDeferredMembershipPropensityUpdates();
    CHECK_FALSE(system->isDeferringMembershipPropensityUpdates());
    CHECK(sumPropensities() == Catch::Approx(
        deferredInitialPropensity * pool->size() / deferredOldPoolSize));

    const int deferredReboundPoolSize = pool->size();
    NFcore::Molecule::unbind(partner, bType->getCompIndexFromName("a"));
    system->beginDeferredMembershipPropensityUpdates();
    bType->updateRxnMembership(partner);
    CHECK(pool->size() == deferredReboundPoolSize + 1);
    system->endDeferredMembershipPropensityUpdates();
    CHECK_FALSE(system->isDeferringMembershipPropensityUpdates());
    CHECK(sumPropensities() == Catch::Approx(deferredInitialPropensity));

    NFcore::DirectSelector selector(allReactions, system);
    CHECK(selector.getAtot() == Catch::Approx(sumPropensities()));

    const int oldPoolSize = pool->size();
    NFcore::Molecule::bind(partner, "a", context, "x");
    bType->updateRxnMembership(partner);

    CHECK(pool->size() == 1);
    selector.updateCompactPartnerPoolBatch(
        pool->getRegisteredReactions(), oldPoolSize, pool->size(), 0);
    CHECK(selector.getAtot() == Catch::Approx(sumPropensities()));

    const int reboundPoolSize = pool->size();
    const int partnerComponent = bType->getCompIndexFromName("a");
    NFcore::Molecule::unbind(partner, partnerComponent);
    bType->updateRxnMembership(partner);
    CHECK(pool->size() == 2);
    selector.updateCompactPartnerPoolBatch(
        pool->getRegisteredReactions(), reboundPoolSize, pool->size(), 0);
    CHECK(selector.getAtot() == Catch::Approx(sumPropensities()));

    const int removedPoolSize = pool->size();
    bType->removeFromRxns(partner);
    CHECK(pool->size() == 1);
    selector.updateCompactPartnerPoolBatch(
        pool->getRegisteredReactions(), removedPoolSize, pool->size(), 0);
    CHECK(selector.getAtot() == Catch::Approx(sumPropensities()));

    auto* aType = system->getMoleculeTypeByName("A");
    REQUIRE(aType != nullptr);
    auto* weighted = aType->getMolecule(0);
    REQUIRE(weighted != nullptr);
    const int weightedComponent = aType->getCompIndexFromName("b");
    REQUIRE(weighted->isBindingSiteOpen(weightedComponent));
    std::vector<double> oldPropensities;
    for (auto* reaction : allReactions)
        oldPropensities.push_back(reaction->get_a());
    NFcore::Molecule::bind(weighted, weightedComponent, context,
                           contextComponent);
    system->beginDeferredMembershipPropensityUpdates();
    aType->updateRxnMembership(weighted);
    system->endDeferredMembershipPropensityUpdates();
    CHECK_FALSE(system->isDeferringMembershipPropensityUpdates());
    selector.updateBatch(allReactions, oldPropensities);
    CHECK(selector.getAtot() == Catch::Approx(sumPropensities()));

    delete system;
}

TEST_CASE("NFsim compact selector preserves seeded order across membership refresh") {
    const std::string modelText = R"(
begin parameters
    phi 0.5
    Gcontext 1.0
    RT 1.0
end parameters
begin molecule types
    A(b,c,d)
    B(a)
    C(x)
    D(x)
end molecule types
begin seed species
    A(b,c!1,d!2).C(x!1).D(x!2) 1
    A(b,c!3).C(x!3) 1
    A(b) 1
    B(a) 2
    C(x) 1
    D(x) 1
end seed species
begin energy patterns
    A(b!1,c!2,d!3).B(a!1).C(x!2).D(x!3) Gcontext
end energy patterns
begin reaction rules
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
end reaction rules
)";

    auto model = bng::parser::parseModel(modelText);
    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    system->prepareForSimulation();

    auto allReactions = system->getAllReactions();
    REQUIRE(allReactions.size() == 18);
    for (auto* reaction : allReactions) {
        auto* compactReaction = dynamic_cast<NFcore::EnergyRxnClass*>(reaction);
        REQUIRE(compactReaction != nullptr);
        CHECK(compactReaction->supportsSparseSelection());
    }

    auto sumPropensities = [&]() {
        double total = 0.0;
        for (auto* reaction : allReactions)
            total += reaction->get_a();
        return total;
    };
    NFcore::DirectSelector selector(allReactions, system);
    const double initialTotal = sumPropensities();
    CHECK(initialTotal > 0.0);
    CHECK(selector.getAtot() == Catch::Approx(initialTotal));

    system->seedRNG(17);
    NFcore::NfsimRNG expectedInitialRng(17);
    const double initialDraw = expectedInitialRng.random(initialTotal);
    double expectedPrefix = 0.0;
    double expectedPreviousPrefix = 0.0;
    std::size_t expectedIndex = allReactions.size();
    for (std::size_t i = 0; i < allReactions.size(); ++i) {
        expectedPrefix += allReactions[i]->get_a();
        if (initialDraw <= expectedPrefix) {
            expectedIndex = i;
            break;
        }
        expectedPreviousPrefix = expectedPrefix;
    }
    REQUIRE(expectedIndex < allReactions.size());
    NFcore::ReactionClass* selected = nullptr;
    const double initialResidual = selector.getNextReactionClass(selected);
    CHECK(selected == allReactions[expectedIndex]);
    CHECK(initialResidual == Catch::Approx(
        initialDraw - expectedPreviousPrefix));

    std::vector<double> oldPropensities;
    for (auto* reaction : allReactions)
        oldPropensities.push_back(reaction->get_a());
    auto* compactReaction = dynamic_cast<NFcore::EnergyRxnClass*>(
        allReactions.front());
    REQUIRE(compactReaction != nullptr);
    REQUIRE(compactReaction->get_a() > 0.0);
    compactReaction->fire(0.0);

    const double refreshedTotal = sumPropensities();
    REQUIRE(refreshedTotal > 0.0);
    selector.updateBatch(allReactions, oldPropensities);
    CHECK(selector.getAtot() == Catch::Approx(refreshedTotal));

    system->seedRNG(19);
    NFcore::NfsimRNG expectedRefreshedRng(19);
    const double refreshedDraw = expectedRefreshedRng.random(refreshedTotal);
    expectedPrefix = 0.0;
    expectedPreviousPrefix = 0.0;
    expectedIndex = allReactions.size();
    for (std::size_t i = 0; i < allReactions.size(); ++i) {
        expectedPrefix += allReactions[i]->get_a();
        if (refreshedDraw <= expectedPrefix) {
            expectedIndex = i;
            break;
        }
        expectedPreviousPrefix = expectedPrefix;
    }
    REQUIRE(expectedIndex < allReactions.size());
    selected = nullptr;
    const double refreshedResidual = selector.getNextReactionClass(selected);
    CHECK(selected == allReactions[expectedIndex]);
    CHECK(refreshedResidual == Catch::Approx(
        refreshedDraw - expectedPreviousPrefix));

    delete system;
}

TEST_CASE("NFsim compact membership refresh preserves unrelated partner rules") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    phi 0.5
    G 1.0
    RT 1.0
end parameters
begin molecule types
    A(b,c)
    B(a,u,v,w)
    C(x)
end molecule types
begin seed species
    A(b,c!1).C(x!1) 4
    B(a,u,v,w) 1
end seed species
begin energy patterns
    A(b!1,c!2).B(a!1).C(x!2) G
    A(b!1,c!2).B(u!1).C(x!2) G
    A(b!1,c!2).B(v!1).C(x!2) G
    A(b!1,c!2).B(w!1).C(x!2) G
end energy patterns
begin reaction rules
    A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi,0)
    A(b) + B(u) <-> A(b!1).B(u!1) Arrhenius(phi,0)
    A(b) + B(v) <-> A(b!1).B(v!1) Arrhenius(phi,0)
    A(b) + B(w) <-> A(b!1).B(w!1) Arrhenius(phi,0)
end reaction rules
)");

    REQUIRE(model != nullptr);
    int suggestedTraversalLimit = 0;
    auto* system = NFinput::buildSystemFromAst(*model, false, 100, false,
                                                suggestedTraversalLimit);
    REQUIRE(system != nullptr);
    const auto allReactions = system->getAllReactions();
    REQUIRE(allReactions.size() == 8);

    std::vector<NFcore::EnergyRxnClass*> forwardReactions;
    std::vector<NFcore::EnergyRxnClass*> reverseReactions;
    for (auto* reaction : allReactions) {
        auto* energyReaction = dynamic_cast<NFcore::EnergyRxnClass*>(reaction);
        REQUIRE(energyReaction != nullptr);
        CHECK(energyReaction->usesIncrementalMembership());
        CHECK(energyReaction->membershipDecisionIsTypeInvariant());
        if (energyReaction->getCompactPartnerPool() != nullptr)
            forwardReactions.push_back(energyReaction);
        else
            reverseReactions.push_back(energyReaction);
    }
    REQUIRE(forwardReactions.size() == 4);
    REQUIRE(reverseReactions.size() == 4);

    system->turnOff_OnTheFlyObs();
    system->prepareForSimulation();
    std::vector<double> initialForwardPropensities;
    for (auto* reaction : forwardReactions) {
        REQUIRE(reaction->get_a() > 0.0);
        initialForwardPropensities.push_back(reaction->get_a());
    }
    for (auto* reaction : reverseReactions)
        CHECK(reaction->get_a() == Catch::Approx(0.0));

    auto* firedReaction = forwardReactions.front();
    firedReaction->fire(0.0);

    CHECK(firedReaction->get_a() == Catch::Approx(0.0));
    for (std::size_t i = 1; i < forwardReactions.size(); ++i)
        CHECK(forwardReactions[i]->get_a() == Catch::Approx(
            initialForwardPropensities[i] * 0.75));
    int activeReverseCount = 0;
    for (auto* reaction : reverseReactions) {
        if (reaction->get_a() > 0.0)
            ++activeReverseCount;
    }
    CHECK(activeReverseCount == 1);

    delete system;
}
