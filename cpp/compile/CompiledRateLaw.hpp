#pragma once

#include <optional>
#include <string>
#include <vector>

#include "Capabilities.hpp"
#include "SymbolTable.hpp"
#include "ast/Expression.hpp"
#include "units/Unit.hpp"

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
    ReactantCountRef,
    TimeRef,
    Unary,
    Binary,
    BuiltinCall,
    TableFunction,
    Unresolved,
};

enum class UnaryOp {
    Plus,
    Negate,
    LogicalNot,
    Unknown,
};

enum class BinaryOp {
    Add,
    Subtract,
    Multiply,
    Divide,
    Power,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    Equal,
    NotEqual,
    LogicalAnd,
    LogicalOr,
    Unknown,
};

enum class BuiltinFunction {
    Abs,
    Acos,
    Acosh,
    Asin,
    Asinh,
    Atan,
    Atanh,
    Avg,
    Ceil,
    Cos,
    Cosh,
    E,
    Exp,
    Floor,
    If,
    Ln,
    Log10,
    Log2,
    Max,
    Min,
    MRatio,
    Pi,
    Rint,
    Sin,
    Sinh,
    Sqrt,
    Sum,
    Tan,
    Tanh,
    Time,
    Arrhenius,
    Saturation,
    MichaelisMenten,
    Hill,
    FunctionProduct,
    Hybrid,
    TableFunction,
    Unknown,
};

struct ResolvedExpression {
    ResolvedExpressionKind kind = ResolvedExpressionKind::Unresolved;

    // Source spelling is diagnostic/provenance metadata only. Execution must
    // use the typed fields below.
    std::string source;
    std::string operation;

    double numberValue = 0.0;
    std::optional<SymbolRef> symbol;
    std::string localName;
    std::size_t reactantIndex = 0; // zero-based for reactant_1 ... reactant_9
    std::optional<UnaryOp> unaryOp;
    std::optional<BinaryOp> binaryOp;
    std::optional<BuiltinFunction> builtin;
    std::vector<ResolvedExpression> arguments;

    // Table-function payload. Keeping it in the semantic tree avoids having to
    // recover execution data from the source expression later.
    std::vector<double> tableX;
    std::vector<double> tableY;
    std::string tableFile;
    std::string tableMethod;

    bool fullyResolved() const noexcept;
};

// Typed execution metadata for a source rate expression. Source spelling is
// retained only for diagnostics/round-tripping; semantic consumers use the
// resolved expression tree.
struct CompiledRateLaw {
    RateLawKind kind = RateLawKind::Expression;
    std::string sourceExpression;
    // Compatibility view retained for the energy/compiler contract tests;
    // semantic consumers use resolvedExpression() below.
    std::vector<ast::Expression> arguments;
    std::optional<units::Unit> unit;
    std::string unitName;

    const ResolvedExpression& resolvedExpression() const { return resolved_; }
    const std::vector<SymbolRef>& references() const { return references_; }
    const std::vector<Diagnostic>& diagnostics() const { return diagnostics_; }
    bool isEnergyCoupled() const { return kind == RateLawKind::ArrheniusEnergy; }
    bool fullyResolved() const noexcept { return resolved_.fullyResolved(); }

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
