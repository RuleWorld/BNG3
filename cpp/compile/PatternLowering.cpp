#include "PatternLowering.hpp"

#include <stdexcept>
#include <string>
#include <unordered_map>

#include "ast/Model.hpp"

namespace bng::compile {
namespace {

const ast::MoleculeType& findMoleculeType(const ast::Model& model,
                                          const std::string& name) {
    const auto* moleculeType = model.findMoleculeType(name);
    if (moleculeType == nullptr) {
        throw std::invalid_argument("pattern references unknown molecule type: " + name);
    }
    return *moleculeType;
}

const ast::ComponentType& findComponentType(const ast::MoleculeType& moleculeType,
                                            const std::string& name) {
    for (const auto& component : moleculeType.getComponents()) {
        if (component.name == name) return component;
    }
    throw std::invalid_argument("pattern references unknown component " + name +
                                " on molecule type " + moleculeType.getName());
}

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
    } else if (kind == BondConstraintKind::Bound ||
               kind == BondConstraintKind::Exact) {
        bond->set_state(BNGcore::BOUND_STATE);
    } else if (kind == BondConstraintKind::Any ||
               treatUnspecifiedBondAsWildcard) {
        bond->set_state(BNGcore::BondState(BNGcore::BOND_STATE_TYPE,
                                           BNGcore::WILDCARD_STRING));
    } else {
        bond->set_state(BNGcore::UNBOUND_STATE);
    }
    return bond;
}

} // namespace

BNGcore::PatternGraph lowerPatternToBNGcore(const Pattern& pattern,
                                            ast::Model& model,
                                            bool treatUnspecifiedBondAsWildcard) {
    BNGcore::PatternGraph graph;
    std::unordered_map<std::size_t, BNGcore::Node*> exactBonds;

    for (const auto& molecule : pattern.molecules()) {
        const auto& moleculeType = findMoleculeType(model, molecule.moleculeType);
        BNGcore::Node moleculeValue(
            model.getGraphTypeRegistry().ensureMoleculeType(moleculeType));
        auto* moleculeNode = graph.add_node(moleculeValue);
        if (!molecule.compartment.empty()) {
            moleculeNode->set_compartment(molecule.compartment);
        }

        for (const auto& site : molecule.sites) {
            const auto& componentType = findComponentType(moleculeType, site.componentName);
            BNGcore::Node componentValue(
                model.getGraphTypeRegistry().ensureComponentType(moleculeType,
                                                                  componentType));
            auto* componentNode = graph.add_node(componentValue);
            graph.add_edge(moleculeNode, componentNode);
            setState(site, *componentNode);
            if (!site.label.empty()) componentNode->set_label_tag(site.label);

            const auto addSiteBond = [&](BondConstraintKind kind,
                                         PatternBondGroupId group) {
                BNGcore::Node* bond = nullptr;
                if (kind == BondConstraintKind::Exact) {
                    auto [it, inserted] = exactBonds.emplace(group.value, nullptr);
                    if (inserted) it->second = addBond(
                        graph, kind, treatUnspecifiedBondAsWildcard);
                    bond = it->second;
                } else {
                    bond = addBond(graph, kind, treatUnspecifiedBondAsWildcard);
                }
                graph.add_edge(componentNode, bond);
            };
            if (site.bondConstraints.empty()) {
                addSiteBond(site.bondKind, site.bondGroup);
            } else {
                for (const auto& bond : site.bondConstraints) {
                    addSiteBond(bond.kind, bond.group);
                }
            }
        }
    }
    return graph;
}

} // namespace bng::compile
