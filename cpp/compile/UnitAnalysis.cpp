#include "UnitAnalysis.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <map>
#include <limits>
#include <set>
#include <stdexcept>
#include <utility>

#include "ast/Model.hpp"

namespace bng::compile {
namespace {

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char character) {
        return static_cast<char>(std::tolower(character));
    });
    return value;
}

std::string stripQuotes(std::string value) {
    if (value.size() >= 2 &&
        ((value.front() == '"' && value.back() == '"') ||
         (value.front() == '\'' && value.back() == '\''))) {
        return value.substr(1, value.size() - 2);
    }
    return value;
}

void addUnitDiagnostic(std::vector<Diagnostic>& diagnostics, Severity severity,
                       const std::string& entity, std::string message) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = severity;
    diagnostic.category = ValidationCategory::Units;
    diagnostic.entity = entity;
    diagnostic.message = std::move(message);
    diagnostics.push_back(std::move(diagnostic));
}

bool hasUnitAnnotations(const ast::Model& model) {
    for (const auto& parameter : model.getParameters().all())
        if (parameter.hasUnit()) return true;
    for (const auto& compartment : model.getCompartments())
        if (compartment.hasUnit()) return true;
    for (const auto& seed : model.getSeedSpecies())
        if (seed.hasUnit()) return true;
    if (!model.getUnitDefaults().empty()) return true;
    return std::any_of(model.getUnitSystem().definitions().begin(),
                       model.getUnitSystem().definitions().end(),
                       [](const auto& definition) { return !definition.builtin; });
}

struct InferredUnit {
    std::optional<units::Unit> unit;
    bool hasKnownOperand = false;
    bool hasUnknownOperand = false;
};

class Analyzer {
public:
    Analyzer(const ast::Model& model, UnitAnalysisResult& result)
        : model_(model), result_(result) {
        const auto found = model_.getOptions().find("NumberPerQuantityUnit");
        if (found != model_.getOptions().end()) {
            try {
                context_.numberPerQuantityUnit =
                    std::stod(stripQuotes(found->second));
            } catch (...) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, "model",
                                  "NumberPerQuantityUnit must be numeric");
            }
        }
    }

    void run() {
        if (result_.mode == UnitMode::Off) {
            if (hasUnitAnnotations(model_)) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, "model",
                                  "unit annotations require units=permissive or units=strict");
            }
            return;
        }

        const std::map<std::string, units::Dimension> defaultDimensions = {
            {"timeUnits", {0, 0, 1}},
            {"substanceUnits", {1, 0, 0}},
            {"volumeUnits", {0, 3, 0}},
            {"areaUnits", {0, 2, 0}},
            {"lengthUnits", {0, 1, 0}},
            {"extentUnits", {1, 0, 0}},
        };
        for (const auto& [role, authored] : model_.getUnitDefaults()) {
            const auto expected = defaultDimensions.find(role);
            const auto parsed = model_.getUnitSystem().parse(authored);
            if (expected != defaultDimensions.end() && parsed &&
                parsed.unit->dimension != expected->second) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, role,
                                  "unit '" + authored + "' has the wrong dimensions for " + role);
            }
        }

        for (const auto& parameter : model_.getParameters().all()) {
            auto inferred = parameterUnit(parameter.getName());
            if (inferred.unit.has_value()) result_.inferredParameters[parameter.getName()] = *inferred.unit;
            if (result_.mode == UnitMode::Strict && inferred.hasUnknownOperand) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, parameter.getName(),
                                  "cannot infer a complete unit expression in strict mode");
            }
        }

        for (const auto& compartment : model_.getCompartments()) {
            if (!compartment.hasUnit()) continue;
            if (compartment.getUnit()->dimension.length != 3) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, compartment.getName(),
                                  "compartment size must have volume dimensions");
            }
        }
        for (const auto& seed : model_.getSeedSpecies()) {
            if (!seed.hasUnit()) continue;
            const auto& dimension = seed.getUnit()->dimension;
            if (dimension.substance == 0) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, seed.getPattern(),
                                  "seed species quantity must have substance dimensions");
            }
        }

        // Elementary BNGL rule rates are concentration-based by convention:
        // an n-th order rate constant has concentration^(1-n)/time units.
        // Accept either mole- or item-based substance units, but reject a
        // known rate whose spatial/time dimensions cannot be reconciled with
        // the rule molecularity.  Built-in nonlinear rate laws remain
        // unknown until their backend-specific contracts are modeled.
        for (const auto& rule : model_.getReactionRules()) {
            const auto molecularity = rule.getReactantPatterns().size();
            const auto expected = expectedRateUnit(molecularity, "mole");
            if (!expected.has_value()) continue;
            for (const auto& rate : rule.getRates()) {
                const auto inferred = expressionUnit(rate, rule.getRuleName());
                if (inferred.unit.has_value()) {
                    result_.inferredExpressions[rate.toString()] = *inferred.unit;
                }
                if (!inferred.unit.has_value()) {
                    if (result_.mode == UnitMode::Strict && inferred.hasUnknownOperand) {
                        addUnitDiagnostic(
                            result_.diagnostics, Severity::Error, rule.getRuleName(),
                            "cannot infer a complete rate unit expression in strict mode");
                    }
                    continue;
                }
                const auto countExpected = expectedRateUnit(molecularity, "item");
                const auto moleConversion = units::conversionFactor(
                    *inferred.unit, *expected, context_);
                const auto itemConversion = countExpected
                    ? units::conversionFactor(*inferred.unit, *countExpected, context_)
                    : units::ConversionResult{std::nullopt, "no item rate basis"};
                if (!units::dimensionallyCompatible(*inferred.unit, *expected) ||
                    (!moleConversion && !itemConversion)) {
                    addUnitDiagnostic(
                        result_.diagnostics, Severity::Error, rule.getRuleName(),
                        "rate expression has unit '" + units::formatUnit(*inferred.unit) +
                        "' but molecularity " + std::to_string(molecularity) +
                        " requires concentration^(1-molecularity)/time");
                }
            }
        }
    }

