#pragma once

#include <vector>

#include "CompiledModel.hpp"
#include "ast/Model.hpp"

namespace bng::compile {

// Execution instructions are intentionally separate from reusable compiled
// model metadata.  This is the first concrete Document/Protocol seam; the AST
// remains the compatibility-facing construction type during migration.
struct SimulationProtocol {
    std::vector<ast::Action> actions;
};

class Document {
public:
    explicit Document(const ast::Model& model);

    const CompiledModel& model() const noexcept { return model_; }
    const SimulationProtocol& protocol() const noexcept { return protocol_; }
    const std::vector<Diagnostic>& diagnostics() const noexcept {
        return model_.diagnostics();
    }
    bool valid() const noexcept;

private:
    CompiledModel model_;
    SimulationProtocol protocol_;
};

} // namespace bng::compile
