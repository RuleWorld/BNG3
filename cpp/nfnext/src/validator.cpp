#include "nfnext/validator.hpp"

#include <cmath>
#include <sstream>
#include <unordered_map>
#include <unordered_set>

namespace nfnext {
namespace {

[[noreturn]] void fail(const std::string& message) {
    throw ValidationError(message);
}

const MoleculeTypeIR& typeFor(const std::unordered_map<TypeId, std::size_t>& types,
                              const std::vector<MoleculeTypeIR>& declarations,
                              TypeId id, const char* context) {
    const auto found = types.find(id);
    if (found == types.end()) {
        std::ostringstream message;
        message << context << " references unknown molecule type " << id;
        fail(message.str());
    }
    return declarations[found->second];
}

void validateRate(double rate, const char* context) {
    if (!std::isfinite(rate) || rate < 0.0) {
        std::ostringstream message;
        message << context << " must be finite and non-negative";
        fail(message.str());
    }
}

void validateRateLaw(const RateLawIR& rate_law, const char* context) {
    if (rate_law.kind != RateLawKind::Elementary && rate_law.kind != RateLawKind::Function)
        fail(std::string(context) + " has an unknown rate-law kind");
    if (rate_law.kind == RateLawKind::Function && rate_law.expression.empty())
        fail(std::string(context) + " has an empty function expression");
}

void validatePredicate(const PredicateIR& predicate,
                       const std::unordered_map<TypeId, std::size_t>& types,
                       const std::vector<MoleculeTypeIR>& declarations,
                       const char* context) {
    const auto& type = typeFor(types, declarations, predicate.molecule_type, context);
    if (predicate.site >= type.sites.size()) {
        std::ostringstream message;
        message << context << " references site " << predicate.site
                << " outside molecule type " << predicate.molecule_type;
        fail(message.str());
    }
    if (predicate.kind == PredicateKind::SiteStateEq) {
        const auto& states = type.sites[predicate.site].states;
        if (predicate.state_set.empty()) {
            if (predicate.value < 0 || static_cast<std::size_t>(predicate.value) >= states.size())
                fail(std::string(context) + " has a state index outside its enumeration");
        } else {
            for (const auto state : predicate.state_set) {
                if (state < 0 || static_cast<std::size_t>(state) >= states.size())
                    fail(std::string(context) + " has a state-set index outside its enumeration");
            }
        }
    }
}

void validateAction(const ActionIR& action,
                    const std::unordered_map<TypeId, std::size_t>& types,
                    const std::vector<MoleculeTypeIR>& declarations,
                    const char* context) {
    const auto& type = typeFor(types, declarations, action.molecule_type, context);
    if (action.site >= type.sites.size()) {
        std::ostringstream message;
        message << context << " references site " << action.site
                << " outside molecule type " << action.molecule_type;
        fail(message.str());
    }
    if (action.kind == ActionKind::SetSiteState) {
        const auto& states = type.sites[action.site].states;
        if (action.value < 0 || static_cast<std::size_t>(action.value) >= states.size())
            fail(std::string(context) + " sets a state outside its enumeration");
    }
}

void validatePattern(const PatternIR& pattern,
                     const std::unordered_map<TypeId, std::size_t>& types,
                     const std::vector<MoleculeTypeIR>& declarations,
                     const char* context) {
    for (const auto& node : pattern.nodes) {
        const auto& type = typeFor(types, declarations, node.molecule_type, context);
        for (const auto& constraint : node.constraints) {
            if (constraint.site >= type.sites.size())
                fail(std::string(context) + " pattern references an unknown site");
            const auto& states = type.sites[constraint.site].states;
            if (constraint.kind == PatternIR::SiteConstraintKind::State) {
                if (constraint.state < 0 || static_cast<std::size_t>(constraint.state) >= states.size())
                    fail(std::string(context) + " pattern has an invalid state");
            } else if (constraint.kind == PatternIR::SiteConstraintKind::StateSet) {
                if (constraint.states.empty()) fail(std::string(context) + " pattern has an empty state set");
                for (const auto state : constraint.states)
                    if (state < 0 || static_cast<std::size_t>(state) >= states.size())
                        fail(std::string(context) + " pattern has an invalid state-set member");
            } else if (constraint.kind != PatternIR::SiteConstraintKind::Free &&
                       constraint.kind != PatternIR::SiteConstraintKind::Bound) {
                fail(std::string(context) + " pattern has an unknown site-constraint kind");
            }
        }
    }
    auto requireNode = [&pattern, context](std::size_t node) {
        if (node >= pattern.nodes.size()) fail(std::string(context) + " pattern references an unknown node");
    };
    for (const auto& bond : pattern.bonds) {
        requireNode(bond.first); requireNode(bond.second);
        const auto& first = typeFor(types, declarations, pattern.nodes[bond.first].molecule_type, context);
        const auto& second = typeFor(types, declarations, pattern.nodes[bond.second].molecule_type, context);
        if (bond.first_site >= first.sites.size() || bond.second_site >= second.sites.size())
            fail(std::string(context) + " pattern bond references an unknown site");
    }
    for (const auto& pair : pattern.aliases) { requireNode(pair.first); requireNode(pair.second); }
    for (const auto& pair : pattern.connected_to) { requireNode(pair.first); requireNode(pair.second); }
    for (const auto& constraint : pattern.molecularity) {
        requireNode(constraint.left); requireNode(constraint.right);
    }
    for (const auto& group : pattern.interchangeable) {
        for (const auto node : group) requireNode(node);
    }
}

void validateRule(const ExpandedRuleIR& rule,
                  const std::unordered_map<TypeId, std::size_t>& types,
                  const std::vector<MoleculeTypeIR>& declarations,
                  const char* context) {
    validateRate(rule.rate, context);
    validateRateLaw(rule.rate_law, context);
    for (const auto& predicate : rule.predicates)
        validatePredicate(predicate, types, declarations, context);
    for (const auto& action : rule.actions)
        validateAction(action, types, declarations, context);
    validatePattern(rule.pattern, types, declarations, context);
}

void validateFamily(const RuleFamilyIR& family,
                    const std::unordered_map<TypeId, std::size_t>& types,
                    const std::vector<MoleculeTypeIR>& declarations) {
    validateRate(family.default_rate, "rule family rate");
    validateRateLaw(family.rate_law, "rule family rate law");
    for (const auto rate : family.indexed_rates) validateRate(rate, "indexed rule-family rate");
    for (const auto& predicate : family.predicates)
        validatePredicate(predicate, types, declarations, "rule family predicate");
    for (const auto& action : family.actions)
        validateAction(action, types, declarations, "rule family action");
    validatePattern(family.pattern, types, declarations, "rule family");
}

} // namespace

void validateModel(const ModelIR& model) {
    std::unordered_map<TypeId, std::size_t> types;
    std::unordered_set<std::string> names;
    for (std::size_t i = 0; i < model.molecule_types.size(); ++i) {
        const auto& type = model.molecule_types[i];
        if (!types.emplace(type.id, i).second) fail("duplicate molecule type ID");
        if (!names.emplace(type.name).second) fail("duplicate molecule type name");
        std::unordered_set<std::string> sites;
        for (const auto& site : type.sites) {
            if (!sites.emplace(site.name).second) fail("duplicate site name within molecule type");
            std::unordered_set<std::string> states;
            for (const auto& state : site.states)
                if (!states.emplace(state).second) fail("duplicate enumerated site state");
        }
    }

    std::unordered_set<RuleId> rule_ids;
    for (const auto& rule : model.expanded_rules) {
        if (!rule_ids.emplace(rule.id).second) fail("duplicate expanded rule ID");
        validateRule(rule, types, model.molecule_types, "expanded rule");
    }
    std::unordered_set<FamilyId> family_ids;
    for (const auto& family : model.rule_families) {
        if (!family_ids.emplace(family.id).second) fail("duplicate rule-family ID");
        validateFamily(family, types, model.molecule_types);
    }
}

} // namespace nfnext
