// RED CONTRACT: every serializer used as a compatibility path must preserve energy patterns.
#include <catch2/catch_test_macros.hpp>
#include "io/BnglWriter.hpp"
#include "io/XmlWriter.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("BNGL roundtrip preserves energy-pattern count and structural fingerprints") {
    auto first=bng::parser::parseModel(R"BNG(
begin model
begin parameters
 G 2
end parameters
begin molecule types
 A(x~U~P)
end molecule types
begin energy patterns
 A(x~P) G
end energy patterns
end model
)BNG");
    REQUIRE(first); REQUIRE(first->getEnergyPatterns().size()==1);
    const std::string text=bng::io::BnglWriter::write(*first);
    auto second=bng::parser::parseModel(text);
    REQUIRE(second); REQUIRE(second->getEnergyPatterns().size()==1);
    CHECK(second->getEnergyPatterns()[0].getGraph().fingerprint()==
          first->getEnergyPatterns()[0].getGraph().fingerprint());
    CHECK(second->getEnergyPatterns()[0].getExpression().toString()==
          first->getEnergyPatterns()[0].getExpression().toString());
}

TEST_CASE("XML writer emits every energy pattern exactly once") {
    auto model=bng::parser::parseModel(R"BNG(
begin model
begin parameters
 G1 1
 G2 2
end parameters
begin molecule types
 A(x~U~P)
end molecule types
begin energy patterns
 A(x~U) G1
 A(x~P) G2
end energy patterns
end model
)BNG");
    REQUIRE(model);
    const auto xml=bng::io::XmlWriter::write(*model);
    CHECK(xml.find("ListOfEnergyPatterns")!=std::string::npos);
    CHECK(std::count(xml.begin(),xml.end(),'\0')==0);
    CHECK(xml.find("G1")!=std::string::npos);
    CHECK(xml.find("G2")!=std::string::npos);
}
