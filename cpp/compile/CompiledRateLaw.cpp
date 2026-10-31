#include "CompiledRateLaw.hpp"
#include "ast/Expression.hpp"
#include "ast/Function.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <iomanip>
#include <limits>
#include <set>
#include <sstream>
#include <unordered_set>

#include "SymbolTable.hpp"

namespace bng::compile {

namespace {

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

bool isReactantCountName(const std::string& name) {
    return name.size() == 10 && name.compare(0, 9, "reactant_") == 0 &&
           name.back() >= '1' && name.back() <= '9';
}

RateLawKind classifyFunction(const std::string& rawName) {
    const auto name = lower(rawName);
    if (name == "arrhenius") return RateLawKind::ArrheniusEnergy;
    if (name == "sat") return RateLawKind::Saturation;
    if (name == "mm") return RateLawKind::MichaelisMenten;
    if (name == "hill") return RateLawKind::Hill;
    if (name == "functionproduct") return RateLawKind::FunctionProduct;
    if (name == "hybrid") return RateLawKind::Hybrid;
    return RateLawKind::Expression;
}

BuiltinFunction builtinFunction(const std::string& rawName) {
    const auto name = lower(rawName);
    if (name == "abs") return BuiltinFunction::Abs;
    if (name == "acos") return BuiltinFunction::Acos;
    if (name == "acosh") return BuiltinFunction::Acosh;
    if (name == "asin") return BuiltinFunction::Asin;
    if (name == "asinh") return BuiltinFunction::Asinh;
    if (name == "atan") return BuiltinFunction::Atan;
    if (name == "atanh") return BuiltinFunction::Atanh;
    if (name == "avg") return BuiltinFunction::Avg;
    if (name == "ceil") return BuiltinFunction::Ceil;
    if (name == "cos") return BuiltinFunction::Cos;
    if (name == "cosh") return BuiltinFunction::Cosh;
    if (name == "e") return BuiltinFunction::E;
    if (name == "exp") return BuiltinFunction::Exp;
    if (name == "factorial") return BuiltinFunction::Factorial;
    if (name == "floor") return BuiltinFunction::Floor;
    if (name == "if") return BuiltinFunction::If;
    if (name == "ln") return BuiltinFunction::Ln;
    if (name == "log10") return BuiltinFunction::Log10;
    if (name == "log2") return BuiltinFunction::Log2;
    if (name == "max") return BuiltinFunction::Max;
    if (name == "min") return BuiltinFunction::Min;
    if (name == "mratio") return BuiltinFunction::MRatio;
    if (name == "pi") return BuiltinFunction::Pi;
    if (name == "rint") return BuiltinFunction::Rint;
    if (name == "sin") return BuiltinFunction::Sin;
    if (name == "sinh") return BuiltinFunction::Sinh;
    if (name == "sqrt") return BuiltinFunction::Sqrt;
    if (name == "sum") return BuiltinFunction::Sum;
    if (name == "tan") return BuiltinFunction::Tan;
    if (name == "tanh") return BuiltinFunction::Tanh;
    if (name == "t" || name == "time") return BuiltinFunction::Time;
    if (name == "delay") return BuiltinFunction::Delay;
    if (name == "arrhenius") return BuiltinFunction::Arrhenius;
    if (name == "sat") return BuiltinFunction::Saturation;
    if (name == "mm") return BuiltinFunction::MichaelisMenten;
    if (name == "hill") return BuiltinFunction::Hill;
    if (name == "functionproduct") return BuiltinFunction::FunctionProduct;
    if (name == "hybrid") return BuiltinFunction::Hybrid;
    if (name == "tfun") return BuiltinFunction::TableFunction;
    if (name == "distrib_bernoulli") return BuiltinFunction::DistribBernoulli;
    if (name == "distrib_binomial") return BuiltinFunction::DistribBinomial;
    if (name == "distrib_cauchy") return BuiltinFunction::DistribCauchy;
    if (name == "distrib_chisquare") return BuiltinFunction::DistribChisquare;
    if (name == "distrib_exponential") return BuiltinFunction::DistribExponential;
    if (name == "distrib_gamma") return BuiltinFunction::DistribGamma;
    if (name == "distrib_laplace") return BuiltinFunction::DistribLaplace;
    if (name == "distrib_lognormal") return BuiltinFunction::DistribLognormal;
    if (name == "distrib_normal") return BuiltinFunction::DistribNormal;
    if (name == "distrib_poisson") return BuiltinFunction::DistribPoisson;
    if (name == "distrib_rayleigh") return BuiltinFunction::DistribRayleigh;
    if (name == "distrib_uniform") return BuiltinFunction::DistribUniform;
    return BuiltinFunction::Unknown;
}

bool isBuiltinFunction(const std::string& rawName) {
    return builtinFunction(rawName) != BuiltinFunction::Unknown;
}

UnaryOp unaryOperator(const std::string& op) {
    if (op == "+") return UnaryOp::Plus;
    if (op == "-") return UnaryOp::Negate;
    if (op == "!" || lower(op) == "not") return UnaryOp::LogicalNot;
    return UnaryOp::Unknown;
}

BinaryOp binaryOperator(const std::string& op) {
    if (op == "+") return BinaryOp::Add;
    if (op == "-") return BinaryOp::Subtract;
    if (op == "*") return BinaryOp::Multiply;
    if (op == "/") return BinaryOp::Divide;
    if (op == "^" || op == "**") return BinaryOp::Power;
    if (op == "<") return BinaryOp::Less;
    if (op == "<=") return BinaryOp::LessEqual;
    if (op == ">") return BinaryOp::Greater;
    if (op == ">=") return BinaryOp::GreaterEqual;
    if (op == "==" || op == "=") return BinaryOp::Equal;
    if (op == "!=") return BinaryOp::NotEqual;
    if (op == "&&" || lower(op) == "and") return BinaryOp::LogicalAnd;
    if (op == "||" || lower(op) == "or") return BinaryOp::LogicalOr;
    return BinaryOp::Unknown;
}

void addReference(std::vector<SymbolRef>& references, SymbolRef reference) {
    if (std::find_if(references.begin(), references.end(), [&](const auto& existing) {
            return existing.kind == reference.kind && existing.index == reference.index;
        }) == references.end()) {
        references.push_back(reference);
    }
}

void unresolved(std::vector<Diagnostic>& diagnostics, const std::string& name) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Expressions;
    diagnostic.entity = name;
    diagnostic.message = "unresolved expression symbol: " + name;
    diagnostics.push_back(std::move(diagnostic));
}

ResolvedExpression resolveExpression(const ast::Expression& expression,
                                     const SymbolTable& symbols,
                                     std::vector<SymbolRef>& references,
                                     std::vector<Diagnostic>& diagnostics,
                                     const std::unordered_set<std::string>& localNames) {
    ResolvedExpression resolved;
    resolved.source = expression.toString();
    switch (expression.kind()) {
    case ast::ExpressionKind::Number:
        resolved.kind = ResolvedExpressionKind::Number;
        resolved.numberValue = expression.numberValue();
        return resolved;
    case ast::ExpressionKind::Identifier: {
        resolved.operation = expression.name();
        if (localNames.count(expression.name()) != 0) {
            resolved.kind = ResolvedExpressionKind::LocalRef;
            resolved.localName = expression.name();
            return resolved;
        }
        if (expression.name().rfind("__substrate_", 0) == 0 ||
            (expression.name().rfind("__tfun_", 0) == 0 && expression.name().size() > 9 &&
             expression.name().substr(expression.name().size() - 2) == "__")) {
            resolved.kind = ResolvedExpressionKind::LocalRef;
            resolved.localName = expression.name();
            return resolved;
        }
        if (expression.name() == "time" || expression.name() == "t") {
            resolved.kind = ResolvedExpressionKind::TimeRef;
            resolved.operation = expression.name();
            resolved.builtin = BuiltinFunction::Time;
            return resolved;
        }
        if (expression.name() == "_PI") {
            resolved.kind = ResolvedExpressionKind::Number;
            resolved.numberValue = 3.141592653589793238462643383279502884;
            return resolved;
        }
        if (expression.name() == "_e") {
            resolved.kind = ResolvedExpressionKind::Number;
            resolved.numberValue = 2.718281828459045235360287471352662498;
            return resolved;
        }
        if (expression.name().size() == 10 &&
            expression.name().compare(0, 9, "reactant_") == 0 &&
            expression.name().back() >= '1' && expression.name().back() <= '9') {
            resolved.kind = ResolvedExpressionKind::ReactantCountRef;
            resolved.reactantIndex = static_cast<std::size_t>(expression.name().back() - '1');
            resolved.localName = expression.name();
            return resolved;
        }
        if (const auto parameter = symbols.resolveParameter(expression.name())) {
            resolved.kind = ResolvedExpressionKind::ParameterRef;
            resolved.symbol = SymbolRef{SymbolKind::Parameter, parameter->value()};
        } else if (const auto observable = symbols.resolveObservable(expression.name())) {
            resolved.kind = ResolvedExpressionKind::ObservableRef;
            resolved.symbol = SymbolRef{SymbolKind::Observable, observable->value()};
        } else if (const auto function = symbols.resolveFunction(expression.name())) {
            resolved.kind = ResolvedExpressionKind::FunctionRef;
            resolved.symbol = SymbolRef{SymbolKind::Function, function->value()};
        } else if (expression.name() == "_Na") {
            resolved.kind = ResolvedExpressionKind::Number;
            resolved.numberValue = 6.02214076e23;
            // Preserve the source token for the NFsim text boundary when the
            // model does not declare _Na as an overriding parameter.
            resolved.operation = expression.name();
            return resolved;
        } else {
            resolved.kind = ResolvedExpressionKind::Unresolved;
            unresolved(diagnostics, expression.name());
        }
        if (resolved.symbol.has_value()) addReference(references, *resolved.symbol);
        return resolved;
    }
    case ast::ExpressionKind::Function: {
        // NFsim exposes reactant_N() as a mapping-local count placeholder.
        // It is commonly written with call syntax in legacy function/rate
        // sections even though it is not a user-defined model function.
        if (expression.args().empty() && isReactantCountName(expression.name())) {
            resolved.kind = ResolvedExpressionKind::ReactantCountRef;
            resolved.reactantIndex =
                static_cast<std::size_t>(expression.name().back() - '1');
            resolved.localName = expression.name();
            return resolved;
        }
        const auto builtin = builtinFunction(expression.name());
        resolved.kind = builtin != BuiltinFunction::Unknown
                            ? ResolvedExpressionKind::BuiltinCall
                            : ResolvedExpressionKind::FunctionRef;
        resolved.operation = expression.name();
        if (builtin != BuiltinFunction::Unknown) {
            resolved.builtin = builtin;
        } else {
            if (const auto function = symbols.resolveFunction(expression.name())) {
                addReference(references, SymbolRef{SymbolKind::Function, function->value()});
                resolved.symbol = SymbolRef{SymbolKind::Function, function->value()};
            } else {
                unresolved(diagnostics, expression.name());
                resolved.kind = ResolvedExpressionKind::Unresolved;
            }
        }
        for (const auto& argument : expression.args()) {
            resolved.arguments.push_back(
                resolveExpression(argument, symbols, references, diagnostics, localNames));
        }
        return resolved;
    }
    case ast::ExpressionKind::ObservableRef: {
        if (expression.args().empty() && isReactantCountName(expression.name())) {
            resolved.kind = ResolvedExpressionKind::ReactantCountRef;
            resolved.reactantIndex =
                static_cast<std::size_t>(expression.name().back() - '1');
            resolved.localName = expression.name();
            return resolved;
        }
        resolved.operation = expression.name();
        if (const auto observable = symbols.resolveObservable(expression.name())) {
            resolved.kind = ResolvedExpressionKind::ObservableRef;
            addReference(references, SymbolRef{SymbolKind::Observable, observable->value()});
            resolved.symbol = SymbolRef{SymbolKind::Observable, observable->value()};
        } else if (const auto function = symbols.resolveFunction(expression.name())) {
            // The parser uses ObservableRef for the legacy zero-argument and
            // function-shaped spelling of named model functions. Resolve the
            // declaration kind from the symbol table instead of treating the
            // AST node kind as semantic truth.
            resolved.kind = ResolvedExpressionKind::FunctionRef;
            addReference(references, SymbolRef{SymbolKind::Function, function->value()});
            resolved.symbol = SymbolRef{SymbolKind::Function, function->value()};
        } else {
            unresolved(diagnostics, expression.name());
            resolved.kind = ResolvedExpressionKind::Unresolved;
        }
        for (const auto& argument : expression.args()) {
            resolved.arguments.push_back(
                resolveExpression(argument, symbols, references, diagnostics, localNames));
        }
        return resolved;
    }
    case ast::ExpressionKind::Unary:
    case ast::ExpressionKind::Binary: {
        resolved.kind = expression.kind() == ast::ExpressionKind::Unary
                            ? ResolvedExpressionKind::Unary
                            : ResolvedExpressionKind::Binary;
        resolved.operation = expression.name();
        if (expression.kind() == ast::ExpressionKind::Unary) {
            resolved.unaryOp = unaryOperator(expression.name());
        } else {
            resolved.binaryOp = binaryOperator(expression.name());
        }
        for (const auto& argument : expression.args()) {
            resolved.arguments.push_back(
                resolveExpression(argument, symbols, references, diagnostics, localNames));
        }
        return resolved;
    }
    case ast::ExpressionKind::TableFunction:
        resolved.kind = ResolvedExpressionKind::TableFunction;
        resolved.operation = expression.tableMethod();
        resolved.builtin = BuiltinFunction::TableFunction;
        resolved.tableX = expression.tableXValues();
        resolved.tableY = expression.tableYValues();
        resolved.tableFile = expression.tableFilePath();
        resolved.tableMethod = expression.tableMethod();
        for (const auto& argument : expression.args()) {
            resolved.arguments.push_back(
                resolveExpression(argument, symbols, references, diagnostics, localNames));
        }
        return resolved;
    }
    return resolved;
}

void collectDependencies(const ResolvedExpression& expression,
                         RateDependencySummary& dependencies) {
    switch (expression.kind) {
    case ResolvedExpressionKind::ParameterRef:
        dependencies.parameter = true;
        break;
    case ResolvedExpressionKind::ObservableRef:
        dependencies.observable = true;
        break;
    case ResolvedExpressionKind::FunctionRef:
        dependencies.function = true;
        break;
    case ResolvedExpressionKind::LocalRef:
        dependencies.local = true;
        if (expression.localName.rfind("__substrate_", 0) == 0) {
            dependencies.reactantCount = true;
        } else if (expression.localName.rfind("__tfun_", 0) == 0) {
            dependencies.tableFunction = true;
            if (expression.localName.find("_AT_") == std::string::npos) {
                dependencies.time = true;
            }
        }
        break;
    case ResolvedExpressionKind::ReactantCountRef:
        dependencies.reactantCount = true;
        break;
    case ResolvedExpressionKind::TimeRef:
        dependencies.time = true;
        break;
    case ResolvedExpressionKind::TableFunction:
        dependencies.tableFunction = true;
        break;
    case ResolvedExpressionKind::BuiltinCall:
        if (expression.builtin == BuiltinFunction::Time) {
            dependencies.time = true;
        }
        if (expression.builtin == BuiltinFunction::Delay) {
            dependencies.time = true;
            dependencies.observable = true;
            dependencies.delay = true;
        }
        if (expression.builtin == BuiltinFunction::TableFunction) {
            dependencies.tableFunction = true;
        }
        break;
    case ResolvedExpressionKind::Unresolved:
        dependencies.unresolved = true;
        break;
    case ResolvedExpressionKind::Number:
    case ResolvedExpressionKind::Unary:
    case ResolvedExpressionKind::Binary:
        break;
    }

    for (const auto& argument : expression.arguments) {
        collectDependencies(argument, dependencies);
    }
}

} // namespace


