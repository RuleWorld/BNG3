#include "Document.hpp"

#include "ast/Model.hpp"

namespace bng::compile {

std::vector<ProtocolAction> SimulationProtocol::modelActions() const {
    std::vector<ProtocolAction> result;
    for (const auto& action : actions)
        if (action.scope == ActionScope::Model) result.push_back(action);
    return result;
}

std::vector<ProtocolAction> SimulationProtocol::simulationActions() const {
    std::vector<ProtocolAction> result;
    for (const auto& action : actions)
        if (action.scope == ActionScope::SimulationProtocol) result.push_back(action);
    return result;
}

Document::Document(const ast::Model& model)
    : model_(model) {
    protocol_.actions.reserve(model.getActions().size() + model.getSimulationProtocol().size());
    for (const auto& action : model.getActions()) {
        protocol_.actions.push_back(
            ProtocolAction{ActionScope::Model, action.name, action.arguments});
    }
    for (const auto& action : model.getSimulationProtocol()) {
        protocol_.actions.push_back(
            ProtocolAction{ActionScope::SimulationProtocol, action.name, action.arguments});
    }
}

} // namespace bng::compile
