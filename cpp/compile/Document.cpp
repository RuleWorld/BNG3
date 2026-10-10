#include "Document.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>

#include "ast/Model.hpp"
#include "parser/BNGAstVisitor.hpp"

namespace bng::compile {

namespace {

using GenerateNetworkOptions = ProtocolAction::GenerateNetworkOptions;

Diagnostic maxIterationsDiagnostic(const std::string& source,
                                   const std::string& reason) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Expressions;
    diagnostic.entity = "generate_network.max_iter";
    diagnostic.message = "invalid generate_network max_iter '" + source + "': " + reason;
    return diagnostic;
}

Diagnostic maxAggregateDiagnostic(const std::string& source,
                                  const std::string& reason) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Expressions;
    diagnostic.entity = "generate_network.max_agg";
    diagnostic.message = "invalid generate_network max_agg '" + source + "': " + reason;
    return diagnostic;
}

bool containsOnlyNumericActionSyntax(const std::string& source) {
    for (std::size_t index = 0; index < source.size(); ++index) {
        const auto character = static_cast<unsigned char>(source[index]);
        if (std::isspace(character) != 0 ||
            (character >= '0' && character <= '9') ||
            character == '.' ||
            character == '+' || character == '-' || character == '*' ||
            character == '/' || character == '^' || character == '%' ||
            character == '(' || character == ')') {
            continue;
        }
        if (character == 'e' || character == 'E') {
            const bool hasMantissa =
                index > 0 && std::isdigit(static_cast<unsigned char>(source[index - 1])) != 0;
            const bool hasDottedMantissa =
                index > 1 && source[index - 1] == '.' &&
                std::isdigit(static_cast<unsigned char>(source[index - 2])) != 0;
            if (!hasMantissa && !hasDottedMantissa) {
                return false;
            }
            std::size_t exponentStart = index + 1;
            if (exponentStart < source.size() &&
                (source[exponentStart] == '+' || source[exponentStart] == '-')) {
                ++exponentStart;
            }
            if (exponentStart == source.size() ||
                !std::isdigit(static_cast<unsigned char>(source[exponentStart]))) {
                return false;
            }
            continue;
        }
        return false;
    }
    return true;
}

double evaluateStaticExpression(const ast::Expression& expression) {
    return expression.evaluate([](const std::string& name) -> double {
        throw std::runtime_error("unresolved identifier '" + name + "'");
    });
}

bool evaluateFiniteStaticExpression(const ast::Expression& expression, double& value) {
    try {
        value = evaluateStaticExpression(expression);
        return std::isfinite(value);
    } catch (const std::exception&) {
        return false;
    }
}

bool supportsStaticActionArithmetic(const ast::Expression& expression,
                                    std::size_t& powerOperators) {
    using ast::ExpressionKind;
    switch (expression.kind()) {
    case ExpressionKind::Number:
        return std::isfinite(expression.numberValue());
    case ExpressionKind::Unary: {
        if ((expression.name() != "+" && expression.name() != "-") ||
            expression.args().size() != 1) {
            return false;
        }
        if (!supportsStaticActionArithmetic(expression.args().front(), powerOperators)) {
            return false;
        }
        double value = 0.0;
        return evaluateFiniteStaticExpression(expression, value);
    }
    case ExpressionKind::Binary: {
        const auto& op = expression.name();
        if (op != "+" && op != "-" && op != "*" && op != "/" && op != "**") {
            // In Safe Perl, ^ is bitwise XOR, not exponentiation; modulo also
            // differs for non-integral values. Do not inherit BNGL's evaluator
            // semantics for those operators.
            return false;
        }
        if (expression.args().size() != 2 ||
            !supportsStaticActionArithmetic(expression.args()[0], powerOperators) ||
            !supportsStaticActionArithmetic(expression.args()[1], powerOperators)) {
            return false;
        }
        double rhs = 0.0;
        if (op == "/" &&
            (!evaluateFiniteStaticExpression(expression.args()[1], rhs) || rhs == 0.0)) {
            return false;
        }
        if (op == "**") {
            // Safe Perl exponentiation is right-associative, while the current
            // BNGL expression builder is left-associative. A single exponent
            // with a non-negative base has the same value in both evaluators.
            double base = 0.0;
            if (++powerOperators > 1 ||
                !evaluateFiniteStaticExpression(expression.args()[0], base) || base < 0.0) {
                return false;
            }
        }
        double value = 0.0;
        return evaluateFiniteStaticExpression(expression, value);
    }
    case ExpressionKind::Identifier:
    case ExpressionKind::Function:
    case ExpressionKind::ObservableRef:
    case ExpressionKind::TableFunction:
        return false;
    }
    return false;
}

