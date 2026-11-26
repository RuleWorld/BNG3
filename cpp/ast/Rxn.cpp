#include "Rxn.hpp"

#include <algorithm>
#include <utility>

namespace bng::ast {

Rxn::Rxn(
    std::string label,
    std::vector<std::size_t> reactants,
    std::vector<std::size_t> products,
    std::string rateLaw,
    double factor,
    std::string originRuleName,
    std::optional<Expression> rateExpression,
    std::optional<Expression> delayExpression,
    bool nonConsuming,
    bool absoluteFlux,
    bool totalRate)
    : label_(std::move(label)),
      reactants_(std::move(reactants)),
      products_(std::move(products)),
      rateLaw_(std::move(rateLaw)),
      factor_(factor),
      originRuleName_(std::move(originRuleName)),
      rateExpression_(std::move(rateExpression)),
      delayExpression_(std::move(delayExpression)),
      nonConsuming_(nonConsuming),
      absoluteFlux_(absoluteFlux),
      totalRate_(totalRate) {
    if (!originRuleName_.empty()) {
        originRuleNames_.push_back(originRuleName_);
    }
}

const std::string& Rxn::getLabel() const {
    return label_;
}

const std::vector<std::size_t>& Rxn::getReactants() const {
    return reactants_;
}

const std::vector<std::size_t>& Rxn::getProducts() const {
    return products_;
}

const std::string& Rxn::getRateLaw() const {
    return rateLaw_;
}

const std::string& Rxn::getOriginRuleName() const {
    return originRuleName_;
}

const std::vector<std::string>& Rxn::getOriginRuleNames() const {
    return originRuleNames_;
}

std::string Rxn::getOriginRuleComment() const {
    if (originRuleNames_.empty()) return originRuleName_;
    std::string joined;
    for (std::size_t i = 0; i < originRuleNames_.size(); ++i) {
        if (i != 0) joined += ",";
        joined += originRuleNames_[i];
    }
    return joined;
}

void Rxn::addOriginRuleName(const std::string& name) {
    if (name.empty()) return;
    if (std::find(originRuleNames_.begin(), originRuleNames_.end(), name) ==
        originRuleNames_.end()) {
        originRuleNames_.push_back(name);
    }
}

double Rxn::getFactor() const {
    return factor_;
}

void Rxn::addFactor(double factor) {
    factor_ += factor;
}

const std::optional<Expression>& Rxn::getRateExpression() const {
    return rateExpression_;
}

const std::optional<Expression>& Rxn::getDelayExpression() const {
    return delayExpression_;
}

bool Rxn::isNonConsuming() const {
    return nonConsuming_;
}

bool Rxn::isAbsoluteFlux() const {
    return absoluteFlux_;
}

bool Rxn::isTotalRate() const {
    return totalRate_;
}

} // namespace bng::ast
