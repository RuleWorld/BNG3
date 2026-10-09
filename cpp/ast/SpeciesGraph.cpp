#include "SpeciesGraph.hpp"

#include <algorithm>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "core/List.hpp"
#include "core/Ullmann.hpp"

namespace bng::ast {

SpeciesGraph::SpeciesGraph(BNGcore::PatternGraph graph, std::string compartment)
    : graph_(std::move(graph)), compartment_(std::move(compartment)) {}

const BNGcore::PatternGraph& SpeciesGraph::getGraph() const {
    return graph_;
}

BNGcore::PatternGraph& SpeciesGraph::getGraph() {
    return graph_;
}

std::string SpeciesGraph::canonicalLabel() const {
    return graph_.get_label();
}

std::string SpeciesGraph::fingerprint() const {
    return graph_.computeFingerprint();
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

    std::vector<int> marked(n, -1);
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
        for (auto edge = left->edges_out_begin(); edge != left->edges_out_end(); ++edge) {
            const int target = (*edge)->get_index();
            if (target < 0 || static_cast<std::size_t>(target) >= n) {
                return false;
            }
            marked[target] = static_cast<int>(i);
        }
        for (auto edge = right->edges_out_begin(); edge != right->edges_out_end(); ++edge) {
            const int target = (*edge)->get_index();
            if (target < 0 || static_cast<std::size_t>(target) >= n ||
                marked[target] != static_cast<int>(i)) {
                return false;
            }
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

bool SpeciesGraph::graphIsomorphicTo(const BNGcore::PatternGraph& other) const {
    if (graph_.empty() || other.empty()) {
        return graph_.get_BNG2_string() == other.get_BNG2_string();
    }
    if (graph_.size() != other.size()) {
        return false;
    }
    if (indexCorrespondenceIsWitness(graph_, other)) {
        return true;
    }

    BNGcore::UllmannSGIso matcher(graph_, other);
    BNGcore::List<BNGcore::Map> maps;
    matcher.find_maps(maps);
    for (auto map = maps.begin(); map != maps.end(); ++map) {
        if (mapIsExactLabeledIsomorphism(graph_, other, *map)) {
            return true;
        }
    }
    return false;
}

std::string SpeciesGraph::toString() const {
    return graph_.get_BNG2_string();
}

std::string SpeciesGraph::toStringForDedup() const {
    // Perl convention: the dedup key includes the species compartment prefix
    // and per-molecule compartments only when they differ from species-level.
    // This matches Perl's SpeciesGraph::toString(1,0) which passes $sg->Compartment
    // to Molecule::toString, which conditionally appends @comp.
    std::vector<std::string> molComps;
    std::string base = graph_.get_BNG2_string(molComps);

    // Unscoped species: the result is exactly the base serialization, so hand
    // it back directly instead of copying it through an empty accumulator.
    if (compartment_.empty()) {
        return base;
    }
    std::string result = "@" + compartment_ + "::";

    // Annotate molecules with compartments that differ from species-level
    if (!molComps.empty()) {
        std::size_t molIdx = 0, pos = 0;
        while (pos < base.size()) {
            int parenDepth = 0;
            std::size_t molEnd = pos;
            while (molEnd < base.size()) {
                if (base[molEnd] == '(') parenDepth++;
                else if (base[molEnd] == ')') parenDepth--;
                else if (base[molEnd] == '.' && parenDepth == 0) break;
                molEnd++;
            }
            result.append(base, pos, molEnd - pos);
            if (molIdx < molComps.size() && !molComps[molIdx].empty() &&
                molComps[molIdx] != compartment_) {
                result += "@" + molComps[molIdx];
            }
            if (molEnd < base.size() && base[molEnd] == '.') {
                result += '.';
                molEnd++;
            }
            pos = molEnd;
            molIdx++;
        }
    } else {
        result += base;
    }

    return result;
}

const std::string& SpeciesGraph::getCompartment() const {
    return compartment_;
}

void SpeciesGraph::setCompartment(std::string compartment) {
    compartment_ = std::move(compartment);
}

namespace {

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

} // namespace

bool SpeciesGraph::isConnected() const {
    return numComponents() <= 1;
}

size_t SpeciesGraph::numComponents() const {
    BNGcore::PatternGraph copy(graph_);
    BNGcore::patterngraph_container_t split_graphs;
    copy.split_connected(split_graphs);
    return split_graphs.size();
}

std::vector<SpeciesGraph> SpeciesGraph::splitConnectedComponents() const {
    BNGcore::PatternGraph copy(graph_);
    BNGcore::patterngraph_container_t split_graphs;
    copy.split_connected(split_graphs);
    std::vector<SpeciesGraph> result;
    while (!split_graphs.empty()) {
        BNGcore::PatternGraph* pg = split_graphs.withdraw_back();
        result.push_back(SpeciesGraph(std::move(*pg), compartment_));
        delete pg;
    }
    std::reverse(result.begin(), result.end());
    return result;
}

std::map<std::string, size_t> SpeciesGraph::stoichiometry() const {
    std::map<std::string, size_t> counts;
    for (auto nodeIter = graph_.begin(); nodeIter != graph_.end(); ++nodeIter) {
        if (isMoleculeNode(**nodeIter)) {
            ++counts[(*nodeIter)->get_type().get_type_name()];
        }
    }
    return counts;
}

std::string SpeciesGraph::inferCompartment(const std::vector<Compartment>& hierarchy) const {
    std::vector<std::string> molComps;
    for (auto nodeIter = graph_.begin(); nodeIter != graph_.end(); ++nodeIter) {
        if (isMoleculeNode(**nodeIter)) {
            const std::string& c = (*nodeIter)->get_compartment();
            if (!c.empty()) {
                molComps.push_back(c);
            }
        }
    }
    if (molComps.empty()) {
        return "";
    }
    bool allSame = true;
    for (size_t i = 1; i < molComps.size(); ++i) {
        if (molComps[i] != molComps[0]) {
            allSame = false;
            break;
        }
    }
    if (allSame) {
        return molComps[0];
    }

    std::map<std::string, const Compartment*> compMap;
    for (const auto& comp : hierarchy) {
        compMap[comp.getName()] = &comp;
    }

    std::vector<const Compartment*> uniqueComps;
    std::vector<std::string> uniqueNames;
    for (const auto& c : molComps) {
        if (std::find(uniqueNames.begin(), uniqueNames.end(), c) == uniqueNames.end()) {
            uniqueNames.push_back(c);
            auto it = compMap.find(c);
            if (it != compMap.end()) {
                uniqueComps.push_back(it->second);
            }
        }
    }

    if (uniqueComps.empty()) {
        return "";
    }

    const Compartment* surfaceComp = nullptr;
    for (const auto* c : uniqueComps) {
        if (c->isSurface()) {
            surfaceComp = c;
            break;
        }
    }

    if (surfaceComp) {
        return surfaceComp->getName();
    }

    auto getDepth = [&](const Compartment* c) {
        int depth = 0;
        const Compartment* current = c;
        while (current && !current->getParent().empty()) {
            depth++;
            auto it = compMap.find(current->getParent());
            if (it != compMap.end()) {
                current = it->second;
            } else {
                break;
            }
        }
        return depth;
    };

    const Compartment* outermost = uniqueComps[0];
    int minDepth = getDepth(outermost);
    for (size_t i = 1; i < uniqueComps.size(); ++i) {
        int d = getDepth(uniqueComps[i]);
        if (d < minDepth) {
            minDepth = d;
            outermost = uniqueComps[i];
        }
    }

    return outermost->getName();
}

} // namespace bng::ast
