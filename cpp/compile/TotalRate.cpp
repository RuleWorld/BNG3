#include "compile/TotalRate.hpp"

#include <algorithm>
#include <cctype>

#include "ast/Model.hpp"
#include "ast/ReactionRule.hpp"
#include "ast/Rxn.hpp"

namespace bng::compile {

namespace {

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char character) {
        return static_cast<char>(std::tolower(character));
    });
    return value;
}

// The markers the network generator and the writers use for a rule that is
// not the rule's own name.
constexpr const char* kReversePrefix = "_reverse__";
constexpr const char* kAlternateReversePrefix = "__reverse__";

} // namespace

bool isTotalRateModifier(const std::string& modifier) {
    return lower(modifier) == "totalrate";
}

bool isTotalRateMarkerName(const std::string& markerName) {
    return lower(markerName).find("totalrate") != std::string::npos;
}

bool hasTotalRateModifier(const std::vector<std::string>& modifiers) {
    return std::any_of(
        modifiers.begin(), modifiers.end(),
        [](const std::string& modifier) { return isTotalRateModifier(modifier); });
}

bool isTotalRateRule(const ast::ReactionRule& rule) {
    return hasTotalRateModifier(rule.getModifiers());
}

bool isTotalRateRule(const ast::Model& model, const std::string& ruleName) {
    for (const auto& rule : model.getReactionRules()) {
        if (rule.getRuleName() != ruleName) continue;
        return isTotalRateRule(rule);
    }
    return false;
}

OriginRule resolveOriginRule(const std::string& originRuleName) {
    OriginRule resolved;
    resolved.name = originRuleName;
    const std::string reversePrefix = kReversePrefix;
    const std::string alternateReversePrefix = kAlternateReversePrefix;
    if (resolved.name.rfind(reversePrefix, 0) == 0) {
        resolved.reverse = true;
        resolved.name.erase(0, reversePrefix.size());
    } else if (resolved.name.rfind(alternateReversePrefix, 0) == 0) {
        resolved.reverse = true;
        resolved.name.erase(0, alternateReversePrefix.size());
    } else if (!resolved.name.empty() && resolved.name.front() == '_') {
        resolved.name.erase(0, 1);
    }
    return resolved;
}

bool isTotalRateReaction(const ast::Model& model, const std::string& originRuleName) {
    if (originRuleName.empty()) return false;
    // The Atomizer emits the two directions of a step whose rate is a total
    // rate in one direction only as two rules whose names end in "_forward"
    // and "_reverse", and each of them keeps its own modifiers; a consumer
    // that stripped a trailing "_reverse" from the name would take the
    // capability from the other direction.
    // An exact model identity is authoritative whether or not it has the
    // modifier.  Only normalize the network marker when no rule has that
    // exact name; otherwise a legal rule such as ``_foo`` could inherit the
    // capability of a different rule named ``foo``.
    for (const auto& rule : model.getReactionRules()) {
        if (rule.getRuleName() == originRuleName) {
            return isTotalRateRule(rule);
        }
    }
    const auto origin = resolveOriginRule(originRuleName);
    if (origin.name.empty() || origin.name == originRuleName) return false;
    return isTotalRateRule(model, origin.name);
}

bool isAbsoluteFluxReaction(const ast::Model& model,
                            const std::string& originRuleName) {
    if (originRuleName.empty()) return false;
    for (const auto& rule : model.getReactionRules()) {
        if (rule.getRuleName() == originRuleName) {
            return rule.isAbsoluteFlux() && isTotalRateRule(rule);
        }
    }
    const auto origin = resolveOriginRule(originRuleName);
    if (origin.name.empty() || origin.name == originRuleName) return false;
    for (const auto& rule : model.getReactionRules()) {
        if (rule.getRuleName() == origin.name) {
            return rule.isAbsoluteFlux() && isTotalRateRule(rule);
        }
    }
    return false;
}

bool isAbsoluteFluxReaction(const ast::Model& model, const ast::Rxn& reaction) {
    return reaction.isAbsoluteFlux() ||
           isAbsoluteFluxReaction(model, reaction.getOriginRuleName());
}

std::string absoluteFluxRuleNames(const ast::Model& model) {
    std::string names;
    for (const auto& rule : model.getReactionRules()) {
        if (!rule.isAbsoluteFlux()) continue;
        if (!names.empty()) names += ',';
        auto key = rule.getLabel().empty() ? rule.getRuleName() : rule.getLabel();
        if (!key.empty() && key.back() == ':') key.pop_back();
        names += key;
    }
    return names;
}

} // namespace bng::compile
