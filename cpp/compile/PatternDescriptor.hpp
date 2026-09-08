#pragma once

#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

namespace bng::ast {
class SpeciesGraph;
}

namespace BNGcore {
class PatternGraph;
}

namespace bng::compile {

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

struct PatternBondDescriptor {
    std::string constraint;
    BondConstraintKind kind = BondConstraintKind::Unspecified;
    PatternBondGroupId group;
};

// Backend-independent, value-like description of a BNGL pattern.
//
// This is intentionally a small migration seam.  It carries semantic pattern
// constraints without exposing BNGcore node ownership to compile clients.
struct PatternSiteDescriptor {
    PatternSiteOccurrenceId occurrence;
    std::string componentName;
    std::string stateConstraint;
    std::string bondConstraint;
    std::string label;
    BondConstraintKind bondKind = BondConstraintKind::Unspecified;
    PatternBondGroupId bondGroup;
    std::vector<PatternBondDescriptor> bondConstraints;
};

struct PatternMoleculeDescriptor {
    PatternMoleculeOccurrenceId occurrence;
    std::string moleculeType;
    std::string compartment;
    std::vector<PatternSiteDescriptor> sites;
};

class Pattern {
public:
    // Parse the compact BNGL pattern form used by energy and semantic tests.
    // This parser is deliberately independent of BNGcore and does not mutate
    // a model registry.
    static Pattern parse(std::string_view text);

    // Build from the already-resolved AST graph.  This is the authoritative
    // path for compiler consumers; it never reparses source text.
    static Pattern fromSpeciesGraph(const ast::SpeciesGraph& graph);

    // Adapter-facing construction for parsed graphs that do not have an
    // owning SpeciesGraph wrapper. The resulting value still owns no graph
    // nodes; it copies only semantic pattern constraints.
    static Pattern fromPatternGraph(const BNGcore::PatternGraph& graph,
                                    std::string_view compartment = {});

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

    // Compare semantic content only. Source spelling and source formatting
    // are intentionally excluded so this can be used by future interchange
    // round-trip tests.
    bool semanticEqual(const Pattern& other) const noexcept;
    bool operator==(const Pattern& other) const noexcept {
        return semanticEqual(other);
    }
    bool operator!=(const Pattern& other) const noexcept {
        return !semanticEqual(other);
    }

private:
    std::vector<PatternMoleculeDescriptor> molecules_;
    std::string sourceText_;
    std::string compartment_;
};

// Compatibility spelling while downstream callers migrate to the canonical
// semantic name.
using PatternDescriptor = Pattern;

} // namespace bng::compile
