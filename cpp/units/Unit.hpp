#pragma once

#include <cstddef>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace bng::units {

// The initial unit vocabulary follows the SBML Core base-unit families that
// are needed by biochemical BNGL models.  The enum is deliberately not
// exposed as a lexer vocabulary: unit names are resolved only in unit
// contexts, so identifiers such as s, M, and L remain legal BNGL names.
enum class BaseUnit {
    Dimensionless,
    Mole,
    Item,
    Metre,
    Litre,
    Second,
};

struct Dimension {
    int substance = 0;
    int length = 0;
    int time = 0;

    friend bool operator==(const Dimension& lhs, const Dimension& rhs) {
        return lhs.substance == rhs.substance && lhs.length == rhs.length &&
               lhs.time == rhs.time;
    }

    friend bool operator!=(const Dimension& lhs, const Dimension& rhs) {
        return !(lhs == rhs);
    }
};

struct Unit {
    std::string name;
    Dimension dimension;

    // Exponents retain the SBML-style base-unit identity.  In particular,
    // mole and item have the same physical dimension but remain distinct
    // until an explicit Avogadro/NumberPerQuantityUnit bridge is supplied.
    std::map<BaseUnit, int> baseExponents;

    // Conversion to the SI-like physical basis metre, mole, and second.  The
    // item basis is intentionally not folded into this scalar; see
    // conversionFactor() for the explicit item/mole bridge.
    double factor = 1.0;

    bool isDimensionless() const { return dimension == Dimension {}; }
    int exponent(BaseUnit base) const;
};

struct UnitDefinition {
    std::string id;
    std::string expression;
    Unit unit;
    bool builtin = false;
};

struct UnitParseResult {
    std::optional<Unit> unit;
    std::string error;

    explicit operator bool() const { return unit.has_value(); }
};

class UnitSystem {
public:
    UnitSystem();

    UnitParseResult parse(std::string_view expression) const;
    UnitParseResult define(std::string id, std::string expression);

    const Unit* find(std::string_view name) const;
    const std::vector<UnitDefinition>& definitions() const { return definitions_; }

    // Used internally while installing the standard SBML-compatible
    // vocabulary.  User-defined units should use define().
    void addBuiltin(std::string name, Unit unit, std::string expression);

private:
    std::map<std::string, Unit> units_;
    std::vector<UnitDefinition> definitions_;
};

struct ConversionContext {
    // Number of item/molecules per mole (or the legacy equivalent selected
    // by NumberPerQuantityUnit).  It is optional because mole/item conversion
    // must fail closed when no bridge is available.
    std::optional<double> numberPerQuantityUnit;

    // A rate or concentration conversion may need a compartment volume.  The
    // numeric value is interpreted in volumeUnit, never assumed to be litres
    // or SI implicitly.
    std::optional<double> compartmentVolume;
    std::optional<Unit> volumeUnit;
};

struct ConversionResult {
    std::optional<double> factor;
    std::string error;

    explicit operator bool() const { return factor.has_value(); }
};

bool dimensionallyCompatible(const Unit& lhs, const Unit& rhs);
Unit multiplyUnits(const Unit& lhs, const Unit& rhs);
Unit divideUnits(const Unit& lhs, const Unit& rhs);
Unit powerUnit(const Unit& unit, int exponent);
ConversionResult conversionFactor(const Unit& from, const Unit& to,
                                  const ConversionContext& context = {});

ConversionResult convertValue(double value, const Unit& from, const Unit& to,
                              const ConversionContext& context = {});

// Convert a concentration/amount density to an item count in one explicit
// compartment.  Mole/item conversion requires numberPerQuantityUnit.
ConversionResult concentrationToItemAmount(double value, const Unit& concentration,
                                            double volume, const Unit& volumeUnit,
                                            const ConversionContext& context = {});

// Convert a concentration-based mass-action rate constant to the coefficient
// consumed by a count-based stochastic backend.  Molecularity is the total
// reactant stoichiometry.  The conversion is context-dependent by design and
// must never be cached as a global parameter rewrite.
ConversionResult stochasticRateFactor(const Unit& rateUnit, std::size_t molecularity,
                                       const ConversionContext& context = {});

std::string baseUnitName(BaseUnit base);
std::string formatUnit(const Unit& unit);

} // namespace bng::units
