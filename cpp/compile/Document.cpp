#include "Document.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <utility>

#include "ast/Model.hpp"
#include "parser/BNGAstVisitor.hpp"

namespace bng::compile {

namespace {

using GenerateNetworkOptions = ProtocolAction::GenerateNetworkOptions;
using SimulationOptions = ProtocolAction::SimulationOptions;
using SetParameterOptions = ProtocolAction::SetParameterOptions;
using SetConcentrationOptions = ProtocolAction::SetConcentrationOptions;
using AddConcentrationOptions = ProtocolAction::AddConcentrationOptions;
using SaveParametersOptions = ProtocolAction::SaveParametersOptions;
using ResetParametersOptions = ProtocolAction::ResetParametersOptions;
using SaveConcentrationsOptions = ProtocolAction::SaveConcentrationsOptions;
using ResetConcentrationsOptions = ProtocolAction::ResetConcentrationsOptions;
using SetVolumeOptions = ProtocolAction::SetVolumeOptions;
using SetOptionOptions = ProtocolAction::SetOptionOptions;
using ArgFileOptions = ProtocolAction::ArgFileOptions;
using WriteModelOptions = ProtocolAction::WriteModelOptions;

std::string trim(std::string value) {
    auto first = std::find_if_not(value.begin(), value.end(), [](unsigned char c) {
        return std::isspace(c) != 0;
    });
    auto last = std::find_if_not(value.rbegin(), value.rend(), [](unsigned char c) {
        return std::isspace(c) != 0;
    }).base();
    if (first >= last) {
        return {};
    }
    return std::string(first, last);
}

Diagnostic concentrationValueDiagnostic(const std::string& entity,
                                        const std::string& source,
                                        const std::string& reason) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Expressions;
    diagnostic.entity = entity + ".value";
    diagnostic.message = "invalid " + entity + " value '" + source + "': " + reason;
    return diagnostic;
}

Diagnostic volumeDiagnostic(const std::string& source, const std::string& reason) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Expressions;
    diagnostic.entity = "setVolume.value";
    diagnostic.message = "invalid setVolume value '" + source + "': " + reason;
    return diagnostic;
}

Diagnostic outputStepIntervalDiagnostic(const std::string& source,
                                       const std::string& reason) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Expressions;
    diagnostic.entity = "simulation.output_step_interval";
    diagnostic.message = "invalid output_step_interval '" + source + "': " + reason;
    return diagnostic;
}

Diagnostic sampleTimesDiagnostic(const std::string& source,
                                 const std::string& reason) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Expressions;
    diagnostic.entity = "simulation.sample_times";
    diagnostic.message = "invalid sample_times '" + source + "': " + reason;
    return diagnostic;
}

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

Diagnostic simulationTimeDiagnostic(const std::string& field,
                                    const std::string& source,
                                    const std::string& reason) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Expressions;
    diagnostic.entity = "simulation." + field;
    diagnostic.message = "invalid " + field + " '" + source + "': " + reason;
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
    const auto targetFound = arguments.find("target");
    if (targetFound != arguments.end()) {
        options.target = unquoteActionValue(targetFound->second);
    }
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

void compileSimulationTimeOption(
    const std::map<std::string, std::string>& arguments,
    const std::string& field,
    std::optional<double>& value,
    std::optional<Diagnostic>& diagnostic) {
    const auto found = arguments.find(field);
    if (found == arguments.end()) {
        return;
    }

    const auto& source = found->second;
    const auto expressionSource = unquoteActionValue(source);
    if (expressionSource.find('^') != std::string::npos) {
        diagnostic = simulationTimeDiagnostic(
            field, source,
            "Safe-Perl '^' is bitwise XOR; use '**' for exponentiation");
        return;
    }

    // Parameter-backed expressions must be evaluated when the action runs,
    // after preceding protocol setters and argfile resolution.
    if (!containsOnlyNumericActionSyntax(expressionSource)) {
        return;
    }

    ast::Expression expression;
    try {
        expression = parser::parseExpression(expressionSource);
    } catch (const std::exception& error) {
        diagnostic = simulationTimeDiagnostic(
            field, source,
            std::string("could not be parsed as a numeric expression: ") + error.what());
        return;
    }

    double parsedValue = 0.0;
    if (!evaluateFiniteStaticExpression(expression, parsedValue)) {
        diagnostic = simulationTimeDiagnostic(
            field, source, "must evaluate to a finite number");
        return;
    }

    std::size_t powerOperators = 0;
    if (!supportsStaticActionArithmetic(expression, powerOperators)) {
        // Keep expressions outside this compiler's conservative arithmetic
        // subset for the existing execution-time evaluator.
        return;
    }
    value = parsedValue;
}

