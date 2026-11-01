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
        std::optional<std::string> method;
        std::optional<Diagnostic> methodDiagnostic;
        std::optional<double> tStart;
        std::optional<double> tEnd;
        std::optional<Diagnostic> tStartDiagnostic;
        std::optional<Diagnostic> tEndDiagnostic;
        std::optional<std::size_t> nSteps;
        // Action diagnostics are deferred until execution, so unused actions
        // do not invalidate otherwise usable model metadata.
        std::optional<Diagnostic> nStepsDiagnostic;
        std::optional<std::size_t> outputStepInterval;
        std::optional<Diagnostic> outputStepIntervalDiagnostic;
        std::optional<bool> continueSimulation;
        std::optional<bool> printConcentrations;
        std::optional<bool> printFunctions;
        std::optional<bool> printNet;
        std::optional<bool> steadyState;
        std::optional<double> steadyStateTol;
        std::optional<Diagnostic> steadyStateTolDiagnostic;
        std::optional<std::string> stopIf;
        std::vector<double> sampleTimes;
        std::string sampleTimesFile;
        std::optional<Diagnostic> sampleTimesDiagnostic;
        std::optional<std::string> prefix;
        std::optional<unsigned int> seed;
        std::optional<double> rtol;
        std::optional<double> atol;
        std::optional<double> maxStep;
    };
    struct SetParameterOptions {
        std::string target;
        std::optional<double> staticValue;
        // Static action values are validated during compilation, but errors
        // are deferred until the setter executes.
        std::optional<Diagnostic> valueDiagnostic;
    };
    struct SetConcentrationOptions {
        std::string target;
        std::optional<double> staticValue;
        std::optional<Diagnostic> valueDiagnostic;
    };
    struct AddConcentrationOptions {
        std::string target;
        std::optional<double> staticValue;
        std::optional<Diagnostic> valueDiagnostic;
    };
    struct SaveParametersOptions {
        std::string label = "default";
    };
    struct ResetParametersOptions {
        std::string label = "default";
    };
    struct SaveConcentrationsOptions {
        std::string label = "default";
    };
    struct ResetConcentrationsOptions {
        std::string label = "default";
    };
    struct SetVolumeOptions {
        std::string target;
        std::optional<double> staticVolume;
        std::optional<Diagnostic> volumeDiagnostic;
    };
    struct SetOptionOptions {
        std::string option;
        std::string value;
    };
    struct ArgFileOptions {
        std::string file;
    };
    struct WriteModelOptions {
        std::string format;
        std::string prefix;
    };
    std::optional<GenerateNetworkOptions> generateNetworkOptions;
    std::optional<SimulationOptions> simulationOptions;
    std::optional<SetParameterOptions> setParameterOptions;
    std::optional<SetConcentrationOptions> setConcentrationOptions;
    std::optional<AddConcentrationOptions> addConcentrationOptions;
    std::optional<SaveParametersOptions> saveParametersOptions;
    std::optional<ResetParametersOptions> resetParametersOptions;
    std::optional<SaveConcentrationsOptions> saveConcentrationsOptions;
    std::optional<ResetConcentrationsOptions> resetConcentrationsOptions;
    std::optional<SetVolumeOptions> setVolumeOptions;
    std::optional<SetOptionOptions> setOptionOptions;
    std::optional<ArgFileOptions> argFileOptions;
    std::optional<WriteModelOptions> writeModelOptions;
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
