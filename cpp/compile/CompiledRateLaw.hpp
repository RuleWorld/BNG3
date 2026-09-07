#pragma once

#include <string>
#include <vector>

#include "ast/Expression.hpp"

namespace bng::compile {

enum class RateLawKind {
    Expression,
    ArrheniusEnergy,
    Saturation,
    MichaelisMenten,
    Hill,
    FunctionProduct,
    Hybrid,
};

// Typed execution metadata for a source rate expression.  Phase 1 only
// classifies existing BNGL semantics; it does not change evaluation.
struct CompiledRateLaw {
    RateLawKind kind = RateLawKind::Expression;
    std::string sourceExpression;
    std::vector<ast::Expression> arguments;

    bool isEnergyCoupled() const { return kind == RateLawKind::ArrheniusEnergy; }

    static CompiledRateLaw compile(const ast::Expression& expression);
};

} // namespace bng::compile