bool tryParseStaticScalar(const std::string& source,
                          double& value,
                          std::optional<Diagnostic>& diagnostic,
                          const std::function<Diagnostic(const std::string&)>& makeDiag) {
    const auto expressionSource = unquoteActionValue(source);
    if (!containsOnlyNumericActionSyntax(expressionSource)) {
        return false;
    }
    ast::Expression expression;
    try {
        expression = parser::parseExpression(expressionSource);
    } catch (const std::exception& error) {
        diagnostic = makeDiag(std::string("could not be parsed as a numeric expression: ") + error.what());
        return false;
    }
    std::size_t powerOps = 0;
    if (!supportsStaticActionArithmetic(expression, powerOps)) {
        return false;
    }
    double val = 0.0;
    if (!evaluateFiniteStaticExpression(expression, val)) {
        diagnostic = makeDiag("must evaluate to a finite number");
        return false;
    }
    value = val;
    return true;
}

SetConcentrationOptions compileSetConcentrationOptions(
    const std::map<std::string, std::string>& arguments) {
    SetConcentrationOptions options;
    const auto targetFound = arguments.find("target");
    if (targetFound != arguments.end()) {
        options.target = unquoteActionValue(targetFound->second);
    }
    const auto valueFound = arguments.find("value");
    if (valueFound != arguments.end()) {
        double val = 0.0;
        if (tryParseStaticScalar(valueFound->second, val, options.valueDiagnostic,
                                 [&](const std::string& reason) {
                                     return concentrationValueDiagnostic("setConcentration", valueFound->second, reason);
                                 })) {
            options.staticValue = val;
        }
    }
    return options;
}

AddConcentrationOptions compileAddConcentrationOptions(
    const std::map<std::string, std::string>& arguments) {
    AddConcentrationOptions options;
    const auto targetFound = arguments.find("target");
    if (targetFound != arguments.end()) {
        options.target = unquoteActionValue(targetFound->second);
    }
    const auto valueFound = arguments.find("value");
    if (valueFound != arguments.end()) {
        double val = 0.0;
        if (tryParseStaticScalar(valueFound->second, val, options.valueDiagnostic,
                                 [&](const std::string& reason) {
                                     return concentrationValueDiagnostic("addConcentration", valueFound->second, reason);
                                 })) {
            options.staticValue = val;
        }
    }
    return options;
}

SaveParametersOptions compileSaveParametersOptions(
    const std::map<std::string, std::string>& arguments) {
    SaveParametersOptions options;
    const auto found = arguments.find("value");
    if (found != arguments.end()) {
        options.label = unquoteActionValue(found->second);
    }
    return options;
}

ResetParametersOptions compileResetParametersOptions(
    const std::map<std::string, std::string>& arguments) {
    ResetParametersOptions options;
    const auto found = arguments.find("value");
    if (found != arguments.end()) {
        options.label = unquoteActionValue(found->second);
    }
    return options;
}

SaveConcentrationsOptions compileSaveConcentrationsOptions(
    const std::map<std::string, std::string>& arguments) {
    SaveConcentrationsOptions options;
    const auto found = arguments.find("value");
    if (found != arguments.end()) {
        options.label = unquoteActionValue(found->second);
    }
    return options;
}

