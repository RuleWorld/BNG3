#include "nfsim_native_reader.hh"
#include "../NFcore/NFcore.hh"
#include "../NFcore/compartment.hh"
#include "../NFcore/observable.hh"
#include "../NFcore/templateMolecule.hh"
#include "../NFreactions/reactions/reaction.hh"
#include "../NFfunction/NFfunction.hh"
#include "../NFreactions/transformations/transformationSet.hh"
#include "../NFreactions/transformations/transformation.hh"
#include "nfsim_transform_decoder.hh"
#include "../NFreactions/transformations/moleculeCreator.hh"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <map>
#include <queue>
#include <set>
namespace NFcore2 {
using namespace NFcore;
NativeNFsimSystemReader::NativeNFsimSystemReader(System& s):system_(s){}

namespace {
bool appendExactComplexObservableBinding(
    Observable* observable, const std::string& name, std::uint16_t reactant,
    int scope, NativeReactionHeader& header);
bool observableHasInternalBond(Observable* observable);

bool appendSimpleScopedLocalFunction(System& system, LocalFunction* local,
                                     std::uint16_t reactant,
                                     NativeReactionHeader& header) {
    if (!local || local->getParsedExpression().empty()) return false;
    NativeReactionHeader candidate = header;
    candidate.rate_law = NATIVE_RATE_EXPRESSION;
    candidate.rate_expression = local->getParsedExpression();
    candidate.rate_expression_bindings.clear();
    for (int i = 0; i < local->getNumOfVarRefs(); ++i) {
        const int scope = local->getVarRefScope(i);
        if (scope != LocalFunction::SPECIES && scope != LocalFunction::MOLECULE)
            return false;
        Observable* observable = system.getObservableByName(
            local->getVarObservableName(i));
        if (!observable || observable->getType() != Observable::MOLECULES)
            return false;
        int templateCount = 0;
        TemplateMolecule** templates = nullptr;
        observable->getTemplateMoleculeList(templateCount, templates);
        if (templateCount == 2 || observableHasInternalBond(observable)) {
            if (!appendExactComplexObservableBinding(
                    observable, local->getVarRefName(i), reactant, scope, candidate))
                return false;
            continue;
        }
        if (templateCount != 1 || templates == nullptr || templates[0] == nullptr ||
            templates[0]->getMoleculeType() == nullptr)
            return false;
        TemplateMolecule::RootLocalConstraints constraints;
        if (!templates[0]->collectRootLocalConstraints(constraints) ||
            constraints.empty.size() > 1 || constraints.occupied.size() > 1 ||
            (!constraints.empty.empty() && !constraints.occupied.empty()) ||
            constraints.states.size() > 1 || !constraints.exclusions.empty() ||
            !constraints.bonds.empty() || !constraints.symmetric.empty() ||
            !constraints.connected_to.empty()) {
            return false;
        }
        NativeRateExpressionBindingSnapshot binding;
        binding.kind = NATIVE_RATE_EXPRESSION_SPECIES_MOLECULE_COUNT;
        binding.name = local->getVarRefName(i);
        binding.reactant = reactant;
        binding.molecule_type = static_cast<std::uint32_t>(
            templates[0]->getMoleculeType()->getTypeID());
        binding.scope = scope;
        if (!constraints.states.empty()) {
            if (constraints.states.front().first < 0 || constraints.states.front().second < 0)
                return false;
            binding.state_component = static_cast<std::uint32_t>(constraints.states.front().first);
            binding.state_value = constraints.states.front().second;
        }
        if (constraints.empty.size() == 1) {
            if (constraints.empty.front() < 0) return false;
            binding.bond_component = static_cast<std::uint32_t>(constraints.empty.front());
            binding.bond_state = TemplateMolecule::EMPTY;
        } else if (constraints.occupied.size() == 1) {
            if (constraints.occupied.front() < 0) return false;
            binding.bond_component = static_cast<std::uint32_t>(constraints.occupied.front());
            binding.bond_state = TemplateMolecule::OCCUPIED;
        }
        if (!constraints.compartment.empty())
            binding.compartment = nativeCompartmentId(constraints.compartment);
        candidate.rate_expression_bindings.push_back(binding);
    }
    for (int i = 0; i < local->getNumOfParams(); ++i) {
        const std::string name = local->getParamName(i);
        const double value = system.getParameter(name);
        if (!std::isfinite(value)) return false;
        NativeRateExpressionBindingSnapshot binding;
        binding.kind = NATIVE_RATE_EXPRESSION_CONSTANT;
        binding.name = name;
        binding.value = value;
        candidate.rate_expression_bindings.push_back(binding);
    }
    header = candidate;
    return true;
}

bool appendSimpleGlobalFunction(System& system, GlobalFunction* global,
                               NativeReactionHeader& header) {
    if (!global || global->getExpression().empty()) return false;
    NativeReactionHeader candidate = header;
    candidate.rate_law = NATIVE_RATE_EXPRESSION;
    candidate.rate_expression = global->getExpression();
    candidate.rate_expression_bindings.clear();
    for (int i = 0; i < global->getNumOfVarRefs(); ++i) {
        const std::string type = global->getVarRefType(i);
        if (type == "Time") continue;
        if (type != "Observable") return false;
        Observable* observable = system.getObservableByName(global->getVarRefName(i));
        if (!observable || observable->getType() != Observable::MOLECULES)
            return false;
        int templateCount = 0;
        TemplateMolecule** templates = nullptr;
        observable->getTemplateMoleculeList(templateCount, templates);
        if (templateCount == 2 || observableHasInternalBond(observable)) {
            if (!appendExactComplexObservableBinding(
                    observable, global->getVarRefName(i), 0,
                    -1, candidate))
                return false;
            continue;
        }
        if (templateCount != 1 || templates == nullptr || templates[0] == nullptr ||
            templates[0]->getMoleculeType() == nullptr)
            return false;
        TemplateMolecule::RootLocalConstraints constraints;
        if (!templates[0]->collectRootLocalConstraints(constraints) ||
            constraints.empty.size() > 1 || constraints.occupied.size() > 1 ||
            (!constraints.empty.empty() && !constraints.occupied.empty()) ||
            constraints.states.size() > 1 || !constraints.exclusions.empty() ||
            !constraints.bonds.empty() || !constraints.symmetric.empty() ||
            !constraints.connected_to.empty())
            return false;
        NativeRateExpressionBindingSnapshot binding;
        binding.kind = NATIVE_RATE_EXPRESSION_GLOBAL_MOLECULE_COUNT;
        binding.name = global->getVarRefName(i);
        binding.molecule_type = static_cast<std::uint32_t>(
            templates[0]->getMoleculeType()->getTypeID());
        if (!constraints.states.empty()) {
            if (constraints.states.front().first < 0 || constraints.states.front().second < 0)
                return false;
            binding.state_component = static_cast<std::uint32_t>(constraints.states.front().first);
            binding.state_value = constraints.states.front().second;
        }
        if (constraints.empty.size() == 1) {
            if (constraints.empty.front() < 0) return false;
            binding.bond_component = static_cast<std::uint32_t>(constraints.empty.front());
            binding.bond_state = TemplateMolecule::EMPTY;
        } else if (constraints.occupied.size() == 1) {
            if (constraints.occupied.front() < 0) return false;
            binding.bond_component = static_cast<std::uint32_t>(constraints.occupied.front());
            binding.bond_state = TemplateMolecule::OCCUPIED;
        }
        if (!constraints.compartment.empty())
            binding.compartment = nativeCompartmentId(constraints.compartment);
        candidate.rate_expression_bindings.push_back(binding);
    }
    for (int i = 0; i < global->getNumOfParams(); ++i) {
        const std::string name = global->getParamName(i);
        const double value = system.getParameter(name);
        if (!std::isfinite(value)) return false;
        NativeRateExpressionBindingSnapshot binding;
        binding.kind = NATIVE_RATE_EXPRESSION_CONSTANT;
        binding.name = name;
        binding.value = value;
        candidate.rate_expression_bindings.push_back(binding);
    }
    header = candidate;
    return true;
}

bool mergeSimpleScopedLocalFunctions(const NativeReactionHeader& first,
                                     const NativeReactionHeader& second,
                                     NativeReactionHeader& merged) {
    merged = first;
    merged.rate_expression = "(" + first.rate_expression + ")*(" +
                             second.rate_expression + ")";
    for (const auto& binding : second.rate_expression_bindings) {
        bool duplicate = false;
        for (const auto& prior : merged.rate_expression_bindings) {
            if (prior.name != binding.name) continue;
            if (prior.kind != binding.kind || prior.reactant != binding.reactant ||
                prior.component != binding.component ||
                prior.state_component != binding.state_component ||
                prior.state_value != binding.state_value ||
                prior.bond_component != binding.bond_component ||
                prior.bond_state != binding.bond_state ||
                prior.molecule_type != binding.molecule_type ||
                prior.partner_molecule_type != binding.partner_molecule_type ||
                prior.partner_component != binding.partner_component ||
                prior.partner_state_component != binding.partner_state_component ||
                prior.partner_state_value != binding.partner_state_value ||
                prior.scope != binding.scope ||
                prior.compartment != binding.compartment ||
                prior.compartment_ancestry != binding.compartment_ancestry ||
                prior.destination_compartment != binding.destination_compartment ||
                prior.value != binding.value) return false;
            duplicate = true;
            break;
        }
        if (!duplicate) merged.rate_expression_bindings.push_back(binding);
    }
    for (const auto& function : second.rate_expression_functions) {
        bool duplicate = false;
        for (const auto& prior : merged.rate_expression_functions) {
            if (prior.name != function.name) continue;
            if (prior.expression != function.expression ||
                prior.arguments != function.arguments) return false;
            duplicate = true;
            break;
        }
        if (!duplicate) merged.rate_expression_functions.push_back(function);
    }
    return true;
}

bool appendExpressionFunction(NativeReactionHeader& header,
                              const std::string& name,
                              const std::string& expression,
                              const std::vector<std::string>& arguments) {
    if (name.empty() || expression.empty()) return false;
    for (const auto& prior : header.rate_expression_functions) {
        if (prior.name != name) continue;
        return prior.expression == expression && prior.arguments == arguments;
    }
    NativeRateExpressionFunctionSnapshot function;
    function.name = name;
    function.expression = expression;
    function.arguments = arguments;
    header.rate_expression_functions.push_back(function);
    return true;
}

bool appendExpressionBinding(NativeReactionHeader& header,
                             const NativeRateExpressionBindingSnapshot& binding) {
    for (const auto& prior : header.rate_expression_bindings) {
        if (prior.name != binding.name) continue;
        return prior.kind == binding.kind && prior.reactant == binding.reactant &&
               prior.component == binding.component &&
               prior.state_component == binding.state_component &&
               prior.state_value == binding.state_value &&
               prior.bond_component == binding.bond_component &&
               prior.bond_state == binding.bond_state &&
               prior.molecule_type == binding.molecule_type &&
               prior.partner_molecule_type == binding.partner_molecule_type &&
               prior.partner_component == binding.partner_component &&
               prior.partner_state_component == binding.partner_state_component &&
               prior.partner_state_value == binding.partner_state_value &&
               prior.scope == binding.scope &&
               prior.compartment == binding.compartment &&
               prior.compartment_ancestry == binding.compartment_ancestry &&
               prior.destination_compartment == binding.destination_compartment &&
               prior.value == binding.value;
    }
    header.rate_expression_bindings.push_back(binding);
    return true;
}

bool appendExactComplexObservableBinding(
    Observable* observable, const std::string& name, std::uint16_t reactant,
    int scope, NativeReactionHeader& header) {
    if (!observable || observable->getType() != Observable::MOLECULES)
        return false;
    int templateCount = 0;
    TemplateMolecule** templates = nullptr;
    observable->getTemplateMoleculeList(templateCount, templates);
    if ((templateCount != 1 && templateCount != 2) || templates == nullptr ||
        !templates[0] || !templates[0]->getMoleculeType())
        return false;
    TemplateMolecule* rootTemplate = templates[0];
    TemplateMolecule* partnerTemplate = nullptr;
    TemplateMolecule::RootLocalConstraints root;
    TemplateMolecule::RootLocalConstraints partner;
    const bool collected = rootTemplate->collectRootLocalConstraints(root);
    if (collected && root.bonds.size() == 1) {
        partnerTemplate = root.bonds[0].partner;
        if (templateCount == 2 && partnerTemplate != templates[1])
            partnerTemplate = nullptr;
    }
    const bool partnerCollected = partnerTemplate && partnerTemplate->getMoleculeType() &&
        partnerTemplate->collectRootLocalConstraints(partner);
    const bool shape = root.bonds.size() == 1 && partner.bonds.size() == 1;
    const bool reciprocal = shape && root.bonds[0].partner == partnerTemplate &&
        partner.bonds[0].partner == rootTemplate;
    const bool componentShape = shape && root.bonds[0].component >= 0 &&
        partner.bonds[0].component >= 0 && root.bonds[0].partner_component >= 0 &&
        partner.bonds[0].partner_component >= 0 &&
        !root.bonds[0].partner_component_symmetric &&
        !partner.bonds[0].partner_component_symmetric &&
        root.bonds[0].partner_component == partner.bonds[0].component &&
        partner.bonds[0].partner_component == root.bonds[0].component;
    const bool localOnly = root.compartment == partner.compartment &&
        root.symmetric.empty() && partner.symmetric.empty() &&
        root.connected_to.empty() && partner.connected_to.empty() &&
        root.empty.empty() && root.occupied.empty() &&
        partner.empty.empty() && partner.occupied.empty() &&
        root.exclusions.empty() && partner.exclusions.empty() &&
        root.states.size() <= 1 && partner.states.size() <= 1;
    if (!(collected && partnerCollected && shape && reciprocal && componentShape && localOnly)) {
        return false;
    }
    NativeRateExpressionBindingSnapshot binding;
    binding.kind = NATIVE_RATE_EXPRESSION_COMPLEX_MOLECULE_COUNT;
    binding.name = name;
    binding.reactant = reactant;
    binding.scope = scope;
    binding.molecule_type = static_cast<std::uint32_t>(
        rootTemplate->getMoleculeType()->getTypeID());
    binding.component = static_cast<std::uint32_t>(root.bonds[0].component);
    binding.partner_molecule_type = static_cast<std::uint32_t>(
        partnerTemplate->getMoleculeType()->getTypeID());
    binding.partner_component = static_cast<std::uint32_t>(root.bonds[0].partner_component);
    if (!root.states.empty()) {
        if (root.states[0].first < 0 || root.states[0].second < 0) return false;
        binding.state_component = static_cast<std::uint32_t>(root.states[0].first);
        binding.state_value = root.states[0].second;
    }
    if (!partner.states.empty()) {
        if (partner.states[0].first < 0 || partner.states[0].second < 0) return false;
        binding.partner_state_component = static_cast<std::uint32_t>(partner.states[0].first);
        binding.partner_state_value = partner.states[0].second;
    }
    if (!root.compartment.empty())
        binding.compartment = nativeCompartmentId(root.compartment);
    return appendExpressionBinding(header, binding);
}

bool observableHasInternalBond(Observable* observable) {
    if (!observable || observable->getType() != Observable::MOLECULES)
        return false;
    int templateCount = 0;
    TemplateMolecule** templates = nullptr;
    observable->getTemplateMoleculeList(templateCount, templates);
    if (templateCount == 2) return true;
    if (templateCount != 1 || templates == nullptr || templates[0] == nullptr)
        return false;
    TemplateMolecule::RootLocalConstraints constraints;
    return templates[0]->collectRootLocalConstraints(constraints) &&
        constraints.bonds.size() == 1 && constraints.bonds[0].partner != nullptr;
}

bool appendScopedObservableBinding(System& system, Observable* observable,
                                  const std::string& name,
                                  std::uint16_t reactant, int scope,
                                  NativeReactionHeader& header) {
    if (!observable || observable->getType() != Observable::MOLECULES ||
        (scope != LocalFunction::SPECIES && scope != LocalFunction::MOLECULE))
        return false;
    int templateCount = 0;
    TemplateMolecule** templates = nullptr;
    observable->getTemplateMoleculeList(templateCount, templates);
    if (templateCount == 2 || observableHasInternalBond(observable))
        return appendExactComplexObservableBinding(
            observable, name, reactant, scope, header);
    if (templateCount != 1 || templates == nullptr || templates[0] == nullptr ||
        templates[0]->getMoleculeType() == nullptr)
        return false;
    TemplateMolecule::RootLocalConstraints constraints;
    if (!templates[0]->collectRootLocalConstraints(constraints) ||
        constraints.empty.size() > 1 || constraints.occupied.size() > 1 ||
        (!constraints.empty.empty() && !constraints.occupied.empty()) ||
        constraints.states.size() > 1 || !constraints.exclusions.empty() ||
        !constraints.bonds.empty() || !constraints.symmetric.empty() ||
        !constraints.connected_to.empty()) {
        return false;
    }
    NativeRateExpressionBindingSnapshot binding;
    binding.kind = NATIVE_RATE_EXPRESSION_SPECIES_MOLECULE_COUNT;
    binding.name = name;
    binding.reactant = reactant;
    binding.molecule_type = static_cast<std::uint32_t>(
        templates[0]->getMoleculeType()->getTypeID());
    binding.scope = scope;
    if (!constraints.states.empty()) {
        if (constraints.states.front().first < 0 || constraints.states.front().second < 0)
            return false;
        binding.state_component = static_cast<std::uint32_t>(constraints.states.front().first);
        binding.state_value = constraints.states.front().second;
    }
    if (constraints.empty.size() == 1) {
        if (constraints.empty.front() < 0) return false;
        binding.bond_component = static_cast<std::uint32_t>(constraints.empty.front());
        binding.bond_state = TemplateMolecule::EMPTY;
    } else if (constraints.occupied.size() == 1) {
        if (constraints.occupied.front() < 0) return false;
        binding.bond_component = static_cast<std::uint32_t>(constraints.occupied.front());
        binding.bond_state = TemplateMolecule::OCCUPIED;
    }
    if (!constraints.compartment.empty())
        binding.compartment = nativeCompartmentId(constraints.compartment);
    return appendExpressionBinding(header, binding);
}

bool appendLocalFunctionDefinition(System& system, LocalFunction* local,
                                   std::uint16_t reactant,
                                   NativeReactionHeader& header,
                                   std::set<std::string>& visiting) {
    if (!local || local->getParsedExpression().empty()) return false;
    if (!visiting.insert(local->getName()).second) return false;
    std::vector<std::string> arguments;
    for (int i = 0; i < local->getNumOfArgs(); ++i)
        arguments.push_back(local->getArgName(i));
    if (!appendExpressionFunction(header, local->getName(),
                                  local->getParsedExpression(), arguments)) {
        visiting.erase(local->getName());
        return false;
    }
    for (int i = 0; i < local->getNumOfVarRefs(); ++i) {
        const int scope = local->getVarRefScope(i);
        Observable* observable = system.getObservableByName(
            local->getVarObservableName(i));
        if (!appendScopedObservableBinding(system, observable,
                                           local->getVarRefName(i), reactant,
                                           scope, header)) {
            visiting.erase(local->getName());
            return false;
        }
    }
    for (int i = 0; i < local->getNumOfParams(); ++i) {
        const std::string name = local->getParamName(i);
        const double value = system.getParameter(name);
        if (!std::isfinite(value) ||
            !appendExpressionBinding(header,
                NativeRateExpressionBindingSnapshot::constant(name, value))) {
            visiting.erase(local->getName());
            return false;
        }
    }
    visiting.erase(local->getName());
    return true;
}

bool appendGlobalFunctionDefinition(System& system, GlobalFunction* global,
                                    NativeReactionHeader& header,
                                    std::set<std::string>& visiting) {
    if (!global || global->getExpression().empty()) return false;
    if (!visiting.insert(global->getName()).second) return false;
    if (!appendExpressionFunction(header, global->getName(),
                                  global->getExpression(), {})) {
        visiting.erase(global->getName());
        return false;
    }
    for (int i = 0; i < global->getNumOfVarRefs(); ++i) {
        const std::string type = global->getVarRefType(i);
        if (type == "Time") continue;
        if (type == "Function") {
            GlobalFunction* nested = system.getGlobalFunctionByName(
                global->getVarRefName(i));
            if (!appendGlobalFunctionDefinition(system, nested, header, visiting)) {
                visiting.erase(global->getName());
                return false;
            }
            continue;
        }
        if (type != "Observable") {
            visiting.erase(global->getName());
            return false;
        }
        Observable* observable = system.getObservableByName(global->getVarRefName(i));
        int templateCount = 0;
        TemplateMolecule** templates = nullptr;
        if (!observable || observable->getType() != Observable::MOLECULES) {
            visiting.erase(global->getName());
            return false;
        }
        observable->getTemplateMoleculeList(templateCount, templates);
        if (templateCount == 2 || observableHasInternalBond(observable)) {
            if (!appendExactComplexObservableBinding(
                    observable, global->getVarRefName(i), 0, -1, header)) {
                visiting.erase(global->getName());
                return false;
            }
            continue;
        }
        if (templateCount != 1 || templates == nullptr || templates[0] == nullptr ||
            templates[0]->getMoleculeType() == nullptr) {
            visiting.erase(global->getName());
            return false;
        }
        TemplateMolecule::RootLocalConstraints constraints;
        if (!templates[0]->collectRootLocalConstraints(constraints) ||
            constraints.empty.size() > 1 || constraints.occupied.size() > 1 ||
            (!constraints.empty.empty() && !constraints.occupied.empty()) ||
            constraints.states.size() > 1 || !constraints.exclusions.empty() ||
            !constraints.bonds.empty() || !constraints.symmetric.empty() ||
            !constraints.connected_to.empty()) {
            visiting.erase(global->getName());
            return false;
        }
        NativeRateExpressionBindingSnapshot binding;
        binding.kind = NATIVE_RATE_EXPRESSION_GLOBAL_MOLECULE_COUNT;
        binding.name = global->getVarRefName(i);
        binding.molecule_type = static_cast<std::uint32_t>(
            templates[0]->getMoleculeType()->getTypeID());
        if (!constraints.states.empty()) {
            if (constraints.states.front().first < 0 || constraints.states.front().second < 0) {
                visiting.erase(global->getName());
                return false;
            }
            binding.state_component = static_cast<std::uint32_t>(constraints.states.front().first);
            binding.state_value = constraints.states.front().second;
        }
        if (constraints.empty.size() == 1) {
            if (constraints.empty.front() < 0) {
                visiting.erase(global->getName());
                return false;
            }
            binding.bond_component = static_cast<std::uint32_t>(constraints.empty.front());
            binding.bond_state = TemplateMolecule::EMPTY;
        } else if (constraints.occupied.size() == 1) {
            if (constraints.occupied.front() < 0) {
                visiting.erase(global->getName());
                return false;
            }
            binding.bond_component = static_cast<std::uint32_t>(constraints.occupied.front());
            binding.bond_state = TemplateMolecule::OCCUPIED;
        }
        if (!constraints.compartment.empty())
            binding.compartment = nativeCompartmentId(constraints.compartment);
        if (!appendExpressionBinding(header, binding)) {
            visiting.erase(global->getName());
            return false;
        }
    }
    for (int i = 0; i < global->getNumOfParams(); ++i) {
        const std::string name = global->getParamName(i);
        const double value = system.getParameter(name);
        if (!std::isfinite(value) ||
            !appendExpressionBinding(header,
                NativeRateExpressionBindingSnapshot::constant(name, value))) {
            visiting.erase(global->getName());
            return false;
        }
    }
    visiting.erase(global->getName());
    return true;
}

bool appendCompositeScopedLocalFunction(System& system, CompositeFunction* composite,
                                        std::uint16_t reactant,
                                        NativeReactionHeader& header) {
    if (!composite || composite->getOriginalExpression().empty()) return false;
    NativeReactionHeader candidate = header;
    candidate.rate_law = NATIVE_RATE_EXPRESSION;
    candidate.rate_expression = composite->getOriginalExpression();
    candidate.rate_expression_bindings.clear();
    candidate.rate_expression_functions.clear();
    std::set<std::string> visiting;
    for (int i = 0; i < composite->getNumOfFunctions(); ++i) {
        const std::string name = composite->getFunctionName(i);
        if (LocalFunction* local = system.getLocalFunctionByName(name)) {
            if (!appendLocalFunctionDefinition(system, local, reactant, candidate, visiting))
                return false;
        } else if (GlobalFunction* global = system.getGlobalFunctionByName(name)) {
            if (!appendGlobalFunctionDefinition(system, global, candidate, visiting))
                return false;
        } else {
            return false;
        }
    }
    header = candidate;
    return true;
}

bool appendCompositeGlobalFunction(System& system, CompositeFunction* composite,
                                   NativeReactionHeader& header) {
    if (!composite || composite->getOriginalExpression().empty()) return false;
    NativeReactionHeader candidate = header;
    candidate.rate_law = NATIVE_RATE_EXPRESSION;
    candidate.rate_expression = composite->getOriginalExpression();
    candidate.rate_expression_bindings.clear();
    candidate.rate_expression_functions.clear();
    std::set<std::string> visiting;
    for (int i = 0; i < composite->getNumOfFunctions(); ++i) {
        GlobalFunction* global = system.getGlobalFunctionByName(
            composite->getFunctionName(i));
        if (!appendGlobalFunctionDefinition(system, global, candidate, visiting))
            return false;
    }
    header = candidate;
    return true;
}
}

std::size_t NativeNFsimSystemReader::moleculeTypeCount() const{return static_cast<std::size_t>(system_.getNumOfMoleculeTypes());}
NativeMoleculeTypeSnapshot NativeNFsimSystemReader::moleculeType(std::size_t i) const{
    MoleculeType* mt=system_.getMoleculeType(static_cast<int>(i));NativeMoleculeTypeSnapshot o;o.name=mt->getName();o.component_count=static_cast<std::uint32_t>(mt->getNumOfComponents());o.population=mt->isPopulationType();return o;
}
std::size_t NativeNFsimSystemReader::reactionCount() const{return system_.getAllReactions().size();}
NativeReactionHeader NativeNFsimSystemReader::reactionHeader(std::size_t i) const{
    ReactionClass* r=system_.getReaction(static_cast<int>(i));NativeReactionHeader h;h.name=r->getName();h.base_rate=r->getBaseRate();h.coordinate=static_cast<std::uint32_t>(i);h.parameter_index=static_cast<std::uint32_t>(i);
    bool directLocalFunction = false;
    bool directGlobalFunction = false;
    if (r->getRxnType() == ReactionClass::DOR_RXN) {
        DORRxnClass* dor = dynamic_cast<DORRxnClass*>(r);
        if (dor && dor->getCompositeFunction()) {
            directLocalFunction = appendCompositeScopedLocalFunction(
                system_, dor->getCompositeFunction(),
                static_cast<std::uint16_t>(std::max(0, dor->getDORreactantPosition())), h);
            LocalFunction* local = system_.getLocalFunctionByName(
                dor->getCompositeFunction()->getName());
            if (!directLocalFunction)
                directLocalFunction = appendSimpleScopedLocalFunction(
                    system_, local, static_cast<std::uint16_t>(std::max(0, dor->getDORreactantPosition())), h);
        }
    } else if (r->getRxnType() == ReactionClass::DOR2_RXN) {
        DOR2RxnClass* dor2 = dynamic_cast<DOR2RxnClass*>(r);
        if (dor2 && dor2->getCompositeFunction1() && dor2->getCompositeFunction2()) {
            LocalFunction* first = system_.getLocalFunctionByName(
                dor2->getCompositeFunction1()->getName());
            LocalFunction* second = system_.getLocalFunctionByName(
                dor2->getCompositeFunction2()->getName());
            NativeReactionHeader firstHeader = h;
            NativeReactionHeader secondHeader = h;
            bool firstSimple = appendCompositeScopedLocalFunction(
                system_, dor2->getCompositeFunction1(),
                static_cast<std::uint16_t>(std::max(0, dor2->getDORreactantPosition())), firstHeader);
            bool secondSimple = appendCompositeScopedLocalFunction(
                system_, dor2->getCompositeFunction2(),
                static_cast<std::uint16_t>(std::max(0, dor2->getDORreactantPosition2())), secondHeader);
            if (!firstSimple)
                firstSimple = appendSimpleScopedLocalFunction(
                    system_, first, static_cast<std::uint16_t>(std::max(0, dor2->getDORreactantPosition())), firstHeader);
            if (!secondSimple)
                secondSimple = appendSimpleScopedLocalFunction(
                    system_, second, static_cast<std::uint16_t>(std::max(0, dor2->getDORreactantPosition2())), secondHeader);
            if (firstSimple && secondSimple)
                directLocalFunction = mergeSimpleScopedLocalFunctions(firstHeader, secondHeader, h);
        }
    } else if (r->getRxnType() == ReactionClass::OBS_DEPENDENT_RXN) {
        FunctionalRxnClass* functional = dynamic_cast<FunctionalRxnClass*>(r);
        if (functional && functional->getGlobalFunction()) {
            NativeReactionHeader candidate = h;
            candidate.rate_law = NATIVE_RATE_EXPRESSION;
            candidate.rate_expression = functional->getGlobalFunction()->getExpression();
            candidate.rate_expression_bindings.clear();
            candidate.rate_expression_functions.clear();
            std::set<std::string> visiting;
            directGlobalFunction = appendGlobalFunctionDefinition(
                system_, functional->getGlobalFunction(), candidate, visiting);
            if (directGlobalFunction) h = candidate;
            else directGlobalFunction = appendSimpleGlobalFunction(
                system_, functional->getGlobalFunction(), h);
        } else if (functional && functional->getCompositeFunction()) {
            directGlobalFunction = appendCompositeGlobalFunction(
                system_, functional->getCompositeFunction(), h);
        }
    }
    h.uses_local_function = r->getRxnType() != ReactionClass::BASIC_RXN &&
                            !directLocalFunction && !directGlobalFunction;
    // A zero-reactant rule is a synthesis/population rule.  It does not
    // imply an unresolved internal graph query.
    h.uses_connected_to = false;
    std::vector<TemplateMolecule*> roots;
    for (int p = 0; p < r->getNumOfReactants(); ++p) roots.push_back(r->getReactantTemplate(p));
    std::vector<NativeGraphPatternSnapshot> graphPatterns;
    collectGraphPatterns(i, graphPatterns);
    for (int p = 0; p < r->getNumOfReactants(); ++p) {
        auto* mt = r->getMoleculeTypeOfReactantTemplate(p);
        if (!mt) throw std::logic_error("NFsim reactant without molecule type");
        h.reactant_types.push_back(static_cast<std::uint32_t>(mt->getTypeID()));
        auto* root = r->getReactantTemplate(p);
        TemplateMolecule::RootLocalConstraints constraints;
        if (!root || (!root->collectRootLocalConstraints(constraints) && graphPatterns.empty())) h.uses_connected_to = true;
        for (const auto& bond : constraints.bonds) {
            if (std::find(roots.begin(), roots.end(), bond.partner) == roots.end() && graphPatterns.empty())
                h.uses_connected_to = true;
        }
        for (TemplateMolecule* connected : constraints.connected_to) {
            if (std::find(roots.begin(), roots.end(), connected) == roots.end() && graphPatterns.empty())
                h.uses_connected_to = true;
        }
    }
    TransformationSet* ts=r->getTransformationSet();if(ts)for(int p=0;p<r->getNumOfReactants();++p)for(int x=0;x<ts->getNumOfTransformations(p);++x)if(ts->getTransformation(p,x)->getType()==TransformationFactory::LOCAL_FUNCTION_REFERENCE && h.rate_law != NATIVE_RATE_EXPRESSION)h.uses_local_function=true;
    return h;
}
void NativeNFsimSystemReader::collectGraphPatterns(std::size_t i,std::vector<NativeGraphPatternSnapshot>& out) const {
    ReactionClass* r=system_.getReaction(static_cast<int>(i));
    std::vector<TemplateMolecule*> roots;
    for (int p=0;p<r->getNumOfReactants();++p) roots.push_back(r->getReactantTemplate(p));
    std::map<TemplateMolecule*,std::size_t> indices;
    std::queue<TemplateMolecule*> pending;
    struct PendingSymmetric {
        std::size_t node;
        std::size_t constraint;
        TemplateMolecule* partner;
    };
    std::vector<PendingSymmetric> pendingSymmetric;
    NativeGraphPatternSnapshot graph;
    auto equivalentComponents = [](MoleculeType* type, const std::string& name,
                                   std::vector<std::uint32_t>& out) {
        if (!type || !type->isEquivalentComponent(name)) return false;
        int* components = 0;
        int count = 0;
        type->getEquivalencyClass(components, count, name);
        if (!components || count <= 0) return false;
        out.clear();
        for (int i = 0; i < count; ++i) {
            if (components[i] < 0 || components[i] >= type->getNumOfComponents()) return false;
            out.push_back(static_cast<std::uint32_t>(components[i]));
        }
        return true;
    };
    auto appendNode = [&](TemplateMolecule* molecule, std::uint16_t reactant) {
        if (!molecule || !molecule->getMoleculeType()) { out.clear(); return false; }
        TemplateMolecule::RootLocalConstraints constraints;
        if (!molecule->collectRootLocalConstraints(constraints)) { out.clear(); return false; }
        // Root-local constraints are emitted separately as dependency
        // predicates. Internal graph nodes need their own exact state
        // constraints here; silently dropping child constraints would widen
        // the graph match.
        NativeGraphNodeSnapshot node;
        node.molecule_type=static_cast<std::uint32_t>(molecule->getMoleculeType()->getTypeID());
        node.reactant=reactant;
        if (!constraints.compartment.empty())
            node.compartment=nativeCompartmentId(constraints.compartment);
        for (const auto component : constraints.empty)
            node.free_components.push_back(static_cast<std::uint32_t>(component));
        for (const auto component : constraints.occupied)
            node.bound_components.push_back(static_cast<std::uint32_t>(component));
        for (const auto& state : constraints.states) {
            if (state.first < 0 || state.second < 0) {
                out.clear(); return false;
            }
            node.state_constraints.emplace_back(static_cast<std::uint32_t>(state.first), state.second);
        }
        for (const auto& excluded : constraints.exclusions) {
            if (excluded.first < 0 || excluded.second < 0) {
                out.clear(); return false;
            }
            node.excluded_states.emplace_back(static_cast<std::uint32_t>(excluded.first), excluded.second);
        }
        if (!constraints.states.empty()) {
            node.state_component=static_cast<std::uint32_t>(constraints.states.front().first);
            node.state=constraints.states.front().second;
        }
        for (const auto& symmetric : constraints.symmetric) {
            if (symmetric.state_constraint < -1 ||
                (symmetric.bond_state != TemplateMolecule::NO_CONSTRAINT &&
                 symmetric.bond_state != TemplateMolecule::EMPTY &&
                 symmetric.bond_state != TemplateMolecule::OCCUPIED)) {
                out.clear(); return false;
            }
            NativeGraphNodeSnapshot::SymmetricConstraint native;
            if (!equivalentComponents(molecule->getMoleculeType(), symmetric.component_name,
                                      native.components)) {
                out.clear(); return false;
            }
            native.state = symmetric.state_constraint;
            native.bond_state = symmetric.bond_state;
            if (symmetric.partner) {
                MoleculeType* partnerType = symmetric.partner->getMoleculeType();
                if (!partnerType) { out.clear(); return false; }
                if (symmetric.partner_component >= 0) {
                    if (symmetric.partner_component >= partnerType->getNumOfComponents()) {
                        out.clear(); return false;
                    }
                    native.partner_components.push_back(static_cast<std::uint32_t>(symmetric.partner_component));
                } else if (symmetric.partner_component_symmetric) {
                    if (!equivalentComponents(partnerType, symmetric.partner_component_name,
                                              native.partner_components)) {
                        out.clear(); return false;
                    }
                    native.partner_symmetric = true;
                } else {
                    out.clear(); return false;
                }
            }
            const std::size_t nodeIndex = graph.nodes.size();
            const std::size_t constraintIndex = node.symmetric_constraints.size();
            node.symmetric_constraints.push_back(native);
            if (symmetric.partner)
                pendingSymmetric.push_back(PendingSymmetric{nodeIndex, constraintIndex, symmetric.partner});
        }
        indices[molecule]=graph.nodes.size();
        graph.nodes.push_back(node);
        pending.push(molecule);
        return true;
    };
    for (std::size_t p=0;p<roots.size();++p) {
        TemplateMolecule* root=roots[p];
        if (!root) { out.clear(); return; }
        if (indices.find(root)==indices.end()) {
            if (!appendNode(root, static_cast<std::uint16_t>(p))) return;
        }
    }
    while (!pending.empty()) {
        TemplateMolecule* current=pending.front(); pending.pop();
        const std::size_t currentIndex=indices[current];
        TemplateMolecule::RootLocalConstraints currentConstraints;
        if (!current->collectRootLocalConstraints(currentConstraints)) { out.clear(); return; }
        for (int b=0;b<current->getBondConstraintCount();++b) {
            TemplateMolecule* partner=current->getBondPartner(b);
            const int partnerComponent=current->getBondPartnerComponent(b);
            const int component=current->getBondComponent(b);
            if (!partner || component<0) { out.clear(); return; }
            auto found=indices.find(partner);
            if (found==indices.end()) {
                if (!appendNode(partner, std::numeric_limits<std::uint16_t>::max())) return;
                found=indices.find(partner);
            }
            const std::size_t partnerIndex=found->second;
            if (partnerComponent >= 0 && currentIndex < partnerIndex) {
                const bool currentEquivalent = current->getMoleculeType()->isEquivalentComponent(component);
                const bool partnerEquivalent = partner->getMoleculeType()->isEquivalentComponent(partnerComponent);
                if (currentEquivalent || partnerEquivalent) {
                    // A concrete edge would freeze one representative of an
                    // equivalent-site orbit. The appendNode pass already
                    // captured the corresponding source symmetric-bond
                    // constraint; omit the concrete edge so the matcher can
                    // assign distinct orbit members across all constraints.
                } else {
                    NativeGraphEdgeSnapshot edge; edge.first_node=currentIndex; edge.first_component=static_cast<std::uint32_t>(component); edge.second_node=partnerIndex; edge.second_component=static_cast<std::uint32_t>(partnerComponent); graph.edges.push_back(edge);
                }
            } else if (partnerComponent < 0) {
                // NFsim stores the reverse half of a bond to a symmetric site
                // as a regular bond with only the generic partner name. Lift
                // that half into an explicit symmetric occupancy constraint on
                // the partner node so the native matcher cannot widen the
                // pattern to an arbitrary occupied equivalent site.
                TemplateMolecule::RootLocalConstraints partnerConstraints;
                const std::string& partnerComponentName = currentConstraints.bonds[static_cast<std::size_t>(b)].partner_component_name;
                if (!partner->collectRootLocalConstraints(partnerConstraints) ||
                    !partner->getMoleculeType() ||
                    !partner->getMoleculeType()->isEquivalentComponent(partnerComponentName)) {
                    out.clear(); return;
                }
                std::vector<std::uint32_t> candidates;
                if (!equivalentComponents(partner->getMoleculeType(), partnerComponentName, candidates)) {
                    out.clear(); return;
                }
                bool alreadyCaptured = false;
                for (const auto& existing : graph.nodes[partnerIndex].symmetric_constraints) {
                    if (existing.partner_node == currentIndex && existing.bond_state == TemplateMolecule::OCCUPIED &&
                        existing.partner_components.size() == 1 && existing.partner_components[0] == static_cast<std::uint32_t>(component)) {
                        alreadyCaptured = true; break;
                    }
                }
                if (!alreadyCaptured) {
                    NativeGraphNodeSnapshot::SymmetricConstraint reverse;
                    reverse.components = candidates;
                    reverse.bond_state = TemplateMolecule::OCCUPIED;
                    reverse.partner_node = static_cast<std::uint32_t>(currentIndex);
                    reverse.partner_components.push_back(static_cast<std::uint32_t>(component));
                    graph.nodes[partnerIndex].symmetric_constraints.push_back(reverse);
                }
            }
        }
        for (const auto& symmetric : currentConstraints.symmetric) {
            if (!symmetric.partner) continue;
            auto found = indices.find(symmetric.partner);
            if (found == indices.end()) {
                if (!appendNode(symmetric.partner, std::numeric_limits<std::uint16_t>::max())) return;
            }
        }
        for (TemplateMolecule* connected : currentConstraints.connected_to) {
            if (!connected) { out.clear(); return; }
            auto found = indices.find(connected);
            if (found == indices.end()) {
                if (!appendNode(connected, std::numeric_limits<std::uint16_t>::max())) return;
                found = indices.find(connected);
            }
            const std::size_t connectedIndex = found->second;
            if (connectedIndex == currentIndex) { out.clear(); return; }
            const std::size_t first = std::min(currentIndex, connectedIndex);
            const std::size_t second = std::max(currentIndex, connectedIndex);
            bool alreadyCaptured = false;
            for (const auto& existing : graph.connected_to) {
                if (existing.first_node == first && existing.second_node == second) {
                    alreadyCaptured = true; break;
                }
            }
            if (!alreadyCaptured)
                graph.connected_to.push_back(NativeGraphConnectivitySnapshot(
                    static_cast<std::uint32_t>(first), static_cast<std::uint32_t>(second)));
        }
    }
    for (const auto& pendingConstraint : pendingSymmetric) {
        auto found = indices.find(pendingConstraint.partner);
        if (found == indices.end() || pendingConstraint.node >= graph.nodes.size() ||
            pendingConstraint.constraint >= graph.nodes[pendingConstraint.node].symmetric_constraints.size() ||
            found->second == pendingConstraint.node) {
            out.clear(); return;
        }
        graph.nodes[pendingConstraint.node].symmetric_constraints[pendingConstraint.constraint].partner_node =
            static_cast<std::uint32_t>(found->second);
    }
    // A symmetric bond can be visited once from each endpoint and may also
    // be present in the root-local symmetric table. Collapse those duplicate
    // descriptors after partner pointers have been resolved; keeping both
    // would incorrectly require two distinct orbit members for one bond.
    for (auto& node : graph.nodes) {
        std::vector<NativeGraphNodeSnapshot::SymmetricConstraint> unique;
        for (const auto& constraint : node.symmetric_constraints) {
            bool duplicate = false;
            for (const auto& prior : unique) {
                if (prior.components == constraint.components &&
                    prior.state == constraint.state &&
                    prior.bond_state == constraint.bond_state &&
                    prior.partner_node == constraint.partner_node &&
                    prior.partner_components == constraint.partner_components &&
                    prior.partner_symmetric == constraint.partner_symmetric) {
                    duplicate = true;
                    break;
                }
            }
            if (!duplicate) unique.push_back(constraint);
        }
        node.symmetric_constraints.swap(unique);
    }
    bool hasSymmetricConstraint = false;
    for (const auto& node : graph.nodes)
        if (!node.symmetric_constraints.empty()) { hasSymmetricConstraint = true; break; }
    if (!hasSymmetricConstraint && graph.edges.empty() && graph.connected_to.empty()) { return; }
    out.push_back(graph);
}

void NativeNFsimSystemReader::collectCompartments(std::vector<NativeCompartmentSnapshot>& out) const {
    out.clear();
    const auto& compartments=system_.getCompartments();
    for (const auto& entry : compartments) {
        Compartment* c=entry.second;
        NativeCompartmentSnapshot snapshot; snapshot.id=nativeCompartmentId(c->getId()); snapshot.dimensions=c->getSpatialDimensions(); snapshot.size=c->getSize();
        snapshot.parent=c->getParent() ? nativeCompartmentId(c->getParent()->getId()) : std::numeric_limits<std::uint32_t>::max();
        out.push_back(snapshot);
    }
}
void NativeNFsimSystemReader::collectDependencies(std::size_t i,std::vector<NativeDependencySnapshot>& out) const{
    ReactionClass* r=system_.getReaction(static_cast<int>(i));
    std::vector<TemplateMolecule*> roots;
    for (int p = 0; p < r->getNumOfReactants(); ++p) roots.push_back(r->getReactantTemplate(p));
    std::vector<NativeGraphPatternSnapshot> graphPatterns;
    collectGraphPatterns(i, graphPatterns);
    for (int p = 0; p < r->getNumOfReactants(); ++p) {
        auto* root = r->getReactantTemplate(p);
        TemplateMolecule::RootLocalConstraints constraints;
        if (!root || !root->collectRootLocalConstraints(constraints)) continue;
        auto append = [&](NativeDependencyKind kind, int component, int state) {
            NativeDependencySnapshot value;
            value.kind = kind; value.reactant = static_cast<std::uint16_t>(p);
            value.component = static_cast<std::uint32_t>(component); value.state = state;
            out.push_back(value);
        };
        for (auto c : constraints.empty) append(NATIVE_BOND_FREE, c, -1);
        for (auto c : constraints.occupied) append(NATIVE_BOND_BOUND, c, -1);
        for (auto c : constraints.states) append(NATIVE_STATE_REQUIRED, c.first, c.second);
        for (auto c : constraints.exclusions) append(NATIVE_STATE_EXCLUDED, c.first, c.second);
        for (const auto& bond : constraints.bonds) {
            auto partner = std::find(roots.begin(), roots.end(), bond.partner);
            if (partner == roots.end()) {
                // The captured graph carries this internal relation. Adding
                // an unresolved topology marker would force fallback again.
                if (graphPatterns.empty()) append(NATIVE_TOPOLOGY, bond.component, -1);
                continue;
            }
            NativeDependencySnapshot value;
            value.kind = NATIVE_BOND_TO;
            value.reactant = static_cast<std::uint16_t>(p);
            value.component = static_cast<std::uint32_t>(bond.component);
            value.partner_reactant = static_cast<std::uint16_t>(partner - roots.begin());
            value.partner_component = static_cast<std::uint32_t>(bond.partner_component);
            out.push_back(value);
        }
        if (!constraints.compartment.empty()) {
            NativeDependencySnapshot value;
            value.kind = NATIVE_COMPARTMENT_REQUIRED;
            value.reactant = static_cast<std::uint16_t>(p);
            value.compartment = nativeCompartmentId(constraints.compartment);
            out.push_back(value);
        }
        for (TemplateMolecule* connected : constraints.connected_to) {
            auto partner = std::find(roots.begin(), roots.end(), connected);
            if (partner == roots.end()) {
                // The graph snapshot carries external connectedTo relations.
                // Keep the unresolved marker only when graph extraction did
                // not produce a native graph; otherwise it would force a
                // fallback despite an exact matcher representation.
                if (graphPatterns.empty()) {
                    NativeDependencySnapshot unsupported;
                    unsupported.kind = NATIVE_TOPOLOGY;
                    unsupported.reactant = static_cast<std::uint16_t>(p);
                    unsupported.partner_reactant = std::numeric_limits<std::uint16_t>::max();
                    out.push_back(unsupported);
                }
                continue;
            }
            NativeDependencySnapshot value;
            value.kind = NATIVE_TOPOLOGY;
            value.reactant = static_cast<std::uint16_t>(p);
            value.partner_reactant = static_cast<std::uint16_t>(partner - roots.begin());
            value.partner_component = NATIVE_INFER_PARTNER_COMPONENT;
            out.push_back(value);
        }
    }
}
void NativeNFsimSystemReader::collectTransforms(std::size_t i,std::vector<NativeTransformSnapshot>& out) const{
    ReactionClass* r=system_.getReaction(static_cast<int>(i));
    TransformationSet* ts=r->getTransformationSet();
    if(!ts)return;
    std::vector<std::vector<NFsimPublicTransformView> > views(
        static_cast<std::size_t>(std::max(1,r->getNumOfReactants())));
    for(int p=0;p<r->getNumOfReactants();++p){
        for(int x=0;x<ts->getNumOfTransformations(p);++x){
            Transformation* t=ts->getTransformation(p,x);
            NFsimPublicTransformView v;
            v.kind=t->getType();
            v.reactant=static_cast<std::uint16_t>(p);
            int ci=-1;
            switch(t->getType()){
                case TransformationFactory::STATE_CHANGE:
                case TransformationFactory::BINDING:
                case TransformationFactory::UNBINDING:
                case TransformationFactory::EMPTY:
                case TransformationFactory::INCREMENT_STATE:
                case TransformationFactory::DECREMENT_STATE:
                    ci=t->getComponentIndex(); break;
                default: break;
            }
            v.component=ci<0?0u:static_cast<std::uint32_t>(ci);
            if(t->getType()==TransformationFactory::STATE_CHANGE){
                StateChangeTransform* q=dynamic_cast<StateChangeTransform*>(t);
                if(!q)throw std::logic_error("state transform type mismatch");
                v.final_state=q->getFinalStateValue();
            }else if(t->getType()==TransformationFactory::BINDING){
                BindingTransform* q=dynamic_cast<BindingTransform*>(t);
                if(!q)throw std::logic_error("binding transform type mismatch");
                v.other_reactant=q->getOtherReactantIndex();
                v.other_mapping_index=q->getOtherMappingIndex();
            }else if(t->getType()==TransformationFactory::EMPTY && ci>=0){
                v.second_binding_half=true;
            }else if(t->getType()==TransformationFactory::REMOVE){
                v.removal_type=t->getRemovalType();
            }else if(t->getType()==TransformationFactory::ADD){
                AddMoleculeTransform* q=dynamic_cast<AddMoleculeTransform*>(t);
                if(q){
                    if(q->isPopulationType()){
                        v.kind=TransformationFactory::INCREMENT_POPULATION;
                        v.population_delta=1;
                    }else if(q->getMoleculeType()){
                        v.added_molecule_type=static_cast<std::uint32_t>(
                            q->getMoleculeType()->getTypeID());
                    }
                }
            }else if(t->getType()==TransformationFactory::DECREMENT_POPULATION){
                v.population_delta=1;
            }else if(t->getType()==TransformationFactory::MOVE){
                MoveTransformation* q=dynamic_cast<MoveTransformation*>(t);
                if(q){
                    v.destination_compartment=nativeCompartmentId(q->getNewCompartmentId());
                    v.move_connected=q->isMoveConnected();
                }
            }else if(t->getType()==TransformationFactory::LOCAL_FUNCTION_REFERENCE){
                LocalFunctionReference* q=dynamic_cast<LocalFunctionReference*>(t);
                if(!q)throw std::logic_error("local-function transform type mismatch");
                v.local_function_pointer=q->getPointerName();
                v.local_function_scope=q->getFunctionScope();
            }
            views[static_cast<std::size_t>(p)].push_back(v);
        }
    }
    for (int x = 0; x < ts->getNumOfAddMoleculeTransforms(); ++x) {
        AddMoleculeTransform* add = ts->getAddMoleculeTransform(static_cast<unsigned int>(x));
        if (!add || !add->getMoleculeType())
            throw std::logic_error("NFsim add-molecule transform has no molecule type");
        NFsimPublicTransformView v;
        v.kind = add->isPopulationType() ? TransformationFactory::INCREMENT_POPULATION
                                          : TransformationFactory::ADD;
        v.reactant = 0;
        v.added_molecule_type = static_cast<std::uint32_t>(add->getMoleculeType()->getTypeID());
        if (add->isPopulationType()) v.population_delta = 1;
        views[0].push_back(v);
    }
    out=NFsimTransformDecoder::decode(views);
}
NativeModelSnapshot snapshotLegacyNFsim(System& system){NativeNFsimSystemReader reader(system);return readNFsimSystem(reader);}
LegacyLoweringResult lowerLegacyNFsim(System& system){
    const NativeModelSnapshot snapshot=snapshotLegacyNFsim(system);
    const LegacyModelIR legacy=NFsimSnapshotAdapter::toLegacy(snapshot);
    LegacyLoweringResult result=LegacyLowerer::lower(legacy);
    result.executable.validate();
    return result;
}
}
