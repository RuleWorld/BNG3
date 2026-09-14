#pragma once

#include <vector>

#include "CompiledModel.hpp"
#include "PatternLowering.hpp"

namespace bng::ast {
class Expression;
class SpeciesGraph;
}

namespace bng::compile {

// Transitional lowering helpers used by legacy execution engines while their
// runtime algorithms are being detached from ast::Model. These functions are
// intentionally one-way: semantic meaning is read from the resolved compile
// IR and materialized into legacy value objects without reparsing BNGL text.
ast::Expression lowerResolvedExpressionToAst(
    const ResolvedExpression& expression,
    const CompiledModel& model);

ast::SpeciesGraph lowerPatternToSpeciesGraph(
    const Pattern& pattern,
    BNGcoreLoweringContext& context);

std::vector<ast::SpeciesGraph> lowerPatternsToSpeciesGraphs(
    const std::vector<Pattern>& patterns,
    BNGcoreLoweringContext& context);

} // namespace bng::compile
