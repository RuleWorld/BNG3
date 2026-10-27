#pragma once

#include <string>
#include <vector>

namespace bng::ast {
class Model;
class Rxn;
class ReactionRule;
} // namespace bng::ast

namespace bng::compile {

// The TotalRate capability: a rule uses a rate coefficient without the
// reaction-centre symmetry factor.  In finite networks, canonical BNG2 still
// multiplies authored BNGL TotalRate coefficients by available reactant
// counts.  Atomizer-lowered SBML laws are separately marked as absolute fluxes
// because their expressions already include that dependence.
//
// This header is the single owner of the capability.  The spelling of the
// modifier belongs here as well: no other translation unit may compare a
// modifier against the TotalRate spelling.

// Is this modifier the TotalRate modifier?  The spelling is matched without
// regard to case, because the modifier reaches the model as authored text.
bool isTotalRateModifier(const std::string& modifier);

// Does a serialized marker name the total-rate capability?  The SBML
// annotation that marks a total-rate reaction carries the same word, and the
// reader of that annotation has to recognise it here as well.
bool isTotalRateMarkerName(const std::string& markerName);

// Does a rule's modifier list carry the TotalRate modifier?
bool hasTotalRateModifier(const std::vector<std::string>& modifiers);

// Does the rule carry the TotalRate modifier?
bool isTotalRateRule(const ast::ReactionRule& rule);

// Does the rule with this name carry the TotalRate modifier?  A rule that
// the model does not declare is not a TotalRate rule.
bool isTotalRateRule(const ast::Model& model, const std::string& ruleName);

// The rule a reaction was generated from.
//
// The network generator marks the reverse direction of a rule with the
// "_reverse__" prefix, and a rule the parser named with a leading underscore
// carries the underscore itself; neither marker is part of the rule's own
// name.  A name that ends in "_reverse" is a rule whose own name ends that
// way, and it is not a marker.
struct OriginRule {
    std::string name;
    bool reverse = false;
};

// Resolve an origin rule name to the rule it names.
OriginRule resolveOriginRule(const std::string& originRuleName);

// Does the reaction originate from a rule carrying the TotalRate modifier?
//
// Reverse directions inherit the modifier.  TotalRate affects symmetry and
// unit conversion; `isAbsoluteFluxReaction` separately identifies source
// laws that already include reactant dependence.
bool isTotalRateReaction(const ast::Model& model, const std::string& originRuleName);

// Is this TotalRate reaction an Atomizer-lowered SBML absolute flux?  These
// laws already contain their reactant dependence and must not get finite
// network count factors applied a second time.
bool isAbsoluteFluxReaction(const ast::Model& model,
                            const std::string& originRuleName);
bool isAbsoluteFluxReaction(const ast::Model& model, const ast::Rxn& reaction);

// Serialize the current per-rule provenance list for BNGL and .net round trips.
std::string absoluteFluxRuleNames(const ast::Model& model);

} // namespace bng::compile
