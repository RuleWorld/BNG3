#include "Model.hpp"

#include "ModelOptions.hpp"

#include <cmath>
#include <iostream>
#include <utility>
#include <stdexcept>

namespace bng {
namespace ast {

Model::Model() = default;
Model::~Model() = default;

void Model::addCompartment(const Compartment& comp) {
    compartments.push_back(comp);
}

void Model::addMolecule(const Molecule& mol) {
    molecules.push_back(mol);
}

void Model::addParameter(Parameter parameter) {
    parameters_.add(std::move(parameter));
}

void Model::addAction(Action action) {
    actions_.push_back(std::move(action));
}

void Model::addFunction(Function function) {
    functions_.push_back(std::move(function));
}

void Model::addEnergyPattern(EnergyPattern energyPattern) {
    energyPatterns_.push_back(std::move(energyPattern));
}

void Model::addBarrierPattern(BarrierPattern barrierPattern) {
    barrierPatterns_.push_back(std::move(barrierPattern));
}

void Model::addObservable(Observable observable) {
    observables_.push_back(std::move(observable));
}

void Model::addMoleculeType(MoleculeType moleculeType) {
    moleculeTypes_.push_back(std::move(moleculeType));
}

void Model::addSeedSpecies(SeedSpecies seedSpecies) {
    seedSpecies_.push_back(std::move(seedSpecies));
}

void Model::addReactionRule(ReactionRule reactionRule) {
    reactionRules_.push_back(std::move(reactionRule));
}

void Model::addPopulationMap(PopulationMap populationMap) {
    populationMaps_.push_back(std::move(populationMap));
}

void Model::addProtocolAction(Action action) {
    simulationProtocol_.push_back(std::move(action));
}

void Model::setVersion(std::string version) {
    version_ = std::move(version);
}

void Model::setSubstanceUnits(std::string units) {
    substanceUnits_ = std::move(units);
}

void Model::setModelName(std::string modelName) {
    modelName_ = std::move(modelName);
}

void Model::setOption(std::string key, std::string value) {
    // Single validation seam. Both entry points reach here: the parser's
    // inline setOption handling (parser/BNGAstVisitor.cpp) and the action
    // dispatcher (actions/ActionDispatch.cpp), plus option copying in
    // engine/HybridModelGenerator.cpp. Validating in the setter rather than in
    // each caller is what keeps an unsupported option from being stored on one
    // path and rejected on another.
    const auto validation = options::validate(key, value);
    if (!validation.accepted()) {
        throw std::runtime_error("setOption(\"" + key + "\",\"" + value +
                                 "\"): " + validation.message);
    }
    if (validation.status == options::Validation::Status::Accepted &&
        !validation.message.empty()) {
        std::cerr << "WARNING: setOption(\"" << key << "\",\"" << value
                  << "\"): " << validation.message << "\n";
    }
    options_[std::move(key)] = std::move(value);
}

void Model::defineUnit(std::string id, std::string expression) {
    const auto result = unitSystem_.define(std::move(id), std::move(expression));
    if (!result) throw std::runtime_error("Invalid unit definition: " + result.error);
}

void Model::setUnitDefault(std::string role, std::string unit) {
    if (unitSystem_.find(unit) == nullptr && !unitSystem_.parse(unit)) {
        throw std::runtime_error("Unknown unit '" + unit + "' for " + role);
    }
    if (role == "substanceUnits") {
        substanceUnits_ = unit;
    }
    unitDefaults_[std::move(role)] = std::move(unit);
}

void Model::setParameterUnit(std::string parameter, std::string unit) {
    if (unitSystem_.find(unit) == nullptr && !unitSystem_.parse(unit)) {
        throw std::runtime_error("Unknown unit '" + unit + "' for parameter '" + parameter + "'");
    }
    const auto parsed = unitSystem_.parse(unit);
    parameterUnits_[parameter] = unit;
    for (auto& candidate : parameters_.all()) {
        if (candidate.getName() == parameter) {
            candidate.setUnit(*parsed.unit, unit);
            break;
        }
    }
}

void Model::setParameterComment(std::string parameter, std::string comment) {
    parameterComments_[std::move(parameter)] = std::move(comment);
}

void Model::setCompartmentUnit(std::string compartment, std::string unit) {
    if (unitSystem_.find(unit) == nullptr && !unitSystem_.parse(unit)) {
        throw std::runtime_error("Unknown unit '" + unit + "' for compartment '" + compartment + "'");
    }
    const auto parsed = unitSystem_.parse(unit);
    compartmentUnits_[compartment] = unit;
    for (auto& candidate : compartments) {
        if (candidate.getName() == compartment) {
            candidate.setUnit(*parsed.unit, unit);
            break;
        }
    }
}

void Model::setSeedUnit(std::size_t index, std::string unit) {
    if (unitSystem_.find(unit) == nullptr && !unitSystem_.parse(unit)) {
        throw std::runtime_error("Unknown unit '" + unit + "' for seed species");
    }
    const auto parsed = unitSystem_.parse(unit);
    seedUnits_[index] = unit;
    if (index < seedSpecies_.size()) {
        seedSpecies_[index].setUnit(*parsed.unit, unit);
    }
}

void Model::merge(Model& other) {
    // Transfer GraphTypeRegistry entries first so PatternGraph node pointers
    // remain valid after the source model is destroyed.
    graphTypeRegistry_.mergeFrom(other.getGraphTypeRegistry());

    // Unit definitions and model-level defaults are semantic model metadata,
    // not parser-only state.  Transfer custom definitions before copying
    // declarations so attached unit names resolve in the destination model.
    for (const auto& definition : other.getUnitSystem().definitions()) {
        if (definition.builtin) continue;
        if (unitSystem_.find(definition.id) == nullptr) {
            defineUnit(definition.id, definition.expression);
        } else {
            const auto existing = unitSystem_.parse(definition.id);
            if (!existing || existing.unit->dimension != definition.unit.dimension ||
                existing.unit->baseExponents != definition.unit.baseExponents ||
                std::abs(existing.unit->factor - definition.unit.factor) > 1e-15) {
                throw std::runtime_error(
                    "cannot merge conflicting unit definition '" + definition.id + "'");
            }
        }
    }
    for (const auto& [role, unit] : other.getUnitDefaults()) {
        setUnitDefault(role, unit);
    }

    // Merge parameters
    for (const auto& param : other.getParameters().all()) {
        parameters_.add(param);
    }
    parameterComments_.insert(other.parameterComments_.begin(),
                              other.parameterComments_.end());

    // Merge compartments
    for (const auto& comp : other.getCompartments()) {
        compartments.push_back(comp);
    }

    // Merge molecule types
    for (const auto& mt : other.getMoleculeTypes()) {
        moleculeTypes_.push_back(mt);
    }

    // Merge seed species
    for (const auto& ss : other.getSeedSpecies()) {
        seedSpecies_.push_back(ss);
    }

    // Merge observables
    for (const auto& obs : other.getObservables()) {
        observables_.push_back(obs);
    }

    // Merge reaction rules (move since ReactionRule has unique_ptr member)
    for (auto& rule : other.getReactionRules()) {
        reactionRules_.push_back(std::move(rule));
    }

    // Merge functions
    for (const auto& func : other.getFunctions()) {
        functions_.push_back(func);
    }

    // Merge energy patterns
    for (const auto& ep : other.getEnergyPatterns()) {
        energyPatterns_.push_back(ep);
    }

    // Merge barrier patterns (move: each owns a non-copyable ReactionRule)
    for (auto& bp : other.getBarrierPatterns()) {
        barrierPatterns_.push_back(std::move(bp));
    }

    // Merge molecules
    for (const auto& mol : other.getMolecules()) {
        molecules.push_back(mol);
    }

    // Merge options (other's options override if keys conflict)
    for (const auto& [key, value] : other.getOptions()) {
        options_[key] = value;
    }
}

const std::vector<Compartment>& Model::getCompartments() const {
    return compartments;
}

std::vector<Compartment>& Model::getCompartments() {
    return compartments;
}

const std::vector<Molecule>& Model::getMolecules() const {
    return molecules;
}

const ParameterList& Model::getParameters() const {
    return parameters_;
}

ParameterList& Model::getParameters() {
    return parameters_;
}

const std::vector<Action>& Model::getActions() const {
    return actions_;
}

std::vector<Action>& Model::getActions() {
    return actions_;
}

const std::vector<Function>& Model::getFunctions() const {
    return functions_;
}

const std::vector<EnergyPattern>& Model::getEnergyPatterns() const {
    return energyPatterns_;
}

const std::vector<BarrierPattern>& Model::getBarrierPatterns() const {
    return barrierPatterns_;
}

std::vector<BarrierPattern>& Model::getBarrierPatterns() {
    return barrierPatterns_;
}

const std::vector<Observable>& Model::getObservables() const {
    return observables_;
}

const std::vector<MoleculeType>& Model::getMoleculeTypes() const {
    return moleculeTypes_;
}

MoleculeType* Model::findMoleculeType(const std::string& name) {
    for (auto& moleculeType : moleculeTypes_) {
        if (moleculeType.getName() == name) {
            return &moleculeType;
        }
    }
    return nullptr;
}

const MoleculeType* Model::findMoleculeType(const std::string& name) const {
    for (const auto& moleculeType : moleculeTypes_) {
        if (moleculeType.getName() == name) {
            return &moleculeType;
        }
    }
    return nullptr;
}

const std::vector<SeedSpecies>& Model::getSeedSpecies() const {
    return seedSpecies_;
}

const std::vector<ReactionRule>& Model::getReactionRules() const {
    return reactionRules_;
}

std::vector<ReactionRule>& Model::getReactionRules() {
    return reactionRules_;
}

const std::vector<PopulationMap>& Model::getPopulationMaps() const {
    return populationMaps_;
}

const std::vector<Action>& Model::getSimulationProtocol() const {
    return simulationProtocol_;
}

const std::string& Model::getVersion() const {
    return version_;
}

const std::string& Model::getSubstanceUnits() const {
    return substanceUnits_;
}

const std::string& Model::getModelName() const {
    return modelName_;
}

const std::map<std::string, std::string>& Model::getOptions() const {
    return options_;
}

const units::UnitSystem& Model::getUnitSystem() const {
    return unitSystem_;
}

const std::map<std::string, std::string>& Model::getUnitDefaults() const {
    return unitDefaults_;
}

const std::string* Model::findParameterUnit(const std::string& name) const {
    const auto it = parameterUnits_.find(name);
    return it == parameterUnits_.end() ? nullptr : &it->second;
}

const std::string* Model::findParameterComment(const std::string& name) const {
    const auto it = parameterComments_.find(name);
    return it == parameterComments_.end() ? nullptr : &it->second;
}

const std::string* Model::findCompartmentUnit(const std::string& name) const {
    const auto it = compartmentUnits_.find(name);
    return it == compartmentUnits_.end() ? nullptr : &it->second;
}

const std::string* Model::findSeedUnit(std::size_t index) const {
    const auto it = seedUnits_.find(index);
    return it == seedUnits_.end() ? nullptr : &it->second;
}

GraphTypeRegistry& Model::getGraphTypeRegistry() {
    return graphTypeRegistry_;
}

} // namespace ast
} // namespace bng
