#pragma once

// Backend-neutral thermodynamic bookkeeping for energy-based rules.
//
// This layer answers three questions that the existing eBNGL machinery does
// not, and that nonequilibrium (driven) rules make unavoidable:
//
//   1. Given a set of reversible transitions annotated with ground-state free
//      energy differences and signed reservoir work, is the resulting kinetics
//      compatible with detailed balance?
//   2. If it is, what state potential reproduces the edge differences (and how
//      many gauge freedoms does that potential have)?
//   3. If it is not, which fundamental cycles carry nonzero affinity?
//
// It deliberately knows nothing about BNGL, patterns, or NFsim. It operates on
// an abstract labelled state graph so it can be driven from the compiler, from
// a test, or from a diagnostic tool without constructing a model.
//
// Rate convention (see ThermodynamicRate):
//
//   k_f = exp[-(Ea + B + phi      * (dG - W)) / RT]
//   k_r = exp[-(Ea + B + (phi - 1) * (dG - W)) / RT]
//
// where
//   Ea = activation energy carried by the rule (Arrhenius first form),
//   B  = matched transition-state/barrier contribution,
//   dG = ground-state free energy difference of the transition,
//   W  = signed work supplied by a driving reservoir,
//   phi = Arrhenius distribution parameter.
//
// Two properties follow directly and are asserted by the tests:
//   * B cancels in k_f / k_r, so barriers change kinetics but not local
//     detailed balance;
//   * k_f / k_r = exp[-(dG - W) / RT], so reservoir work shifts local detailed
//     balance and can sustain a nonzero cycle affinity.

#include <cmath>
#include <cstddef>
#include <map>
#include <string>
#include <vector>

namespace bng::compile::energy {

// Forward/reverse rate pair produced by a single annotated transition.
struct ThermodynamicRatePair {
    double forward = 0.0;
    double reverse = 0.0;
};

// One annotated reversible transition. Field names are part of the published
// contract; the compiler fills them from rule metadata.
struct ThermodynamicRate {
    // Ground-state free energy change of the transition (product - reactant).
    double stateDeltaG = 0.0;
    // Activation energy from the rule's Arrhenius rate law.
    double activationBarrier = 0.0;
    // Matched barrier-pattern contribution. Enters both directions equally.
    double barrierModifier = 0.0;
    // Signed reservoir work consumed by the forward direction.
    double reservoirWork = 0.0;
    // Arrhenius distribution parameter.
    double phi = 0.5;
    // Gas constant times temperature, in the same units as the energies.
    double RT = 1.0;

    // Effective free energy difference seen by local detailed balance.
    double effectiveDeltaG() const { return stateDeltaG - reservoirWork; }

    ThermodynamicRatePair rates() const;
};

// One reversible edge of the state graph, oriented from -> to.
struct ThermodynamicEdge {
    std::string from;
    std::string to;
    double deltaG = 0.0;
    double reservoirWork = 0.0;
    double barrierModifier = 0.0;

    double effectiveDeltaG() const { return deltaG - reservoirWork; }
};

// Labelled state graph. States may be declared explicitly (so that isolated
// states still contribute a connected component and a gauge freedom) or
// created implicitly by adding an edge.
class ThermodynamicGraph {
public:
    // Declares a state. Repeated declarations are ignored.
    void addState(const std::string& state);

    // Declares a reversible transition. Endpoints are created if unknown.
    void addReversibleEdge(
        const std::string& from,
        const std::string& to,
        double deltaG,
        double reservoirWork,
        double barrierModifier = 0.0);

    const std::vector<std::string>& states() const { return states_; }
    const std::vector<ThermodynamicEdge>& edges() const { return edges_; }

    bool hasState(const std::string& state) const;
    std::size_t stateCount() const { return states_.size(); }
    std::size_t edgeCount() const { return edges_.size(); }

private:
    // Insertion-ordered for reporting; analysis sorts independently so results
    // never depend on the order in which a caller built the graph.
    std::vector<std::string> states_;
    std::vector<ThermodynamicEdge> edges_;
};

// One fundamental cycle of the state graph, expressed in canonical traversal
// order. `affinity` is the net effective free energy released around the cycle:
// zero for every cycle iff the kinetics admit a state potential.
struct ThermodynamicCycle {
    // States visited, in canonical traversal order, starting and ending at the
    // same state (the closing state is not repeated).
    std::vector<std::string> states;
    // Indices into ThermodynamicGraph::edges(), in traversal order.
    std::vector<std::size_t> edgeIndices;
    // True where the edge was traversed against its stored orientation.
    std::vector<bool> reversed;
    double affinity = 0.0;
};

struct ThermodynamicAnalysis {
    int connectedComponents = 0;
    // E - V + C.
    int cycleRank = 0;
    // One arbitrary reference potential per connected component.
    int gaugeDegreesOfFreedom = 0;
    // Affinity of each fundamental cycle, in canonical cycle order.
    std::vector<double> cycleAffinities;
    std::vector<ThermodynamicCycle> cycles;
    // Spanning-forest gauge: the lexicographically smallest state of each
    // component is pinned to zero. Only reproduces every edge difference when
    // isEquilibriumCompatible is true.
    std::map<std::string, double> statePotential;
    // Largest |(potential(to) - potential(from)) - effectiveDeltaG| over edges.
    double maxEdgeResidual = 0.0;
    // True iff every fundamental cycle affinity is within tolerance of zero.
    bool isEquilibriumCompatible = true;
    // Cycles whose affinity exceeded tolerance, in canonical cycle order.
    std::vector<std::size_t> drivenCycleIndices;
};

// Deterministic for a given graph regardless of state/edge insertion order:
// states are sorted lexicographically, edges are sorted by canonical endpoint
// pair, the spanning forest is grown greedily over that order, and each
// fundamental cycle is oriented by traversing its non-tree edge from its
// lexicographically smaller endpoint to its larger endpoint.
//
// Because an edge's contribution is negated when traversed against its stored
// orientation, reversing how a driven transition was written flips the sign of
// its cycle affinity, while the magnitude is unchanged.
ThermodynamicAnalysis analyzeThermodynamics(
    const ThermodynamicGraph& graph,
    double tolerance = 1e-9);

} // namespace bng::compile::energy
