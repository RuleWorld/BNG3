#pragma once

#include <cstddef>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "Capabilities.hpp"
#include "CompiledModel.hpp"

namespace bng::ast { class Model; }

namespace bng::compile {

enum class ActionScope {
    Model,
    SimulationProtocol,
};

struct ProtocolAction {
    ActionScope scope = ActionScope::Model;
    std::string name;
    std::map<std::string, std::string> arguments;
    struct GenerateNetworkOptions {
        std::optional<std::size_t> maxIterations;
        // Kept with the typed option so callers that supply an explicit
        // native override can bypass an invalid BNGL action value.
        std::optional<Diagnostic> maxIterationsDiagnostic;
        std::optional<double> maxAggregate;
        std::optional<Diagnostic> maxAggregateDiagnostic;
        using MaxStoichLimits = std::map<std::string, std::optional<double>>;
        // A null per-molecule limit represents the exact `unlimited` sentinel.
        // The optional distinguishes an omitted option from an explicitly empty map.
        std::optional<MaxStoichLimits> maxStoich;
        std::optional<Diagnostic> maxStoichDiagnostic;
    };
    struct SimulationOptions {
        std::optional<std::size_t> nSteps;
        // Action diagnostics are deferred until execution, so unused actions
        // do not invalidate otherwise usable model metadata.
        std::optional<Diagnostic> nStepsDiagnostic;
    };
    struct SetParameterOptions {
        std::optional<double> staticValue;
        // Static action values are validated during compilation, but errors
        // are deferred until the setter executes.
        std::optional<Diagnostic> valueDiagnostic;
    };
    std::optional<GenerateNetworkOptions> generateNetworkOptions;
    std::optional<SimulationOptions> simulationOptions;
    std::optional<SetParameterOptions> setParameterOptions;
};

// Execution instructions are intentionally separate from reusable compiled
// model metadata. Actions are copied into compile-owned value types so
// execution clients do not need parser/AST declarations. Model-level writer/
// generation actions and simulation-protocol actions retain distinct scopes.
struct SimulationProtocol {
    std::vector<ProtocolAction> actions;

    std::vector<ProtocolAction> modelActions() const;
    std::vector<ProtocolAction> simulationActions() const;
};

class Document {
public:
    explicit Document(const ast::Model& model);

    const CompiledModel& model() const noexcept { return model_; }
    const SimulationProtocol& protocol() const noexcept { return protocol_; }
    const std::vector<Diagnostic>& diagnostics() const noexcept {
        return model_.diagnostics();
    }
    bool valid() const noexcept { return model_.valid(); }

private:
    CompiledModel model_;
    SimulationProtocol protocol_;
};

} // namespace bng::compile
