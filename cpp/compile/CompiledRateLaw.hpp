#pragma once

#include <optional>
#include <string>
#include <vector>

#include "Capabilities.hpp"
#include "SymbolTable.hpp"
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

enum class ResolvedExpressionKind {
    Number,
    ParameterRef,
    ObservableRef,
    FunctionRef,
    LocalRef,
    TimeRef,
    Unary,
    Binary,
    BuiltinCall,
    TableFunction,
    Unresolved,
};

struct ResolvedExpression {
    ResolvedExpressionKind kind = ResolvedExpressionKind::Unresolved;
    std::string source;
    std::string operation;
    std::optional<SymbolRef> symbol;
    std::string localName;
    std::vector<ResolvedExpression> arguments;
};

// Typed execution metadata for a source rate expression.  Phase 1 only
// classifies existing BNGL semantics; it does not change evaluation.
struct CompiledRateLaw {
    RateLawKind kind = RateLawKind::Expression;
    std::string sourceExpression;
    std::vector<ast::Expression> arguments;

    const ResolvedExpression& resolvedExpression() const { return resolved_; }

    const std::vector<SymbolRef>& references() const { return references_; }
    const std::vector<Diagnostic>& diagnostics() const { return diagnostics_; }

    bool isEnergyCoupled() const { return kind == RateLawKind::ArrheniusEnergy; }

    static CompiledRateLaw compile(const ast::Expression& expression);
    static CompiledRateLaw compile(const ast::Expression& expression,
                                   const SymbolTable& symbols);
    static CompiledRateLaw compile(const ast::Expression& expression,
                                   const SymbolTable& symbols,
                                   const std::vector<std::string>& localNames);

private:
    std::vector<SymbolRef> references_;
    std::vector<Diagnostic> diagnostics_;
    ResolvedExpression resolved_;
};

} // namespace bng::compile
