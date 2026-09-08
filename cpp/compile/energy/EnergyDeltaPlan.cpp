#include "EnergyDeltaPlan.hpp"

#include <cmath>
#include <limits>
#include <utility>

namespace bng::compile::energy {

bool EnergyCondition::operator==(const EnergyCondition& other) const {
    return kind == other.kind && reactantIndex == other.reactantIndex &&
           moleculeType == other.moleculeType &&
           componentName == other.componentName &&
           expectedBound == other.expectedBound &&
           partnerType == other.partnerType &&
           partnerComponent == other.partnerComponent &&
           expectedState == other.expectedState &&
           sourceFactorIndices == other.sourceFactorIndices;
}

bool EnergyTerm::operator==(const EnergyTerm& other) const {
    return energyValue == other.energyValue && conditionMask == other.conditionMask &&
           sourceFactorIndex == other.sourceFactorIndex;
}

EnergyDeltaPlan EnergyDeltaPlan::constant(double baseEnergy) {
    EnergyDeltaPlan plan;
    if (!std::isfinite(baseEnergy)) return materializedFallback();
    plan.strategy_ = EnergyDeltaStrategy::Constant;
    plan.baseEnergy_ = baseEnergy;
    return plan;
}

std::optional<EnergyDeltaPlan> EnergyDeltaPlan::factorized(
    double baseEnergy,
    std::vector<EnergyCondition> conditions,
    std::vector<EnergyTerm> terms,
    std::size_t maxConditions) {
    if (!std::isfinite(baseEnergy) || conditions.size() > maxConditions ||
        conditions.size() >= 64) {
        return std::nullopt;
    }

    if (terms.empty()) return constant(baseEnergy);
    if (conditions.empty()) return std::nullopt;

    const std::uint64_t validMask =
        conditions.size() == 64
            ? std::numeric_limits<std::uint64_t>::max()
            : ((std::uint64_t{1} << conditions.size()) - 1);

    for (const auto& condition : conditions) {
        if (condition.kind != ConditionKind::Bond && condition.kind != ConditionKind::State)
            return std::nullopt;
        if (condition.reactantIndex < 0 || condition.moleculeType.empty() ||
            condition.componentName.empty()) {
            return std::nullopt;
        }
        if (condition.kind == ConditionKind::Bond) {
            // An occupancy-only predicate is valid without a named partner.
            // If one partner field is present, require both for deterministic
            // lowering rather than silently weakening the predicate.
            if (condition.partnerType.empty() != condition.partnerComponent.empty()) {
                return std::nullopt;
            }
        } else if (condition.kind == ConditionKind::State &&
                   condition.expectedState.empty()) {
            return std::nullopt;
        }
    }

    for (const auto& term : terms) {
        if (!std::isfinite(term.energyValue) || term.conditionMask == 0 ||
            (term.conditionMask & ~validMask) != 0) {
            return std::nullopt;
        }
    }

    EnergyDeltaPlan plan;
    plan.strategy_ = EnergyDeltaStrategy::BitmaskFactorized;
    plan.baseEnergy_ = baseEnergy;
    plan.conditions_ = std::move(conditions);
    plan.terms_ = std::move(terms);
    return plan;
}

EnergyDeltaPlan EnergyDeltaPlan::materializedFallback() {
    EnergyDeltaPlan plan;
    plan.strategy_ = EnergyDeltaStrategy::MaterializedFallback;
    return plan;
}

std::uint64_t EnergyDeltaPlan::validConditionMask() const {
    if (conditions_.empty()) return 0;
    if (conditions_.size() >= 64) return std::numeric_limits<std::uint64_t>::max();
    return (std::uint64_t{1} << conditions_.size()) - 1;
}

bool EnergyDeltaPlan::maskIsValid(std::uint64_t conditionMask) const {
    if (!isExecutable()) return false;
    return (conditionMask & ~validConditionMask()) == 0;
}

std::optional<double> EnergyDeltaPlan::tryDeltaG(
    std::uint64_t conditionMask) const {
    if (!maskIsValid(conditionMask)) return std::nullopt;

    double deltaG = baseEnergy_;
    for (const auto& term : terms_) {
        if ((conditionMask & term.conditionMask) == term.conditionMask) {
            deltaG += term.energyValue;
        }
    }
    if (!std::isfinite(deltaG)) return std::nullopt;
    return deltaG;
}

std::optional<double> EnergyDeltaPlan::tryArrheniusFactor(
    std::uint64_t conditionMask,
    double phi,
    double RT,
    bool isForward) const {
    if (!std::isfinite(phi) || !std::isfinite(RT) || RT <= 0.0) {
        return std::nullopt;
    }
    const auto deltaG = tryDeltaG(conditionMask);
    if (!deltaG.has_value()) return std::nullopt;

    const double coefficient = isForward ? phi : (phi - 1.0);
    const double factor = std::exp(-(coefficient * *deltaG) / RT);
    if (!std::isfinite(factor)) return std::nullopt;
    return factor;
}

std::optional<std::vector<double>> EnergyDeltaPlan::buildArrheniusTable(
    double phi,
    double RT,
    bool isForward,
    std::size_t maxConditions) const {
    if (!isExecutable() || conditions_.size() > maxConditions ||
        conditions_.size() >= sizeof(std::size_t) * 8) {
        return std::nullopt;
    }

    const std::size_t count = std::size_t{1} << conditions_.size();
    std::vector<double> table;
    table.reserve(count);
    for (std::size_t mask = 0; mask < count; ++mask) {
        const auto factor = tryArrheniusFactor(
            static_cast<std::uint64_t>(mask), phi, RT, isForward);
        if (!factor.has_value()) return std::nullopt;
        table.push_back(*factor);
    }
    return table;
}

std::optional<int> EnergyDeltaPlan::singleReactantIndex() const {
    if (conditions_.empty()) return std::nullopt;
    const int reactantIndex = conditions_.front().reactantIndex;
    for (const auto& condition : conditions_) {
        if (condition.reactantIndex != reactantIndex) return std::nullopt;
    }
    return reactantIndex;
}

std::uint64_t EnergyDeltaPlan::predicateMaskForReactant(int reactantIndex) const {
    std::uint64_t result = 0;
    for (std::size_t index = 0; index < conditions_.size(); ++index) {
        if (conditions_[index].reactantIndex == reactantIndex) {
            result |= (std::uint64_t{1} << index);
        }
    }
    return result;
}

} // namespace bng::compile::energy
