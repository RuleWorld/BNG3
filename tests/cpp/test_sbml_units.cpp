#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <filesystem>
#include <fstream>
#include <cmath>
#include <string>

#include "io/BnglWriter.hpp"
#include "io/NetWriter.hpp"
#include "io/SbmlMultiWriter.hpp"
#include "io/SbmlReader.hpp"
#include "io/SbmlUnitWriter.hpp"
#include "io/SbmlWriter.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "compile/CompiledModel.hpp"
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

const auto l2UnitModel = [] {
    return bng::parser::parseModel(R"BNGL(
begin model
  setOption("units", "strict")
  begin units
    timeUnits = bng_minute
    substanceUnits = item
    volumeUnits = litre
    extentUnits = item
    unit bng_minute = 60 * second
  end units
  begin molecule types
    A()
  end molecule types
  begin compartments
    cyto 3 1 [fL]
  end compartments
  begin parameters
    koff = 0.02 [second^-1]
  end parameters
  begin seed species
    A()@cyto 10 [molecule]
  end seed species
end model
)BNGL");
};

std::string startTag(const std::string& xml, const std::string& opening) {
    const auto begin = xml.find(opening);
    if (begin == std::string::npos) return {};
    const auto end = xml.find('>', begin);
    if (end == std::string::npos) return {};
    return xml.substr(begin, end - begin + 1);
}

std::string attributeValue(const std::string& tag, const std::string& name) {
    const auto marker = name + "=\"";
    const auto begin = tag.find(marker);
    if (begin == std::string::npos) return {};
    const auto valueBegin = begin + marker.size();
    const auto end = tag.find('"', valueBegin);
    return end == std::string::npos ? std::string{} :
        tag.substr(valueBegin, end - valueBegin);
}

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

TEST_CASE("SBML-Multi rejects unit-aware reaction rates it cannot convert") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeUnits = second
    substanceUnits = item
    volumeUnits = fL
    unit per_s = second^-1
  end units
  begin parameters
    k = 1 [per_s]
  end parameters
  begin molecule types
    A()
  end molecule types
  begin compartments
    cell 3 1 [fL]
  end compartments
  begin seed species
    A()@cell 1 [M]
  end seed species
  begin reaction rules
    A() -> 0 k
  end reaction rules
end model
)BNGL");
    REQUIRE(model != nullptr);

    CHECK_THROWS_WITH(
        bng::io::SbmlMultiWriter::write(*model),
        Catch::Matchers::ContainsSubstring("cannot preserve unit-aware reaction-rule rates"));
}

TEST_CASE("SBML species export uses the standard substanceUnits attribute") {
    const auto model = unitModel();
    REQUIRE(model != nullptr);

    const auto core = bng::io::SbmlWriter::write(*model, nullptr);
    const auto multi = bng::io::SbmlMultiWriter::write(*model);
    const auto coreSpecies = startTag(core, "<species id=\"S1\"");
    const auto multiSpecies = startTag(multi, "<species id=\"S1\"");
    REQUIRE_FALSE(coreSpecies.empty());
    REQUIRE_FALSE(multiSpecies.empty());
    CHECK(coreSpecies.find(" substanceUnits=\"item\"") != std::string::npos);
    CHECK(coreSpecies.find(" units=\"") == std::string::npos);
    CHECK(multiSpecies.find(" substanceUnits=\"item\"") != std::string::npos);
    CHECK(multiSpecies.find(" units=\"") == std::string::npos);

    const auto concentrationModel = bng::parser::parseModel(R"BNGL(
begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeUnits = second
    substanceUnits = item
    volumeUnits = fL
    unit per_s = second^-1
  end units
  begin parameters
    k = 1 [per_s]
  end parameters
  begin molecule types
    A()
  end molecule types
  begin compartments
    cell 3 1 [fL]
  end compartments
  begin seed species
    A()@cell 1 [M]
  end seed species
end model
)BNGL");
    REQUIRE(concentrationModel != nullptr);
    const auto concentrationCore = bng::io::SbmlWriter::write(*concentrationModel, nullptr);
    const auto concentrationMulti = bng::io::SbmlMultiWriter::write(*concentrationModel);
    for (const auto* xml : {&concentrationCore, &concentrationMulti}) {
        const auto species = startTag(*xml, "<species id=\"S1\"");
        REQUIRE_FALSE(species.empty());
        CHECK(species.find("substanceUnits=\"item\"") != std::string::npos);
        CHECK(species.find("initialConcentration=") == std::string::npos);
        CHECK(std::stod(attributeValue(species, "initialAmount")) ==
              Catch::Approx(6.02214076e8).epsilon(1e-12));
    }
}