GenerateNetworkOptions compileGenerateNetworkOptions(
    const std::map<std::string, std::string>& arguments) {
    GenerateNetworkOptions options;
    const auto maxAggregate = arguments.find("max_agg");
    if (maxAggregate != arguments.end()) {
        const auto& source = maxAggregate->second;
        if (!containsOnlyNumericActionSyntax(source)) {
            options.maxAggregateDiagnostic = maxAggregateDiagnostic(
                source, "names, functions, and non-numeric syntax are not supported");
        } else {
            ast::Expression expression;
            try {
                expression = parser::parseExpression(source);
            } catch (const std::exception& error) {
                options.maxAggregateDiagnostic = maxAggregateDiagnostic(
                    source, std::string("could not be parsed as a numeric expression: ") +
                                error.what());
            }

            if (!options.maxAggregateDiagnostic.has_value()) {
                std::size_t powerOperators = 0;
                if (!supportsStaticActionArithmetic(expression, powerOperators)) {
                    options.maxAggregateDiagnostic = maxAggregateDiagnostic(
                        source,
                        "cannot be translated without changing Safe-Perl arithmetic semantics");
                }
            }

            if (!options.maxAggregateDiagnostic.has_value()) {
                double value = 0.0;
                try {
                    value = evaluateStaticExpression(expression);
                } catch (const std::exception& error) {
                    options.maxAggregateDiagnostic = maxAggregateDiagnostic(
                        source, std::string("could not be evaluated: ") + error.what());
                }
                if (!options.maxAggregateDiagnostic.has_value()) {
                    if (!std::isfinite(value)) {
                        options.maxAggregateDiagnostic = maxAggregateDiagnostic(
                            source, "must evaluate to a finite number");
                    } else {
                        options.maxAggregate = value;
                    }
                }
            }
        }
    }

    const auto found = arguments.find("max_iter");
    if (found == arguments.end()) {
        return options;
    }

    const auto& source = found->second;
    if (!containsOnlyNumericActionSyntax(source)) {
        options.maxIterationsDiagnostic = maxIterationsDiagnostic(
            source, "names, functions, and non-numeric syntax are not supported");
        return options;
    }

    ast::Expression expression;
    try {
        expression = parser::parseExpression(source);
    } catch (const std::exception& error) {
        options.maxIterationsDiagnostic = maxIterationsDiagnostic(
            source, std::string("could not be parsed as a numeric expression: ") + error.what());
        return options;
    }

    std::size_t powerOperators = 0;
    if (!supportsStaticActionArithmetic(expression, powerOperators)) {
        options.maxIterationsDiagnostic = maxIterationsDiagnostic(
            source, "cannot be translated without changing Safe-Perl arithmetic semantics");
        return options;
    }

    double value = 0.0;
    try {
        value = evaluateStaticExpression(expression);
    } catch (const std::exception& error) {
        options.maxIterationsDiagnostic = maxIterationsDiagnostic(
            source, std::string("could not be evaluated: ") + error.what());
        return options;
    }
    if (!std::isfinite(value)) {
        options.maxIterationsDiagnostic = maxIterationsDiagnostic(
            source, "must evaluate to a finite number");
        return options;
    }

    // Perl's 1 .. $max_iter range includes only integer endpoints, so positive
    // fractional bounds truncate toward zero (for example, 2.5 means 2).
    const double iterations = std::floor(value);
    if (iterations < 1.0) {
        options.maxIterationsDiagnostic = maxIterationsDiagnostic(
            source, "must evaluate to at least one iteration");
        return options;
    }

    // BNG2's Perl action range is limited by its signed IV type. Keep the
    // accepted bound within that range and the host's size_t representation.
    const int acceptedValueBits = std::min(
        std::numeric_limits<std::int64_t>::digits,
        std::numeric_limits<std::size_t>::digits);
    const double firstUnsupportedValue = std::ldexp(1.0, acceptedValueBits);
    if (iterations >= firstUnsupportedValue) {
        options.maxIterationsDiagnostic = maxIterationsDiagnostic(
            source, "exceeds the supported integer iteration range");
        return options;
    }

    options.maxIterations = static_cast<std::size_t>(iterations);
    return options;
}

ProtocolAction compileProtocolAction(ActionScope scope, const ast::Action& action) {
    ProtocolAction compiled;
    compiled.scope = scope;
    compiled.name = action.name;
    compiled.arguments = action.arguments;
    if (action.name == "generate_network") {
        compiled.generateNetworkOptions = compileGenerateNetworkOptions(action.arguments);
    }
    return compiled;
}

} // namespace

std::vector<ProtocolAction> SimulationProtocol::modelActions() const {
    std::vector<ProtocolAction> result;
    for (const auto& action : actions)
        if (action.scope == ActionScope::Model) result.push_back(action);
    return result;
}

std::vector<ProtocolAction> SimulationProtocol::simulationActions() const {
    std::vector<ProtocolAction> result;
    for (const auto& action : actions)
        if (action.scope == ActionScope::SimulationProtocol) result.push_back(action);
    return result;
}

Document::Document(const ast::Model& model)
    : model_(model) {
    protocol_.actions.reserve(model.getActions().size() + model.getSimulationProtocol().size());
    for (const auto& action : model.getActions()) {
        protocol_.actions.push_back(compileProtocolAction(ActionScope::Model, action));
    }
    for (const auto& action : model.getSimulationProtocol()) {
        protocol_.actions.push_back(
            compileProtocolAction(ActionScope::SimulationProtocol, action));
    }
}

} // namespace bng::compile