ResetConcentrationsOptions compileResetConcentrationsOptions(
    const std::map<std::string, std::string>& arguments) {
    ResetConcentrationsOptions options;
    const auto found = arguments.find("value");
    if (found != arguments.end()) {
        options.label = unquoteActionValue(found->second);
    }
    return options;
}

SetVolumeOptions compileSetVolumeOptions(
    const std::map<std::string, std::string>& arguments) {
    SetVolumeOptions options;
    const auto targetFound = arguments.find("target");
    if (targetFound != arguments.end()) {
        options.target = unquoteActionValue(targetFound->second);
    }
    const auto valueFound = arguments.find("value");
    if (valueFound != arguments.end()) {
        double val = 0.0;
        if (tryParseStaticScalar(valueFound->second, val, options.volumeDiagnostic,
                                 [&](const std::string& reason) {
                                     return volumeDiagnostic(valueFound->second, reason);
                                 })) {
            options.staticVolume = val;
        }
    }
    return options;
}

SetOptionOptions compileSetOptionOptions(
    const std::map<std::string, std::string>& arguments) {
    SetOptionOptions options;
    auto found = arguments.find("target");
    if (found == arguments.end()) {
        found = arguments.find("option");
    }
    if (found != arguments.end()) {
        options.option = unquoteActionValue(found->second);
    }
    const auto valFound = arguments.find("value");
    if (valFound != arguments.end()) {
        options.value = unquoteActionValue(valFound->second);
    }
    return options;
}

ArgFileOptions compileArgFileOptions(
    const std::map<std::string, std::string>& arguments) {
    ArgFileOptions options;
    auto found = arguments.find("file");
    if (found == arguments.end()) {
        found = arguments.find("target");
    }
    if (found != arguments.end()) {
        options.file = unquoteActionValue(found->second);
    }
    return options;
}

WriteModelOptions compileWriteModelOptions(
    const std::string& actionName,
    const std::map<std::string, std::string>& arguments) {
    WriteModelOptions options;
    options.format = actionName;
    const auto prefixFound = arguments.find("prefix");
    if (prefixFound != arguments.end()) {
        options.prefix = unquoteActionValue(prefixFound->second);
    } else {
        const auto fileFound = arguments.find("file");
        if (fileFound != arguments.end()) {
            options.prefix = unquoteActionValue(fileFound->second);
        }
    }
    return options;
}