TEST_CASE("SBML L2V3 carries model unit defaults in reserved unit definitions") {
    const auto model = l2UnitModel();
    REQUIRE(model != nullptr);

    bng::io::SbmlWriter::Options options;
    options.level = 2;
    options.version = 3;
    const auto xml = bng::io::SbmlWriter::write(*model, nullptr, options);
    const auto modelTag = startTag(xml, "<model ");
    const auto species = startTag(xml, "<species id=\"S1\"");
    REQUIRE_FALSE(modelTag.empty());
    REQUIRE_FALSE(species.empty());
    CHECK(modelTag.find("timeUnits=") == std::string::npos);
    CHECK(modelTag.find("substanceUnits=") == std::string::npos);
    CHECK(xml.find("<unitDefinition id=\"time\">") != std::string::npos);
    CHECK(xml.find("<unitDefinition id=\"volume\">") != std::string::npos);
    CHECK(xml.find("kind=\"dimensionless\" exponent=\"1\" multiplier=\"60\"") !=
          std::string::npos);
    const auto timeDefinitionBegin = xml.find("<unitDefinition id=\"time\">");
    REQUIRE(timeDefinitionBegin != std::string::npos);
    const auto timeDefinitionEnd = xml.find("</unitDefinition>", timeDefinitionBegin);
    REQUIRE(timeDefinitionEnd != std::string::npos);
    const auto timeDefinition = xml.substr(
        timeDefinitionBegin, timeDefinitionEnd - timeDefinitionBegin);
    CHECK(timeDefinition.find(
              "<unit kind=\"second\" exponent=\"1\" multiplier=\"60\" scale=\"0\"/>") !=
          std::string::npos);
    CHECK(timeDefinition.find("kind=\"dimensionless\"") == std::string::npos);
    CHECK(xml.find("<unitDefinition id=\"substance\">") != std::string::npos);
    CHECK(species.find(" substanceUnits=\"item\"") != std::string::npos);
    CHECK(species.find(" units=\"") == std::string::npos);
}

TEST_CASE("SBML L2V3 reader recovers reserved model defaults and species units") {
    const auto model = l2UnitModel();
    REQUIRE(model != nullptr);

    bng::io::SbmlWriter::Options options;
    options.level = 2;
    options.version = 3;
    const auto path = std::filesystem::temp_directory_path() /
        "bng3_sbml_units_l2_roundtrip.xml";
    {
        std::ofstream output(path);
        output << bng::io::SbmlWriter::write(*model, nullptr, options);
    }
    const auto parsed = bng::io::SbmlReader::parse(path);
    std::filesystem::remove(path);

    REQUIRE(parsed.success);
    CHECK(parsed.unitDefaults.at("timeUnits") == "time");
    CHECK(parsed.unitDefinitions.at("time").find("60*second") !=
          std::string::npos);
    CHECK(parsed.unitDefaults.at("substanceUnits") == "substance");
    CHECK(parsed.unitDefaults.at("volumeUnits") == "volume");
    REQUIRE(parsed.speciesUnits.size() == 1);
    CHECK(parsed.speciesUnits.front() == "item");
}

TEST_CASE("SBML L2V3 rejects a distinct extent default") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin model
  setOption("units", "strict")
  begin units
    substanceUnits = item
    extentUnits = mole
  end units
end model
)BNGL");
    REQUIRE(model != nullptr);

    bng::io::SbmlWriter::Options options;
    options.level = 2;
    options.version = 3;
    CHECK_THROWS_WITH(
        bng::io::SbmlWriter::write(*model, nullptr, options),
        Catch::Matchers::ContainsSubstring("extentUnits='mole'") &&
            Catch::Matchers::ContainsSubstring("substanceUnits must be physically equivalent"));
}

TEST_CASE("SBML L2V3 rejects extent units with a near but non-unit conversion factor") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin model
  setOption("units", "strict")
  begin units
    substanceUnits = item
    extentUnits = almost_item
    unit almost_item = 1.0000000000005 * item
  end units
end model
)BNGL");
    REQUIRE(model != nullptr);

    bng::io::SbmlWriter::Options options;
    options.level = 2;
    options.version = 3;
    CHECK_THROWS_WITH(
        bng::io::SbmlWriter::write(*model, nullptr, options),
        Catch::Matchers::ContainsSubstring("extentUnits='almost_item'"));
}

TEST_CASE("SBML L2V3 rejects conflicting authored reserved unit IDs") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin model
  setOption("units", "strict")
  begin units
    timeUnits = second
    unit time = 60 * second
  end units
  begin parameters
    elapsed = 1 [time]
  end parameters
end model
)BNGL");
    REQUIRE(model != nullptr);

    bng::io::SbmlWriter::Options options;
    options.level = 2;
    options.version = 3;
    CHECK_THROWS_WITH(
        bng::io::SbmlWriter::write(*model, nullptr, options),
        Catch::Matchers::ContainsSubstring("reserved UnitDefinition id 'time'"));
}

