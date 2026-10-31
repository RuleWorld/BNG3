#pragma once

#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "Capabilities.hpp"
#include "SymbolTable.hpp"
#include "ast/Expression.hpp"
#include "units/Unit.hpp"

namespace bng::compile {

struct RateEvaluationContext;

// True when a call spelled with this name resolves to a compiler builtin
// rather than to a user-defined model function. The comparison is
// case-insensitive, matching the compiler's own builtin dispatch.
bool isBuiltinFunctionName(std::string_view name);

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
    Factorial,
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
    Sign,
    Sin,
    Sinh,
    Sqrt,
    Sum,
    Tan,
    Tanh,
    Time,
    Delay,
    Arrhenius,
    Saturation,
    MichaelisMenten,
    Hill,
    FunctionProduct,
    Hybrid,
    TableFunction,
    DistribBernoulli,
    DistribBinomial,
    DistribCauchy,
    DistribChisquare,
    DistribExponential,
    DistribGamma,
    DistribLaplace,
    DistribLognormal,
    DistribNormal,
    DistribPoisson,
    DistribRayleigh,
    DistribUniform,
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

    // Direct semantic evaluation without AST dependence
    double evaluate(const RateEvaluationContext& context) const;
};

// Evaluation context for resolved expressions and compiled rate laws.
struct RateEvaluationContext {
    double time = 0.0;

    // Parameter lookup: by index if symbol has SymbolRef, and/or by name.
    std::function<double(std::size_t index, const std::string& name)> resolveParameter;

    // Observable lookup: by index if symbol has SymbolRef, and/or by name.
    std::function<double(std::size_t index, const std::string& name)> resolveObservable;

    // Reactant count lookup: 0-based index (0 for reactant_1, 1 for reactant_2, ...)
    std::function<double(std::size_t reactantIndex)> resolveReactantCount;

    // Local scope / argument lookup: by local name
    std::function<double(const std::string& localName)> resolveLocal;

    // User-defined function lookup: by name and evaluated argument values
    std::function<double(const std::string& name, const std::vector<double>& args)> resolveFunction;

    // Table lookup: by table file/name and argument value
    std::function<double(const std::string& tableName, double arg)> resolveTable;

    // Historical state lookup for delay(expr, tau)
    std::function<double(const ResolvedExpression& expr, double delayTime)> resolveDelay;

    // Fallback general identifier resolver
    std::function<double(const std::string& name)> resolveIdentifier;

    // Discrete reactant counts mode for stochastic propensities (e.g. max(0, X - offset))
    bool discreteReactantCounts = false;
};

// Dependency kinds are derived from the typed expression tree. This keeps
// backend classification from having to rescan source spellings for names like
// `time`, observables, local variables, or reactant counts. Parameter values
// are intentionally separate: model-level metadata determines whether a
// parameter is time-dependent.
struct RateDependencySummary {
    bool parameter = false;
    bool observable = false;
    bool function = false;
    bool local = false;
    bool reactantCount = false;
    bool time = false;
    bool tableFunction = false;
    bool delay = false;
    bool unresolved = false;

    bool requiresRuntimeEvaluation() const noexcept {
        return observable || function || local || reactantCount || time ||
               tableFunction || delay || unresolved;
    }
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
    const RateDependencySummary& dependencies() const { return dependencies_; }
    bool isEnergyCoupled() const { return kind == RateLawKind::ArrheniusEnergy; }
    bool fullyResolved() const noexcept { return resolved_.fullyResolved(); }

    // Direct semantic evaluation without AST dependence
    double evaluate(const RateEvaluationContext& context) const;
    double evaluate(const std::function<double(const std::string&)>& resolver,
                    double time = 0.0) const;

    // Invalidation and dependency queries
    bool dependsOnTime() const noexcept { return dependencies_.time; }
    bool dependsOnObservables() const noexcept { return dependencies_.observable; }
    bool dependsOnReactantCounts() const noexcept { return dependencies_.reactantCount; }
    bool dependsOnParameters() const noexcept { return dependencies_.parameter; }
    bool dependsOnDelay() const noexcept { return dependencies_.delay; }
    bool requiresRuntimeEvaluation() const noexcept {
        return dependencies_.requiresRuntimeEvaluation();
    }

    bool dependsOnParameter(std::size_t parameterIndex) const noexcept;
    bool dependsOnParameter(const std::string& name) const noexcept;
    bool dependsOnObservable(std::size_t observableIndex) const noexcept;
    bool dependsOnObservable(const std::string& name) const noexcept;

    bool isInvalidatedBy(bool timeChanged) const noexcept {
        return timeChanged && dependencies_.time;
    }

    bool isInvalidatedBy(
        bool timeChanged,
        const std::vector<std::size_t>& changedParameterIndices,
        const std::vector<std::size_t>& changedObservableIndices = {}) const noexcept;

    bool isInvalidatedBy(
        bool timeChanged,
        const std::vector<std::string>& changedParameterNames,
        const std::vector<std::string>& changedObservableNames = {}) const noexcept;

    static CompiledRateLaw compile(const ast::Expression& expression);
    static CompiledRateLaw compile(const ast::Expression& expression,
                                   const SymbolTable& symbols);
    static CompiledRateLaw compile(const ast::Expression& expression,
                                   const SymbolTable& symbols,
                                   const std::vector<std::string>& localNames);
    static CompiledRateLaw compile(
        const ast::Expression& expression, const SymbolTable& symbols,
        const std::vector<std::string>& localNames,
        const std::vector<ast::Function>& functions);

private:
    std::vector<SymbolRef> references_;
    std::vector<Diagnostic> diagnostics_;
    ResolvedExpression resolved_;
    RateDependencySummary dependencies_;
};

// Fast rate-string evaluation shared across engines (ODE, PLA, PSA).
double evaluateRateString(
    const std::string& rateStr,
    const std::function<double(const std::string&)>& resolver);

} // namespace bng::compile
