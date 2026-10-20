#pragma once

#include <string>
#include <vector>

namespace bng::ast { class Model; }
namespace bng::engine {
struct GeneratedNetwork;
struct OdeOptions;
struct OdeResult;
} // namespace bng::engine

namespace bng::engine {

// Finite-network numerical backend. BNG3 owns BNGL semantics; the backend
// owns finite-network numerical execution for the generated network.
enum class FiniteBackend {
    Native = 0,
    Bngsim = 1,
    Auto = 2,
};

// Stable route identifiers for a finite-backend routing decision.  A route is
// recorded with every finite-network result so that a native route is never
// implicit (ADR 0003).  Keep the identifiers stable: qualification harnesses
// compare them by name.
namespace finite_backend_route {

// The native backend was requested explicitly.
inline constexpr const char kNativeExplicit[] = "native-explicit";
// The BNGsim backend was requested explicitly and the network is lowerable.
inline constexpr const char kBngsimExplicit[] = "bngsim-explicit";
// BNGsim was wanted but the generated network is not faithfully lowerable.
inline constexpr const char kFallbackUnsupported[] =
    "native-fallback:unsupported-semantics";
// BNGsim was wanted but the adapter is not linked into this build.
inline constexpr const char kFallbackUnavailable[] =
    "native-fallback:bngsim-unavailable";
// BNGsim was wanted but does not claim the requested method.
inline constexpr const char kFallbackMethodNotClaimed[] =
    "native-fallback:method-not-claimed";
// The automatic route resolved to the native backend because the ADR 0003
// migration policy keeps the native backend as the default.
inline constexpr const char kPolicyAutoNative[] =
    "native-policy:auto-native-during-migration";

} // namespace finite_backend_route

// What the current build can execute via BNGsim (availability + version).
struct BngsimCapabilities {
    bool available = false;
    std::string version; // pinned revision or "unavailable"
    bool supportsOde = false;
    bool supportsSsa = false;
    bool supportsPsa = false;
    bool supportsPla = false;
};

// Whether *this particular* generated network can be faithfully lowered.
// This semantic decision is independent of whether the external solver was
// linked into the current build; inspect BngsimCapabilities::available for that.
struct BngsimLoweringCheck {
    bool supported = false;
    std::vector<std::string> blockers; // each is an adapter rejection message
};

// The named decision that selected a finite-network backend.  `route` states
// which decision was taken and `reason` why; the remaining fields retain the
// facts behind it so a native route can be audited rather than merely
// observed.
struct FiniteBackendDecision {
    FiniteBackend backend = FiniteBackend::Native;
    std::string route;   // stable route identifier
    std::string reason;  // human-readable justification
    std::string method;  // requested finite method ("ode", "ssa", "pla", "psa")
    bool bngsimAvailable = false;
    bool bngsimLoweringChecked = false; // whether the semantic check was run
    bool bngsimLowerable = false;       // meaningful when the check was run
    std::string bngsimVersion;
    std::vector<std::string> blockers; // lowering blockers, when any
};

// Capability queries — never throw.
BngsimCapabilities getBngsimCapabilities();
bool isBngsimAvailable();
std::string bngsimVersion();

// Semantic lowering check — never throws and does not depend on solver availability.
BngsimLoweringCheck checkBngsimLowering(
    const ast::Model& model,
    const GeneratedNetwork& network);

// Parse helpers for Python/env-opt-in layer.
FiniteBackend finiteBackendFromString(const std::string& name);
std::string finiteBackendToString(FiniteBackend backend);

// Whether the BNGsim backend claims the named finite method.
bool bngsimClaimsMethod(const std::string& method);

// Resolve the effective backend and record the decision.  Never throws: a
// BNGsim request that cannot be honoured resolves to the native backend with
// a named fallback route, so the caller can fail closed on an explicit
// request instead of running native silently.
FiniteBackendDecision resolveFiniteBackend(
    FiniteBackend requested,
    const std::string& method,
    const ast::Model& model,
    const GeneratedNetwork& network);

// High-level dispatch helpers — route to the appropriate engine.
// These are the narrow lowering boundary callers in C++; Python's
// model.simulate() is the primary dispatch point and may call these.
OdeResult simulateFiniteOde(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const OdeOptions& options,
    FiniteBackend backend);

OdeResult simulateFiniteSsa(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const OdeOptions& options,
    FiniteBackend backend);

} // namespace bng::engine
