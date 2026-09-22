#pragma once

#include <memory>
#include <string>

#include "Expression.hpp"
#include "ReactionRule.hpp"

namespace bng::ast {

// A barrier pattern contributes to the transition state of every rule whose
// reaction center it matches. It does not change the free energy of either
// ground state, so it must never be folded into an EnergyPattern or into an
// EnergyDeltaPlan; it is added to the activation energy instead.
//
// The transition itself is stored as an ordinary ReactionRule. That is
// deliberate: BNG3 already derives reaction centers, component mappings and
// graph diffs from ReactionRule, so a barrier written as `A(s~U) -> A(s~P)`
// reuses that machinery rather than requiring a second transition detector.
// The barrier energy occupies the rule's rate-law position.
//
// ReactionRule owns non-copyable state, so BarrierPattern is move-only.
class BarrierPattern {
public:
    BarrierPattern(std::string label, ReactionRule transition);
    ~BarrierPattern();

    BarrierPattern(BarrierPattern&&) noexcept;
    BarrierPattern& operator=(BarrierPattern&&) noexcept;
    BarrierPattern(const BarrierPattern&) = delete;
    BarrierPattern& operator=(const BarrierPattern&) = delete;

    const std::string& getLabel() const;

    // Transition-state energy contributed when this pattern matches.
    const Expression& expression() const;
    bool hasExpression() const;

    // The backing transition. Reaction-center extraction reads this.
    const ReactionRule& transition() const;
    ReactionRule& transition();

    std::string toString() const;

private:
    std::string label_;
    // Held indirectly so BarrierPattern stays movable without depending on
    // ReactionRule's move-assignment being noexcept in every future revision.
    std::unique_ptr<ReactionRule> transition_;
    Expression expression_;
    bool hasExpression_ = false;
};

} // namespace bng::ast
