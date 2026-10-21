// Regression coverage for the SBML delay and rateOf csymbols.
//
// SBML Level 3 Version 2 Core Sec. 4.3.4 (delay) and Sec. 4.3.5 (rateOf)
// define both as MathML <csymbol> operators:
//
//   delay(x, d) -> <apply>
//                    <csymbol encoding="text"
//                             definitionURL="http://www.sbml.org/sbml/symbols/delay">
//                      delay </csymbol>
//                    <ci> x </ci>
//                    <cn> d </cn>
//                  </apply>
//
// MathML has no <delay/> or <rateOf/> operator, so emitting such an element
// would produce a document that libSBML rejects.  libSBML 5.21.1 serializes
// both csymbols in exactly the form above; these tests pin that form and
// check that the native SBML reader reads it back.
#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <filesystem>
#include <fstream>
#include <string>

#include "engine/NetworkGenerator.hpp"
#include "io/SbmlReader.hpp"
#include "io/SbmlWriter.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

namespace {

std::string writeSbml(const char* source) {
    auto model = parser::parseModel(source);
    REQUIRE(model != nullptr);
    // An empty network keeps the writer on the function/assignment-rule path
    // without requiring a compilable rate law.
    engine::GeneratedNetwork network;
    return io::SbmlWriter::write(*model, &network);
}

}  // namespace

TEST_CASE("SBML writer emits the Level 3 Version 2 delay csymbol", "[SbmlWriter][delay]") {
    const std::string xml = writeSbml(R"(
begin model
begin parameters
  x 1
end parameters
begin functions
  y() = delay(x, 1)
end functions
end model
)");

    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<csymbol encoding=\"text\" "
        "definitionURL=\"http://www.sbml.org/sbml/symbols/delay\"> delay </csymbol>"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<apply>\n"
        "            <csymbol encoding=\"text\" "
        "definitionURL=\"http://www.sbml.org/sbml/symbols/delay\"> delay </csymbol>\n"
        "            <ci> x </ci>\n"
        "            <cn> 1 </cn>\n"
        "          </apply>"));
    // MathML has no delay operator; the csymbol form is the only valid one.
    CHECK(xml.find("<delay/>") == std::string::npos);
}

TEST_CASE("SBML writer emits the Level 3 Version 2 rateOf csymbol", "[SbmlWriter][rateOf]") {
    const std::string xml = writeSbml(R"(
begin model
begin parameters
  x 1
end parameters
begin functions
  y() = rateOf(x)
end functions
end model
)");

    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<csymbol encoding=\"text\" "
        "definitionURL=\"http://www.sbml.org/sbml/symbols/rateOf\"> rateOf </csymbol>"));
    CHECK(xml.find("<rateOf/>") == std::string::npos);
}

TEST_CASE("SBML writer rejects a delay csymbol with the wrong arity", "[SbmlWriter][delay]") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  x 1
end parameters
begin functions
  y() = delay(x)
end functions
end model
)");
    REQUIRE(model != nullptr);
    engine::GeneratedNetwork network;
    CHECK_THROWS_AS(io::SbmlWriter::write(*model, &network), std::invalid_argument);
}

TEST_CASE("SBML writer refuses a model function that collides with a history operator",
          "[SbmlWriter][delay]") {
    // "delay" and "rateOf" are SBML history operators, not identifiers.  A
    // model that declares its own function with one of those names cannot be
    // written: the csymbol form would silently change the model's meaning and
    // the identifier form would refer to a function this writer does not
    // emit.
    auto model = parser::parseModel(R"(
begin model
begin parameters
  k 1
  j 2
end parameters
begin functions
  delay(x,y) = x
  f() = delay(k,j)
end functions
end model
)");
    REQUIRE(model != nullptr);
    engine::GeneratedNetwork network;
    CHECK_THROWS_WITH(
        io::SbmlWriter::write(*model, &network),
        Catch::Matchers::ContainsSubstring("collides with the SBML Level 3 Version 2 delay csymbol"));
}

TEST_CASE("SBML writer refuses a model function that collides with rateOf",
          "[SbmlWriter][rateOf]") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  k 1
end parameters
begin functions
  rateOf(x) = x
  f() = rateOf(k)
end functions
end model
)");
    REQUIRE(model != nullptr);
    engine::GeneratedNetwork network;
    CHECK_THROWS_WITH(
        io::SbmlWriter::write(*model, &network),
        Catch::Matchers::ContainsSubstring("collides with the SBML Level 3 Version 2 rateOf csymbol"));
}

TEST_CASE("SBML writer still emits the history operator without a colliding function",
          "[SbmlWriter][delay]") {
    // A function with the same name but without arguments cannot be the
    // target of a two-argument call, so the csymbol stays the right lowering.
    auto model = parser::parseModel(R"(
begin model
begin parameters
  k 1
  j 2
end parameters
begin functions
  delay() = 1
  f() = delay(k,j)
end functions
end model
)");
    REQUIRE(model != nullptr);
    engine::GeneratedNetwork network;
    const auto xml = io::SbmlWriter::write(*model, &network);
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<csymbol encoding=\"text\" "
        "definitionURL=\"http://www.sbml.org/sbml/symbols/delay\"> delay </csymbol>"));
}

TEST_CASE("Native SBML reader accepts the delay and rateOf csymbols", "[SbmlReader][delay]") {
    const auto path = std::filesystem::temp_directory_path() /
        "bng3_sbml_delay_reader_test.xml";
    {
        std::ofstream out(path);
        out << R"xml(<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="delayed">
    <listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialAmount="2" name="A()"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="3"/></listOfParameters>
    <listOfRules>
      <assignmentRule variable="p">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay"> delay </csymbol>
            <ci> k </ci>
            <cn> 1 </cn>
          </apply>
        </math>
      </assignmentRule>
      <assignmentRule variable="q">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/rateOf"> rateOf </csymbol>
            <ci> k </ci>
          </apply>
        </math>
      </assignmentRule>
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
    }
    const auto parsed = bng::io::SbmlReader::parse(path);
    std::filesystem::remove(path);

    REQUIRE(parsed.success);
    REQUIRE(parsed.functions.size() == 2);
    CHECK(parsed.functions[0].second == "delay(k,1)");
    CHECK(parsed.functions[1].second == "rateOf(k)");
}
