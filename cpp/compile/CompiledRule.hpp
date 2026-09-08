#pragma once

#include <string>
#include <vector>

#include "CompiledRateLaw.hpp"
#include "Pattern.hpp"
#include "ast/ReactionRule.hpp"

namespace bng::compile {

class SymbolTable;

enum class MutationKind {
    AddBond,
    DeleteBond,
    ChangeState,
    AddMolecule,
    DeleteMolecule,
};

enum class ModifierKind {
    DeleteMolecules,
    MoveConnected,
    MatchOnce,
    TotalRate,
    IncludeReactants,
    ExcludeReactants,
    IncludeProducts,
    ExcludeProducts,
    Unknown,
};

struct CompiledFilter {
    bool include = false;
    bool products = false;
    std::size_t patternIndex = 0;
    std::vector<std::string> sourcePatterns;
    std::vector<Pattern> patterns;
};

struct CompiledModifier {
    ModifierKind kind = ModifierKind::Unknown;
    std::string source;
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
    static CompiledRule compile(const ast::ReactionRule& rule,
                                const SymbolTable& symbols,
                                std::vector<Diagnostic>* diagnostics = nullptr);

    const std::string& name() const { return name_; }
    ReactionRuleId id() const { return id_; }
    const std::string& label() const { return label_; }
    bool requiresConservativeInvalidation() const { return conservativeInvalidation_; }
    bool isBidirectional() const { return bidirectional_; }
    const std::vector<MutationSignature>& mutations() const { return mutations_; }
    const std::vector<CompiledRateLaw>& rateLaws() const { return rateLaws_; }
    const std::vector<CompiledModifier>& modifiers() const { return modifiers_; }
    const std::vector<CompiledFilter>& filters() const { return filters_; }
    const std::vector<Pattern>& reactantPatterns() const {
        return reactantPatterns_;
    }
    const std::vector<Pattern>& productPatterns() const {
        return productPatterns_;
    }

    // Explicit reactant-side component references whose local
    // structure can be changed by this rule. Backends may refine this further,
    // but must not omit any of these dependencies. When
    // requiresConservativeInvalidation() is true, this list is insufficient.
    const std::vector<ast::ReactionRule::ComponentRef>& affectedComponents() const {
        return affectedComponents_;
    }

private:
    friend class CompiledModel;
    void setId(ReactionRuleId id) { id_ = id; }

    ReactionRuleId id_;
    std::string name_;
    std::string label_;
    bool conservativeInvalidation_ = false;
    bool bidirectional_ = false;
    std::vector<MutationSignature> mutations_;
    std::vector<CompiledRateLaw> rateLaws_;
    std::vector<CompiledModifier> modifiers_;
    std::vector<CompiledFilter> filters_;
    std::vector<Pattern> reactantPatterns_;
    std::vector<Pattern> productPatterns_;
    std::vector<ast::ReactionRule::ComponentRef> affectedComponents_;
};

} // namespace bng::compile
