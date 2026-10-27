// The TotalRate capability must be decided once, for every consumer.
//
// Authored BNGL TotalRate keeps the canonical BNG2 symmetry-factor convention
// while finite-network ODE/SSA still multiply by reactant availability.
// Atomizer SBML laws whose expressions already include reactant dependence are
// separately marked as absolute fluxes.  These tests keep both source laws
// consistent across the engine and writers.
//
// The rule name is the model's own identity, so the name is set explicitly
// here rather than left to the parser's positional naming.
#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>

#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "compile/TotalRate.hpp"
#include "io/NetWriter.hpp"
#include "io/BnglWriter.hpp"
#include "io/SbmlWriter.hpp"
#include "ast/RxnList.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

namespace {

// A rule whose own name ends in ``_reverse``.  The name is longer than the
// ``_reverse`` marker itself, so a consumer that strips the marker as a
// suffix looks up a rule that does not exist.
constexpr const char* kRuleName = "r_total_reverse";

std::unique_ptr<ast::Model> parseTotalRateModel(const char* ruleName) {
    auto model = parser::parseModel(R"(
begin parameters
    k 1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 0
    B() 10
end seed species
begin observables
    Molecules Btot B()
end observables
begin reaction rules
    r1: B() + B() -> A() k TotalRate
end reaction rules
)");
    REQUIRE(model != nullptr);
    auto& rules = model->getReactionRules();
    REQUIRE(rules.size() == 1);
    rules.front().setRuleName(ruleName);
    return model;
}

std::string readFile(const std::filesystem::path& path) {
    std::ifstream file(path);
    REQUIRE(file.good());
    return std::string((std::istreambuf_iterator<char>(file)),
                       std::istreambuf_iterator<char>());
}

std::filesystem::path temporaryPath(const char* stem) {
    return std::filesystem::temp_directory_path() /
        (std::string(stem) + "_" + std::to_string(
             std::chrono::steady_clock::now().time_since_epoch().count()));
}

} // namespace

TEST_CASE("the engine and the network writer agree about a rule named reverse",
          "[TotalRate][NetWriter]") {
    auto model = parseTotalRateModel(kRuleName);
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    REQUIRE(network.reactions.size() == 1);

    // BNG2's finite-network convention removes the repeated-reactant
    // symmetry factor for TotalRate, but still multiplies by each reactant
    // amount: dB/dt = -2*k*B^2.  A small horizon keeps this RK4 check stable.
    engine::OdeOptions options;
    options.method = "rk4";
    options.tStart = 0.0;
    options.tEnd = 0.001;
    options.nSteps = 1;
    const auto result = engine::OdeIntegrator(*model, network).integrate(options);
    REQUIRE(result.observables.size() == 2);
    REQUIRE(result.observables.front().size() == 1);
    CHECK(result.observables[0][0] == Catch::Approx(10.0));
    CHECK(result.observables[1][0] == Catch::Approx(
        10.0 / (1.0 + 20.0 * options.tEnd)).epsilon(1e-7));

    // The network writer applies the symmetry factor of identical reactants
    // to an ordinary reaction and not to a total rate, exactly as the engine
    // does.
    const auto netPath = temporaryPath("bng3_total_rate");
    io::NetWriter::write(netPath, *model, network);
    const std::string netText = readFile(netPath);
    std::filesystem::remove(netPath);
    CHECK_THAT(netText, Catch::Matchers::ContainsSubstring("begin reactions"));
    CHECK(netText.find("0.5*") == std::string::npos);
}

TEST_CASE("Atomizer absolute flux provenance is per rule and round-trips",
          "[TotalRate][AbsoluteFlux]") {
    auto model = parser::parseModel(R"(
begin model
setOption("BNG3AbsoluteFluxRules","r1")
begin parameters
    k 1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 0
    B() 10
end seed species
begin reaction rules
    r1: B() + B() -> A() k TotalRate
    r2: B() -> A() k TotalRate
end reaction rules
end model
)");
    REQUIRE(model != nullptr);
    REQUIRE(model->getReactionRules().size() == 2);
    CHECK(model->getReactionRules()[0].isAbsoluteFlux());
    CHECK_FALSE(model->getReactionRules()[1].isAbsoluteFlux());
    CHECK(compile::isAbsoluteFluxReaction(
        *model, model->getReactionRules()[0].getRuleName()));
    CHECK_FALSE(compile::isAbsoluteFluxReaction(
        *model, model->getReactionRules()[1].getRuleName()));

    const std::string source = io::BnglWriter::write(*model);
    CHECK(source.find("setOption(\"BNG3AbsoluteFluxRules\",\"r1\")") !=
          std::string::npos);
    CHECK(source.find("setOption(\"BNG3AbsoluteFluxRules\",\"r1\")") <
          source.find("begin model"));
    auto roundTrip = parser::parseModel(source);
    REQUIRE(roundTrip != nullptr);
    REQUIRE(roundTrip->getReactionRules().size() == 2);
    CHECK(roundTrip->getReactionRules()[0].isAbsoluteFlux());
    CHECK_FALSE(roundTrip->getReactionRules()[1].isAbsoluteFlux());

    roundTrip->setOption("BNG3AbsoluteFluxRules", "r2");
    CHECK_FALSE(roundTrip->getReactionRules()[0].isAbsoluteFlux());
    CHECK(roundTrip->getReactionRules()[1].isAbsoluteFlux());
}

TEST_CASE("reaction deduplication keeps distinct source-law provenance",
          "[TotalRate][AbsoluteFlux]") {
    ast::RxnList reactions;
    CHECK(reactions.add(ast::Rxn("ordinary", {0}, {1}, "k")));
    CHECK(reactions.add(ast::Rxn(
        "absolute", {0}, {1}, "k", 1.0, {}, std::nullopt, std::nullopt,
        false, true)));
    REQUIRE(reactions.size() == 2);
    CHECK_FALSE(reactions.all()[0].isAbsoluteFlux());
    CHECK(reactions.all()[1].isAbsoluteFlux());
}

TEST_CASE("the engine and the SBML writer agree about a rule named reverse",
          "[TotalRate][SbmlWriter]") {
    auto model = parseTotalRateModel(kRuleName);
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();

    const std::string xml = io::SbmlWriter::write(*model, &network);
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("bng:totalRate"));
    // The complete flux is stated as the rate; the reactant population is
    // not part of it.
    CHECK(xml.find("<ci> k </ci>") != std::string::npos);
}

TEST_CASE("an exact underscore-prefixed rule name decides its own capability",
          "[TotalRate]") {
    auto model = parser::parseModel(R"(
begin parameters
    k 1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 0
    B() 10
end seed species
begin reaction rules
    foo: B() -> A() k TotalRate
    _foo: A() -> B() k
end reaction rules
)");
    REQUIRE(model != nullptr);
    REQUIRE(model->getReactionRules().size() == 2);
    model->getReactionRules()[0].setRuleName("foo");
    model->getReactionRules()[1].setRuleName("_foo");

    CHECK(compile::isTotalRateReaction(*model, "foo"));
    CHECK_FALSE(compile::isTotalRateReaction(*model, "_foo"));
}
