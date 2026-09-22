// Network-free strict check of the RED contract in
// tests/energy/tests/cpp/future_thermodynamic_constraints.cpp
#include "compile/energy/ThermodynamicConstraints.hpp"
#include <cstdio>
#include <cmath>
#include <cstdlib>

using namespace bng::compile::energy;

static int failures = 0;
static const char* section = "";
#define CHECK(cond) do { if (!(cond)) { \
    std::printf("  FAIL [%s] line %d: %s\n", section, __LINE__, #cond); ++failures; } } while (0)
static bool approx(double a, double b, double m = 1e-12) { return std::fabs(a - b) <= m; }

int main() {
    {
        section = "tree has no cycle constraints and one gauge freedom per component";
        ThermodynamicGraph g;
        g.addState("A"); g.addState("B"); g.addState("C");
        g.addReversibleEdge("A","B",1.0,0.0);
        g.addReversibleEdge("B","C",2.0,0.0);
        const auto a = analyzeThermodynamics(g);
        CHECK(a.connectedComponents == 1);
        CHECK(a.cycleRank == 0);
        CHECK(a.gaugeDegreesOfFreedom == 1);
        CHECK(a.isEquilibriumCompatible);
    }
    {
        section = "one triangle has one fundamental cycle";
        ThermodynamicGraph g;
        g.addReversibleEdge("A","B",1.0,0.0);
        g.addReversibleEdge("B","C",2.0,0.0);
        g.addReversibleEdge("C","A",-3.0,0.0);
        const auto a = analyzeThermodynamics(g);
        CHECK(a.cycleRank == 1);
        CHECK(a.cycleAffinities.size() == 1);
        if (a.cycleAffinities.size() == 1) CHECK(approx(a.cycleAffinities[0], 0.0));
        CHECK(a.isEquilibriumCompatible);
    }
    {
        section = "driving work produces nonzero cycle affinity";
        ThermodynamicGraph g;
        g.addReversibleEdge("A","B",1.0,0.0);
        g.addReversibleEdge("B","C",2.0,0.5);
        g.addReversibleEdge("C","A",-3.0,0.0);
        const auto a = analyzeThermodynamics(g);
        CHECK(a.cycleAffinities.size() == 1);
        if (a.cycleAffinities.size() == 1) CHECK(std::fabs(a.cycleAffinities[0]) > 1e-12);
        CHECK(!a.isEquilibriumCompatible);
    }
    {
        section = "barrier modifier changes kinetics but not equilibrium ratio";
        ThermodynamicRate r;
        r.stateDeltaG = 2.0; r.activationBarrier = 5.0; r.barrierModifier = 3.0;
        r.phi = 0.4; r.RT = 2.0;
        const auto shifted = r.rates();
        r.barrierModifier = 0.0;
        const auto base = r.rates();
        CHECK(shifted.forward < base.forward);
        CHECK(shifted.reverse < base.reverse);
        CHECK(approx(shifted.forward / shifted.reverse, base.forward / base.reverse, 1e-9));
    }
    {
        section = "cycle rank obeys E minus V plus connected-components";
        ThermodynamicGraph g;
        g.addReversibleEdge("A","B",1,0);
        g.addReversibleEdge("B","C",1,0);
        g.addReversibleEdge("C","A",-2,0);
        g.addReversibleEdge("C","D",1,0);
        g.addReversibleEdge("D","A",-1,0);
        auto a = analyzeThermodynamics(g);
        CHECK(a.cycleRank == 2);
        CHECK(a.cycleAffinities.size() == 2);
    }
    {
        section = "disconnected components contribute independent gauge freedoms";
        ThermodynamicGraph g;
        g.addReversibleEdge("A","B",1,0);
        g.addReversibleEdge("X","Y",2,0);
        auto a = analyzeThermodynamics(g);
        CHECK(a.connectedComponents == 2);
        CHECK(a.gaugeDegreesOfFreedom == 2);
        CHECK(a.cycleRank == 0);
    }
    {
        section = "equilibrium state potentials reproduce edge free-energy differences";
        ThermodynamicGraph g;
        g.addReversibleEdge("A","B",1,0);
        g.addReversibleEdge("B","C",2,0);
        g.addReversibleEdge("C","A",-3,0);
        auto a = analyzeThermodynamics(g);
        CHECK(a.isEquilibriumCompatible);
        CHECK(approx(a.statePotential.at("B") - a.statePotential.at("A"), 1.0, 1e-9));
        CHECK(approx(a.statePotential.at("C") - a.statePotential.at("B"), 2.0, 1e-9));
        CHECK(a.maxEdgeResidual < 1e-9);
    }
    {
        section = "pure barrier changes do not contribute to cycle affinity";
        ThermodynamicGraph g;
        g.addReversibleEdge("A","B",1,0,100);
        g.addReversibleEdge("B","C",2,0,-7);
        g.addReversibleEdge("C","A",-3,0,2);
        auto a = analyzeThermodynamics(g);
        CHECK(a.cycleAffinities.size() == 1);
        if (a.cycleAffinities.size() == 1) CHECK(approx(a.cycleAffinities[0], 0.0));
    }
    {
        section = "reversing driven edge reverses its contribution to cycle affinity";
        ThermodynamicGraph g1, g2;
        g1.addReversibleEdge("A","B",0,1.5);
        g1.addReversibleEdge("B","C",0,0);
        g1.addReversibleEdge("C","A",0,0);
        g2.addReversibleEdge("B","A",0,1.5);
        g2.addReversibleEdge("A","C",0,0);
        g2.addReversibleEdge("C","B",0,0);
        auto a1 = analyzeThermodynamics(g1), a2 = analyzeThermodynamics(g2);
        CHECK(a1.cycleAffinities.size() == 1);
        CHECK(a2.cycleAffinities.size() == 1);
        if (a1.cycleAffinities.size() == 1 && a2.cycleAffinities.size() == 1) {
            std::printf("  (a1=%g a2=%g)\n", a1.cycleAffinities[0], a2.cycleAffinities[0]);
            CHECK(approx(a1.cycleAffinities[0], -a2.cycleAffinities[0], 1e-9));
            CHECK(std::fabs(a1.cycleAffinities[0]) > 1e-12);
        }
    }
    std::printf(failures ? "THERMO: %d failure(s)\n" : "THERMO: all checks passed\n", failures);
    return failures ? 1 : 0;
}
