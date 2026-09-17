#include "nfnext/canonical.hpp"

#include "nfnext/validator.hpp"

#include <algorithm>
#include <cstring>
#include <iomanip>
#include <map>
#include <sstream>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace nfnext {
namespace {

void mix(std::uint64_t& hash, std::uint64_t value) noexcept {
    hash ^= value + 0x9E3779B97F4A7C15ULL + (hash << 6) + (hash >> 2);
}

void mixString(std::uint64_t& hash, const std::string& value) noexcept {
    for (const unsigned char byte : value) mix(hash, byte);
}

void appendString(std::ostringstream& out, const std::string& value) {
    out << value.size() << ':' << value;
}

void appendRateLaw(std::ostringstream& out, const RateLawIR& rate_law) {
    out << static_cast<unsigned>(rate_law.kind) << ':';
    appendString(out, rate_law.expression);
}

void appendPredicate(std::ostringstream& out, const PredicateIR& predicate) {
    out << static_cast<unsigned>(predicate.kind) << ':' << predicate.molecule_type << ':'
        << predicate.site << ':' << predicate.value << ':' << predicate.aux << ':'
        << predicate.state_set.size() << ':';
    for (const auto state : predicate.state_set) out << state << ',';
}

void appendAction(std::ostringstream& out, const ActionIR& action) {
    out << static_cast<unsigned>(action.kind) << ':' << action.molecule_type << ':'
        << action.site << ':' << action.value << ':' << action.aux;
}

void appendPattern(std::ostringstream& out, const PatternIR& pattern) {
    out << "nodes:" << pattern.nodes.size() << ';';
    for (const auto& node : pattern.nodes) {
        out << node.molecule_type << ':' << node.constraints.size() << ';';
        for (const auto& constraint : node.constraints) {
            out << static_cast<unsigned>(constraint.kind) << ':' << constraint.site << ':'
                << constraint.state << ':' << constraint.states.size() << ':';
            for (const auto state : constraint.states) out << state << ',';
            out << ';';
        }
    }
    out << "bonds:" << pattern.bonds.size() << ';';
    for (const auto& bond : pattern.bonds)
        out << bond.first << ':' << bond.first_site << ':' << bond.second << ':'
            << bond.second_site << ';';
    out << pattern.molecularity.size() << ':';
    for (const auto& constraint : pattern.molecularity) {
        out << static_cast<unsigned>(constraint.kind) << ':' << constraint.left << ':'
            << constraint.right << ';';
    }
    out << "aliases:" << pattern.aliases.size() << ';';
    for (const auto& pair : pattern.aliases) out << pair.first << ':' << pair.second << ';';
    out << "connected:" << pattern.connected_to.size() << ';';
    for (const auto& pair : pattern.connected_to) out << pair.first << ':' << pair.second << ';';
    out << "interchangeable:" << pattern.interchangeable.size() << ';';
    for (const auto& group : pattern.interchangeable) {
        out << group.size() << ':';
        for (const auto node : group) out << node << ',';
        out << ';';
    }
}

void appendRule(std::ostringstream& out, const ExpandedRuleIR& rule) {
    std::uint64_t bits = 0;
    std::memcpy(&bits, &rule.rate, sizeof(bits));
    out << std::hex << bits << std::dec << ':';
    appendRateLaw(out, rule.rate_law);
    out << ':' << rule.predicates.size() << ':';
    for (const auto& predicate : rule.predicates) {
        appendPredicate(out, predicate);
        out << ';';
    }
    out << ':' << rule.actions.size() << ':';
    for (const auto& action : rule.actions) {
        appendAction(out, action);
        out << ';';
    }
    out << ':';
    appendPattern(out, rule.pattern);
}

void appendFamily(std::ostringstream& out, const RuleFamilyIR& family) {
    out << family.begin_index << ':' << family.end_index << ':'
        << (family.coordinate_parameterized ? 1 : 0) << ':';
    std::uint64_t bits = 0;
    std::memcpy(&bits, &family.default_rate, sizeof(bits));
    out << std::hex << bits << std::dec << ':';
    appendRateLaw(out, family.rate_law);
    out << ':' << family.indexed_rates.size() << ':';
    for (const auto rate : family.indexed_rates) {
        std::memcpy(&bits, &rate, sizeof(bits));
        out << std::hex << bits << std::dec << ',';
    }
    out << ':' << family.predicates.size() << ':';
    for (const auto& predicate : family.predicates) {
        appendPredicate(out, predicate);
        out << ';';
    }
    out << ':' << family.actions.size() << ':';
    for (const auto& action : family.actions) {
        appendAction(out, action);
        out << ';';
    }
    out << ':';
    appendPattern(out, family.pattern);
}

struct TypeRemap {
    TypeId old_id{0};
    TypeId new_id{0};
    std::vector<std::uint16_t> sites;
};

const TypeRemap& remapFor(const std::unordered_map<TypeId, std::size_t>& by_old_id,
                          const std::vector<TypeRemap>& remaps, TypeId old_id) {
    return remaps.at(by_old_id.at(old_id));
}

void remapPredicate(PredicateIR& predicate,
                    const std::unordered_map<TypeId, std::size_t>& by_old_id,
                    const std::vector<TypeRemap>& remaps) {
    const auto& remap = remapFor(by_old_id, remaps, predicate.molecule_type);
    predicate.molecule_type = remap.new_id;
    predicate.site = remap.sites.at(predicate.site);
}

void remapAction(ActionIR& action,
                 const std::unordered_map<TypeId, std::size_t>& by_old_id,
                 const std::vector<TypeRemap>& remaps) {
    const auto& remap = remapFor(by_old_id, remaps, action.molecule_type);
    action.molecule_type = remap.new_id;
    action.site = remap.sites.at(action.site);
}

void remapPattern(PatternIR& pattern,
                  const std::unordered_map<TypeId, std::size_t>& by_old_id,
                  const std::vector<TypeRemap>& remaps) {
    std::vector<const TypeRemap*> node_remaps;
    node_remaps.reserve(pattern.nodes.size());
    for (const auto& node : pattern.nodes)
        node_remaps.push_back(&remapFor(by_old_id, remaps, node.molecule_type));
    for (std::size_t node_index = 0; node_index < pattern.nodes.size(); ++node_index) {
        auto& node = pattern.nodes[node_index];
        const auto& remap = *node_remaps[node_index];
        node.molecule_type = remap.new_id;
        for (auto& constraint : node.constraints)
            constraint.site = remap.sites.at(constraint.site);
    }
    for (auto& bond : pattern.bonds) {
        bond.first_site = node_remaps.at(bond.first)->sites.at(bond.first_site);
        bond.second_site = node_remaps.at(bond.second)->sites.at(bond.second_site);
    }
}

void resolveLegacyTypeReferences(ModelIR& model) {
    std::unordered_set<TypeId> declared;
    for (const auto& type : model.molecule_types) declared.insert(type.id);
    auto resolve = [&model, &declared](TypeId& id) {
        // Early NFIR producers used declaration-vector positions as type IDs.
        // Accept that bounded legacy spelling only when the explicit ID is
        // absent; truly unknown IDs still fail validation below.
        if (declared.find(id) == declared.end() && id < model.molecule_types.size())
            id = model.molecule_types[id].id;
    };
    for (auto& rule : model.expanded_rules) {
        for (auto& predicate : rule.predicates) resolve(predicate.molecule_type);
        for (auto& action : rule.actions) resolve(action.molecule_type);
    }
    for (auto& family : model.rule_families) {
        for (auto& predicate : family.predicates) resolve(predicate.molecule_type);
        for (auto& action : family.actions) resolve(action.molecule_type);
    }
}

std::uint64_t hashBytes(const std::string& bytes) noexcept {
    std::uint64_t hash = 0xCBF29CE484222325ULL;
    mixString(hash, bytes);
    return hash;
}

} // namespace

