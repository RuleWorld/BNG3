#include "PatternLowering.hpp"

#include <stdexcept>
#include <string>
#include <unordered_map>

#include "ast/Model.hpp"

namespace bng::compile {
namespace {

void setState(const PatternSiteDescriptor& site, BNGcore::Node& node) {
    const auto& stateType = node.get_type().get_state_type();
    const auto* labelType = dynamic_cast<const BNGcore::LabelStateType*>(&stateType);
    if (labelType == nullptr) return;
    const auto state = site.stateConstraint.empty() ? "?" : site.stateConstraint;
    node.set_state(BNGcore::LabelState(*labelType, state));
}

BNGcore::Node* addBond(BNGcore::PatternGraph& graph,
                       BondConstraintKind kind,
                       bool treatUnspecifiedBondAsWildcard) {
    BNGcore::Node value(BNGcore::BOND_NODE_TYPE);
    auto* bond = graph.add_node(value);
    if (kind == BondConstraintKind::Unbound) {
        bond->set_state(BNGcore::UNBOUND_STATE);
    } else if (kind == BondConstraintKind::Bound || kind == BondConstraintKind::Exact) {
        bond->set_state(BNGcore::BOUND_STATE);
    } else if (kind == BondConstraintKind::Any || treatUnspecifiedBondAsWildcard) {
        bond->set_state(BNGcore::BondState(BNGcore::BOND_STATE_TYPE,
                                           BNGcore::WILDCARD_STRING));
    } else {
        bond->set_state(BNGcore::UNBOUND_STATE);
    }
    return bond;
}

template <typename EnsureMolecule, typename EnsureComponent>
BNGcore::PatternGraph lowerPattern(const Pattern& pattern,
                                   EnsureMolecule&& ensureMolecule,
                                   EnsureComponent&& ensureComponent,
                                   bool treatUnspecifiedBondAsWildcard) {
    BNGcore::PatternGraph graph;
    std::unordered_map<std::size_t, BNGcore::Node*> exactBonds;

    for (const auto& molecule : pattern.molecules()) {
        BNGcore::Node moleculeValue(ensureMolecule(molecule));
        auto* moleculeNode = graph.add_node(moleculeValue);
        if (!molecule.compartment.empty()) moleculeNode->set_compartment(molecule.compartment);

        for (const auto& site : molecule.sites) {
            BNGcore::Node componentValue(ensureComponent(molecule, site));
            auto* componentNode = graph.add_node(componentValue);
            graph.add_edge(moleculeNode, componentNode);
            setState(site, *componentNode);
            if (!site.label.empty()) componentNode->set_label_tag(site.label);

            const auto addSiteBond = [&](BondConstraintKind kind, PatternBondGroupId group) {
                BNGcore::Node* bond = nullptr;
                if (kind == BondConstraintKind::Exact) {
                    auto [it, inserted] = exactBonds.emplace(group.value, nullptr);
                    if (inserted) it->second = addBond(graph, kind, treatUnspecifiedBondAsWildcard);
                    bond = it->second;
                } else {
                    bond = addBond(graph, kind, treatUnspecifiedBondAsWildcard);
                }
                graph.add_edge(componentNode, bond);
            };
            if (site.bondConstraints.empty()) {
                addSiteBond(site.bondKind, site.bondGroup);
            } else {
                for (const auto& bond : site.bondConstraints) addSiteBond(bond.kind, bond.group);
            }
        }
    }
    return graph;
}

} // namespace

const BNGcore::EntityType& BNGcoreLoweringContext::ensureMoleculeType(MoleculeTypeId id) {
    if (!id.valid()) throw std::invalid_argument("invalid molecule type ID");
    const auto existing = moleculeTypes_.find(id.value());
    if (existing != moleculeTypes_.end()) return *existing->second;
    const auto* molecule = model_->moleculeType(id);
    if (molecule == nullptr) throw std::invalid_argument("unknown molecule type ID");

    auto nodeType = std::make_unique<BNGcore::EntityType>(
        molecule->name, BNGcore::ENTITY_NODE_TYPE, BNGcore::NULL_STATE_TYPE);
    auto* raw = nodeType.get();
    moleculeTypes_.emplace(id.value(), std::move(nodeType));

    std::unordered_map<std::string, int> multiplicity;
    for (const auto& component : molecule->components) ++multiplicity[component.name];
    for (const auto& component : molecule->components) {
        const auto& componentType = ensureComponentType(component.id);
        raw->add_edges_out(const_cast<BNGcore::EntityType&>(componentType),
                           multiplicity[component.name]);
    }
    return *raw;
}

const BNGcore::EntityType& BNGcoreLoweringContext::ensureComponentType(ComponentTypeId id) {
    if (!id.valid()) throw std::invalid_argument("invalid component type ID");
    const auto existing = componentTypes_.find(id);
    if (existing != componentTypes_.end()) return *existing->second.nodeType;
    const auto* component = model_->component(id);
    const auto* molecule = model_->moleculeType(id.moleculeType);
    if (component == nullptr || molecule == nullptr)
        throw std::invalid_argument("unknown component type ID");

    ComponentRuntimeType runtime;
    const BNGcore::StateType* stateType = &BNGcore::NULL_STATE_TYPE;
    if (!component->stateNames.empty()) {
        auto labels = std::make_unique<BNGcore::LabelStateType>(
            molecule->name + "::" + component->name, component->stateNames.front());
        for (std::size_t i = 1; i < component->stateNames.size(); ++i)
            labels->add_state(component->stateNames[i]);
        stateType = labels.get();
        runtime.stateType = std::move(labels);
    }
    runtime.nodeType = std::make_unique<BNGcore::EntityType>(
        component->name, BNGcore::COMPONENT_NODE_TYPE, *stateType);
    runtime.nodeType->add_edges_out(BNGcore::BOND_NODE_TYPE, 1);
    const auto moleculeType = moleculeTypes_.find(id.moleculeType.value());
    if (moleculeType != moleculeTypes_.end())
        runtime.nodeType->add_edges_in(*moleculeType->second, 1);
    auto* raw = runtime.nodeType.get();
    componentTypes_.emplace(id, std::move(runtime));
    return *raw;
}

BNGcore::PatternGraph lowerPatternToBNGcore(const Pattern& pattern,
                                            BNGcoreLoweringContext& context,
                                            bool treatUnspecifiedBondAsWildcard) {
    if (!pattern.isResolved())
        throw std::invalid_argument("compiled pattern must be resolved before backend lowering");
    return lowerPattern(
        pattern,
        [&](const PatternMoleculeDescriptor& molecule) -> const BNGcore::EntityType& {
            if (!molecule.moleculeTypeId.has_value())
                throw std::invalid_argument("pattern molecule has no resolved type ID");
            return context.ensureMoleculeType(*molecule.moleculeTypeId);
        },
        [&](const PatternMoleculeDescriptor&, const PatternSiteDescriptor& site)
            -> const BNGcore::EntityType& {
            if (!site.componentType.has_value())
                throw std::invalid_argument("pattern site has no resolved component ID");
            return context.ensureComponentType(*site.componentType);
        },
        treatUnspecifiedBondAsWildcard);
}

BNGcore::PatternGraph lowerPatternToBNGcore(const Pattern& pattern,
                                            ast::Model& model,
                                            bool treatUnspecifiedBondAsWildcard) {
    return lowerPattern(
        pattern,
        [&](const PatternMoleculeDescriptor& molecule) -> const BNGcore::EntityType& {
            const auto* moleculeType = model.findMoleculeType(molecule.moleculeType);
            if (moleculeType == nullptr)
                throw std::invalid_argument("pattern references unknown molecule type: " +
                                            molecule.moleculeType);
            return model.getGraphTypeRegistry().ensureMoleculeType(*moleculeType);
        },
        [&](const PatternMoleculeDescriptor& molecule, const PatternSiteDescriptor& site)
            -> const BNGcore::EntityType& {
            const auto* moleculeType = model.findMoleculeType(molecule.moleculeType);
            if (moleculeType == nullptr)
                throw std::invalid_argument("pattern references unknown molecule type: " +
                                            molecule.moleculeType);
            for (const auto& component : moleculeType->getComponents()) {
                if (component.name == site.componentName)
                    return model.getGraphTypeRegistry().ensureComponentType(*moleculeType, component);
            }
            throw std::invalid_argument("pattern references unknown component " + site.componentName +
                                        " on molecule type " + molecule.moleculeType);
        },
        treatUnspecifiedBondAsWildcard);
}

} // namespace bng::compile