SimulationOptions compileSimulationOptions(
    const std::map<std::string, std::string>& arguments) {
    SimulationOptions options;
    const auto methodFound = arguments.find("method");
    if (methodFound != arguments.end()) {
        options.method = unquoteActionValue(methodFound->second);
    }
    compileSimulationTimeOption(
        arguments, "t_start", options.tStart, options.tStartDiagnostic);
    compileSimulationTimeOption(
        arguments, "t_end", options.tEnd, options.tEndDiagnostic);

    const auto found = arguments.find("n_steps");
    if (found != arguments.end()) {
        const auto& source = found->second;
        const auto expressionSource = unquoteActionValue(source);
        if (expressionSource.find('^') != std::string::npos) {
            options.nStepsDiagnostic = nStepsDiagnostic(
                source,
                "Safe-Perl '^' is bitwise XOR; use '**' for exponentiation");
        } else if (containsOnlyNumericActionSyntax(expressionSource)) {
            ast::Expression expression;
            try {
                expression = parser::parseExpression(expressionSource);
                std::size_t powerOperators = 0;
                if (!supportsStaticActionArithmetic(expression, powerOperators)) {
                    options.nStepsDiagnostic = nStepsDiagnostic(
                        source,
                        "cannot be translated without changing Safe-Perl arithmetic semantics");
                } else {
                    double value = 0.0;
                    if (!evaluateFiniteStaticExpression(expression, value)) {
                        options.nStepsDiagnostic = nStepsDiagnostic(
                            source, "must evaluate to a finite number");
                    } else if (value <= 0.0 || std::floor(value) != value) {
                        options.nStepsDiagnostic = nStepsDiagnostic(
                            source, "must evaluate to a positive integer");
                    } else {
                        const double firstUnsupportedValue =
                            std::ldexp(1.0, std::numeric_limits<std::size_t>::digits);
                        if (value >= firstUnsupportedValue) {
                            options.nStepsDiagnostic = nStepsDiagnostic(
                                source, "exceeds the supported integer step-count range");
                        } else {
                            options.nSteps = static_cast<std::size_t>(value);
                        }
                    }
                }
            } catch (const std::exception& error) {
                options.nStepsDiagnostic = nStepsDiagnostic(
                    source,
                    std::string("could not be parsed as a numeric expression: ") + error.what());
            }
        }
    }

    const auto intervalFound = arguments.find("output_step_interval");
    if (intervalFound != arguments.end()) {
        const auto& source = intervalFound->second;
        const auto expressionSource = unquoteActionValue(source);
        if (containsOnlyNumericActionSyntax(expressionSource)) {
            try {
                const auto expr = parser::parseExpression(expressionSource);
                double val = 0.0;
                if (evaluateFiniteStaticExpression(expr, val) && val >= 0.0) {
                    options.outputStepInterval = static_cast<std::size_t>(val);
                }
            } catch (...) {}
        }
    }

    const auto continueFound = arguments.find("continue");
    if (continueFound != arguments.end()) {
        const auto val = unquoteActionValue(continueFound->second);
        if (val == "1" || val == "true" || val == "yes") {
            options.continueSimulation = true;
        } else if (val == "0" || val == "false" || val == "no") {
            options.continueSimulation = false;
        }
    }

    const auto printCdatFound = arguments.find("print_concentrations");
    if (printCdatFound != arguments.end()) {
        const auto val = unquoteActionValue(printCdatFound->second);
        options.printConcentrations = (val == "1" || val == "true" || val == "yes");
    }

    const auto printFuncsFound = arguments.find("print_functions");
    if (printFuncsFound != arguments.end()) {
        const auto val = unquoteActionValue(printFuncsFound->second);
        options.printFunctions = (val == "1" || val == "true" || val == "yes");
    }

    const auto printNetFound = arguments.find("print_net");
    if (printNetFound != arguments.end()) {
        const auto val = unquoteActionValue(printNetFound->second);
        options.printNet = (val == "1" || val == "true" || val == "yes");
    }

    const auto steadyFound = arguments.find("steady_state");
    if (steadyFound != arguments.end()) {
        const auto val = unquoteActionValue(steadyFound->second);
        options.steadyState = (val == "1" || val == "true" || val == "yes");
    }

    const auto threshFound = arguments.find("threshold");
    if (threshFound != arguments.end()) {
        double val = 0.0;
        if (tryParseStaticScalar(threshFound->second, val, options.steadyStateTolDiagnostic,
                                 [&](const std::string& reason) {
                                     Diagnostic d;
                                     d.code = DiagnosticCode::InvalidModel;
                                     d.severity = Severity::Error;
                                     d.category = ValidationCategory::Expressions;
                                     d.entity = "simulation.threshold";
                                     d.message = "invalid threshold '" + threshFound->second + "': " + reason;
                                     return d;
                                 })) {
            options.steadyStateTol = val;
        }
    }

    const auto stopIfFound = arguments.find("stop_if");
    if (stopIfFound != arguments.end()) {
        options.stopIf = unquoteActionValue(stopIfFound->second);
    }

    const auto prefixFound = arguments.find("prefix");
    if (prefixFound != arguments.end()) {
        options.prefix = unquoteActionValue(prefixFound->second);
    }

    const auto seedFound = arguments.find("seed");
    if (seedFound != arguments.end()) {
        const auto val = unquoteActionValue(seedFound->second);
        if (containsOnlyNumericActionSyntax(val)) {
            try {
                options.seed = static_cast<unsigned int>(std::stoul(val));
            } catch (...) {}
        }
    }

    const auto sampleTimesFound = arguments.find("sample_times");
    if (sampleTimesFound != arguments.end()) {
        const auto raw = unquoteActionValue(sampleTimesFound->second);
        if (raw.size() >= 2 && raw.front() == '[' && raw.back() == ']') {
            std::stringstream ss(raw.substr(1, raw.size() - 2));
            std::string item;
            bool ok = true;
            std::vector<double> times;
            while (std::getline(ss, item, ',')) {
                item = trim(item);
                if (item.empty()) continue;
                try {
                    times.push_back(std::stod(item));
                } catch (...) {
                    ok = false;
                    break;
                }
            }
            if (ok) {
                options.sampleTimes = std::move(times);
            } else {
                options.sampleTimesDiagnostic = sampleTimesDiagnostic(
                    sampleTimesFound->second, "malformed sample_times list");
            }
        } else if (!raw.empty()) {
            options.sampleTimesFile = raw;
        }
    }

    return options;
}

