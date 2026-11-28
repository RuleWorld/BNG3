#pragma once

#include <algorithm>
#include <numeric>
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
  PatternSide side = PatternSide::Reactant;
  std::size_t patternIndex = 0;
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
    // Pattern indices whose default deletion removes the full matched species.
    // Resolved once by the compiler; backend lowering must preserve connectivity.
    std::vector<std::size_t> wholeSpeciesDeletions;
    std::vector<CompiledFilter> filters;
    std::vector<CompiledLocalScope> localScopes;

    // Reactant-pattern permutation symmetry factor (1 / |Aut|): counts
    // permutations of identical reactant patterns that leave the rule's
    // transformations, deletions, filters, and local scopes invariant.
    // Shared by direct NFsim and BNG-XML export.
    double wholeReactantPermutationFactor() const noexcept {
        const std::size_t n = reactantPatterns.size();
        if (n < 2 || n > 8 || !transformationsComplete) return 1.0;

        // Product filters may depend on specific product pattern indices.
        for (const auto& filter : filters) {
            if (filter.products) return 1.0;
        }

        // An added molecule inside a multi-molecule product pattern may bond
        // asymmetrically to one specific reactant via new-molecule bonds.
        for (const auto& mutation : mutations) {
            if (mutation.kind == MutationKind::AddMolecule &&
                mutation.molecule.patternIndex < productPatterns.size() &&
                productPatterns[mutation.molecule.patternIndex].molecules().size() > 1) {
                return 1.0;
            }
        }

        // Compartment transport is not encoded in MutationSignature; when
        // non-deleted reactants survive into products, require matching
        // (moleculeType, effectiveCompartment) multisets so asymmetric
        // transport (e.g. A@EC + A@EC -> A@CP + A@EC) is not over-divided.
        if (wholeSpeciesDeletions.size() != n && !productPatterns.empty()) {
            std::vector<std::pair<std::string, std::string>> survivingReactants;
            std::vector<std::pair<std::string, std::string>> nonAddedProducts;
            const auto effectiveComp = [](const Pattern& pat, const PatternMoleculeDescriptor& mol) {
                return !mol.compartment.empty() ? mol.compartment : pat.compartment();
            };
            bool anyCompartment = false;
            for (std::size_t pi = 0; pi < n; ++pi) {
                const auto& pat = reactantPatterns[pi];
                if (!pat.compartment().empty()) anyCompartment = true;
                for (std::size_t mi = 0; mi < pat.molecules().size(); ++mi) {
                    const auto& mol = pat.molecules()[mi];
                    if (!mol.compartment.empty()) anyCompartment = true;
                    const bool deleted =
                        std::find(wholeSpeciesDeletions.begin(), wholeSpeciesDeletions.end(), pi) !=
                            wholeSpeciesDeletions.end() ||
                        std::any_of(mutations.begin(), mutations.end(), [&](const auto& m) {
                            return m.kind == MutationKind::DeleteMolecule &&
                                   m.molecule.side == PatternSide::Reactant &&
                                   m.molecule.patternIndex == pi &&
                                   m.molecule.moleculeIndex == mi;
                        });
                    if (!deleted) {
                        survivingReactants.emplace_back(mol.moleculeType, effectiveComp(pat, mol));
                    }
                }
            }
            for (std::size_t pi = 0; pi < productPatterns.size(); ++pi) {
                const auto& pat = productPatterns[pi];
                if (!pat.compartment().empty()) anyCompartment = true;
                for (std::size_t mi = 0; mi < pat.molecules().size(); ++mi) {
                    const auto& mol = pat.molecules()[mi];
                    if (!mol.compartment.empty()) anyCompartment = true;
                    const bool added = std::any_of(mutations.begin(), mutations.end(), [&](const auto& m) {
                        return m.kind == MutationKind::AddMolecule &&
                               m.molecule.side == PatternSide::Product &&
                               m.molecule.patternIndex == pi &&
                               m.molecule.moleculeIndex == mi;
                    });
                    if (!added) {
                        nonAddedProducts.emplace_back(mol.moleculeType, effectiveComp(pat, mol));
                    }
                }
            }
            if (anyCompartment) {
                std::sort(survivingReactants.begin(), survivingReactants.end());
                std::sort(nonAddedProducts.begin(), nonAddedProducts.end());
                if (survivingReactants != nonAddedProducts) return 1.0;
            }
        }

        // Check whether two reactant patterns are structurally identical with
        // matching molecule/site index ordering so permuting patternIndex maps
        // mutation site/molecule refs accurately.
        const auto patternsInterchangeable = [&](std::size_t a, std::size_t b) -> bool {
            if (a == b) return true;
            if (!(reactantPatterns[a] == reactantPatterns[b])) return false;
            const auto& ma = reactantPatterns[a].molecules();
            const auto& mb = reactantPatterns[b].molecules();
            if (ma.size() != mb.size()) return false;
            for (std::size_t mi = 0; mi < ma.size(); ++mi) {
                if (ma[mi].moleculeType != mb[mi].moleculeType ||
                    ma[mi].compartment != mb[mi].compartment ||
                    ma[mi].sites.size() != mb[mi].sites.size()) {
                    return false;
                }
                for (std::size_t si = 0; si < ma[mi].sites.size(); ++si) {
                    if (ma[mi].sites[si].componentName != mb[mi].sites[si].componentName) {
                        return false;
                    }
                }
            }
            return true;
        };

        bool hasIdenticalPair = false;
        for (std::size_t i = 0; i < n && !hasIdenticalPair; ++i) {
            for (std::size_t j = i + 1; j < n; ++j) {
                if (patternsInterchangeable(i, j)) {
                    hasIdenticalPair = true;
                    break;
                }
            }
        }
        if (!hasIdenticalPair) return 1.0;

        // Any reactant pattern bound to a local-function scope is pinned.
        std::vector<bool> pinned(n, false);
        for (const auto& scope : localScopes) {
            if (scope.side == PatternSide::Reactant && scope.patternIndex < n) {
                pinned[scope.patternIndex] = true;
            }
        }

        std::vector<bool> wholeDeleted(n, false);
        for (const std::size_t idx : wholeSpeciesDeletions) {
            if (idx < n) wholeDeleted[idx] = true;
        }

        struct CanonicalMutation {
            MutationKind kind = MutationKind::ChangeState;
            PatternSiteRef a;
            PatternSiteRef b;
            PatternMoleculeRef mol;
            std::string newState;

            bool operator==(const CanonicalMutation& other) const noexcept {
                return kind == other.kind && a == other.a && b == other.b &&
                       mol == other.mol && newState == other.newState;
            }
            bool operator<(const CanonicalMutation& other) const noexcept {
                if (kind != other.kind) return kind < other.kind;
                if (!(a == other.a)) return a < other.a;
                if (!(b == other.b)) return b < other.b;
                if (mol.side != other.mol.side) return mol.side < other.mol.side;
                if (mol.patternIndex != other.mol.patternIndex) return mol.patternIndex < other.mol.patternIndex;
                if (mol.moleculeIndex != other.mol.moleculeIndex) return mol.moleculeIndex < other.mol.moleculeIndex;
                return newState < other.newState;
            }
        };

        const auto canonicalizeMutations = [&](const std::vector<std::size_t>& perm) {
            const auto mapSite = [&](PatternSiteRef ref) {
                if (ref.side == PatternSide::Reactant && ref.patternIndex < n) {
                    ref.patternIndex = perm[ref.patternIndex];
                }
                return ref;
            };
            const auto mapMol = [&](PatternMoleculeRef ref) {
                if (ref.side == PatternSide::Reactant && ref.patternIndex < n) {
                    ref.patternIndex = perm[ref.patternIndex];
                }
                return ref;
            };
            std::vector<CanonicalMutation> out;
            out.reserve(mutations.size());
            for (const auto& m : mutations) {
                CanonicalMutation cm;
                cm.kind = m.kind;
                switch (m.kind) {
                case MutationKind::AddBond:
                case MutationKind::DeleteBond: {
                    auto sa = mapSite(m.source);
                    auto sb = mapSite(m.partner);
                    if (sb < sa) std::swap(sa, sb);
                    cm.a = sa;
                    cm.b = sb;
                    break;
                }
                case MutationKind::ChangeState:
                    cm.a = mapSite(m.source);
                    cm.newState = m.newState;
                    break;
                case MutationKind::DeleteMolecule:
                    cm.mol = mapMol(m.molecule);
                    break;
                case MutationKind::AddMolecule:
                    cm.mol = m.molecule;
                    break;
                }
                out.push_back(std::move(cm));
            }
            std::sort(out.begin(), out.end());
            return out;
        };

        const auto filtersInvariant = [&](const std::vector<std::size_t>& perm) -> bool {
            if (filters.empty()) return true;
            std::vector<bool> matched(filters.size(), false);
            for (const auto& f : filters) {
                const std::size_t mappedIndex =
                    f.patternIndex < n ? perm[f.patternIndex] : f.patternIndex;
                bool found = false;
                for (std::size_t j = 0; j < filters.size(); ++j) {
                    if (matched[j]) continue;
                    const auto& g = filters[j];
                    if (g.include == f.include && g.products == f.products &&
                        g.patternIndex == mappedIndex && g.patterns == f.patterns) {
                        matched[j] = true;
                        found = true;
                        break;
                    }
                }
                if (!found) return false;
            }
            return true;
        };

        std::vector<std::size_t> identity(n);
        std::iota(identity.begin(), identity.end(), 0);
        const auto baseMutations = canonicalizeMutations(identity);

        // Group interchangeable, unpinned reactant indices into equivalence classes
        // and enumerate only within-class permutations.
        std::vector<std::vector<std::size_t>> classes;
        std::vector<bool> assigned(n, false);
        for (std::size_t i = 0; i < n; ++i) {
            if (assigned[i] || pinned[i]) continue;
            std::vector<std::size_t> group = {i};
            assigned[i] = true;
            for (std::size_t j = i + 1; j < n; ++j) {
                if (!assigned[j] && !pinned[j] &&
                    wholeDeleted[i] == wholeDeleted[j] &&
                    patternsInterchangeable(i, j)) {
                    group.push_back(j);
                    assigned[j] = true;
                }
            }
            if (group.size() > 1) {
                classes.push_back(std::move(group));
            }
        }
        if (classes.empty()) return 1.0;

        std::size_t automorphisms = 0;
        std::vector<std::size_t> perm = identity;
        const auto search = [&](const auto& self, std::size_t classIdx) -> void {
            if (classIdx == classes.size()) {
                if (filtersInvariant(perm) && canonicalizeMutations(perm) == baseMutations) {
                    ++automorphisms;
                }
                return;
            }
            const auto& group = classes[classIdx];
            auto target = group;
            do {
                for (std::size_t k = 0; k < group.size(); ++k) {
                    perm[group[k]] = target[k];
                }
                self(self, classIdx + 1);
            } while (std::next_permutation(target.begin(), target.end()));
            for (const std::size_t idx : group) {
                perm[idx] = idx;
            }
        };
        search(search, 0);
        return automorphisms > 1 ? (1.0 / static_cast<double>(automorphisms)) : 1.0;
    }

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
    const std::optional<ast::Expression>& delayExpression() const { return delayExpression_; }
    const std::optional<ResolvedExpression>& resolvedDelayExpression() const { return resolvedDelayExpression_; }
    bool isNonConsuming() const { return nonConsuming_; }
    bool isAbsoluteFlux() const { return absoluteFlux_; }

    // Signed reservoir work from a `driven_by(W)` annotation.
    //
    // Semantics: the forward direction consumes +W and the reverse direction
    // -W, shifting local detailed balance to k_f/k_r = exp[-(dG - W)/RT].
    // Absent work is reported as hasDrivingWork() == false with a zero value,
    // so a backend that ignores it still produces the undriven rates.
    bool hasDrivingWork() const { return hasDrivingWork_; }
    const std::string& drivingWorkExpression() const { return drivingWorkExpression_; }
    const std::optional<double>& drivingWorkValue() const { return drivingWorkValue_; }

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
    std::optional<ast::Expression> delayExpression_;
    std::optional<ResolvedExpression> resolvedDelayExpression_;
    bool nonConsuming_ = false;
    bool absoluteFlux_ = false;
    bool hasDrivingWork_ = false;
    std::string drivingWorkExpression_;
    std::optional<double> drivingWorkValue_;
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