bool ResolvedExpression::fullyResolved() const noexcept {
    if (kind == ResolvedExpressionKind::Unresolved) return false;
    if (kind == ResolvedExpressionKind::Unary &&
        (!unaryOp.has_value() || *unaryOp == UnaryOp::Unknown)) return false;
    if (kind == ResolvedExpressionKind::Binary &&
        (!binaryOp.has_value() || *binaryOp == BinaryOp::Unknown)) return false;
    if (kind == ResolvedExpressionKind::BuiltinCall &&
        (!builtin.has_value() || *builtin == BuiltinFunction::Unknown)) return false;
    return std::all_of(arguments.begin(), arguments.end(),
                       [](const ResolvedExpression& argument) {
                           return argument.fullyResolved();
                       });
}

CompiledRateLaw CompiledRateLaw::compile(const ast::Expression& expression) {
    const auto simplified = ast::partialEvaluate(expression);
    CompiledRateLaw compiled;
    compiled.sourceExpression = expression.toString();
    if (simplified.kind() == ast::ExpressionKind::Function ||
        simplified.kind() == ast::ExpressionKind::ObservableRef) {
        compiled.kind = classifyFunction(simplified.name());
        compiled.arguments = simplified.args();
    }
    // This overload has no symbol table, so it cannot make a dependency
    // summary safe for backend classification.
    compiled.dependencies_.unresolved = true;
    return compiled;
}

