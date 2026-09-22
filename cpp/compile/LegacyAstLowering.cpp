#include "LegacyAstLowering.hpp"

#include <stdexcept>
#include <string>
#include <utility>

#include "ast/Expression.hpp"
#include "ast/SpeciesGraph.hpp"

namespace bng::compile {
namespace {

std::string unaryToken(UnaryOp op) {
    switch (op) {
    case UnaryOp::Plus: return "+";
    case UnaryOp::Negate: return "-";
    case UnaryOp::LogicalNot: return "!";
    case UnaryOp::Unknown: break;
    }
    throw std::invalid_argument("cannot lower unresolved unary operator");
}

std::string binaryToken(BinaryOp op) {
    switch (op) {
    case BinaryOp::Add: return "+";
    case BinaryOp::Subtract: return "-";
    case BinaryOp::Multiply: return "*";
    case BinaryOp::Divide: return "/";
    case BinaryOp::Power: return "^";
    case BinaryOp::Less: return "<";
    case BinaryOp::LessEqual: return "<=";
    case BinaryOp::Greater: return ">";
    case BinaryOp::GreaterEqual: return ">=";
    case BinaryOp::Equal: return "==";
    case BinaryOp::NotEqual: return "!=";
    case BinaryOp::LogicalAnd: return "&&";
    case BinaryOp::LogicalOr: return "||";
    case BinaryOp::Unknown: break;
    }
    throw std::invalid_argument("cannot lower unresolved binary operator");
}

std::string builtinName(BuiltinFunction function) {
    switch (function) {
    case BuiltinFunction::Abs: return "abs";
    case BuiltinFunction::Acos: return "acos";
    case BuiltinFunction::Acosh: return "acosh";
    case BuiltinFunction::Asin: return "asin";
    case BuiltinFunction::Asinh: return "asinh";
    case BuiltinFunction::Atan: return "atan";
    case BuiltinFunction::Atanh: return "atanh";
    case BuiltinFunction::Avg: return "avg";
    case BuiltinFunction::Ceil: return "ceil";
    case BuiltinFunction::Cos: return "cos";
    case BuiltinFunction::Cosh: return "cosh";
    case BuiltinFunction::E: return "_e";
    case BuiltinFunction::Exp: return "exp";
    case BuiltinFunction::Factorial: return "factorial";
    case BuiltinFunction::Floor: return "floor";
    case BuiltinFunction::If: return "if";
    case BuiltinFunction::Ln: return "ln";
    case BuiltinFunction::Log10: return "log10";
    case BuiltinFunction::Log2: return "log2";
    case BuiltinFunction::Max: return "max";
    case BuiltinFunction::Min: return "min";
    case BuiltinFunction::MRatio: return "mratio";
    case BuiltinFunction::Pi: return "_PI";
    case BuiltinFunction::Rint: return "rint";
    case BuiltinFunction::Sin: return "sin";
    case BuiltinFunction::Sinh: return "sinh";
    case BuiltinFunction::Sqrt: return "sqrt";
    case BuiltinFunction::Sum: return "sum";
    case BuiltinFunction::Tan: return "tan";
    case BuiltinFunction::Tanh: return "tanh";
    case BuiltinFunction::Time: return "time";
    case BuiltinFunction::Arrhenius: return "Arrhenius";
    case BuiltinFunction::Saturation: return "Sat";
    case BuiltinFunction::MichaelisMenten: return "MM";
    case BuiltinFunction::Hill: return "Hill";
    case BuiltinFunction::FunctionProduct: return "FunctionProduct";
    case BuiltinFunction::Hybrid: return "Hybrid";
    case BuiltinFunction::TableFunction: return "TFUN";
    case BuiltinFunction::Unknown: break;
    }
    throw std::invalid_argument("cannot lower unresolved builtin function");
}

std::vector<ast::Expression> lowerArguments(
    const std::vector<ResolvedExpression>& arguments,
    const CompiledModel& model) {
    std::vector<ast::Expression> result;
    result.reserve(arguments.size());
    for (const auto& argument : arguments)
        result.push_back(lowerResolvedExpressionToAst(argument, model));
    return result;
}

} // namespace

ast::Expression lowerResolvedExpressionToAst(
    const ResolvedExpression& expression,
    const CompiledModel& model) {
    switch (expression.kind) {
    case ResolvedExpressionKind::Number:
        return ast::Expression::number(expression.numberValue);
    case ResolvedExpressionKind::ParameterRef: {
        if (!expression.symbol.has_value())
            throw std::invalid_argument("parameter reference has no symbol");
        const auto* parameter = model.parameter(
            ParameterId::fromDenseIndex(expression.symbol->index));
        if (parameter == nullptr)
            throw std::invalid_argument("parameter reference is out of range");
        return ast::Expression::identifier(parameter->name);
    }
    case ResolvedExpressionKind::ObservableRef: {
        if (!expression.symbol.has_value())
            throw std::invalid_argument("observable reference has no symbol");
        const auto* observable = model.observable(
            ObservableId::fromDenseIndex(expression.symbol->index));
        if (observable == nullptr)
            throw std::invalid_argument("observable reference is out of range");
        return ast::Expression::observableRef(
            observable->name, lowerArguments(expression.arguments, model));
    }
    case ResolvedExpressionKind::FunctionRef: {
        if (!expression.symbol.has_value())
            throw std::invalid_argument("function reference has no symbol");
        const auto* function = model.function(
            FunctionId::fromDenseIndex(expression.symbol->index));
        if (function == nullptr)
            throw std::invalid_argument("function reference is out of range");
        return ast::Expression::function(
            function->name, lowerArguments(expression.arguments, model));
    }
    case ResolvedExpressionKind::LocalRef:
        return ast::Expression::identifier(expression.localName);
    case ResolvedExpressionKind::ReactantCountRef:
        return ast::Expression::identifier(
            "reactant_" + std::to_string(expression.reactantIndex + 1));
    case ResolvedExpressionKind::TimeRef:
        return ast::Expression::identifier("time");
    case ResolvedExpressionKind::Unary:
        if (!expression.unaryOp.has_value() || expression.arguments.size() != 1)
            throw std::invalid_argument("malformed resolved unary expression");
        return ast::Expression::unary(
            unaryToken(*expression.unaryOp),
            lowerResolvedExpressionToAst(expression.arguments.front(), model));
    case ResolvedExpressionKind::Binary:
        if (!expression.binaryOp.has_value() || expression.arguments.size() != 2)
            throw std::invalid_argument("malformed resolved binary expression");
        return ast::Expression::binary(
            binaryToken(*expression.binaryOp),
            lowerResolvedExpressionToAst(expression.arguments[0], model),
            lowerResolvedExpressionToAst(expression.arguments[1], model));
    case ResolvedExpressionKind::BuiltinCall:
        if (!expression.builtin.has_value())
            throw std::invalid_argument("builtin expression has no resolved function");
        return ast::Expression::function(
            builtinName(*expression.builtin), lowerArguments(expression.arguments, model));
    case ResolvedExpressionKind::TableFunction: {
        if (expression.arguments.size() != 1)
            throw std::invalid_argument("table function requires one resolved counter");
        return ast::Expression::tableFunction(
            expression.tableX, expression.tableY, expression.tableFile,
            lowerResolvedExpressionToAst(expression.arguments.front(), model),
            expression.tableMethod);
    }
    case ResolvedExpressionKind::Unresolved:
        break;
    }
    throw std::invalid_argument("cannot lower unresolved expression into legacy AST");
}

ast::SpeciesGraph lowerPatternToSpeciesGraph(
    const Pattern& pattern,
    BNGcoreLoweringContext& context) {
    auto graph = lowerPatternToBNGcore(pattern, context);
    ast::SpeciesGraph result(std::move(graph), pattern.compartment());
    result.setCompartmentIsPrefix(pattern.compartmentIsPrefix());
    return result;
}

std::vector<ast::SpeciesGraph> lowerPatternsToSpeciesGraphs(
    const std::vector<Pattern>& patterns,
    BNGcoreLoweringContext& context) {
    std::vector<ast::SpeciesGraph> result;
    result.reserve(patterns.size());
    for (const auto& pattern : patterns)
        result.push_back(lowerPatternToSpeciesGraph(pattern, context));
    return result;
}

} // namespace bng::compile
