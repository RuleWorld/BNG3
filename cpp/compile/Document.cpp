#include "Document.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <utility>

#include "SimulationMethod.hpp"
#include "ast/Model.hpp"
#include "parser/BNGAstVisitor.hpp"

namespace bng::compile {

namespace {

using GenerateNetworkOptions = ProtocolAction::GenerateNetworkOptions;
using SimulationOptions = ProtocolAction::SimulationOptions;
using SetParameterOptions = ProtocolAction::SetParameterOptions;

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

Diagnostic maxStoichDiagnostic(const std::string& source,
                                const std::string& reason) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Expressions;
    diagnostic.entity = "generate_network.max_stoich";
    diagnostic.message = "invalid generate_network max_stoich '" + source + "': " + reason;
    return diagnostic;
}

Diagnostic nStepsDiagnostic(const std::string& source, const std::string& reason) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Expressions;
    diagnostic.entity = "simulation.n_steps";
    diagnostic.message = "invalid n_steps '" + source + "': " + reason;
    return diagnostic;
}

Diagnostic setParameterValueDiagnostic(const std::string& source,
                                       const std::string& reason) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Expressions;
    diagnostic.entity = "setParameter.value";
    diagnostic.message = "invalid setParameter value '" + source + "': " + reason;
    return diagnostic;
}

bool isQuotedActionValue(const std::string& value) {
    return value.size() >= 2 &&
           ((value.front() == '"' && value.back() == '"') ||
            (value.front() == '\'' && value.back() == '\''));
}

