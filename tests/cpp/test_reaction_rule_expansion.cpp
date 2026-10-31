#include <catch2/catch_test_macros.hpp>
#include <stdexcept>
#include <string>
#include <utility>

#include "compile/CompiledModel.hpp"
#include "compile/Document.hpp"
#include "compile/PatternLowering.hpp"
#include "engine/NetworkRulePlan.hpp"
#include "parser/BNGAstVisitor.hpp"
#include "engine/NetworkGenerator.hpp"

using namespace bng;

static std::unique_ptr<ast::Model> parseModel(const std::string& bngl) {
    return parser::parseModel(bngl);
}

static std::unique_ptr<ast::Model> modelWithMaxIter(const std::string& option) {
    return parseModel(R"(
begin molecule types
    A(s~0~1~2)
end molecule types
begin seed species
    A(s~0) 1
end seed species
begin reaction rules
    r01: A(s~0) -> A(s~1) 1
    r12: A(s~1) -> A(s~2) 1
end reaction rules
begin actions
    generate_network({max_iter=>)" + option + R"(,overwrite=>1})
end actions
)");
}

static std::unique_ptr<ast::Model> modelWithSimulationAction(
    const std::string& action, bool protocol = false) {
    std::string source = R"(
begin model
begin parameters
    N 3
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
    B() 0
end seed species
begin reaction rules
    convert: A() -> B() 0.4
end reaction rules
)";
    if (protocol) {
        source += "begin protocol\n" + action + "\nend protocol\n";
    }
    source += "end model\n";
    if (!protocol) {
        source += action + "\n";
    }
    return parseModel(source);
}

TEST_CASE("Rule expansion: execution caches are independent", "[ReactionRule]") {
    auto model = parseModel(R"(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin reaction rules
    A() -> B() 1
end reaction rules
)"
    );

    const auto& rule = model->getReactionRules().front();
    ast::SpeciesList species;
    species.add(ast::Species(
        ast::SpeciesGraph(model->getSeedSpecies().front().getGraph()), 1.0));

    auto firstState = rule.createExecutionState();
    auto secondState = rule.createExecutionState();
    ast::RxnList firstReactions;
    ast::RxnList secondReactions;
    const auto first = rule.expandRule(species, firstReactions, 0, *firstState, {}, 1, model.get());
    const auto independent = rule.expandRule(species, secondReactions, 0, *secondState, {}, 1, model.get());

    REQUIRE(first == 1);
    REQUIRE(independent == 1);
}

TEST_CASE("generate_network max_iter is compiled as a qualified typed option") {
    const auto compiledValue = [](const std::string& expression) {
        auto model = modelWithMaxIter(expression);
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto& action = generator.document().protocol().actions.front();
        REQUIRE(action.generateNetworkOptions.has_value());
        CHECK(action.arguments.at("max_iter") == expression);
        CHECK_FALSE(action.generateNetworkOptions->maxIterationsDiagnostic.has_value());
        REQUIRE(action.generateNetworkOptions->maxIterations.has_value());
        return *action.generateNetworkOptions->maxIterations;
    };

    CHECK(compiledValue("1+1") == 2);
    CHECK(compiledValue("2.5") == 2);
    CHECK(compiledValue("(1+1)*2") == 4);
    CHECK(compiledValue("1e2") == 100);
    CHECK(compiledValue("2**3") == 8);

    for (const auto& expression : {"0", "-1", "0.5", "2^3", "2**3**2",
                                   "(1/0)**0", "(1e308*1e308)**0",
                                   "-2**2", "(-2)**2", "iters", "exp(2)", "e",
                                   "9223372036854775808", "1e309"}) {
        INFO("max_iter expression: " << expression);
        auto model = modelWithMaxIter(expression);
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto& action = generator.document().protocol().actions.front();
        REQUIRE(action.generateNetworkOptions.has_value());
        CHECK_FALSE(action.generateNetworkOptions->maxIterations.has_value());
        REQUIRE(action.generateNetworkOptions->maxIterationsDiagnostic.has_value());
        CHECK(action.generateNetworkOptions->maxIterationsDiagnostic->message.find("max_iter") !=
              std::string::npos);
    }
}

TEST_CASE("ODE and SSA n_steps compile Safe-Perl exponentiation for finite actions") {
    struct Case {
        const char* action;
        bool protocol;
    };
    const Case cases[] = {
        {"simulate_ode({t_end=>1,n_steps=>2**3})", false},
        {"simulate_ssa({t_end=>1,n_steps=>2**3,seed=>1})", false},
        {"simulate({method=>\"ode\",t_end=>1,n_steps=>2**3})", true},
        {"simulate({method=>\"ssa\",t_end=>1,n_steps=>2**3,seed=>1})", true},
    };

    for (const auto& testCase : cases) {
        INFO("action: " << testCase.action);
        auto model = modelWithSimulationAction(testCase.action, testCase.protocol);
        REQUIRE(model != nullptr);
        const compile::Document document(*model);
        REQUIRE(document.protocol().actions.size() == 1);
        const auto& action = document.protocol().actions.front();
        REQUIRE(action.simulationOptions.has_value());
        CHECK(action.arguments.at("n_steps") == "2**3");
        CHECK_FALSE(action.simulationOptions->nStepsDiagnostic.has_value());
        REQUIRE(action.simulationOptions->nSteps.has_value());
        CHECK(*action.simulationOptions->nSteps == 8);
    }
}

TEST_CASE("simulation n_steps diagnostics preserve raw source and defer failure") {
    for (const auto& expression : {"2^3", "2.5", "-1", "0", "1e309",
                                   "1e30", "2**3**2"}) {
        INFO("n_steps: " << expression);
        auto model = modelWithSimulationAction(
            std::string("simulate_ode({t_end=>1,n_steps=>") + expression + "})");
        REQUIRE(model != nullptr);
        const compile::Document document(*model);
        CHECK(document.valid());
        REQUIRE(document.protocol().actions.size() == 1);
        const auto& action = document.protocol().actions.front();
        REQUIRE(action.simulationOptions.has_value());
        CHECK(action.arguments.at("n_steps") == expression);
        CHECK_FALSE(action.simulationOptions->nSteps.has_value());
        REQUIRE(action.simulationOptions->nStepsDiagnostic.has_value());
        CHECK(action.simulationOptions->nStepsDiagnostic->message.find("n_steps") !=
              std::string::npos);
        CHECK(action.simulationOptions->nStepsDiagnostic->message.find(expression) !=
              std::string::npos);
    }
}

TEST_CASE("absent n_steps stays unset and non-finite backends are not typed") {
    auto model = modelWithSimulationAction("simulate_ode({t_end=>1})");
    REQUIRE(model != nullptr);
    const compile::Document document(*model);
    REQUIRE(document.protocol().actions.size() == 1);
    REQUIRE(document.protocol().actions.front().simulationOptions.has_value());
    CHECK_FALSE(document.protocol().actions.front().simulationOptions->nSteps.has_value());
    CHECK_FALSE(document.protocol().actions.front().simulationOptions->nStepsDiagnostic.has_value());

    for (const auto& actionSource : {
             "simulate({method=>\"nf\",t_end=>1,n_steps=>2**3})",
             "simulate_pla({t_end=>1,n_steps=>2**3})",
             "simulate({method=>\"psa\",t_end=>1,n_steps=>2**3})"}) {
        INFO("action: " << actionSource);
        auto backendModel = modelWithSimulationAction(actionSource);
        REQUIRE(backendModel != nullptr);
        const compile::Document backendDocument(*backendModel);
        REQUIRE(backendDocument.protocol().actions.size() == 1);
        CHECK_FALSE(backendDocument.protocol().actions.front().simulationOptions.has_value());
    }
}

