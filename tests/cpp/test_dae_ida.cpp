#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <string>

#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "parser/BNGAstVisitor.hpp"

namespace {

std::shared_ptr<bng::ast::Model> makeModel(bool withEvent = false) {
    const std::string event = withEvent ? R"(
begin bng3_events version 1
  event "reset"
    trigger: X < 0.25
    initial_value: true
    persistent: true
    use_values_from_trigger_time: true
    assignment: X = 1
  end event
end bng3_events
)" : "";
    return bng::parser::parseModel(R"(
begin model
begin parameters
  k 1
end parameters
begin molecule types
  X()
  Z()
end molecule types
begin seed species
  X() 1
  Z() 1
end seed species
begin observables
  Species X_amt X()
  Species X X()
  Species Z_amt Z()
  Species Z Z()
end observables
begin reaction rules
  decay: X() -> 0 k*Z_amt/X_amt TotalRate
end reaction rules
)" + event + R"(
end model
)");
}

std::size_t speciesIndex(const bng::engine::GeneratedNetwork& network,
                         const std::string& name) {
    for (std::size_t index = 0; index < network.species.size(); ++index) {
        if (network.species.get(index).getSpeciesGraph().toString().find(
                name + "(") != std::string::npos) {
            return index;
        }
    }
    return network.species.size();
}

bng::engine::OdeResult simulate(bool withEvent, const std::string& residual,
                                double endTime) {
    auto model = makeModel(withEvent);
    bng::engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    bng::engine::OdeIntegrator integrator(*model, network);
    integrator.setAlgebraicRules({{"Z", residual}});
    bng::engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = endTime;
    options.nSteps = 1;
    options.rtol = 1e-9;
    options.atol = 1e-12;
    return integrator.integrate(options);
}

}  // namespace

TEST_CASE("IDA enforces a nonlinear algebraic constraint during ODE dynamics",
          "[OdeIntegrator][IDA][DAE]") {
    auto model = makeModel();
    bng::engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    bng::engine::OdeIntegrator integrator(*model, network);
    integrator.setAlgebraicRules({{"Z", "Z^2-X"}});
    bng::engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 0.5;
    options.nSteps = 1;
    const auto result = integrator.integrate(options);

    const auto x = speciesIndex(network, "X");
    const auto z = speciesIndex(network, "Z");
    REQUIRE(x < network.species.size());
    REQUIRE(z < network.species.size());
    CHECK(result.concentrations.back()[x] == Catch::Approx(0.5625).margin(1e-6));
    CHECK(result.concentrations.back()[z] == Catch::Approx(0.75).margin(1e-6));
}

TEST_CASE("IDA reinitializes algebraic states after a native event",
          "[OdeIntegrator][IDA][DAE][Events]") {
    auto model = makeModel(true);
    bng::engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    bng::engine::OdeIntegrator integrator(*model, network);
    integrator.setAlgebraicRules({{"Z", "Z^2-X"}});
    bng::engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 2.0;
    options.nSteps = 1;
    const auto result = integrator.integrate(options);

    const auto x = speciesIndex(network, "X");
    const auto z = speciesIndex(network, "Z");
    REQUIRE(x < network.species.size());
    REQUIRE(z < network.species.size());
    CHECK(result.concentrations.back()[x] == Catch::Approx(0.25).margin(2e-5));
    CHECK(result.concentrations.back()[z] == Catch::Approx(0.5).margin(2e-5));
}

TEST_CASE("IDA reports an inconsistent nonlinear algebraic constraint",
          "[OdeIntegrator][IDA][DAE]") {
    CHECK_THROWS_WITH(simulate(false, "Z^2+1", 0.5),
                      Catch::Matchers::ContainsSubstring("algebraic constraint"));
}
