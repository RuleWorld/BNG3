#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>
#include <cmath>
#include <cstdint>
#include "../../cpp/engine/PlaSimulator.hpp"
#include "../../cpp/ast/Model.hpp"
#include "../../cpp/engine/NetworkGenerator.hpp"
#include "../../cpp/parser/BNGAstVisitor.hpp"
// Include implementation to exercise evaluateRateString in anonymous namespace.
#include "../../cpp/engine/PlaSimulator.cpp"

using namespace bng::engine;
using namespace bng::ast;

TEST_CASE("PlaConfig parsing", "[PlaSimulator]") {
    SECTION("Default configuration") {
        PlaConfig config;
        REQUIRE(config.method == PlaConfig::Method::fEuler);
        REQUIRE(config.checkType == PlaConfig::CheckType::PreNeg);
        REQUIRE(config.basis == PlaConfig::Basis::SpeciesBased);
        REQUIRE_THAT(config.eps, Catch::Matchers::WithinAbs(0.03, 1e-6));
        REQUIRE_THAT(config.p, Catch::Matchers::WithinAbs(0.5, 1e-6));
        REQUIRE_THAT(config.q, Catch::Matchers::WithinAbs(1.5, 1e-6));
        REQUIRE_THAT(config.w, Catch::Matchers::WithinAbs(0.75, 1e-6));
        REQUIRE_THAT(config.fixedTau, Catch::Matchers::WithinAbs(0.0, 1e-6));
    }

    SECTION("Parsing simple format") {
        PlaConfig config = PlaConfig::parse("fEuler|pre-neg:sb|eps=0.05");
        REQUIRE(config.method == PlaConfig::Method::fEuler);
        REQUIRE(config.checkType == PlaConfig::CheckType::PreNeg);
        REQUIRE(config.basis == PlaConfig::Basis::SpeciesBased);
        REQUIRE_THAT(config.eps, Catch::Matchers::WithinAbs(0.05, 1e-6));
    }

    SECTION("Parsing all methods") {
        REQUIRE(PlaConfig::parse("fEuler||").method == PlaConfig::Method::fEuler);
        REQUIRE(PlaConfig::parse("midpt||").method == PlaConfig::Method::Midpoint);
        REQUIRE(PlaConfig::parse("rk4||").method == PlaConfig::Method::RK4);
    }

    SECTION("Parsing check types and basis") {
        auto c1 = PlaConfig::parse("|pre-neg:sb|");
        REQUIRE(c1.checkType == PlaConfig::CheckType::PreNeg);
        REQUIRE(c1.basis == PlaConfig::Basis::SpeciesBased);

        auto c2 = PlaConfig::parse("|post-eps:rb|");
        REQUIRE(c2.checkType == PlaConfig::CheckType::PostEps);
        REQUIRE(c2.basis == PlaConfig::Basis::ReactionBased);
    }

    SECTION("Parsing multiple parameters") {
        PlaConfig config = PlaConfig::parse("||eps=0.1,tau=1.5,p=0.8,q=2.0,w=0.5");
        REQUIRE_THAT(config.eps, Catch::Matchers::WithinAbs(0.1, 1e-6));
        REQUIRE_THAT(config.fixedTau, Catch::Matchers::WithinAbs(1.5, 1e-6));
        REQUIRE_THAT(config.p, Catch::Matchers::WithinAbs(0.8, 1e-6));
        REQUIRE_THAT(config.q, Catch::Matchers::WithinAbs(2.0, 1e-6));
        REQUIRE_THAT(config.w, Catch::Matchers::WithinAbs(0.5, 1e-6));
    }

    SECTION("Handling malformed inputs gracefully") {
        PlaConfig c1 = PlaConfig::parse("invalidMethod|pre-neg:sb|eps=0.05");
        REQUIRE(c1.method == PlaConfig::Method::fEuler);

        PlaConfig c2 = PlaConfig::parse("||eps=invalid,tau=malformed,p=2");
        REQUIRE_THAT(c2.eps, Catch::Matchers::WithinAbs(0.03, 1e-6));
        REQUIRE_THAT(c2.fixedTau, Catch::Matchers::WithinAbs(0.0, 1e-6));
        REQUIRE_THAT(c2.p, Catch::Matchers::WithinAbs(2.0, 1e-6));
    }
}

TEST_CASE("PlaSimulator initialization and simulation", "[PlaSimulator]") {
    Model model;
    GeneratedNetwork network;

    // Test that empty simulation completes successfully
    PlaSimulator simulator(model, network);

    OdeOptions opts;
    opts.tEnd = 1.0;
    opts.nSteps = 10;

    PlaConfig config;

    OdeResult result = simulator.simulate(opts, config);

    REQUIRE(result.timePoints.size() > 0);
    REQUIRE_THAT(result.timePoints.back(), Catch::Matchers::WithinAbs(1.0, 1e-6));
    REQUIRE(result.concentrations.size() == result.timePoints.size());
    REQUIRE(result.observables.size() == result.timePoints.size());
}