TEST_CASE("parameter-backed simulation n_steps remain execution-time values") {
    auto model = modelWithSimulationAction(
        "simulate({method=>\"ode\",t_end=>1,n_steps=>N})", true);
    REQUIRE(model != nullptr);
    const compile::Document document(*model);
    REQUIRE(document.protocol().actions.size() == 1);
    const auto& action = document.protocol().actions.front();
    REQUIRE(action.simulationOptions.has_value());
    CHECK(action.arguments.at("n_steps") == "N");
    CHECK_FALSE(action.simulationOptions->nSteps.has_value());
    CHECK_FALSE(action.simulationOptions->nStepsDiagnostic.has_value());
}

TEST_CASE("simulation time options compile finite static arithmetic") {
    const auto model = modelWithSimulationAction(
        "simulate_ode({t_start=>2**3,t_end=>1e1,n_steps=>2})");
    REQUIRE(model != nullptr);
    const compile::Document document(*model);
    REQUIRE(document.protocol().actions.size() == 1);
    const auto& action = document.protocol().actions.front();
    REQUIRE(action.simulationOptions.has_value());
    REQUIRE(action.simulationOptions->tStart.has_value());
    CHECK(*action.simulationOptions->tStart == 8.0);
    REQUIRE(action.simulationOptions->tEnd.has_value());
    CHECK(*action.simulationOptions->tEnd == 10.0);
    CHECK_FALSE(action.simulationOptions->tStartDiagnostic.has_value());
    CHECK_FALSE(action.simulationOptions->tEndDiagnostic.has_value());

    const auto defaultStart = modelWithSimulationAction(
        "simulate_ode({t_end=>1,n_steps=>2})");
    REQUIRE(defaultStart != nullptr);
    const compile::Document defaultDocument(*defaultStart);
    REQUIRE(defaultDocument.protocol().actions.front().simulationOptions.has_value());
    CHECK_FALSE(defaultDocument.protocol().actions.front().simulationOptions->tStart.has_value());
}

TEST_CASE("simulation time options defer dynamic values and invalid diagnostics") {
    const auto dynamic = modelWithSimulationAction(
        "simulate({method=>\"ode\",t_start=>N,t_end=>N+1,n_steps=>2})", true);
    REQUIRE(dynamic != nullptr);
    const compile::Document dynamicDocument(*dynamic);
    const auto& dynamicOptions =
        *dynamicDocument.protocol().actions.front().simulationOptions;
    CHECK_FALSE(dynamicOptions.tStart.has_value());
    CHECK_FALSE(dynamicOptions.tEnd.has_value());
    CHECK_FALSE(dynamicOptions.tStartDiagnostic.has_value());
    CHECK_FALSE(dynamicOptions.tEndDiagnostic.has_value());

    for (const auto& [field, expression] : {
             std::pair{"t_start", "2^3"}, std::pair{"t_start", "1e309"},
             std::pair{"t_start", "1/0"}, std::pair{"t_end", "1/0"},
             std::pair{"t_end", "1e309"}}) {
        INFO(field << " expression: " << expression);
        const auto timeArguments = std::string(field) == "t_start"
            ? std::string("t_start=>") + expression + ",t_end=>1"
            : std::string("t_start=>0,t_end=>") + expression;
        auto model = modelWithSimulationAction(
            "simulate_ode({" + timeArguments + ",n_steps=>2})");
        REQUIRE(model != nullptr);
        const compile::Document document(*model);
        CHECK(document.valid());
        const auto& options = *document.protocol().actions.front().simulationOptions;
        const auto& diagnostic = std::string(field) == "t_start"
            ? options.tStartDiagnostic
            : options.tEndDiagnostic;
        REQUIRE(diagnostic.has_value());
        CHECK(diagnostic->message.find(field) != std::string::npos);
        CHECK(diagnostic->message.find(expression) != std::string::npos);
    }
}

TEST_CASE("setParameter compiles static arithmetic while retaining dynamic values") {
    struct StaticCase {
        const char* expression;
        double expected;
        bool protocol;
    };
    const StaticCase staticCases[] = {
        {"2**3", 8.0, false},
        {"0", 0.0, false},
        {"-2", -2.0, true},
    };

    for (const auto& testCase : staticCases) {
        INFO("setParameter value: " << testCase.expression);
        auto model = modelWithSimulationAction(
            std::string("setParameter(\"N\",") + testCase.expression + ")",
            testCase.protocol);
        REQUIRE(model != nullptr);
        const compile::Document document(*model);
        REQUIRE(document.valid());
        REQUIRE(document.protocol().actions.size() == 1);
        const auto& action = document.protocol().actions.front();
        CHECK(action.scope == (testCase.protocol ? compile::ActionScope::SimulationProtocol
                                                : compile::ActionScope::Model));
        REQUIRE(action.setParameterOptions.has_value());
        CHECK(action.arguments.at("value") == testCase.expression);
        REQUIRE(action.setParameterOptions->staticValue.has_value());
        CHECK(*action.setParameterOptions->staticValue == testCase.expected);
        CHECK_FALSE(action.setParameterOptions->valueDiagnostic.has_value());
    }

    auto dynamicModel = modelWithSimulationAction("setParameter(\"N\",N)");
    REQUIRE(dynamicModel != nullptr);
    const compile::Document dynamicDocument(*dynamicModel);
    REQUIRE(dynamicDocument.protocol().actions.size() == 1);
    const auto& dynamicAction = dynamicDocument.protocol().actions.front();
    REQUIRE(dynamicAction.setParameterOptions.has_value());
    CHECK_FALSE(dynamicAction.setParameterOptions->staticValue.has_value());
    CHECK_FALSE(dynamicAction.setParameterOptions->valueDiagnostic.has_value());

    auto dynamicPowerModel = modelWithSimulationAction("setParameter(\"N\",2**N)");
    REQUIRE(dynamicPowerModel != nullptr);
    const compile::Document dynamicPowerDocument(*dynamicPowerModel);
    REQUIRE(dynamicPowerDocument.protocol().actions.size() == 1);
    const auto& dynamicPowerAction = dynamicPowerDocument.protocol().actions.front();
    REQUIRE(dynamicPowerAction.setParameterOptions.has_value());
    CHECK_FALSE(dynamicPowerAction.setParameterOptions->staticValue.has_value());
    REQUIRE(dynamicPowerAction.setParameterOptions->valueDiagnostic.has_value());
    CHECK(dynamicPowerAction.setParameterOptions->valueDiagnostic->message.find(
              "unquoted named arithmetic") != std::string::npos);
}

