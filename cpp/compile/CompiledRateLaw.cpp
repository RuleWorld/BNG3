#include "CompiledRateLaw.hpp"
#include "ast/Expression.hpp"

#include <algorithm>
#include <cctype>
#include <set>
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
    if (name == "arrhenius") return BuiltinFunction::Arrhenius;
    if (name == "sat") return BuiltinFunction::Saturation;
    if (name == "mm") return BuiltinFunction::MichaelisMenten;
    if (name == "hill") return BuiltinFunction::Hill;
    if (name == "functionproduct") return BuiltinFunction::FunctionProduct;
    if (name == "hybrid") return BuiltinFunction::Hybrid;
    if (name == "tfun") return BuiltinFunction::TableFunction;
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
        if (localNames.count(expression.name()) != 0) {
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
    CompiledRateLaw compiled;
    compiled.sourceExpression = expression.toString();
    if (expression.kind() == ast::ExpressionKind::Function ||
        expression.kind() == ast::ExpressionKind::ObservableRef) {
        compiled.kind = classifyFunction(expression.name());
        compiled.arguments = expression.args();
    }
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
    auto compiled = compile(expression);
    const std::unordered_set<std::string> lexicalNames(
        localNames.begin(), localNames.end());
    compiled.resolved_ = resolveExpression(
        expression, symbols, compiled.references_, compiled.diagnostics_, lexicalNames);
    return compiled;
}

} // namespace bng::compile
