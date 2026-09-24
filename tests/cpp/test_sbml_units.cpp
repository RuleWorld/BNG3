#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>

#include <filesystem>
#include <fstream>
#include <string>

#include "io/BnglWriter.hpp"
#include "io/NetWriter.hpp"
#include "io/SbmlMultiWriter.hpp"
#include "io/SbmlReader.hpp"
#include "io/SbmlWriter.hpp"
#include "engine/NetworkGenerator.hpp"
#include "parser/BNGAstVisitor.hpp"

namespace {

const auto unitModel = [] {
    return bng::parser::parseModel(R"BNGL(
begin model
  setOption("units", "strict")
  begin units
    timeUnits = second
    substanceUnits = item
    volumeUnits = litre
    unit per_s = second^-1
  end units
  begin parameters
    KD = 100 [nM]
    koff = 0.02 [per_s]
  end parameters
  begin compartments
    cyto 3 1 [fL]
  end compartments
  begin seed species
    A()@cyto 10 [molecule]
  end seed species
end model
)BNGL");
};

} // namespace

TEST_CASE("SBML Core writer emits compatible unit definitions and attributes") {
    const auto model = unitModel();
    REQUIRE(model != nullptr);

    const auto xml = bng::io::SbmlWriter::write(*model, nullptr);
    CHECK(xml.find("timeUnits=\"second\"") != std::string::npos);
    CHECK(xml.find("substanceUnits=\"item\"") != std::string::npos);
    CHECK(xml.find("id=\"nM\"") != std::string::npos);
    CHECK(xml.find("kind=\"mole\"") != std::string::npos);
    CHECK(xml.find("units=\"nM\"") != std::string::npos);
    CHECK(xml.find("units=\"per_s\"") != std::string::npos);
    CHECK(xml.find("units=\"fL\"") != std::string::npos);
    CHECK(xml.find("kind=\"second\" exponent=\"-1\" multiplier=\"1\" scale=\"0\"") != std::string::npos);
    CHECK(xml.find("initialAmount=\"10\"") != std::string::npos);
}

TEST_CASE("SBML-Multi reuses Core units without a second unit system") {
    const auto model = unitModel();
    REQUIRE(model != nullptr);

    const auto xml = bng::io::SbmlMultiWriter::write(*model);
    CHECK(xml.find("xmlns:multi=") != std::string::npos);
    CHECK(xml.find("id=\"nM\"") != std::string::npos);
    CHECK(xml.find("units=\"nM\"") != std::string::npos);
    CHECK(xml.find("units=\"fL\"") != std::string::npos);
    CHECK(xml.find("multi:units") == std::string::npos);
}

TEST_CASE("SBML unit factors are exact for inverse and higher-order units") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin units
  unit inverse_second_squared = 2 * second^-2
end units
begin parameters
  x = 1 [inverse_second_squared]
end parameters
)BNGL");
    REQUIRE(model != nullptr);

    const auto xml = bng::io::SbmlWriter::write(*model, nullptr);
    CHECK(xml.find("id=\"inverse_second_squared\"") != std::string::npos);
    CHECK(xml.find("kind=\"dimensionless\" exponent=\"1\" multiplier=\"2\" scale=\"0\"") != std::string::npos);
    CHECK(xml.find("kind=\"second\" exponent=\"-2\" multiplier=\"1\" scale=\"0\"") != std::string::npos);
}

TEST_CASE("SBML serializes Sat rates as MathML rather than an unresolved symbol",
          "[SbmlWriter][issue-277]") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
  kcat 1.52
  Km 114.4
  n 2
end parameters
begin molecule types
  A()
  E()
end molecule types
begin seed species
  A() 10
  E() 10
end seed species
begin reaction rules
  A() + E() -> E() Sat(kcat, Km)
  A() + E() -> E() MM(kcat, Km)
  A() + E() -> E() Hill(kcat, Km, n)