std::string CanonicalModel::canonicalBytes() const {
    std::ostringstream out;
    if (options.include_model_name_in_semantic_hash) {
        out << "name:";
        appendString(out, model.model_name);
        out << ';';
    }
    out << "backend:" << static_cast<unsigned>(model.preferred_backend)
        << ":lattice:" << model.lattice_length << ';';
    out << "types:" << model.molecule_types.size() << ';';
    for (const auto& type : model.molecule_types) {
        out << "type:" << type.id << ':';
        appendString(out, type.name);
        out << ':' << type.sites.size() << ';';
        for (const auto& site : type.sites) {
            appendString(out, site.name);
            out << ':' << site.states.size() << ':';
            for (const auto& state : site.states) {
                appendString(out, state);
                out << ',';
            }
            out << ';';
        }
    }
    out << "rules:" << model.expanded_rules.size() << ';';
    for (const auto& rule : model.expanded_rules) {
        appendRule(out, rule);
        out << ';';
    }
    out << "families:" << model.rule_families.size() << ';';
    for (const auto& family : model.rule_families) {
        appendFamily(out, family);
        out << ';';
    }
    return out.str();
}

std::uint64_t CanonicalModel::semanticFingerprint() const noexcept {
    try {
        return hashBytes(canonicalBytes());
    } catch (...) {
        return 0;
    }
}

std::uint64_t CanonicalModel::diagnosticFingerprint() const noexcept {
    try {
        std::uint64_t hash = hashBytes(canonicalBytes());
        for (const auto& rule : model.expanded_rules) {
            mixString(hash, rule.source.source);
            mix(hash, rule.source.line);
        }
        return hash;
    } catch (...) {
        return 0;
    }
}

std::uint64_t CanonicalModel::compileKey() const noexcept {
    std::uint64_t hash = semanticFingerprint();
    mix(hash, static_cast<std::uint8_t>(options.connectivity_policy));
    return hash;
}

