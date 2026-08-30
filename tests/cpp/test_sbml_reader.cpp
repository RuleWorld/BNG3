#include <catch2/catch_test_macros.hpp>

#include <filesystem>
#include <fstream>
#include <string>

#include "io/SbmlReader.hpp"

TEST_CASE("SBML reader imports a flat reaction network", "[SbmlReader]") {
    const auto path = std::filesystem::temp_directory_path() / "bng3_sbml_reader_test.xml";
    std::ofstream out(path);
    out << R"(<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version3" level="2" version="3">
  <model id="flat">
    <listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialAmount="2" name="A()"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="3"/></listOfParameters>
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
</sbml>)";
    out.close();

    const auto parsed = bng::io::SbmlReader::parse(path);
    std::filesystem::remove(path);

    REQUIRE(parsed.success);
    REQUIRE(parsed.parameters.at("k") == 3.0);
    REQUIRE(parsed.species.size() == 1);
    CHECK(parsed.species.front().first == "@cell::A____()");
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
    CHECK(parsed.error.find("atomize") != std::string::npos);
}
