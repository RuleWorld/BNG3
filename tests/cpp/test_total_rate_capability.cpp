// The TotalRate capability must be decided once, for every consumer.
//
// A ``TotalRate`` rule states the complete macroscopic flux: neither the
// reactant population nor the reaction centre's symmetry factor multiplies
// it.  The engine, the network writer and the SBML writer each decided the
// capability for themselves, from the origin rule name, and they did not
// agree.  In particular, a consumer that derived the decision by stripping a
// trailing ``_reverse`` from the rule name lost the capability for a rule
// whose *own* name ends in ``_reverse`` -- a shape the Atomizer emits for the
// two directions of a reversible step with mixed rate semantics.  The engine
// then executed that rule as a total rate while the network writer wrote it
// as an ordinary elementary reaction: one model, two meanings, and the
// exported network no longer reproduced the engine's own trajectory.
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
#include "io/NetWriter.hpp"
#include "io/SbmlWriter.hpp"
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

    // The complete flux is 1 per unit time and every event consumes two B,
    // so B(t) = 10 - 2t.  An ordinary elementary reaction would instead
    // apply the symmetry factor 1/2 and the reactant population.
    engine::OdeOptions options;
    options.method = "rk4";
    options.tStart = 0.0;
    options.tEnd = 2.0;
    options.nSteps = 2;
    const auto result = engine::OdeIntegrator(*model, network).integrate(options);
    REQUIRE(result.observables.size() == 3);
    REQUIRE(result.observables.front().size() == 1);
    CHECK(result.observables[0][0] == Catch::Approx(10.0));
    CHECK(result.observables[1][0] == Catch::Approx(8.0));
    CHECK(result.observables[2][0] == Catch::Approx(6.0));

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
