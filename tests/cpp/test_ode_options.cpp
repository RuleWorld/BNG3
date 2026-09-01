#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>
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

TEST_CASE("OdeIntegrator evaluates user-defined function rates", "[OdeOptions]") {
    // Source-derived from akutuva21/bionetgen PR #508 head e67850cf and
    // PR #509 head 5cf5cd47: function-name matching is an allocation-sensitive
    // compile path, but must retain the user-defined rate contract.
    auto model = parser::parseModel(R"(
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin functions
    rate() = 2
end functions
begin reaction rules
    X() -> 0 rate
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);

    double state[] = {1.0};
    double derivatives[] = {0.0};
    integrator.derivs(0.0, state, derivatives);

    REQUIRE_THAT(derivatives[0], Catch::Matchers::WithinAbs(-2.0, 1e-12));
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

TEST_CASE("OdeIntegrator preserves multi-species derivative updates", "[OdeOptions]") {
    // Source-derived from akutuva21/bionetgen commit dd665873: compacting
    // large constant-reaction updates must preserve the complete stoichiometric
    // derivative, including multiple reactants and products.
    ast::Model model;
    engine::GeneratedNetwork network;
    network.species.setCheckIso(false);

    for (double amount : {3.0, 4.0, 0.0, 0.0}) {
        ast::SpeciesGraph graph;
        network.species.add(ast::Species(graph, amount));
    }

    // Cross the source port's compact-reaction threshold while retaining a
    // two-reactant, two-product update shape representative of generated
    // networks.
    for (std::size_t i = 0; i < 512; ++i) {
        network.reactions.add(ast::Rxn(
            "R" + std::to_string(i), {0, 1}, {2, 3}, "2.0", 1.0,
            "rule" + std::to_string(i)));
    }

    engine::OdeIntegrator integrator(model, network);
    double state[] = {3.0, 4.0, 0.0, 0.0};
    double derivatives[] = {0.0, 0.0, 0.0, 0.0};
    integrator.derivs(0.0, state, derivatives);

    constexpr double expectedRate = 2.0 * 3.0 * 4.0 * 512.0;
    REQUIRE_THAT(derivatives[0], Catch::Matchers::WithinAbs(-expectedRate, 1e-12));
    REQUIRE_THAT(derivatives[1], Catch::Matchers::WithinAbs(-expectedRate, 1e-12));
    REQUIRE_THAT(derivatives[2], Catch::Matchers::WithinAbs(expectedRate, 1e-12));
    REQUIRE_THAT(derivatives[3], Catch::Matchers::WithinAbs(expectedRate, 1e-12));
}
