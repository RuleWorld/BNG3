#include "compile/energy/DrivenEnergy.hpp"
#include "compile/energy/ThermodynamicConstraints.hpp"
#include <cstdio>
#include <cmath>
#include <cstdlib>
using namespace bng::compile::energy;
static int failures = 0;
#define CHECK(c) do { if(!(c)){ std::printf("  FAIL line %d: %s\n", __LINE__, #c); ++failures; } } while(0)
static bool approx(double a,double b,double t=1e-12){ return std::fabs(a-b)<=t*std::fmax(1.0,std::fabs(b)); }

int main() {
    const double Ea=1.0, B=0.7, dG=2.0, W=0.4, phi=0.35, RT=1.7;

    // The shared helper must agree with ThermodynamicRate::rates().
    {
        ThermodynamicRate r;
        r.activationBarrier=Ea; r.barrierModifier=B; r.stateDeltaG=dG;
        r.reservoirWork=W; r.phi=phi; r.RT=RT;
        auto pair=r.rates();
        CHECK(approx(drivenArrheniusRate(Ea,B,dG,W,phi,RT,true),  pair.forward));
        CHECK(approx(drivenArrheniusRate(Ea,B,dG,W,phi,RT,false), pair.reverse));
    }
    // Barrier cancels in the ratio; work does not.
    {
        auto ratio=[&](double b,double w){
            return drivenArrheniusRate(Ea,b,dG,w,phi,RT,true)/
                   drivenArrheniusRate(Ea,b,dG,w,phi,RT,false); };
        CHECK(approx(ratio(0.0,W), ratio(5.0,W), 1e-10));
        CHECK(approx(ratio(0.0,W), std::exp(-(dG-W)/RT), 1e-10));
        CHECK(!approx(ratio(0.0,0.0), ratio(0.0,W), 1e-6));
        // Undriven local detailed balance is recovered exactly at W=0.
        CHECK(approx(ratio(0.0,0.0), std::exp(-dG/RT), 1e-10));
    }
    // Work is antisymmetric under traversal direction.
    {
        CHECK(approx(directedWork(1.5,true), 1.5));
        CHECK(approx(directedWork(1.5,false), -1.5));
    }
    // A driven cycle built from directedWork has the affinity the rate math implies.
    {
        ThermodynamicGraph g;
        g.addReversibleEdge("A","B",0.0,1.25);
        g.addReversibleEdge("B","C",0.0,0.0);
        g.addReversibleEdge("C","A",0.0,0.0);
        auto a=analyzeThermodynamics(g);
        CHECK(a.cycleAffinities.size()==1);
        if(!a.cycleAffinities.empty()) CHECK(approx(std::fabs(a.cycleAffinities[0]),1.25,1e-10));
        CHECK(!a.isEquilibriumCompatible);
    }
    // Gate defaults off, honours "0", and turns on for any other value.
    {
        unsetenv("BNG_NFSIM_GENERAL_ENERGY");
        CHECK(!generalEnergyEnabled());
        setenv("BNG_NFSIM_GENERAL_ENERGY","0",1);
        CHECK(!generalEnergyEnabled());
        setenv("BNG_NFSIM_GENERAL_ENERGY","",1);
        CHECK(!generalEnergyEnabled());
        setenv("BNG_NFSIM_GENERAL_ENERGY","1",1);
        CHECK(generalEnergyEnabled());
        setenv("BNG_NFSIM_GENERAL_ENERGY","on",1);
        CHECK(generalEnergyEnabled());
        unsetenv("BNG_NFSIM_GENERAL_ENERGY");
        std::printf("  gate name = %s\n", generalEnergyGateName());
    }
    // The compact NFsim path multiplies a constant base rate by a per-mapping
    // context factor. Folding the barrier into the base rate must reproduce the
    // materialized rate exactly, which is what licenses keeping barrier-only
    // rules on the compact path while driven rules fall back.
    {
        const double RT = 1.9, phi = 0.3, Ea = 0.8;
        for (double B : {0.0, 2.5, -1.25})
        for (double dG : {-2.0, 0.0, 1.75}) {
            const double base = std::exp(-(Ea + B) / RT);
            const double fwdContext = std::exp(-phi * dG / RT);
            const double revContext = std::exp(-(phi - 1.0) * dG / RT);
            CHECK(approx(base * fwdContext,
                         drivenArrheniusRate(Ea, B, dG, 0.0, phi, RT, true), 1e-10));
            CHECK(approx(base * revContext,
                         drivenArrheniusRate(Ea, B, dG, 0.0, phi, RT, false), 1e-10));
        }
        // With no barrier the folded base rate is bit-identical to exp(-Ea/RT).
        CHECK(std::exp(-(Ea + 0.0) / RT) == std::exp(-Ea / RT));
    }
    std::printf(failures ? "DRIVEN: %d failure(s)\n" : "DRIVEN: all checks passed\n", failures);
    return failures ? 1 : 0;
}