TEST_CASE("setParameter preserves quoted BNGL arithmetic and refuses unquoted named arithmetic") {
    auto quotedStaticModel = modelWithSimulationAction(
        "setParameter(\"N\",\"2^3\")");
    REQUIRE(quotedStaticModel != nullptr);
    const compile::Document quotedStaticDocument(*quotedStaticModel);
    REQUIRE(quotedStaticDocument.protocol().actions.size() == 1);
    const auto& quotedStaticAction = quotedStaticDocument.protocol().actions.front();
    REQUIRE(quotedStaticAction.setParameterOptions.has_value());
    CHECK(quotedStaticAction.arguments.at("value") == "\"2^3\"");
    REQUIRE(quotedStaticAction.setParameterOptions->staticValue.has_value());
    CHECK(*quotedStaticAction.setParameterOptions->staticValue == 8.0);
    CHECK_FALSE(quotedStaticAction.setParameterOptions->valueDiagnostic.has_value());

    auto quotedDynamicModel = modelWithSimulationAction(
        "setParameter(\"N\",\"2^N\")");
    REQUIRE(quotedDynamicModel != nullptr);
    const compile::Document quotedDynamicDocument(*quotedDynamicModel);
    REQUIRE(quotedDynamicDocument.protocol().actions.size() == 1);
    const auto& quotedDynamicAction = quotedDynamicDocument.protocol().actions.front();
    REQUIRE(quotedDynamicAction.setParameterOptions.has_value());
    CHECK(quotedDynamicAction.arguments.at("value") == "\"2^N\"");
    CHECK_FALSE(quotedDynamicAction.setParameterOptions->staticValue.has_value());
    CHECK_FALSE(quotedDynamicAction.setParameterOptions->valueDiagnostic.has_value());

    auto quotedChainedCaretModel = modelWithSimulationAction(
        "setParameter(\"N\",\"2^N^2\")");
    REQUIRE(quotedChainedCaretModel != nullptr);
    const compile::Document quotedChainedCaretDocument(*quotedChainedCaretModel);
    REQUIRE(quotedChainedCaretDocument.protocol().actions.size() == 1);
    const auto& quotedChainedCaretAction =
        quotedChainedCaretDocument.protocol().actions.front();
    REQUIRE(quotedChainedCaretAction.setParameterOptions.has_value());
    CHECK(quotedChainedCaretAction.arguments.at("value") == "\"2^N^2\"");
    CHECK_FALSE(quotedChainedCaretAction.setParameterOptions->staticValue.has_value());
    CHECK_FALSE(quotedChainedCaretAction.setParameterOptions->valueDiagnostic.has_value());

    auto quotedDynamicParameterBaseModel = modelWithSimulationAction(
        "setParameter(\"N\",\"-N^2\")");
    REQUIRE(quotedDynamicParameterBaseModel != nullptr);
    const compile::Document quotedDynamicParameterBaseDocument(
        *quotedDynamicParameterBaseModel);
    REQUIRE(quotedDynamicParameterBaseDocument.protocol().actions.size() == 1);
    const auto& quotedDynamicParameterBaseAction =
        quotedDynamicParameterBaseDocument.protocol().actions.front();
    REQUIRE(quotedDynamicParameterBaseAction.setParameterOptions.has_value());
    CHECK_FALSE(quotedDynamicParameterBaseAction.setParameterOptions->staticValue.has_value());
    CHECK_FALSE(
        quotedDynamicParameterBaseAction.setParameterOptions->valueDiagnostic.has_value());

    auto bareIdentifierModel = modelWithSimulationAction("setParameter(\"N\",N)");
    REQUIRE(bareIdentifierModel != nullptr);
    const compile::Document bareIdentifierDocument(*bareIdentifierModel);
    REQUIRE(bareIdentifierDocument.protocol().actions.size() == 1);
    const auto& bareIdentifierAction = bareIdentifierDocument.protocol().actions.front();
    REQUIRE(bareIdentifierAction.setParameterOptions.has_value());
    CHECK_FALSE(bareIdentifierAction.setParameterOptions->staticValue.has_value());
    CHECK_FALSE(bareIdentifierAction.setParameterOptions->valueDiagnostic.has_value());

    for (const auto& expression : {"2*N", "N+1", "2**N"}) {
        INFO("unquoted setParameter expression: " << expression);
        auto model = modelWithSimulationAction(
            std::string("setParameter(\"N\",") + expression + ")");
        REQUIRE(model != nullptr);
        const compile::Document document(*model);
        CHECK(document.valid());
        REQUIRE(document.protocol().actions.size() == 1);
        const auto& action = document.protocol().actions.front();
        REQUIRE(action.setParameterOptions.has_value());
        CHECK_FALSE(action.setParameterOptions->staticValue.has_value());
        REQUIRE(action.setParameterOptions->valueDiagnostic.has_value());
        CHECK(action.setParameterOptions->valueDiagnostic->message.find(
                  "unquoted named arithmetic") != std::string::npos);
    }
}

TEST_CASE("setParameter refuses quoted negative power bases and mixed power spellings") {
    for (const auto& testCase : {
             std::pair{"-2^N", "statically negative base"},
             std::pair{"(-2)^N", "statically negative base"},
             std::pair{"2**N^2", "mixing '^' and '**' power operators"}}) {
        INFO("quoted setParameter value: " << testCase.first);
        auto model = modelWithSimulationAction(
            std::string("setParameter(\"N\",\"") + testCase.first + "\")");
        REQUIRE(model != nullptr);
        const compile::Document document(*model);
        REQUIRE(document.protocol().actions.size() == 1);
        const auto& action = document.protocol().actions.front();
        REQUIRE(action.setParameterOptions.has_value());
        REQUIRE(action.setParameterOptions->valueDiagnostic.has_value());
        CHECK(action.setParameterOptions->valueDiagnostic->message.find(
                  testCase.second) != std::string::npos);
    }
}

TEST_CASE("setParameter refuses quoted double-star expressions unsupported at runtime") {
    for (const auto& expression : {"2**N", "2**3"}) {
        INFO("quoted setParameter value: " << expression);
        auto model = modelWithSimulationAction(
            std::string("setParameter(\"N\",\"") + expression + "\")");
        REQUIRE(model != nullptr);
        const compile::Document document(*model);
        REQUIRE(document.protocol().actions.size() == 1);
        const auto& action = document.protocol().actions.front();
        REQUIRE(action.setParameterOptions.has_value());
        REQUIRE(action.setParameterOptions->valueDiagnostic.has_value());
        CHECK(action.setParameterOptions->valueDiagnostic->message.find(
                  "quoted '**' power expressions") != std::string::npos);
    }
}

TEST_CASE("setParameter refuses quoted caret expressions outside parameter arithmetic") {
    for (const auto& expression : {
             "time^2", "t^2", "time()^2", "sqrt(N)^2",
             "TFUN([0,1],[2,4],N)^2", "N % 2^2"}) {
        INFO("quoted setParameter value: " << expression);
        auto model = modelWithSimulationAction(
            std::string("setParameter(\"N\",\"") + expression + "\")");
        REQUIRE(model != nullptr);
        const compile::Document document(*model);
        CHECK(document.valid());
        REQUIRE(document.protocol().actions.size() == 1);
        const auto& action = document.protocol().actions.front();
        REQUIRE(action.setParameterOptions.has_value());
        CHECK_FALSE(action.setParameterOptions->staticValue.has_value());
        REQUIRE(action.setParameterOptions->valueDiagnostic.has_value());
        CHECK(action.setParameterOptions->valueDiagnostic->message.find(
                  "quoted caret expressions require simple parameter arithmetic") !=
              std::string::npos);
    }
}

