#pragma once

#include <optional>
#include <vector>

namespace bng::compile {

// One reactant's resolved compartment geometry, in reactant order.
//
// `size` is the compartment volume/area already scaled by the system
// NumberPerQuantityUnit (when greater than zero). Callers are responsible for
// that scaling because the conversion is a property of the runtime System,
// not of the compiled pattern.
struct ReactantCompartment {
    int dimension = 3;
    double size = 1.0;
};

// Perl-faithful mass-action count-rate compartment conversion for a
// reactant-bearing reaction (Rxn.pm:100-197), shared by the deterministic
// NetWriter and the NFsim bridges.
//
// Semantics mirror NetWriter::unitConversionFactor exactly:
//   * collect the 2-D (surface) and 3-D (volume) reactant compartments;
//   * erase exactly one anchor: the first surface, else the first volume;
//   * if no compartment remains, there is no conversion (factor 1);
//   * otherwise the factor is 1 / product(remaining compartment sizes).
//
// Examples: bimolecular `A@V + A@V` in one volume V -> 1/V; unimolecular
// `A@V` -> nullopt (no volume dependence).
inline std::optional<double> reactantUnitConversionFactor(
    const std::vector<ReactantCompartment>& reactants) {
    std::vector<double> surfaces;
    std::vector<double> volumes;
    for (const auto& reactant : reactants) {
        if (reactant.dimension == 2) surfaces.push_back(reactant.size);
        else if (reactant.dimension == 3) volumes.push_back(reactant.size);
    }

    // Toss one anchor compartment, mirroring Rxn.pm's reference-compartment
    // removal. Surfaces take precedence so a surface+volume pair keeps the
    // volume in the denominator.
    if (!surfaces.empty()) surfaces.erase(surfaces.begin());
    else if (!volumes.empty()) volumes.erase(volumes.begin());

    if (surfaces.empty() && volumes.empty()) return std::nullopt;

    double denominator = 1.0;
    for (const double size : surfaces) denominator *= size;
    for (const double size : volumes) denominator *= size;
    return 1.0 / denominator;
}

} // namespace bng::compile
