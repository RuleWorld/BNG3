#include <catch2/catch_test_macros.hpp>

#include <cstddef>
#include <cstdint>

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