TEST_CASE("SBML L2V3 validates model default dimensions") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin model
  setOption("units", "strict")
  begin units
    timeUnits = litre
  end units
end model
)BNGL");
    REQUIRE(model != nullptr);

    bng::io::SbmlWriter::Options options;
    options.level = 2;
    options.version = 3;
    CHECK_THROWS_WITH(
        bng::io::SbmlWriter::write(*model, nullptr, options),
        Catch::Matchers::ContainsSubstring("timeUnits='litre' must have time dimension"));
}

TEST_CASE("compiled unit references drive SBML unit emission") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin units
  timeUnits = second
  substanceUnits = item
  volumeUnits = litre
  unit per_s = second^-1
end units
begin parameters
  k = 1 [second^-2]
end parameters
)BNGL");
    REQUIRE(model != nullptr);

    const bng::compile::CompiledModel compiled(*model);
    const auto& unitReferences = compiled.metadata().resolvedUnitReferences;
    REQUIRE(unitReferences.count("per_s") == 1);
    REQUIRE(unitReferences.count("second^-2") == 1);
    CHECK(unitReferences.at("per_s").namedDefinition);
    CHECK_FALSE(unitReferences.at("second^-2").namedDefinition);
    CHECK(unitReferences.at("second^-2").unit.baseExponents.at(
              bng::units::BaseUnit::Second) == -2);
    CHECK(bng::io::sbml_units::enabled(compiled));
    CHECK(bng::io::sbml_units::modelAttributes(compiled).find(
              "timeUnits=\"second\"") != std::string::npos);
    CHECK(bng::io::sbml_units::attribute(compiled, "per_s") ==
          " units=\"per_s\"");
    CHECK(bng::io::sbml_units::attribute(compiled, "second^-2") ==
          " units=\"bng_unit_second__2\"");

    const auto definitions = bng::io::sbml_units::writeUnitDefinitions(compiled);
    CHECK(definitions.find("id=\"per_s\"") != std::string::npos);
    CHECK(definitions.find("id=\"bng_unit_second__2\"") != std::string::npos);
    CHECK(definitions.find(
              "kind=\"second\" exponent=\"-2\" multiplier=\"1\" scale=\"0\"") !=
          std::string::npos);
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

TEST_CASE("SBML Core preserves unit-aware first-order decay on the generated count basis") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeUnits = second
    substanceUnits = item
    volumeUnits = fL
    extentUnits = item
    unit per_s = second^-1
  end units
  begin parameters
    k = 0.1 [per_s]
  end parameters
  begin molecule types
    A()
  end molecule types
  begin compartments
    cell 3 1 [fL]
  end compartments
  begin seed species
    A()@cell 1 [M]
  end seed species
  begin reaction rules
    A() -> 0 k
  end reaction rules
end model
)BNGL");
    REQUIRE(model != nullptr);

    bng::engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    REQUIRE(network.species.size() == 1);
    CHECK(network.species.get(0).getAmount() == Catch::Approx(6.02214076e8));

    bng::engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 10.0;
    options.nSteps = 10;
    const auto trajectory = bng::engine::OdeIntegrator(*model, network).integrate(options);
    REQUIRE_FALSE(trajectory.concentrations.empty());
    const double remaining = trajectory.concentrations.back().front() /
        network.species.get(0).getAmount();
    CHECK(remaining == Catch::Approx(std::exp(-0.1 * options.tEnd)).epsilon(2e-6));

    const auto xml = bng::io::SbmlWriter::write(*model, &network);
    const auto modelTag = startTag(xml, "<model ");
    const auto species = startTag(xml, "<species id=\"S1\"");
    REQUIRE_FALSE(modelTag.empty());
    REQUIRE_FALSE(species.empty());
    CHECK(attributeValue(modelTag, "timeUnits") == "second");
    CHECK(attributeValue(modelTag, "substanceUnits") == "item");
    CHECK(attributeValue(modelTag, "extentUnits") == "item");
    CHECK(attributeValue(species, "substanceUnits") == "item");
    CHECK(std::stod(attributeValue(species, "initialAmount")) ==
          Catch::Approx(network.species.get(0).getAmount()).margin(1e-6));
    CHECK(xml.find("<parameter id=\"k\"") != std::string::npos);
    CHECK(xml.find("units=\"per_s\"") != std::string::npos);
    const auto lawStart = xml.find("<kineticLaw>");
    REQUIRE(lawStart != std::string::npos);
    const auto lawEnd = xml.find("</kineticLaw>", lawStart);
    REQUIRE(lawEnd != std::string::npos);
    const auto kineticLaw = xml.substr(lawStart, lawEnd - lawStart);
    CHECK(kineticLaw.find("<ci> k </ci>") != std::string::npos);
    CHECK(kineticLaw.find("<ci> S1 </ci>") != std::string::npos);
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
