#include "compile/SimulationMethod.hpp"

#include <stdexcept>

namespace bng::compile {

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
    const auto normalized = detail::lowercase(engineName);
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