TEST_CASE("unused invalid setParameter values remain deferred in compiled metadata") {
    auto model = modelWithSimulationAction("setParameter(\"N\",2^N)", true);
    REQUIRE(model != nullptr);
    const compile::Document document(*model);
    CHECK(document.valid());
    REQUIRE(document.protocol().actions.size() == 1);
    const auto& action = document.protocol().actions.front();
    REQUIRE(action.setParameterOptions.has_value());
    CHECK_FALSE(action.setParameterOptions->staticValue.has_value());
    REQUIRE(action.setParameterOptions->valueDiagnostic.has_value());
    CHECK(action.arguments.at("value") == "2^N");
    CHECK(action.setParameterOptions->valueDiagnostic->message.find(
              "Safe-Perl '^' is bitwise XOR") != std::string::npos);
}

TEST_CASE("BNGL network generation uses typed max_iter and explicit native overrides") {
    auto defaultModel = parseModel(R"(
begin molecule types
    A(s~0~1~2)
end molecule types
begin seed species
    A(s~0) 1
end seed species
begin reaction rules
    r01: A(s~0) -> A(s~1) 1
    r12: A(s~1) -> A(s~2) 1
end reaction rules
)");
    REQUIRE(defaultModel != nullptr);
    engine::NetworkGenerator defaultGenerator(*defaultModel);
    const auto defaultNetwork = defaultGenerator.generate({});
    REQUIRE(defaultNetwork.species.size() == 3);
    REQUIRE(defaultNetwork.reactions.size() == 2);

    auto twoPassModel = modelWithMaxIter("1+1");
    REQUIRE(twoPassModel != nullptr);
    engine::NetworkGenerator twoPassGenerator(*twoPassModel);
    const auto twoPassNetwork = twoPassGenerator.generate({});
    REQUIRE(twoPassNetwork.species.size() == 3);
    REQUIRE(twoPassNetwork.reactions.size() == 2);

    auto onePassModel = modelWithMaxIter("1");
    REQUIRE(onePassModel != nullptr);
    engine::NetworkGenerator onePassGenerator(*onePassModel);
    const auto onePassNetwork = onePassGenerator.generate({});
    REQUIRE(onePassNetwork.species.size() == 2);
    REQUIRE(onePassNetwork.reactions.size() == 1);

    auto invalidProtocolModel = modelWithMaxIter("iters");
    REQUIRE(invalidProtocolModel != nullptr);
    engine::NetworkGenerator invalidGenerator(*invalidProtocolModel);
    try {
        (void)invalidGenerator.generate({});
        FAIL("invalid BNGL max_iter must fail before network generation");
    } catch (const std::runtime_error& error) {
        CHECK(std::string(error.what()).find("max_iter") != std::string::npos);
    }

    // This is the same native entry point used by the direct Python binding:
    // an explicit numeric override must not decode the BNGL protocol value.
    const auto overriddenNetwork = invalidGenerator.generateNative(2);
    REQUIRE(overriddenNetwork.species.size() == 3);
    REQUIRE(overriddenNetwork.reactions.size() == 2);
}

TEST_CASE("Rule expansion: pattern metadata survives reinitialization and move", "[ReactionRule]") {
    // Source-derived from akutuva21/bionetgen commit 7ee2db11: immutable
    // pattern metadata is rebuilt on initialize() and must survive moving a
    // fully initialized rule into the owning model before expansion.
    auto model = parseModel(R"(
begin parameters
    kf 1.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
end seed species
begin reaction rules
    A() -> B() kf
end reaction rules
)");

    auto rule = std::move(model->getReactionRules().front());
    model->getReactionRules().clear();
    rule.initialize();
    model->addReactionRule(std::move(rule));

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(5);

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Rule expansion: simple binding A + B -> AB", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    kf 1.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 100
    B(a) 100
end seed species
begin observables
    Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) kf
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 3);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Rule expansion: unmatched product molecules cannot discard connected context",
          "[ReactionRule][issue139]") {
    const auto generate = [](const std::string& moleculeTypes,
                             const std::string& seedSpecies,
                             const std::string& reactionRule) {
        auto model = parseModel(R"(
begin parameters
    k 1
end parameters
begin molecule types
)" + moleculeTypes + R"(
end molecule types
begin seed species
)" + seedSpecies + R"(
end seed species
begin reaction rules
)" + reactionRule + R"(
end reaction rules
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        return generator.generateNative(5);
    };

    const auto wholePatternReplacement = generate(
        "    A(x,y)\n    C(x)",
        "    A(x!1,y).C(x!1) 1",
        "    r: A(x!+) -> A(x,y) k");
    REQUIRE(wholePatternReplacement.reactions.size() == 1);
    REQUIRE(wholePatternReplacement.species.size() == 2);
    CHECK(wholePatternReplacement.species.get(1).getSpeciesGraph().toString() == "A(x,y)");

    const auto partialDifferentTypeReplacement = generate(
        "    A(x,c)\n    B(x)\n    C(c)\n    D(x)",
        "    A(x!1,c!2).B(x!1).C(c!2) 1",
        "    r: A(x!1,c!+).B(x!1) -> D(x!1).B(x!1) k");
    CHECK(partialDifferentTypeReplacement.reactions.size() == 0);
    CHECK(partialDifferentTypeReplacement.species.size() == 1);

    const auto wholeAndPartialPatterns = generate(
        "    A(x,y)\n    C(x)\n    B(z,c)\n    D(z)\n    E(c)\n    F(z)",
        "    A(x!1,y).C(x!1) 1\n"
        "    B(z!1,c!2).D(z!1).E(c!2) 1",
        "    whole: A(x!+) -> A(x,y) k\n"
        "    partial: B(z!1,c!+).D(z!1) -> F(z!1).D(z!1) k");
    REQUIRE(wholeAndPartialPatterns.reactions.size() == 1);
    CHECK(wholeAndPartialPatterns.species.size() == 3);
    bool sawWholeProduct = false;
    bool sawPartialReplacement = false;
    for (std::size_t i = 0; i < wholeAndPartialPatterns.species.size(); ++i) {
        const auto graph = wholeAndPartialPatterns.species.get(i).getSpeciesGraph().toString();
        sawWholeProduct = sawWholeProduct || graph == "A(x,y)";
        sawPartialReplacement = sawPartialReplacement || graph.find("F(") != std::string::npos;
    }
    CHECK(sawWholeProduct);
    CHECK_FALSE(sawPartialReplacement);

    const auto explicitDeleteMoleculesWholePattern = generate(
        "    A(x)\n    B(x)\n    C(x)",
        "    A(x!1).C(x!1) 1",
        "    r: A(x!+) -> B(x) k DeleteMolecules");
    REQUIRE(explicitDeleteMoleculesWholePattern.reactions.size() == 1);
    REQUIRE(explicitDeleteMoleculesWholePattern.reactions.all().front().getProducts().size() == 2);
    bool sawReplacementProduct = false;
    bool sawWholePatternReleasedPartner = false;
    for (const auto productIndex :
         explicitDeleteMoleculesWholePattern.reactions.all().front().getProducts()) {
        const auto graph = explicitDeleteMoleculesWholePattern.species.get(productIndex)
                               .getSpeciesGraph().toString();
        sawReplacementProduct = sawReplacementProduct || graph == "B(x)";
        sawWholePatternReleasedPartner = sawWholePatternReleasedPartner || graph == "C(x)";
    }
    CHECK(sawReplacementProduct);
    CHECK(sawWholePatternReleasedPartner);

    const auto externalPartner = generate(
        "    A(x,y,s~u~p)\n    B(x)\n    C(y)",
        "    A(x!1,y!2,s~u).B(x!1).C(y!2) 1",
        "    r: A(x!1,s~u).B(x!1) -> A(x!1,y,s~p).B(x!1) k");
    CHECK(externalPartner.reactions.size() == 0);
    CHECK(externalPartner.species.size() == 1);

    const auto twoExternalPartners = generate(
        "    A(x,y,s~u~p)\n    B(x)\n    C(y)\n    D(y)",
        "    A(x!1,y!2!3,s~u).B(x!1).C(y!2).D(y!3) 1",
        "    r: A(x!1,s~u).B(x!1) -> A(x!1,y,s~p).B(x!1) k");
    CHECK(twoExternalPartners.reactions.size() == 0);
    CHECK(twoExternalPartners.species.size() == 1);

    const auto mixedFreeAndBoundSites = generate(
        "    A(x,y,s~u~p)\n    B(x)\n    C(y)\n    D(y)",
        "    A(x!1,y,s~u).B(x!1) 1\n"
        "    A(x!1,y!2,s~u).B(x!1).C(y!2) 1\n"
        "    A(x!1,y!2!3,s~u).B(x!1).C(y!2).D(y!3) 1",
        "    r: A(x!1,s~u).B(x!1) -> A(x!1,y,s~p).B(x!1) k");
    CHECK(mixedFreeAndBoundSites.reactions.size() == 1);

    const auto freeProductSite = generate(
        "    A(x,y,s~u~p)\n    B(x)",
        "    A(x!1,y,s~u).B(x!1) 1",
        "    r: A(x!1,s~u).B(x!1) -> A(x!1,y,s~p).B(x!1) k");
    CHECK(freeProductSite.reactions.size() == 1);

    const auto explicitBondBreak = generate(
        "    A(x,y,s~u~p)\n    B(x)\n    C(y)",
        "    A(x!1,y!2,s~u).B(x!1).C(y!2) 1",
        "    r: A(x!1,y!2,s~u).B(x!1).C(y!2) -> "
        "A(x!1,y,s~p).B(x!1) + C(y) k");
    CHECK(explicitBondBreak.reactions.size() == 1);

    const auto retainedBoundSite = generate(
        "    A(x,y,s~u~p)\n    B(x)\n    C(y)",
        "    A(x!1,y!2,s~u).B(x!1).C(y!2) 1",
        "    r: A(x!1,y!2,s~u).B(x!1).C(y!2) -> "
        "A(x!1,y!2,s~p).B(x!1).C(y!2) k");
    CHECK(retainedBoundSite.reactions.size() == 1);

    const auto explicitDeleteMolecules = generate(
        "    A(x,y,s~u~p)\n    B(x)\n    C(y)",
        "    A(x!1,y!2,s~u).B(x!1).C(y!2) 1",
        "    r: A(x!1,s~u).B(x!1) -> A(x!1,y,s~p).B(x!1) k DeleteMolecules");
    REQUIRE(explicitDeleteMolecules.reactions.size() == 1);
    const auto& products = explicitDeleteMolecules.reactions.all().front().getProducts();
    REQUIRE(products.size() == 2);
    bool sawRetainedPair = false;
    bool sawReleasedPartner = false;
    for (const auto productIndex : products) {
        const auto& graph = explicitDeleteMolecules.species.get(productIndex)
                                .getSpeciesGraph().toString();
        sawRetainedPair = sawRetainedPair ||
            (graph.find("A(") != std::string::npos &&
             graph.find("B(") != std::string::npos &&
             graph.find("s~p") != std::string::npos);
        sawReleasedPartner = sawReleasedPartner || graph == "C(y)";
    }
    CHECK(sawRetainedPair);
    CHECK(sawReleasedPartner);
}

TEST_CASE("Rule expansion: plain deletion splitting a complex yields no reaction", "[ReactionRule]") {
    // BNG2 build_reaction returns undef when a molecule deletion without the
    // DeleteMolecules modifier would leave more fragments than product
    // patterns. ComplexDegradation Rule04 (A(b!1).B(a!1) -> A(b)) fires on the
    // dimer but must not fire on the trimer, where deleting B would orphan C.
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b)
    B(a,c)
    C(b)
end molecule types
begin seed species
    A(b!1).B(a!1,c) 1
    A(b!1).B(a!1,c!2).C(b!2) 1
end seed species
begin reaction rules
    Rule04: A(b!1).B(a!1) -> A(b) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Rule expansion: null self-loop reactions are pruned like BNG2", "[ReactionRule]") {
    // BNG2 RxnList.pm drops reactions whose reactant and product multisets
    // are identical (Hawse_full: 88 reactions, not 176). A wildcard rule
    // matching a species already in the target state yields no reaction.
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(s~U~P)
end molecule types
begin seed species
    A(s~U) 1
end seed species
begin reaction rules
    R: A(s) -> A(s~U) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.reactions.size() == 0);
}

