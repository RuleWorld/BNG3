#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <filesystem>
#include <cmath>
#include <fstream>
#include <iterator>
#include <memory>
#include <string>

#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "engine/BatchSsa.hpp"
#include "engine/PsaSimulator.hpp"
#include "actions/ActionDispatch.hpp"
#include "io/BnglWriter.hpp"
#include "io/CppExportWriter.hpp"
#include "io/NetWriter.hpp"
#include "io/NetReader.hpp"
#include "io/SbmlWriter.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

namespace {

std::unique_ptr<ast::Model> parse(const std::string& rule,
                                  const std::string& extra = "") {
    return parser::parseModel(R"(
begin model
begin parameters
  tau 2
end parameters
begin molecule types
  A()
  B()
  G()
  M()
end molecule types
begin seed species
  A() 10
  G() 2
end seed species
begin reaction rules
  )" + rule + R"(
end reaction rules
)" + extra + R"(
end model
)");
}

std::string readFile(const std::filesystem::path& path) {
    std::ifstream input(path);
    return std::string(std::istreambuf_iterator<char>(input), {});
}

}  // namespace

TEST_CASE("delayed reaction metadata parses, survives network generation, and round trips") {
    auto model = parse("G() -> G() + M() 0.5 delay=tau+1 NonConsuming");
    REQUIRE(model->getReactionRules().size() == 1);
    const auto& rule = model->getReactionRules().front();
    REQUIRE(rule.getDelayExpression());
    CHECK(rule.getDelayExpression()->toBnglString() == "tau + 1");
    CHECK(rule.isNonConsuming());

    const auto bngl = io::BnglWriter::write(*model);
    CHECK_THAT(bngl, Catch::Matchers::ContainsSubstring("delay=tau + 1 NonConsuming"));
    auto roundTrip = parser::parseModel(bngl);
    REQUIRE(roundTrip->getReactionRules().front().getDelayExpression());
    CHECK(roundTrip->getReactionRules().front().isNonConsuming());

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    REQUIRE(network.reactions.size() == 1);
    CHECK(network.reactions.all().front().getDelayExpression());
    CHECK(network.reactions.all().front().isNonConsuming());

    auto output = std::filesystem::temp_directory_path() / "bng3-delay-net-writer.net";
    io::NetWriterOptions options;
    io::NetWriter::write(output, *model, network, options);
    const auto netText = readFile(output);
    CHECK_THAT(netText, Catch::Matchers::ContainsSubstring("delay=__delay_1 NonConsuming"));
    CHECK_THAT(netText, Catch::Matchers::ContainsSubstring("__delay_1 3"));
    const auto parsedNet = io::NetReader::parse(output);
    REQUIRE(parsedNet.success);
    REQUIRE(parsedNet.parameters.count("__delay_1") == 1);
    CHECK(parsedNet.parameters.at("__delay_1") == Catch::Approx(3.0));
    REQUIRE(parsedNet.reactions.size() == 1);
    CHECK_THAT(parsedNet.reactions.front(),
               Catch::Matchers::ContainsSubstring("delay=__delay_1 NonConsuming"));

    auto reloaded = parser::parseModel(R"(
begin model
begin molecule types
  G()
  M()
end molecule types
begin seed species
  G() 2
end seed species
end model
)");
    reloaded->addAction(ast::Action{
        "readFile", {{"file", output.filename().string()}}});
    reloaded->addAction(ast::Action{
        "simulate", {{"method", "ode"}, {"t_end", "1"}, {"n_steps", "1"}}});
    CHECK_THROWS_WITH(actions::ActionDispatch::execute(
                          *reloaded, output.parent_path() / "delayed_read.bngl"),
                      Catch::Matchers::ContainsSubstring(
                          "Delayed reactions are not supported by the native ODE engine"));
    std::filesystem::remove(output);
}

TEST_CASE("delayed rule syntax rejects invalid modes and dynamic delays") {
    CHECK_THROWS_WITH(parse("A() -> B() 1 NonConsuming"),
                      Catch::Matchers::ContainsSubstring("only with delay"));
    CHECK_THROWS_WITH(parse("A() <-> B() 1, 1 delay=tau"),
                      Catch::Matchers::ContainsSubstring("reversible"));
    CHECK_THROWS_WITH(parse("A() -> B() 1 delay=-1"),
                      Catch::Matchers::ContainsSubstring("nonnegative"));
    CHECK_THROWS_WITH(parse("A() -> B() 1 delay=time"),
                      Catch::Matchers::ContainsSubstring("constant"));
    CHECK_THROWS_WITH(parse("A() <-> B() 1, 1 delay=0"),
                      Catch::Matchers::ContainsSubstring("reversible"));
    CHECK_THROWS_WITH(parse("A() -> B() 1 delay=tau delay=tau"),
                      Catch::Matchers::ContainsSubstring("only one delay"));
}