end reaction rules
)BNGL");
    REQUIRE(model != nullptr);

    bng::engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    const auto xml = bng::io::SbmlWriter::write(*model, &network);
    std::size_t rateStart = 0;
    std::size_t macroCount = 0;
    while ((rateStart = xml.find("<kineticLaw>", rateStart)) != std::string::npos) {
        const auto rateEnd = xml.find("</kineticLaw>", rateStart);
        REQUIRE(rateEnd != std::string::npos);
        const auto kineticLaw = xml.substr(rateStart, rateEnd - rateStart);
        CHECK(kineticLaw.find("<ci> sat </ci>") == std::string::npos);
        CHECK(kineticLaw.find("<ci> mm </ci>") == std::string::npos);
        CHECK(kineticLaw.find("<ci> hill </ci>") == std::string::npos);
        CHECK(kineticLaw.find("<ci> kcat </ci>") != std::string::npos);
        CHECK(kineticLaw.find("<ci> Km </ci>") != std::string::npos);
        CHECK(kineticLaw.find("<ci> S1 </ci>") != std::string::npos);
        // BNG2 RateLaw.pm and BNG3 OdeIntegrator retain additional reactants
        // as multiplicative factors for Sat and Hill; keep SBML aligned.
        CHECK(kineticLaw.find("<ci> S2 </ci>") != std::string::npos);
        ++macroCount;
        rateStart = rateEnd + std::string("</kineticLaw>").size();
    }
    CHECK(macroCount == 3);
}

TEST_CASE("unit-free SBML retains the legacy substance definition") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
  k 1
end parameters
)BNGL");
    REQUIRE(model != nullptr);

    const auto xml = bng::io::SbmlWriter::write(*model, nullptr);
    CHECK(xml.find("id=\"substance\"") != std::string::npos);
    CHECK(xml.find("units=\"nM\"") == std::string::npos);
}

TEST_CASE("BNGL writer round-trips unit declarations and annotations") {
    const auto model = unitModel();
    REQUIRE(model != nullptr);

    const auto bngl = bng::io::BnglWriter::write(*model);
    CHECK(bngl.find("begin units") != std::string::npos);
    CHECK(bngl.find("unit per_s = second^-1") != std::string::npos);
    CHECK(bngl.find("[nM]") != std::string::npos);
    CHECK(bngl.find("[fL]") != std::string::npos);

    const auto reparsed = bng::parser::parseModel(bngl);
    REQUIRE(reparsed != nullptr);
    CHECK(reparsed->getParameters().get("KD").getUnitName() == "nM");
    CHECK(reparsed->getCompartments().front().getUnitName() == "fL");
    CHECK(reparsed->getSeedSpecies().front().getUnitName() == "molecule");
}

TEST_CASE("unit-aware network lowering converts concentration seeds and rates once") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    substanceUnits = item
    volumeUnits = fL
  end units
  begin molecule types
    A()
  end molecule types
  begin compartments
    cell 3 1 [fL]
  end compartments
  begin parameters
    kon = 1 [M^-1*s^-1]
  end parameters
  begin seed species
    A()@cell 1 [M]
  end seed species
end model
)BNGL");
    REQUIRE(model != nullptr);

    bng::engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(0);
    REQUIRE(network.species.size() == 1);
    CHECK(network.species.get(0).getAmount() == Catch::Approx(6.02214076e8));

    const bng::ast::Rxn reaction("R", {0, 0}, {0}, "kon");
    const auto factor = bng::io::NetWriter::computeUnitConversionFactor(
        reaction, *model, network);
    REQUIRE(factor.has_value());
    CHECK(*factor == Catch::Approx(1.0e15 / 6.02214076e23));
}

TEST_CASE("SBML Core writer and reader preserve unit metadata together") {
    const auto model = unitModel();
    REQUIRE(model != nullptr);
    const auto path = std::filesystem::temp_directory_path() / "bng3_sbml_units_roundtrip.xml";
    {
        std::ofstream output(path);
        output << bng::io::SbmlWriter::write(*model, nullptr);
    }
    const auto parsed = bng::io::SbmlReader::parse(path);
    std::filesystem::remove(path);

    REQUIRE(parsed.success);
    CHECK(parsed.unitDefaults.at("substanceUnits") == "item");
    CHECK(parsed.unitDefaults.at("volumeUnits") == "litre");
    CHECK(parsed.unitDefinitions.at("nM").find("mole") != std::string::npos);
    CHECK(parsed.parameterUnits.at("KD") == "nM");
    CHECK(parsed.compartmentUnits.at("cyto") == "fL");
    REQUIRE(parsed.speciesUnits.size() == 1);
    CHECK(parsed.speciesUnits.front() == "item");
    REQUIRE(parsed.speciesInitialConcentrations.size() == 1);
    CHECK_FALSE(parsed.speciesInitialConcentrations.front());
}
