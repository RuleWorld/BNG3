#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <string>

#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "io/BnglWriter.hpp"
#include "io/NetWriter.hpp"
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
    auto model = parse("G() -> G() + M() 0.5 delay=tau NonConsuming");
    REQUIRE(model->getReactionRules().size() == 1);
    const auto& rule = model->getReactionRules().front();
    REQUIRE(rule.getDelayExpression());
    CHECK(rule.getDelayExpression()->toBnglString() == "tau");
    CHECK(rule.isNonConsuming());

    const auto bngl = io::BnglWriter::write(*model);
    CHECK_THAT(bngl, Catch::Matchers::ContainsSubstring("delay=tau NonConsuming"));
    auto roundTrip = parser::parseModel(bngl);
    REQUIRE(roundTrip->getReactionRules().front().getDelayExpression());
    CHECK(roundTrip->getReactionRules().front().isNonConsuming());

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    REQUIRE(network.reactions.size() == 1);
    CHECK(network.reactions.all().front().getDelayExpression());
    CHECK(network.reactions.all().front().isNonConsuming());

    auto output = std::filesystem::temp_directory_path() / "bng3-delay-net-writer.net";
    io::NetWriter::write(output, *model, network);
    CHECK_THAT(readFile(output), Catch::Matchers::ContainsSubstring("delay=tau NonConsuming"));
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
}

TEST_CASE("native ODE refuses a delayed reaction instead of running it undelayed") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    CHECK_THROWS_WITH(engine::OdeIntegrator(*model, network),
                      Catch::Matchers::ContainsSubstring("Delayed reactions are not supported"));
}

TEST_CASE("native ODE validates delayed parameter values at execution time") {
    auto model = parse("A() -> B() 0.5 delay=tau");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    model->getParameters().all().front().setValue(-1.0);
    CHECK_THROWS_WITH(engine::OdeIntegrator(*model, network),
                      Catch::Matchers::ContainsSubstring("Invalid delayed reaction time"));
}

