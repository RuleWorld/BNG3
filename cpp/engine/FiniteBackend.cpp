#include "FiniteBackend.hpp"

#include <algorithm>
#include <cctype>
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
    if (n.empty() || n == "auto" || n == "automatic") return FiniteBackend::Native; // auto resolves dynamically; caller should use resolveFiniteBackend
    if (n == "native" || n == "bng3" || n == "default") return FiniteBackend::Native;
    if (n == "bngsim" || n == "bng_sim" || n == "bng-sim") return FiniteBackend::Bngsim;
    throw std::invalid_argument("Unknown finite backend: '" + name + "'. Use 'auto', 'native', or 'bngsim'.");
}

std::string finiteBackendToString(FiniteBackend backend) {
    switch (backend) {
    case FiniteBackend::Native: return "native";
    case FiniteBackend::Bngsim: return "bngsim";
    }
    return "native";
}

FiniteBackend resolveFiniteBackend(
    FiniteBackend requested,
    const ast::Model& model,
    const GeneratedNetwork& network,
    BngsimLoweringCheck* outCheck) {
    if (requested == FiniteBackend::Bngsim) {
        auto check = checkBngsimLowering(model, network);
        if (outCheck) *outCheck = check;
        if (isBngsimAvailable() && check.supported) return FiniteBackend::Bngsim;
        // Explicit bngsim request but unsupported — caller should surface the
        // blocker; we return Native so callers that want fail-closed can throw.
        return FiniteBackend::Native;
    }
    // Native or auto: prefer bngsim when trivially lowerable, otherwise native.
    // Auto semantics are intentionally conservative during migration.
    auto check = checkBngsimLowering(model, network);
    if (outCheck) *outCheck = check;
    // For now "auto" == native to preserve default stability. Phase D will
    // flip auto to prefer bngsim when supported.
    (void)check;
    return FiniteBackend::Native;
}

OdeResult simulateFiniteOde(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const OdeOptions& options,
    FiniteBackend backend) {
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
    if (backend == FiniteBackend::Bngsim) {
        return simulateSsaViaBngsim(model, network, options);
    }
    OdeIntegrator integrator(model, network);
    OdeOptions ssaOpts = options;
    ssaOpts.method = "ssa";
    return integrator.integrate(ssaOpts);
}

} // namespace bng::engine
