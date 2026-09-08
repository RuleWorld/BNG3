#pragma once

#include <string>
#include <vector>

#include "compile/Pattern.hpp"

namespace NFcore {
class System;
class TemplateMolecule;
}

namespace NFcore2 {

// Lower the backend-independent semantic pattern into NFsim's mutable
// template graph.  TemplateMolecule instances are registered with the
// supplied System and remain owned by its MoleculeType objects.
bool lowerPatternToNFsim(
    const bng::compile::Pattern& pattern,
    NFcore::System& system,
    std::vector<NFcore::TemplateMolecule*>& templates,
    bool& hasDisjointSets,
    int& suggestedTraversalLimit,
    std::string& diagnostic);

} // namespace NFcore2
