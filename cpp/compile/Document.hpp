#pragma once

#include <map>
#include <string>
#include <vector>

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
