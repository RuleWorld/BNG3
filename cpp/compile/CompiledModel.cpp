#include "CompiledModel.hpp"

#include "energy/BarrierCompiler.hpp"

#include <algorithm>
#include <cmath>
#include <set>
#include <cctype>
#include <limits>
#include <stdexcept>
#include <utility>

#include "ast/Model.hpp"
#include "UnitAnalysis.hpp"

namespace bng::compile {

namespace {

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

void addDiagnostic(std::vector<Diagnostic>& diagnostics,
                   ValidationCategory category,
                   const std::string& entity,
                   const std::string& message) {
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = category;
    diagnostic.entity = entity;
    diagnostic.message = message;
    diagnostics.push_back(std::move(diagnostic));
}

ObservableKind observableKind(const std::string& type) {
    const auto value = lower(type);
    if (value == "molecules" || value == "molecule") return ObservableKind::Molecules;
    if (value == "species") return ObservableKind::Species;
    return ObservableKind::Unknown;
}

PopulationMapKind populationMapKind(const std::string& name) {
    const auto value = lower(name);
    if (value == "lumped") return PopulationMapKind::Lumped;
    if (!name.empty()) return PopulationMapKind::Function;
    return PopulationMapKind::Unknown;
}

struct ObservablePatternText {
    std::string pattern;
    std::string relation;
    int quantity = 0;
};

std::vector<units::UnitDefinition> authoredUnitDefinitions(const ast::Model& model) {
    std::vector<units::UnitDefinition> result;
    for (const auto& definition : model.getUnitSystem().definitions()) {
        if (!definition.builtin) result.push_back(definition);
    }
    return result;
}

std::optional<units::Unit> defaultUnit(const ast::Model& model,
                                       const std::string& role) {
    const auto found = model.getUnitDefaults().find(role);
    if (found == model.getUnitDefaults().end()) return std::nullopt;
    const auto parsed = model.getUnitSystem().parse(found->second);
    return parsed ? parsed.unit : std::nullopt;
}

std::optional<ObservablePatternText> splitObservablePattern(
    const std::string& source, std::string& error) {
    ObservablePatternText result;
    result.pattern = source;
    int depth = 0;
    std::size_t relationPos = std::string::npos;
    std::string relation;
    for (std::size_t i = 0; i < source.size(); ++i) {
        const char c = source[i];
        if (c == '(') { ++depth; continue; }
        if (c == ')') { --depth; continue; }
        if (depth != 0) continue;
        if (i + 1 < source.size()) {
            const auto two = source.substr(i, 2);
            if (two == "==" || two == ">=" || two == "<=") {
                relationPos = i; relation = two; break;
            }
        }
        if (c == '>' || c == '<') { relationPos = i; relation.assign(1, c); break; }
    }
    if (depth != 0) { error = "unbalanced parentheses"; return std::nullopt; }
    if (relationPos == std::string::npos) return result;

    auto trim = [](std::string value) {
        const auto first = value.find_first_not_of(" \t\r\n");
        if (first == std::string::npos) return std::string{};
        const auto last = value.find_last_not_of(" \t\r\n");
        return value.substr(first, last - first + 1);
    };
    result.pattern = trim(source.substr(0, relationPos));
    result.relation = relation;
    const auto rhs = trim(source.substr(relationPos + relation.size()));
    if (result.pattern.empty() || rhs.empty()) {
        error = "missing pattern or comparison quantity"; return std::nullopt;
    }
    try {
        std::size_t consumed = 0;
        const long long value = std::stoll(rhs, &consumed, 10);
        if (consumed != rhs.size() || value < std::numeric_limits<int>::min() ||
            value > std::numeric_limits<int>::max()) {
            error = "comparison quantity is not an integer"; return std::nullopt;
        }
        result.quantity = static_cast<int>(value);
    } catch (...) {
        error = "comparison quantity is not an integer"; return std::nullopt;
    }
    // BNGL accepts a bare molecule type in a stoichiometric term (`R==2`).
    // Normalize that spelling to the ordinary empty-site structural pattern.
    if (result.pattern.find('(') == std::string::npos) result.pattern += "()";
    return result;
}

} // namespace

std::optional<StateId> CompiledComponentType::resolveState(const std::string& name) const {
    const auto found = std::find(stateNames.begin(), stateNames.end(), name);
    if (found == stateNames.end()) return std::nullopt;
    return StateId{id, static_cast<std::size_t>(std::distance(stateNames.begin(), found))};
}

const CompiledComponentType* CompiledMoleculeType::component(ComponentTypeId requested) const noexcept {
    if (requested.moleculeType != id || requested.index >= components.size()) return nullptr;
    return &components[requested.index];
}

const CompiledComponentType* CompiledMoleculeType::findComponent(const std::string& requested) const noexcept {
    const auto found = std::find_if(components.begin(), components.end(), [&](const auto& component) {
        return component.name == requested;
    });
    return found == components.end() ? nullptr : &*found;
}

CompiledModel::CompiledModel(const ast::Model& model)
    : metadata_{model.getModelName(), model.getVersion(), model.getSubstanceUnits(),
                model.getOptions(), model.getUnitDefaults(), authoredUnitDefinitions(model)},
      features_(featuresUsed(model)),
      symbols_(SymbolTable::fromModel(model)),
      diagnostics_(symbols_.diagnostics()) {

    const auto unitAnalysis = analyzeUnits(model);
    diagnostics_.insert(diagnostics_.end(), unitAnalysis.diagnostics.begin(),
                        unitAnalysis.diagnostics.end());

    parameters_.reserve(model.getParameters().size());
    for (std::size_t index = 0; index < model.getParameters().all().size(); ++index) {
        const auto& parameter = model.getParameters().all()[index];
        auto expression = CompiledRateLaw::compile(parameter.getExpression(), symbols_);
        diagnostics_.insert(diagnostics_.end(), expression.diagnostics().begin(),
                            expression.diagnostics().end());
        CompiledParameter compiled;
        compiled.id = ParameterId::fromDenseIndex(index);
        compiled.index = index;
        compiled.name = parameter.getName();
        compiled.sourceExpression = parameter.getExpression().toString();
        compiled.expression = expression.resolvedExpression();
        try {
            compiled.constantValue = model.getParameters().evaluate(parameter.getName(), 0.0);
        } catch (const std::exception&) {
            if (parameter.hasValue()) compiled.constantValue = parameter.getValue();
        }
        if (parameter.hasUnit()) {
            compiled.declaredUnit = parameter.getUnit();
            compiled.unitName = parameter.getUnitName();
        }
        const auto inferred = unitAnalysis.inferredParameters.find(parameter.getName());
        if (inferred != unitAnalysis.inferredParameters.end()) {
            compiled.inferredUnit = inferred->second;
            if (compiled.unitName.empty()) compiled.unitName = units::formatUnit(inferred->second);
        }
        const auto& normalizedUnit = compiled.inferredUnit.has_value()
                                         ? compiled.inferredUnit
                                         : compiled.declaredUnit;
        if (compiled.constantValue.has_value() && normalizedUnit.has_value()) {
            const double normalized = *compiled.constantValue * normalizedUnit->factor;
            if (std::isfinite(normalized)) compiled.normalizedValue = normalized;
        }
        parameters_.push_back(std::move(compiled));
    }

    moleculeTypes_.reserve(model.getMoleculeTypes().size());
    for (std::size_t index = 0; index < model.getMoleculeTypes().size(); ++index) {
        const auto& molecule = model.getMoleculeTypes()[index];
        CompiledMoleculeType compiled;
        compiled.id = MoleculeTypeId::fromDenseIndex(index);
        compiled.index = index;
        compiled.name = molecule.getName();
        compiled.population = molecule.isPopulation();
        compiled.components.reserve(molecule.getComponents().size());
        for (std::size_t componentIndex = 0;
             componentIndex < molecule.getComponents().size(); ++componentIndex) {
            const auto& component = molecule.getComponents()[componentIndex];
            compiled.components.push_back(CompiledComponentType{
                ComponentTypeId{compiled.id, componentIndex},
                component.name,
                component.allowedStates});
        }
        moleculeTypes_.push_back(std::move(compiled));
    }

    compartments_.reserve(model.getCompartments().size());
    for (std::size_t index = 0; index < model.getCompartments().size(); ++index) {
        const auto& compartment = model.getCompartments()[index];
        CompiledCompartment compiled;
        compiled.id = CompartmentId::fromDenseIndex(index);
        compiled.index = index;
        compiled.name = compartment.getName();
        compiled.volume = compartment.getVolume();
        compiled.dimension = compartment.getDimension();
        compiled.parentName = compartment.getParent();
        if (compartment.hasUnit()) {
            compiled.declaredUnit = compartment.getUnit();
            compiled.unitName = compartment.getUnitName();
            const double normalized = compiled.volume * compartment.getUnit()->factor;
            if (std::isfinite(normalized)) compiled.normalizedVolume = normalized;
        } else if (unitAnalysis.enabled) {
            if (const auto unit = defaultUnit(model, "volumeUnits")) {
                compiled.declaredUnit = unit;
                compiled.unitName = model.getUnitDefaults().at("volumeUnits");
                const double normalized = compiled.volume * unit->factor;
                if (std::isfinite(normalized)) compiled.normalizedVolume = normalized;
            }
        }
        if (!compiled.parentName.empty()) {
            compiled.parent = symbols_.resolveCompartment(compiled.parentName);
            if (!compiled.parent.has_value()) {
                addDiagnostic(diagnostics_, ValidationCategory::InternalStructure, compiled.name,
                              "unknown parent compartment '" + compiled.parentName + "'");
            }
        }
        compartments_.push_back(std::move(compiled));
    }

    rules_.reserve(model.getReactionRules().size());
    for (std::size_t index = 0; index < model.getReactionRules().size(); ++index) {
        auto compiled = CompiledRule::compile(
            model.getReactionRules()[index], model, symbols_, &diagnostics_);
        const auto& sourceRates = model.getReactionRules()[index].getRates();
        const auto annotateRate = [&](CompiledRateLaw& rate,
                                      const ast::Expression& source) {
            const auto inferred = unitAnalysis.inferredExpressions.find(source.toString());
            if (inferred != unitAnalysis.inferredExpressions.end()) {
                rate.unit = inferred->second;
                rate.unitName = units::formatUnit(inferred->second);
            }
        };
        for (std::size_t rateIndex = 0;
             rateIndex < compiled.rateLaws_.size() && rateIndex < sourceRates.size();
             ++rateIndex) {
            annotateRate(compiled.rateLaws_[rateIndex], sourceRates[rateIndex]);
        }
        if (compiled.forward_.rateLaw.has_value() && !sourceRates.empty()) {
            annotateRate(*compiled.forward_.rateLaw, sourceRates.front());
        }
        if (compiled.reverse_.has_value() && compiled.reverse_->rateLaw.has_value() &&
            !sourceRates.empty()) {
            const auto reverseIndex = sourceRates.size() > 1 ? 1u : 0u;
            annotateRate(*compiled.reverse_->rateLaw, sourceRates[reverseIndex]);
        }
        compiled.setId(ReactionRuleId::fromDenseIndex(index));
        rules_.push_back(std::move(compiled));
    }

    functions_.reserve(model.getFunctions().size());
    for (std::size_t index = 0; index < model.getFunctions().size(); ++index) {
        const auto& function = model.getFunctions()[index];
        const auto compiled = CompiledRateLaw::compile(
            function.getExpression(), symbols_, function.getArgs());
        diagnostics_.insert(diagnostics_.end(), compiled.diagnostics().begin(),
                            compiled.diagnostics().end());
        functions_.push_back(CompiledFunction{
            FunctionId::fromDenseIndex(index), function.getName(), function.getArgs(),
            compiled.resolvedExpression()});
    }

    energyFactors_.reserve(model.getEnergyPatterns().size());
    for (std::size_t index = 0; index < model.getEnergyPatterns().size(); ++index) {
        const auto& factor = model.getEnergyPatterns()[index];
        const auto expression = CompiledRateLaw::compile(factor.getExpression(), symbols_);
        diagnostics_.insert(diagnostics_.end(), expression.diagnostics().begin(),
                            expression.diagnostics().end());
        CompiledEnergyFactor compiled;
        compiled.id = EnergyPatternId::fromDenseIndex(index);
        compiled.index = index;
        compiled.label = factor.getLabel();
        compiled.sourcePattern = factor.getPattern();
        compiled.structuralFingerprint = factor.getGraph().fingerprint();
        compiled.energyExpression = factor.getExpression().toString();
        compiled.expression = expression.resolvedExpression();
        // Preserve a pre-evaluated value for static energy factors so backend
        // adapters do not need an AST expression evaluator. Dynamic references
        // remain explicit in the resolved expression and fail closed below.
        const auto isStatic = [&](const auto& self, const ResolvedExpression& node) -> bool {
            using Kind = ResolvedExpressionKind;
            if (node.kind == Kind::TimeRef || node.kind == Kind::ObservableRef ||
                node.kind == Kind::FunctionRef || node.kind == Kind::LocalRef ||
                node.kind == Kind::TableFunction || node.kind == Kind::Unresolved) return false;
            return std::all_of(node.arguments.begin(), node.arguments.end(),
                               [&](const auto& child) { return self(self, child); });
        };
        if (isStatic(isStatic, compiled.expression)) {
            try {
                compiled.evaluatedValue = factor.getExpression().evaluate(
                    [&](const std::string& name) -> double {
                        if (name == "_PI" || name == "_pi") return 3.14159265358979323846;
                        if (name == "_e") return 2.71828182845904523536;
                        if (name == "_Na") return 6.02214076e23;
                        return model.getParameters().evaluate(name, 0.0);
                    }, 0.0);
            } catch (...) {
                compiled.evaluatedValue.reset();
            }
        }
        compiled.pattern = Pattern::fromSpeciesGraph(
            factor.getGraph(), model, symbols_, &diagnostics_);
        energyFactors_.push_back(std::move(compiled));
    }

    // Barrier factors: a transition-state energy plus the canonical reaction
    // center its transition lowers to. A barrier whose transition cannot be
    // reduced to one supported rewrite is recorded with centerResolved=false
    // and a diagnostic, never dropped.
    barrierFactors_.reserve(model.getBarrierPatterns().size());
    for (std::size_t index = 0; index < model.getBarrierPatterns().size(); ++index) {
        const auto& barrier = model.getBarrierPatterns()[index];
        CompiledBarrierFactor compiled;
        compiled.index = index;
        compiled.label = barrier.getLabel();
        compiled.sourceTransition = barrier.toString();

        if (!barrier.hasExpression()) {
            addDiagnostic(diagnostics_, ValidationCategory::Energy, compiled.label,
                          "barrier pattern has no transition-state energy expression");
            barrierFactors_.push_back(std::move(compiled));
            continue;
        }

        const auto expression = CompiledRateLaw::compile(barrier.expression(), symbols_);
        diagnostics_.insert(diagnostics_.end(), expression.diagnostics().begin(),
                            expression.diagnostics().end());
        compiled.energyExpression = barrier.expression().toString();
        compiled.expression = expression.resolvedExpression();

        const auto isStaticBarrier =
            [&](const auto& self, const ResolvedExpression& node) -> bool {
            using Kind = ResolvedExpressionKind;
            if (node.kind == Kind::TimeRef || node.kind == Kind::ObservableRef ||
                node.kind == Kind::FunctionRef || node.kind == Kind::LocalRef ||
                node.kind == Kind::TableFunction || node.kind == Kind::Unresolved) return false;
            return std::all_of(node.arguments.begin(), node.arguments.end(),
                               [&](const auto& child) { return self(self, child); });
        };
        if (isStaticBarrier(isStaticBarrier, compiled.expression)) {
            try {
                compiled.evaluatedValue = barrier.expression().evaluate(
                    [&](const std::string& name) -> double {
                        if (name == "_PI" || name == "_pi") return 3.14159265358979323846;
                        if (name == "_e") return 2.71828182845904523536;
                        if (name == "_Na") return 6.02214076e23;
                        return model.getParameters().evaluate(name, 0.0);
                    }, 0.0);
            } catch (...) {
                compiled.evaluatedValue.reset();
            }
        } else {
            // A time- or observable-dependent transition state would change
            // the rate during a trajectory; that is not implemented and must
            // not be folded to its initial value.
            addDiagnostic(diagnostics_, ValidationCategory::Energy, compiled.label,
                          "barrier pattern energy must be statically evaluable");
        }

        energy::ReactionCenterKey key;
        std::string diagnostic;
        if (energy::compileBarrierCenter(barrier.transition(), key, diagnostic)) {
            compiled.reactionCenter = key;
            compiled.reactionCenterKey = key.toString();
            compiled.centerResolved = true;
        } else {
            addDiagnostic(diagnostics_, ValidationCategory::Energy, compiled.label,
                          "barrier pattern transition is unsupported: " + diagnostic);
        }
        barrierFactors_.push_back(std::move(compiled));
    }

    observables_.reserve(model.getObservables().size());
    for (std::size_t index = 0; index < model.getObservables().size(); ++index) {
        const auto& observable = model.getObservables()[index];
        CompiledObservable compiled;
        compiled.id = ObservableId::fromDenseIndex(index);
        compiled.index = index;
        compiled.name = observable.getName();
        compiled.type = observable.getType();
        compiled.kind = observableKind(compiled.type);
        compiled.sourcePatterns = observable.getPatterns();
        for (const auto& sourcePattern : compiled.sourcePatterns) {
            try {
                std::string splitError;
                const auto parsed = splitObservablePattern(sourcePattern, splitError);
                if (!parsed.has_value()) {
                    addDiagnostic(diagnostics_, ValidationCategory::Patterns, compiled.name,
                                  "invalid observable pattern '" + sourcePattern + "': " +
                                      splitError);
                    continue;
                }
                auto pattern = Pattern::parse(parsed->pattern);
                if (!pattern.resolve(model, symbols_, &diagnostics_)) continue;
                compiled.terms.push_back(CompiledObservablePattern{
                    sourcePattern, pattern, parsed->relation, parsed->quantity});
                compiled.patterns.push_back(std::move(pattern));
            } catch (const std::invalid_argument& error) {
                addDiagnostic(diagnostics_, ValidationCategory::Patterns, compiled.name,
                              "invalid observable pattern '" + sourcePattern + "': " +
                                  error.what());
            }
        }
        observables_.push_back(std::move(compiled));
    }

    seeds_.reserve(model.getSeedSpecies().size());
    for (std::size_t index = 0; index < model.getSeedSpecies().size(); ++index) {
        const auto& seed = model.getSeedSpecies()[index];
        const auto amount = CompiledRateLaw::compile(seed.getAmount(), symbols_);
        diagnostics_.insert(diagnostics_.end(), amount.diagnostics().begin(),
                            amount.diagnostics().end());
        CompiledSeed compiled;
        compiled.id = SeedSpeciesId::fromDenseIndex(index);
        compiled.index = index;
        compiled.sourcePattern = seed.getPattern();
        compiled.amountExpression = seed.getAmount().toString();
        compiled.amount = amount.resolvedExpression();
        compiled.constant = seed.isConstant();
        compiled.compartment = seed.getCompartment();
        if (seed.hasUnit()) {
            compiled.declaredUnit = seed.getUnit();
            compiled.unitName = seed.getUnitName();
        } else if (unitAnalysis.enabled) {
            if (const auto unit = defaultUnit(model, "substanceUnits")) {
                compiled.declaredUnit = unit;
                compiled.unitName = model.getUnitDefaults().at("substanceUnits");
            }
        }
        if (!compiled.compartment.empty()) {
            compiled.compartmentId = symbols_.resolveCompartment(compiled.compartment);
            if (!compiled.compartmentId.has_value()) {
                addDiagnostic(diagnostics_, ValidationCategory::InternalStructure,
                              compiled.sourcePattern,
                              "unknown seed compartment '" + compiled.compartment + "'");
            }
        }
        try {
            compiled.evaluatedAmount = seed.getAmount().evaluate(
                [&](const std::string& name) { return model.getParameters().evaluate(name); });
            if (compiled.declaredUnit.has_value()) {
                const double normalized = *compiled.evaluatedAmount * compiled.declaredUnit->factor;
                if (std::isfinite(normalized)) compiled.normalizedAmount = normalized;
            }
        } catch (const std::exception&) {
            // Dynamic/time/function-dependent amounts are intentionally retained
            // as expressions without pretending they are compile-time constants.
        }
        compiled.structuralFingerprint = seed.getGraph().computeFingerprint();
        compiled.pattern = Pattern::fromSpeciesGraph(
            ast::SpeciesGraph(seed.getGraph(), seed.getCompartment()),
            model, symbols_, &diagnostics_);
        seeds_.push_back(std::move(compiled));
    }

    {
        std::set<std::string> seenPopulationTypes;
        for (const auto& mapping : model.getPopulationMaps()) {
            const auto& name = !mapping.populationName.empty()
                ? mapping.populationName : mapping.populationFunction;
            if (name.empty() || !seenPopulationTypes.insert(name).second) continue;
            CompiledPopulationType type;
            type.name = name;
            if (const auto id = symbols_.resolvePopulationType(name)) type.id = *id;
            populationTypes_.push_back(std::move(type));
        }
    }

    populationMaps_.reserve(model.getPopulationMaps().size());
    for (std::size_t index = 0; index < model.getPopulationMaps().size(); ++index) {
        const auto& mapping = model.getPopulationMaps()[index];
        CompiledPopulationMap compiled;
        compiled.index = index;
        compiled.label = mapping.label;
        compiled.sourcePattern = mapping.patternText;
        compiled.populationName = !mapping.populationName.empty()
            ? mapping.populationName : mapping.populationFunction;
        compiled.population = symbols_.resolvePopulationType(compiled.populationName);
        compiled.populationArguments = !mapping.populationArgs.empty()
            ? mapping.populationArgs : mapping.functionArgs;
        compiled.functionName = compiled.populationName;
        compiled.arguments = compiled.populationArguments;
        compiled.sourceRate = mapping.hasExplicitRate ? mapping.rateText : "0";
        const auto compiledRate = CompiledRateLaw::compile(
            mapping.hasExplicitRate ? mapping.rateExpression : ast::Expression::number(0.0),
            symbols_);
        compiled.rate = compiledRate.resolvedExpression();
        diagnostics_.insert(diagnostics_.end(), compiledRate.diagnostics().begin(),
                            compiledRate.diagnostics().end());
        try {
            compiled.pattern = Pattern::parse(mapping.patternText);
            compiled.pattern.resolve(model, symbols_, &diagnostics_);
        } catch (const std::invalid_argument& error) {
            addDiagnostic(diagnostics_, ValidationCategory::Patterns, compiled.label,
                          "invalid population-map pattern '" + mapping.patternText + "': " +
                              error.what());
        }
        populationMaps_.push_back(std::move(compiled));
    }

}

bool CompiledModel::valid() const noexcept {
    return std::none_of(diagnostics_.begin(), diagnostics_.end(), [](const auto& diagnostic) {
        return diagnostic.severity == Severity::Error;
    });
}

const CompiledParameter* CompiledModel::parameter(ParameterId id) const noexcept {
    return id.valid() && id.value() < parameters_.size() ? &parameters_[id.value()] : nullptr;
}

const CompiledMoleculeType* CompiledModel::moleculeType(MoleculeTypeId id) const noexcept {
    return id.valid() && id.value() < moleculeTypes_.size() ? &moleculeTypes_[id.value()] : nullptr;
}

const CompiledComponentType* CompiledModel::component(ComponentTypeId id) const noexcept {
    const auto* molecule = moleculeType(id.moleculeType);
    return molecule == nullptr ? nullptr : molecule->component(id);
}

const std::string* CompiledModel::stateName(StateId id) const noexcept {
    const auto* componentType = component(id.component);
    if (componentType == nullptr || id.index >= componentType->stateNames.size()) return nullptr;
    return &componentType->stateNames[id.index];
}

const CompiledCompartment* CompiledModel::compartment(CompartmentId id) const noexcept {
    return id.valid() && id.value() < compartments_.size() ? &compartments_[id.value()] : nullptr;
}

const CompiledFunction* CompiledModel::function(FunctionId id) const noexcept {
    return id.valid() && id.value() < functions_.size() ? &functions_[id.value()] : nullptr;
}

const CompiledObservable* CompiledModel::observable(ObservableId id) const noexcept {
    return id.valid() && id.value() < observables_.size() ? &observables_[id.value()] : nullptr;
}

} // namespace bng::compile
