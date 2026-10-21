#pragma once

#include <algorithm>
#include <cctype>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>

#include "ast/Model.hpp"

namespace bng::compile {

// The simulation methods a protocol action or a public API call can select.
//
// This typed decision is the single owner of the method spelling, the engine
// name and the options each method can honour, so the compile layer, the
// action dispatcher and the numerical backends cannot drift apart.  The
// source spelling of the selection is kept so a diagnostic can quote it.
enum class SimulationMethod {
    Cvode,
    Euler,
    Rk4,
    Ssa,
    Pla,
    Psa,
    Nf,
};

// The options whose acceptance depends on the selected method.
struct SimulationOptionSupport {
    bool maxStep = false;
    bool steadyState = false;
    bool sparse = false;
    bool stopIf = false;
    bool sampleTimes = false;
    bool outputStepInterval = false;
    bool maxSimSteps = false;
    bool checkProductScale = false;
};

struct SimulationMethodDecision {
    SimulationMethod method = SimulationMethod::Cvode;
    // The engine name the numerical backends dispatch on.
    std::string engineName = "cvode";
    // The selection as written in the source, preserved for diagnostics.
    std::string sourceSpelling = "ode";
    // The deterministic ODE family.
    bool deterministic = false;
    // The direct-method stochastic family.
    bool stochastic = false;
    // The method reads its step count with the Safe-Perl numeric expression
    // rules of the fixed output grid.
    bool expressionStepCount = false;
};

namespace detail {

inline std::string lowercase(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

inline bool isQuotedActionValue(const std::string& value) {
    return value.size() >= 2 &&
           ((value.front() == '"' && value.back() == '"') ||
            (value.front() == '\'' && value.back() == '\''));
}

inline std::string unquoteActionValue(const std::string& value) {
    if (isQuotedActionValue(value)) {
        return value.substr(1, value.size() - 2);
    }
    return value;
}

inline SimulationMethodDecision decision(SimulationMethod method,
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

} // namespace detail

// The method a protocol action selects.  The action's own name selects the
// method for the dedicated actions, and its `method` argument selects it
// otherwise.  An absent `method` argument selects the ODE default.  No
// decision is returned for a spelling that is not supported.
//
// The decision lives in the header, and that is deliberate: it is the one
// decision the compile layer, the action dispatcher and the numerical
// backends all take, and it crosses the boundary between them by value.  A
// function that returns a class with a destructor across a static library
// boundary is mangled with a type index that depends on the order the
// translation unit happened to meet the types, so two translation units that
// include this header in a different order name the same function
// differently and the Microsoft linker cannot resolve it.  Keeping the
// decision here removes the cross-boundary symbol entirely.
inline std::optional<SimulationMethodDecision> tryDecideSimulationMethod(
    const ast::Action& action) {
    const auto name = detail::lowercase(action.name);
    // The dedicated simulation actions select their own method; the generic
    // `simulate` action selects it with its `method` argument.
    if (name == "simulate_ode") {
        return detail::decision(SimulationMethod::Cvode, "cvode", action.name);
    }
    if (name == "simulate_ssa") {
        return detail::decision(SimulationMethod::Ssa, "ssa", action.name);
    }
    if (name == "simulate_pla") {
        return detail::decision(SimulationMethod::Pla, "pla", action.name);
    }
    if (name == "simulate_psa") {
        return detail::decision(SimulationMethod::Psa, "psa", action.name);
    }
    if (name == "simulate_nf") {
        return detail::decision(SimulationMethod::Nf, "nf", action.name);
    }
    if (name != "simulate") {
        return std::nullopt;
    }

    const auto argument = action.arguments.find("method");
    const std::string spelling =
        argument == action.arguments.end() ? "ode" : argument->second;
    const auto normalized = detail::lowercase(detail::unquoteActionValue(spelling));
    if (normalized == "ode" || normalized == "cvode") {
        return detail::decision(SimulationMethod::Cvode, "cvode", spelling);
    }
    if (normalized == "euler") {
        return detail::decision(SimulationMethod::Euler, "euler", spelling);
    }
    if (normalized == "rk4") {
        return detail::decision(SimulationMethod::Rk4, "rk4", spelling);
    }
    if (normalized == "ssa") {
        return detail::decision(SimulationMethod::Ssa, "ssa", spelling);
    }
    if (normalized == "pla") {
        return detail::decision(SimulationMethod::Pla, "pla", spelling);
    }
    if (normalized == "psa") {
        return detail::decision(SimulationMethod::Psa, "psa", spelling);
    }
    if (normalized == "nf") {
        return detail::decision(SimulationMethod::Nf, "nf", spelling);
    }
    return std::nullopt;
}

// As above, but an unsupported spelling is an error whose message quotes the
// source spelling.
inline SimulationMethodDecision decideSimulationMethod(const ast::Action& action) {
    const auto selected = tryDecideSimulationMethod(action);
    if (!selected.has_value()) {
        const auto name = detail::lowercase(action.name);
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

// The options a method can honour.
SimulationOptionSupport optionSupportFor(SimulationMethod method);

// Reject the requested options that the selected method cannot honour.  The
// diagnostic names the option and the method family that supports it, so
// every surface that asks for an unsupported option refuses it the same way.
void validateSimulationOptions(SimulationMethod method,
                                const SimulationOptionSupport& requested);

// The method an engine name ("cvode", "ssa", ...) selects.
std::optional<SimulationMethod> simulationMethodForEngineName(
    const std::string& engineName);

} // namespace bng::compile
