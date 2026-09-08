#pragma once

#include "Pattern.hpp"
#include "core/BNGcore.hpp"

namespace bng::ast {
class Model;
}

namespace bng::compile {

// Explicit lowering boundary from the value-like semantic Pattern to the
// legacy BNGcore graph consumed by existing matchers and writers. The graph's
// type storage remains owned by the supplied model; callers must keep it alive
// while using the returned graph.
BNGcore::PatternGraph lowerPatternToBNGcore(
    const Pattern& pattern,
    ast::Model& model,
    bool treatUnspecifiedBondAsWildcard = false);

} // namespace bng::compile
