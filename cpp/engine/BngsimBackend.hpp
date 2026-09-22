#pragma once

#include "OdeIntegrator.hpp"

namespace bng::engine {

// BNGsim-backed finite-network execution.  Only available when the build
// was configured with BUILD_BNGSIM_ADAPTER=ON and a pinned external BNGsim.
// All functions fail closed with a precise unsupported-capability message
// when the model cannot be faithfully lowered.

#ifdef BNG3_HAS_BNGSIM_ADAPTER

// ODE via BNGsim CVODE (in-memory, no .net serialization).
// Throws std::runtime_error with "BNGsim adapter rejected …" on lowering
// failure or with "BNGsim numerical failure: …" on solver failure.
OdeResult simulateOdeViaBngsim(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const OdeOptions& options);

// SSA via BNGsim (when the external API exposes it; otherwise throws
// with an explicit capability message and caller should fall back).
OdeResult simulateSsaViaBngsim(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const OdeOptions& options);

// Introspection helpers for the capability layer.
std::string bngsimPinnedVersion();
bool bngsimSupportsOde();
bool bngsimSupportsSsa();
bool bngsimSupportsPsa();

#else // !BNG3_HAS_BNGSIM_ADAPTER

inline OdeResult simulateOdeViaBngsim(
    const ast::Model&, const GeneratedNetwork&, const OdeOptions&) {
    throw std::runtime_error(
        "BNGsim backend unavailable: build without BUILD_BNGSIM_ADAPTER");
}
inline OdeResult simulateSsaViaBngsim(
    const ast::Model&, const GeneratedNetwork&, const OdeOptions&) {
    throw std::runtime_error(
        "BNGsim backend unavailable: build without BUILD_BNGSIM_ADAPTER");
}
inline std::string bngsimPinnedVersion() { return "unavailable"; }
inline bool bngsimSupportsOde() { return false; }
inline bool bngsimSupportsSsa() { return false; }
inline bool bngsimSupportsPsa() { return false; }

#endif

} // namespace bng::engine