CompiledRateLaw CompiledRateLaw::compile(const ast::Expression& expression,
                                         const SymbolTable& symbols) {
    return compile(expression, symbols, {});
}

CompiledRateLaw CompiledRateLaw::compile(
    const ast::Expression& expression,
    const SymbolTable& symbols,
    const std::vector<std::string>& localNames) {
    return compile(expression, symbols, localNames,
                   std::vector<ast::Function>{});
}

CompiledRateLaw CompiledRateLaw::compile(
    const ast::Expression& expression,
    const SymbolTable& symbols,
    const std::vector<std::string>& localNames,
    const std::vector<ast::Function>& functions) {
    const auto simplified = ast::partialEvaluate(expression, functions);
    auto compiled = compile(simplified);
    compiled.sourceExpression = expression.toString();
    compiled.dependencies_ = {};
    const std::unordered_set<std::string> lexicalNames(
        localNames.begin(), localNames.end());
    compiled.resolved_ = resolveExpression(
        simplified, symbols, compiled.references_, compiled.diagnostics_, lexicalNames);
    collectDependencies(compiled.resolved_, compiled.dependencies_);
    compiled.dependencies_.unresolved =
        compiled.dependencies_.unresolved || !compiled.resolved_.fullyResolved();
    return compiled;
}

