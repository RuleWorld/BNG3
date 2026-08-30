#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

namespace {

std::unique_ptr<ast::Model> parseDecayModel() {
    return parser::parseModel(R"(
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
)");
}

} // namespace

TEST_CASE("OdeIntegrator honors explicit nonuniform sample times", "[OdeOptions]") {
    auto model = parseDecayModel();
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();

    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 10.0;
    options.nSteps = 1;
    options.sampleTimes = {0.0, 0.25, 1.5, 10.0};

    const auto result = engine::OdeIntegrator(*model, network).integrate(options);

    REQUIRE(result.timePoints == options.sampleTimes);
    REQUIRE(result.concentrations.size() == options.sampleTimes.size());
    REQUIRE(result.observables.size() == options.sampleTimes.size());
}

TEST_CASE("OdeIntegrator rejects malformed stop conditions", "[OdeOptions]") {
    auto model = parseDecayModel();
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();

    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 1.0;
    options.nSteps = 2;
    options.stopIf = "Xtot <";

    REQUIRE_THROWS_WITH(
        engine::OdeIntegrator(*model, network).integrate(options),
        Catch::Matchers::ContainsSubstring("stop_if"));
}

TEST_CASE("CVODE honors steady-state stopping", "[OdeOptions]") {
    auto model = parseDecayModel();
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();

    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 10.0;
    options.nSteps = 10;
    options.steadyState = true;
    options.steadyStateTol = 100.0;

    const auto result = engine::OdeIntegrator(*model, network).integrate(options);

    REQUIRE(result.timePoints.size() < options.nSteps + 1);
    REQUIRE(result.timePoints.back() < options.tEnd);
}

TEST_CASE("SSA honors explicit sample times", "[OdeOptions]") {
    auto model = parseDecayModel();
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();

    engine::OdeOptions options;
    options.method = "ssa";
    options.tStart = 0.0;
    options.tEnd = 10.0;
    options.nSteps = 1;
    options.seed = 42;
    options.sampleTimes = {0.0, 0.25, 1.5, 10.0};

    const auto result = engine::OdeIntegrator(*model, network).integrate(options);

    REQUIRE(result.timePoints == options.sampleTimes);
    REQUIRE(result.concentrations.size() == options.sampleTimes.size());
    REQUIRE(result.observables.size() == options.sampleTimes.size());
}
