#include "BarrierPattern.hpp"

#include <utility>

namespace bng::ast {

BarrierPattern::BarrierPattern(std::string label, ReactionRule transition)
    : label_(std::move(label)),
      transition_(std::make_unique<ReactionRule>(std::move(transition))) {
    // The normalizer places the barrier energy in the rate-law position, so a
    // well-formed barrier pattern always carries exactly one rate expression.
    if (!transition_->getRates().empty()) {
        expression_ = transition_->getRates().front();
        hasExpression_ = true;
    }
}

BarrierPattern::~BarrierPattern() = default;
BarrierPattern::BarrierPattern(BarrierPattern&&) noexcept = default;
BarrierPattern& BarrierPattern::operator=(BarrierPattern&&) noexcept = default;

const std::string& BarrierPattern::getLabel() const {
    return label_;
}

const Expression& BarrierPattern::expression() const {
    return expression_;
}

bool BarrierPattern::hasExpression() const {
    return hasExpression_;
}

const ReactionRule& BarrierPattern::transition() const {
    return *transition_;
}

ReactionRule& BarrierPattern::transition() {
    return *transition_;
}

std::string BarrierPattern::toString() const {
    std::string result;
    if (!label_.empty()) result += label_ + ": ";
    const auto& reactants = transition_->getReactants();
    for (std::size_t index = 0; index < reactants.size(); ++index) {
        if (index != 0) result += " + ";
        result += reactants[index];
    }
    result += transition_->isBidirectional() ? " <-> " : " -> ";
    const auto& products = transition_->getProducts();
    for (std::size_t index = 0; index < products.size(); ++index) {
        if (index != 0) result += " + ";
        result += products[index];
    }
    if (hasExpression_) result += " " + expression_.toString();
    return result;
}

} // namespace bng::ast
