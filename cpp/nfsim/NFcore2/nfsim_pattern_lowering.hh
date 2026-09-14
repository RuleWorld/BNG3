#pragma once

#include <set>
#include <string>
#include <utility>
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

using RuntimeComponentNames = std::vector<std::vector<std::string>>;

// Expand an NFsim equivalent-component orbit into concrete runtime names only
// where the caller identifies a reaction-center site.  Other symmetric sites
// remain generic matching constraints.  `assignments` is parallel to `builds`
// and records the concrete runtime component name selected for every site.
bool lowerPatternToNFsimPermutations(
    const bng::compile::Pattern& pattern,
    NFcore::System& system,
    const std::set<std::pair<std::size_t, std::size_t>>& concreteSymmetricSites,
    std::vector<std::vector<NFcore::TemplateMolecule*>>& builds,
    std::vector<RuntimeComponentNames>& assignments,
    bool& hasDisjointSets,
    int& suggestedTraversalLimit,
    std::string& diagnostic);

} // namespace NFcore2
