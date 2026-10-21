#include "FiniteBackend.hpp"

#include <algorithm>
#include <cctype>
#include <sstream>
#include <stdexcept>
#include <string>

#include "BngsimBackend.hpp"
#include "OdeIntegrator.hpp"

namespace bng::engine {

namespace {
std::string toLowerCopy(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return s;
}
std::string trimCopy(const std::string& s) {
    const auto first = s.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    const auto last = s.find_last_not_of(" \t\r\n");
    return s.substr(first, last - first + 1);
}

std::string joinBlockers(const std::vector<std::string>& blockers) {
    if (blockers.empty()) return "unsupported";
    std::ostringstream joined;
    for (std::size_t index = 0; index < blockers.size(); ++index) {
        if (index != 0) joined << "; ";
        joined << blockers[index];
    }
    return joined.str();
}

} // namespace

BngsimCapabilities getBngsimCapabilities() {
    BngsimCapabilities caps;
#ifdef BNG3_HAS_BNGSIM_ADAPTER
    caps.available = true;
    caps.version = bngsimPinnedVersion();
    caps.supportsOde = bngsimSupportsOde();
    caps.supportsSsa = bngsimSupportsSsa();
    caps.supportsPsa = bngsimSupportsPsa();
    caps.supportsPla = false; // not claimed for BNGsim in this phase
#else
    caps.available = false;
    caps.version = "unavailable";
    caps.supportsOde = false;
    caps.supportsSsa = false;
    caps.supportsPsa = false;
    caps.supportsPla = false;
#endif
    return caps;
}

bool isBngsimAvailable() {
    return getBngsimCapabilities().available;
}

std::string bngsimVersion() {
    return getBngsimCapabilities().version;
}

FiniteBackend finiteBackendFromString(const std::string& name) {
    const auto n = toLowerCopy(trimCopy(name));
    if (n.empty() || n == "auto" || n == "automatic") return FiniteBackend::Auto;
    if (n == "native" || n == "bng3" || n == "default") return FiniteBackend::Native;
    if (n == "bngsim" || n == "bng_sim" || n == "bng-sim") return FiniteBackend::Bngsim;
    throw std::invalid_argument("Unknown finite backend: '" + name + "'. Use 'auto', 'native', or 'bngsim'.");
}

std::string finiteBackendToString(FiniteBackend backend) {
    switch (backend) {
    case FiniteBackend::Native: return "native";
    case FiniteBackend::Bngsim: return "bngsim";
    case FiniteBackend::Auto: return "auto";
    }
    return "native";
}

bool bngsimClaimsMethod(const std::string& method) {
    const auto normalized = toLowerCopy(trimCopy(method));
    return normalized == "ode" || normalized == "ssa";
}

FiniteBackendDecision resolveFiniteBackend(
    FiniteBackend requested,
    const std::string& method,
    const ast::Model& model,
    const GeneratedNetwork& network) {
    FiniteBackendDecision decision;
    decision.method = method;

    const auto capabilities = getBngsimCapabilities();
    decision.bngsimAvailable = capabilities.available;
    decision.bngsimVersion = capabilities.version;

    if (requested == FiniteBackend::Native) {
        decision.backend = FiniteBackend::Native;
        decision.route = finite_backend_route::kNativeExplicit;
        decision.reason = "the native finite backend was requested explicitly";
        return decision;
    }

    if (!bngsimClaimsMethod(method)) {
        decision.backend = FiniteBackend::Native;
        decision.route = finite_backend_route::kFallbackMethodNotClaimed;
        decision.reason =
            "BNGsim backend does not yet support method='" + method + "'";
        return decision;
    }

    // The semantic boundary is a property of the model, not of the build, so
    // an explicit BNGsim request decides it first and names the blocker.
    // The automatic route stays cheap: it is resolved from the build and the
    // migration policy, and the semantic boundary is queried explicitly.
    if (requested == FiniteBackend::Bngsim) {
        const auto check = checkBngsimLowering(model, network);
        decision.bngsimLoweringChecked = true;
        decision.bngsimLowerable = check.supported;
        decision.blockers = check.blockers;
        if (!check.supported) {
            decision.backend = FiniteBackend::Native;
            decision.route = finite_backend_route::kFallbackUnsupported;
            decision.reason =
                "BioNetGen finite-network backend cannot represent model for "
                "BNGsim: " + joinBlockers(check.blockers);
            return decision;
        }
        if (!capabilities.available) {
            decision.backend = FiniteBackend::Native;
            decision.route = finite_backend_route::kFallbackUnavailable;
            decision.reason =
                "BNGsim backend unavailable: build without BUILD_BNGSIM_ADAPTER";
            return decision;
        }
        decision.backend = FiniteBackend::Bngsim;
        decision.route = finite_backend_route::kBngsimExplicit;
        decision.reason =
            "the BNGsim adapter is available and the generated network is "
            "faithfully lowerable";
        return decision;
    }

    if (!capabilities.available) {
        decision.backend = FiniteBackend::Native;
        decision.route = finite_backend_route::kFallbackUnavailable;
        decision.reason =
            "BNGsim backend unavailable: build without BUILD_BNGSIM_ADAPTER";
        return decision;
    }

    // The automatic route keeps the native backend as the default while the
    // ADR 0003 migration is in its Phase A-C state.  The decision is named so
    // the route is never implicit.
    decision.backend = FiniteBackend::Native;
    decision.route = finite_backend_route::kPolicyAutoNative;
    decision.reason =
        "the BNGsim adapter is available and the generated network may be "
        "faithfully lowerable, but the ADR 0003 migration policy keeps the "
        "native finite backend as the default until the differential parity "
        "gate passes";
    return decision;
}

OdeResult simulateFiniteOde(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const OdeOptions& options,
    FiniteBackend backend) {
    if (backend == FiniteBackend::Auto) {
        backend = resolveFiniteBackend(FiniteBackend::Auto, "ode", model, network).backend;
    }
    if (backend == FiniteBackend::Bngsim) {
        return simulateOdeViaBngsim(model, network, options);
    }
    OdeIntegrator integrator(model, network);
    return integrator.integrate(options);
}

OdeResult simulateFiniteSsa(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const OdeOptions& options,
    FiniteBackend backend) {
    if (backend == FiniteBackend::Auto) {
        backend = resolveFiniteBackend(FiniteBackend::Auto, "ssa", model, network).backend;
    }
    if (backend == FiniteBackend::Bngsim) {
        return simulateSsaViaBngsim(model, network, options);
    }
    OdeIntegrator integrator(model, network);
    OdeOptions ssaOpts = options;
    ssaOpts.method = "ssa";
    return integrator.integrate(ssaOpts);
}

} // namespace bng::engine