TEST_CASE("Rule expansion: multi-type reactant pattern requires every molecule type", "[ReactionRule]") {
    auto model = parseModel(R"(
begin molecule types
    A()
    B()
    C()
end molecule types
begin seed species
    A().B() 1
    A() 1
end seed species
begin reaction rules
    A().B() -> C() 1
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(5);

    REQUIRE(network.species.size() == 3);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Rule expansion: DeleteMolecules degradation", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    kd 0.1
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b!1).B(a!1) 100
end seed species
begin reaction rules
    A(b!1).B(a!1) -> B(a) kd DeleteMolecules
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() >= 2);
    REQUIRE(network.reactions.size() >= 1);
}

TEST_CASE("compiled whole-species deletion metadata controls a non-symmetric embedding",
          "[NetworkRulePlan][deletion]") {
    auto model = parseModel(R"(
begin parameters
    k 1
end parameters
begin molecule types
    A(x)
    B(x)
end molecule types
begin seed species
    A(x!1).A(x!1) 1
end seed species
begin reaction rules
    convert_one: A(x!+) -> B(x) k
end reaction rules
)");
    REQUIRE(model != nullptr);

    const compile::CompiledModel compiled(*model);
    REQUIRE(compiled.rules().size() == 1);
    const auto& rule = compiled.rules().front();
    REQUIRE(rule.forward().wholeSpeciesDeletions == std::vector<std::size_t>{0});

    const auto factorFor = [&](const compile::CompiledRuleDirection& direction) {
        compile::BNGcoreLoweringContext loweringContext(compiled);
        engine::NetworkRulePlan plan(rule, direction, compiled, loweringContext);
        ast::SpeciesList species;
        species.add(ast::Species(
            ast::SpeciesGraph(model->getSeedSpecies().front().getGraph()), 1.0));
        ast::RxnList reactions;
        plan.expand(species, reactions, 0, {}, species.size());
        if (reactions.size() != 1 || species.size() != 2) return -1.0;
        CHECK(species.get(1).getSpeciesGraph().toString() == "B(x)");
        const auto& reaction = reactions.all().front();
        CHECK(reaction.getReactants() == std::vector<std::size_t>{0});
        CHECK(reaction.getProducts() == std::vector<std::size_t>{1});
        CHECK(reaction.getRateLaw() == "k");
        return reaction.getFactor();
    };

    // The pinned BNG2 2.9.3 network has one reaction for this dimer seed.
    CHECK(factorFor(rule.forward()) == 1.0);

    // The compatibility AST can independently reconstruct the same deletion
    // from graph edits, so clearing the compiler-owned decision distinguishes
    // whether the network runtime actually consumes the compiled metadata.
    auto forwardWithoutWholeDeletion = rule.forward();
    forwardWithoutWholeDeletion.wholeSpeciesDeletions.clear();
    CHECK(factorFor(forwardWithoutWholeDeletion) == 2.0);
}

