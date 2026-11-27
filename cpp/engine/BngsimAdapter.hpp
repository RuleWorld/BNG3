#pragma once

#include <filesystem>
#include <memory>

#include "FiniteBackend.hpp"
#include "NetworkGenerator.hpp"

namespace bngsim {
class NetworkModel;
}

namespace bng::engine {

// Execution mode used when lowering mode-sensitive constructs (such as
// Atomizer absolute-flux reactions that require reactant-availability
// clamping in stochastic SSA but continuous flux evaluation in ODE).
enum class BngsimExecutionMode {
    Ode,
    Ssa,
    Psa,
};

// Options governing bounded lowering from BNG3's generated network to BNGsim.
// Defaults remain strict and fail-closed for the legacy 2-argument entry points.
struct BngsimLoweringOptions {
    // Optional BNGL source file or directory used to resolve relative TFUN
    // table paths. When empty, relative table paths are rejected fail-closed.
    std::filesystem::path sourcePath;
    // When true, simple inline non-reference reaction rate expressions over
    // BNGsim-supported arithmetic, parameters, observables, nullary functions,
    // and TFUNs are lowered into synthetic nullary Functional rate laws.
    // Unsupported expressions (e.g. local functions or delay()) remain
    // rejected fail-closed.
    bool allowRateExpressionWrapping = false;
    // Target execution mode for mode-sensitive lowering (default: Ode).
    BngsimExecutionMode executionMode = BngsimExecutionMode::Ode;
};

// Semantic lowering check with explicit lowering options (never throws).
BngsimLoweringCheck checkBngsimLowering(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const BngsimLoweringOptions& options);

// Build BNGsim's native model directly from BNG3's generated network. This is
// deliberately bounded: unsupported semantic forms throw before solver use.
// No .net serialization is involved.
std::unique_ptr<bngsim::NetworkModel> buildBngsimNetwork(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const BngsimLoweringOptions& options = {});

} // namespace bng::engine
