#pragma once

// Gating and shared rate math for the nonequilibrium energy extensions.
//
// Barrier patterns and driving reservoirs are experimental: they extend eBNGL
// beyond what canonical NFsim implements, so no independent oracle exists for
// them yet. They are therefore off by default at every backend boundary and
// enabled only by the BNG_NFSIM_GENERAL_ENERGY environment variable, matching
// the existing BNG_NFSIM_* gating convention.
//
// The rate math lives here rather than being duplicated in the NFsim energy
// function and the network writer, because the two paths use different energy
// conventions (explicit RT versus RT folded into the parameters) and must not
// drift apart.

#include <string>

namespace bng::compile::energy {

// True when the experimental general-energy path is explicitly enabled.
bool generalEnergyEnabled();

// Name of the gate, for diagnostics that tell the user how to opt in.
const char* generalEnergyGateName();

// Signed reservoir work applied to one traversal direction. Forward traversal
// consumes +W; the reverse traversal of the same edge consumes -W, which is
// what keeps the cycle affinity antisymmetric under edge reversal.
inline double directedWork(double work, bool isForward) {
    return isForward ? work : -work;
}

// Arrhenius rate with a transition-state barrier and reservoir work:
//
//   k_f = exp[-(Ea + B + phi       * (dG - W)) / RT]
//   k_r = exp[-(Ea + B + (phi - 1) * (dG - W)) / RT]
//
// `deltaG` and `work` must already be expressed in the direction being built.
double drivenArrheniusRate(
    double activationEnergy,
    double barrier,
    double deltaG,
    double work,
    double phi,
    double RT,
    bool isForward);

// Network-compiler convention, which differs from the NFsim one in two ways
// that interact and are easy to get wrong:
//
//   1. Energies are already expressed in units of RT, so there is no RT
//      divisor (the NFsim path divides by an explicit RT).
//   2. Each direction is a separate generated reaction whose reactants and
//      products are swapped, so `reactionDeltaG` is ALREADY negated for a
//      reverse direction, and `directionPhi` is already (1 - phi).
//
// Because the reverse reaction's dG arrives pre-negated, the rule's reservoir
// work must be negated here to match; otherwise the reverse rate would use
// exp(-(Ea + (1-phi)(-dG - W))) instead of the correct
// exp(-(Ea + (1-phi)(W - dG))).
//
// A barrier is direction-independent -- the same transition state is crossed
// either way -- so it is never negated.
//
// `ruleWork` is always the rule's FORWARD work, as written in driven_by().
// Passing an already-negated value would double-negate it.
double networkArrheniusRate(
    double activationEnergy,
    double barrier,
    double reactionDeltaG,
    double ruleWork,
    double directionPhi,
    bool reverseDirection);

} // namespace bng::compile::energy
