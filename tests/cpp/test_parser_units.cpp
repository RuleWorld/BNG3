#include <algorithm>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "ast/Model.hpp"
#include "compile/Document.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("BNGL unit annotations are preserved in the canonical AST") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin units
  timeunits second
  substanceUnits item
  volumeUnits litre
  unit per_s = second^-1
end units
begin parameters
  KD = 100 [nM]
  koff = 0.02 [per_s]
  kon = koff / KD
  Vcell = 1.0 [fL]
end parameters
begin compartments
  cyto 3 Vcell [fL]
end compartments
begin seed species
  A()@cyto 10 [molecule]
end seed species
)BNGL");

    REQUIRE(model != nullptr);
    REQUIRE(model->getParameters().contains("KD"));
    REQUIRE(model->getParameters().contains("koff"));
    REQUIRE(model->getParameters().contains("kon"));
    CHECK(model->getParameters().get("KD").hasUnit());
    CHECK(model->getParameters().get("KD").getUnitName() == "nM");
    CHECK(model->getParameters().get("koff").getUnitName() == "per_s");
    CHECK(model->getUnitDefaults().at("timeUnits") == "second");
    REQUIRE(model->getCompartments().size() == 1);
    CHECK(model->getCompartments().front().getUnitName() == "fL");
    REQUIRE(model->getSeedSpecies().size() == 1);
    CHECK(model->getSeedSpecies().front().getUnitName() == "molecule");
}

TEST_CASE("unit syntax does not reserve ordinary BNGL identifiers") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
  s = 2 [s]
  M = 3 [M]
end parameters
)BNGL");

    REQUIRE(model != nullptr);
    CHECK(model->getParameters().get("s").getValue() == 2.0);
    CHECK(model->getParameters().get("s").getUnitName() == "s");
    CHECK(model->getParameters().get("M").getUnitName() == "M");
}

TEST_CASE("legacy models remain unit-free without unit annotations") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
  koff 0.02
end parameters
)BNGL");

    REQUIRE(model != nullptr);
    CHECK_FALSE(model->getParameters().get("koff").hasUnit());
    CHECK(model->getParameters().get("koff").getValue() == 0.02);
}

TEST_CASE("compiled unit metadata follows parameter dependencies") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
  KD = 100 [nM]
  koff = 0.02 [s^-1]
  kon = koff / KD
end parameters
)BNGL");

    REQUIRE(model != nullptr);
    const bng::compile::Document document(*model);
    REQUIRE(document.valid());
    const auto& parameters = document.model().parameters();
    REQUIRE(parameters.size() == 3);
    CHECK(parameters[0].unitName == "nM");
    REQUIRE(parameters[0].normalizedValue.has_value());
    CHECK(*parameters[0].normalizedValue == Catch::Approx(1e-4));
    CHECK(parameters[1].unitName == "s^-1");
    REQUIRE(parameters[1].normalizedValue.has_value());
    CHECK(*parameters[1].normalizedValue == Catch::Approx(0.02));
    REQUIRE(parameters[2].inferredUnit.has_value());
    CHECK(parameters[2].inferredUnit->dimension == bng::units::Dimension {-1, 3, -1});
    REQUIRE(parameters[2].normalizedValue.has_value());
    CHECK(*parameters[2].normalizedValue == Catch::Approx(200.0));
}

TEST_CASE("incompatible annotated arithmetic fails closed in the compiler") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
  KD = 100 [nM]
  koff = 0.02 [s^-1]
  invalid = KD + koff
end parameters
)BNGL");

    REQUIRE(model != nullptr);
    const bng::compile::Document document(*model);
    CHECK_FALSE(document.valid());
    CHECK(std::any_of(document.diagnostics().begin(), document.diagnostics().end(),
                      [](const auto& diagnostic) {
                          return diagnostic.category == bng::compile::ValidationCategory::Units &&
                                 diagnostic.message.find("cannot combine") != std::string::npos;
                      }));
}

TEST_CASE("strict unit mode rejects unsupported dynamic expressions") {
    const auto model = bng::parser::parseModel(R"BNGL(
setOption("units", "strict")
begin parameters
  KD = 100 [nM]
  k = sqrt(KD)
end parameters
)BNGL");

    REQUIRE(model != nullptr);
    const bng::compile::Document document(*model);
    CHECK_FALSE(document.valid());
    CHECK(std::any_of(document.diagnostics().begin(), document.diagnostics().end(),
                      [](const auto& diagnostic) {
                          return diagnostic.category == bng::compile::ValidationCategory::Units &&
                                 diagnostic.message.find("complete unit expression") != std::string::npos;
                      }));
}

TEST_CASE("rule molecularity is checked against annotated rate dimensions") {
    const auto valid = bng::parser::parseModel(R"BNGL(
begin parameters
  kon = 1 [M^-1*s^-1]
end parameters
begin molecule types
  A(x)
  B(y)
  C(z)
end molecule types
begin reaction rules
  A(x) + B(y) -> C(z) kon
end reaction rules
)BNGL");
    REQUIRE(valid != nullptr);
    CHECK(bng::compile::Document(*valid).valid());
    CHECK(bng::compile::capabilitiesFor(*valid, bng::compile::BackendKind::Network)
              .state(bng::compile::Feature::Units) ==
          bng::compile::CapabilityState::ExactLowering);
    CHECK(bng::compile::capabilitiesFor(*valid, bng::compile::BackendKind::NFsim)
              .state(bng::compile::Feature::Units) ==
          bng::compile::CapabilityState::Unsupported);

    const auto invalid = bng::parser::parseModel(R"BNGL(
begin parameters
  kon = 1 [s^-1]
end parameters
begin molecule types
  A(x)
  B(y)
  C(z)
end molecule types
begin reaction rules
  A(x) + B(y) -> C(z) kon
end reaction rules
)BNGL");
    REQUIRE(invalid != nullptr);
    const bng::compile::Document document(*invalid);
    CHECK_FALSE(document.valid());
    CHECK(std::any_of(document.diagnostics().begin(), document.diagnostics().end(),
                      [](const auto& diagnostic) {
                          return diagnostic.category == bng::compile::ValidationCategory::Units &&
                                 diagnostic.message.find("molecularity") != std::string::npos;
                      }));
}