bool isBuiltinFunctionName(std::string_view name) {
    return builtinFunction(std::string(name)) != BuiltinFunction::Unknown;
}

double ResolvedExpression::evaluate(const RateEvaluationContext& context) const {
    switch (kind) {
    case ResolvedExpressionKind::Number:
        return numberValue;

    case ResolvedExpressionKind::TimeRef:
        return context.time;

    case ResolvedExpressionKind::ParameterRef: {
        const std::string& name = !operation.empty() ? operation : source;
        if (context.resolveParameter && symbol.has_value() &&
            symbol->kind == SymbolKind::Parameter) {
            return context.resolveParameter(symbol->index, name);
        }
        if (context.resolveIdentifier) {
            return context.resolveIdentifier(name);
        }
        return numberValue;
    }

    case ResolvedExpressionKind::ObservableRef: {
        const std::string& name = !operation.empty() ? operation : source;
        if (context.resolveObservable && symbol.has_value() &&
            symbol->kind == SymbolKind::Observable) {
            return context.resolveObservable(symbol->index, name);
        }
        if (context.resolveIdentifier) {
            return context.resolveIdentifier(name);
        }
        return 0.0;
    }

    case ResolvedExpressionKind::ReactantCountRef: {
        if (context.resolveReactantCount) {
            return context.resolveReactantCount(reactantIndex);
        }
        if (context.resolveIdentifier) {
            return context.resolveIdentifier("reactant_" + std::to_string(reactantIndex + 1));
        }
        return 0.0;
    }

    case ResolvedExpressionKind::LocalRef: {
        if (context.resolveLocal) {
            return context.resolveLocal(localName);
        }
        if (context.resolveIdentifier) {
            return context.resolveIdentifier(localName);
        }
        return 0.0;
    }

    case ResolvedExpressionKind::Unary: {
        if (arguments.empty()) return 0.0;
        const double val = arguments[0].evaluate(context);
        if (!unaryOp.has_value()) return val;
        switch (*unaryOp) {
        case UnaryOp::Plus: return val;
        case UnaryOp::Negate: return -val;
        case UnaryOp::LogicalNot: return (val == 0.0) ? 1.0 : 0.0;
        default: return val;
        }
    }

    case ResolvedExpressionKind::Binary: {
        if (arguments.size() < 2) return 0.0;
        const double lhs = arguments[0].evaluate(context);
        const double rhs = arguments[1].evaluate(context);
        if (!binaryOp.has_value()) return 0.0;
        switch (*binaryOp) {
        case BinaryOp::Add: return lhs + rhs;
        case BinaryOp::Subtract: return lhs - rhs;
        case BinaryOp::Multiply: return lhs * rhs;
        case BinaryOp::Divide: return (rhs != 0.0) ? (lhs / rhs) : 0.0;
        case BinaryOp::Power: return std::pow(lhs, rhs);
        case BinaryOp::Less: return (lhs < rhs) ? 1.0 : 0.0;
        case BinaryOp::LessEqual: return (lhs <= rhs) ? 1.0 : 0.0;
        case BinaryOp::Greater: return (lhs > rhs) ? 1.0 : 0.0;
        case BinaryOp::GreaterEqual: return (lhs >= rhs) ? 1.0 : 0.0;
        case BinaryOp::Equal: return (lhs == rhs) ? 1.0 : 0.0;
        case BinaryOp::NotEqual: return (lhs != rhs) ? 1.0 : 0.0;
        case BinaryOp::LogicalAnd: return (lhs != 0.0 && rhs != 0.0) ? 1.0 : 0.0;
        case BinaryOp::LogicalOr: return (lhs != 0.0 || rhs != 0.0) ? 1.0 : 0.0;
        default: return 0.0;
        }
    }

    case ResolvedExpressionKind::BuiltinCall: {
        if (!builtin.has_value()) return 0.0;
        const auto evalArg = [&](std::size_t idx) -> double {
            return (idx < arguments.size()) ? arguments[idx].evaluate(context) : 0.0;
        };

        switch (*builtin) {
        case BuiltinFunction::Time:
            return context.time;
        case BuiltinFunction::Abs:
            return std::abs(evalArg(0));
        case BuiltinFunction::Acos:
            return std::acos(evalArg(0));
        case BuiltinFunction::Acosh:
            return std::acosh(evalArg(0));
        case BuiltinFunction::Asin:
            return std::asin(evalArg(0));
        case BuiltinFunction::Asinh:
            return std::asinh(evalArg(0));
        case BuiltinFunction::Atan:
            return std::atan(evalArg(0));
        case BuiltinFunction::Atanh:
            return std::atanh(evalArg(0));
        case BuiltinFunction::Ceil:
            return std::ceil(evalArg(0));
        case BuiltinFunction::Cos:
            return std::cos(evalArg(0));
        case BuiltinFunction::Cosh:
            return std::cosh(evalArg(0));
        case BuiltinFunction::E:
            return 2.718281828459045235360287471352662498;
        case BuiltinFunction::Exp:
            return std::exp(evalArg(0));
        case BuiltinFunction::Floor:
            return std::floor(evalArg(0));
        case BuiltinFunction::Factorial: {
            const double val = evalArg(0);
            if (!std::isfinite(val) || val < 0.0) return 0.0;
            if (val > 170.0) return std::numeric_limits<double>::infinity();
            double res = 1.0;
            for (double i = 2.0; i <= val; i += 1.0) res *= i;
            return res;
        }
        case BuiltinFunction::If:
            return evalArg(0) != 0.0 ? evalArg(1) : evalArg(2);
        case BuiltinFunction::Ln:
            return std::log(evalArg(0));
        case BuiltinFunction::Log10:
            return std::log10(evalArg(0));
        case BuiltinFunction::Log2:
            return std::log2(evalArg(0));
        case BuiltinFunction::Max: {
            if (arguments.empty()) return 0.0;
            double m = evalArg(0);
            for (std::size_t i = 1; i < arguments.size(); ++i) m = std::max(m, evalArg(i));
            return m;
        }
        case BuiltinFunction::Min: {
            if (arguments.empty()) return 0.0;
            double m = evalArg(0);
            for (std::size_t i = 1; i < arguments.size(); ++i) m = std::min(m, evalArg(i));
            return m;
        }
        case BuiltinFunction::MRatio: {
            const double a = evalArg(0);
            const double b = evalArg(1);
            const double z = evalArg(2);
            auto hypergeom1F1 = [](double aa, double bb, double zz) -> double {
                double sum = 1.0, term = 1.0;
                for (int k = 1; k <= 1000; ++k) {
                    term *= (aa + k - 1) * zz / ((bb + k - 1) * k);
                    sum += term;
                    if (std::abs(term) < 1e-15 * std::abs(sum)) break;
                }
                return sum;
            };
            const double M_ab = hypergeom1F1(a, b, z);
            const double M_a1b1 = hypergeom1F1(a + 1, b + 1, z);
            return (std::abs(M_ab) < 1e-300) ? 0.0 : M_a1b1 / M_ab;
        }
        case BuiltinFunction::Pi:
            return 3.141592653589793238462643383279502884;
        case BuiltinFunction::Rint:
            return std::floor(evalArg(0) + 0.5);
        case BuiltinFunction::Sin:
            return std::sin(evalArg(0));
        case BuiltinFunction::Sinh:
            return std::sinh(evalArg(0));
        case BuiltinFunction::Sqrt:
            return std::sqrt(evalArg(0));
        case BuiltinFunction::Sum: {
            double s = 0.0;
            for (std::size_t i = 0; i < arguments.size(); ++i) s += evalArg(i);
            return s;
        }
        case BuiltinFunction::Avg: {
            if (arguments.empty()) return 0.0;
            double s = 0.0;
            for (std::size_t i = 0; i < arguments.size(); ++i) s += evalArg(i);
            return s / static_cast<double>(arguments.size());
        }
        case BuiltinFunction::Tan:
            return std::tan(evalArg(0));
        case BuiltinFunction::Tanh:
            return std::tanh(evalArg(0));
        case BuiltinFunction::Delay:
            if (context.resolveDelay && arguments.size() >= 2) {
                const double tau = evalArg(1);
                return context.resolveDelay(arguments[0], context.time - tau);
            }
            return evalArg(0);
        case BuiltinFunction::Saturation: {
            if (arguments.size() >= 3) {
                const double k0 = evalArg(0);
                const double K = evalArg(1);
                const double S = evalArg(2);
                return (K + S != 0.0) ? (k0 * S / (K + S)) : 0.0;
            }
            if (arguments.size() == 2) {
                return evalArg(0);
            }
            return 0.0;
        }
        case BuiltinFunction::MichaelisMenten: {
            if (arguments.size() == 4) {
                const double kcat = evalArg(0);
                const double Km = evalArg(1);
                const double St = evalArg(2);
                const double Et = evalArg(3);
                const double b = St - Km - Et;
                const double q = std::sqrt(b * b + 4.0 * St * Km);
                const double S = (b >= 0.0) ? 0.5 * (b + q)
                                            : 2.0 * St * Km / (q - b);
                return (Km + S != 0.0) ? (kcat * Et * S / (Km + S)) : 0.0;
            }
            if (arguments.size() >= 3) {
                const double Vmax = evalArg(0);
                const double Km = evalArg(1);
                const double S = evalArg(2);
                return (Km + S != 0.0) ? (Vmax * S / (Km + S)) : 0.0;
            }
            return 0.0;
        }
        case BuiltinFunction::Hill: {
            if (arguments.size() >= 4) {
                const double Vmax = evalArg(0);
                const double Kh = evalArg(1);
                const double n = evalArg(2);
                const double S = evalArg(3);
                const double Sn = std::pow(S, n);
                const double den = std::pow(Kh, n) + Sn;
                return (den != 0.0) ? (Vmax * Sn / den) : 0.0;
            }
            return 0.0;
        }
        case BuiltinFunction::Arrhenius: {
            if (arguments.size() >= 2) {
                const double A = evalArg(0);
                const double Ea = evalArg(1);
                constexpr double kBT = 1.3806488e-23 * 298.15;
                return A * std::exp(-Ea / kBT);
            }
            return 0.0;
        }
        case BuiltinFunction::FunctionProduct: {
            double prod = 1.0;
            for (std::size_t i = 0; i < arguments.size(); ++i) prod *= evalArg(i);
            return prod;
        }
        case BuiltinFunction::TableFunction: {
            const double counter = evalArg(0);
            if (!tableX.empty() && tableX.size() == tableY.size()) {
                if (tableX.size() == 1) return tableY.front();
                if (counter <= tableX.front()) return tableY.front();
                if (counter >= tableX.back()) return tableY.back();
                const auto upper = std::upper_bound(tableX.begin(), tableX.end(), counter);
                const std::size_t right = static_cast<std::size_t>(upper - tableX.begin());
                const std::size_t left = right - 1;
                if (tableMethod == "step") return tableY[left];
                const double fraction = (counter - tableX[left]) / (tableX[right] - tableX[left]);
                return tableY[left] + fraction * (tableY[right] - tableY[left]);
            }
            if (context.resolveTable && !tableFile.empty()) {
                return context.resolveTable(tableFile, counter);
            }
            return 0.0;
        }
        default:
            return 0.0;
        }
    }

    case ResolvedExpressionKind::FunctionRef: {
        if (context.resolveFunction) {
            std::vector<double> args;
            args.reserve(arguments.size());
            for (const auto& arg : arguments) {
                args.push_back(arg.evaluate(context));
            }
            return context.resolveFunction(operation, args);
        }
        if (arguments.empty() && context.resolveIdentifier) {
            return context.resolveIdentifier(operation);
        }
        return 0.0;
    }

    case ResolvedExpressionKind::TableFunction: {
        const double counter =
            (!arguments.empty()) ? arguments[0].evaluate(context) : context.time;
        if (!tableX.empty() && tableX.size() == tableY.size()) {
            if (tableX.size() == 1) return tableY.front();
            if (counter <= tableX.front()) return tableY.front();
            if (counter >= tableX.back()) return tableY.back();
            const auto upper = std::upper_bound(tableX.begin(), tableX.end(), counter);
            const std::size_t right = static_cast<std::size_t>(upper - tableX.begin());
            const std::size_t left = right - 1;
            if (tableMethod == "step") return tableY[left];
            const double fraction = (counter - tableX[left]) / (tableX[right] - tableX[left]);
            return tableY[left] + fraction * (tableY[right] - tableY[left]);
        }
        if (context.resolveTable && !tableFile.empty()) {
            return context.resolveTable(tableFile, counter);
        }
        if (context.resolveIdentifier && !tableFile.empty()) {
            std::ostringstream val;
            val << std::scientific << std::setprecision(17) << counter;
            return context.resolveIdentifier("__tfun_" + tableFile + "_AT_" + val.str() + "__");
        }
        return 0.0;
    }

    case ResolvedExpressionKind::Unresolved:
        if (context.resolveIdentifier && !source.empty()) {
            return context.resolveIdentifier(source);
        }
        return 0.0;
    }
    return 0.0;
}

