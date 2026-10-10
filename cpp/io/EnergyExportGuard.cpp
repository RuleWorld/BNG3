#include "EnergyExportGuard.hpp"

#include <stdexcept>
#include <string>

#include "compile/CompiledModel.hpp"

namespace bng::io {

namespace {

// Returns the first unrepresentable construct found, or an empty string.
// Ordered most-specific-first so the message names the construct a user would
// recognize from their source rather than a downstream consequence of it.
std::string firstUnsupportedConstruct(const compile::CompiledModel& model) {
    if (!model.barrierFactors().empty()) {
        return "barrier patterns";
    }
    for (const auto& rule : model.rules()) {
        if (rule.hasDrivingWork()) {
            return "driven_by() reservoir work on rule '" + rule.name() + "'";
        }
    }
    if (!model.energyFactors().empty()) {
        return "energy patterns";
    }
    for (const auto& rule : model.rules()) {
        for (const auto& rate : rule.rateLaws()) {
            const auto& expression = rate.resolvedExpression();
            // RateLawKind also classifies legacy ObservableRef nodes by name.
            // Requiring the resolved built-in call preserves the former
            // top-level Function-only guard boundary without inspecting AST.
            if (rate.isEnergyCoupled() &&
                expression.kind == compile::ResolvedExpressionKind::BuiltinCall &&
                expression.builtin.has_value() &&
                *expression.builtin == compile::BuiltinFunction::Arrhenius) {
                return "an Arrhenius rate law on rule '" + rule.name() + "'";
            }
        }
    }
    return {};
}

} // namespace

bool usesEnergySemantics(const compile::CompiledModel& model) {
    return !firstUnsupportedConstruct(model).empty();
}

void requireNoEnergySemantics(const compile::CompiledModel& model,
                              const std::string& formatName) {
    const auto construct = firstUnsupportedConstruct(model);
    if (construct.empty()) return;
    throw std::runtime_error(
        formatName + " export rejected model: " + construct +
        " cannot be represented in this format. Energy-derived rates are only "
        "resolved by the .net writer and the NFsim backends; exporting here "
        "would silently change the model's kinetics.");
}

bool usesEnergySemantics(const ast::Model& model) {
    const compile::CompiledModel compiled(model);
    return usesEnergySemantics(compiled);
}

void requireNoEnergySemantics(const ast::Model& model, const std::string& formatName) {
    const compile::CompiledModel compiled(model);
    requireNoEnergySemantics(compiled, formatName);
}

} // namespace bng::io