TEST_CASE("compiled reverse whole-species deletion remains compatible",
          "[NetworkRulePlan][deletion]") {
    auto model = parseModel(R"(
begin parameters
    k 1
end parameters
begin molecule types
    A(x)
    B(x)
end molecule types
begin seed species
    A(x!1).A(x!1) 1
    B(x!1).B(x!1) 1
end seed species
begin reaction rules
    convert: A(x!1).A(x!1) <-> B(x!1).B(x!1) k,k
end reaction rules
)");
    REQUIRE(model != nullptr);

    const compile::CompiledModel compiled(*model);
    REQUIRE(compiled.rules().size() == 1);
    const auto& rule = compiled.rules().front();
    REQUIRE(rule.reverse().has_value());
    REQUIRE(rule.forward().wholeSpeciesDeletions == std::vector<std::size_t>{0});
    REQUIRE(rule.reverse()->wholeSpeciesDeletions == std::vector<std::size_t>{0});

    compile::BNGcoreLoweringContext loweringContext(compiled);
    engine::NetworkRulePlan plan(rule, *rule.reverse(), compiled, loweringContext, true);
    ast::SpeciesList species;
    species.add(ast::Species(
        ast::SpeciesGraph(model->getSeedSpecies().at(1).getGraph()), 1.0));
    ast::RxnList reactions;
    plan.expand(species, reactions, 0, {}, species.size());

    REQUIRE(reactions.size() == 1);
    REQUIRE(species.size() == 2);
    CHECK(reactions.all().front().getFactor() == 1.0);
    CHECK(species.get(1).getSpeciesGraph().toString() == "A(x!1).A(x!1)");
}

TEST_CASE("compiled DeleteMolecules semantics preserve unmatched connected context",
          "[NetworkRulePlan][deletion]") {
    auto model = parseModel(R"(
begin parameters
    k 1
end parameters
begin molecule types
    A(b)
    B(a,c)
    C(c)
    D()
end molecule types
begin seed species
    A(b!1).B(a!1,c!2).C(c!2) 1
end seed species
begin reaction rules
    replace_A: A(b!+) -> D() k DeleteMolecules
end reaction rules
)");
    REQUIRE(model != nullptr);

    const compile::CompiledModel compiled(*model);
    REQUIRE(compiled.rules().size() == 1);
    const auto& rule = compiled.rules().front();
    CHECK(rule.forward().wholeSpeciesDeletions.empty());
    REQUIRE(rule.modifiers().size() == 1);
    CHECK(rule.modifiers().front().kind == compile::ModifierKind::DeleteMolecules);

    compile::BNGcoreLoweringContext loweringContext(compiled);
    engine::NetworkRulePlan plan(
        rule, rule.forward(), compiled, loweringContext, false);
    ast::SpeciesList species;
    species.add(ast::Species(
        ast::SpeciesGraph(model->getSeedSpecies().front().getGraph()), 1.0));
    ast::RxnList reactions;
    plan.expand(species, reactions, 0, {}, species.size());

    REQUIRE(reactions.size() == 1);
    REQUIRE(species.size() == 3);
    CHECK(species.get(1).getSpeciesGraph().toString() == "D()");
    CHECK(species.get(2).getSpeciesGraph().toString() == "B(a,c!1).C(c!1)");
    const auto& reaction = reactions.all().front();
    CHECK(reaction.getReactants() == std::vector<std::size_t>{0});
    CHECK(reaction.getProducts() == std::vector<std::size_t>{1, 2});
    CHECK(reaction.getRateLaw() == "k");
    CHECK(reaction.getFactor() == 1.0);
}

TEST_CASE("Rule expansion: deleting a bound molecule preserves a free site", "[ReactionRule]") {
    // BNG2 serializes an unbound component without an edge marker.  A
    // DeleteMolecules product must therefore remain the same species as the
    // independently seeded BNG2-equivalent graph, even when the deleted bond
    // was the component's only explicit internal unbound marker.
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    DNA(p1,p2)
    P1(dna)
    TF(d,dna)
    Sink()
end molecule types
begin seed species
    DNA(p1!1!2,p2).TF(d!3,dna!2).TF(d!3,dna!1) 1
    DNA(p1!1!2,p2!4).P1(dna!4).TF(d!3,dna!1).TF(d!3,dna!2) 1
end seed species
begin reaction rules
    P1 -> Sink() k DeleteMolecules
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(4);

    std::size_t targetCount = 0;
    for (std::size_t index = 0; index < network.species.size(); ++index) {
        const auto text = network.species.get(index).getSpeciesGraph().toString();
        REQUIRE_FALSE(text.empty());
        if (text.find("DNA(p1!1!2,p2)") == 0 && text.find("TF(") != std::string::npos &&
            text.find("P1(") == std::string::npos) {
            ++targetCount;
        }
    }
    REQUIRE(targetCount == 1);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Rule expansion: bidirectional rule decomposition", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    kf 1.0
    kr 0.5
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 100
    B(a) 100
end seed species
begin reaction rules
    A(b) + B(a) <-> A(b!1).B(a!1) kf, kr
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 3);
    REQUIRE(network.reactions.size() == 2);
}

TEST_CASE("Rule expansion: reverse local-rate scope remains bound", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(s~up~dn)
end molecule types
begin seed species
    A(s~dn) 1
    A(s~up) 1
end seed species
begin observables
    Molecules up A(s~up)
end observables
begin functions
    rate(z) = k + up(z)
end functions
begin reaction rules
    A%x(s~dn) <-> A%x(s~up) rate(x), rate(x)
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(4);

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 2);

    bool sawDownContext = false;
    bool sawUpContext = false;
    for (const auto& reaction : network.reactions.all()) {
        const auto& rate = reaction.getRateLaw();
        sawDownContext = sawDownContext || rate.find("|local:up=0;") != std::string::npos;
        sawUpContext = sawUpContext || rate.find("|local:up=1;") != std::string::npos;
    }
    REQUIRE(sawDownContext);
    REQUIRE(sawUpContext);
}

TEST_CASE("Rule expansion: MatchOnce modifier", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b,b)
    B(a)
end molecule types
begin seed species
    A(b,b) 100
    B(a) 200
end seed species
begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) k MatchOnce
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.reactions.size() >= 1);
}

