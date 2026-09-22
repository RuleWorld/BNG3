#include "EnergyExportGuard.hpp"

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <string>

#include "ast/Expression.hpp"
#include "ast/Model.hpp"
#include "ast/ReactionRule.hpp"

namespace bng::io {

namespace {

// Matches the spelling accepted elsewhere in the pipeline: NetWriter's
// parseArrhenius and the NFsim adapters both accept either case.
bool isArrheniusRateLaw(const ast::Expression& expression) {
    if (expression.kind() != ast::ExpressionKind::Function) return false;
    std::string name = expression.name();
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    return name == "arrhenius";
}

// Returns the first unrepresentable construct found, or an empty string.
// Ordered most-specific-first so the message names the construct a user would
// recognize from their source rather than a downstream consequence of it.
std::string firstUnsupportedConstruct(const ast::Model& model) {
    if (!model.getBarrierPatterns().empty()) {
        return "barrier patterns";
    }
    for (const auto& rule : model.getReactionRules()) {
        if (rule.hasDrivingWork()) {
            return "driven_by() reservoir work on rule '" + rule.getRuleName() + "'";
        }
    }
    if (!model.getEnergyPatterns().empty()) {
        return "energy patterns";
    }
    for (const auto& rule : model.getReactionRules()) {
        const auto& rates = rule.getRates();
        if (std::any_of(rates.begin(), rates.end(), isArrheniusRateLaw)) {
            return "an Arrhenius rate law on rule '" + rule.getRuleName() + "'";
        }
    }
    return {};
}

} // namespace

bool usesEnergySemantics(const ast::Model& model) {
    return !firstUnsupportedConstruct(model).empty();
}

void requireNoEnergySemantics(const ast::Model& model, const std::string& formatName) {
    const auto construct = firstUnsupportedConstruct(model);
    if (construct.empty()) return;
    throw std::runtime_error(
        formatName + " export rejected model: " + construct +
        " cannot be represented in this format. Energy-derived rates are only "
        "resolved by the .net writer and the NFsim backends; exporting here "
        "would silently change the model's kinetics.");
}

} // namespace bng::io
