// RED CONTRACT: thermodynamic graph diagnostics.
#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include "compile/energy/ThermodynamicConstraints.hpp"

using namespace bng::compile::energy;

TEST_CASE("tree has no cycle constraints and one gauge freedom per component") {
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

TEST_CASE("one triangle has one fundamental cycle") {
    ThermodynamicGraph g;
    g.addReversibleEdge("A","B",1.0,0.0);
    g.addReversibleEdge("B","C",2.0,0.0);
    g.addReversibleEdge("C","A",-3.0,0.0);
    const auto a = analyzeThermodynamics(g);
    CHECK(a.cycleRank == 1);
    REQUIRE(a.cycleAffinities.size() == 1);
    CHECK(a.cycleAffinities[0] == Catch::Approx(0.0).margin(1e-12));
    CHECK(a.isEquilibriumCompatible);
}

TEST_CASE("driving work produces nonzero cycle affinity") {
    ThermodynamicGraph g;
    g.addReversibleEdge("A","B",1.0,0.0);
    g.addReversibleEdge("B","C",2.0,0.5);
    g.addReversibleEdge("C","A",-3.0,0.0);
    const auto a = analyzeThermodynamics(g);
    REQUIRE(a.cycleAffinities.size() == 1);
    CHECK(std::fabs(a.cycleAffinities[0]) > 1e-12);
    CHECK_FALSE(a.isEquilibriumCompatible);
}

TEST_CASE("barrier modifier changes kinetics but not equilibrium ratio") {
    ThermodynamicRate r;
    r.stateDeltaG = 2.0;
    r.activationBarrier = 5.0;
    r.barrierModifier = 3.0;
    r.phi = 0.4;
    r.RT = 2.0;
    const auto shifted = r.rates();
    r.barrierModifier = 0.0;
    const auto base = r.rates();
    CHECK(shifted.forward < base.forward);
    CHECK(shifted.reverse < base.reverse);
    CHECK(shifted.forward / shifted.reverse ==
          Catch::Approx(base.forward / base.reverse).epsilon(1e-12));
}

TEST_CASE("cycle rank obeys E minus V plus connected-components") {
    ThermodynamicGraph g;
    g.addReversibleEdge("A","B",1,0);
    g.addReversibleEdge("B","C",1,0);
    g.addReversibleEdge("C","A",-2,0);
    g.addReversibleEdge("C","D",1,0);
    g.addReversibleEdge("D","A",-1,0);
    auto a=analyzeThermodynamics(g);
    CHECK(a.cycleRank==2);
}

TEST_CASE("disconnected components contribute independent gauge freedoms") {
    ThermodynamicGraph g;
    g.addReversibleEdge("A","B",1,0);
    g.addReversibleEdge("X","Y",2,0);
    auto a=analyzeThermodynamics(g);
    CHECK(a.connectedComponents==2);
    CHECK(a.gaugeDegreesOfFreedom==2);
    CHECK(a.cycleRank==0);
}

TEST_CASE("equilibrium state potentials reproduce edge free-energy differences") {
    ThermodynamicGraph g;
    g.addReversibleEdge("A","B",1,0);
    g.addReversibleEdge("B","C",2,0);
    g.addReversibleEdge("C","A",-3,0);
    auto a=analyzeThermodynamics(g);
    REQUIRE(a.isEquilibriumCompatible);
    CHECK(a.statePotential.at("B")-a.statePotential.at("A") == Catch::Approx(1.0));
    CHECK(a.statePotential.at("C")-a.statePotential.at("B") == Catch::Approx(2.0));
}

TEST_CASE("pure barrier changes do not contribute to cycle affinity") {
    ThermodynamicGraph g;
    g.addReversibleEdge("A","B",1,0,/*barrierModifier=*/100);
    g.addReversibleEdge("B","C",2,0,/*barrierModifier=*/-7);
    g.addReversibleEdge("C","A",-3,0,/*barrierModifier=*/2);
    auto a=analyzeThermodynamics(g);
    REQUIRE(a.cycleAffinities.size()==1);
    CHECK(a.cycleAffinities[0] == Catch::Approx(0.0).margin(1e-12));
}

TEST_CASE("reversing driven edge reverses its contribution to cycle affinity") {
    ThermodynamicGraph g1,g2;
    g1.addReversibleEdge("A","B",0,1.5);
    g1.addReversibleEdge("B","C",0,0);
    g1.addReversibleEdge("C","A",0,0);
    g2.addReversibleEdge("B","A",0,1.5);
    g2.addReversibleEdge("A","C",0,0);
    g2.addReversibleEdge("C","B",0,0);
    auto a1=analyzeThermodynamics(g1),a2=analyzeThermodynamics(g2);
    REQUIRE(a1.cycleAffinities.size()==1); REQUIRE(a2.cycleAffinities.size()==1);
    CHECK(a1.cycleAffinities[0] == Catch::Approx(-a2.cycleAffinities[0]).epsilon(1e-12));
}
