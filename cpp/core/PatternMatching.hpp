#pragma once

#include <cstddef>

namespace BNGcore {
class Node;
class PatternGraph;
}

namespace bng::ast { class SpeciesGraph; }

namespace bng::core {

// Backend-neutral BioNetGen graph-embedding semantics layered on top of
// BNGcore::UllmannSGIso. These functions enforce BNGL state, compartment and
// bond-cardinality rules and are shared by AST compatibility code and compiled
// backends.
bool patternMatchesSpecies(const ast::SpeciesGraph& pattern,
                           const ast::SpeciesGraph& species);
bool patternMatchesSpecies(const BNGcore::PatternGraph& pattern,
                           const BNGcore::PatternGraph& species);

std::size_t countPatternMatches(const ast::SpeciesGraph& pattern,
                                const BNGcore::PatternGraph& speciesGraph);
std::size_t countPatternMatches(const BNGcore::PatternGraph& pattern,
                                const BNGcore::PatternGraph& speciesGraph);

std::size_t countPatternMatchesForScopedMolecule(
    const ast::SpeciesGraph& pattern,
    const ast::SpeciesGraph& species,
    const BNGcore::Node* scopedMolecule);

std::size_t countPatternMatchesForScopedMolecule(
    const ast::SpeciesGraph& pattern,
    const BNGcore::PatternGraph& speciesGraph,
    const BNGcore::Node* scopedMolecule);

} // namespace bng::core