std::string unquoteActionValue(std::string value) {
    if (isQuotedActionValue(value)) {
        value = value.substr(1, value.size() - 2);
    }
    return value;
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

bool isMaxStoichMoleculeName(const std::string& name) {
    const auto isLetter = [](unsigned char character) {
        return (character >= 'A' && character <= 'Z') ||
               (character >= 'a' && character <= 'z');
    };
    if (name.empty() || (name.front() != '_' &&
                         !isLetter(static_cast<unsigned char>(name.front())))) {
        return false;
    }
    return std::all_of(name.begin() + 1, name.end(), [&](unsigned char character) {
        return character == '_' || isLetter(character) ||
               (character >= '0' && character <= '9');
    });
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
                                    std::size_t& powerOperators,
                                    bool allowCaret = false) {
    using ast::ExpressionKind;
    switch (expression.kind()) {
    case ExpressionKind::Number:
        return std::isfinite(expression.numberValue());
    case ExpressionKind::Unary: {
        if ((expression.name() != "+" && expression.name() != "-") ||
            expression.args().size() != 1) {
            return false;
        }
        if (!supportsStaticActionArithmetic(
                expression.args().front(), powerOperators, allowCaret)) {
            return false;
        }
        double value = 0.0;
        return evaluateFiniteStaticExpression(expression, value);
    }
    case ExpressionKind::Binary: {
        const auto& op = expression.name();
        if (op != "+" && op != "-" && op != "*" && op != "/" && op != "**" &&
            !(allowCaret && op == "^")) {
            // Unquoted Safe Perl uses ^ for XOR; modulo also differs for
            // non-integral values. Keep those operators out of that path.
            return false;
        }
        if (expression.args().size() != 2 ||
            !supportsStaticActionArithmetic(
                expression.args()[0], powerOperators, allowCaret) ||
            !supportsStaticActionArithmetic(
                expression.args()[1], powerOperators, allowCaret)) {
            return false;
        }
        double rhs = 0.0;
        if (op == "/" &&
            (!evaluateFiniteStaticExpression(expression.args()[1], rhs) || rhs == 0.0)) {
            return false;
        }
        if (op == "**" || op == "^") {
            // Keep the existing conservative static limit for both exponent
            // spellings: one power node with a non-negative base.
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

bool isParameterArithmeticExpression(const ast::Expression& expression,
                                     bool& hasIdentifier,
                                     bool& hasOperator,
                                     bool quotedCaretScope = false) {
    using ast::ExpressionKind;
    switch (expression.kind()) {
    case ExpressionKind::Number:
        return true;
    case ExpressionKind::Identifier:
        if (quotedCaretScope &&
            (expression.name() == "time" || expression.name() == "t")) {
            return false;
        }
        hasIdentifier = true;
        return true;
    case ExpressionKind::Unary:
        if ((expression.name() != "+" && expression.name() != "-") ||
            expression.args().size() != 1) {
            return false;
        }
        hasOperator = true;
        return isParameterArithmeticExpression(
            expression.args().front(), hasIdentifier, hasOperator, quotedCaretScope);
    case ExpressionKind::Binary: {
        const auto& op = expression.name();
        if ((op != "+" && op != "-" && op != "*" && op != "/" &&
             op != "**" && op != "^" &&
             !(op == "%" && !quotedCaretScope)) ||
            expression.args().size() != 2) {
            return false;
        }
        hasOperator = true;
        return isParameterArithmeticExpression(
                   expression.args()[0], hasIdentifier, hasOperator,
                   quotedCaretScope) &&
               isParameterArithmeticExpression(
                   expression.args()[1], hasIdentifier, hasOperator,
                   quotedCaretScope);
    }
    case ExpressionKind::Function:
    case ExpressionKind::ObservableRef:
    case ExpressionKind::TableFunction:
        return false;
    }
    return false;
}

bool containsPowerOperator(const ast::Expression& expression,
                           const std::string& op) {
    if (expression.kind() == ast::ExpressionKind::Binary &&
        expression.name() == op) {
        return true;
    }
    for (const auto& argument : expression.args()) {
        if (containsPowerOperator(argument, op)) {
            return true;
        }
    }
    return false;
}

bool containsStaticallyNegativeCaretBase(const ast::Expression& expression) {
    if (expression.kind() == ast::ExpressionKind::Binary &&
        expression.name() == "^" && expression.args().size() == 2) {
        double base = 0.0;
        if (evaluateFiniteStaticExpression(expression.args().front(), base) && base < 0.0) {
            return true;
        }
    }
    for (const auto& argument : expression.args()) {
        if (containsStaticallyNegativeCaretBase(argument)) {
            return true;
        }
    }
    return false;
}

SetParameterOptions compileSetParameterOptions(
    const std::map<std::string, std::string>& arguments) {
    SetParameterOptions options;
    const auto found = arguments.find("value");
    if (found == arguments.end()) {
        return options;
    }

    const auto& source = found->second;
    const bool valueWasQuoted = isQuotedActionValue(source);
    const auto expressionSource = unquoteActionValue(source);
    if (!valueWasQuoted && expressionSource.find('^') != std::string::npos) {
        options.valueDiagnostic = setParameterValueDiagnostic(
            source, "Safe-Perl '^' is bitwise XOR; use '**' for exponentiation");
        return options;
    }

    ast::Expression expression;
    bool expressionParsed = false;
    if (valueWasQuoted &&
        (expressionSource.find('^') != std::string::npos ||
         expressionSource.find("**") != std::string::npos)) {
        try {
            expression = parser::parseExpression(expressionSource);
            expressionParsed = true;
        } catch (const std::exception& error) {
            options.valueDiagnostic = setParameterValueDiagnostic(
                source, std::string("could not be parsed as a numeric expression: ") +
                           error.what());
            return options;
        }

        if (containsPowerOperator(expression, "^") &&
            containsPowerOperator(expression, "**")) {
            options.valueDiagnostic = setParameterValueDiagnostic(
                source, "mixing '^' and '**' power operators is unsupported");
            return options;
        }
        if (containsStaticallyNegativeCaretBase(expression)) {
            options.valueDiagnostic = setParameterValueDiagnostic(
                source, "quoted caret power with a statically negative base is unsupported");
            return options;
        }
        if (containsPowerOperator(expression, "**")) {
            options.valueDiagnostic = setParameterValueDiagnostic(
                source,
                "quoted '**' power expressions are unsupported by the current runtime evaluator");
            return options;
        }
        if (containsPowerOperator(expression, "^") &&
            !containsOnlyNumericActionSyntax(expressionSource)) {
            bool hasIdentifier = false;
            bool hasOperator = false;
            if (!isParameterArithmeticExpression(
                    expression, hasIdentifier, hasOperator, true) ||
                !hasIdentifier || !hasOperator) {
                options.valueDiagnostic = setParameterValueDiagnostic(
                    source,
                    "quoted caret expressions require simple parameter arithmetic; "
                    "clock aliases, functions, TFUN, and modulo are unsupported");
                return options;
            }
        }
    }

    if (!containsOnlyNumericActionSyntax(expressionSource)) {
        if (!valueWasQuoted) {
            try {
                const auto expression = parser::parseExpression(expressionSource);
                bool hasIdentifier = false;
                bool hasOperator = false;
                if (isParameterArithmeticExpression(
                        expression, hasIdentifier, hasOperator) &&
                    hasIdentifier && hasOperator) {
                    options.valueDiagnostic = setParameterValueDiagnostic(
                        source,
                        "unquoted named arithmetic uses Safe-Perl semantics and "
                        "cannot be translated without changing results");
                }
            } catch (const std::exception&) {
                // Leave unsupported or otherwise dynamic values for the existing
                // execution-time path, which reports failures when the setter runs.
            }
        }
        // Parameter-backed values stay raw so execution can resolve them after
        // preceding actions have updated the model. Quoted values use BNGL
        // expression semantics, including '^' for exponentiation; quoted '**'
        // is rejected above because the current runtime evaluator mishandles it.
        return options;
    }

    if (!expressionParsed) {
        try {
            expression = parser::parseExpression(expressionSource);
        } catch (const std::exception& error) {
            options.valueDiagnostic = setParameterValueDiagnostic(
                source, std::string("could not be parsed as a numeric expression: ") +
                            error.what());
            return options;
        }
    }

    std::size_t powerOperators = 0;
    if (!supportsStaticActionArithmetic(expression, powerOperators, valueWasQuoted)) {
        options.valueDiagnostic = setParameterValueDiagnostic(
            source,
            "cannot be translated without changing Safe-Perl arithmetic semantics");
        return options;
    }

    double value = 0.0;
    if (!evaluateFiniteStaticExpression(expression, value)) {
        options.valueDiagnostic = setParameterValueDiagnostic(
            source, "must evaluate to a finite number");
        return options;
    }
    options.staticValue = value;
    return options;
}

GenerateNetworkOptions compileGenerateNetworkOptions(
    const std::map<std::string, std::string>& arguments) {
    GenerateNetworkOptions options;
    const auto maxStoich = arguments.find("max_stoich");
    if (maxStoich != arguments.end()) {
        const auto& source = maxStoich->second;
        try {
            GenerateNetworkOptions::MaxStoichLimits limits;
            const auto entries = parser::parseNestedHashEntries(source);
            for (const auto& [sourceKey, valueSource] : entries) {
                const auto key = unquoteActionValue(sourceKey);
                if (!isMaxStoichMoleculeName(key)) {
                    options.maxStoichDiagnostic = maxStoichDiagnostic(
                        source, "key '" + sourceKey + "' is not a valid molecule name");
                    break;
                }
                if (valueSource == "unlimited" || valueSource == "'unlimited'" ||
                    valueSource == "\"unlimited\"") {
                    limits.insert_or_assign(key, std::nullopt);
                    continue;
                }

                if (!containsOnlyNumericActionSyntax(valueSource)) {
                    options.maxStoichDiagnostic = maxStoichDiagnostic(
                        source, "names, functions, and non-numeric syntax are not supported");
                    break;
                }

                ast::Expression expression;
                try {
                    expression = parser::parseExpression(valueSource);
                } catch (const std::exception& error) {
                    options.maxStoichDiagnostic = maxStoichDiagnostic(
                        source,
                        std::string("could not parse value '") + valueSource + "': " +
                            error.what());
                    break;
                }

                std::size_t powerOperators = 0;
                if (!supportsStaticActionArithmetic(expression, powerOperators)) {
                    options.maxStoichDiagnostic = maxStoichDiagnostic(
                        source,
                        std::string("value '") + valueSource +
                            "' cannot be translated without changing Safe-Perl arithmetic semantics");
                    break;
                }

                double value = 0.0;
                if (!evaluateFiniteStaticExpression(expression, value)) {
                    options.maxStoichDiagnostic = maxStoichDiagnostic(
                        source, std::string("value '") + valueSource +
                                    "' must evaluate to a finite number");
                    break;
                }
                // Perl hash assignment keeps the last value for a repeated key.
                limits.insert_or_assign(key, value);
            }
            if (!options.maxStoichDiagnostic.has_value()) {
                options.maxStoich = std::move(limits);
            }
        } catch (const std::exception& error) {
            options.maxStoichDiagnostic = maxStoichDiagnostic(
                source, std::string("could not be parsed as a nested map: ") + error.what());
        }
    }

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

SimulationOptions compileSimulationOptions(
    const std::map<std::string, std::string>& arguments) {
    SimulationOptions options;
    const auto found = arguments.find("n_steps");
    if (found == arguments.end()) {
        return options;
    }

    const auto& source = found->second;
    const auto expressionSource = unquoteActionValue(source);
    if (expressionSource.find('^') != std::string::npos) {
        options.nStepsDiagnostic = nStepsDiagnostic(
            source,
            "Safe-Perl '^' is bitwise XOR; use '**' for exponentiation");
        return options;
    }

    // Parameter-backed and otherwise dynamic values remain raw for execution:
    // protocol actions may change parameters, and runSimulation resolves them
    // only after argfile merging and earlier protocol actions have run.
    if (!containsOnlyNumericActionSyntax(expressionSource)) {
        return options;
    }

    ast::Expression expression;
    try {
        expression = parser::parseExpression(expressionSource);
    } catch (const std::exception& error) {
        options.nStepsDiagnostic = nStepsDiagnostic(
            source,
            std::string("could not be parsed as a numeric expression: ") + error.what());
        return options;
    }

    std::size_t powerOperators = 0;
    if (!supportsStaticActionArithmetic(expression, powerOperators)) {
        options.nStepsDiagnostic = nStepsDiagnostic(
            source,
            "cannot be translated without changing Safe-Perl arithmetic semantics");
        return options;
    }

    double value = 0.0;
    if (!evaluateFiniteStaticExpression(expression, value)) {
        options.nStepsDiagnostic = nStepsDiagnostic(
            source, "must evaluate to a finite number");
        return options;
    }
    if (value <= 0.0 || std::floor(value) != value) {
        options.nStepsDiagnostic = nStepsDiagnostic(
            source, "must evaluate to a positive integer");
        return options;
    }

    const double firstUnsupportedValue =
        std::ldexp(1.0, std::numeric_limits<std::size_t>::digits);
    if (value >= firstUnsupportedValue) {
        options.nStepsDiagnostic = nStepsDiagnostic(
            source, "exceeds the supported integer step-count range");
        return options;
    }

    options.nSteps = static_cast<std::size_t>(value);
    return options;
}

std::optional<SimulationOptions> compileSimulationOptions(
    const ast::Action& action) {
    // The method decision is shared with the action dispatcher, so the typed
    // options are compiled for exactly the actions the dispatcher runs as a
    // deterministic or direct-method stochastic simulation.
    const auto decision = tryDecideSimulationMethod(action);
    if (!decision.has_value() ||
        (!decision->deterministic && !decision->stochastic)) {
        return std::nullopt;
    }
    return compileSimulationOptions(action.arguments);
}

ProtocolAction compileProtocolAction(ActionScope scope, const ast::Action& action) {
    ProtocolAction compiled;
    compiled.scope = scope;
    compiled.name = action.name;
    compiled.arguments = action.arguments;
    if (action.name == "generate_network") {
        compiled.generateNetworkOptions = compileGenerateNetworkOptions(action.arguments);
    }
    std::string actionName = action.name;
    std::transform(actionName.begin(), actionName.end(), actionName.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (actionName == "setparameter") {
        compiled.setParameterOptions = compileSetParameterOptions(action.arguments);
    }
    compiled.simulationOptions = compileSimulationOptions(action);
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