double CompiledRateLaw::evaluate(const RateEvaluationContext& context) const {
    return resolved_.evaluate(context);
}

double CompiledRateLaw::evaluate(
    const std::function<double(const std::string&)>& resolver,
    double time) const {
    RateEvaluationContext context;
    context.time = time;
    context.resolveIdentifier = resolver;
    return resolved_.evaluate(context);
}

bool CompiledRateLaw::dependsOnParameter(std::size_t parameterIndex) const noexcept {
    if (!dependencies_.parameter) return false;
    return std::any_of(references_.begin(), references_.end(),
                       [parameterIndex](const SymbolRef& ref) {
                           return ref.kind == SymbolKind::Parameter && ref.index == parameterIndex;
                       });
}

bool CompiledRateLaw::dependsOnParameter(const std::string& name) const noexcept {
    if (!dependencies_.parameter) return false;
    std::function<bool(const ResolvedExpression&)> checkExpr;
    checkExpr = [&](const ResolvedExpression& expr) -> bool {
        if (expr.kind == ResolvedExpressionKind::ParameterRef &&
            (expr.operation == name || expr.source == name)) {
            return true;
        }
        for (const auto& arg : expr.arguments) {
            if (checkExpr(arg)) return true;
        }
        return false;
    };
    return checkExpr(resolved_);
}

