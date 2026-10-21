#include "Capabilities.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
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

std::optional<std::string> nonsecondTimeBasisRejection(const CompiledModel& model) {
    const auto declaredTime = model.metadata().unitDefaults.find("timeUnits");
    if (declaredTime == model.metadata().unitDefaults.end()) return std::nullopt;
    const auto resolved = model.metadata().resolvedUnitReferences.find(declaredTime->second);
    units::UnitSystem unitSystem;
    const auto second = unitSystem.parse("second");
    if (resolved == model.metadata().resolvedUnitReferences.end() || !second)
        return "the declared time basis cannot be resolved for NFsim's second clock";
    const auto conversion = units::conversionFactor(resolved->second.unit, *second.unit);
    if (!conversion || !conversion.factor.has_value() ||
        !std::isfinite(*conversion.factor) || *conversion.factor != 1.0)
        return "NFsim physical rates require a declared time basis equal to seconds";
    return std::nullopt;
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

    for (const auto& seed : model.seeds()) {
        if (seed.declaredUnit.has_value())
            return "unit-bearing seed species amounts are unsupported; seeds must be item counts";
    }

    if (const auto rejection = nonsecondTimeBasisRejection(model)) return rejection;

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

    bool foundPhysicalRate = false;
    for (const auto& rule : model.rules()) {
        if (rule.isBidirectional() || rule.reverse().has_value())
            return "bidirectional rules have multiple directions outside the supported subset";
        const auto& direction = rule.forward();
        if (!direction.transformationsComplete || !direction.rateLaw.has_value() ||
            direction.rateLaw->kind != RateLawKind::Expression)
            return "only complete elementary expression rate laws are supported";

        const auto& rate = *direction.rateLaw;
        if (!rate.unit.has_value())
            return "every rate in a unit-bearing NFsim model must have a typed physical unit";
        if (!rate.fullyResolved() || rate.dependencies().requiresRuntimeEvaluation())
            return "dynamic or unresolved elementary rate expressions are unsupported";
        const auto& resolvedRate = rate.resolvedExpression();
        if (resolvedRate.kind == ResolvedExpressionKind::ParameterRef) {
            if (!resolvedRate.symbol.has_value())
                return "physical rates require a direct numeric parameter or literal";
            const auto* parameter = model.parameter(
                ParameterId::fromDenseIndex(resolvedRate.symbol->index));
            if (parameter == nullptr ||
                parameter->expression.kind != ResolvedExpressionKind::Number)
                return "physical rates cannot use compound parameter expressions or aliases";
        } else if (resolvedRate.kind != ResolvedExpressionKind::Number) {
            return "physical rates require a direct numeric parameter or literal";
        }

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
            if (parameter == nullptr || !parameter->constantValue.has_value() ||
                !std::isfinite(*parameter->constantValue))
                return "physical rates may depend only on finite constant parameters";
        }

        // The conversion context is the compartment the rate acts in: the
        // reactant compartment for a reactant-bearing direction, the product
        // compartment for a zero-order direction.  The molecularity is the
        // number of reactant molecules the count propensity multiplies.
        std::optional<CompartmentId> contextCompartmentId;
        std::size_t molecularity = 0;
        if (!direction.reactantPatterns.empty()) {
            for (const auto& pattern : direction.reactantPatterns) {
                if (pattern.molecules().size() != 1)
                    return "physical rates require single-molecule reactant patterns";
                ++molecularity;
                for (const auto& molecule : pattern.molecules()) {
                    auto compartmentId = molecule.compartmentId;
                    if (!compartmentId.has_value()) compartmentId = pattern.compartmentId();
                    if (!compartmentId.has_value())
                        return "physical rates require one explicit declared 3D compartment";
                    if (contextCompartmentId.has_value() &&
                        *contextCompartmentId != *compartmentId)
                        return "physical rates in multiple compartments are ambiguous";
                    contextCompartmentId = *compartmentId;
                }
            }
            if (!contextCompartmentId.has_value())
                return "physical rates require at least one reactant compartment";
        } else {
            std::size_t productMoleculeCount = 0;
            for (const auto& pattern : direction.productPatterns) {
                for (const auto& molecule : pattern.molecules()) {
                    ++productMoleculeCount;
                    auto compartmentId = molecule.compartmentId;
                    if (!compartmentId.has_value()) compartmentId = pattern.compartmentId();
                    if (!compartmentId.has_value())
                        return "zero-order products require one explicit declared 3D compartment";
                    if (contextCompartmentId.has_value() &&
                        *contextCompartmentId != *compartmentId)
                        return "zero-order products in multiple compartments are ambiguous";
                    contextCompartmentId = *compartmentId;
                }
            }
            if (productMoleculeCount == 0 || !contextCompartmentId.has_value())
                return "zero-order physical rates require at least one product molecule";
        }

        const auto* compartment = model.compartment(*contextCompartmentId);
        if (compartment == nullptr || compartment->dimension != 3 ||
            compartment->volumeTimeDependent ||
            !std::isfinite(compartment->volume) || compartment->volume <= 0.0 ||
            !compartment->declaredUnit.has_value() ||
            compartment->declaredUnit->dimension.length != 3 ||
            compartment->declaredUnit->dimension.substance != 0 ||
            compartment->declaredUnit->dimension.time != 0)
            return "physical rates require a positive static declared 3D volume with volume units";

        auto context = baseContext;
        context.compartmentVolume = compartment->volume;
        context.volumeUnit = compartment->declaredUnit;
        const auto factor = units::stochasticRateFactor(
            *rate.unit, molecularity, context);
        if (!factor || !factor.factor.has_value() || !std::isfinite(*factor.factor))
            return "physical rate unit cannot be converted to a count rate: " + factor.error;
        double authoredRate = resolvedRate.numberValue;
        if (resolvedRate.kind == ResolvedExpressionKind::ParameterRef) {
            const auto* parameter = model.parameter(
                ParameterId::fromDenseIndex(resolvedRate.symbol->index));
            if (parameter == nullptr || !parameter->constantValue.has_value())
                return "physical rates require a finite direct parameter value";
            authoredRate = *parameter->constantValue;
        }
        const double countRate = authoredRate * *factor.factor;
        if (!std::isfinite(countRate) || countRate < 0.0)
            return "converted physical count rate must be finite and non-negative";
        foundPhysicalRate = true;
    }

    if (!foundPhysicalRate)
        return "no static elementary physical rate is present";
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
        // NFsim cannot execute a population map.  The hybrid model generator
        // lowers a population map into a hybrid BNGL model, but no backend
        // executes the population/particle refinement, so the diagnostic must
        // not send the user to a backend that does not exist.
        addUnsupported(report, Feature::PopulationMaps, "NFsim",
                       "population maps; NFsim executes particle models only. "
                       "A population map is stored and can be lowered into a "
                       "hybrid model by generate_hybrid_model, but the "
                       "population/particle execution refinement is not "
                       "implemented");
    }
    return report;
}

} // namespace bng::compile
