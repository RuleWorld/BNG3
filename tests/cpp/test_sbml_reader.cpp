#include <catch2/catch_test_macros.hpp>

#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>

#include "io/SbmlReader.hpp"
#include "tinyxml.h"

namespace {

void replaceAll(std::string& text, const std::string& from, const std::string& to) {
    std::size_t start = 0;
    while ((start = text.find(from, start)) != std::string::npos) {
        text.replace(start, from.size(), to);
        start += to.size();
    }
}

}  // namespace

TEST_CASE("SBML reader imports a flat reaction network", "[SbmlReader]") {
    const auto path = std::filesystem::temp_directory_path() / "bng3_sbml_reader_test.xml";
    std::ofstream out(path);
    out << R"xml(<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version3" level="2" version="3">
  <model id="flat">
    <listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialAmount="2" name="A()"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="3"/></listOfParameters>
    <listOfRules>
      <assignmentRule variable="dim"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math></assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="S1"/></listOfReactants>
        <listOfProducts/>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>S1</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>)xml";
    out.close();

    const auto parsed = bng::io::SbmlReader::parse(path);
    std::filesystem::remove(path);

    REQUIRE(parsed.success);
    REQUIRE(parsed.parameters.at("k") == 3.0);
    REQUIRE(parsed.functions.size() == 1);
    CHECK(parsed.functions.front().first == "dim");
    CHECK(parsed.functions.front().second == "k");
    REQUIRE(parsed.species.size() == 1);
    CHECK(parsed.species.front().first == "@cell::A()");
    CHECK(parsed.species.front().second == "2");
    REQUIRE(parsed.reactions.size() == 1);
    CHECK(parsed.reactions.front().find("1 1 0 k") != std::string::npos);
}

TEST_CASE("SBML reader rejects atomized conversion requests", "[SbmlReader]") {
    const auto path = std::filesystem::temp_directory_path() / "bng3_sbml_reader_atomize.xml";
    std::ofstream out(path);
    out << "<sbml><model id=\"empty\"/></sbml>\n";
    out.close();

    const auto parsed = bng::io::SbmlReader::parse(path, true);
    std::filesystem::remove(path);

    REQUIRE_FALSE(parsed.success);
    CHECK_FALSE(parsed.error.empty());
}

TEST_CASE("SBML reader recognizes structured BNG2 schema independent of IDs",
          "[SbmlReader]") {
    const auto source = std::filesystem::path(BNG3_SOURCE_DIR) / "tests" /
        "validation" / "Validate" / "INPUT_FILES" /
        "test_sbml_structured_SBML.xml";
    std::ifstream input(source);
    REQUIRE(input.good());
    std::string xml((std::istreambuf_iterator<char>(input)),
                    std::istreambuf_iterator<char>());
    replaceAll(xml, "id=\"plain2\"", "id=\"renamed_structured_model\"");
    replaceAll(xml, "MolA_MolB", "Alpha_Beta");
    replaceAll(xml, "MolA-P", "Alpha-P");
    replaceAll(xml, "(MolB)2", "(Beta)2");
    replaceAll(xml, "MolA", "Alpha");
    replaceAll(xml, "MolB", "Beta");
    replaceAll(xml, "S1", "species_a");
    replaceAll(xml, "S2", "species_b");
    replaceAll(xml, "S3", "complex_ab");
    replaceAll(xml, "S4", "modified_a");
    replaceAll(xml, "S5", "dimer_b");

    const auto path = std::filesystem::temp_directory_path() /
        "bng3_sbml_reader_structured_renamed.xml";
    std::ofstream out(path);
    out << xml;
    out.close();

    const auto parsed = bng::io::SbmlReader::parse(path, true);
    std::filesystem::remove(path);

    REQUIRE(parsed.success);
    REQUIRE(parsed.species.size() == 5);
    REQUIRE(parsed.reactions.size() == 5);
    REQUIRE_FALSE(parsed.functions.empty());
    CHECK(parsed.functions.front().first.rfind("functionRate", 0) == 0);
    CHECK(parsed.functions.front().second == "k3_f*2");
    CHECK(parsed.species.front().first.find("Alpha(_p~0,beta)") != std::string::npos);
}

