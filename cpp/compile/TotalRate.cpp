#include "compile/TotalRate.hpp"

#include <algorithm>
#include <cctype>

#include "ast/Model.hpp"
#include "ast/ReactionRule.hpp"

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
constexpr const char* kReverseSuffix = "_reverse";

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

namespace {

bool hasRule(const ast::Model& model, const std::string& ruleName) {
    return std::any_of(
        model.getReactionRules().begin(), model.getReactionRules().end(),
        [&](const ast::ReactionRule& rule) { return rule.getRuleName() == ruleName; });
}

} // namespace

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
    const std::string reverseSuffix = kReverseSuffix;
    if (resolved.name.size() > reverseSuffix.size() &&
        resolved.name.compare(resolved.name.size() - reverseSuffix.size(),
                              reverseSuffix.size(), reverseSuffix) == 0) {
        resolved.name.erase(resolved.name.size() - reverseSuffix.size());
    }
    return resolved;
}

bool isTotalRateReaction(const ast::Model& model, const std::string& originRuleName) {
    if (originRuleName.empty()) return false;
    // The origin names the rule directly when the model declares a rule with
    // that name.  The Atomizer emits the two directions of a step whose rate
    // is a total rate in one direction only as two rules whose names end in
    // "_forward" and "_reverse", and each of them keeps its own modifiers.
    if (hasRule(model, originRuleName))
        return isTotalRateRule(model, originRuleName);
    const auto origin = resolveOriginRule(originRuleName);
    if (origin.name.empty()) return false;
    return isTotalRateRule(model, origin.name);
}

} // namespace bng::compile
