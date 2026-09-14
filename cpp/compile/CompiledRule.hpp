#pragma once

#include <algorithm>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "CompiledRateLaw.hpp"
#include "Pattern.hpp"
#include "SemanticIds.hpp"

namespace bng::ast { class Model; class ReactionRule; }

namespace bng::compile {

class SymbolTable;
namespace detail { class RuleCompiler; }

enum class PatternSide {
    Reactant,
    Product,
};

struct PatternMoleculeRef {
    PatternSide side = PatternSide::Reactant;
    std::size_t patternIndex = 0;
    std::size_t moleculeIndex = 0;

    friend bool operator==(const PatternMoleculeRef& left,
                           const PatternMoleculeRef& right) noexcept {
        return left.side == right.side && left.patternIndex == right.patternIndex &&
               left.moleculeIndex == right.moleculeIndex;
    }
};

struct PatternSiteRef {
    PatternSide side = PatternSide::Reactant;
    std::size_t patternIndex = 0;
    std::size_t moleculeIndex = 0;
    std::size_t siteIndex = 0;

    friend bool operator==(const PatternSiteRef& left,
                           const PatternSiteRef& right) noexcept {
        return left.side == right.side && left.patternIndex == right.patternIndex &&
               left.moleculeIndex == right.moleculeIndex && left.siteIndex == right.siteIndex;
    }
    friend bool operator<(const PatternSiteRef& left,
                          const PatternSiteRef& right) noexcept {
        if (left.side != right.side) return left.side < right.side;
        if (left.patternIndex != right.patternIndex) return left.patternIndex < right.patternIndex;
        if (left.moleculeIndex != right.moleculeIndex) return left.moleculeIndex < right.moleculeIndex;
        return left.siteIndex < right.siteIndex;
    }
};

enum class MutationKind {
    AddBond,
    DeleteBond,
    ChangeState,
    AddMolecule,
    DeleteMolecule,
};

enum class LocalScopeKind {
    Molecule,
    Species,
};

struct CompiledLocalScope {
    std::string name;
    std::size_t reactantPatternIndex = 0;
    LocalScopeKind kind = LocalScopeKind::Molecule;
    // Exact molecule occurrence for molecule-local scopes. Species scopes do
    // not require an anchor and leave this unset.
    std::optional<std::size_t> moleculeOccurrence;
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
    PatternSiteRef source;
    PatternSiteRef partner;
    PatternMoleculeRef molecule;
    std::string newState; // diagnostic/round-trip spelling
    std::optional<StateId> newStateId;
};

struct CompiledRuleDirection {
    std::vector<Pattern> reactantPatterns;
    std::vector<Pattern> productPatterns;
    std::optional<CompiledRateLaw> rateLaw;
    std::vector<MutationSignature> mutations;
    std::vector<CompiledFilter> filters;
    std::vector<CompiledLocalScope> localScopes;

    const CompiledLocalScope* findLocalScope(const std::string& name) const noexcept {
        const auto it = std::find_if(localScopes.begin(), localScopes.end(),
            [&](const auto& scope) { return scope.name == name; });
        return it == localScopes.end() ? nullptr : &*it;
    }

    // False means this direction is semantically represented but the local
    // edit program could not be proven complete. Backends must use a declared
    // compatibility path rather than infer missing transformations.
    bool transformationsComplete = true;
};

class CompiledRule {
public:
    static CompiledRule compile(const ast::ReactionRule& rule);
    static CompiledRule compile(const ast::ReactionRule& rule,
                                const SymbolTable& symbols,
                                std::vector<Diagnostic>* diagnostics = nullptr);
    static CompiledRule compile(const ast::ReactionRule& rule,
                                const ast::Model& model,
                                const SymbolTable& symbols,
                                std::vector<Diagnostic>* diagnostics = nullptr);

    const std::string& name() const { return name_; }
    ReactionRuleId id() const { return id_; }
    const std::string& label() const { return label_; }
    bool requiresConservativeInvalidation() const { return conservativeInvalidation_; }
    bool isBidirectional() const { return bidirectional_; }

    const CompiledRuleDirection& forward() const { return forward_; }
    const std::optional<CompiledRuleDirection>& reverse() const { return reverse_; }

    // Compatibility accessors: these expose the forward direction while older
    // compiler clients migrate to forward()/reverse().
    const std::vector<MutationSignature>& mutations() const { return forward_.mutations; }
    const std::vector<CompiledRateLaw>& rateLaws() const { return rateLaws_; }
    const std::vector<CompiledModifier>& modifiers() const { return modifiers_; }
    const std::vector<CompiledFilter>& filters() const { return forward_.filters; }
    const std::vector<Pattern>& reactantPatterns() const { return forward_.reactantPatterns; }
    const std::vector<Pattern>& productPatterns() const { return forward_.productPatterns; }

    const std::vector<PatternSiteRef>& affectedComponents() const {
        return affectedComponents_;
    }
    const std::vector<std::pair<PatternMoleculeRef, PatternMoleculeRef>>&
    moleculeMappings() const { return moleculeMappings_; }
    const std::vector<std::pair<PatternSiteRef, PatternSiteRef>>&
    componentMappings() const { return componentMappings_; }

private:
    friend class CompiledModel;
    friend class detail::RuleCompiler;
    void setId(ReactionRuleId id) { id_ = id; }

    ReactionRuleId id_;
    std::string name_;
    std::string label_;
    bool conservativeInvalidation_ = false;
    bool bidirectional_ = false;
    std::vector<CompiledRateLaw> rateLaws_;
    std::vector<CompiledModifier> modifiers_;
    CompiledRuleDirection forward_;
    std::optional<CompiledRuleDirection> reverse_;
    std::vector<PatternSiteRef> affectedComponents_;
    // pair order is product -> reactant, matching the resolved AST contract.
    std::vector<std::pair<PatternMoleculeRef, PatternMoleculeRef>> moleculeMappings_;
    std::vector<std::pair<PatternSiteRef, PatternSiteRef>> componentMappings_;
};

} // namespace bng::compile