TEST_CASE("PlaSimulator rejects BNG3 events until event execution is implemented",
          "[PlaSimulator][Events]") {
    const auto model = bng::parser::parseModel(R"(
begin bng3_events version 1
  event "later"
    trigger: time >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: A = 0
  end event
end bng3_events
)");
    REQUIRE(model != nullptr);
    bng::engine::GeneratedNetwork network;

    REQUIRE_THROWS_WITH(
        bng::engine::PlaSimulator(*model, network),
        Catch::Matchers::ContainsSubstring("BNG3 native event execution is not implemented"));
}

TEST_CASE("PLA fails closed on unsupported TotalRate source laws",
          "[PlaSimulator][TotalRate]") {
    const std::vector<std::string> sources = {
        R"(begin parameters
    k 1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 2
    B() 0
end seed species
begin reaction rules
    r: A() + A() -> B() k TotalRate
end reaction rules
)",
        R"(setOption("BNG3AbsoluteFluxRules","r")
begin parameters
    k 1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 2
    B() 0
end seed species
begin reaction rules
    r: A() + A() -> B() k TotalRate
end reaction rules
)",
    };

    for (const auto& source : sources) {
        const auto model = bng::parser::parseModel(source);
        REQUIRE(model != nullptr);
        NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE_THROWS_WITH(
            PlaSimulator(*model, network),
            Catch::Matchers::ContainsSubstring(
                "PLA does not support TotalRate or absolute-flux"));
    }
}

TEST_CASE("evaluateRateString error path", "[PlaSimulator]") {
    auto resolve = [](const std::string& s) {
        if (s == "valid_var") return 42.0;
        return 0.0;
    };

    REQUIRE_THAT(evaluateRateString("1.23", resolve), Catch::Matchers::WithinRel(1.23));
    REQUIRE_THAT(evaluateRateString("invalid_float", resolve), Catch::Matchers::WithinRel(0.0));
    REQUIRE_THAT(evaluateRateString("valid_var", resolve), Catch::Matchers::WithinRel(42.0));
    REQUIRE_THAT(evaluateRateString("1.23abc", resolve), Catch::Matchers::WithinRel(0.0));
}

TEST_CASE("PLA counts three identical reactants as distinct triples",
          "[PlaSimulator][RepeatedReactants]") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
    k 1
end parameters
begin molecule types
    A()
    D()
end molecule types
begin seed species
    A() 10
    D() 0
end seed species
begin observables
    Molecules Dtot D()
end observables
begin reaction rules
    A() + A() + A() -> D() k
end reaction rules
)BNGL");
    REQUIRE(model != nullptr);
    NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    PlaSimulator simulator(*model, network);

    OdeOptions options;
    options.method = "pla";
    options.tEnd = 0.01;
    options.nSteps = 1;
    const PlaConfig config = PlaConfig::parse(
        "||tau=0.0001,apx1=1000000,gg1=1000001");

    constexpr std::size_t trajectories = 2000;
    std::vector<double> eventCounts;
    eventCounts.reserve(trajectories);
    for (std::uint64_t seed = 1; seed <= trajectories; ++seed) {
        options.seed = static_cast<unsigned int>(seed);
        const auto result = simulator.simulate(options, config);
        REQUIRE(result.observables.size() == 2);
        REQUIRE(result.observables.back().size() == 1);
        eventCounts.push_back(result.observables.back()[0]);
    }

    double mean = 0.0;
    for (const double count : eventCounts) mean += count;
    mean /= static_cast<double>(eventCounts.size());
    double sumSquares = 0.0;
    for (const double count : eventCounts) {
        const double difference = count - mean;
        sumSquares += difference * difference;
    }
    const double standardError = std::sqrt(
        sumSquares / static_cast<double>(eventCounts.size() - 1) /
        static_cast<double>(eventCounts.size()));

    // Independent pure-death master equation for rates k * choose(n, 3),
    // with states 10, 7, 4, 1 and t=0.01. RK4 at 20,000 steps gives
    // E[D]=0.829896932543434. Multiplying by n^3/6 instead gives 1.060199,
    // outside this four-standard-error band.
    constexpr double discreteExpected = 0.829896932543434;
    constexpr double continuousExpected = 1.060199043093818;
    CHECK(std::abs(mean - discreteExpected) <= 4.0 * standardError);
    CHECK(std::abs(mean - continuousExpected) > 4.0 * standardError);
}