bool CompiledRateLaw::dependsOnObservable(std::size_t observableIndex) const noexcept {
    if (!dependencies_.observable) return false;
    return std::any_of(references_.begin(), references_.end(),
                       [observableIndex](const SymbolRef& ref) {
                           return ref.kind == SymbolKind::Observable && ref.index == observableIndex;
                       });
}

bool CompiledRateLaw::dependsOnObservable(const std::string& name) const noexcept {
    if (!dependencies_.observable) return false;
    std::function<bool(const ResolvedExpression&)> checkExpr;
    checkExpr = [&](const ResolvedExpression& expr) -> bool {
        if (expr.kind == ResolvedExpressionKind::ObservableRef &&
            (expr.operation == name || expr.source == name)) {
            return true;
        }
        for (const auto& arg : expr.arguments) {
            if (checkExpr(arg)) return true;
        }
        return false;
    };
    return checkExpr(resolved_);
}

bool CompiledRateLaw::isInvalidatedBy(
    bool timeChanged,
    const std::vector<std::size_t>& changedParameterIndices,
    const std::vector<std::size_t>& changedObservableIndices) const noexcept {
    if (timeChanged && dependencies_.time) return true;
    for (const auto paramIdx : changedParameterIndices) {
        if (dependsOnParameter(paramIdx)) return true;
    }
    for (const auto obsIdx : changedObservableIndices) {
        if (dependsOnObservable(obsIdx)) return true;
    }
    return false;
}