TEST_CASE("generate_network max_agg is numeric and filters generated products only") {
    const auto generateWithMaxAgg = [](const std::string& maxAgg) {
        auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
begin reaction rules
  bind: A(b) + A(b) -> A(b!1).A(b!1) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>3,max_agg=>)" + maxAgg + R"(})
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        return generator.generate({});
    };

    const auto expressionBound = generateWithMaxAgg("1+1");
    CHECK(expressionBound.species.size() == 2);
    CHECK(expressionBound.reactions.size() == 1);

    const auto fractionalBelowProductSize = generateWithMaxAgg("1.5");
    CHECK(fractionalBelowProductSize.species.size() == 1);
    CHECK(fractionalBelowProductSize.reactions.size() == 0);

    const auto fractionalAboveProductSize = generateWithMaxAgg("2.5");
    CHECK(fractionalAboveProductSize.species.size() == 2);
    CHECK(fractionalAboveProductSize.reactions.size() == 1);

    const auto negativeBound = generateWithMaxAgg("-1");
    CHECK(negativeBound.species.size() == 1);
    CHECK(negativeBound.reactions.size() == 0);

    auto boundaryModel = parseModel(R"(
begin model
begin molecule types
  A(b)
  X(b)
  Y(b)
  Z(b)
end molecule types
begin seed species
  A(b!1!2).A(b!1).A(b!2) 1
  X(b) 1
  Y(b) 1
end seed species
begin reaction rules
  trimer: X(b) + X(b) + X(b) -> X(b!1).X(b!1!2).X(b!2) 1
  convert: Y(b) -> Z(b) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>3,max_agg=>2})
)");
    REQUIRE(boundaryModel != nullptr);
    engine::NetworkGenerator boundaryGenerator(*boundaryModel);
    const auto boundary = boundaryGenerator.generate({});
    REQUIRE(boundary.species.size() == 4);
    REQUIRE(boundary.reactions.size() == 1);

    bool retainedOverLimitSeed = false;
    bool rejectedOverLimitProduct = true;
    bool allowedOtherProduct = false;
    for (const auto& species : boundary.species.all()) {
        const auto& graph = species.getSpeciesGraph().toString();
        retainedOverLimitSeed = retainedOverLimitSeed ||
            graph == "A(b!1!2).A(b!1).A(b!2)";
        rejectedOverLimitProduct = rejectedOverLimitProduct &&
            graph != "X(b!1).X(b!1!2).X(b!2)";
        allowedOtherProduct = allowedOtherProduct || graph == "Z(b)";
    }
    CHECK(retainedOverLimitSeed);
    CHECK(rejectedOverLimitProduct);
    CHECK(allowedOtherProduct);
}

TEST_CASE("generate_network max_stoich accepts unlimited as an unbounded molecule type") {
    const auto generateWithSentinel = [](const std::string& sentinel) {
        auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
begin reaction rules
  bind: A(b) -> A(b!1).A(b!1) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>1,max_stoich=>{A=>)" + sentinel + R"(}})
)");
        REQUIRE(model != nullptr);

        engine::NetworkGenerator generator(*model);
        return generator.generate({});
    };

    for (const auto& sentinel : {"unlimited", "'unlimited'", "\"unlimited\""}) {
        INFO("max_stoich sentinel: " << sentinel);
        const auto network = generateWithSentinel(sentinel);
        CHECK(network.species.size() == 2);
        REQUIRE(network.reactions.size() == 1);
        const auto& reaction = network.reactions.all().front();
        REQUIRE(reaction.getReactants().size() == 1);
        REQUIRE(reaction.getProducts().size() == 1);
        CHECK(network.species.get(reaction.getReactants().front()).getSpeciesGraph().toString() == "A(b)");
        CHECK(network.species.get(reaction.getProducts().front()).getSpeciesGraph().toString() ==
              "A(b!1).A(b!1)");
    }
}

TEST_CASE("generate_network max_stoich does not trim whitespace inside quoted values") {
    const auto parseWithValue = [](const std::string& value) {
        return parseModel(R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
begin reaction rules
  bind: A(b) -> A(b!1).A(b!1) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>1,max_stoich=>{A=>)" + value + R"(}})
)");
    };

    for (const auto& quote : {"'", "\""}) {
        for (const auto& contents : {"un limited", " unlimited", "unlimited "}) {
            const std::string value = std::string(quote) + contents + quote;
            INFO("quoted max_stoich value: " << value);
            auto model = parseWithValue(value);
            REQUIRE(model != nullptr);
            engine::NetworkGenerator generator(*model);
            CHECK_THROWS(generator.generate({}));
        }
    }
}

TEST_CASE("generate_network max_stoich combines finite limits with unlimited and retains seeds") {
    auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
  B(b)
end molecule types
begin seed species
  A(b) 1
  A(b!1).A(b!1) 1
  B(b) 1
end seed species
begin reaction rules
  A_dimerize: A(b) -> A(b!1).A(b!1) 1
  B_dimerize: B(b) -> B(b!1).B(b!1) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>1,max_stoich=>{A=>1,B=>unlimited}})
)");
    REQUIRE(model != nullptr);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generate({});

    REQUIRE(network.species.size() == 4);
    REQUIRE(network.reactions.size() == 1);
    const auto& reaction = network.reactions.all().front();
    REQUIRE(reaction.getReactants().size() == 1);
    REQUIRE(reaction.getProducts().size() == 1);
    CHECK(network.species.get(reaction.getReactants().front()).getSpeciesGraph().toString() == "B(b)");
    CHECK(network.species.get(reaction.getProducts().front()).getSpeciesGraph().toString() ==
          "B(b!1).B(b!1)");

    bool retainedOverLimitASeed = false;
    bool generatedUnlimitedBProduct = false;
    for (const auto& species : network.species.all()) {
        const auto& graph = species.getSpeciesGraph().toString();
        retainedOverLimitASeed = retainedOverLimitASeed || graph == "A(b!1).A(b!1)";
        generatedUnlimitedBProduct = generatedUnlimitedBProduct || graph == "B(b!1).B(b!1)";
    }
    CHECK(retainedOverLimitASeed);
    CHECK(generatedUnlimitedBProduct);
}

TEST_CASE("generate_network max_stoich evaluates static numeric expressions and last duplicate") {
    const auto generateDimer = [](const std::string& limits) {
        auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
begin reaction rules
  bind: A(b) -> A(b!1).A(b!1) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>1,max_stoich=>)" + limits + R"(})
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        return generator.generate({});
    };

    const auto sumLimit = generateDimer("{A=>1+1}");
    CHECK(sumLimit.reactions.size() == 1);

    const auto fractionalLimit = generateDimer("{A=>2.5}");
    CHECK(fractionalLimit.reactions.size() == 1);

    const auto negativeLimit = generateDimer("{A=>-1}");
    CHECK(negativeLimit.reactions.size() == 0);

    const auto lastDuplicateWins = generateDimer("{A=>1,A=>2}");
    CHECK(lastDuplicateWins.reactions.size() == 1);

    const auto reversedDuplicateWins = generateDimer("{A=>2,A=>1}");
    CHECK(reversedDuplicateWins.reactions.size() == 0);

    auto trimerModel = parseModel(R"(
begin model
begin molecule types
  A(b,c)
  C(x)
end molecule types
begin seed species
  C(x) 1
end seed species
begin reaction rules
  synthesize: C(x) -> A(b!1,c!2).A(b!1,c).A(b,c!2) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>1,max_stoich=>{A=>2**3}})
)");
    REQUIRE(trimerModel != nullptr);
    engine::NetworkGenerator trimerGenerator(*trimerModel);
    const auto trimer = trimerGenerator.generate({});
    CHECK(trimer.reactions.size() == 1);
}

TEST_CASE("nested action-map parser preserves ordered entries and rejects trailing tokens") {
    const auto entries = parser::parseNestedHashEntries(
        "{A=>2.5,'B'=>unlimited,A=>1+1}");

    REQUIRE(entries.size() == 3);
    CHECK(entries[0].first == "A");
    CHECK(entries[0].second == "2.5");
    CHECK(entries[1].first == "'B'");
    CHECK(entries[1].second == "unlimited");
    CHECK(entries[2].first == "A");
    CHECK(entries[2].second == "1+1");
    const auto quotedKeys = parser::parseNestedHashEntries("{'A B'=>1,\"A-B\"=>2}");
    REQUIRE(quotedKeys.size() == 2);
    CHECK(quotedKeys[0].first == "'A B'");
    CHECK(quotedKeys[1].first == "\"A-B\"");
    CHECK(parser::parseNestedHashEntries("{}").empty());
    CHECK_THROWS(parser::parseNestedHashEntries("{A=>1} trailing"));
    CHECK_THROWS(parser::parseNestedHashEntries("{A=>1`+1}"));
}