TEST_CASE("SBML reader rejects fractional stoichiometry instead of rounding",
          "[SbmlReader]") {
    const auto path = std::filesystem::temp_directory_path() /
        "bng3_sbml_reader_fractional_stoich.xml";
    std::ofstream out(path);
    out << R"xml(<sbml><model id="flat"><listOfSpecies>
<species id="A" initialAmount="1" name="A"/>
</listOfSpecies><listOfReactions><reaction id="R">
<listOfReactants><speciesReference species="A" stoichiometry="1.5"/></listOfReactants>
<listOfProducts/><kineticLaw><math><ci>k</ci></math></kineticLaw>
</reaction></listOfReactions></model></sbml>)xml";
    out.close();

    const auto parsed = bng::io::SbmlReader::parse(path);
    std::filesystem::remove(path);

    REQUIRE_FALSE(parsed.success);
    CHECK(parsed.error.find("positive integer") != std::string::npos);
}

TEST_CASE("SBML reader preserves grouping in compound kinetic laws",
          "[SbmlReader]") {
    const auto path = std::filesystem::temp_directory_path() /
        "bng3_sbml_reader_compound_rate.xml";
    std::ofstream out(path);
    out << R"xml(<sbml xmlns="http://www.sbml.org/sbml/level2/version3" level="2" version="3">
  <model id="compound_rate">
    <listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>
    <listOfSpecies><species id="S1" compartment="cell" initialAmount="1" name="A()"/></listOfSpecies>
    <listOfReactions><reaction id="R1" reversible="false">
      <listOfReactants><speciesReference species="S1"/></listOfReactants>
      <listOfProducts/>
      <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/>
        <apply><minus/><ci>k_forward</ci><ci>k_reverse</ci></apply><ci>S1</ci>
      </apply></math></kineticLaw>
    </reaction></listOfReactions>
  </model>
</sbml>)xml";
    out.close();

    const auto parsed = bng::io::SbmlReader::parse(path);
    std::filesystem::remove(path);

    REQUIRE(parsed.success);
    REQUIRE(parsed.reactions.size() == 1);
    CHECK(parsed.reactions.front().find("(k_forward-k_reverse)") != std::string::npos);
}

TEST_CASE("TinyXML parses numeric character references in source order") {
    TiXmlDocument document;
    document.Parse("<root>&#x41;&#xA9;&#160;</root>", nullptr, TIXML_ENCODING_UTF8);

    REQUIRE_FALSE(document.Error());
    const auto* root = document.FirstChildElement("root");
    REQUIRE(root != nullptr);
    REQUIRE(root->GetText() != nullptr);
    const std::string expected = std::string("A") + "\xC2\xA9\xC2\xA0";
    CHECK(root->GetText() == expected);
}

TEST_CASE("SBML reader preserves Core unit metadata") {
    const auto path = std::filesystem::temp_directory_path() / "bng3_sbml_reader_units.xml";
    std::ofstream out(path);
    out << R"xml(<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version3" level="2" version="3">
  <model id="units" substanceUnits="item" volumeUnits="fL">
    <listOfUnitDefinitions>
      <unitDefinition id="per_s"><listOfUnits>
        <unit kind="second" exponent="-1"/>
      </listOfUnits></unitDefinition>
      <unitDefinition id="nM"><listOfUnits>
        <unit kind="mole" exponent="1" scale="-9"/>
        <unit kind="litre" exponent="-1"/>
      </listOfUnits></unitDefinition>
    </listOfUnitDefinitions>
    <listOfCompartments>
      <compartment id="cell" size="1" units="fL"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialAmount="2" units="item" name="A()"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="3" units="per_s"/>
    </listOfParameters>
  </model>
</sbml>)xml";
    out.close();

    const auto parsed = bng::io::SbmlReader::parse(path);
    std::filesystem::remove(path);

    REQUIRE(parsed.success);
    CHECK(parsed.unitDefaults.at("substanceUnits") == "item");
    CHECK(parsed.unitDefaults.at("volumeUnits") == "fL");
    CHECK(parsed.unitDefinitions.at("per_s") == "second^-1");
    CHECK(parsed.unitDefinitions.at("nM").find("mole") != std::string::npos);
    CHECK(parsed.parameterUnits.at("k") == "per_s");
    CHECK(parsed.compartmentUnits.at("cell") == "fL");
    REQUIRE(parsed.speciesUnits.size() == 1);
    CHECK(parsed.speciesUnits.front() == "item");
}
