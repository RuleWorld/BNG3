#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "SemanticIds.hpp"

namespace bng::ast {
class Model;
class SpeciesGraph;
}

namespace BNGcore {
class PatternGraph;
}

namespace bng::compile {

struct Diagnostic;
class SymbolTable;

struct PatternMoleculeOccurrenceId {
    std::size_t value = 0;
};

struct PatternSiteOccurrenceId {
    std::size_t value = 0;
};

struct PatternBondGroupId {
    std::size_t value = 0;
};

enum class BondConstraintKind {
    Unspecified,
    Unbound,
    Bound,
    Any,
    Exact,
};

enum class StateConstraintKind {
    Any,
    Exact,
    Set,
};

struct PatternStateConstraint {
    StateConstraintKind kind = StateConstraintKind::Any;
    std::string source;
    std::optional<StateId> exact;
    std::vector<StateId> states;
};

struct PatternBondDescriptor {
    std::string constraint;
    BondConstraintKind kind = BondConstraintKind::Unspecified;
    PatternBondGroupId group;
};

// Backend-independent, value-like description of a resolved BNGL site.
// Human-readable names are retained for diagnostics/round-tripping; semantic
// consumers should prefer componentType/stateConstraintResolved when present.
struct PatternSiteDescriptor {
    PatternSiteOccurrenceId occurrence;
    std::string componentName;
    std::string stateConstraint;
    std::string bondConstraint;
    std::string label;
    BondConstraintKind bondKind = BondConstraintKind::Unspecified;
    PatternBondGroupId bondGroup;
    std::vector<PatternBondDescriptor> bondConstraints;
    std::optional<ComponentTypeId> componentType;
    PatternStateConstraint stateConstraintResolved;
};

struct PatternMoleculeDescriptor {
    PatternMoleculeOccurrenceId occurrence;
    std::string moleculeType;
    std::string compartment;
    std::vector<PatternSiteDescriptor> sites;
    std::optional<MoleculeTypeId> moleculeTypeId;
    std::optional<CompartmentId> compartmentId;
};

class Pattern {
public:
    // Parse compact BNGL pattern text for compatibility/tests. This path is
    // deliberately not authoritative for backend compilation because it has no
    // declaration context and therefore cannot assign typed semantic IDs.
    static Pattern parse(std::string_view text);

    // Build from an already-resolved AST graph. The simple overload preserves
    // the compatibility API. The context-aware overload additionally resolves
    // molecule/component/state/compartment identifiers and is the canonical
    // compiler path.
    static Pattern fromSpeciesGraph(const ast::SpeciesGraph& graph);
    static Pattern fromSpeciesGraph(const ast::SpeciesGraph& graph,
                                    const ast::Model& model,
                                    const SymbolTable& symbols,
                                    std::vector<Diagnostic>* diagnostics = nullptr);

    static Pattern fromPatternGraph(const BNGcore::PatternGraph& graph,
                                    std::string_view compartment = {});

    // Resolve a parsed/value-like pattern against the semantic declarations.
    // Returns false and emits diagnostics for unknown declarations/states.
    bool resolve(const ast::Model& model,
                 const SymbolTable& symbols,
                 std::vector<Diagnostic>* diagnostics = nullptr);
    bool isResolved() const noexcept { return resolved_; }

    std::size_t moleculeCount() const noexcept { return molecules_.size(); }
    bool hasSite(std::string_view moleculeType,
                 std::string_view componentName) const noexcept;
    std::string stateConstraint(std::string_view moleculeType,
                                std::string_view componentName) const;

    const std::vector<PatternMoleculeDescriptor>& molecules() const noexcept {
        return molecules_;
    }
    const std::string& sourceText() const noexcept { return sourceText_; }
    const std::string& compartment() const noexcept { return compartment_; }
    std::optional<CompartmentId> compartmentId() const noexcept { return compartmentId_; }
    bool compartmentIsPrefix() const noexcept { return compartmentIsPrefix_; }

    bool semanticEqual(const Pattern& other) const noexcept;
    bool operator==(const Pattern& other) const noexcept { return semanticEqual(other); }
    bool operator!=(const Pattern& other) const noexcept { return !semanticEqual(other); }

private:
    std::vector<PatternMoleculeDescriptor> molecules_;
    std::string sourceText_;
    std::string compartment_;
    std::optional<CompartmentId> compartmentId_;
    bool compartmentIsPrefix_ = false;
    bool resolved_ = false;
};

using PatternDescriptor = Pattern;

} // namespace bng::compile
