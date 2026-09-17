#include "FiniteBackend.hpp"

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <functional>
#include <stdexcept>
#include <string>
#include <type_traits>

#include "BngsimAdapter.hpp"
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

std::vector<std::string> collectSemanticBlockers(
    const ast::Model& model,
    const GeneratedNetwork& network) {
    std::vector<std::string> blockers;
    if (!model.getCompartments().empty()) {
        blockers.push_back("BNGsim adapter rejected model: compartments require a volume-aware bridge");
    }
    if (!model.getEnergyPatterns().empty()) {
        blockers.push_back("BNGsim adapter rejected model: energy patterns require an eBNGL rate bridge");
    }
#if __has_include("ast/BarrierPattern.hpp")
    if (!model.getBarrierPatterns().empty()) {
        blockers.push_back("BNGsim adapter rejected model: barrier patterns require an eBNGL rate bridge");
    }
    for (const auto& rule : model.getReactionRules()) {
        if (rule.hasDrivingWork()) {
            blockers.push_back(
                "BNGsim adapter rejected model: driven_by() reservoir work requires an eBNGL rate bridge");
            break;
        }
    }
#else
    (void)model; // silence unused warning when barrier/driven not present
#endif
    if (!model.getPopulationMaps().empty()) {
        blockers.push_back(
            "BNGsim adapter rejected model: population maps are not a generated-network feature");
    }
    if (!model.getSimulationProtocol().empty()) {
        blockers.push_back("BNGsim adapter rejected model: simulation protocol requires a protocol bridge");
    }
    for (const auto& action : model.getActions()) {
        if (action.name != "generate_network") {
            blockers.push_back(
                "BNGsim adapter rejected model action '" + action.name +
                "': action execution requires a protocol bridge");
            break;
        }
    }
    for (const auto& function : model.getFunctions()) {
        if (!function.getArgs().empty()) {
            blockers.push_back(
                "BNGsim adapter rejected function '" + function.getName() +
                "': function arguments require a local-function bridge");
            break;
        }
    }
    // Rate-law and TFUN checks require the generated network; reuse the same
    // messages as BngsimAdapter.cpp but do not require BNGsim headers.
    for (std::size_t idx = 0; idx < network.reactions.size(); ++idx) {
        const auto& reaction = network.reactions.all()[idx];
        const auto& rateLaw = reaction.getRateLaw();
        // Check non-reference rate expressions
        if (!model.getParameters().contains(rateLaw)) {
            bool isFunction = false;
            for (const auto& function : model.getFunctions()) {
                if (function.getName() == rateLaw) { isFunction = true; break; }
            }
            if (!isFunction) {
                blockers.push_back(
                    "BNGsim adapter rejected reaction " + std::to_string(idx) +
                    ": rate law '" + rateLaw + "' is not a direct parameter or function reference");
                break;
            }
        }
    }
    for (const auto& function : model.getFunctions()) {
        const auto& expr = function.getExpression();
        // Walk expression tree for relative TFUN paths
        std::function<void(const ast::Expression&)> visit = [&](const ast::Expression& e) {
            if (e.kind() == ast::ExpressionKind::TableFunction) {
                if (!e.tableFilePath().empty()) {
                    // Need filesystem check for absoluteness — replicate adapter's check.
                    // Use string prefix heuristic when filesystem not available.
                    const auto& p = e.tableFilePath();
                    bool isAbs = !p.empty() && p[0] == '/';
                    if (!isAbs) {
#ifdef __has_include
#if __has_include(<filesystem>)
                        try {
                            if (!std::filesystem::path(p).is_absolute()) isAbs = false;
                            else isAbs = true;
                        } catch (...) {}
#endif
#endif
                        if (!isAbs) {
                            blockers.push_back(
                                "BNGsim adapter rejected TFUN: relative table path requires source-directory provenance");
                        }
                    }
                }
            }
            for (const auto& arg : e.args()) visit(arg);
        };
        visit(expr);
        if (!blockers.empty() && blockers.back().find("relative table path") != std::string::npos) break;
    }
    return blockers;
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

BngsimLoweringCheck checkBngsimLowering(
    const ast::Model& model,
    const GeneratedNetwork& network) {
    BngsimLoweringCheck check;
    // Always collect semantic blockers so Python/tests get precise diagnostics
    // even when the BNGsim build is unavailable.
    auto semanticBlockers = collectSemanticBlockers(model, network);
    if (!semanticBlockers.empty()) {
        check.supported = false;
        check.blockers = std::move(semanticBlockers);
        // If BNGsim is also unavailable, prepend that fact for completeness.
        if (!isBngsimAvailable()) {
            check.blockers.insert(
                check.blockers.begin(),
                "BNGsim backend unavailable: build without BUILD_BNGSIM_ADAPTER");
        }
        return check;
    }
    if (!isBngsimAvailable()) {
        check.supported = false;
        check.blockers.push_back("BNGsim backend unavailable: build without BUILD_BNGSIM_ADAPTER");
        return check;
    }
#ifdef BNG3_HAS_BNGSIM_ADAPTER
    try {
        // buildBngsimNetwork is the single lowering boundary; it throws with
        // precise "BNGsim adapter rejected …" messages on unsupported forms.
        auto tmp = buildBngsimNetwork(model, network);
        (void)tmp;
        check.supported = true;
    } catch (const std::exception& ex) {
        check.supported = false;
        check.blockers.push_back(ex.what());
    } catch (...) {
        check.supported = false;
        check.blockers.push_back("BNGsim adapter rejected model: unknown lowering failure");
    }
#else
    check.supported = false;
    check.blockers.push_back("BNGsim backend unavailable: build without BUILD_BNGSIM_ADAPTER");
#endif
    return check;
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
        if (check.supported) return FiniteBackend::Bngsim;
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
