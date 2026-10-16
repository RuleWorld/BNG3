#pragma once

#include <cstddef>
#include <vector>

namespace BNGcore {
class Node;
class PatternGraph;
}

namespace bng::ast {

// Structural information available for one candidate reaction. Mapped
// molecules follow compiled reactant-pattern order; product graphs and their
// pattern indices appear once the transformation is constructed. This context
// contains graph structure only, never populations or state.
struct RateCandidateContext {
    std::vector<const BNGcore::PatternGraph *> speciesGraphs;
    std::vector<std::vector<const BNGcore::Node *>> mappedMolecules;
    std::vector<const BNGcore::PatternGraph *> productSpeciesGraphs;
    std::vector<std::size_t> productPatternIndices;
};

} // namespace bng::ast
