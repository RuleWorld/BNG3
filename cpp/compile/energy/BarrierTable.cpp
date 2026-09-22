#include "BarrierTable.hpp"

#include <cmath>
#include <tuple>
#include <utility>

namespace bng::compile::energy {

namespace {

// Orders the two halves of a key so that a barrier is symmetric under
// reversal: A(s~U)->A(s~P) and A(s~P)->A(s~U) must produce the same key.
void sortHalves(
    std::string& firstType, std::string& firstName,
    std::string& secondType, std::string& secondName) {
    if (std::tie(secondType, secondName) < std::tie(firstType, firstName)) {
        std::swap(firstType, secondType);
        std::swap(firstName, secondName);
    }
}

} // namespace

ReactionCenterKey ReactionCenterKey::binding(
    std::string typeA, std::string siteA,
    std::string typeB, std::string siteB) {
    ReactionCenterKey key;
    key.kind = ReactionCenterKind::Binding;
    key.firstType = std::move(typeA);
    key.firstName = std::move(siteA);
    key.secondType = std::move(typeB);
    key.secondName = std::move(siteB);
    sortHalves(key.firstType, key.firstName, key.secondType, key.secondName);
    return key;
}

ReactionCenterKey ReactionCenterKey::stateChange(
    std::string moleculeType, std::string componentName,
    std::string stateA, std::string stateB) {
    ReactionCenterKey key;
    key.kind = ReactionCenterKind::StateChange;
    // For a state change both halves share the molecule type and component;
    // only the state endpoints are ordered.
    key.firstType = moleculeType;
    key.secondType = std::move(moleculeType);
    key.firstName = componentName;
    key.secondName = std::move(componentName);
    if (stateB < stateA) std::swap(stateA, stateB);
    // Endpoint states are appended to the name halves so a single comparison
    // order covers both kinds without a separate field pair.
    key.firstName += "~" + stateA;
    key.secondName += "~" + stateB;
    return key;
}

bool ReactionCenterKey::operator==(const ReactionCenterKey& other) const {
    return kind == other.kind && firstType == other.firstType &&
           firstName == other.firstName && secondType == other.secondType &&
           secondName == other.secondName;
}

bool ReactionCenterKey::operator<(const ReactionCenterKey& other) const {
    return std::tie(kind, firstType, firstName, secondType, secondName) <
           std::tie(other.kind, other.firstType, other.firstName,
                    other.secondType, other.secondName);
}

std::string ReactionCenterKey::toString() const {
    const char* prefix = kind == ReactionCenterKind::Binding ? "bond" : "state";
    return std::string(prefix) + ":" + firstType + "." + firstName + "|" +
           secondType + "." + secondName;
}

bool ReactionCenterKey::parse(const std::string& text, ReactionCenterKey& key) {
    const auto colon = text.find(':');
    if (colon == std::string::npos) return false;
    const auto kindText = text.substr(0, colon);
    const auto body = text.substr(colon + 1);

    ReactionCenterKind kind;
    if (kindText == "bond") {
        kind = ReactionCenterKind::Binding;
    } else if (kindText == "state") {
        kind = ReactionCenterKind::StateChange;
    } else {
        return false;
    }

    const auto bar = body.find('|');
    if (bar == std::string::npos) return false;
    const auto left = body.substr(0, bar);
    const auto right = body.substr(bar + 1);
    if (body.find('|', bar + 1) != std::string::npos) return false;

    const auto split = [](const std::string& half, std::string& type,
                          std::string& name) {
        const auto dot = half.find('.');
        if (dot == std::string::npos || dot == 0 || dot + 1 == half.size()) return false;
        type = half.substr(0, dot);
        name = half.substr(dot + 1);
        return true;
    };

    std::string leftType;
    std::string leftName;
    std::string rightType;
    std::string rightName;
    if (!split(left, leftType, leftName) || !split(right, rightType, rightName)) {
        return false;
    }

    if (kind == ReactionCenterKind::Binding) {
        key = ReactionCenterKey::binding(leftType, leftName, rightType, rightName);
        // Reject a key whose halves were not already canonical: accepting it
        // would silently rewrite the caller's key.
        return key.toString() == text;
    }

    // A state-change key carries the endpoint state after a '~' in each half,
    // and both halves must name the same molecule type and component.
    const auto leftTilde = leftName.find('~');
    const auto rightTilde = rightName.find('~');
    if (leftTilde == std::string::npos || rightTilde == std::string::npos) return false;
    const auto component = leftName.substr(0, leftTilde);
    if (component.empty() || rightName.substr(0, rightTilde) != component) return false;
    if (leftType != rightType) return false;
    const auto leftState = leftName.substr(leftTilde + 1);
    const auto rightState = rightName.substr(rightTilde + 1);
    if (leftState.empty() || rightState.empty()) return false;

    key = ReactionCenterKey::stateChange(leftType, component, leftState, rightState);
    return key.toString() == text;
}

bool BarrierTable::add(
    const ReactionCenterKey& key,
    double barrier,
    const std::string& sourceLabel,
    std::string& diagnostic) {
    if (!std::isfinite(barrier)) {
        diagnostic = "barrier pattern '" + sourceLabel +
                     "' has a non-finite transition-state energy for " +
                     key.toString();
        return false;
    }
    auto& entry = entries_[key];
    entry.barrier += barrier;
    ++entry.contributingPatterns;
    entry.sources.push_back(sourceLabel);
    return true;
}

double BarrierTable::lookup(const ReactionCenterKey& key) const {
    const auto found = entries_.find(key);
    return found == entries_.end() ? 0.0 : found->second.barrier;
}

bool BarrierTable::contains(const ReactionCenterKey& key) const {
    return entries_.find(key) != entries_.end();
}

const BarrierTable::Entry* BarrierTable::find(const ReactionCenterKey& key) const {
    const auto found = entries_.find(key);
    return found == entries_.end() ? nullptr : &found->second;
}

} // namespace bng::compile::energy