TEST_CASE("delay parameters reject aliases assigned by native events") {
    CHECK_THROWS_WITH(parser::parseModel(R"(
begin model
begin parameters
  tau 2
  tauAlias tau
end parameters
begin molecule types
  A()
  B()
end molecule types
begin reaction rules
  A() -> B() 1 delay=tauAlias
end reaction rules
begin bng3_events version 1
  event "change_tau"
    trigger: time >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: tau = 3
  end event
end bng3_events
end model
)"), Catch::Matchers::ContainsSubstring("event-assigned parameter 'tau'"));
}

TEST_CASE("delay keywords remain valid parameter identifiers outside modifiers") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
  delay 0.5
  NonConsuming 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin reaction rules
  A() -> B() delay*NonConsuming
end reaction rules
end model
)");
    CHECK(model->getParameters().evaluate("delay") == 0.5);
    CHECK(model->getParameters().evaluate("NonConsuming") == 1.0);
}

TEST_CASE("static mathematical functions are permitted in delay parameters") {
    auto model = parse("A() -> B() 1 delay=sqrt(tau)");
    REQUIRE(model->getReactionRules().front().getDelayExpression());
    CHECK(model->getReactionRules().front().getDelayExpression()->evaluate(
              [&](const std::string& name) { return model->getParameters().evaluate(name); })
          == Catch::Approx(std::sqrt(2.0)));
}

TEST_CASE("NonConsuming delayed rules require nonnegative net species stoichiometry") {
    auto model = parse("A() -> 0 1 delay=tau NonConsuming");
    engine::NetworkGenerator generator(*model);
    CHECK_THROWS_WITH(generator.generateNative(),
                      Catch::Matchers::ContainsSubstring("negative net reactant stoichiometry"));
}

TEST_CASE("SBML lowers consuming delay with an empty initial history gate") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    io::SbmlWriter::Options options;
    options.startTime = 5.0;
    const auto xml = io::SbmlWriter::write(*model, &network, options);

    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("R1_init"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("R1_complete"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("<csymbol encoding=\"text\" definitionURL=\"http://www.sbml.org/sbml/symbols/delay\"> delay </csymbol>"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("<cn> 5 </cn>"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("<apply><geq/>"));

    options.level = 2;
    const auto level2 = io::SbmlWriter::write(*model, &network, options);
    CHECK_THAT(level2, Catch::Matchers::ContainsSubstring(
                           "definitionURL=\"http://www.sbml.org/sbml/symbols/delay\""));
}

TEST_CASE("native ODE refuses a delayed reaction instead of running it undelayed") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    CHECK_THROWS_WITH(engine::OdeIntegrator(*model, network),
                      Catch::Matchers::ContainsSubstring("Delayed reactions are not supported"));
}

TEST_CASE("SSA and PSA refuse delayed reactions at their construction boundary") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    CHECK_THROWS_WITH(engine::CpuBatchSsaSimulator(*model, network),
                      Catch::Matchers::ContainsSubstring("not supported by SSA"));
    CHECK_THROWS_WITH(engine::PsaSimulator(*model, network),
                      Catch::Matchers::ContainsSubstring("not supported by PSA"));
}

TEST_CASE("native simulation refuses the SBML delay function in a rate law") {
    auto model = parse("A() -> B() 1");
    engine::GeneratedNetwork network;
    network.reactions.add(ast::Rxn(
        "r_delay", {}, {}, "delay(A, tau)", 1.0, {},
        ast::Expression::function("delay", {ast::Expression::identifier("A"),
                                             ast::Expression::identifier("tau")})));
    CHECK_THROWS_WITH(engine::OdeIntegrator(*model, network),
                      Catch::Matchers::ContainsSubstring("delay(x, tau)"));
}

TEST_CASE("network exporters refuse delay metadata even when the AST lacks the rule") {
    auto delayedModel = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*delayedModel);
    const auto delayedNetwork = generator.generateNative();
    auto ordinaryModel = parse("A() -> B() 0.5");
    CHECK_THROWS_WITH(io::CppExportWriter::write(*ordinaryModel, delayedNetwork),
                      Catch::Matchers::ContainsSubstring(
                          "Delayed reactions are not supported by C++ export"));
}

TEST_CASE("native ODE validates delayed parameter values at execution time") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    model->getParameters().all().front().setValue(-1.0);
    CHECK_THROWS_WITH(engine::OdeIntegrator(*model, network),
                      Catch::Matchers::ContainsSubstring("finite and nonnegative"));
}

