#include "nfnext/family_compiler.hpp"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <map>
#include <sstream>
#include <utility>

namespace nfnext {
namespace {

void mix(std::uint64_t& hash, std::uint64_t value) noexcept {
    hash ^= value + 0x9E3779B97F4A7C15ULL + (hash << 6) + (hash >> 2);
}

void mixString(std::uint64_t& hash, const std::string& value) noexcept {
    for (const unsigned char byte : value) mix(hash, byte);
}

void mixDouble(std::uint64_t& hash, double value) noexcept {
    std::uint64_t bits = 0;
    static_assert(sizeof(bits) == sizeof(value), "unexpected double width");
    std::memcpy(&bits, &value, sizeof(bits));
    mix(hash, bits);
}

bool sameRateLaw(const RateLawIR& a, const RateLawIR& b) noexcept {
    return a.kind == b.kind && a.expression == b.expression;
}

void appendPatternKey(std::ostringstream& out, const PatternIR& pattern) {
    out << "n" << pattern.nodes.size() << ':';
    for (const auto& node : pattern.nodes) {
        out << node.molecule_type << ':' << node.constraints.size() << ':';
        for (const auto& constraint : node.constraints) {
            out << static_cast<unsigned>(constraint.kind) << ':' << constraint.site << ':'
                << constraint.state << ':' << constraint.states.size() << ':';
            for (const auto state : constraint.states) out << state << ',';
        }
        out << ';';
    }
    out << "b" << pattern.bonds.size() << ':';
    for (const auto& bond : pattern.bonds)
        out << bond.first << ':' << bond.first_site << ':' << bond.second << ':'
            << bond.second_site << ';';
    out << "m" << pattern.molecularity.size() << ':';
    for (const auto& constraint : pattern.molecularity)
        out << static_cast<unsigned>(constraint.kind) << ':' << constraint.left << ':'
            << constraint.right << ';';
    out << "a" << pattern.aliases.size() << ':';
    for (const auto& pair : pattern.aliases) out << pair.first << ':' << pair.second << ';';
    out << "c" << pattern.connected_to.size() << ':';
    for (const auto& pair : pattern.connected_to) out << pair.first << ':' << pair.second << ';';
    out << "i" << pattern.interchangeable.size() << ':';
    for (const auto& group : pattern.interchangeable) {
        out << group.size() << ':';
        for (const auto node : group) out << node << ',';
    }
}

bool samePattern(const PatternIR& a, const PatternIR& b) {
    std::ostringstream left;
    std::ostringstream right;
    appendPatternKey(left, a);
    appendPatternKey(right, b);
    return left.str() == right.str();
}

std::int32_t normalized(std::int32_t value, std::uint32_t index) noexcept {
    return static_cast<std::int32_t>(static_cast<std::int64_t>(value) - index);
}

std::int32_t denormalized(std::int32_t value, std::uint32_t index) noexcept {
    return static_cast<std::int32_t>(static_cast<std::int64_t>(value) + index);
}

bool inferCoordinate(const ExpandedRuleIR& rule, std::uint32_t& index) noexcept {
    for (const auto& predicate : rule.predicates) {
        if (predicate.kind != PredicateKind::PositionEq &&
            predicate.kind != PredicateKind::PositionRange)
            continue;
        if (predicate.value < 0) return false;
        index = static_cast<std::uint32_t>(predicate.value);
        return true;
    }
    return false;
}

void appendPredicateKey(std::ostringstream& key, const PredicateIR& p, std::uint32_t index) {
    key << 'p' << static_cast<int>(p.kind) << ':' << p.molecule_type << ':' << p.site << ':';
    if (p.kind == PredicateKind::PositionEq || p.kind == PredicateKind::PositionRange)
        key << normalized(p.value, index);
    else
        key << p.value;
    key << ':';
    if (p.kind == PredicateKind::PositionRange)
        key << normalized(p.aux, index);
    else
        key << p.aux;
    key << ':' << p.state_set.size() << ':';
    for (const auto state : p.state_set) key << state << ',';
    key << ';';
}

std::string shapeKey(const ExpandedRuleIR& rule, std::uint32_t index) {
    std::ostringstream key;
    key << 'r' << static_cast<int>(rule.rate_law.kind) << ':';
    // The expression is appended directly as text; unlike std::hash this is
    // stable across processes and platforms.
    key << rule.rate_law.expression.size() << ':' << rule.rate_law.expression << '|';
    for (const auto& predicate : rule.predicates) appendPredicateKey(key, predicate, index);
    key << '|';
    for (const auto& action : rule.actions) {
        key << 'a' << static_cast<int>(action.kind) << ':' << action.molecule_type << ':'
            << action.site << ':' << action.value << ':' << action.aux << ';';
    }
    key << '|';
    for (const auto& constraint : rule.pattern.molecularity) {
        key << 'm' << static_cast<int>(constraint.kind) << ':' << constraint.left << ':'
            << constraint.right << ';';
    }
    key << '|';
    appendPatternKey(key, rule.pattern);
    return key.str();
}

bool samePredicateShape(const PredicateIR& a, std::uint32_t ai,
                        const PredicateIR& b, std::uint32_t bi) noexcept {
    if (a.kind != b.kind || a.molecule_type != b.molecule_type || a.site != b.site ||
        a.state_set != b.state_set)
        return false;
    const bool coordinate = a.kind == PredicateKind::PositionEq ||
                            a.kind == PredicateKind::PositionRange;
    if ((coordinate && normalized(a.value, ai) != normalized(b.value, bi)) ||
        (!coordinate && a.value != b.value))
        return false;
    if (a.kind == PredicateKind::PositionRange)
        return normalized(a.aux, ai) == normalized(b.aux, bi);
    return a.aux == b.aux;
}

bool sameRuleShape(const ExpandedRuleIR& a, std::uint32_t ai,
                   const ExpandedRuleIR& b, std::uint32_t bi) noexcept {
    if (!sameRateLaw(a.rate_law, b.rate_law) || a.predicates.size() != b.predicates.size() ||
        a.actions.size() != b.actions.size() || !samePattern(a.pattern, b.pattern))
        return false;
    for (std::size_t i = 0; i < a.predicates.size(); ++i)
        if (!samePredicateShape(a.predicates[i], ai, b.predicates[i], bi)) return false;
    for (std::size_t i = 0; i < a.actions.size(); ++i) {
        const auto& x = a.actions[i];
        const auto& y = b.actions[i];
        if (x.kind != y.kind || x.molecule_type != y.molecule_type || x.site != y.site ||
            x.value != y.value || x.aux != y.aux)
            return false;
    }
    return true;
}

std::string rejectionReason(const ExpandedRuleIR& a, std::uint32_t ai,
                            const ExpandedRuleIR& b, std::uint32_t bi) {
    if (!sameRateLaw(a.rate_law, b.rate_law)) return "rate-law mismatch";
    if (a.predicates.size() != b.predicates.size()) return "predicate count mismatch";
    for (std::size_t i = 0; i < a.predicates.size(); ++i)
        if (!samePredicateShape(a.predicates[i], ai, b.predicates[i], bi))
            return "predicate mismatch";
    if (a.actions.size() != b.actions.size()) return "action count mismatch";
    for (std::size_t i = 0; i < a.actions.size(); ++i) {
        const auto& x = a.actions[i];
        const auto& y = b.actions[i];
        if (x.kind != y.kind || x.molecule_type != y.molecule_type || x.site != y.site ||
            x.value != y.value || x.aux != y.aux)
            return "action mismatch";
    }
    if (!samePattern(a.pattern, b.pattern)) return "pattern mismatch";
    return "semantic shape mismatch";
}

RuleFamilyIR singleton(const ExpandedRuleIR& rule) {
    RuleFamilyIR family;
    family.name = rule.name;
    family.default_rate = rule.rate;
    family.rate_law = rule.rate_law;
    family.predicates = rule.predicates;
    family.actions = rule.actions;
    family.pattern = rule.pattern;
    family.source_rules.push_back(rule.id);
    return family;
}

RuleFamilyIR merged(const std::vector<const ExpandedRuleIR*>& rules,
                    std::uint32_t begin, std::uint32_t end) {
    const auto& first = *rules.front();
    RuleFamilyIR family;
    family.name = stripTrailingIndex(first.name);
    family.begin_index = begin;
    family.end_index = end;
    family.default_rate = first.rate;
    family.rate_law = first.rate_law;
    family.predicates = first.predicates;
    family.actions = first.actions;
    family.pattern = first.pattern;
    family.coordinate_parameterized = true;
    family.indexed_rates.reserve(rules.size());
    family.source_rules.reserve(rules.size());
    for (const auto* rule : rules) {
        family.indexed_rates.push_back(rule->rate);
        family.source_rules.push_back(rule->id);
    }
    for (auto& predicate : family.predicates) {
        if (predicate.kind == PredicateKind::PositionEq ||
            predicate.kind == PredicateKind::PositionRange)
            predicate.value = normalized(predicate.value, begin);
        if (predicate.kind == PredicateKind::PositionRange)
            predicate.aux = normalized(predicate.aux, begin);
    }
    return family;
}

void mixPredicate(std::uint64_t& hash, const PredicateIR& predicate) noexcept {
    mix(hash, static_cast<std::uint8_t>(predicate.kind));
    mix(hash, predicate.molecule_type);
    mix(hash, predicate.site);
    mix(hash, static_cast<std::uint32_t>(predicate.value));
    mix(hash, static_cast<std::uint32_t>(predicate.aux));
    mix(hash, predicate.state_set.size());
    for (const auto state : predicate.state_set) mix(hash, static_cast<std::uint32_t>(state));
}

void mixFamily(std::uint64_t& hash, const RuleFamilyIR& family) noexcept {
    mix(hash, family.begin_index);
    mix(hash, family.end_index);
    mix(hash, family.coordinate_parameterized ? 1 : 0);
    mix(hash, static_cast<std::uint8_t>(family.rate_law.kind));
    mixString(hash, family.rate_law.expression);
    mixDouble(hash, family.default_rate);
    for (const auto rate : family.indexed_rates) mixDouble(hash, rate);
    for (const auto& predicate : family.predicates) mixPredicate(hash, predicate);
    for (const auto& action : family.actions) {
        mix(hash, static_cast<std::uint8_t>(action.kind));
        mix(hash, action.molecule_type);
        mix(hash, action.site);
        mix(hash, static_cast<std::uint32_t>(action.value));
        mix(hash, static_cast<std::uint32_t>(action.aux));
    }
    for (const auto& constraint : family.pattern.molecularity) {
        mix(hash, static_cast<std::uint8_t>(constraint.kind));
        mix(hash, constraint.left);
        mix(hash, constraint.right);
    }
    std::ostringstream pattern;
    appendPatternKey(pattern, family.pattern);
    mixString(hash, pattern.str());
}

} // namespace

std::uint64_t FamilyCompileResult::semanticFingerprint() const noexcept {
    std::uint64_t hash = 0xCBF29CE484222325ULL;
    for (const auto& family : families) mixFamily(hash, family);
    return hash;
}

FamilyCompileResult compileRuleFamilies(const std::vector<ExpandedRuleIR>& rules,
                                        const FamilyCompileOptions& options) {
    struct IndexedRef {
        const ExpandedRuleIR* rule;
        std::uint32_t index;
    };

    std::map<std::string, std::vector<IndexedRef>> groups;
    std::vector<const ExpandedRuleIR*> singletons;
    std::vector<IndexedRef> indexed;
    for (const auto& rule : rules) {
        std::uint32_t index = 0;
        if (!inferCoordinate(rule, index) && stripTrailingIndex(rule.name, &index) == rule.name) {
            singletons.push_back(&rule);
        } else {
            indexed.push_back({&rule, index});
            groups[shapeKey(rule, index)].push_back({&rule, index});
        }
    }

    FamilyCompileResult result;
    result.stats.input_rules = rules.size();
    for (auto& entry : groups) {
        auto& group = entry.second;
        std::sort(group.begin(), group.end(), [](const IndexedRef& a, const IndexedRef& b) {
            if (a.index != b.index) return a.index < b.index;
            return a.rule->id < b.rule->id;
        });
        for (std::size_t start = 0; start < group.size();) {
            std::size_t end = start + 1;
            while (end < group.size() && group[end].index == group[end - 1].index + 1) ++end;
            if (end - start >= 2) {
                std::vector<const ExpandedRuleIR*> run;
                run.reserve(end - start);
                for (std::size_t i = start; i < end; ++i) run.push_back(group[i].rule);
                result.families.push_back(merged(run, group[start].index, group[end - 1].index));
                result.stats.collapsed_rules += end - start;
            } else {
                result.families.push_back(singleton(*group[start].rule));
                ++result.stats.singleton_families;
            }
            start = end;
        }
    }
    for (const auto* rule : singletons) {
        result.families.push_back(singleton(*rule));
        ++result.stats.singleton_families;
    }

    std::sort(result.families.begin(), result.families.end(), [](const RuleFamilyIR& a,
                                                                 const RuleFamilyIR& b) {
        const RuleId ar = a.source_rules.empty() ? kInvalidIndex :
                          *std::min_element(a.source_rules.begin(), a.source_rules.end());
        const RuleId br = b.source_rules.empty() ? kInvalidIndex :
                          *std::min_element(b.source_rules.begin(), b.source_rules.end());
        return ar < br;
    });
    for (FamilyId id = 0; id < result.families.size(); ++id) result.families[id].id = id;
    result.stats.output_families = result.families.size();

    if (options.explain_rejections) {
        std::sort(indexed.begin(), indexed.end(), [](const IndexedRef& a, const IndexedRef& b) {
            if (a.rule->name != b.rule->name) return a.rule->name < b.rule->name;
            return a.index < b.index;
        });
        for (std::size_t i = 0; i < indexed.size(); ++i) {
            const auto& left = indexed[i];
            const auto base = stripTrailingIndex(left.rule->name);
            for (std::size_t j = i + 1; j < indexed.size(); ++j) {
                const auto& right = indexed[j];
                if (stripTrailingIndex(right.rule->name) != base) continue;
                if (right.index != left.index + 1) continue;
                if (sameRuleShape(*left.rule, left.index, *right.rule, right.index)) continue;
                result.rejections.push_back({left.rule->id, right.rule->id,
                    rejectionReason(*left.rule, left.index, *right.rule, right.index)});
                break;
            }
        }
    }
    return result;
}

FamilyCollapseResult collapseIndexedRuleFamilies(const std::vector<ExpandedRuleIR>& rules) {
    auto result = compileRuleFamilies(rules);
    FamilyCollapseResult collapsed;
    collapsed.families = std::move(result.families);
    collapsed.stats = result.stats;
    return collapsed;
}

std::vector<ExpandedRuleIR> expandFamilies(const std::vector<RuleFamilyIR>& families) {
    std::vector<ExpandedRuleIR> expanded;
    for (const auto& family : families) {
        if (!family.coordinate_parameterized) {
            ExpandedRuleIR rule;
            rule.id = family.source_rules.empty() ? 0 : family.source_rules.front();
            rule.name = family.name;
            rule.rate = family.default_rate;
            rule.rate_law = family.rate_law;
            rule.predicates = family.predicates;
            rule.actions = family.actions;
            rule.pattern = family.pattern;
            expanded.push_back(std::move(rule));
            continue;
        }
        const auto count = family.source_rules.size();
        for (std::size_t offset = 0; offset < count; ++offset) {
            const auto index = family.begin_index + static_cast<std::uint32_t>(offset);
            ExpandedRuleIR rule;
            rule.id = family.source_rules[offset];
            rule.name = family.name + "_" + std::to_string(index);
            rule.rate = offset < family.indexed_rates.size() ? family.indexed_rates[offset]
                                                              : family.default_rate;
            rule.rate_law = family.rate_law;
            rule.predicates = family.predicates;
            rule.actions = family.actions;
            rule.pattern = family.pattern;
            for (auto& predicate : rule.predicates) {
                if (predicate.kind == PredicateKind::PositionEq ||
                    predicate.kind == PredicateKind::PositionRange)
                    predicate.value = denormalized(predicate.value, index);
                if (predicate.kind == PredicateKind::PositionRange)
                    predicate.aux = denormalized(predicate.aux, index);
            }
            expanded.push_back(std::move(rule));
        }
    }
    std::sort(expanded.begin(), expanded.end(), [](const ExpandedRuleIR& a, const ExpandedRuleIR& b) {
        return a.id < b.id;
    });
    return expanded;
}

bool semanticRuleEqual(const ExpandedRuleIR& a, const ExpandedRuleIR& b) noexcept {
    if (a.rate != b.rate || !sameRateLaw(a.rate_law, b.rate_law) ||
        a.predicates.size() != b.predicates.size() || a.actions.size() != b.actions.size() ||
        !samePattern(a.pattern, b.pattern)) return false;
    for (std::size_t i = 0; i < a.predicates.size(); ++i) {
        const auto& x = a.predicates[i];
        const auto& y = b.predicates[i];
        if (x.kind != y.kind || x.molecule_type != y.molecule_type || x.site != y.site ||
            x.value != y.value || x.aux != y.aux || x.state_set != y.state_set)
            return false;
    }
    for (std::size_t i = 0; i < a.actions.size(); ++i) {
        const auto& x = a.actions[i];
        const auto& y = b.actions[i];
        if (x.kind != y.kind || x.molecule_type != y.molecule_type || x.site != y.site ||
            x.value != y.value || x.aux != y.aux)
            return false;
    }
    return true;
}

bool semanticRuleSequenceEqual(const std::vector<ExpandedRuleIR>& a,
                               const std::vector<ExpandedRuleIR>& b) noexcept {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i)
        if (!semanticRuleEqual(a[i], b[i])) return false;
    return true;
}

} // namespace nfnext
