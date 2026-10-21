#include "compile/SimulationMethod.hpp"

#include <algorithm>
#include <cctype>
#include <stdexcept>

#include "ast/Model.hpp"

namespace bng::compile {

namespace {

std::string lowercase(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

bool isQuotedActionValue(const std::string& value) {
    return value.size() >= 2 &&
           ((value.front() == '"' && value.back() == '"') ||
            (value.front() == '\'' && value.back() == '\''));
}

std::string unquoteActionValue(const std::string& value) {
    if (isQuotedActionValue(value)) {
        return value.substr(1, value.size() - 2);
    }
    return value;
}

SimulationMethodDecision decision(SimulationMethod method,
                                  std::string engineName,
                                  std::string sourceSpelling) {
    SimulationMethodDecision result;
    result.method = method;
    result.engineName = std::move(engineName);
    result.sourceSpelling = std::move(sourceSpelling);
    result.deterministic =
        method == SimulationMethod::Cvode || method == SimulationMethod::Euler ||
        method == SimulationMethod::Rk4;
    result.stochastic = method == SimulationMethod::Ssa;
    result.expressionStepCount =
        method == SimulationMethod::Cvode || method == SimulationMethod::Euler ||
        method == SimulationMethod::Rk4 || method == SimulationMethod::Ssa;
    return result;
}

} // namespace

std::optional<SimulationMethodDecision> tryDecideSimulationMethod(
    const ast::Action& action) {
    const auto name = lowercase(action.name);
    // The dedicated simulation actions select their own method; the generic
    // `simulate` action selects it with its `method` argument.
    if (name == "simulate_ode") {
        return decision(SimulationMethod::Cvode, "cvode", action.name);
    }
    if (name == "simulate_ssa") {
        return decision(SimulationMethod::Ssa, "ssa", action.name);
    }
    if (name == "simulate_pla") {
        return decision(SimulationMethod::Pla, "pla", action.name);
    }
    if (name == "simulate_psa") {
        return decision(SimulationMethod::Psa, "psa", action.name);
    }
    if (name == "simulate_nf") {
        return decision(SimulationMethod::Nf, "nf", action.name);
    }
    if (name != "simulate") {
        return std::nullopt;
    }

    const auto argument = action.arguments.find("method");
    const std::string spelling =
        argument == action.arguments.end() ? "ode" : argument->second;
    const auto normalized = lowercase(unquoteActionValue(spelling));
    if (normalized == "ode" || normalized == "cvode") {
        return decision(SimulationMethod::Cvode, "cvode", spelling);
    }
    if (normalized == "euler") {
        return decision(SimulationMethod::Euler, "euler", spelling);
    }
    if (normalized == "rk4") {
        return decision(SimulationMethod::Rk4, "rk4", spelling);
    }
    if (normalized == "ssa") {
        return decision(SimulationMethod::Ssa, "ssa", spelling);
    }
    if (normalized == "pla") {
        return decision(SimulationMethod::Pla, "pla", spelling);
    }
    if (normalized == "psa") {
        return decision(SimulationMethod::Psa, "psa", spelling);
    }
    if (normalized == "nf") {
        return decision(SimulationMethod::Nf, "nf", spelling);
    }
    return std::nullopt;
}

SimulationMethodDecision decideSimulationMethod(const ast::Action& action) {
    const auto selected = tryDecideSimulationMethod(action);
    if (!selected.has_value()) {
        const auto name = lowercase(action.name);
        if (name != "simulate" && name != "simulate_ode" &&
            name != "simulate_ssa" && name != "simulate_pla" &&
            name != "simulate_psa" && name != "simulate_nf") {
            throw std::runtime_error(
                "action '" + action.name + "' does not select a simulation method");
        }
        const auto argument = action.arguments.find("method");
        const std::string spelling =
            argument == action.arguments.end() ? "ode" : argument->second;
        throw std::runtime_error(
            "simulate: unsupported simulation method: " + spelling);
    }
    return *selected;
}

SimulationOptionSupport optionSupportFor(SimulationMethod method) {
    SimulationOptionSupport support;
    switch (method) {
    case SimulationMethod::Cvode:
    case SimulationMethod::Euler:
    case SimulationMethod::Rk4:
        support.maxStep = true;
        support.steadyState = true;
        support.sparse = true;
        support.stopIf = true;
        support.sampleTimes = true;
        support.checkProductScale = true;
        return support;
    case SimulationMethod::Ssa:
        support.stopIf = true;
        support.sampleTimes = true;
        support.outputStepInterval = true;
        support.maxSimSteps = true;
        return support;
    case SimulationMethod::Pla:
        return support;
    case SimulationMethod::Psa:
        // The population sampler honours the internal step budget but not the
        // continuous-time options of the ODE family.
        support.maxSimSteps = true;
        return support;
    case SimulationMethod::Nf:
        // The network-free path samples explicit output times and owns its
        // own equilibration and traversal controls.
        support.sampleTimes = true;
        return support;
    }
    return support;
}

std::optional<SimulationMethod> simulationMethodForEngineName(
    const std::string& engineName) {
    const auto normalized = lowercase(engineName);
    if (normalized == "cvode") return SimulationMethod::Cvode;
    if (normalized == "euler") return SimulationMethod::Euler;
    if (normalized == "rk4") return SimulationMethod::Rk4;
    if (normalized == "ssa") return SimulationMethod::Ssa;
    if (normalized == "pla") return SimulationMethod::Pla;
    if (normalized == "psa") return SimulationMethod::Psa;
    if (normalized == "nf") return SimulationMethod::Nf;
    return std::nullopt;
}

void validateSimulationOptions(SimulationMethod method,
                               const SimulationOptionSupport& requested) {
    const auto support = optionSupportFor(method);
    if (!support.maxStep &&
        (requested.maxStep || requested.steadyState || requested.sparse)) {
        throw std::runtime_error(
            "max_step, steady_state, and sparse require an ODE simulation method");
    }
    if (!support.stopIf && requested.stopIf) {
        throw std::runtime_error(
            "stop_if requires an ODE or SSA simulation method");
    }
    if (!support.sampleTimes && requested.sampleTimes) {
        throw std::runtime_error(
            "sample_times requires an ODE or SSA simulation method");
    }
    if (!support.outputStepInterval && requested.outputStepInterval) {
        throw std::runtime_error(
            "output_step_interval requires an SSA simulation method");
    }
    if (!support.maxSimSteps && requested.maxSimSteps) {
        throw std::runtime_error(
            "max_sim_steps requires an SSA or PSA simulation method");
    }
    if (!support.checkProductScale && requested.checkProductScale) {
        throw std::runtime_error(
            "check_product_scale requires an ODE simulation method");
    }
}

} // namespace bng::compile
