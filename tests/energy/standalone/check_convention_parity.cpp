// The NFsim path and the network path use different energy conventions. This
// pins down that they describe the SAME kinetics, which is the single most
// likely place for a silent sign error in the driven-energy work.
//
//   NFsim   : divides by an explicit RT; BOTH directions receive the forward
//             dG and the forward W, differing only via phi vs (phi - 1).
//   Network : energies already in units of RT (so RT == 1); each direction is
//             its own reaction whose dG is ALREADY negated, and whose phi is
//             already (1 - phi). Work must therefore be negated there.
#include "compile/energy/DrivenEnergy.hpp"
#include <cmath>
#include <cstdio>
using namespace bng::compile::energy;
static int failures = 0;
#define CHECK(c) do { if(!(c)){ std::printf("  FAIL line %d: %s\n", __LINE__, #c); ++failures; } } while(0)
static bool close(double a, double b) {
    return std::fabs(a - b) <= 1e-12 * std::fmax(1.0, std::fabs(b));
}

int main() {
    const double phis[]   = {0.0, 0.25, 0.5, 0.75, 1.0};
    const double dGs[]    = {-3.0, -0.5, 0.0, 1.0, 2.5};
    const double works[]  = {-1.5, 0.0, 0.4, 2.0};
    const double barrs[]  = {-1.0, 0.0, 3.0};
    const double Ea       = 1.3;

    for (double phi : phis)
    for (double dG : dGs)
    for (double W : works)
    for (double B : barrs) {
        // RT == 1 is the network convention; compare against NFsim at RT == 1.
        const double nfFwd = drivenArrheniusRate(Ea, B, dG, W, phi, 1.0, true);
        const double nfRev = drivenArrheniusRate(Ea, B, dG, W, phi, 1.0, false);

        // Network forward: this reaction's dG is the forward dG, phi as given.
        const double netFwd = networkArrheniusRate(Ea, B, dG, W, phi, false);
        // Network reverse: dG arrives negated, phi arrives as (1 - phi).
        const double netRev = networkArrheniusRate(Ea, B, -dG, W, 1.0 - phi, true);

        CHECK(close(netFwd, nfFwd));
        CHECK(close(netRev, nfRev));
        if (!close(netRev, nfRev)) {
            std::printf("    phi=%g dG=%g W=%g B=%g nfRev=%g netRev=%g\n",
                        phi, dG, W, B, nfRev, netRev);
        }
    }
    std::printf("  swept %zu parameter combinations\n",
                sizeof(phis)/sizeof(*phis) * sizeof(dGs)/sizeof(*dGs)
                * sizeof(works)/sizeof(*works) * sizeof(barrs)/sizeof(*barrs));

    // Had the work NOT been negated on the reverse side, the reverse rates
    // would disagree whenever W != 0. Demonstrate that the guard is load-bearing.
    {
        const double phi = 0.35, dG = 2.0, W = 0.8, B = 0.0;
        const double nfRev  = drivenArrheniusRate(Ea, B, dG, W, phi, 1.0, false);
        const double correct = networkArrheniusRate(Ea, B, -dG, W, 1.0 - phi, true);
        const double buggy   = networkArrheniusRate(Ea, B, -dG, W, 1.0 - phi, false);
        CHECK(close(correct, nfRev));
        CHECK(!close(buggy, nfRev));
        std::printf("  sign guard is load-bearing: correct=%g buggy=%g\n", correct, buggy);
    }

    // A barrier must never be negated by direction: it cancels in the ratio on
    // both paths.
    {
        const double phi = 0.4, dG = 1.5, W = 0.0;
        for (double B : {0.0, 2.0, -2.0}) {
            const double f = networkArrheniusRate(Ea, B, dG, W, phi, false);
            const double r = networkArrheniusRate(Ea, B, -dG, W, 1.0 - phi, true);
            CHECK(close(f / r, std::exp(-dG)));
        }
    }
    // Reservoir work shifts the network-path ratio by exactly exp(W).
    {
        const double phi = 0.4, dG = 1.5, B = 1.0, W = 0.6;
        const double f = networkArrheniusRate(Ea, B, dG, W, phi, false);
        const double r = networkArrheniusRate(Ea, B, -dG, W, 1.0 - phi, true);
        CHECK(close(f / r, std::exp(-(dG - W))));
    }
    std::printf(failures ? "CONVENTION: %d failure(s)\n" : "CONVENTION: all checks passed\n", failures);
    return failures ? 1 : 0;
}
