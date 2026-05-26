#include "SpeciesGraph.hpp"

#include <utility>
#include <algorithm>

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

    std::string result;
    if (!compartment_.empty()) {
        result += "@" + compartment_ + "::";
    }

    // Annotate molecules with compartments that differ from species-level
    if (!compartment_.empty() && !molComps.empty()) {
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
            result += base.substr(pos, molEnd - pos);
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
