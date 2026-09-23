#pragma once
#include <map>
#include <string>
#include <vector>
#include "Compartment.hpp"
#include "BarrierPattern.hpp"
#include "EnergyPattern.hpp"
#include "Function.hpp"
#include "GraphTypeRegistry.hpp"
#include "Molecule.hpp"
#include "MoleculeType.hpp"
#include "Observable.hpp"
#include "ParameterList.hpp"
#include "PopulationMap.hpp"
#include "ReactionRule.hpp"
#include "SeedSpecies.hpp"
#include "units/Unit.hpp"

namespace bng {
namespace ast {

struct Action {
    std::string name;
    std::map<std::string, std::string> arguments;
};

class Model {
public:
    Model();
    ~Model();

    void addCompartment(const Compartment& comp);
    void addMolecule(const Molecule& mol);
    void addParameter(Parameter parameter);
    void addAction(Action action);
    void addFunction(Function function);
    void addEnergyPattern(EnergyPattern energyPattern);
    // Barrier patterns are move-only because they own a ReactionRule.
    void addBarrierPattern(BarrierPattern barrierPattern);
    void addObservable(Observable observable);
    void addMoleculeType(MoleculeType moleculeType);
    void addSeedSpecies(SeedSpecies seedSpecies);
    void addReactionRule(ReactionRule reactionRule);
    void addPopulationMap(PopulationMap populationMap);
    void addProtocolAction(Action action);
    void setVersion(std::string version);
    void setSubstanceUnits(std::string units);
    void setModelName(std::string modelName);
    void setOption(std::string key, std::string value);
    void defineUnit(std::string id, std::string expression);
    void setUnitDefault(std::string role, std::string unit);
    void setParameterUnit(std::string parameter, std::string unit);
    void setParameterComment(std::string parameter, std::string comment);
    void setCompartmentUnit(std::string compartment, std::string unit);
    void setSeedUnit(std::size_t index, std::string unit);

    /// Merge all model elements from another model into this one.
    /// Takes a non-const reference because it moves reaction rules and
    /// transfers GraphTypeRegistry ownership to keep PatternGraph pointers valid.
    /// Actions from the other model are NOT merged.
    void merge(Model& other);

    const std::vector<Compartment>& getCompartments() const;
    std::vector<Compartment>& getCompartments();
    const std::vector<Molecule>& getMolecules() const;
    const ParameterList& getParameters() const;
    ParameterList& getParameters();
    const std::vector<Action>& getActions() const;
    std::vector<Action>& getActions();
    const std::vector<Function>& getFunctions() const;
    const std::vector<EnergyPattern>& getEnergyPatterns() const;
    const std::vector<BarrierPattern>& getBarrierPatterns() const;
    std::vector<BarrierPattern>& getBarrierPatterns();
    const std::vector<Observable>& getObservables() const;
    const std::vector<MoleculeType>& getMoleculeTypes() const;
    MoleculeType* findMoleculeType(const std::string& name);
    const MoleculeType* findMoleculeType(const std::string& name) const;
    const std::vector<SeedSpecies>& getSeedSpecies() const;
    const std::vector<ReactionRule>& getReactionRules() const;
    std::vector<ReactionRule>& getReactionRules();
    const std::vector<PopulationMap>& getPopulationMaps() const;
    const std::vector<Action>& getSimulationProtocol() const;
    const std::string& getVersion() const;
    const std::string& getSubstanceUnits() const;
    const std::string& getModelName() const;
    const std::map<std::string, std::string>& getOptions() const;
    const units::UnitSystem& getUnitSystem() const;
    const std::map<std::string, std::string>& getUnitDefaults() const;
    const std::string* findParameterUnit(const std::string& name) const;
    const std::string* findParameterComment(const std::string& name) const;
    const std::string* findCompartmentUnit(const std::string& name) const;
    const std::string* findSeedUnit(std::size_t index) const;
    GraphTypeRegistry& getGraphTypeRegistry();

private:
    std::vector<Compartment> compartments;
    std::vector<Molecule> molecules;
    ParameterList parameters_;
    std::vector<Action> actions_;
    std::vector<Function> functions_;
    std::vector<EnergyPattern> energyPatterns_;
    std::vector<BarrierPattern> barrierPatterns_;
    std::vector<Observable> observables_;
    std::vector<MoleculeType> moleculeTypes_;
    std::vector<SeedSpecies> seedSpecies_;
    std::vector<ReactionRule> reactionRules_;
    std::vector<PopulationMap> populationMaps_;
    std::vector<Action> simulationProtocol_;
    GraphTypeRegistry graphTypeRegistry_;
    std::string version_;
    std::string substanceUnits_;
    std::string modelName_;
    std::map<std::string, std::string> options_;
    units::UnitSystem unitSystem_;
    std::map<std::string, std::string> unitDefaults_;
    std::map<std::string, std::string> parameterUnits_;
    std::map<std::string, std::string> parameterComments_;
    std::map<std::string, std::string> compartmentUnits_;
    std::map<std::size_t, std::string> seedUnits_;
};

} // namespace ast
} // namespace bng