std::optional<SimulationOptions> compileSimulationOptions(
    const ast::Action& action) {
    const auto name = [&]() {
        std::string value = action.name;
        std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        return value;
    }();

    const auto methodArgument = action.arguments.find("method");
    std::string method = methodArgument == action.arguments.end()
        ? "ode"
        : unquoteActionValue(methodArgument->second);
    std::transform(method.begin(), method.end(), method.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });

    const bool deterministic = name == "simulate_ode" ||
        (name == "simulate" && (method.empty() || method == "ode" ||
                                 method == "cvode" || method == "euler" ||
                                 method == "rk4"));
    const bool stochastic = name == "simulate_ssa" ||
        (name == "simulate" && method == "ssa");
    if (!deterministic && !stochastic) {
        return std::nullopt;
    }

    auto options = compileSimulationOptions(action.arguments);
    if (!options.method.has_value()) {
        if (name == "simulate_ode") options.method = "cvode";
        else if (name == "simulate_ssa") options.method = "ssa";
        else options.method = method.empty() ? "ode" : method;
    }
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
    std::string actionName = action.name;
    std::transform(actionName.begin(), actionName.end(), actionName.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (actionName == "setparameter") {
        compiled.setParameterOptions = compileSetParameterOptions(action.arguments);
    } else if (actionName == "setconcentration") {
        compiled.setConcentrationOptions = compileSetConcentrationOptions(action.arguments);
    } else if (actionName == "addconcentration" || actionName == "add_concentration") {
        compiled.addConcentrationOptions = compileAddConcentrationOptions(action.arguments);
    } else if (actionName == "saveparameters" || actionName == "save_parameters") {
        compiled.saveParametersOptions = compileSaveParametersOptions(action.arguments);
    } else if (actionName == "resetparameters" || actionName == "reset_parameters") {
        compiled.resetParametersOptions = compileResetParametersOptions(action.arguments);
    } else if (actionName == "saveconcentrations" || actionName == "save_concentrations") {
        compiled.saveConcentrationsOptions = compileSaveConcentrationsOptions(action.arguments);
    } else if (actionName == "resetconcentrations" || actionName == "reset_concentrations") {
        compiled.resetConcentrationsOptions = compileResetConcentrationsOptions(action.arguments);
    } else if (actionName == "setvolume") {
        compiled.setVolumeOptions = compileSetVolumeOptions(action.arguments);
    } else if (actionName == "setoption") {
        compiled.setOptionOptions = compileSetOptionOptions(action.arguments);
    } else if (actionName == "readfile" || actionName == "runargfile") {
        compiled.argFileOptions = compileArgFileOptions(action.arguments);
    } else if (actionName.rfind("write", 0) == 0) {
        compiled.writeModelOptions = compileWriteModelOptions(action.name, action.arguments);
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
