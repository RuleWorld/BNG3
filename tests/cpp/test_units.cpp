#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "units/Unit.hpp"

using bng::units::BaseUnit;
using bng::units::ConversionContext;
using bng::units::UnitSystem;
using bng::units::conversionFactor;
using bng::units::dimensionallyCompatible;

TEST_CASE("standard units parse with SBML-compatible dimensions") {
    UnitSystem units;
    const auto concentration = units.parse("nM");
    const auto inverseRate = units.parse("s^-1");
    const auto compound = units.parse("1/(uM*s)");

    REQUIRE(concentration);
    REQUIRE(inverseRate);
    REQUIRE(compound);
    CHECK(concentration.unit->dimension == bng::units::Dimension {1, -3, 0});
    CHECK(inverseRate.unit->dimension == bng::units::Dimension {0, 0, -1});
    CHECK(compound.unit->dimension == bng::units::Dimension {-1, 3, -1});
    CHECK(concentration.unit->exponent(BaseUnit::Mole) == 1);
    CHECK(inverseRate.unit->exponent(BaseUnit::Second) == -1);
}

TEST_CASE("compatible metric units convert without runtime unit objects") {
    UnitSystem units;
    const auto nM = units.parse("nM");
    const auto uM = units.parse("uM");
    const auto fL = units.parse("fL");
    const auto litre = units.parse("litre");

    REQUIRE(nM);
    REQUIRE(uM);
    REQUIRE(fL);
    REQUIRE(litre);
    CHECK(dimensionallyCompatible(*nM.unit, *uM.unit));
    CHECK(conversionFactor(*nM.unit, *uM.unit).factor.value() == Catch::Approx(1e-3));
    CHECK(conversionFactor(*uM.unit, *nM.unit).factor.value() == Catch::Approx(1e3));
    CHECK(conversionFactor(*fL.unit, *litre.unit).factor.value() == Catch::Approx(1e-15));
}

TEST_CASE("mole and item conversion requires an explicit bridge") {
    UnitSystem units;
    const auto molar = units.parse("M^-1*s^-1");
    const auto count = units.parse("item^-1*litre*s^-1");

    REQUIRE(molar);
    REQUIRE(count);
    CHECK(dimensionallyCompatible(*molar.unit, *count.unit));
    CHECK_FALSE(conversionFactor(*molar.unit, *count.unit));

    ConversionContext context;
    context.numberPerQuantityUnit = 6.022e23;
    const auto converted = conversionFactor(*molar.unit, *count.unit, context);
    REQUIRE(converted);
    CHECK(converted.factor.value() == Catch::Approx(1.0 / 6.022e23));
}

TEST_CASE("unknown unit names are rejected only in unit context") {
    UnitSystem units;
    const auto result = units.parse("not_a_unit");
    CHECK_FALSE(result);
    CHECK(result.error.find("unknown unit") != std::string::npos);
}

TEST_CASE("custom unit definitions resolve through the same algebra") {
    UnitSystem units;
    const auto defined = units.define("per_nM_s", "nM^-1*s^-1");
    const auto parsed = units.parse("per_nM_s");

    REQUIRE(defined);
    REQUIRE(parsed);
    CHECK(parsed.unit->dimension == bng::units::Dimension {-1, 3, -1});
    CHECK(parsed.unit->name == "per_nM_s");
}

TEST_CASE("explicit compartment context converts concentrations and rate constants") {
    UnitSystem units;
    const auto concentration = units.parse("M");
    const auto micromolar = units.parse("uM");
    const auto volume = units.parse("fL");
    const auto bimolecular = units.parse("M^-1*s^-1");
    REQUIRE(concentration);
    REQUIRE(micromolar);
    REQUIRE(volume);
    REQUIRE(bimolecular);

    ConversionContext context;
    context.numberPerQuantityUnit = 6.02214076e23;
    context.compartmentVolume = 1.0;
    context.volumeUnit = *volume.unit;

    const auto concentrationValue = bng::units::concentrationToItemAmount(
        1.0, *concentration.unit, 1.0, *volume.unit, context);
    REQUIRE(concentrationValue);
    CHECK(*concentrationValue.factor == Catch::Approx(6.02214076e8));

    const auto converted = bng::units::convertValue(
        1.0, *concentration.unit, *micromolar.unit, context);
    REQUIRE(converted);
    CHECK(*converted.factor == Catch::Approx(1.0e6));

    const auto stochastic = bng::units::stochasticRateFactor(
        *bimolecular.unit, 2, context);
    REQUIRE(stochastic);
    CHECK(*stochastic.factor == Catch::Approx(1.0e15 / 6.02214076e23));
}

TEST_CASE("context-dependent conversion fails closed without a volume") {
    UnitSystem units;
    const auto bimolecular = units.parse("M^-1*s^-1");
    REQUIRE(bimolecular);

    ConversionContext context;
    context.numberPerQuantityUnit = 6.02214076e23;
    const auto result = bng::units::stochasticRateFactor(*bimolecular.unit, 2, context);
    CHECK_FALSE(result);
    CHECK(result.error.find("compartment volume") != std::string::npos);
}
