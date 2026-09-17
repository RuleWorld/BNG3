#pragma once

// Lowers ast::BarrierPattern transitions into canonical reaction-center keys.
//
// Barrier patterns reuse ReactionRule, so the transition's operations are
// already computed by the existing graph-diff machinery. This layer only has
// to classify the single rewrite and read the molecule type, component name
// and endpoint states off the patterns.
//
// Everything it cannot express exactly fails closed: a barrier that silently
// matched nothing, or matched more than the user wrote, would change kinetics
// without changing the model text.

#include <functional>
#include <string>
#include <vector>

#include "BarrierTable.hpp"

namespace bng::ast {
class BarrierPattern;
class Model;
class ReactionRule;
} // namespace bng::ast

namespace bng::compile::energy {

// Resolved reaction center of one barrier transition, before its energy has
// been evaluated.
struct BarrierCenter {
    ReactionCenterKey key;
    std::string label;
};

// Extracts the reaction center of a single barrier transition.
// Returns false and fills `diagnostic` when the rewrite is not a single
// supported state change or bond change.
bool compileBarrierCenter(
    const ast::ReactionRule& transition,
    ReactionCenterKey& key,
    std::string& diagnostic);

// Builds the barrier table for a whole model.
//
// `resolveEnergy` evaluates a barrier pattern's expression to a number; it is
// supplied by the caller because parameter resolution differs between the
// network compiler and the NFsim adapters. It must return false when the
// expression is not statically evaluable, since a dynamic transition-state
// energy is not supported and must not be folded to its initial value.
//
// Returns false when any barrier pattern cannot be lowered; `diagnostics`
// then holds one message per rejected pattern and the table is left unused.
bool buildBarrierTable(
    const ast::Model& model,
    const std::function<bool(const ast::BarrierPattern&, double&, std::string&)>&
        resolveEnergy,
    BarrierTable& table,
    std::vector<std::string>& diagnostics);

} // namespace bng::compile::energy
