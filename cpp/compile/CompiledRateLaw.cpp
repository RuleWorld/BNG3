#include "CompiledRateLaw.hpp"

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

bool isBuiltinFunction(const std::string& rawName) {
    const auto name = lower(rawName);
    static const std::set<std::string> builtins = {
        "abs", "acos", "acosh", "asin", "asinh", "atan", "atanh", "avg", "ceil",
        "cos", "cosh", "e", "exp", "floor", "functionproduct", "hill", "hybrid",
        "if", "ln", "log10", "log2", "max", "min", "mm", "mratio", "pi",
        "rint", "sat", "sin", "sinh", "sqrt", "sum", "t", "tan", "tanh", "time",
        "arrhenius", "tfun"
    };
    return builtins.find(name) != builtins.end();
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
        } else {
            resolved.kind = ResolvedExpressionKind::Unresolved;
            unresolved(diagnostics, expression.name());
        }
        if (resolved.symbol.has_value()) addReference(references, *resolved.symbol);
        return resolved;
    }
    case ast::ExpressionKind::Function: {
        resolved.kind = isBuiltinFunction(expression.name())
                            ? ResolvedExpressionKind::BuiltinCall
                            : ResolvedExpressionKind::FunctionRef;
        resolved.operation = expression.name();
        if (!isBuiltinFunction(expression.name())) {
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
        for (const auto& argument : expression.args()) {
            resolved.arguments.push_back(
                resolveExpression(argument, symbols, references, diagnostics, localNames));
        }
        return resolved;
    }
    case ast::ExpressionKind::TableFunction:
        resolved.kind = ResolvedExpressionKind::TableFunction;
        resolved.operation = expression.tableMethod();
        for (const auto& argument : expression.args()) {
            resolved.arguments.push_back(
                resolveExpression(argument, symbols, references, diagnostics, localNames));
        }
        return resolved;
    }
    return resolved;
}

} // namespace

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
