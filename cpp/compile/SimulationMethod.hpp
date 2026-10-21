#pragma once

#include <optional>
#include <string>

namespace bng::ast {
class Action;
}

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

// The method a protocol action selects.  The action's own name selects the
// method for the dedicated actions, and its `method` argument selects it
// otherwise.  An absent `method` argument selects the ODE default.  No
// decision is returned for a spelling that is not supported.
std::optional<SimulationMethodDecision> tryDecideSimulationMethod(
    const ast::Action& action);

// As above, but an unsupported spelling is an error whose message quotes the
// source spelling.
SimulationMethodDecision decideSimulationMethod(const ast::Action& action);

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
