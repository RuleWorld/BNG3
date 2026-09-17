#pragma once

// Post-parse lowering of the synthetic thermodynamic metadata produced by
// normalizeThermodynamicSyntax().
//
// This is deliberately separate from BNGAstVisitor: it touches only ast::Model
// and ast::ReactionRule, with expression parsing injected as a callback. That
// keeps it free of any ANTLR dependency, so the partitioning, renumbering and
// validation rules can be executed directly in a test instead of only being
// reachable through a full parse.
//
// What it does, in order:
//
//   1. Partitions the model's reaction rules into synthetic barrier rules
//      (label `__bng3_barrier_<N>`) and ordinary rules, preserving source
//      order within each group.
//   2. Attaches each `driven_by(W)` annotation to the ordinary rule at its
//      recorded index. Indexing over ordinary rules only is what makes the
//      annotation independent of where the barrier block appeared in source.
//   3. Renumbers the surviving ordinary rules to R1..Rn, so the model is
//      indistinguishable from one written without a barrier patterns block
//      even though the synthetic rules consumed names during parsing.
//   4. Moves the barrier rules into the model's barrier patterns, in barrier
//      index order, reattaching any user-supplied label.
//
// Every inconsistency throws std::runtime_error rather than dropping metadata:
// a silently discarded barrier or drive changes the model's kinetics without
// changing its text.

#include <cstddef>
#include <functional>
#include <map>
#include <string>

namespace bng::ast {
class Expression;
class Model;
} // namespace bng::ast

namespace bng::parser {

// Parses a work expression from its source text. Supplied by the caller so
// this unit does not depend on the generated parser.
using ExpressionParser = std::function<ast::Expression(const std::string&)>;

// Returns true when the model carried any synthetic thermodynamic metadata and
// was therefore rewritten; false means an ordinary model was left untouched
// (rule names and order are preserved exactly).
bool finalizeThermodynamicMetadata(
    ast::Model& model,
    const std::map<std::size_t, std::string>& barrierLabels,
    const std::map<std::size_t, std::string>& drivingWork,
    const ExpressionParser& parseExpression);

} // namespace bng::parser
