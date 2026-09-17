#pragma once

#include <cstddef>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "CompiledRule.hpp"
#include "SemanticIds.hpp"
#include "SymbolTable.hpp"
#include "units/Unit.hpp"

namespace bng::ast { class Model; }

namespace bng::compile {

struct ModelMetadata {
    std::string name;
    std::string version;
    std::string substanceUnits;
    std::map<std::string, std::string> options;
    std::map<std::string, std::string> unitDefaults;
    std::vector<units::UnitDefinition> unitDefinitions;
};

struct CompiledParameter {
    ParameterId id;
    std::size_t index = 0;
    std::string name;
    std::string sourceExpression;
    ResolvedExpression expression;
    std::optional<double> constantValue;
    // Compile-time physical-basis value.  Existing consumers continue to use
    // constantValue until a backend conversion context is available.
    std::optional<double> normalizedValue;
    std::optional<units::Unit> declaredUnit;
    std::optional<units::Unit> inferredUnit;
    std::string unitName;
};

struct CompiledComponentType {
    ComponentTypeId id;
    std::string name;
    std::vector<std::string> stateNames;

    std::optional<StateId> resolveState(const std::string& name) const;
};

struct CompiledMoleculeType {
    MoleculeTypeId id;
    std::size_t index = 0;
    std::string name;
    bool population = false;
    std::vector<CompiledComponentType> components;

    const CompiledComponentType* component(ComponentTypeId id) const noexcept;
    const CompiledComponentType* findComponent(const std::string& name) const noexcept;
};

struct CompiledCompartment {
    CompartmentId id;
    std::size_t index = 0;
    std::string name;
    double volume = 1.0;
    int dimension = 3;
    std::string parentName;
    std::optional<CompartmentId> parent;
    std::optional<units::Unit> declaredUnit;
    std::string unitName;
    std::optional<double> normalizedVolume;
};

enum class ObservableKind {
    Molecules,
    Species,
    Unknown,
};

struct CompiledEnergyFactor {
    EnergyPatternId id;
    std::size_t index = 0;
    std::string label;
    std::string sourcePattern;
    std::string structuralFingerprint;
    std::string energyExpression;
    ResolvedExpression expression;
    std::optional<double> evaluatedValue;
    Pattern pattern;
};

struct CompiledFunction {
    FunctionId id;
    std::string name;
    std::vector<std::string> arguments;
    ResolvedExpression expression;
};

struct CompiledObservablePattern {
    std::string source;
    Pattern pattern;
    std::string relation;
    int quantity = 0;
};

struct CompiledObservable {
    ObservableId id;
    std::size_t index = 0;
    std::string name;
    std::string type;
    ObservableKind kind = ObservableKind::Unknown;
    std::vector<std::string> sourcePatterns;
    // Structured observable terms. Stoichiometric comparisons such as R==2
    // are resolved here once so execution backends never reparse observable
    // source strings. `patterns` is retained as a compatibility projection.
    std::vector<CompiledObservablePattern> terms;
    std::vector<Pattern> patterns;
};

struct CompiledSeed {
    SeedSpeciesId id;
    std::size_t index = 0;
    std::string sourcePattern;
    std::string amountExpression;
    ResolvedExpression amount;
    std::optional<double> evaluatedAmount;
    bool constant = false;
    std::string compartment;
    std::optional<CompartmentId> compartmentId;
    std::string structuralFingerprint;
    Pattern pattern;
    std::optional<units::Unit> declaredUnit;
    std::string unitName;
    std::optional<double> normalizedAmount;
};

enum class PopulationMapKind {
    Lumped,
    Function,
    Unknown,
};

struct CompiledPopulationType {
    PopulationTypeId id;
    std::string name;
};

struct CompiledPopulationMap {
    std::size_t index = 0;
    std::string label;
    std::string sourcePattern;
    Pattern pattern;
    std::string populationName;
    std::optional<PopulationTypeId> population;
    std::vector<std::string> populationArguments;
    std::string sourceRate;
    ResolvedExpression rate;

    // Compatibility projection for older consumers that treated the RHS
    // population species as a function. New code must use populationName/rate.
    PopulationMapKind kind = PopulationMapKind::Unknown;
    std::string functionName;
    std::optional<FunctionId> function;
    std::vector<std::string> arguments;
};

// Immutable, backend-independent semantic compilation of ast::Model. This is
// the sole model contract intended for execution backends. It deliberately
// contains no mutable matcher, solver, trajectory, generated-network, or NFsim
// object state.
class CompiledModel {
public:
    explicit CompiledModel(const ast::Model& model);

    const ModelMetadata& metadata() const noexcept { return metadata_; }
    const std::vector<CompiledParameter>& parameters() const noexcept { return parameters_; }
    const std::vector<CompiledMoleculeType>& moleculeTypes() const noexcept { return moleculeTypes_; }
    const std::vector<CompiledCompartment>& compartments() const noexcept { return compartments_; }
    const std::vector<CompiledRule>& rules() const noexcept { return rules_; }
    const std::vector<CompiledEnergyFactor>& energyFactors() const noexcept { return energyFactors_; }
    const std::vector<CompiledFunction>& functions() const noexcept { return functions_; }
    const std::vector<CompiledObservable>& observables() const noexcept { return observables_; }
    const std::vector<CompiledSeed>& seeds() const noexcept { return seeds_; }
    const std::vector<CompiledPopulationType>& populationTypes() const noexcept { return populationTypes_; }
    const std::vector<CompiledPopulationMap>& populationMaps() const noexcept { return populationMaps_; }

    std::size_t energyPatternCount() const noexcept { return energyFactors_.size(); }
    const FeatureSet& features() const noexcept { return features_; }
    const SymbolTable& symbols() const noexcept { return symbols_; }
    const std::vector<Diagnostic>& diagnostics() const noexcept { return diagnostics_; }
    bool valid() const noexcept;

    const CompiledParameter* parameter(ParameterId id) const noexcept;
    const CompiledMoleculeType* moleculeType(MoleculeTypeId id) const noexcept;
    const CompiledComponentType* component(ComponentTypeId id) const noexcept;
    const std::string* stateName(StateId id) const noexcept;
    const CompiledCompartment* compartment(CompartmentId id) const noexcept;
    const CompiledFunction* function(FunctionId id) const noexcept;
    const CompiledObservable* observable(ObservableId id) const noexcept;

private:
    ModelMetadata metadata_;
    FeatureSet features_;
    SymbolTable symbols_;
    std::vector<Diagnostic> diagnostics_;
    std::vector<CompiledParameter> parameters_;
    std::vector<CompiledMoleculeType> moleculeTypes_;
    std::vector<CompiledCompartment> compartments_;
    std::vector<CompiledRule> rules_;
    std::vector<CompiledFunction> functions_;
    std::vector<CompiledEnergyFactor> energyFactors_;
    std::vector<CompiledObservable> observables_;
    std::vector<CompiledSeed> seeds_;
    std::vector<CompiledPopulationType> populationTypes_;
    std::vector<CompiledPopulationMap> populationMaps_;
};

} // namespace bng::compile
