#include "ThermodynamicConstraints.hpp"

#include <algorithm>
#include <deque>
#include <numeric>
#include <unordered_map>
#include <utility>

namespace bng::compile::energy {

namespace {

// Canonical undirected key for an edge: the sorted endpoint pair.
std::pair<std::string, std::string> canonicalEndpoints(const ThermodynamicEdge& edge) {
    return edge.from <= edge.to ? std::make_pair(edge.from, edge.to)
                                : std::make_pair(edge.to, edge.from);
}

// Disjoint-set over state indices. Used both for the connected-component count
// and for the greedy spanning forest.
class UnionFind {
public:
    explicit UnionFind(std::size_t count) : parent_(count) {
        std::iota(parent_.begin(), parent_.end(), std::size_t {0});
    }

    std::size_t find(std::size_t node) {
        while (parent_[node] != node) {
            parent_[node] = parent_[parent_[node]];
            node = parent_[node];
        }
        return node;
    }

    // Returns false when both endpoints were already connected.
    bool join(std::size_t left, std::size_t right) {
        const auto a = find(left);
        const auto b = find(right);
        if (a == b) return false;
        parent_[a] = b;
        return true;
    }

private:
    std::vector<std::size_t> parent_;
};

struct TreeAdjacency {
    std::size_t neighbor = 0;
    std::size_t edgeIndex = 0;
    // True when traversing neighbor-ward runs against the stored orientation.
    bool reversed = false;
};

} // namespace

ThermodynamicRatePair ThermodynamicRate::rates() const {
    // RT == 0 would make both directions meaningless; treat it as unit scale
    // rather than producing inf/nan, and leave the caller's validation to
    // reject the model. The compiler never constructs a zero-RT rate.
    const double scale = RT == 0.0 ? 1.0 : RT;
    const double drive = effectiveDeltaG();
    const double base = activationBarrier + barrierModifier;
    ThermodynamicRatePair pair;
    pair.forward = std::exp(-(base + phi * drive) / scale);
    pair.reverse = std::exp(-(base + (phi - 1.0) * drive) / scale);
    return pair;
}

void ThermodynamicGraph::addState(const std::string& state) {
    if (hasState(state)) return;
    states_.push_back(state);
}

bool ThermodynamicGraph::hasState(const std::string& state) const {
    return std::find(states_.begin(), states_.end(), state) != states_.end();
}

void ThermodynamicGraph::addReversibleEdge(
    const std::string& from,
    const std::string& to,
    double deltaG,
    double reservoirWork,
    double barrierModifier) {
    addState(from);
    addState(to);
    ThermodynamicEdge edge;
    edge.from = from;
    edge.to = to;
    edge.deltaG = deltaG;
    edge.reservoirWork = reservoirWork;
    edge.barrierModifier = barrierModifier;
    edges_.push_back(std::move(edge));
}

ThermodynamicAnalysis analyzeThermodynamics(
    const ThermodynamicGraph& graph,
    double tolerance) {
    ThermodynamicAnalysis analysis;

    // --- Deterministic state ordering -------------------------------------
    std::vector<std::string> sortedStates = graph.states();
    std::sort(sortedStates.begin(), sortedStates.end());
    std::unordered_map<std::string, std::size_t> stateIndex;
    stateIndex.reserve(sortedStates.size());
    for (std::size_t index = 0; index < sortedStates.size(); ++index) {
        stateIndex.emplace(sortedStates[index], index);
    }

    if (sortedStates.empty()) {
        analysis.connectedComponents = 0;
        analysis.cycleRank = 0;
        analysis.gaugeDegreesOfFreedom = 0;
        analysis.isEquilibriumCompatible = true;
        return analysis;
    }

    // --- Deterministic edge ordering --------------------------------------
    // Sort by canonical endpoint pair, then by stored orientation, then by the
    // original index. Two graphs that differ only in insertion order therefore
    // produce identical spanning forests and identical cycle bases.
    const auto& edges = graph.edges();
    std::vector<std::size_t> edgeOrder(edges.size());
    std::iota(edgeOrder.begin(), edgeOrder.end(), std::size_t {0});
    std::sort(edgeOrder.begin(), edgeOrder.end(),
              [&edges](std::size_t left, std::size_t right) {
                  const auto a = canonicalEndpoints(edges[left]);
                  const auto b = canonicalEndpoints(edges[right]);
                  if (a != b) return a < b;
                  const auto orientationA = std::make_pair(edges[left].from, edges[left].to);
                  const auto orientationB = std::make_pair(edges[right].from, edges[right].to);
                  if (orientationA != orientationB) return orientationA < orientationB;
                  return left < right;
              });

    // --- Spanning forest + non-tree edges ---------------------------------
    UnionFind forest(sortedStates.size());
    std::vector<std::vector<TreeAdjacency>> adjacency(sortedStates.size());
    std::vector<std::size_t> nonTreeEdges;
    for (const auto edgeIndex : edgeOrder) {
        const auto& edge = edges[edgeIndex];
        const auto from = stateIndex.at(edge.from);
        const auto to = stateIndex.at(edge.to);
        if (from != to && forest.join(from, to)) {
            adjacency[from].push_back(TreeAdjacency {to, edgeIndex, false});
            adjacency[to].push_back(TreeAdjacency {from, edgeIndex, true});
        } else {
            // Self-loops and edges closing a cycle both contribute one
            // independent cycle each.
            nonTreeEdges.push_back(edgeIndex);
        }
    }

    // --- Component count, cycle rank, gauge freedoms ----------------------
    std::vector<std::size_t> componentRoots;
    for (std::size_t index = 0; index < sortedStates.size(); ++index) {
        const auto root = forest.find(index);
        if (std::find(componentRoots.begin(), componentRoots.end(), root) ==
            componentRoots.end()) {
            componentRoots.push_back(root);
        }
    }
    analysis.connectedComponents = static_cast<int>(componentRoots.size());
    analysis.gaugeDegreesOfFreedom = analysis.connectedComponents;
    analysis.cycleRank = static_cast<int>(edges.size()) -
                         static_cast<int>(sortedStates.size()) +
                         analysis.connectedComponents;

    // --- Spanning-forest gauge --------------------------------------------
    // Pin the lexicographically smallest state of each component to zero, then
    // propagate the effective free energy differences along tree edges. The
    // sorted state order makes the reference state a property of the graph,
    // not of the caller.
    std::vector<bool> assigned(sortedStates.size(), false);
    std::vector<double> potential(sortedStates.size(), 0.0);
    for (std::size_t index = 0; index < sortedStates.size(); ++index) {
        if (assigned[index]) continue;
        assigned[index] = true;
        potential[index] = 0.0;
        std::deque<std::size_t> queue {index};
        while (!queue.empty()) {
            const auto current = queue.front();
            queue.pop_front();
            for (const auto& link : adjacency[current]) {
                if (assigned[link.neighbor]) continue;
                const auto& edge = edges[link.edgeIndex];
                // Walking current -> neighbor adds +dG_eff when that matches
                // the stored orientation and -dG_eff otherwise.
                const double step =
                    link.reversed ? -edge.effectiveDeltaG() : edge.effectiveDeltaG();
                potential[link.neighbor] = potential[current] + step;
                assigned[link.neighbor] = true;
                queue.push_back(link.neighbor);
            }
        }
    }
    for (std::size_t index = 0; index < sortedStates.size(); ++index) {
        analysis.statePotential.emplace(sortedStates[index], potential[index]);
    }

    // --- Fundamental cycles ------------------------------------------------
    // For non-tree edge {u, v}, the fundamental cycle is that edge plus the
    // unique tree path between its endpoints. It is traversed starting at the
    // lexicographically smaller endpoint so the orientation is a property of
    // the graph rather than of how the edge happened to be written.
    const auto treePath = [&](std::size_t origin, std::size_t target,
                              std::vector<std::size_t>& pathEdges,
                              std::vector<bool>& pathReversed,
                              std::vector<std::size_t>& pathStates) {
        // Breadth-first search restricted to forest edges; the path is unique.
        std::vector<bool> seen(sortedStates.size(), false);
        std::vector<std::size_t> previousState(sortedStates.size(), 0);
        std::vector<std::size_t> previousEdge(sortedStates.size(), 0);
        std::vector<bool> previousReversed(sortedStates.size(), false);
        std::deque<std::size_t> queue {origin};
        seen[origin] = true;
        bool found = origin == target;
        while (!queue.empty() && !found) {
            const auto current = queue.front();
            queue.pop_front();
            for (const auto& link : adjacency[current]) {
                if (seen[link.neighbor]) continue;
                seen[link.neighbor] = true;
                previousState[link.neighbor] = current;
                previousEdge[link.neighbor] = link.edgeIndex;
                previousReversed[link.neighbor] = link.reversed;
                if (link.neighbor == target) {
                    found = true;
                    break;
                }
                queue.push_back(link.neighbor);
            }
        }
        if (!found) return false;

        // Walk back from target to origin, then reverse into forward order.
        std::vector<std::size_t> reverseEdges;
        std::vector<bool> reverseFlags;
        std::vector<std::size_t> reverseStates;
        for (auto node = target; node != origin; node = previousState[node]) {
            reverseEdges.push_back(previousEdge[node]);
            reverseFlags.push_back(previousReversed[node]);
            reverseStates.push_back(node);
        }
        std::reverse(reverseEdges.begin(), reverseEdges.end());
        std::reverse(reverseFlags.begin(), reverseFlags.end());
        std::reverse(reverseStates.begin(), reverseStates.end());
        pathEdges = std::move(reverseEdges);
        pathReversed = std::move(reverseFlags);
        pathStates = std::move(reverseStates);
        return true;
    };

    for (const auto edgeIndex : nonTreeEdges) {
        const auto& edge = edges[edgeIndex];
        ThermodynamicCycle cycle;

        if (edge.from == edge.to) {
            // Self-loop: a one-edge cycle carrying its own effective drop.
            cycle.states.push_back(edge.from);
            cycle.edgeIndices.push_back(edgeIndex);
            cycle.reversed.push_back(false);
            cycle.affinity = -edge.effectiveDeltaG();
            analysis.cycleAffinities.push_back(cycle.affinity);
            analysis.cycles.push_back(std::move(cycle));
            continue;
        }

        // Canonical start is the smaller endpoint, so the traversal direction
        // does not depend on which way the caller wrote the edge.
        const bool storedForward = edge.from <= edge.to;
        const std::string& start = storedForward ? edge.from : edge.to;
        const std::string& finish = storedForward ? edge.to : edge.from;

        cycle.states.push_back(start);
        cycle.edgeIndices.push_back(edgeIndex);
        cycle.reversed.push_back(!storedForward);
        double sum = storedForward ? edge.effectiveDeltaG() : -edge.effectiveDeltaG();

        std::vector<std::size_t> pathEdges;
        std::vector<bool> pathReversed;
        std::vector<std::size_t> pathStates;
        if (treePath(stateIndex.at(finish), stateIndex.at(start), pathEdges,
                     pathReversed, pathStates)) {
            cycle.states.push_back(finish);
            for (std::size_t step = 0; step < pathEdges.size(); ++step) {
                const auto& pathEdge = edges[pathEdges[step]];
                const double contribution = pathReversed[step]
                                                ? -pathEdge.effectiveDeltaG()
                                                : pathEdge.effectiveDeltaG();
                sum += contribution;
                cycle.edgeIndices.push_back(pathEdges[step]);
                cycle.reversed.push_back(pathReversed[step]);
                // The final state closes the cycle and is not repeated.
                if (step + 1 < pathStates.size()) {
                    cycle.states.push_back(sortedStates[pathStates[step]]);
                }
            }
        }

        // Affinity is the net free energy released by one forward traversal,
        // hence the sign flip relative to the accumulated potential drop.
        cycle.affinity = -sum;
        analysis.cycleAffinities.push_back(cycle.affinity);
        analysis.cycles.push_back(std::move(cycle));
    }

    // --- Equilibrium compatibility ----------------------------------------
    for (std::size_t index = 0; index < analysis.cycleAffinities.size(); ++index) {
        if (std::fabs(analysis.cycleAffinities[index]) > tolerance) {
            analysis.isEquilibriumCompatible = false;
            analysis.drivenCycleIndices.push_back(index);
        }
    }

    for (const auto& edge : edges) {
        const auto from = stateIndex.at(edge.from);
        const auto to = stateIndex.at(edge.to);
        const double residual =
            std::fabs((potential[to] - potential[from]) - edge.effectiveDeltaG());
        analysis.maxEdgeResidual = std::max(analysis.maxEdgeResidual, residual);
    }

    return analysis;
}

} // namespace bng::compile::energy
