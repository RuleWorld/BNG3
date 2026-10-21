#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <string>

#include "ast/Model.hpp"
#include "compile/ActionOptions.hpp"
#include "compile/SimulationMethod.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;
using Catch::Matchers::ContainsSubstring;

namespace {

ast::Action makeAction(const std::string& name,
                        const std::map<std::string, std::string>& arguments = {}) {
    ast::Action action;
    action.name = name;
    action.arguments = arguments;
    return action;
}

} // namespace

TEST_CASE("the simulation method decision is owned by the shared layer") {
    const auto ode = compile::tryDecideSimulationMethod(makeAction("simulate"));
    REQUIRE(ode.has_value());
    CHECK(ode->method == compile::SimulationMethod::Cvode);
    CHECK(ode->engineName == "cvode");
    CHECK(ode->deterministic);
    CHECK_FALSE(ode->stochastic);

    const auto ssa = compile::tryDecideSimulationMethod(
        makeAction("simulate", {{"method", "\"ssa\""}}));
    REQUIRE(ssa.has_value());
    CHECK(ssa->method == compile::SimulationMethod::Ssa);
    CHECK(ssa->engineName == "ssa");
    CHECK(ssa->stochastic);
    CHECK_FALSE(ssa->deterministic);

    const auto psa = compile::tryDecideSimulationMethod(
        makeAction("simulate", {{"method", "psa"}}));
    REQUIRE(psa.has_value());
    CHECK(psa->method == compile::SimulationMethod::Psa);
    CHECK(psa->engineName == "psa");

    const auto dedicated = compile::tryDecideSimulationMethod(
        makeAction("simulate_ode"));
    REQUIRE(dedicated.has_value());
    CHECK(dedicated->method == compile::SimulationMethod::Cvode);

    const auto pla = compile::tryDecideSimulationMethod(
        makeAction("simulate_pla"));
    REQUIRE(pla.has_value());
    CHECK(pla->method == compile::SimulationMethod::Pla);

    CHECK_FALSE(compile::tryDecideSimulationMethod(
                    makeAction("simulate", {{"method", "\"nope\""}}))
                    .has_value());
    CHECK_FALSE(
        compile::tryDecideSimulationMethod(makeAction("writeNetwork")).has_value());
}

TEST_CASE("an unsupported simulation method quotes its source spelling") {
    CHECK_THROWS_WITH(
        compile::decideSimulationMethod(
            makeAction("simulate", {{"method", "\"Quantum\""}})),
        ContainsSubstring("Quantum"));
    CHECK_THROWS_WITH(
        compile::decideSimulationMethod(
            makeAction("simulate", {{"method", "\"Quantum\""}})),
        ContainsSubstring("unsupported simulation method"));
}

TEST_CASE("the options a method can honour are decided once") {
    const auto ode = compile::optionSupportFor(compile::SimulationMethod::Cvode);
    CHECK(ode.maxStep);
    CHECK(ode.steadyState);
    CHECK(ode.sparse);
    CHECK(ode.stopIf);
    CHECK(ode.sampleTimes);
    CHECK(ode.checkProductScale);
    CHECK_FALSE(ode.outputStepInterval);
    CHECK_FALSE(ode.maxSimSteps);

    const auto ssa = compile::optionSupportFor(compile::SimulationMethod::Ssa);
    CHECK(ssa.stopIf);
    CHECK(ssa.sampleTimes);
    CHECK(ssa.outputStepInterval);
    CHECK(ssa.maxSimSteps);
    CHECK_FALSE(ssa.maxStep);
    CHECK_FALSE(ssa.sparse);
    CHECK_FALSE(ssa.checkProductScale);

    const auto pla = compile::optionSupportFor(compile::SimulationMethod::Pla);
    CHECK_FALSE(pla.maxStep);
    CHECK_FALSE(pla.stopIf);
    CHECK_FALSE(pla.sampleTimes);
    CHECK_FALSE(pla.maxSimSteps);

    const auto psa = compile::optionSupportFor(compile::SimulationMethod::Psa);
    CHECK(psa.maxSimSteps);
    CHECK_FALSE(psa.maxStep);
    CHECK_FALSE(psa.sampleTimes);
    CHECK_FALSE(psa.checkProductScale);
}

TEST_CASE("an option a method cannot honour is refused with its own name") {
    compile::SimulationOptionSupport requested;
    requested.sparse = true;
    CHECK_THROWS_WITH(
        compile::validateSimulationOptions(compile::SimulationMethod::Ssa, requested),
        ContainsSubstring("max_step, steady_state, and sparse require an ODE"));

    compile::SimulationOptionSupport stop;
    stop.stopIf = true;
    CHECK_THROWS_WITH(
        compile::validateSimulationOptions(compile::SimulationMethod::Pla, stop),
        ContainsSubstring("stop_if requires an ODE or SSA simulation method"));

    compile::SimulationOptionSupport steps;
    steps.maxSimSteps = true;
    CHECK_THROWS_WITH(
        compile::validateSimulationOptions(compile::SimulationMethod::Cvode, steps),
        ContainsSubstring("max_sim_steps requires an SSA or PSA simulation method"));
    CHECK_NOTHROW(
        compile::validateSimulationOptions(compile::SimulationMethod::Psa, steps));
}

TEST_CASE("action options are read as typed values") {
    auto model = parser::parseModel(R"(
begin parameters
    k 0.1
    steps 4
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
)");
    REQUIRE(model != nullptr);

    const auto action = makeAction("simulate", {
        {"t_end", "2"},
        {"n_steps", "steps"},
        {"atol", "1e-9"},
        {"sparse", "1"},
        {"steady_state", "0"},
    });
    const compile::ActionOptions options(action, *model);

    CHECK(options.hasValue("t_end"));
    CHECK_FALSE(options.hasValue("max_step"));
    REQUIRE(options.optionalNumber("t_end").has_value());
    CHECK(*options.optionalNumber("t_end") == 2.0);
    REQUIRE(options.optionalCount("n_steps").has_value());
    CHECK(*options.optionalCount("n_steps") == 4u);
    REQUIRE(options.optionalNumber("atol").has_value());
    CHECK(*options.optionalNumber("atol") == 1e-9);
    CHECK(options.flag("sparse", false));
    CHECK_FALSE(options.flag("steady_state", false));
    CHECK(options.sourceSpelling("atol") == "1e-9");
}

TEST_CASE("an invalid action option quotes its source spelling") {
    auto model = parser::parseModel(R"(
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
)");
    REQUIRE(model != nullptr);

    const auto action = makeAction("simulate", {{"n_steps", "2.5"}});
    const compile::ActionOptions options(action, *model);
    CHECK_THROWS_WITH(
        options.optionalCount("n_steps"),
        ContainsSubstring("n_steps must be a non-negative integer (value '2.5')"));

    const auto negative = makeAction("simulate", {{"output_step_interval", "-1"}});
    const compile::ActionOptions negativeOptions(negative, *model);
    CHECK_THROWS_WITH(
        negativeOptions.optionalEventCount("output_step_interval"),
        ContainsSubstring("output_step_interval must be a non-negative integer"));
}
