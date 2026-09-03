#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <sstream>

#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "io/NetWriter.hpp"
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

TEST_CASE("OdeIntegrator preserves case-insensitive rate classification", "[OdeOptions]") {
    // Source-derived from akutuva21/bionetgen commit
    // 5fab87788a4d6253ea83fd2cb35312be0c99c725: caching the lowercased raw
    // rate law and suppressing a duplicate function scan must not change the
    // existing classification contract.
    auto makeNetwork = [](const std::string& rateLaw) {
        engine::GeneratedNetwork network;
        network.species.setCheckIso(false);

        ast::SpeciesGraph reactantGraph;
        network.species.add(ast::Species(reactantGraph, 1.0));

        ast::SpeciesGraph productGraph;
        network.species.add(ast::Species(productGraph, 0.0));

        network.reactions.add(ast::Rxn(
            "R1", {0}, {1}, rateLaw, 1.0, "dummy_rule",
            ast::Expression::number(2.0)));
        return network;
    };

    SECTION("time keyword casing remains functional") {
        for (const auto& rateLaw : {std::string("time"), std::string("TIME"),
                                    std::string("Time")}) {
            ast::Model model;
            auto network = makeNetwork(rateLaw);
            engine::OdeIntegrator integrator(model, network);

            double state[] = {1.0, 0.0};
            double derivatives[] = {0.0, 0.0};
            integrator.derivs(0.0, state, derivatives);

            REQUIRE_THAT(derivatives[0], Catch::Matchers::WithinAbs(-2.0, 1e-12));
            REQUIRE_THAT(derivatives[1], Catch::Matchers::WithinAbs(2.0, 1e-12));
        }
    }

    SECTION("mixed-case function names are matched without lowercasing") {
        ast::Model model;
        model.addFunction(ast::Function(
            "rateFn", {}, ast::Expression::number(1.0)));
        auto network = makeNetwork("RATEFN");
        engine::OdeIntegrator integrator(model, network);

        double state[] = {1.0, 0.0};
        double derivatives[] = {0.0, 0.0};
        integrator.derivs(0.0, state, derivatives);

        REQUIRE_THAT(derivatives[0], Catch::Matchers::WithinAbs(-2.0, 1e-12));
        REQUIRE_THAT(derivatives[1], Catch::Matchers::WithinAbs(2.0, 1e-12));
    }
}

TEST_CASE("Observable pattern compilation preserves multi-pattern weights", "[OdeOptions]") {
    // Source-derived from akutuva21/bionetgen commit 60ac7e5f: moving
    // observable parsing outside the species loop must preserve every pattern
    // contribution when a functional ODE rate reads the group.
    auto model = parser::parseModel(R"(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 2
    B() 1
end seed species
begin observables
    Molecules total A() B()
end observables
begin reaction rules
    A() -> B() total
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);

    double state[] = {2.0, 1.0};
    double derivatives[] = {0.0, 0.0};
    integrator.derivs(0.0, state, derivatives);

    REQUIRE_THAT(derivatives[0], Catch::Matchers::WithinAbs(-6.0, 1e-12));
    REQUIRE_THAT(derivatives[1], Catch::Matchers::WithinAbs(6.0, 1e-12));
}

TEST_CASE("NetWriter preserves repeated observable group patterns", "[NetWriter]") {
    // Source-derived from akutuva21/bionetgen commit 60ac7e5f: pre-parsing
    // each observable pattern must leave the emitted group entries unchanged.
    auto model = parser::parseModel(R"(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 2
    B() 1
end seed species
begin observables
    Molecules total A() B()
    Species present A()
end observables
begin reaction rules
    A() -> B() 1
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    const auto suffix = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto outputPath = std::filesystem::temp_directory_path() /
                            ("bng3-net-writer-groups-" + std::to_string(suffix) + ".net");
    io::NetWriter::write(outputPath, *model, network);

    std::ifstream input(outputPath);
    REQUIRE(input.good());
    const std::string output((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    std::filesystem::remove(outputPath);

    REQUIRE(output.find("begin groups\n") != std::string::npos);
    REQUIRE(output.find("    1 total 1,2\n") != std::string::npos);
    REQUIRE(output.find("    2 present 1\n") != std::string::npos);
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