private:
    const ast::Model& model_;
    UnitAnalysisResult& result_;
    units::ConversionContext context_;
    std::map<std::string, InferredUnit> cache_;
    std::set<std::string> visiting_;

    InferredUnit parameterUnit(const std::string& name) {
        const auto cached = cache_.find(name);
        if (cached != cache_.end()) return cached->second;
        if (!model_.getParameters().contains(name)) return {};
        if (!visiting_.insert(name).second) {
            addUnitDiagnostic(result_.diagnostics, Severity::Error, name,
                              "circular unit dependency detected");
            return {};
        }

        const auto& parameter = model_.getParameters().get(name);
        auto inferred = expressionUnit(parameter.getExpression(), name);
        if (parameter.hasUnit()) {
            const auto declared = *parameter.getUnit();
            if (inferred.unit.has_value() && inferred.hasKnownOperand) {
                const auto conversion = units::conversionFactor(
                    *inferred.unit, declared, context_);
                if (!conversion) {
                    addUnitDiagnostic(result_.diagnostics, Severity::Error, name,
                                      "declared unit '" + parameter.getUnitName() +
                                      "' is incompatible with the inferred expression unit: " +
                                      conversion.error);
                }
            }
            // A bare numeric RHS is a quantity literal in declaration context;
            // its declared unit supplies the missing dimension.
            inferred.unit = declared;
            inferred.hasKnownOperand = true;
            inferred.hasUnknownOperand = false;
        }
        visiting_.erase(name);
        cache_[name] = inferred;
        return inferred;
    }

    std::optional<units::Unit> expectedRateUnit(std::size_t molecularity,
                                                const std::string& substance) const {
        if (molecularity > static_cast<std::size_t>(std::numeric_limits<int>::max() - 1)) {
            return std::nullopt;
        }
        const auto mole = model_.getUnitSystem().parse(substance);
        const auto metre = model_.getUnitSystem().parse("metre");
        const auto second = model_.getUnitSystem().parse("second");
        if (!mole || !metre || !second) return std::nullopt;
        const auto concentration = units::divideUnits(
            *mole.unit, units::powerUnit(*metre.unit, 3));
        const auto exponent = 1 - static_cast<int>(molecularity);
        return units::multiplyUnits(
            units::powerUnit(concentration, exponent),
            units::powerUnit(*second.unit, -1));
    }

    InferredUnit expressionUnit(const ast::Expression& expression, const std::string& entity) {
        using Kind = ast::ExpressionKind;
        if (expression.kind() == Kind::Number) {
            auto dimensionless = model_.getUnitSystem().parse("dimensionless");
            return {dimensionless.unit, false, false};
        }
        if (expression.kind() == Kind::Identifier) {
            const auto& name = expression.name();
            if (model_.getParameters().contains(name)) {
                auto result = parameterUnit(name);
                result.hasKnownOperand = result.unit.has_value();
                return result;
            }
            if (name == "time" || name == "TIME") {
                const auto* selected = model_.getUnitSystem().find("second");
                return {selected == nullptr ? std::optional<units::Unit>{} : *selected, true, false};
            }
            return {std::nullopt, false, true};
        }
        if (expression.kind() == Kind::ObservableRef ||
            expression.kind() == Kind::TableFunction) {
            return {std::nullopt, false, true};
        }
        if (expression.kind() == Kind::Unary) {
            const auto operand = expression.args().empty()
                                     ? InferredUnit {}
                                     : expressionUnit(expression.args().front(), entity);
            if (expression.name() == "!") {
                auto dimensionless = model_.getUnitSystem().parse("dimensionless");
                return {dimensionless.unit, operand.hasKnownOperand, operand.hasUnknownOperand};
            }
            return operand;
        }
        if (expression.kind() == Kind::Binary) return binaryUnit(expression, entity);
        if (expression.kind() == Kind::Function) return functionUnit(expression, entity);
        return {std::nullopt, false, true};
    }

    InferredUnit binaryUnit(const ast::Expression& expression, const std::string& entity) {
        using Kind = ast::ExpressionKind;
        if (expression.args().size() < 2) return {};
        const auto lhs = expressionUnit(expression.args()[0], entity);
        const auto rhs = expressionUnit(expression.args()[1], entity);
        InferredUnit result;
        result.hasKnownOperand = lhs.hasKnownOperand || rhs.hasKnownOperand;
        result.hasUnknownOperand = lhs.hasUnknownOperand || rhs.hasUnknownOperand;
        const auto op = expression.name();
        if (!lhs.unit.has_value() || !rhs.unit.has_value()) return result;

        if (op == "+" || op == "-" || op == "%" || op == "==" || op == "!=" ||
            op == ">" || op == ">=" || op == "<" || op == "<=") {
            if (!units::dimensionallyCompatible(*lhs.unit, *rhs.unit)) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, entity,
                                  "cannot combine '" + units::formatUnit(*lhs.unit) +
                                  "' with '" + units::formatUnit(*rhs.unit) + "' using '" + op + "'");
                return result;
            }
            const auto conversion = units::conversionFactor(*lhs.unit, *rhs.unit, context_);
            if (!conversion) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, entity,
                                  "cannot convert '" + units::formatUnit(*rhs.unit) +
                                  "' to '" + units::formatUnit(*lhs.unit) + "': " +
                                  conversion.error);
                return result;
            }
            if (op == "==" || op == "!=" || op == ">" || op == ">=" || op == "<" || op == "<=") {
                result.unit = model_.getUnitSystem().parse("dimensionless").unit;
            } else {
                result.unit = lhs.unit;
            }
            return result;
        }
        if (op == "*") result.unit = units::multiplyUnits(*lhs.unit, *rhs.unit);
        else if (op == "/") result.unit = units::divideUnits(*lhs.unit, *rhs.unit);
        else if (op == "^") {
            if (!rhs.unit->isDimensionless()) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, entity,
                                  "unit exponent must be dimensionless");
                return result;
            }
            if (expression.args()[1].kind() != Kind::Number) {
                if (!lhs.unit->isDimensionless()) {
                    addUnitDiagnostic(result_.diagnostics, Severity::Error, entity,
                                      "dimensionful powers require an integer literal exponent");
                }
                return result;
            }
            const double exponent = expression.args()[1].numberValue();
            const auto integer = static_cast<int>(exponent);
            if (!std::isfinite(exponent) || exponent != static_cast<double>(integer)) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, entity,
                                  "unit exponents must be signed integers");
                return result;
            }
            result.unit = units::powerUnit(*lhs.unit, integer);
        }
        return result;
    }

    InferredUnit functionUnit(const ast::Expression& expression, const std::string& entity) {
        const auto name = lower(expression.name());
        std::vector<InferredUnit> arguments;
        for (const auto& argument : expression.args()) arguments.push_back(expressionUnit(argument, entity));
        InferredUnit result;
        for (const auto& argument : arguments) {
            result.hasKnownOperand = result.hasKnownOperand || argument.hasKnownOperand;
            result.hasUnknownOperand = result.hasUnknownOperand || argument.hasUnknownOperand;
        }
        const auto dimensionless = model_.getUnitSystem().parse("dimensionless").unit;
        if (name == "abs") {
            if (!arguments.empty()) result.unit = arguments.front().unit;
            return result;
        }
        if (name == "min" || name == "max" || name == "avg" || name == "sum") {
            if (arguments.empty()) return result;
            result.unit = arguments.front().unit;
            for (std::size_t index = 1; index < arguments.size(); ++index) {
                if (result.unit.has_value() && arguments[index].unit.has_value() &&
                    !units::dimensionallyCompatible(*result.unit, *arguments[index].unit)) {
                    addUnitDiagnostic(result_.diagnostics, Severity::Error, entity,
                                      "function '" + name + "' requires compatible argument units");
                } else if (result.unit.has_value() && arguments[index].unit.has_value() &&
                           !units::conversionFactor(*result.unit, *arguments[index].unit,
                                                    context_)) {
                    addUnitDiagnostic(result_.diagnostics, Severity::Error, entity,
                                      "function '" + name +
                                      "' requires convertible argument units");
                }
            }
            return result;
        }
        if (name == "if") {
            if (arguments.size() != 3) return result;
            if (arguments[0].unit.has_value() && !arguments[0].unit->isDimensionless()) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, entity,
                                  "if condition must be dimensionless");
            }
            if (arguments[1].unit.has_value() && arguments[2].unit.has_value() &&
                !units::dimensionallyCompatible(*arguments[1].unit, *arguments[2].unit)) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, entity,
                                  "if branches must have compatible units");
            } else if (arguments[1].unit.has_value() && arguments[2].unit.has_value() &&
                       !units::conversionFactor(*arguments[1].unit, *arguments[2].unit,
                                                context_)) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, entity,
                                  "if branches must have convertible units");
            }
            result.unit = arguments[1].unit;
            return result;
        }
        static const std::set<std::string> dimensionlessFunctions = {
            "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh",
            "asinh", "acosh", "atanh", "exp", "ln", "log10", "log2"};
        if (dimensionlessFunctions.find(name) != dimensionlessFunctions.end()) {
            if (!arguments.empty() && arguments.front().unit.has_value() &&
                !arguments.front().unit->isDimensionless()) {
                addUnitDiagnostic(result_.diagnostics, Severity::Error, entity,
                                  "function '" + name + "' requires a dimensionless argument");
            }
            result.unit = dimensionless;
            return result;
        }
        // sqrt and arbitrary/user-defined functions need richer contracts than
        // the initial unit algebra currently carries.  Unknown functions stay
        // unknown rather than being silently treated as dimensionless.
        result.unit.reset();
        result.hasUnknownOperand = true;
        return result;
    }
};

} // namespace

UnitMode unitMode(const ast::Model& model) {
    const auto found = model.getOptions().find("units");
    if (found == model.getOptions().end()) {
        return hasUnitAnnotations(model) ? UnitMode::Permissive : UnitMode::Off;
    }
    const auto value = lower(stripQuotes(found->second));
    if (value == "off" || value.empty()) return UnitMode::Off;
    if (value == "permissive") return UnitMode::Permissive;
    if (value == "strict") return UnitMode::Strict;
    return UnitMode::Strict;
}

UnitAnalysisResult analyzeUnits(const ast::Model& model) {
    UnitAnalysisResult result;
    result.mode = unitMode(model);
    result.enabled = result.mode != UnitMode::Off || hasUnitAnnotations(model);
    if (result.mode == UnitMode::Strict) {
        const auto found = model.getOptions().find("units");
        if (found != model.getOptions().end() &&
            lower(stripQuotes(found->second)) != "strict") {
            addUnitDiagnostic(result.diagnostics, Severity::Error, "model",
                              "units option must be off, permissive, or strict");
        }
    }
    Analyzer analyzer(model, result);
    analyzer.run();
    return result;
}

} // namespace bng::compile