TEST_CASE("max_stoich compiler handles programmatically constructed actions") {
    ast::Model model;
    ast::Action action;
    action.name = "generate_network";
    action.arguments.emplace("max_stoich", "{A=>2.5,A=>1+1}");
    model.addAction(action);

    const compile::Document document(model);
    REQUIRE(document.protocol().actions.size() == 1);
    const auto& compiledAction = document.protocol().actions.front();
    REQUIRE(compiledAction.generateNetworkOptions.has_value());
    const auto& options = *compiledAction.generateNetworkOptions;
    REQUIRE(options.maxStoich.has_value());
    REQUIRE(options.maxStoich->size() == 1);
    CHECK(options.maxStoich->at("A") == 2.0);
    CHECK(compiledAction.arguments.at("max_stoich") == "{A=>2.5,A=>1+1}");
}

TEST_CASE("generate_network max_stoich rejects quoted non-identifier keys without aliasing") {
    const auto diagnosticForKey = [](const std::string& key) {
        auto model = parseModel(R"(
begin model
begin molecule types
  AB(b)
end molecule types
begin seed species
  AB(b) 1
end seed species
begin reaction rules
  bind: AB(b) -> AB(b!1).AB(b!1) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>1,max_stoich=>{)" + key + R"(=>1}})
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        std::string errorMessage;
        try {
            (void)generator.generate({});
        } catch (const std::runtime_error& error) {
            errorMessage = error.what();
        }
        return errorMessage;
    };

    for (const auto& key : {"'A B'", "\"A B\"", "'A-B'", "\"A-B\""}) {
        const auto errorMessage = diagnosticForKey(key);
        CHECK(errorMessage.find("max_stoich") != std::string::npos);
        CHECK(errorMessage.find(key) != std::string::npos);
    }

    auto validQuotedKey = parseModel(R"(
begin model
begin molecule types
  AB(b)
end molecule types
begin seed species
  AB(b) 1
end seed species
begin reaction rules
  bind: AB(b) -> AB(b!1).AB(b!1) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>1,max_stoich=>{'AB'=>2}})
)");
    REQUIRE(validQuotedKey != nullptr);
    engine::NetworkGenerator validGenerator(*validQuotedKey);
    CHECK(validGenerator.generate({}).reactions.size() == 1);
}

TEST_CASE("generate_network max_stoich applies negative limits to absent product types only") {
    const auto generateWithALimit = [](const std::string& limit) {
        auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
  B(b)
  C(b)
end molecule types
begin seed species
  A(b) 1
  B(b) 1
end seed species
begin reaction rules
  B_to_C: B(b) -> C(b) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>1,max_stoich=>{A=>)" + limit + R"(}})
)");
        REQUIRE(model != nullptr);

        engine::NetworkGenerator generator(*model);
        return generator.generate({});
    };

    const auto negative = generateWithALimit("-1");

    CHECK(negative.species.size() == 2);
    CHECK(negative.reactions.size() == 0);

    bool retainedASeed = false;
    bool retainedBSeed = false;
    for (const auto& species : negative.species.all()) {
        const auto& graph = species.getSpeciesGraph().toString();
        retainedASeed = retainedASeed || graph == "A(b)";
        retainedBSeed = retainedBSeed || graph == "B(b)";
    }
    CHECK(retainedASeed);
    CHECK(retainedBSeed);

    const auto zero = generateWithALimit("0");
    CHECK(zero.reactions.size() == 1);
}

TEST_CASE("generate_network max_stoich defers unsupported numeric diagnostics") {
    auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
begin reaction rules
  bind: A(b) -> A(b!1).A(b!1) 1
end reaction rules
end model

generate_network({overwrite=>1,max_iter=>1,max_stoich=>{A=>1/0}})
)");
    REQUIRE(model != nullptr);

    engine::NetworkGenerator generator(*model);
    CHECK(generator.document().valid());
    std::string errorMessage;
    try {
        (void)generator.generateNative(3);
    } catch (const std::runtime_error& error) {
        errorMessage = error.what();
    }
    CHECK(errorMessage.find("max_stoich") != std::string::npos);
    CHECK(errorMessage.find("1/0") != std::string::npos);
}

TEST_CASE("generate_network max_stoich uses the first action that supplies the option") {
    auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
begin reaction rules
  bind: A(b) -> A(b!1).A(b!1) 1
end reaction rules
end model

begin actions
  generate_network({overwrite=>1,max_iter=>1,max_stoich=>{}})
  generate_network({overwrite=>1,max_iter=>1,max_stoich=>{A=>1}})
end actions
)");
    REQUIRE(model != nullptr);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generate({});
    CHECK(network.reactions.size() == 1);
}

TEST_CASE("generate_network max_agg compiles finite numeric expressions and defers diagnostics") {
    const auto compileMaxAgg = [](const std::string& source) {
        auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
end model

generate_network({max_agg=>)" + source + R"(})
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        REQUIRE(generator.document().valid());
        const auto& action = generator.document().protocol().actions.front();
        REQUIRE(action.generateNetworkOptions.has_value());
        CHECK(action.arguments.at("max_agg") == source);
        return *action.generateNetworkOptions;
    };

    for (const auto& [source, expected] : std::vector<std::pair<std::string, double>>{
             {"1+1", 2.0}, {"2.5", 2.5}, {"1e2", 100.0}, {"-1", -1.0}}) {
        INFO("max_agg expression: " << source);
        const auto options = compileMaxAgg(source);
        CHECK_FALSE(options.maxAggregateDiagnostic.has_value());
        REQUIRE(options.maxAggregate.has_value());
        CHECK(*options.maxAggregate == expected);
    }

    for (const auto& source : {"unknown", "exp(2)", "1e309", "1/0", "\"2junk\""}) {
        INFO("max_agg expression: " << source);
        const auto options = compileMaxAgg(source);
        CHECK_FALSE(options.maxAggregate.has_value());
        REQUIRE(options.maxAggregateDiagnostic.has_value());
        CHECK(options.maxAggregateDiagnostic->message.find("max_agg") != std::string::npos);
        CHECK(options.maxAggregateDiagnostic->message.find(source) != std::string::npos);

        const std::string invalidBnglPrefix = R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
end model

generate_network({max_agg=>)";
        auto invalidModel = parseModel(invalidBnglPrefix + source + "})\n");
        REQUIRE(invalidModel != nullptr);
        engine::NetworkGenerator invalidGenerator(*invalidModel);
        CHECK(invalidGenerator.document().valid());
        try {
            (void)invalidGenerator.generateNative(3);
            FAIL("invalid max_agg must fail when generation begins");
        } catch (const std::runtime_error& error) {
            CHECK(std::string(error.what()).find(source) != std::string::npos);
        }
    }
}

TEST_CASE("generate_network max_agg uses the first action that supplies the option") {
    auto model = parseModel(R"(
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 1
end seed species
begin reaction rules
  bind: A(b) + A(b) -> A(b!1).A(b!1) 1
end reaction rules
end model

begin actions
  generate_network({max_iter=>1})
  generate_network({max_agg=>1})
end actions
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generate({});
    CHECK(network.species.size() == 1);
    CHECK(network.reactions.size() == 0);
}
