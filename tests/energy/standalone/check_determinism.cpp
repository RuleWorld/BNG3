#include "compile/energy/ThermodynamicConstraints.hpp"
#include <cstdio>
#include <cmath>
#include <vector>
#include <algorithm>
using namespace bng::compile::energy;
static int failures = 0;
#define CHECK(c) do { if(!(c)){ std::printf("  FAIL line %d: %s\n", __LINE__, #c); ++failures; } } while(0)

struct E { const char* f; const char* t; double g; double w; };

int main() {
    // Same graph, six insertion permutations: affinity must be identical.
    std::vector<E> base = {{"A","B",1.0,0.25},{"B","C",2.0,0.0},{"C","A",-3.0,0.0}};
    std::vector<int> idx = {0,1,2};
    std::sort(idx.begin(), idx.end());
    double reference = 0.0; bool first = true;
    do {
        ThermodynamicGraph g;
        for (int i : idx) g.addReversibleEdge(base[i].f, base[i].t, base[i].g, base[i].w);
        auto a = analyzeThermodynamics(g);
        CHECK(a.cycleAffinities.size() == 1);
        if (a.cycleAffinities.empty()) continue;
        if (first) { reference = a.cycleAffinities[0]; first = false; }
        else CHECK(std::fabs(a.cycleAffinities[0] - reference) < 1e-12);
        // statePotential is also a graph property, not an insertion artifact
        CHECK(std::fabs(a.statePotential.at("A")) < 1e-12);
    } while (std::next_permutation(idx.begin(), idx.end()));
    std::printf("  reference affinity = %g\n", reference);
    CHECK(std::fabs(reference - 0.25) < 1e-12);

    // Declaring states in a different order must not matter either.
    {
        ThermodynamicGraph g1, g2;
        g1.addState("C"); g1.addState("A"); g1.addState("B");
        g1.addReversibleEdge("A","B",1,0); g1.addReversibleEdge("B","C",2,0);
        g2.addState("A"); g2.addState("B"); g2.addState("C");
        g2.addReversibleEdge("B","C",2,0); g2.addReversibleEdge("A","B",1,0);
        auto a1 = analyzeThermodynamics(g1), a2 = analyzeThermodynamics(g2);
        CHECK(a1.statePotential == a2.statePotential);
        CHECK(a1.cycleRank == a2.cycleRank && a1.connectedComponents == a2.connectedComponents);
    }

    // Parallel edges and self-loops contribute one independent cycle each.
    {
        ThermodynamicGraph g;
        g.addReversibleEdge("A","B",1.0,0.0);
        g.addReversibleEdge("A","B",1.0,0.0);   // parallel, consistent -> affinity 0
        auto a = analyzeThermodynamics(g);
        CHECK(a.cycleRank == 1);
        CHECK(a.cycleAffinities.size() == 1);
        CHECK(std::fabs(a.cycleAffinities[0]) < 1e-12);
        CHECK(a.isEquilibriumCompatible);
    }
    {
        ThermodynamicGraph g;
        g.addReversibleEdge("A","B",1.0,0.0);
        g.addReversibleEdge("A","B",2.0,0.0);   // inconsistent parallel edges
        auto a = analyzeThermodynamics(g);
        CHECK(a.cycleRank == 1);
        CHECK(!a.isEquilibriumCompatible);
        CHECK(a.drivenCycleIndices.size() == 1);
    }
    {
        ThermodynamicGraph g;
        g.addReversibleEdge("A","A",0.0,0.75);  // driven self-loop
        auto a = analyzeThermodynamics(g);
        CHECK(a.cycleRank == 1);
        CHECK(a.cycleAffinities.size() == 1);
        CHECK(std::fabs(a.cycleAffinities[0] - 0.75) < 1e-12);
        CHECK(!a.isEquilibriumCompatible);
    }
    // Empty graph is compatible and rank-free.
    {
        ThermodynamicGraph g;
        auto a = analyzeThermodynamics(g);
        CHECK(a.cycleRank == 0 && a.connectedComponents == 0 && a.isEquilibriumCompatible);
    }
    std::printf(failures ? "ORDER: %d failure(s)\n" : "ORDER: all checks passed\n", failures);
    return failures ? 1 : 0;
}
