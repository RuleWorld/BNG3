#include "DrivenEnergy.hpp"

#include <cmath>
#include <cstdlib>

namespace bng::compile::energy {

namespace {
constexpr const char* kGate = "BNG_NFSIM_GENERAL_ENERGY";
} // namespace

bool generalEnergyEnabled() {
    const char* value = std::getenv(kGate);
    if (value == nullptr) return false;
    // An explicit "0" disables, so a CI job can pin the gate off without
    // having to unset the variable.
    return value[0] != '\0' && !(value[0] == '0' && value[1] == '\0');
}

const char* generalEnergyGateName() {
    return kGate;
}

double drivenArrheniusRate(
    double activationEnergy,
    double barrier,
    double deltaG,
    double work,
    double phi,
    double RT,
    bool isForward) {
    const double scale = RT == 0.0 ? 1.0 : RT;
    const double effective = deltaG - work;
    const double distribution = isForward ? phi : phi - 1.0;
    return std::exp(-(activationEnergy + barrier + distribution * effective) / scale);
}

double networkArrheniusRate(
    double activationEnergy,
    double barrier,
    double reactionDeltaG,
    double ruleWork,
    double directionPhi,
    bool reverseDirection) {
    // See the header: the reaction's dG is pre-negated for a reverse
    // direction, so the work must be negated alongside it to keep
    // (dG - W) consistent. The barrier is direction-independent.
    const double directedW = reverseDirection ? -ruleWork : ruleWork;
    return std::exp(
        -(activationEnergy + barrier + directionPhi * (reactionDeltaG - directedW)));
}

} // namespace bng::compile::energy
