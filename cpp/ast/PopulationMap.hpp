#pragma once

#include <string>
#include <vector>

#include "Expression.hpp"

namespace bng::ast {

/**
 * PopulationMap - Represents a mapping from a species pattern to a
 * population-level variable/function.
 *
 * In BNG2, the "begin population maps" block defines how individual
 * species patterns are aggregated into population-level variables for
 * hybrid population/particle simulations.
 *
 * Grammar: [label:] species_pattern -> functionName(args...)
 *
 * Note: Parsing and storage is supported. Actual population-based
 * simulation refinement (RefineRule) is not yet executed.
 */
struct PopulationMap {
    std::string label;
    std::string patternText;         // raw species pattern text
    // Canonical population-species target and mapping rate. In BNGL a map is
    // `pattern -> Population(args) rate`; the RHS species is not a function.
    std::string populationName;
    std::vector<std::string> populationArgs;
    Expression rateExpression = Expression::number(0.0);
    std::string rateText;
    bool hasExplicitRate = false;

    // Compatibility aliases retained for older callers while they migrate.
    std::string populationFunction;
    std::vector<std::string> functionArgs;
};

} // namespace bng::ast
