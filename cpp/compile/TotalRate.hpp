#pragma once

#include <string>
#include <vector>

namespace bng::ast {
class Model;
class ReactionRule;
} // namespace bng::ast

namespace bng::compile {

// The TotalRate capability: a rule whose rate law states the complete
// macroscopic reaction rate.
//
// A TotalRate reaction carries neither the reaction centre's symmetry factor
// nor the reactant concentration factors: the rate is already the complete
// flux.  The decision therefore has to be made once, and every consumer of it
// - the network writer, the SBML writer, the BNG-XML writer, the ODE and SSA
// engines and the compiled model's modifier vocabulary - has to ask the same
// owner.  A consumer that re-derives the decision from the rule name alone
// cannot see the reverse direction of a rule, and then reports a different
// rate for a reaction that the engine executes as a total rate.
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
// does not exist is not a TotalRate rule.
bool isTotalRateRule(const ast::Model& model, const std::string& ruleName);

// The rule a reaction was generated from.
//
// The network generator marks the reverse direction of a rule with the
// "_reverse__" prefix, and a rule label with a leading "_"; the marker is not
// part of the rule's own name.
struct OriginRule {
    std::string name;
    bool reverse = false;
};

OriginRule resolveOriginRule(const std::string& originRuleName);

// Is the reaction's rate a macroscopic total rate?
//
// The reverse direction of a TotalRate rule is a total rate as well: the rule
// states the complete rate of the reversible step, and both directions
// inherit it.
bool isTotalRateReaction(const ast::Model& model, const std::string& originRuleName);

} // namespace bng::compile
