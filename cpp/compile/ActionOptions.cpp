#include "compile/ActionOptions.hpp"

#include <cmath>
#include <limits>
#include <sstream>
#include <stdexcept>

#include "ast/Parameter.hpp"
#include "parser/BNGAstVisitor.hpp"

namespace bng::compile {

namespace {

bool supportsRuntimeSafeStepArithmetic(const ast::Expression& expression,
                                       ast::Model& model,
                                       std::size_t& powerOperators) {
    using ast::ExpressionKind;
    switch (expression.kind()) {
    case ExpressionKind::Number:
        return std::isfinite(expression.numberValue());
    case ExpressionKind::Identifier:
        return true;
    case ExpressionKind::Unary:
        return (expression.name() == "+" || expression.name() == "-") &&
            expression.args().size() == 1 &&
            supportsRuntimeSafeStepArithmetic(expression.args().front(), model,
                                              powerOperators);
    case ExpressionKind::Binary: {
        const auto& op = expression.name();
        if (op != "+" && op != "-" && op != "*" && op != "/" && op != "**") {
            return false;
        }
        if (expression.args().size() != 2 ||
            !supportsRuntimeSafeStepArithmetic(expression.args()[0], model,
                                              powerOperators) ||
            !supportsRuntimeSafeStepArithmetic(expression.args()[1], model,
                                              powerOperators)) {
            return false;
        }
        if (op == "**") {
            if (++powerOperators > 1) {
                return false;
            }
            try {
                const double base = expression.args()[0].evaluate(
                    [&](const std::string& name) {
                        return model.getParameters().evaluate(name);
                    });
                if (!std::isfinite(base) || base < 0.0) {
                    return false;
                }
            } catch (const std::exception&) {
                return false;
            }
        }
        return true;
    }
    case ExpressionKind::Function:
    case ExpressionKind::ObservableRef:
    case ExpressionKind::TableFunction:
        return false;
    }
    return false;
}

std::size_t checkedSimulationStepCount(double value, const std::string& source) {
    if (!std::isfinite(value) || value < 0.0 || std::floor(value) != value) {
        throw std::runtime_error(
            "n_steps must be a non-negative integer (value '" + source + "')");
    }
    const double firstUnsupportedValue =
        std::ldexp(1.0, std::numeric_limits<std::size_t>::digits);
    if (value >= firstUnsupportedValue) {
        throw std::runtime_error(
            "n_steps exceeds the supported integer step-count range: '" + source + "'");
    }
    return static_cast<std::size_t>(value);
}

} // namespace

double parseScalarValue(const std::string& text, ast::Model& model) {
    const std::string raw = stripQuotes(trim(text));

    // Keep identifiers intact while parsing expressions. The lexer recognizes
    // Fortran D exponents as numeric tokens, and parseNumberLiteral normalizes
    // only those tokens before passing them to std::stod.
    if (model.getParameters().contains(raw)) {
        return model.getParameters().evaluate(raw);
    }

    std::string value = raw;

    std::size_t consumed = 0;
    try {
        const double parsed = std::stod(value, &consumed);
        if (consumed == value.size()) {
            return parsed;
        }
    } catch (const std::exception&) {
        // Try the expression forms below.
    }

    // Try evaluating as expression with parameter resolution
    try {
        // Simple recursive evaluator for expressions like "2e-9*NA*V"
        double result = 1.0;
        std::string token;
        std::istringstream stream(value);
        bool allResolved = true;
        while (std::getline(stream, token, '*')) {
            std::string t = trim(token);
            if (t.empty()) continue;
            std::size_t pos = 0;
            try {
                double val = std::stod(t, &pos);
                if (pos == t.size()) { result *= val; continue; }
            } catch (...) {}
            if (model.getParameters().contains(t)) {
                result *= model.getParameters().evaluate(t);
            } else {
                allResolved = false;
                break;
            }
        }
        if (allResolved) return result;
    } catch (...) {}

    // Fallback: parse as a full expression (handles nested parentheses, division, etc.)
    try {
        auto expr = bng::parser::parseExpression(value);
        return expr.evaluate([&](const std::string& name) {
            return model.getParameters().evaluate(name);
        });
    } catch (...) {}

    throw std::runtime_error("Unsupported scalar action value: '" + text + "'");
}

bool parseBoolean(const std::string& text, bool defaultValue) {
    const auto value = lowercase(stripQuotes(trim(text)));
    if (value.empty()) {
        return defaultValue;
    }
    if (value == "1" || value == "true" || value == "yes" || value == "on") {
        return true;
    }
    if (value == "0" || value == "false" || value == "no" || value == "off") {
        return false;
    }
    throw std::runtime_error("Expected a boolean value, got '" + text + "'");
}

std::size_t parseNonNegativeCount(const std::string& text,
                                  ast::Model& model,
                                  const std::string& name) {
    const double value = parseScalarValue(text, model);
    if (!std::isfinite(value) || value < 0.0 || std::floor(value) != value ||
        value > static_cast<double>(std::numeric_limits<std::size_t>::max())) {
        throw std::runtime_error(name + " must be a non-negative integer");
    }
    return static_cast<std::size_t>(value);
}

std::size_t parseSimulationStepCount(const std::string& text, ast::Model& model) {
    const auto expressionSource = stripQuotes(trim(text));
    if (expressionSource.find('^') != std::string::npos) {
        throw std::runtime_error(
            "invalid n_steps '" + text +
            "': Safe-Perl '^' is bitwise XOR; use '**' for exponentiation");
    }

    if (expressionSource.find("**") == std::string::npos) {
        return checkedSimulationStepCount(
            parseScalarValue(expressionSource, model), text);
    }

    ast::Expression expression;
    try {
        expression = parser::parseExpression(expressionSource);
    } catch (const std::exception& error) {
        throw std::runtime_error(
            "invalid n_steps '" + text +
            "': could not be parsed as a Safe-Perl numeric expression: " + error.what());
    }

    std::size_t powerOperators = 0;
    if (!supportsRuntimeSafeStepArithmetic(expression, model, powerOperators)) {
        throw std::runtime_error(
            "invalid n_steps '" + text +
            "': cannot be translated without changing Safe-Perl arithmetic semantics");
    }
    double value = 0.0;
    try {
        value = expression.evaluate([&](const std::string& name) {
            return model.getParameters().evaluate(name);
        });
    } catch (const std::exception& error) {
        throw std::runtime_error(
            "invalid n_steps '" + text + "': could not be evaluated: " + error.what());
    }
    return checkedSimulationStepCount(value, text);
}

} // namespace bng::compile