bool CompiledRateLaw::isInvalidatedBy(
    bool timeChanged,
    const std::vector<std::string>& changedParameterNames,
    const std::vector<std::string>& changedObservableNames) const noexcept {
    if (timeChanged && dependencies_.time) return true;
    for (const auto& paramName : changedParameterNames) {
        if (dependsOnParameter(paramName)) return true;
    }
    for (const auto& obsName : changedObservableNames) {
        if (dependsOnObservable(obsName)) return true;
    }
    return false;
}

double evaluateRateString(
    const std::string& rateStr,
    const std::function<double(const std::string&)>& resolver) {
    std::string s = rateStr;
    const auto first = s.find_first_not_of(" \t");
    if (first != std::string::npos) s.erase(0, first);
    else s.clear();
    if (!s.empty()) {
        const auto last = s.find_last_not_of(" \t");
        s.erase(last + 1);
    }
    if (s.empty()) return 0.0;
    try {
        size_t idx = 0;
        double val = std::stod(s, &idx);
        if (idx == s.size()) return val;
    } catch (...) {}
    if (s.front() == '(' && s.back() == ')') {
        int depth = 0;
        bool outermost = true;
        for (size_t i = 0; i < s.size() - 1; ++i) {
            if (s[i] == '(') depth++;
            else if (s[i] == ')') depth--;
            if (depth == 0) { outermost = false; break; }
        }
        if (outermost) return evaluateRateString(s.substr(1, s.size() - 2), resolver);
    }
    int depth = 0;
    int lastAddSub = -1;
    int lastMulDiv = -1;
    for (size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '(') depth++;
        else if (s[i] == ')') depth--;
        else if (depth == 0) {
            if (s[i] == '+' || (s[i] == '-' && i > 0 && s[i - 1] != '*' &&
                                s[i - 1] != '/' && s[i - 1] != '+' && s[i - 1] != '-')) {
                lastAddSub = static_cast<int>(i);
            } else if (s[i] == '*' || s[i] == '/') {
                lastMulDiv = static_cast<int>(i);
            }
        }
    }
    if (lastAddSub >= 0) {
        double l = evaluateRateString(s.substr(0, lastAddSub), resolver);
        double r = evaluateRateString(s.substr(lastAddSub + 1), resolver);
        return (s[lastAddSub] == '+') ? (l + r) : (l - r);
    }
    if (lastMulDiv >= 0) {
        double l = evaluateRateString(s.substr(0, lastMulDiv), resolver);
        double r = evaluateRateString(s.substr(lastMulDiv + 1), resolver);
        return (s[lastMulDiv] == '*') ? (l * r) : ((r != 0.0) ? (l / r) : 0.0);
    }
    if (s.front() == '-') return -evaluateRateString(s.substr(1), resolver);
    if (s.size() > 4 && s.substr(0, 4) == "exp(" && s.back() == ')') {
        return std::exp(evaluateRateString(s.substr(4, s.size() - 5), resolver));
    }
    return resolver ? resolver(s) : 0.0;
}

} // namespace bng::compile
