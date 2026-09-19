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
};

// What the current build can do via BNGsim (availability + version).
struct BngsimCapabilities {
    bool available = false;
    std::string version; // pinned revision or "unavailable"
    bool supportsOde = false;
    bool supportsSsa = false;
    bool supportsPsa = false;
    bool supportsPla = false;
};

// Whether *this particular* generated network can be faithfully lowered.
struct BngsimLoweringCheck {
    bool supported = false;
    std::vector<std::string> blockers; // each is an adapter rejection message
};

// Capability queries — never throw.
BngsimCapabilities getBngsimCapabilities();
bool isBngsimAvailable();
std::string bngsimVersion();

// Lowering check — never throws; returns supported=false with blockers on failure.
BngsimLoweringCheck checkBngsimLowering(
    const ast::Model& model,
    const GeneratedNetwork& network);

// Parse helpers for Python/env-opt-in layer.
FiniteBackend finiteBackendFromString(const std::string& name);
std::string finiteBackendToString(FiniteBackend backend);

// Resolve the effective backend given a requested value and the current
// model/network.  "auto" semantics live here:
//   - Bngsim requested but unavailable or unsupported  → Native (with diagnostics)
//   - auto → Bngsim if available+lowerable else Native
// Caller may inspect checkBngsimLowering() for the reason.
FiniteBackend resolveFiniteBackend(
    FiniteBackend requested,
    const ast::Model& model,
    const GeneratedNetwork& network,
    BngsimLoweringCheck* outCheck = nullptr);

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
