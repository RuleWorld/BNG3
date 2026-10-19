#pragma once

#include <optional>
#include <vector>

namespace bng::compile {

// One reactant's resolved compartment geometry, in reactant order.
//
// `size` is the compartment volume/area/length already scaled by the system
// NumberPerQuantityUnit (when greater than zero). Callers are responsible for
// that scaling because the conversion is a property of the runtime System,
// not of the compiled pattern.
struct ReactantCompartment {
    int dimension = 3;
    double size = 1.0;
};

// Mass-action count-rate compartment conversion for a reactant-bearing
// reaction, shared by the deterministic NetWriter and the NFsim bridges.
//
// BNG2/Perl authority (Rxn.pm:100-197, NetWriter::unitConversionFactor) only
// recognizes 2-D (surface) and 3-D (volume) reactants: it anchors the first
// surface, else the first volume, and divides by the sizes of the remaining
// 2-D/3-D reactants.  BNG2 rejects 1-D/0-D compartments at parse time, so Perl
// has no rule for them.
//
// This helper intentionally generalizes that rule to every dimension.  A
// 1-D/0-D reactant still carries a concentration whose conversion to a count
// rate divides by its size, so silently dropping it (as a literal 2-D/3-D-only
// port would) understates the conversion.  The anchor preference is preserved:
// first surface, else first volume, else the first reactant of any other
// dimension.  For 2-D/3-D-only inputs this is exactly the Perl factor.
//
//   * if no compartment remains after anchoring, there is no conversion
//     (factor 1, returns nullopt);
//   * otherwise the factor is 1 / product(remaining compartment sizes).
//
// Examples: bimolecular `A@V + A@V` in one volume V -> 1/V; unimolecular
// `A@V` -> nullopt (no volume dependence); `A@L + A@L` in one 1-D length L ->
// 1/L (a deliberate generalization of the Perl rule).
inline std::optional<double> reactantUnitConversionFactor(
    const std::vector<ReactantCompartment>& reactants) {
    std::vector<double> surfaces;
    std::vector<double> volumes;
    std::vector<double> others;
    for (const auto& reactant : reactants) {
        if (reactant.dimension == 2) surfaces.push_back(reactant.size);
        else if (reactant.dimension == 3) volumes.push_back(reactant.size);
        else others.push_back(reactant.size);
    }

    // Toss one anchor compartment.  Surfaces take precedence, then volumes,
    // then any remaining dimension, mirroring Rxn.pm's reference-compartment
    // removal while generalizing it beyond 2-D/3-D.
    if (!surfaces.empty()) surfaces.erase(surfaces.begin());
    else if (!volumes.empty()) volumes.erase(volumes.begin());
    else if (!others.empty()) others.erase(others.begin());

    if (surfaces.empty() && volumes.empty() && others.empty()) return std::nullopt;

    double denominator = 1.0;
    for (const double size : surfaces) denominator *= size;
    for (const double size : volumes) denominator *= size;
    for (const double size : others) denominator *= size;
    return 1.0 / denominator;
}

} // namespace bng::compile
