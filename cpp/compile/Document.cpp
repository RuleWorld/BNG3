#include "Document.hpp"

namespace bng::compile {

Document::Document(const ast::Model& model)
    : model_(model), protocol_{model.getSimulationProtocol()} {}

bool Document::valid() const noexcept {
    for (const auto& diagnostic : model_.diagnostics()) {
        if (diagnostic.severity == Severity::Error) return false;
    }
    return true;
}

} // namespace bng::compile
