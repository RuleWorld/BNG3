#include <algorithm>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers.hpp>

#include "ast/Model.hpp"
#include "compile/Document.hpp"
#include "io/BnglWriter.hpp"
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

TEST_CASE("BNG3 event extension accepts a versioned event block") {
    const auto source = R"BNGL(
begin bng3_events version 1
  event "reset_a"
    trigger: A > 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    delay: 2
    priority: 10
    assignment: A = 0
  end event
  event "pulse_b"
    trigger: time >= 4
    initial_value: true
    persistent: false
    use_values_from_trigger_time: false
    assignment: A = 3
    assignment: B = A + 1
  end event
end bng3_events
)BNGL";

    const auto model = bng::parser::parseModel(source);
    REQUIRE(model != nullptr);
    REQUIRE(model->getEventFormatVersion().has_value());
    CHECK(*model->getEventFormatVersion() == 1);
    REQUIRE(model->getEvents().size() == 2);
    const auto& event = model->getEvents().front();
    CHECK(event.id == "reset_a");
    CHECK(event.trigger.toString() == "(A > 1)");
    CHECK_FALSE(event.initialValue);
    CHECK(event.persistent);
    CHECK(event.useValuesFromTriggerTime);
    REQUIRE(event.delay.has_value());
    CHECK(event.delay->toString() == "2");
    REQUIRE(event.priority.has_value());
    CHECK(event.priority->toString() == "10");
    REQUIRE(event.assignments.size() == 1);
    CHECK(event.assignments.front().target == "A");
    CHECK(event.assignments.front().value.toString() == "0");

    const auto& secondEvent = model->getEvents().at(1);
    CHECK(secondEvent.id == "pulse_b");
    CHECK(secondEvent.initialValue);
    CHECK_FALSE(secondEvent.persistent);
    CHECK_FALSE(secondEvent.useValuesFromTriggerTime);
    CHECK_FALSE(secondEvent.delay.has_value());
    CHECK_FALSE(secondEvent.priority.has_value());
    REQUIRE(secondEvent.assignments.size() == 2);
    CHECK(secondEvent.assignments.at(1).target == "B");
    CHECK(secondEvent.assignments.at(1).value.toString() == "(A + 1)");

    const bng::compile::Document document(*model);
    CHECK_FALSE(document.valid());
    CHECK(std::any_of(document.diagnostics().begin(), document.diagnostics().end(),
                      [](const auto& diagnostic) {
                          return diagnostic.code == bng::compile::DiagnosticCode::UnsupportedFeature &&
                                 diagnostic.category == bng::compile::ValidationCategory::BackendCapability &&
                                 diagnostic.message.find("event execution is not implemented") !=
                                     std::string::npos;
                      }));

    const auto serialized = bng::io::BnglWriter::write(*model);
    const auto reparsed = bng::parser::parseModel(serialized);
    REQUIRE(reparsed != nullptr);
    REQUIRE(reparsed->getEventFormatVersion().has_value());
    CHECK(*reparsed->getEventFormatVersion() == *model->getEventFormatVersion());
    REQUIRE(reparsed->getEvents().size() == model->getEvents().size());
    CHECK(reparsed->getEvents().at(0).trigger.toString() == event.trigger.toString());
    CHECK(reparsed->getEvents().at(1).assignments.at(1).value.toString() ==
          secondEvent.assignments.at(1).value.toString());
}

TEST_CASE("BNG3 event extension rejects unknown format versions") {
    const auto source = R"BNGL(
begin bng3_events version 2
end bng3_events
)BNGL";

    CHECK_THROWS_WITH(bng::parser::parseModel(source),
                      "Unsupported BNG3 event format version: 2");
}

TEST_CASE("BNG3 event extension rejects duplicate event ids") {
    const auto source = R"BNGL(
begin bng3_events version 1
  event "same"
    trigger: A > 0
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
  end event
  event "same"
    trigger: A > 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
  end event
end bng3_events
)BNGL";

    CHECK_THROWS_WITH(bng::parser::parseModel(source), "duplicate BNG3 event id 'same'");
}

TEST_CASE("BNG3 event keywords remain usable as legacy model identifiers") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
  event = 1
  delay = event + 1
  bng3_events = delay
end parameters
begin molecule types
  trigger(delay)
end molecule types
)BNGL");

    REQUIRE(model != nullptr);
    CHECK(model->getParameters().get("event").getValue() == 1.0);
    CHECK(model->getParameters().get("delay").getValue() == 2.0);
    CHECK(model->getParameters().get("bng3_events").getValue() == 2.0);
    REQUIRE(model->getMoleculeTypes().size() == 1);
    CHECK(model->getMoleculeTypes().front().getName() == "trigger");
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

TEST_CASE("priority is preserved as molecule, molecule type, and parameter name") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
  priority = 2
  rate = priority + 1
end parameters
begin molecule types
  priority(x)
end molecule types
begin seed species
  priority(x) 3
end seed species
)BNGL");

    REQUIRE(model != nullptr);
    REQUIRE(model->getMoleculeTypes().size() == 1);
    CHECK(model->getMoleculeTypes().front().getName() == "priority");
    REQUIRE(model->getSeedSpecies().size() == 1);
    CHECK(model->getSeedSpecies().front().getPattern() == "priority(x)");
    CHECK(model->getParameters().get("priority").getValue() == 2.0);
    CHECK(model->getParameters().get("rate").getValue() == 3.0);
}

TEST_CASE("priority is retained as an observable name") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin molecule types
  A()
end molecule types
begin seed species
  A() 3
end seed species
begin observables
  Molecules priority A()
end observables
)BNGL");

    REQUIRE(model != nullptr);
    REQUIRE(model->getObservables().size() == 1);
    CHECK(model->getObservables().front().getName() == "priority");
    CHECK(model->getObservables().front().getType() == "Molecules");
}

TEST_CASE("priority observable references do not consume rule or event priority syntax") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
  priority = 2
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules priority A()
end observables
begin reaction rules
  A() -> A() priority priority=5
  A() -> A() priority()
end reaction rules
begin bng3_events version 1
  event "uses_priority_identifier"
    trigger: time >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    priority: priority + 1
    assignment: priority = 0
  end event
end bng3_events
)BNGL");

    REQUIRE(model != nullptr);
    REQUIRE(model->getReactionRules().size() == 2);
    const auto& modifiedRule = model->getReactionRules().at(0);
    REQUIRE(modifiedRule.getRates().size() == 1);
    CHECK(modifiedRule.getRates().front().kind() == bng::ast::ExpressionKind::Identifier);
    CHECK(modifiedRule.getRates().front().name() == "priority");
    CHECK(modifiedRule.getModifiers() == std::vector<std::string>{"priority=5"});

    const auto& observableRate = model->getReactionRules().at(1).getRates().front();
    CHECK(observableRate.kind() == bng::ast::ExpressionKind::ObservableRef);
    CHECK(observableRate.name() == "priority");

    REQUIRE(model->getEvents().size() == 1);
    const auto& event = model->getEvents().front();
    REQUIRE(event.priority.has_value());
    CHECK(event.priority->toString() == "(priority + 1)");
    REQUIRE(event.assignments.size() == 1);
    CHECK(event.assignments.front().target == "priority");
}
