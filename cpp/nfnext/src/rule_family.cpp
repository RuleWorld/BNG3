#include "nfnext/rule_family.hpp"

#include <algorithm>
#include <cctype>
#include <map>
#include <sstream>

namespace nfnext {

std::string stripTrailingIndex(const std::string& name, std::uint32_t* index) {
    if (index) *index = 0;
    if (name.empty()) return name;
    std::size_t end = name.size();
    std::size_t begin = end;
    while (begin > 0 && std::isdigit(static_cast<unsigned char>(name[begin - 1]))) --begin;
    if (begin == end || begin == 0) return name;
    const char sep = name[begin - 1];
    if (sep != '_' && sep != ':') return name;
    std::uint64_t value = 0;
    for (std::size_t i = begin; i < end; ++i) value = value * 10 + static_cast<unsigned>(name[i] - '0');
    if (value > 0xffffffffULL) return name;
    if (index) *index = static_cast<std::uint32_t>(value);
    return name.substr(0, begin - 1);
}

namespace {

std::int64_t normalizedPredicateValue(const PredicateIR& p, std::uint32_t index) {
    switch (p.kind) {
        case PredicateKind::PositionEq:
        case PredicateKind::PositionRange:
            return static_cast<std::int64_t>(p.value) - static_cast<std::int64_t>(index);
        default:
            return p.value;
    }
}

std::int64_t normalizedPredicateAux(const PredicateIR& p, std::uint32_t index) {
    if (p.kind == PredicateKind::PositionRange)
        return static_cast<std::int64_t>(p.aux) - static_cast<std::int64_t>(index);
    return p.aux;
}

std::string shapeKey(const ExpandedRuleIR& r, const std::string& base, std::uint32_t index) {
    std::ostringstream k;
    k << base << '|';
    for (const auto& p : r.predicates) {
        k << 'p' << static_cast<int>(p.kind) << ':' << p.molecule_type << ':' << p.site
          << ':' << normalizedPredicateValue(p, index)
          << ':' << normalizedPredicateAux(p, index) << ';';
    }
    k << '|';
    for (const auto& a : r.actions) {
        // Action values are preserved. MovePosition.value is a displacement, not
        // an absolute coordinate, so structurally different transformations do
        // not collapse merely because their names share an index.
        k << 'a' << static_cast<int>(a.kind) << ':' << a.molecule_type << ':' << a.site
          << ':' << a.value << ':' << a.aux << ';';
    }
    return k.str();
}

RuleFamilyIR singleton(const ExpandedRuleIR& r, FamilyId id) {
    RuleFamilyIR f;
    f.id = id; f.name = r.name; f.default_rate = r.rate;
    f.predicates = r.predicates; f.actions = r.actions; f.source_rules.push_back(r.id);
    return f;
}

void normalizeFamilyCoordinates(RuleFamilyIR& f, std::uint32_t first_index) {
    for (auto& p : f.predicates) {
        if (p.kind == PredicateKind::PositionEq || p.kind == PredicateKind::PositionRange)
            p.value -= static_cast<std::int32_t>(first_index);
        if (p.kind == PredicateKind::PositionRange)
            p.aux -= static_cast<std::int32_t>(first_index);
    }
}

} // namespace

FamilyCollapseResult collapseIndexedRuleFamilies(const std::vector<ExpandedRuleIR>& rules) {
    struct IndexedRef { const ExpandedRuleIR* rule; std::uint32_t index; std::string base; };
    std::map<std::string, std::vector<IndexedRef>> groups;
    std::vector<const ExpandedRuleIR*> singletons;

    for (const auto& r : rules) {
        std::uint32_t idx = 0;
        const std::string base = stripTrailingIndex(r.name, &idx);
        if (base == r.name) { singletons.push_back(&r); continue; }
        groups[shapeKey(r, base, idx)].push_back(IndexedRef{&r, idx, base});
    }

    FamilyCollapseResult out;
    out.stats.input_rules = rules.size();
    FamilyId next_id = 0;

    for (auto& kv : groups) {
        auto& g = kv.second;
        std::sort(g.begin(), g.end(), [](const IndexedRef& a, const IndexedRef& b) { return a.index < b.index; });
        bool consecutive = g.size() >= 2;
        for (std::size_t i = 1; i < g.size() && consecutive; ++i) consecutive = g[i].index == g[i - 1].index + 1;
        if (!consecutive) {
            for (const auto& x : g) { out.families.push_back(singleton(*x.rule, next_id++)); ++out.stats.singleton_families; }
            continue;
        }
        RuleFamilyIR f;
        f.id = next_id++;
        f.name = g.front().base;
        f.begin_index = g.front().index;
        f.end_index = g.back().index;
        f.default_rate = g.front().rule->rate;
        f.predicates = g.front().rule->predicates;
        f.actions = g.front().rule->actions;
        normalizeFamilyCoordinates(f, g.front().index);
        f.coordinate_parameterized = true;
        f.indexed_rates.reserve(g.size());
        f.source_rules.reserve(g.size());
        for (const auto& x : g) { f.indexed_rates.push_back(x.rule->rate); f.source_rules.push_back(x.rule->id); }
        out.stats.collapsed_rules += g.size();
        out.families.push_back(std::move(f));
    }

    for (const auto* r : singletons) { out.families.push_back(singleton(*r, next_id++)); ++out.stats.singleton_families; }

    // Preserve the original expanded-rule order at family granularity. This is
    // important for deterministic differential execution and stable caches.
    std::sort(out.families.begin(), out.families.end(), [](const RuleFamilyIR& a, const RuleFamilyIR& b) {
        const RuleId ar = a.source_rules.empty() ? kInvalidIndex : *std::min_element(a.source_rules.begin(), a.source_rules.end());
        const RuleId br = b.source_rules.empty() ? kInvalidIndex : *std::min_element(b.source_rules.begin(), b.source_rules.end());
        return ar < br;
    });
    for (FamilyId id = 0; id < out.families.size(); ++id) out.families[id].id = id;
    out.stats.output_families = out.families.size();
    return out;
}

} // namespace nfnext
