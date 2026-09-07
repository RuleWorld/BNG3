#include "CompiledModel.hpp"

#include <utility>

namespace bng::compile {

CompiledModel::CompiledModel(const ast::Model& model) {
    rules_.reserve(model.getReactionRules().size());
    for (const auto& rule : model.getReactionRules()) {
        rules_.push_back(CompiledRule::compile(rule));
    }

    energyFactors_.reserve(model.getEnergyPatterns().size());
    for (std::size_t index = 0; index < model.getEnergyPatterns().size(); ++index) {
        const auto& factor = model.getEnergyPatterns()[index];
        CompiledEnergyFactor compiled;
        compiled.index = index;
        compiled.label = factor.getLabel();
        compiled.sourcePattern = factor.getPattern();
        compiled.structuralFingerprint = factor.getGraph().fingerprint();
        compiled.energyExpression = factor.getExpression().toString();
        energyFactors_.push_back(std::move(compiled));
    }
}

} // namespace bng::compile
