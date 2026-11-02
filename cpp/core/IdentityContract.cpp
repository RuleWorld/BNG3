#include "IdentityContract.hpp"

#include <algorithm>
#include <unordered_map>
#include <unordered_set>

#include "BNGcore.hpp"
#include "List.hpp"
#include "Ullmann.hpp"

namespace bng::identity {

const char* layerName(Layer layer) {
    switch (layer) {
        case Layer::Structure:
            return "structure";
        case Layer::Compartment:
            return "structure+compartment";
        case Layer::Species:
            return "species";
    }
    return "unknown";
}

bool layerIncludes(Layer outer, Layer inner) {
    if (outer == inner) {
        return true;
    }
    switch (outer) {
        case Layer::Structure:
            return false;
        case Layer::Compartment:
            return inner == Layer::Structure;
        case Layer::Species:
            return true;
    }
    return false;
}

bool isBondNode(const BNGcore::Node& node) {
    return node.get_type().get_type_name() == BNGcore::BOND_NODE_TYPE.get_type_name();
}

bool isComponentNode(const BNGcore::Node& node) {
    if (isBondNode(node)) {
        return false;
    }
    for (auto edge = node.edges_in_begin(); edge != node.edges_in_end(); ++edge) {
        if (!isBondNode(**edge)) {
            return true;
        }
    }
    return false;
}

bool isMoleculeNode(const BNGcore::Node& node) {
    return !isBondNode(node) && !isComponentNode(node);
}

bool MoleculeKey::operator==(const MoleculeKey& other) const {
    return type == other.type && components == other.components;
}

bool MoleculeKey::operator<(const MoleculeKey& other) const {
    if (type != other.type) {
        return type < other.type;
    }
    return components < other.components;
}

std::vector<MoleculeKey> moleculeKeys(const BNGcore::PatternGraph& graph) {
    std::vector<MoleculeKey> keys;
    for (auto node = graph.begin(); node != graph.end(); ++node) {
        if (!isMoleculeNode(**node)) {
            continue;
        }
        MoleculeKey key;
        key.type = (*node)->get_type().get_type_name();
        for (auto edge = (*node)->edges_out_begin();
             edge != (*node)->edges_out_end(); ++edge) {
            if (!isComponentNode(**edge)) {
                continue;
            }
            // The bond state of a site is part of the molecule's content: a
            // bound site, a free site and a wildcard bond are different.
            int bonds = 0;
            for (auto bond = (*edge)->edges_out_begin();
                 bond != (*edge)->edges_out_end(); ++bond) {
                if (!isBondNode(**bond)) {
                    continue;
                }
                const std::string state = (*bond)->get_state().get_BNG2_string();
                if (state == "!+") {
                    bonds = 1;
                } else if (state == "!-") {
                    bonds = 0;
                } else {
                    bonds = -1;
                }
            }
            key.components.emplace_back((*edge)->get_type().get_type_name(), bonds);
        }
        std::sort(key.components.begin(), key.components.end());
        keys.push_back(std::move(key));
    }
    std::sort(keys.begin(), keys.end());
    return keys;
}

std::vector<std::string> moleculeCompartments(const BNGcore::PatternGraph& graph) {
    std::vector<std::string> compartments;
    for (auto node = graph.begin(); node != graph.end(); ++node) {
        if (!isMoleculeNode(**node)) {
            continue;
        }
        compartments.push_back((*node)->get_compartment());
    }
    return compartments;
}

namespace {

// A verified index-for-index correspondence avoids the general search for
// already aligned graphs. Every node label, compartment, degree, and outgoing
// edge is checked, so this is a sufficient witness rather than a heuristic.
bool indexCorrespondenceIsWitness(const BNGcore::PatternGraph& lhs,
                                  const BNGcore::PatternGraph& rhs) {
    const std::size_t n = lhs.size();
    if (n != rhs.size()) {
        return false;
    }

    std::vector<const BNGcore::Node*> lhsNodes(n, nullptr);
    std::vector<const BNGcore::Node*> rhsNodes(n, nullptr);
    const auto indexNodes = [n](const BNGcore::PatternGraph& graph,
                                std::vector<const BNGcore::Node*>& slots) {
        for (auto it = graph.begin(); it != graph.end(); ++it) {
            const int index = (*it)->get_index();
            if (index < 0 || static_cast<std::size_t>(index) >= n ||
                slots[index] != nullptr) {
                return false;
            }
            slots[index] = *it;
        }
        return true;
    };
    if (!indexNodes(lhs, lhsNodes) || !indexNodes(rhs, rhsNodes)) {
        return false;
    }

    for (std::size_t i = 0; i < n; ++i) {
        const BNGcore::Node* left = lhsNodes[i];
        const BNGcore::Node* right = rhsNodes[i];
        if (left == nullptr || right == nullptr ||
            !(left->get_type() == right->get_type()) ||
            left->get_state().get_BNG2_string() !=
                right->get_state().get_BNG2_string() ||
            left->get_compartment() != right->get_compartment() ||
            left->out_degree() != right->out_degree()) {
            return false;
        }
        std::vector<int> leftTargets;
        std::vector<int> rightTargets;
        leftTargets.reserve(left->out_degree());
        rightTargets.reserve(right->out_degree());
        for (auto edge = left->edges_out_begin(); edge != left->edges_out_end(); ++edge) {
            const int target = (*edge)->get_index();
            if (target < 0 || static_cast<std::size_t>(target) >= n ||
                lhsNodes[static_cast<std::size_t>(target)] != *edge) {
                return false;
            }
            leftTargets.push_back(target);
        }
        for (auto edge = right->edges_out_begin(); edge != right->edges_out_end(); ++edge) {
            const int target = (*edge)->get_index();
            if (target < 0 || static_cast<std::size_t>(target) >= n ||
                rhsNodes[static_cast<std::size_t>(target)] != *edge) {
                return false;
            }
            rightTargets.push_back(target);
        }
        std::sort(leftTargets.begin(), leftTargets.end());
        std::sort(rightTargets.begin(), rightTargets.end());
        if (leftTargets != rightTargets) {
            return false;
        }
    }
    return true;
}

bool mapIsExactLabeledIsomorphism(const BNGcore::PatternGraph& lhs,
                                  const BNGcore::PatternGraph& rhs,
                                  const BNGcore::Map& map) {
    std::unordered_set<const BNGcore::Node*> mappedNodes;
    for (auto node = lhs.begin(); node != lhs.end(); ++node) {
        const auto* mapped = map.mapf(*node);
        if (mapped == nullptr ||
            !((*node)->get_type() == mapped->get_type()) ||
            (*node)->get_state().get_BNG2_string() !=
                mapped->get_state().get_BNG2_string() ||
            (*node)->get_compartment() != mapped->get_compartment() ||
            (*node)->out_degree() != mapped->out_degree() ||
            !mappedNodes.insert(mapped).second) {
            return false;
        }

        std::unordered_map<const BNGcore::Node*, std::size_t> expectedEdges;
        for (auto edge = (*node)->edges_out_begin();
             edge != (*node)->edges_out_end(); ++edge) {
            const auto* mappedTarget = map.mapf(*edge);
            if (mappedTarget == nullptr) {
                return false;
            }
            ++expectedEdges[mappedTarget];
        }
        std::unordered_map<const BNGcore::Node*, std::size_t> actualEdges;
        for (auto edge = mapped->edges_out_begin();
             edge != mapped->edges_out_end(); ++edge) {
            ++actualEdges[*edge];
        }
        if (expectedEdges != actualEdges) {
            return false;
        }
    }
    return mappedNodes.size() == rhs.size();
}

} // namespace

bool sameMoleculeGraph(const BNGcore::PatternGraph& lhs,
                        const BNGcore::PatternGraph& rhs) {
    if (lhs.empty() || rhs.empty()) {
        return lhs.get_BNG2_string() == rhs.get_BNG2_string();
    }
    if (lhs.size() != rhs.size()) {
        return false;
    }
    if (indexCorrespondenceIsWitness(lhs, rhs)) {
        return true;
    }

    BNGcore::UllmannSGIso matcher(lhs, rhs);
    BNGcore::List<BNGcore::Map> maps;
    matcher.find_maps(maps);
    for (auto map = maps.begin(); map != maps.end(); ++map) {
        if (mapIsExactLabeledIsomorphism(lhs, rhs, *map)) {
            return true;
        }
    }
    return false;
}

} // namespace bng::identity
