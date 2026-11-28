#include "Capabilities.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <limits>
#include <utility>
#include <unordered_set>

#include "CompiledModel.hpp"
#include "CompiledRateLaw.hpp"
#include "ast/Expression.hpp"
#include "ast/Model.hpp"
#include "energy/DrivenEnergy.hpp"

namespace bng::compile {

namespace {

void addUnsupported(CapabilityReport& report, Feature feature,
                    const std::string& backend, const std::string& detail) {
    report.set(feature, CapabilityState::Unsupported);
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::UnsupportedFeature;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::BackendCapability;
    diagnostic.entity = backend;
    diagnostic.message = backend + " cannot execute " + detail;
    report.addDiagnostic(std::move(diagnostic));
}

bool isIntegerState(const std::string& value) {
    if (value.empty()) return false;
    const auto first = value.front() == '-' || value.front() == '+' ? 1u : 0u;
    if (first == value.size()) return false;
    return std::all_of(value.begin() + first, value.end(), [](unsigned char c) {
        return std::isdigit(c) != 0;
    });
}

bool containsTableFunction(const ast::Expression& expression) {
    if (expression.kind() == ast::ExpressionKind::TableFunction) return true;
    return std::any_of(expression.args().begin(), expression.args().end(), [](const auto& arg) {
        return containsTableFunction(arg);
    });
}

void inspectExpression(const ast::Expression& expression, FeatureSet& features) {
    if (containsTableFunction(expression)) features.add(Feature::TableFunctions);
}

// Matches the spelling accepted elsewhere in the pipeline (NetWriter's
// parseArrhenius and the NFsim adapters both accept either case).
bool isArrheniusRateLaw(const ast::Expression& expression) {
    if (expression.kind() != ast::ExpressionKind::Function) return false;
    std::string name = expression.name();
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return name == "arrhenius";
}

bool expressionDependsOnTime(const CompiledModel& model,
                             const ResolvedExpression& expression,
                             std::unordered_set<std::size_t>& activeParameters,
                             std::unordered_set<std::size_t>& activeFunctions) {
    if (expression.kind == ResolvedExpressionKind::TimeRef ||
        (expression.kind == ResolvedExpressionKind::BuiltinCall &&
         expression.builtin == BuiltinFunction::Time) ||
        expression.kind == ResolvedExpressionKind::Unresolved)
        return true;
    if (expression.kind == ResolvedExpressionKind::ParameterRef) {
        if (!expression.symbol.has_value()) return true;
        const auto index = expression.symbol->index;
        const auto* parameter = model.parameter(ParameterId::fromDenseIndex(index));
        if (parameter == nullptr || !activeParameters.insert(index).second) return true;
        const bool dependent = expressionDependsOnTime(
            model, parameter->expression, activeParameters, activeFunctions);
        activeParameters.erase(index);
        return dependent;
    }
    if (expression.kind == ResolvedExpressionKind::FunctionRef) {
        if (!expression.symbol.has_value() || !expression.arguments.empty()) return true;
        const auto index = expression.symbol->index;
        const auto* function = model.function(FunctionId::fromDenseIndex(index));
        if (function == nullptr || !function->arguments.empty() ||
            !activeFunctions.insert(index).second)
            return true;
        const bool dependent = expressionDependsOnTime(
            model, function->expression, activeParameters, activeFunctions);
        activeFunctions.erase(index);
        return dependent;
    }
    return std::any_of(expression.arguments.begin(), expression.arguments.end(),
                       [&](const auto& argument) {
                           return expressionDependsOnTime(
                               model, argument, activeParameters, activeFunctions);
                       });
}

std::optional<std::string> timeDependentParameterReference(
    const CompiledModel& model,
    const ResolvedExpression& expression,
    std::unordered_set<std::size_t>& activeFunctions) {
    if (expression.kind == ResolvedExpressionKind::ParameterRef) {
        if (!expression.symbol.has_value()) return std::nullopt;
        const auto* parameter = model.parameter(
            ParameterId::fromDenseIndex(expression.symbol->index));
        if (parameter != nullptr && parameter->timeDependent)
            return parameter->name;
        return std::nullopt;
    }
    if (expression.kind == ResolvedExpressionKind::FunctionRef &&
        expression.symbol.has_value()) {
        const auto index = expression.symbol->index;
        const auto* function = model.function(FunctionId::fromDenseIndex(index));
        if (function == nullptr || !activeFunctions.insert(index).second)
            return std::nullopt;
        const auto name = timeDependentParameterReference(
            model, function->expression, activeFunctions);
        activeFunctions.erase(index);
        if (name.has_value()) return name;
    }
    for (const auto& argument : expression.arguments) {
        if (const auto name = timeDependentParameterReference(
                model, argument, activeFunctions))
            return name;
    }
    return std::nullopt;
}

std::optional<std::string> invalidTimeBasisRejection(const CompiledModel& model) {
    const auto declaredTime = model.metadata().unitDefaults.find("timeUnits");
    if (declaredTime == model.metadata().unitDefaults.end()) return std::nullopt;
    const auto resolved = model.metadata().resolvedUnitReferences.find(declaredTime->second);
    units::UnitSystem unitSystem;
    const auto second = unitSystem.parse("second");
    if (resolved == model.metadata().resolvedUnitReferences.end() || !second)
        return "the declared time basis cannot be resolved for NFsim's second clock";
    const auto conversion = units::conversionFactor(resolved->second.unit, *second.unit);
    if (!conversion || !conversion.factor.has_value() ||
        !std::isfinite(*conversion.factor) || *conversion.factor <= 0.0)
        return "the declared time basis cannot be converted to seconds";
    return std::nullopt;
}

std::optional<double> evaluateStaticRateExpression(
    const CompiledModel& model,
    const ResolvedExpression& expression) {
    using Kind = ResolvedExpressionKind;
    switch (expression.kind) {
    case Kind::Number:
        return std::isfinite(expression.numberValue)
                   ? std::optional<double>(expression.numberValue)
                   : std::nullopt;
    case Kind::ParameterRef: {
        if (!expression.symbol.has_value()) return std::nullopt;
        const auto* parameter = model.parameter(
            ParameterId::fromDenseIndex(expression.symbol->index));
        if (parameter == nullptr || parameter->timeDependent ||
            !parameter->constantValue.has_value() ||
            !std::isfinite(*parameter->constantValue))
            return std::nullopt;
        return *parameter->constantValue;
    }
    case Kind::Unary: {
        if (!expression.unaryOp.has_value() || expression.arguments.size() != 1)
            return std::nullopt;
        const auto value = evaluateStaticRateExpression(model, expression.arguments.front());
        if (!value.has_value()) return std::nullopt;
        switch (*expression.unaryOp) {
        case UnaryOp::Plus: return *value;
        case UnaryOp::Negate: return -*value;
        case UnaryOp::LogicalNot: return *value == 0.0 ? 1.0 : 0.0;
        case UnaryOp::Unknown: return std::nullopt;
        }
        return std::nullopt;
    }
    case Kind::Binary: {
        if (!expression.binaryOp.has_value() || expression.arguments.size() != 2)
            return std::nullopt;
        const auto lhs = evaluateStaticRateExpression(model, expression.arguments[0]);
        const auto rhs = evaluateStaticRateExpression(model, expression.arguments[1]);
        if (!lhs.has_value() || !rhs.has_value()) return std::nullopt;
        double out = 0.0;
        switch (*expression.binaryOp) {
        case BinaryOp::Add: out = *lhs + *rhs; break;
        case BinaryOp::Subtract: out = *lhs - *rhs; break;
        case BinaryOp::Multiply: out = *lhs * *rhs; break;
        case BinaryOp::Divide:
            if (*rhs == 0.0) return std::nullopt;
            out = *lhs / *rhs;
            break;
        case BinaryOp::Modulo:
            if (*rhs == 0.0) return std::nullopt;
            out = std::fmod(*lhs, *rhs);
            break;
        case BinaryOp::Power: out = std::pow(*lhs, *rhs); break;
        case BinaryOp::Less: out = *lhs < *rhs ? 1.0 : 0.0; break;
        case BinaryOp::LessEqual: out = *lhs <= *rhs ? 1.0 : 0.0; break;
        case BinaryOp::Greater: out = *lhs > *rhs ? 1.0 : 0.0; break;
        case BinaryOp::GreaterEqual: out = *lhs >= *rhs ? 1.0 : 0.0; break;
        case BinaryOp::Equal: out = *lhs == *rhs ? 1.0 : 0.0; break;
        case BinaryOp::NotEqual: out = *lhs != *rhs ? 1.0 : 0.0; break;
        case BinaryOp::LogicalAnd: out = (*lhs != 0.0 && *rhs != 0.0) ? 1.0 : 0.0; break;
        case BinaryOp::LogicalOr: out = (*lhs != 0.0 || *rhs != 0.0) ? 1.0 : 0.0; break;
        case BinaryOp::LogicalXor: out = ((*lhs != 0.0) != (*rhs != 0.0)) ? 1.0 : 0.0; break;
        case BinaryOp::Unknown: return std::nullopt;
        }
        return std::isfinite(out) ? std::optional<double>(out) : std::nullopt;
    }
    case Kind::BuiltinCall: {
        if (!expression.builtin.has_value()) return std::nullopt;
        std::vector<double> args;
        args.reserve(expression.arguments.size());
        for (const auto& argument : expression.arguments) {
            const auto value = evaluateStaticRateExpression(model, argument);
            if (!value.has_value()) return std::nullopt;
            args.push_back(*value);
        }
        double out = 0.0;
        if (*expression.builtin == BuiltinFunction::Pi && args.empty()) {
            out = std::acos(-1.0);
        } else if (*expression.builtin == BuiltinFunction::E && args.empty()) {
            out = std::exp(1.0);
        } else if (args.size() == 1) {
            switch (*expression.builtin) {
            case BuiltinFunction::Abs: out = std::fabs(args[0]); break;
            case BuiltinFunction::Exp: out = std::exp(args[0]); break;
            case BuiltinFunction::Ln: out = std::log(args[0]); break;
            case BuiltinFunction::Log10: out = std::log10(args[0]); break;
            case BuiltinFunction::Log2: out = std::log2(args[0]); break;
            case BuiltinFunction::Sqrt: out = std::sqrt(args[0]); break;
            case BuiltinFunction::Sin: out = std::sin(args[0]); break;
            case BuiltinFunction::Cos: out = std::cos(args[0]); break;
            case BuiltinFunction::Tan: out = std::tan(args[0]); break;
            case BuiltinFunction::Floor: out = std::floor(args[0]); break;
            case BuiltinFunction::Ceil: out = std::ceil(args[0]); break;
            default: return std::nullopt;
            }
        } else if (*expression.builtin == BuiltinFunction::Min && !args.empty()) {
            out = *std::min_element(args.begin(), args.end());
        } else if (*expression.builtin == BuiltinFunction::Max && !args.empty()) {
            out = *std::max_element(args.begin(), args.end());
        } else if (*expression.builtin == BuiltinFunction::If && args.size() == 3) {
            out = args[0] != 0.0 ? args[1] : args[2];
        } else {
            return std::nullopt;
        }
        return std::isfinite(out) ? std::optional<double>(out) : std::nullopt;
    }
    default:
        return std::nullopt;
    }
}

units::Unit capabilitiesItemUnit() {
    units::Unit item;
    item.name = "item";
    item.dimension.substance = 1;
    item.baseExponents[units::BaseUnit::Item] = 1;
    return item;
}

} // namespace

std::optional<std::string> nfSimPhysicalUnitBridgeRejection(
    const CompiledModel& model) {
    const bool hasTypedRate = std::any_of(
        model.rules().begin(), model.rules().end(), [](const auto& rule) {
            return (rule.forward().rateLaw.has_value() &&
                    rule.forward().rateLaw->unit.has_value()) ||
                   (rule.reverse().has_value() &&
                    rule.reverse()->rateLaw.has_value() &&
                    rule.reverse()->rateLaw->unit.has_value());
        });
    if (!model.features().contains(Feature::Units) && !hasTypedRate)
        return std::nullopt;
    if (!model.valid())
        return "unit annotations do not form a valid typed model";

    if (const auto rejection = invalidTimeBasisRejection(model)) return rejection;

    units::ConversionContext baseContext;
    if (const auto option = model.metadata().options.find("NumberPerQuantityUnit");
        option != model.metadata().options.end()) {
        try {
            std::size_t consumed = 0;
            const double value = std::stod(option->second, &consumed);
            if (consumed == option->second.size() && std::isfinite(value) && value > 0.0)
                baseContext.numberPerQuantityUnit = value;
        } catch (...) {
            // Conversion will fail closed if this bridge is needed.
        }
    }

    const auto validStaticVolume = [&](CompartmentId id) {
        const auto* compartment = model.compartment(id);
        return compartment != nullptr && compartment->dimension == 3 &&
               !compartment->volumeTimeDependent &&
               std::isfinite(compartment->volume) && compartment->volume > 0.0 &&
               compartment->declaredUnit.has_value() &&
               compartment->declaredUnit->dimension.length == 3 &&
               compartment->declaredUnit->dimension.substance == 0 &&
               compartment->declaredUnit->dimension.time == 0;
    };

    const auto compartmentId = [](const Pattern& pattern,
                                  const PatternMoleculeDescriptor& molecule) {
        return molecule.compartmentId.has_value()
                   ? molecule.compartmentId : pattern.compartmentId();
    };

    bool foundUnitSeed = false;
    for (const auto& seed : model.seeds()) {
        if (!seed.declaredUnit.has_value()) continue;
        if (!seed.evaluatedAmount.has_value() || !std::isfinite(*seed.evaluatedAmount) ||
            *seed.evaluatedAmount < 0.0)
            return "unit-bearing seed species amount must be a finite non-negative constant";
        const auto& unit = *seed.declaredUnit;
        units::ConversionResult converted;
        if (unit.dimension.length == -3 && unit.dimension.time == 0) {
            std::optional<CompartmentId> seedComp = seed.compartmentId;
            if (!seedComp.has_value()) seedComp = seed.pattern.compartmentId();
            if (!seedComp.has_value()) {
                for (const auto& molecule : seed.pattern.molecules()) {
                    if (!molecule.compartmentId.has_value()) continue;
                    if (seedComp.has_value() && *seedComp != *molecule.compartmentId)
                        return "concentration seed species spanning multiple compartments is ambiguous";
                    seedComp = molecule.compartmentId;
                }
            }
            if (!seedComp.has_value() || !validStaticVolume(*seedComp))
                return "concentration seed species requires a positive static declared 3D compartment";
            const auto* comp = model.compartment(*seedComp);
            converted = units::concentrationToItemAmount(
                *seed.evaluatedAmount, unit, comp->volume, *comp->declaredUnit, baseContext);
        } else if (unit.dimension.length == 0 && unit.dimension.time == 0 &&
                   unit.dimension.substance == 1) {
            converted = units::convertValue(
                *seed.evaluatedAmount, unit, capabilitiesItemUnit(), baseContext);
        } else {
            return "unit-bearing seed species must have substance amount or concentration units";
        }
        if (!converted || !converted.factor.has_value() ||
            !std::isfinite(*converted.factor) || *converted.factor < 0.0 ||
            std::floor(*converted.factor + 0.5) >
                static_cast<double>(std::numeric_limits<int>::max())) {
            return "unit-bearing seed species amount cannot be converted to an item count: " +
                   converted.error;
        }
        foundUnitSeed = true;
    }

    bool foundPhysicalRate = false;
    const auto checkDirection = [&](const CompiledRuleDirection& direction)
        -> std::optional<std::string> {
        const auto molecularity = direction.reactantPatterns.size();
        const bool zeroOrder = molecularity == 0;

        for (const auto& pattern : direction.reactantPatterns) {
            for (const auto& molecule : pattern.molecules()) {
                if (!molecule.moleculeTypeId.has_value())
                    return "physical rates require resolved molecule types";
                const auto* type = model.moleculeType(*molecule.moleculeTypeId);
                if (type == nullptr || type->population)
                    return "physical rates require item-count molecule reactants";
            }
        }
        for (const auto& pattern : direction.productPatterns) {
            for (const auto& molecule : pattern.molecules()) {
                if (!molecule.moleculeTypeId.has_value())
                    return "physical rates require resolved molecule types";
                const auto* type = model.moleculeType(*molecule.moleculeTypeId);
                if (type == nullptr || type->population)
                    return "physical rates require item-count molecule products";
            }
        }

        if (!direction.transformationsComplete || !direction.rateLaw.has_value() ||
            direction.rateLaw->kind != RateLawKind::Expression)
            return "only complete elementary expression rate laws are supported";

        const auto& rate = *direction.rateLaw;
        if (!rate.unit.has_value())
            return "every rate in a unit-bearing NFsim model must have a typed physical unit";
        if (!rate.fullyResolved() || rate.dependencies().requiresRuntimeEvaluation())
            return "dynamic or unresolved elementary rate expressions are unsupported";

        const auto& resolvedRate = rate.resolvedExpression();
        std::unordered_set<std::size_t> activeParameters;
        std::unordered_set<std::size_t> activeFunctions;
        if (expressionDependsOnTime(model, resolvedRate, activeParameters,
                                    activeFunctions))
            return "physical rates may not depend on time-dependent parameters";

        for (const auto& reference : rate.references()) {
            if (reference.kind != SymbolKind::Parameter)
                return "physical rates may depend only on constant parameters";
            const auto* parameter = model.parameter(
                ParameterId::fromDenseIndex(reference.index));
            if (parameter == nullptr || parameter->timeDependent ||
                !parameter->constantValue.has_value() ||
                !std::isfinite(*parameter->constantValue))
                return "physical rates may depend only on finite constant parameters";
        }

        const auto authoredRate = evaluateStaticRateExpression(model, resolvedRate);
        if (!authoredRate.has_value() || !std::isfinite(*authoredRate) ||
            *authoredRate < 0.0)
            return "physical rates require a finite non-negative constant expression";

        auto context = baseContext;
        if (zeroOrder) {
            std::optional<CompartmentId> productCompartmentId;
            std::size_t productMoleculeCount = 0;
            for (const auto& pattern : direction.productPatterns) {
                for (const auto& molecule : pattern.molecules()) {
                    ++productMoleculeCount;
                    auto compId = compartmentId(pattern, molecule);
                    if (!compId.has_value())
                        return "zero-order products require one explicit declared 3D compartment";
                    if (productCompartmentId.has_value() &&
                        *productCompartmentId != *compId)
                        return "zero-order products in multiple compartments are ambiguous";
                    productCompartmentId = *compId;
                }
            }
            if (productMoleculeCount == 0 || !productCompartmentId.has_value())
                return "zero-order physical rates require at least one product molecule";
            if (!validStaticVolume(*productCompartmentId))
                return "zero-order products require a positive static declared 3D volume with volume units";

            const auto* compartment = model.compartment(*productCompartmentId);
            context.compartmentVolume = compartment->volume;
            context.volumeUnit = compartment->declaredUnit;
        } else if (molecularity == 1) {
            for (const auto& pattern : direction.reactantPatterns) {
                for (const auto& molecule : pattern.molecules()) {
                    const auto compId = compartmentId(pattern, molecule);
                    if (!model.compartments().empty() && !compId.has_value())
                        return "unimolecular physical rates require explicit compartments when compartments are declared";
                    if (compId.has_value() && !validStaticVolume(*compId))
                        return "unimolecular physical rates require a positive static declared 3D compartment";
                }
            }
            for (const auto& pattern : direction.productPatterns) {
                for (const auto& molecule : pattern.molecules()) {
                    const auto compId = compartmentId(pattern, molecule);
                    if (!model.compartments().empty() && !compId.has_value())
                        return "unimolecular physical rates require explicit compartments when compartments are declared";
                    if (compId.has_value() && !validStaticVolume(*compId))
                        return "unimolecular physical rates require a positive static declared 3D compartment for products";
                }
            }
        } else {
            std::optional<CompartmentId> sharedReactantCompartment;
            for (const auto& pattern : direction.reactantPatterns) {
                for (const auto& molecule : pattern.molecules()) {
                    const auto compId = compartmentId(pattern, molecule);
                    if (!compId.has_value())
                        return "multi-reactant physical rates require reactants in one explicit declared 3D compartment";
                    if (sharedReactantCompartment.has_value() &&
                        *sharedReactantCompartment != *compId)
                        return "multi-reactant physical rates spanning multiple compartments are ambiguous";
                    sharedReactantCompartment = *compId;
                }
            }
            if (!sharedReactantCompartment.has_value() ||
                !validStaticVolume(*sharedReactantCompartment))
                return "multi-reactant physical rates require a positive static declared 3D compartment";
            for (const auto& pattern : direction.productPatterns) {
                for (const auto& molecule : pattern.molecules()) {
                    const auto compId = compartmentId(pattern, molecule);
                    if (compId.has_value() && !validStaticVolume(*compId))
                        return "multi-reactant physical rates require positive static declared 3D compartments";
                }
            }
            const auto* compartment = model.compartment(*sharedReactantCompartment);
            context.compartmentVolume = compartment->volume;
            context.volumeUnit = compartment->declaredUnit;
        }

        const auto factor = units::stochasticRateFactor(
            *rate.unit, molecularity, context);
        if (!factor || !factor.factor.has_value() || !std::isfinite(*factor.factor))
            return "physical rate unit cannot be converted to a count rate: " + factor.error;
        const double countRate = *authoredRate * *factor.factor;
        if (!std::isfinite(countRate) || countRate < 0.0)
            return "converted physical count rate must be finite and non-negative";
        foundPhysicalRate = true;
        return std::nullopt;
    };

    for (const auto& rule : model.rules()) {
        if (const auto rejection = checkDirection(rule.forward()))
            return rejection;
        if (rule.reverse().has_value()) {
            if (const auto rejection = checkDirection(*rule.reverse()))
                return rejection;
        }
    }

    if (!foundPhysicalRate && !foundUnitSeed)
        return "no supported static elementary physical rate is present";
    return std::nullopt;
}

std::optional<std::string> nfSimTimeDependentRateParameterRejection(
    const CompiledModel& model) {
    const auto checkDirection = [&](const CompiledRule& rule,
                                    const CompiledRuleDirection& direction)
        -> std::optional<std::string> {
        if (!direction.rateLaw.has_value()) return std::nullopt;
        std::unordered_set<std::size_t> activeFunctions;
        const auto parameter = timeDependentParameterReference(
            model, direction.rateLaw->resolvedExpression(), activeFunctions);
        if (!parameter.has_value()) return std::nullopt;
        const std::string rateDescription = direction.rateLaw->unit.has_value()
                                                ? "physical-unit rate" : "rate";
        return "NFsim cannot preserve the " + rateDescription + " for reaction rule '" + rule.name() +
               "': named parameter '" + *parameter +
               "' is time-dependent and would be frozen at t=0";
    };

    for (const auto& rule : model.rules()) {
        if (const auto rejection = checkDirection(rule, rule.forward()))
            return rejection;
        if (rule.reverse().has_value()) {
            if (const auto rejection = checkDirection(rule, *rule.reverse()))
                return rejection;
        }
    }
    return std::nullopt;
}

FeatureSet::FeatureSet(std::initializer_list<Feature> features) {
    for (const auto feature : features) add(feature);
}

std::uint64_t FeatureSet::bit(Feature feature) {
    const auto index = static_cast<unsigned>(feature);
    return index >= static_cast<unsigned>(Feature::Count) ? 0 : (std::uint64_t{1} << index);
}

void FeatureSet::add(Feature feature) {
    mask_ |= bit(feature);
}

bool FeatureSet::contains(Feature feature) const {
    return (mask_ & bit(feature)) != 0;
}

std::vector<Feature> FeatureSet::toVector() const {
    std::vector<Feature> result;
    for (unsigned index = 0; index < static_cast<unsigned>(Feature::Count); ++index) {
        const auto feature = static_cast<Feature>(index);
        if (contains(feature)) result.push_back(feature);
    }
    return result;
}

FeatureSet featuresUsed(const ast::Model& model) {
    FeatureSet features;
    if (!model.getEnergyPatterns().empty()) features.add(Feature::EnergyPatterns);
    if (!model.getBarrierPatterns().empty()) features.add(Feature::BarrierPatterns);
    if (!model.getPopulationMaps().empty()) features.add(Feature::PopulationMaps);
    if (!model.getFunctions().empty()) features.add(Feature::Functions);
    if (!model.getCompartments().empty()) features.add(Feature::Compartments);
    for (const auto& parameter : model.getParameters().all()) {
        if (parameter.hasUnit()) { features.add(Feature::Units); break; }
    }
    if (!features.contains(Feature::Units)) {
        for (const auto& compartment : model.getCompartments()) {
            if (compartment.hasUnit()) { features.add(Feature::Units); break; }
        }
    }
    if (!features.contains(Feature::Units)) {
        for (const auto& seed : model.getSeedSpecies()) {
            if (seed.hasUnit()) { features.add(Feature::Units); break; }
        }
    }
    if (!features.contains(Feature::Units)) {
        for (const auto& definition : model.getUnitSystem().definitions()) {
            if (!definition.builtin) { features.add(Feature::Units); break; }
        }
    }
    if (!features.contains(Feature::Units) && !model.getUnitDefaults().empty()) {
        features.add(Feature::Units);
    }
    if (!model.getActions().empty() || !model.getSimulationProtocol().empty()) {
        features.add(Feature::ProtocolActions);
    }

    for (const auto& moleculeType : model.getMoleculeTypes()) {
        for (const auto& component : moleculeType.getComponents()) {
            if (std::any_of(component.allowedStates.begin(), component.allowedStates.end(), isIntegerState)) {
                features.add(Feature::IntegerStates);
            }
        }
    }

    for (const auto& function : model.getFunctions()) {
        if (!function.getArgs().empty()) features.add(Feature::LocalFunctions);
        inspectExpression(function.getExpression(), features);
    }
    for (const auto& energyPattern : model.getEnergyPatterns()) {
        inspectExpression(energyPattern.getExpression(), features);
    }
    for (const auto& rule : model.getReactionRules()) {
        if (rule.hasScopePrefix()) features.add(Feature::LocalFunctions);
        if (rule.hasDrivingWork()) features.add(Feature::DrivenReservoirs);
        for (const auto& rate : rule.getRates()) inspectExpression(rate, features);
    }
    for (const auto& barrier : model.getBarrierPatterns()) {
        if (barrier.hasExpression()) inspectExpression(barrier.expression(), features);
    }
    return features;
}

void CapabilityReport::set(Feature feature, CapabilityState state) {
    states_[feature] = state;
}

CapabilityState CapabilityReport::state(Feature feature) const {
    const auto found = states_.find(feature);
    return found == states_.end() ? CapabilityState::Unsupported : found->second;
}

bool CapabilityReport::isSupported() const {
    const auto unsupported = std::any_of(states_.begin(), states_.end(), [](const auto& entry) {
        return entry.second == CapabilityState::Unsupported;
    });
    const auto errors = std::any_of(diagnostics_.begin(), diagnostics_.end(), [](const auto& diagnostic) {
        return diagnostic.severity == Severity::Error;
    });
    return !unsupported && !errors;
}

void CapabilityReport::addDiagnostic(Diagnostic diagnostic) {
    diagnostics_.push_back(std::move(diagnostic));
}

CapabilityReport capabilitiesFor(const ast::Model& model, BackendKind backend,
                                 const CompiledModel* compiledModel) {
    CapabilityReport report;
    const auto features = featuresUsed(model);
    std::optional<std::string> unitBridgeRejection;
    std::optional<std::string> timedRateParameterRejection;
    std::optional<CompiledModel> ownedCompiledModel;
    const CompiledModel* semanticModel = compiledModel;
    if (backend == BackendKind::NFsim && semanticModel == nullptr) {
        ownedCompiledModel.emplace(model);
        semanticModel = &*ownedCompiledModel;
    }
    if (backend == BackendKind::NFsim && semanticModel != nullptr) {
        if (features.contains(Feature::Units))
            unitBridgeRejection = nfSimPhysicalUnitBridgeRejection(*semanticModel);
        timedRateParameterRejection =
            nfSimTimeDependentRateParameterRejection(*semanticModel);
    }
    for (const auto feature : features.toVector()) {
        // The native network compiler and the NFsim adapter both have an
        // execution path for the current semantic families.  Population maps
        // are deliberately different: they require HybridModelGenerator and
        // cannot be dropped into an NFcore::System without changing meaning.
        const auto state = feature == Feature::Units && backend == BackendKind::NFsim
                               ? (unitBridgeRejection.has_value()
                                      ? CapabilityState::Unsupported
                                      : CapabilityState::ExactLowering)
                           : feature == Feature::Functions ||
                                   feature == Feature::LocalFunctions ||
                                   feature == Feature::TableFunctions ||
                                   feature == Feature::ProtocolActions
                               ? CapabilityState::CompatibilityOnly
                               : CapabilityState::ExactLowering;
        report.set(feature, state);
    }

    // Barrier patterns and driving reservoirs extend eBNGL beyond canonical
    // NFsim, so no independent oracle exists for them. They stay unsupported
    // at every backend boundary until the gate is explicitly set, and the gate
    // itself is documented as experimental rather than as parity.
    const bool generalEnergy = energy::generalEnergyEnabled();
    if (!generalEnergy) {
        if (features.contains(Feature::BarrierPatterns)) {
            addUnsupported(report, Feature::BarrierPatterns,
                           backend == BackendKind::NFsim ? "NFsim" : "the network compiler",
                           std::string("barrier patterns without ") +
                               energy::generalEnergyGateName() + " set");
        }
        if (features.contains(Feature::DrivenReservoirs)) {
            addUnsupported(report, Feature::DrivenReservoirs,
                           backend == BackendKind::NFsim ? "NFsim" : "the network compiler",
                           std::string("driven_by() reservoir work without ") +
                               energy::generalEnergyGateName() + " set");
        }
    } else {
        // A driving reservoir only has meaning for an Arrhenius rate law: it
        // shifts dG, and a plain rate constant has no dG to shift. Treating it
        // as a no-op would silently discard the user's thermodynamics.
        for (const auto& rule : model.getReactionRules()) {
            if (!rule.hasDrivingWork()) continue;
            const bool arrhenius =
                !rule.getRates().empty() && isArrheniusRateLaw(rule.getRates().front());
            if (!arrhenius) {
                addUnsupported(report, Feature::DrivenReservoirs,
                               backend == BackendKind::NFsim ? "NFsim" : "the network compiler",
                               "driven_by() on a rule whose rate law is not Arrhenius");
                break;
            }
        }
        // A barrier pattern needs energy patterns to be meaningful in the same
        // sense: with no dG in the model there is no Arrhenius expansion for
        // the barrier to modify.
        if (features.contains(Feature::BarrierPatterns) &&
            !features.contains(Feature::EnergyPatterns)) {
            Diagnostic diagnostic;
            diagnostic.code = DiagnosticCode::UnsupportedFeature;
            diagnostic.severity = Severity::Warning;
            diagnostic.category = ValidationCategory::Energy;
            diagnostic.entity = "barrier patterns";
            diagnostic.message =
                "barrier patterns have no effect without energy patterns and an "
                "Arrhenius rate law";
            report.addDiagnostic(std::move(diagnostic));
        }
    }

    if (backend == BackendKind::NFsim && unitBridgeRejection.has_value()) {
        addUnsupported(report, Feature::Units, "NFsim",
                       "physical-unit annotations: " + *unitBridgeRejection);
    }

    if (backend == BackendKind::NFsim && timedRateParameterRejection.has_value()) {
        Diagnostic diagnostic;
        diagnostic.code = DiagnosticCode::UnsupportedFeature;
        diagnostic.severity = Severity::Error;
        diagnostic.category = ValidationCategory::BackendCapability;
        diagnostic.entity = "reaction rates";
        diagnostic.message = *timedRateParameterRejection;
        report.addDiagnostic(std::move(diagnostic));
    }

    if (backend == BackendKind::NFsim &&
        features.contains(Feature::PopulationMaps)) {
        addUnsupported(report, Feature::PopulationMaps, "NFsim",
                       "population maps; use the hybrid population backend");
    }
    return report;
}

} // namespace bng::compile
