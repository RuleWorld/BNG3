#pragma once

#include <string>
#include <vector>

#include "CompiledRateLaw.hpp"
#include "ast/ReactionRule.hpp"

namespace bng::compile {

enum class MutationKind {
    AddBond,
    DeleteBond,
    ChangeState,
    AddMolecule,
    DeleteMolecule,
};

struct MutationSignature {
    MutationKind kind = MutationKind::ChangeState;
    ast::ReactionRule::ComponentRef source;
    ast::ReactionRule::ComponentRef partner;
    std::size_t moleculeIndex = 0;
    std::size_t patternIndex = 0;
    std::string newState;
};

class CompiledRule {
public:
    static CompiledRule compile(const ast::ReactionRule& rule);

    const std::string& name() const { return name_; }
    const std::string& label() const { return label_; }
    bool requiresConservativeInvalidation() const { return conservativeInvalidation_; }
    bool isBidirectional() const { return bidirectional_; }
    const std::vector<MutationSignature>& mutations() const { return mutations_; }
    const std::vector<CompiledRateLaw>& rateLaws() const { return rateLaws_; }

    // Explicit reactant-side component references whose local
    // structure can be changed by this rule. Backends may refine this further,
    // but must not omit any of these dependencies. When
    // requiresConservativeInvalidation() is true, this list is insufficient.
    const std::vector<ast::ReactionRule::ComponentRef>& affectedComponents() const {
        return affectedComponents_;
    }

private:
    std::string name_;
    std::string label_;
    bool conservativeInvalidation_ = false;
    bool bidirectional_ = false;
    std::vector<MutationSignature> mutations_;
    std::vector<CompiledRateLaw> rateLaws_;
    std::vector<ast::ReactionRule::ComponentRef> affectedComponents_;
};

} // namespace bng::compile