CanonicalModel canonicalizeModel(const ModelIR& input, const CanonicalOptions& options) {
    ModelIR normalized = input;
    resolveLegacyTypeReferences(normalized);
    validateModel(normalized);
    const auto& sourceModel = normalized;

    CanonicalModel result;
    result.options = options;
    result.model = sourceModel;

    std::vector<std::size_t> order(sourceModel.molecule_types.size());
    for (std::size_t i = 0; i < order.size(); ++i) order[i] = i;
    std::sort(order.begin(), order.end(), [&sourceModel](std::size_t a, std::size_t b) {
        if (sourceModel.molecule_types[a].name != sourceModel.molecule_types[b].name)
            return sourceModel.molecule_types[a].name < sourceModel.molecule_types[b].name;
        return sourceModel.molecule_types[a].id < sourceModel.molecule_types[b].id;
    });

    std::unordered_map<TypeId, std::size_t> by_old_id;
    std::vector<TypeRemap> remaps(sourceModel.molecule_types.size());
    result.model.molecule_types.clear();
    result.model.molecule_types.reserve(order.size());
    for (std::size_t new_index = 0; new_index < order.size(); ++new_index) {
        const auto old_index = order[new_index];
        const auto& source = sourceModel.molecule_types[old_index];
        MoleculeTypeIR type = source;
        type.id = static_cast<TypeId>(new_index);
        std::vector<std::size_t> site_order(type.sites.size());
        for (std::size_t i = 0; i < site_order.size(); ++i) site_order[i] = i;
        std::sort(site_order.begin(), site_order.end(), [&type](std::size_t a, std::size_t b) {
            return type.sites[a].name < type.sites[b].name;
        });
        std::vector<SiteSpec> sorted_sites;
        sorted_sites.reserve(site_order.size());
        std::vector<std::uint16_t> site_remap(site_order.size());
        for (std::size_t new_site = 0; new_site < site_order.size(); ++new_site) {
            site_remap[site_order[new_site]] = static_cast<std::uint16_t>(new_site);
            sorted_sites.push_back(type.sites[site_order[new_site]]);
        }
        type.sites = std::move(sorted_sites);
        remaps[old_index] = TypeRemap{source.id, type.id, std::move(site_remap)};
        result.model.molecule_types.push_back(std::move(type));
    }
    // `by_old_id` indexes the remap vector by the original declaration index.
    // Rebuild it explicitly after sorting so references cannot depend on input
    // insertion order.
    by_old_id.clear();
    for (std::size_t old_index = 0; old_index < sourceModel.molecule_types.size(); ++old_index)
        by_old_id.emplace(sourceModel.molecule_types[old_index].id, old_index);

    std::vector<std::size_t> rule_order(sourceModel.expanded_rules.size());
    for (std::size_t i = 0; i < rule_order.size(); ++i) rule_order[i] = i;
    std::sort(rule_order.begin(), rule_order.end(), [&sourceModel](std::size_t a, std::size_t b) {
        return sourceModel.expanded_rules[a].id < sourceModel.expanded_rules[b].id;
    });
    result.model.expanded_rules.clear();
    result.model.expanded_rules.reserve(rule_order.size());
    for (std::size_t new_id = 0; new_id < rule_order.size(); ++new_id) {
        auto rule = sourceModel.expanded_rules[rule_order[new_id]];
        rule.id = static_cast<RuleId>(new_id);
        for (auto& predicate : rule.predicates) remapPredicate(predicate, by_old_id, remaps);
        for (auto& action : rule.actions) remapAction(action, by_old_id, remaps);
        remapPattern(rule.pattern, by_old_id, remaps);
        result.model.expanded_rules.push_back(std::move(rule));
    }

    std::sort(result.model.rule_families.begin(), result.model.rule_families.end(),
              [](const RuleFamilyIR& a, const RuleFamilyIR& b) { return a.id < b.id; });
    for (std::size_t id = 0; id < result.model.rule_families.size(); ++id) {
        auto& family = result.model.rule_families[id];
        family.id = static_cast<FamilyId>(id);
        for (auto& predicate : family.predicates) remapPredicate(predicate, by_old_id, remaps);
        for (auto& action : family.actions) remapAction(action, by_old_id, remaps);
        remapPattern(family.pattern, by_old_id, remaps);
    }
    result.model.dependencies.feature_to_families.clear();
    for (const auto& family : result.model.rule_families) {
        for (const auto& predicate : family.predicates) {
            auto& ids = result.model.dependencies.feature_to_families[
                encodeFeature(predicate.molecule_type, predicate.site, predicate.kind,
                              predicate.value)];
            if (std::find(ids.begin(), ids.end(), family.id) == ids.end()) ids.push_back(family.id);
        }
    }
    return result;
}

CanonicalModel canonicalizeModel(const CanonicalModel& model, const CanonicalOptions& options) {
    return canonicalizeModel(model.model, options);
}

} // namespace nfnext
