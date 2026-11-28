#include "BarrierCompiler.hpp"

#include <algorithm>
#include <utility>

#include "ast/BarrierPattern.hpp"
#include "ast/Model.hpp"
#include "ast/ReactionRule.hpp"
#include "ast/SpeciesGraph.hpp"
#include "core/BNGcore.hpp"

namespace bng::compile::energy {

namespace {

bool isBondNode(const BNGcore::Node& node) {
    return node.get_type().get_type_name() == BNGcore::BOND_NODE_TYPE.get_type_name();
}

bool isComponentNode(const BNGcore::Node& node) {
    if (isBondNode(node)) return false;
    for (auto edge = node.edges_in_begin(); edge != node.edges_in_end(); ++edge) {
        if (!isBondNode(**edge)) return true;
    }
    return false;
}

bool isMoleculeNode(const BNGcore::Node& node) {
    return !isBondNode(node) && !isComponentNode(node);
}

struct FlatComponent {
    const BNGcore::Node* node = nullptr;
    std::string name;
};

struct FlatMolecule {
    const BNGcore::Node* node = nullptr;
    std::string name;
    std::vector<FlatComponent> components;
};

// Same traversal the NFsim direct adapter uses, restated here so the compile
// layer does not depend on the NFsim translation unit.
std::vector<FlatMolecule> flattenMolecules(const BNGcore::PatternGraph& graph) {
    std::vector<FlatMolecule> result;
    for (auto node = graph.begin(); node != graph.end(); ++node) {
        if (!isMoleculeNode(**node)) continue;
        FlatMolecule molecule;
        molecule.node = *node;
        molecule.name = (*node)->get_type().get_type_name();
        for (auto edge = (*node)->edges_out_begin(); edge != (*node)->edges_out_end();
             ++edge) {
            if (!isComponentNode(**edge)) continue;
            FlatComponent component;
            component.node = *edge;
            component.name = (*edge)->get_type().get_type_name();
            molecule.components.push_back(std::move(component));
        }
        result.push_back(std::move(molecule));
    }
    return result;
}

std::string stateToken(const BNGcore::Node& node) {
    const std::string state = node.get_state().get_BNG2_string();
    if (state.empty()) return {};
    return state.front() == '~' ? state.substr(1) : state;
}

// Resolves a rule-relative component reference to (moleculeType, component).
bool resolveComponent(
    const std::vector<ast::SpeciesGraph>& patterns,
    const ast::ReactionRule::ComponentRef& ref,
    std::string& moleculeType,
    std::string& componentName,
    std::string& state,
    std::string& diagnostic) {
    if (ref.patternIndex >= patterns.size()) {
        diagnostic = "reaction center refers to an unknown pattern";
        return false;
    }
    const auto molecules = flattenMolecules(patterns[ref.patternIndex].getGraph());
    if (ref.moleculeIndex >= molecules.size()) {
        diagnostic = "reaction center refers to an unknown molecule";
        return false;
    }
    const auto& molecule = molecules[ref.moleculeIndex];
    if (ref.componentIndex >= molecule.components.size()) {
        diagnostic = "reaction center refers to an unknown component";
        return false;
    }
    moleculeType = molecule.name;
    componentName = molecule.components[ref.componentIndex].name;
    state = stateToken(*molecule.components[ref.componentIndex].node);
    return true;
}

bool hasConcreteStateConstraint(const BNGcore::Node& componentNode) {
    const std::string state = stateToken(componentNode);
    return !state.empty() && state != "?";
}

bool hasNonWildcardBondConstraint(const BNGcore::Node& componentNode) {
    for (auto edge = componentNode.edges_out_begin();
         edge != componentNode.edges_out_end(); ++edge) {
        if (!isBondNode(**edge)) continue;
        const std::string bondState = (*edge)->get_state().get_BNG2_string();
        if (bondState != "!?") return true;
    }
    return false;
}

// A BarrierTable entry is keyed only by its single reaction center, so any
// extra spectator molecule or non-wildcard context constraint on a barrier
// pattern would be silently stripped and leak onto unrelated species. Fail
// closed when such context is present on a barrier pattern.
bool validateUnconditionalBarrierTransition(
    const ast::ReactionRule& transition,
    std::string& diagnostic) {
    const auto& operations = transition.getOperations();
    if (operations.size() != 1) return false;
    const auto& operation = operations.front();
    const auto& reactants = transition.getReactantPatterns();

    std::size_t totalMolecules = 0;
    std::vector<std::vector<FlatMolecule>> flatReactants;
    flatReactants.reserve(reactants.size());
    for (const auto& reactant : reactants) {
        auto molecules = flattenMolecules(reactant.getGraph());
        totalMolecules += molecules.size();
        flatReactants.push_back(std::move(molecules));
    }

    using Type = ast::ReactionRule::TransformOp::Type;
    switch (operation.type) {
    case Type::ChangeState: {
        if (totalMolecules != 1) {
            diagnostic = "barrier state transition with extra context molecules is not supported";
            return false;
        }
        const auto& molecule =
            flatReactants[operation.source.patternIndex][operation.source.moleculeIndex];
        for (std::size_t ci = 0; ci < molecule.components.size(); ++ci) {
            if (ci == operation.source.componentIndex) continue;
            const auto& comp = molecule.components[ci];
            if (hasConcreteStateConstraint(*comp.node) ||
                hasNonWildcardBondConstraint(*comp.node)) {
                diagnostic = "barrier pattern with context constraint on '" +
                             molecule.name + "." + comp.name + "' is not supported";
                return false;
            }
        }
        return true;
    }
    case Type::AddBond:
    case Type::DeleteBond: {
        const bool intramolecular =
            operation.source.patternIndex == operation.partner.patternIndex &&
            operation.source.moleculeIndex == operation.partner.moleculeIndex;
        const std::size_t expectedMolecules = intramolecular ? 1 : 2;
        if (totalMolecules != expectedMolecules) {
            diagnostic = "barrier bond transition with extra context molecules is not supported";
            return false;
        }
        for (std::size_t pi = 0; pi < flatReactants.size(); ++pi) {
            for (std::size_t mi = 0; mi < flatReactants[pi].size(); ++mi) {
                const auto& molecule = flatReactants[pi][mi];
                for (std::size_t ci = 0; ci < molecule.components.size(); ++ci) {
                    const bool isCenter =
                        (pi == operation.source.patternIndex &&
                         mi == operation.source.moleculeIndex &&
                         ci == operation.source.componentIndex) ||
                        (pi == operation.partner.patternIndex &&
                         mi == operation.partner.moleculeIndex &&
                         ci == operation.partner.componentIndex);
                    const auto& comp = molecule.components[ci];
                    if (isCenter) {
                        if (hasConcreteStateConstraint(*comp.node)) {
                            diagnostic = "barrier bond transition with state constraint on '" +
                                         molecule.name + "." + comp.name + "' is not supported";
                            return false;
                        }
                    } else if (hasConcreteStateConstraint(*comp.node) ||
                               hasNonWildcardBondConstraint(*comp.node)) {
                        diagnostic = "barrier pattern with context constraint on '" +
                                     molecule.name + "." + comp.name + "' is not supported";
                        return false;
                    }
                }
            }
        }
        return true;
    }
    default:
        return true;
    }
}

} // namespace

bool compileBarrierCenter(
    const ast::ReactionRule& transition,
    ReactionCenterKey& key,
    std::string& diagnostic) {
    const auto& operations = transition.getOperations();
    if (operations.empty()) {
        diagnostic = "barrier transition does not change anything";
        return false;
    }
    // A compound rewrite has no single transition state to attach a barrier
    // to. Rejecting it is the documented fail-closed behavior; the compact
    // representation is deliberately not generalized here.
    if (operations.size() != 1) {
        diagnostic = "barrier transitions support exactly one state or bond change, found " +
                     std::to_string(operations.size());
        return false;
    }

    const auto& operation = operations.front();
    // Both AddBond and DeleteBond carry reactant-side component references:
    // the added bond's endpoints are reactant-mapped, and a deleted bond only
    // exists on the reactant side.
    const auto& reactants = transition.getReactantPatterns();

    using Type = ast::ReactionRule::TransformOp::Type;
    switch (operation.type) {
    case Type::ChangeState: {
        std::string moleculeType;
        std::string componentName;
        std::string fromState;
        if (!resolveComponent(reactants, operation.source, moleculeType, componentName,
                              fromState, diagnostic)) {
            return false;
        }
        if (fromState.empty() || fromState == "?" || fromState == "*") {
            diagnostic = "barrier state transition needs an explicit source state";
            return false;
        }
        const auto& toState = operation.newState;
        if (toState.empty() || toState == "PLUS" || toState == "MINUS") {
            diagnostic = "barrier state transition needs an explicit target state";
            return false;
        }
        if (toState == fromState) {
            diagnostic = "barrier state transition does not change the state";
            return false;
        }
        key = ReactionCenterKey::stateChange(moleculeType, componentName, fromState, toState);
        return true;
    }
    case Type::AddBond:
    case Type::DeleteBond: {
        // Bond formation and dissociation cross the same transition state, so
        // both map to the same symmetric binding key.
        std::string typeA;
        std::string nameA;
        std::string stateA;
        std::string typeB;
        std::string nameB;
        std::string stateB;
        if (!resolveComponent(reactants, operation.source, typeA, nameA, stateA, diagnostic) ||
            !resolveComponent(reactants, operation.partner, typeB, nameB, stateB, diagnostic)) {
            return false;
        }
        key = ReactionCenterKey::binding(typeA, nameA, typeB, nameB);
        return true;
    }
    case Type::AddMolecule:
    case Type::DeleteMolecule:
        diagnostic = "barrier transitions do not support molecule creation or deletion";
        return false;
    }

    // Defensive: an operation kind added later must fail closed rather than
    // fall through to an unkeyed barrier.
    diagnostic = "unsupported barrier transition rewrite";
    return false;
}

bool buildBarrierTable(
    const ast::Model& model,
    const std::function<bool(const ast::BarrierPattern&, double&, std::string&)>&
        resolveEnergy,
    BarrierTable& table,
    std::vector<std::string>& diagnostics) {
    bool ok = true;
    for (std::size_t index = 0; index < model.getBarrierPatterns().size(); ++index) {
        const auto& pattern = model.getBarrierPatterns()[index];
        const std::string label = pattern.getLabel().empty()
                                      ? "barrier_" + std::to_string(index + 1)
                                      : pattern.getLabel();

        if (!pattern.hasExpression()) {
            diagnostics.push_back("barrier pattern '" + label +
                                  "' has no transition-state energy expression");
            ok = false;
            continue;
        }

        ReactionCenterKey key;
        std::string diagnostic;
        if (!compileBarrierCenter(pattern.transition(), key, diagnostic) ||
            !validateUnconditionalBarrierTransition(pattern.transition(), diagnostic)) {
            diagnostics.push_back("barrier pattern '" + label + "': " + diagnostic);
            ok = false;
            continue;
        }

        double barrier = 0.0;
        if (!resolveEnergy(pattern, barrier, diagnostic)) {
            diagnostics.push_back("barrier pattern '" + label + "': " + diagnostic);
            ok = false;
            continue;
        }

        if (!table.add(key, barrier, label, diagnostic)) {
            diagnostics.push_back(diagnostic);
            ok = false;
        }
    }
    return ok;
}

} // namespace bng::compile::energy
