#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <cstddef>
#include <cstdint>
#include <cmath>

#include "engine/NetworkGenerator.hpp"
#include "engine/PsaSimulator.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("PSA reaction selection samples competing channels by propensity",
          "[PsaSimulator][issue-265]") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
    k1 1
    k2 1
end parameters
begin molecule types
    A()
    B()
    C()
end molecule types
begin seed species
    A() 1
    B() 0
    C() 0
end seed species
begin reaction rules
    A() -> B() k1
    A() -> C() k2
end reaction rules
)BNGL");
    REQUIRE(model != nullptr);

    bng::engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    bng::engine::PsaSimulator simulator(*model, network);

    bng::engine::OdeOptions options;
    options.method = "psa";
    options.tEnd = 2.0;
    options.nSteps = 1;

    std::size_t toB = 0;
    std::size_t toC = 0;
    for (std::uint64_t seed = 1; seed <= 600; ++seed) {
        options.seed = seed;
        const auto result = simulator.simulate(options, 0.0);
        REQUIRE_FALSE(result.concentrations.empty());
        const auto& finalState = result.concentrations.back();
        REQUIRE(finalState.size() == 3);
        toB += finalState[1] == 1.0;
        toC += finalState[2] == 1.0;
    }

    const auto fired = toB + toC;
    REQUIRE(fired > 450);
    CHECK(toB > 0.42 * static_cast<double>(fired));
    CHECK(toB < 0.58 * static_cast<double>(fired));
}

TEST_CASE("PsaSimulator rejects BNG3 events until event execution is implemented",
          "[PsaSimulator][Events]") {
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
        bng::engine::PsaSimulator(*model, network),
        Catch::Matchers::ContainsSubstring("BNG3 native event execution is not implemented"));
}

TEST_CASE("PSA applies the shared TotalRate modifier semantics",
          "[PsaSimulator][TotalRate]") {
    const auto model = bng::parser::parseModel(R"BNGL(
begin parameters
    k 1000
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 0
    B() 100
end seed species
begin reaction rules
    B() -> A() k TotalRate
end reaction rules
)BNGL");
    REQUIRE(model != nullptr);

    bng::engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    bng::engine::PsaSimulator simulator(*model, network);
    bng::engine::OdeOptions options;
    options.method = "psa";
    options.tEnd = 0.001;
    options.nSteps = 1;

    std::size_t consumed = 0;
    for (std::uint64_t seed = 1; seed <= 64; ++seed) {
        options.seed = seed;
        const auto result = simulator.simulate(options, 0.0);
        REQUIRE_FALSE(result.concentrations.empty());
        consumed += static_cast<std::size_t>(100.0 - result.concentrations.back()[1]);
    }

    // BNG2 finite-network TotalRate multiplies by each available B count and
    // omits only the symmetry factor.  Here the expected consumed population
    // is 100 * (1 - exp(-1000 * 0.001)) per trajectory.
    CHECK(consumed == Catch::Approx(
        100.0 * (1.0 - std::exp(-1.0)) * 64.0).margin(500.0));
}

TEST_CASE("PSA preserves repeated-reactant TotalRate factors by source law",
          "[PsaSimulator][TotalRate][AbsoluteFlux]") {
    const auto eventFraction = [](const std::string& source) {
        const auto model = bng::parser::parseModel(source);
        REQUIRE(model != nullptr);
        bng::engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        bng::engine::PsaSimulator simulator(*model, network);
        bng::engine::OdeOptions options;
        options.method = "psa";
        options.tEnd = 0.1;
        options.nSteps = 1;

        constexpr std::size_t trajectories = 4096;
        std::size_t fired = 0;
        for (std::uint64_t seed = 1; seed <= trajectories; ++seed) {
            options.seed = seed;
            const auto result = simulator.simulate(options, 0.0);
            REQUIRE(result.observables.size() == 2);
            REQUIRE(result.observables.back().size() == 1);
            fired += static_cast<std::size_t>(result.observables.back()[0]);
        }
        return static_cast<double>(fired) / trajectories;
    };

    const std::string authored = R"BNGL(
begin parameters
    k 1
end parameters
begin molecule types
    A()
    D()
end molecule types
begin seed species
    A() 2
    D() 0
end seed species
begin observables
    Molecules Dtot D()
end observables
begin reaction rules
    A() + A() -> D() k TotalRate
end reaction rules
)BNGL";
    const std::string absolute = R"BNGL(
setOption("BNG3AbsoluteFluxRules","r")
begin parameters
    k 1
end parameters
begin molecule types
    A()
    D()
end molecule types
begin seed species
    A() 2
    D() 0
end seed species
begin observables
    Molecules Dtot D()
end observables
begin reaction rules
    r: A() + A() -> D() k TotalRate
end reaction rules
)BNGL";

    CHECK(eventFraction(authored) == Catch::Approx(1.0 - std::exp(-0.2)).margin(0.025));
    CHECK(eventFraction(absolute) == Catch::Approx(1.0 - std::exp(-0.1)).margin(0.018));
}

TEST_CASE("PSA rejects dynamic absolute-flux rate laws",
          "[PsaSimulator][AbsoluteFlux]") {
    for (const auto* dynamicRate : {"k*time", "k*Atot"}) {
    const auto model = bng::parser::parseModel(std::string(R"BNGL(
setOption("BNG3AbsoluteFluxRules","r")
begin parameters
    k 1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
    B() 0
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    r: A() -> B() )BNGL") + dynamicRate + R"BNGL( TotalRate
end reaction rules
)BNGL");
    REQUIRE(model != nullptr);
    bng::engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();

    REQUIRE_THROWS_WITH(
        bng::engine::PsaSimulator(*model, network),
        Catch::Matchers::ContainsSubstring(
            "PSA does not support state/time-dependent absolute-flux rate laws"));
    }
}

TEST_CASE("PSA does not resolve an exact reverse-shaped rule as a marker",
          "[PsaSimulator][TotalRate]") {
    auto model = bng::parser::parseModel(R"BNGL(
begin parameters
    k 1000
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 0
    B() 100
end seed species
begin reaction rules
    foo: A() -> B() k TotalRate
    _reverse__foo: B() -> A() k
end reaction rules
)BNGL");
    REQUIRE(model != nullptr);
    REQUIRE(model->getReactionRules().size() == 2);
    model->getReactionRules()[0].setRuleName("foo");
    model->getReactionRules()[1].setRuleName("_reverse__foo");

    bng::engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    REQUIRE(network.reactions.size() == 2);
    CHECK(network.reactions.all()[1].getOriginRuleName() == "_reverse__foo");

    bng::engine::PsaSimulator simulator(*model, network);
    bng::engine::OdeOptions options;
    options.method = "psa";
    options.tEnd = 0.001;
    options.nSteps = 1;

    std::size_t consumed = 0;
    for (std::uint64_t seed = 1; seed <= 64; ++seed) {
        options.seed = seed;
        const auto result = simulator.simulate(options, 0.0);
        REQUIRE_FALSE(result.concentrations.empty());
        consumed += static_cast<std::size_t>(
            100.0 - result.concentrations.back()[1]);
    }

    // The exact rule named ``_reverse__foo`` is ordinary, so PSA must use
    // mass action (about 100 firings per trajectory), not inherit foo's
    // TotalRate capability from the marker-shaped prefix.
    CHECK(consumed > 4 * 64);
}
