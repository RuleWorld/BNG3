#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <sstream>

#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "io/MatlabWriter.hpp"
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

TEST_CASE("CVODE randomizes equal-priority native event execution with its seed",
          "[OdeOptions][Events]") {
    auto model = parser::parseModel(R"(
begin molecule types
    A()
    B()
    X()
end molecule types
begin seed species
    A() 1
    X() 0
end seed species
begin observables
    Molecules b B()
    Molecules x X()
end observables
begin reaction rules
    fire: A() -> B() 10
end reaction rules
begin bng3_events version 1
    event "first"
        trigger: b > 0.25
        initial_value: false
        persistent: true
        use_values_from_trigger_time: true
        priority: 5
        assignment: x = 1
    end event
    event "second"
        trigger: b >= 0.25
        initial_value: false
        persistent: true
        use_values_from_trigger_time: true
        priority: 5
        assignment: x = 2
    end event
end bng3_events
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 1.0;
    options.nSteps = 10;
    std::vector<double> finalValues;
    for (std::uint64_t seed = 0; seed < 24; ++seed) {
        options.seed = seed;
        const auto result = integrator.integrate(options);
        finalValues.push_back(result.observables.back()[1]);
    }
    CHECK(std::all_of(finalValues.begin(), finalValues.end(), [](double value) {
        return value == 1.0 || value == 2.0;
    }));
    CHECK(std::find(finalValues.begin(), finalValues.end(), 1.0) != finalValues.end());
    CHECK(std::find(finalValues.begin(), finalValues.end(), 2.0) != finalValues.end());
}


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

TEST_CASE("constant rate branches are folded for network and writer outputs",
          "[Expression][PartialEvaluation][NetWriter][MatlabWriter]") {
    auto model = parser::parseModel(R"(
begin parameters
    k1 2
    k2 3
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin functions
    choose() = if(2*3==6,k1+0,k2)
    wrapper() = choose()
end functions
begin reaction rules
    X() -> 0 wrapper()
end reaction rules
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();

    REQUIRE(network.reactions.size() == 1);
    const auto& rateExpression = network.reactions.all().front().getRateExpression();
    REQUIRE(rateExpression.has_value());
    CHECK(rateExpression->toString() == "k1");
    CHECK(io::NetWriter::buildDerivedRateParams(*model, network).empty());

    const auto netPath = std::filesystem::temp_directory_path() /
        ("bng3_partial_eval_" + std::to_string(
            std::chrono::steady_clock::now().time_since_epoch().count()) + ".net");
    io::NetWriter::write(netPath, *model, network);
    std::ifstream netFile(netPath);
    REQUIRE(netFile.good());
    const std::string netText((std::istreambuf_iterator<char>(netFile)),
                              std::istreambuf_iterator<char>());
    netFile.close();
    std::filesystem::remove(netPath);
    CHECK(netText.find("if(") == std::string::npos);
    CHECK(netText.find("choose() k1") != std::string::npos);
    CHECK(netText.find("wrapper() k1") != std::string::npos);

    // Keep the source rate AST unsimplified here so this assertion exercises
    // the MATLAB writer's shared simplification path, independently of the
    // simplification already performed during network compilation.
    engine::GeneratedNetwork matlabNetwork;
    const auto& sourceSpecies = network.species.get(0);
    matlabNetwork.species.add(ast::Species(
        sourceSpecies.getSpeciesGraph(), sourceSpecies.getAmount(),
        sourceSpecies.isConstant(), sourceSpecies.getCompartment()));
    REQUIRE(matlabNetwork.reactions.add(ast::Rxn(
        "matlab_fold", {0}, {}, "if(2*3==6,k1+0,k2)", 1.0,
        "matlab_fold", parser::parseExpression("if(2*3==6,k1+0,k2)"))));
    const auto matlab = io::MatlabWriter::write(*model, matlabNetwork);
    CHECK(matlab.find("expressions(1)*species(1)") != std::string::npos);
    CHECK(matlab.find("if(") == std::string::npos);
}

TEST_CASE("OdeIntegrator default tolerances preserve an analytic decay trajectory",
          "[OdeOptions][issue-208]") {
    auto model = parseDecayModel();
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();

    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 10.0;
    options.nSteps = 10;
    const auto result = engine::OdeIntegrator(*model, network).integrate(options);

    REQUIRE_FALSE(result.concentrations.empty());
    const double expected = 100.0 * std::exp(-0.1 * options.tEnd);
    CHECK_THAT(result.concentrations.back().front(),
               Catch::Matchers::WithinAbs(expected, 2e-6));
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

TEST_CASE("SSA evaluates native event triggers after reaction firings",
          "[OdeOptions][Events][SSA]") {
    auto model = parser::parseModel(R"(
begin molecule types
    A()
    B()
    C()
    D()
end molecule types
begin seed species
    A() 1
    C() 1
end seed species
begin observables
    Species a A()
    Species b B()
    Species c C()
    Species d D()
end observables
begin reaction rules
    fire: A() -> B() 1000000
    consume_c: C() -> D() 1
end reaction rules
begin bng3_events version 1
    event "reset"
        trigger: b > 0
        initial_value: false
        persistent: true
        use_values_from_trigger_time: true
        assignment: c = 0
    end event
end bng3_events
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "ssa";
    options.seed = 17;
    options.tEnd = 0.1;
    options.nSteps = 1;

    const auto result = integrator.integrate(options);

    REQUIRE(result.eventCount == 1);
    CHECK_THAT(result.observables.back()[1], Catch::Matchers::WithinAbs(1.0, 1e-12));
    CHECK_THAT(result.observables.back()[2], Catch::Matchers::WithinAbs(0.0, 1e-12));
    CHECK_THAT(result.observables.back()[3], Catch::Matchers::WithinAbs(0.0, 1e-12));
}

TEST_CASE("SSA checks native event triggers after delayed reaction completions",
          "[OdeOptions][Events][SSA]") {
    auto model = parser::parseModel(R"(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Species a A()
    Species b B()
end observables
begin reaction rules
    fire: A() -> B() 100 delay=0.01
end reaction rules
begin bng3_events version 1
    event "reset"
        trigger: b > 0
        initial_value: false
        persistent: true
        use_values_from_trigger_time: true
        delay: 0.05
        assignment: b = 0
    end event
end bng3_events
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "ssa";
    options.seed = 17;
    options.tEnd = 0.2;
    options.nSteps = 2;

    const auto result = integrator.integrate(options);

    REQUIRE(result.eventCount == 1);
    CHECK_THAT(result.observables.back()[1], Catch::Matchers::WithinAbs(0.0, 1e-12));
}

TEST_CASE("SSA keeps absolute-flux reaction channels stochastic with native events",
          "[OdeOptions][Events][SSA]") {
    auto model = parser::parseModel(R"(
begin model
setOption("BNG3AbsoluteFluxRules", "birth")
begin molecule types
    X()
    Marker()
end molecule types
begin seed species
    X() 0
    Marker() 0
end seed species
begin observables
    Molecules x X()
    Molecules marker Marker()
end observables
begin reaction rules
    birth: 0 -> X() 2 TotalRate
end reaction rules
begin bng3_events version 1
    event "mark_first_birth"
        trigger: x > 0.5
        initial_value: false
        persistent: true
        use_values_from_trigger_time: true
        assignment: marker = 1
    end event
end bng3_events
end model
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "ssa";
    options.seed = 17;
    options.tEnd = 1.0;
    options.nSteps = 4;

    const auto result = integrator.integrate(options);

    REQUIRE(result.eventCount > 0);
    for (const auto& row : result.observables) {
        CHECK(row[0] == std::round(row[0]));
        CHECK(row[1] == (row[0] > 0 ? 1.0 : 0.0));
    }
}

TEST_CASE("SSA keeps event-only absolute-flux states continuous",
          "[OdeOptions][Events][SSA]") {
    auto model = parser::parseModel(R"(
begin model
setOption("BNG3AbsoluteFluxRules", "__rate_rule_x")
begin molecule types
    X()
end molecule types
begin seed species
    X() 0
end seed species
begin observables
    Molecules x_amt X()
end observables
begin functions
    __rate_rule__x() = 1
end functions
begin reaction rules
    __rate_rule_x: 0 -> X() __rate_rule__x() TotalRate
end reaction rules
begin bng3_events version 1
    event "reset"
        trigger: x_amt >= 1
        initial_value: false
        persistent: true
        use_values_from_trigger_time: true
        assignment: x_amt = 0
    end event
end bng3_events
end model
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "ssa";
    options.seed = 29;
    options.tEnd = 2.0;
    options.nSteps = 2;

    const auto result = integrator.integrate(options);

    CHECK_THAT(result.observables.back()[0], Catch::Matchers::WithinAbs(0.0, 1e-8));
}

TEST_CASE("native event distribution draws use the simulation seed",
          "[OdeOptions][Events][Distribution]") {
    auto model = parser::parseModel(R"(
begin molecule types
    A()
    B()
    X()
end molecule types
begin seed species
    A() 1
    X() 0
end seed species
begin observables
    Molecules x X()
    Molecules b B()
end observables
begin reaction rules
    fire: A() -> B() 1000000
end reaction rules
begin bng3_events version 1
    event "draw"
        trigger: b > 0
        initial_value: false
        persistent: true
        use_values_from_trigger_time: true
        assignment: x = distrib_normal(-1, 0.01)
    end event
end bng3_events
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "ssa";
    options.seed = 173;
    options.tEnd = 1.0;
    options.nSteps = 1;

    const auto first = integrator.integrate(options);
    const auto repeated = integrator.integrate(options);

    REQUIRE(first.eventCount == 1);
    REQUIRE(repeated.eventCount == 1);
    CHECK(first.observables.back()[0] == repeated.observables.back()[0]);
    CHECK(first.observables.back()[0] < 0.0);
}


TEST_CASE("native event distribution parameters evaluate square roots",
          "[OdeOptions][Events][Distribution]") {
    auto model = parser::parseModel(R"(
begin molecule types
    A()
    B()
    X()
end molecule types
begin seed species
    A() 1
    X() 0
end seed species
begin observables
    Molecules x X()
    Molecules b B()
end observables
begin reaction rules
    fire: A() -> B() 1000000
end reaction rules
begin bng3_events version 1
    event "draw"
        trigger: b > 0
        initial_value: false
        persistent: true
        use_values_from_trigger_time: true
        assignment: x = distrib_normal(-1, sqrt(0.0001))
    end event
end bng3_events
)");
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "ssa";
    options.seed = 173;
    options.tEnd = 1.0;
    options.nSteps = 1;

    const auto first = integrator.integrate(options);
    const auto repeated = integrator.integrate(options);

    REQUIRE(first.eventCount == 1);
    REQUIRE(repeated.eventCount == 1);
    CHECK(first.observables.back()[0] == repeated.observables.back()[0]);
    CHECK(first.observables.back()[0] < 0.0);
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

TEST_CASE("OdeIntegrator reevaluates functional rates after time and state changes",
          "[OdeOptions][RateDependencies]") {
    auto model = parser::parseModel(R"(
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules Xtotal X()
end observables
begin functions
    rate() = Xtotal + time
end functions
begin reaction rules
    X() -> 0 rate
end reaction rules
)");
    REQUIRE(model != nullptr);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    const engine::OdeIntegrator integrator(*model, network);
    std::vector<double> state(network.species.size(), 0.0);
    REQUIRE(network.species.size() == 1);

    state[0] = 1.0;
    CHECK_THAT(integrator.evaluateRateCoefficients(0.0, state.data()).front(),
               Catch::Matchers::WithinAbs(1.0, 1e-12));
    CHECK_THAT(integrator.evaluateRateCoefficients(1.0, state.data()).front(),
               Catch::Matchers::WithinAbs(2.0, 1e-12));

    state[0] = 3.0;
    CHECK_THAT(integrator.evaluateRateCoefficients(0.0, state.data()).front(),
               Catch::Matchers::WithinAbs(3.0, 1e-12));
}

TEST_CASE("OdeIntegrator reevaluates a rate through a time-dependent parameter",
          "[OdeOptions][RateDependencies]") {
    auto model = parser::parseModel(R"(
begin parameters
    k time + 1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin reaction rules
    X() -> 0 k
end reaction rules
)");
    REQUIRE(model != nullptr);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    const engine::OdeIntegrator integrator(*model, network);
    const double state[] = {1.0};

    CHECK_THAT(integrator.evaluateRateCoefficients(0.0, state).front(),
               Catch::Matchers::WithinAbs(1.0, 1e-12));
    CHECK_THAT(integrator.evaluateRateCoefficients(1.0, state).front(),
               Catch::Matchers::WithinAbs(2.0, 1e-12));
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

TEST_CASE("OdeIntegrator keeps function-name matching bounded", "[OdeOptions]") {
    auto model = parser::parseModel(R"(
begin parameters
    rateFnExtra 3
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin functions
    rateFn() = 2
end functions
begin reaction rules
    X() -> 0 rateFnExtra
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);

    double state[] = {1.0};
    double derivatives[] = {0.0};
    integrator.derivs(0.0, state, derivatives);

    REQUIRE_THAT(derivatives[0], Catch::Matchers::WithinAbs(-3.0, 1e-12));
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

    std::string output;
    {
        std::ifstream input(outputPath);
        REQUIRE(input.good());
        output.assign((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    }
    std::filesystem::remove(outputPath);

    REQUIRE(output.find("begin groups\n") != std::string::npos);
    REQUIRE(output.find("    1 total 1,2\n") != std::string::npos);
    REQUIRE(output.find("    2 present 1\n") != std::string::npos);
}

TEST_CASE("NetWriter associates seed amounts with compartmented species",
          "[NetWriter][issue-142]") {
    auto model = parser::parseModel(R"(
begin compartments
    cyto 3 1.0
    nuc 3 1.0
end compartments
begin molecule types
    A(x)
end molecule types
begin seed species
    A(x)@cyto 2
    A(x)@nuc 7
end seed species
)");

    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    REQUIRE(network.species.size() == 2);

    const auto outputPath = std::filesystem::temp_directory_path() /
        ("bng3-net-writer-compartment-seeds-" +
         std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) +
         ".net");
    io::NetWriter::write(outputPath, *model, network);

    std::ifstream input(outputPath);
    REQUIRE(input.good());
    const std::string output((std::istreambuf_iterator<char>(input)),
                             std::istreambuf_iterator<char>());
    input.close();
    std::filesystem::remove(outputPath);

    CHECK(output.find("@cyto::A(x) 2") != std::string::npos);
    CHECK(output.find("@nuc::A(x) 7") != std::string::npos);
}

TEST_CASE("NetWriter emits the live amount after seed species mutation",
          "[NetWriter][issue-272]") {
    auto model = parser::parseModel(R"(
begin parameters
    S0 100
end parameters
begin molecule types
    S(c~R)
end molecule types
begin seed species
    S(c~R) S0
end seed species
)");

    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    REQUIRE(network.species.size() == 1);
    network.species.get(0).setAmount(200.0);

    const auto outputPath = std::filesystem::temp_directory_path() /
        ("bng3-net-writer-live-seed-" +
         std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) +
         ".net");
    io::NetWriter::write(outputPath, *model, network);

    std::ifstream input(outputPath);
    REQUIRE(input.good());
    const std::string output((std::istreambuf_iterator<char>(input)),
                             std::istreambuf_iterator<char>());
    input.close();
    std::filesystem::remove(outputPath);

    CHECK(output.find("S(c~R) 200\n") != std::string::npos);
    CHECK(output.find("S(c~R) S0\n") == std::string::npos);
}

TEST_CASE("NetWriter does not reuse a seed expression after a sub-tolerance mutation",
          "[NetWriter][issue-272]") {
    auto model = parser::parseModel(R"(
begin parameters
    S0 1
end parameters
begin molecule types
    S(c~R)
end molecule types
begin seed species
    S(c~R) S0
end seed species
)");

    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    REQUIRE(network.species.size() == 1);
    network.species.get(0).setAmount(1.0 + 5e-13);

    const auto outputPath = std::filesystem::temp_directory_path() /
        ("bng3-net-writer-sub-tolerance-seed-" +
         std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) +
         ".net");
    io::NetWriter::write(outputPath, *model, network);

    std::ifstream input(outputPath);
    REQUIRE(input.good());
    const std::string output((std::istreambuf_iterator<char>(input)),
                             std::istreambuf_iterator<char>());
    input.close();
    std::filesystem::remove(outputPath);

    const auto speciesStart = output.find("begin species\n");
    REQUIRE(speciesStart != std::string::npos);
    const auto speciesEnd = output.find("end species", speciesStart);
    REQUIRE(speciesEnd != std::string::npos);
    std::istringstream speciesLines(
        output.substr(speciesStart, speciesEnd - speciesStart));
    std::string line;
    double exportedAmount = -1.0;
    while (std::getline(speciesLines, line)) {
        std::istringstream row(line);
        std::size_t index = 0;
        std::string pattern;
        double amount = 0.0;
        if (row >> index >> pattern >> amount && pattern == "S(c~R)") {
            exportedAmount = amount;
            break;
        }
    }
    REQUIRE(exportedAmount > 0.0);
    CHECK(exportedAmount == network.species.get(0).getAmount());
    CHECK(exportedAmount != 1.0);
    CHECK(output.find("S(c~R) S0\n") == std::string::npos);
}

TEST_CASE("NetWriter matches seed amount expressions by constant identity",
          "[NetWriter][issue-272]") {
    auto model = parser::parseModel(R"(
begin parameters
    dynamicAmount 1
    constantAmount 1
end parameters
begin molecule types
    S(c~R)
end molecule types
begin seed species
    S(c~R) dynamicAmount
    $S(c~R) constantAmount
end seed species
)");

    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    REQUIRE(network.species.size() == 1);
    auto constantGraph = network.species.get(0).getSpeciesGraph();
    network.species.setCheckIso(false);
    network.species.add(ast::Species(std::move(constantGraph), 1.0, true));

    const auto outputPath = std::filesystem::temp_directory_path() /
        ("bng3-net-writer-constant-seed-" +
         std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) +
         ".net");
    io::NetWriter::write(outputPath, *model, network);

    std::ifstream input(outputPath);
    REQUIRE(input.good());
    const std::string output((std::istreambuf_iterator<char>(input)),
                             std::istreambuf_iterator<char>());
    input.close();
    std::filesystem::remove(outputPath);

    CHECK(output.find("S(c~R) dynamicAmount\n") != std::string::npos);
    CHECK(output.find("$S(c~R) constantAmount\n") != std::string::npos);
}

TEST_CASE("NetWriter preserves indexed and empty NET observable groups",
          "[NetWriter][issue-273]") {
    auto model = parser::parseModel(R"(
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 2
    A().B() 7
end seed species
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    REQUIRE(network.species.size() == 2);
    const auto exactASpecies = std::find_if(
        network.species.all().begin(), network.species.all().end(),
        [](const ast::Species& species) {
            return species.getSpeciesGraph().toString() == "A()";
        });
    REQUIRE(exactASpecies != network.species.all().end());
    const auto exactAIndex = static_cast<std::size_t>(
        std::distance(network.species.all().begin(), exactASpecies));
    const auto otherSpeciesIndex = 1 - exactAIndex;

    ast::Observable indexed("selected", "Species", {});
    indexed.setIndexedSpeciesWeights(
        {{exactAIndex, 2.0}, {otherSpeciesIndex, 3.0}});
    model->addObservable(std::move(indexed));
    ast::Observable empty("absent", "Species", {});
    empty.setIndexedSpeciesWeights({});
    model->addObservable(std::move(empty));

    const auto outputPath = std::filesystem::temp_directory_path() /
        ("bng3-net-writer-indexed-groups-" +
         std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) +
         ".net");
    io::NetWriter::write(outputPath, *model, network);

    std::ifstream input(outputPath);
    REQUIRE(input.good());
    const std::string output((std::istreambuf_iterator<char>(input)),
                             std::istreambuf_iterator<char>());
    input.close();
    std::filesystem::remove(outputPath);

    std::ostringstream expectedGroup;
    expectedGroup << "    1 selected ";
    for (std::size_t speciesIndex = 0; speciesIndex < network.species.size();
         ++speciesIndex) {
        if (speciesIndex != 0) expectedGroup << ',';
        expectedGroup << (speciesIndex == exactAIndex ? 2 : 3) << '*'
                      << speciesIndex + 1;
    }
    CHECK(output.find(expectedGroup.str()) != std::string::npos);
    CHECK(output.find("    2 absent \n") != std::string::npos);
}

TEST_CASE("NetWriter does not apply pattern symmetry factor to TotalRate", "[NetWriter]") {
    auto model = parser::parseModel(R"(
begin parameters
    k 0.75
end parameters
begin molecule types
    A()
    B()
    C()
end molecule types
begin seed species
    A() 1
    B() 2
end seed species
begin reaction rules
    A() + B() + B() -> C() k TotalRate
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    const auto suffix = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto outputPath = std::filesystem::temp_directory_path() /
        ("bng3-net-writer-total-rate-" + std::to_string(suffix) + ".net");
    io::NetWriter::write(outputPath, *model, network);

    std::string output;
    {
        std::ifstream input(outputPath);
        REQUIRE(input.good());
        output.assign(std::istreambuf_iterator<char>(input),
                      std::istreambuf_iterator<char>());
    }
    std::filesystem::remove(outputPath);

    CHECK(output.find("0.5*k") == std::string::npos);
    CHECK(output.find(" k #") != std::string::npos);
}

TEST_CASE("NetWriter preserves inline parameter comments from BNGL", "[NetWriter][issue-216]") {
    auto model = parser::parseModel(R"(
begin parameters
    k 2  # units=s-1
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin reaction rules
    A() -> 0 k
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    const auto suffix = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto outputPath = std::filesystem::temp_directory_path() /
        ("bng3-net-writer-parameter-comment-" + std::to_string(suffix) + ".net");
    io::NetWriter::write(outputPath, *model, network);

    std::string output;
    {
        std::ifstream input(outputPath);
        REQUIRE(input.good());
        output.assign(std::istreambuf_iterator<char>(input),
                      std::istreambuf_iterator<char>());
    }
    std::filesystem::remove(outputPath);

    CHECK(output.find("    1 k 2  # units=s-1\n") != std::string::npos);
}

TEST_CASE("NetWriter keeps nested model-function rates dynamic", "[NetWriter]") {
    auto model = parser::parseModel(R"BNG(
begin parameters
    k 0.5
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules A_total A()
end observables
begin functions
    f() = A_total
end functions
begin reaction rules
    A() -> B() k * f()
end reaction rules
)BNG");

    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    const auto derived = io::NetWriter::buildDerivedRateParams(*model, network);
    REQUIRE(derived.size() == 1);
    const auto found = derived.find(model->getReactionRules().front().getRuleName());
    REQUIRE(found != derived.end());
    CHECK(found->second.asFunction);
}

TEST_CASE(
    "finite-network FunctionProduct rates use each reaction's local scopes",
    "[NetWriter][issue-162]") {
  auto model = parser::parseModel(R"BNG(
begin molecule types
    A(s~u~p)
    B()
end molecule types
begin seed species
    A(s~u) 1
    B() 1
end seed species
begin observables
    Molecules A_unphosphorylated A(s~u)
    Molecules A_phosphorylated A(s~p)
    Molecules B_total B()
end observables
begin functions
    fA(x) = A_unphosphorylated(x) + _pi - _pi
    fB(y) = B_total(y) + _e - _e
end functions
begin reaction rules
    %x::A(s~u) + %y::B() -> %x::A(s~p) + %y::B() FunctionProduct("fA(x)", "fB(y)")
end reaction rules
)BNG");

  REQUIRE(model != nullptr);
  engine::NetworkGenerator generator(*model);
  const auto network = generator.generateNative();
  REQUIRE(network.reactions.all().size() == 1);
  INFO(network.reactions.all().front().getRateLaw());

  const auto derived = io::NetWriter::buildDerivedRateParams(*model, network);
  REQUIRE(derived.size() == 1);
  const auto found =
      derived.find(model->getReactionRules().front().getRuleName());
  REQUIRE(found != derived.end());
  REQUIRE(found->second.perReactionRates.size() == 1);
  CHECK(found->second.perReactionRates.begin()->second.second == 1.0);

  engine::OdeIntegrator integrator(*model, network);
  std::vector<double> concentrations(network.species.size(), 0.0);
  std::vector<double> derivatives(network.species.size(), 0.0);
  for (const auto reactant : network.reactions.all().front().getReactants()) {
    concentrations[reactant] = 1.0;
  }
  integrator.derivs(0.0, concentrations.data(), derivatives.data());
  CHECK_THAT(
      derivatives[network.reactions.all().front().getReactants().front()],
      Catch::Matchers::WithinAbs(-1.0, 1e-12));

  const auto outputPath =
      std::filesystem::temp_directory_path() /
      ("bng3-function-product-" +
       std::to_string(
           std::chrono::steady_clock::now().time_since_epoch().count()) +
       ".net");
  io::NetWriter::write(outputPath, *model, network);
  std::ifstream input(outputPath);
  REQUIRE(input.good());
  const std::string output((std::istreambuf_iterator<char>(input)),
                           std::istreambuf_iterator<char>());
  input.close();
  std::filesystem::remove(outputPath);
  CHECK(output.find("R1_local1 1") != std::string::npos);
  CHECK(output.find("R1_local1 #R1") != std::string::npos);
}

TEST_CASE("finite-network local functions can inspect product scopes",
          "[NetWriter][issue-132]") {
  auto model = parser::parseModel(R"BNG(
begin parameters
    k 1
    threshold 0.5
    p 0.1
end parameters
begin molecule types
    L(s)
    R(s)
end molecule types
begin seed species
    L(s!1).R(s!1) 1
end seed species
begin observables
    Molecules Rtot R()
end observables
begin functions
    large(x) = if(Rtot(x) > threshold, 1, 0)
    both_large(x,y) = FunctionProduct("large(x)", "large(y)")
end functions
begin reaction rules
    L(s!1).R(s!1) -> L(s!+)%x + R(s)%y k*if(both_large(x,y) > 0.5, p, 1.0)
end reaction rules
)BNG");

  REQUIRE(model != nullptr);
  engine::NetworkGenerator generator(*model);
  const auto network = generator.generateNative();
  REQUIRE(network.reactions.all().size() == 1);
  INFO(model->getReactionRules().front().getRates().front().toString());
  INFO(network.reactions.all().front().getRateLaw());
  INFO(model->getFunctions()[1].getExpression().toString());
  CHECK(network.reactions.all().front().getRateLaw().find("x::Rtot=0") !=
        std::string::npos);
  CHECK(network.reactions.all().front().getRateLaw().find("y::Rtot=1") !=
        std::string::npos);
  const auto derived = io::NetWriter::buildDerivedRateParams(*model, network);
  const auto found =
      derived.find(model->getReactionRules().front().getRuleName());
  REQUIRE(found != derived.end());
  REQUIRE(found->second.perReactionRates.size() == 1);
  CHECK(found->second.perReactionRates.begin()->second.second == 1.0);

  engine::OdeIntegrator integrator(*model, network);
  std::vector<double> concentrations(network.species.size(), 0.0);
  std::vector<double> derivatives(network.species.size(), 0.0);
  const auto &reaction = network.reactions.all().front();
  for (const auto reactant : reaction.getReactants())
    concentrations[reactant] = 1.0;
  integrator.derivs(0.0, concentrations.data(), derivatives.data());
  CHECK_THAT(derivatives[reaction.getReactants().front()],
             Catch::Matchers::WithinAbs(-1.0, 1e-12));

  const auto outputPath =
      std::filesystem::temp_directory_path() /
      ("bng3-product-local-function-" +
       std::to_string(
           std::chrono::steady_clock::now().time_since_epoch().count()) +
       ".net");
  io::NetWriter::write(outputPath, *model, network);
  std::ifstream input(outputPath);
  REQUIRE(input.good());
  const std::string output((std::istreambuf_iterator<char>(input)),
                           std::istreambuf_iterator<char>());
  input.close();
  std::filesystem::remove(outputPath);
  CHECK(output.find("R1_local1 1") != std::string::npos);
  CHECK(output.find("R1_local1 #R1") != std::string::npos);
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

TEST_CASE("Batch SSA returns one species row per output time on every backend",
          "[OdeOptions][BatchSSA]") {
    // OdeResult::concentrations and batchStdDevs are documented as
    // [timeIndex][speciesIndex] and are walked in lockstep with timePoints by
    // every consumer: writeOutputFiles indexes concentrations[step] for step up
    // to timePoints.size() (the .cdat row count), save_progress does the same,
    // and the Python binding shapes them as an (n_steps, n_species) array.
    // integrateBatchSSA's GPU branch used to fill them from
    // BatchSsaMetrics::meanSpecies, which detail::fillDoubleFields collapses to
    // a single final-state row, so crossing the GPU threshold silently changed
    // the result's shape and overran the .cdat writer.  A GPU backend can only
    // be selected on a machine with a compiled-in device, so this pins the
    // contract for both selections: "none" must reach the CPU pool directly,
    // and "auto" must produce the same grid whether it takes the GPU branch or
    // rejects it -- never a one-row grid.
    auto model = parseDecayModel();
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();

    constexpr std::size_t kBatch = 8;
    constexpr std::size_t kSteps = 4;

    auto runBatch = [&](const std::string& gpuBackend) {
        engine::OdeOptions options;
        options.method = "ssa";
        options.tStart = 0.0;
        options.tEnd = 4.0;
        options.nSteps = kSteps;
        options.seed = 7;
        options.batchSize = kBatch;
        options.batchGpuPreferred = true;
        options.batchGpuBackend = gpuBackend;
        return engine::OdeIntegrator(*model, network).integrate(options);
    };

    const engine::OdeResult cpuResult = runBatch("none");
    const engine::OdeResult autoResult = runBatch("auto");

    REQUIRE(cpuResult.batchSize == kBatch);
    REQUIRE(autoResult.batchSize == kBatch);

    // Both backend selections must agree on shape with each other.
    REQUIRE(autoResult.concentrations.size() == cpuResult.concentrations.size());
    REQUIRE(autoResult.batchStdDevs.size() == cpuResult.batchStdDevs.size());
    REQUIRE(autoResult.observables.size() == cpuResult.observables.size());
    REQUIRE(autoResult.batchObsStdDevs.size() == cpuResult.batchObsStdDevs.size());

    const std::size_t nSpecies = network.species.size();
    for (const engine::OdeResult* result : {&cpuResult, &autoResult}) {
        const std::size_t expectedRows = kSteps + 1;
        REQUIRE(result->timePoints.size() == expectedRows);
        REQUIRE(result->concentrations.size() == expectedRows);
        REQUIRE(result->batchStdDevs.size() == expectedRows);
        REQUIRE(result->observables.size() == expectedRows);
        REQUIRE(result->batchObsStdDevs.size() == expectedRows);
        for (std::size_t t = 0; t < expectedRows; ++t) {
            REQUIRE(result->concentrations[t].size() == nSpecies);
            REQUIRE(result->batchStdDevs[t].size() == nSpecies);
        }
    }
}

TEST_CASE("ParameterList re-evaluates a time-dependent parameter at each t",
          "[OdeOptions][Parameters]") {
    // A parameter whose expression reads `time` is a function of t, so it must
    // not be memoized.  Caching it froze the value at whatever t was evaluated
    // first -- t=0 during model construction -- and left a time-dependent
    // decay rate stuck at zero for the whole run.
    auto model = parser::parseModel(R"(
begin parameters
    kbase 1.0
    k time*kbase
    kDerived k+1
    kConst 2.0
end parameters
)");
    REQUIRE(model != nullptr);
    auto& parameters = model->getParameters();
    parameters.evaluateAll(0.0);

    CHECK_THAT(parameters.evaluate("k", 0.0), Catch::Matchers::WithinAbs(0.0, 1e-12));
    CHECK_THAT(parameters.evaluate("k", 2.0), Catch::Matchers::WithinAbs(2.0, 1e-12));
    CHECK_THAT(parameters.evaluate("k", 5.0), Catch::Matchers::WithinAbs(5.0, 1e-12));

    // Time-dependence is transitive: kDerived reads k, so it tracks t as well.
    CHECK_THAT(parameters.evaluate("kDerived", 2.0), Catch::Matchers::WithinAbs(3.0, 1e-12));
    CHECK_THAT(parameters.evaluate("kDerived", 5.0), Catch::Matchers::WithinAbs(6.0, 1e-12));

    // A time-independent parameter must still return the same value at any t;
    // that is the memo the rate-evaluation hot path depends on.
    CHECK_THAT(parameters.evaluate("kConst", 0.0), Catch::Matchers::WithinAbs(2.0, 1e-12));
    CHECK_THAT(parameters.evaluate("kConst", 100.0), Catch::Matchers::WithinAbs(2.0, 1e-12));
}

TEST_CASE("finite-network rates distinguish species and molecule local scopes",
          "[NetWriter][LocalScope]") {
    const auto localRateFor = [](const std::string& reactant,
                                 const std::string& product) {
        auto model = parser::parseModel(R"BNG(
begin molecule types
    A(s~u~p)
    I(i)
end molecule types
begin seed species
    A(s~u!1).I(i!1) 1
end seed species
begin observables
    Molecules I_total I()
end observables
begin functions
    f(x) = I_total(x)
end functions
begin reaction rules
)BNG" + reactant + " -> " + product + R"BNG( f(x)
end reaction rules
)BNG");
        REQUIRE(model != nullptr);

        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE(network.reactions.all().size() == 1);
        const auto derived = io::NetWriter::buildDerivedRateParams(*model, network);
        REQUIRE(derived.size() == 1);
        const auto found = derived.find(model->getReactionRules().front().getRuleName());
        REQUIRE(found != derived.end());
        REQUIRE(found->second.perReactionRates.size() == 1);
        return found->second.perReactionRates.begin()->second.second;
    };

    CHECK(localRateFor("    %x:A(s~u!1).I(i!1)",
                       "A(s~p!1).I(i!1)") == 1.0);
    CHECK(localRateFor("    A%x(s~u!1).I(i!1)",
                       "A%x(s~p!1).I(i!1)") == 0.0);
}

TEST_CASE("NetWriter evaluated parameters round trip binary64 values",
          "[NetWriter][Precision]") {
    auto model = parseDecayModel();
    const double expected = -9.221848749616356;
    model->getParameters().add(ast::Parameter("precise", ast::Expression::number(expected)));
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    const auto outputPath = std::filesystem::temp_directory_path() /
        ("bng3-net-parameter-precision-" +
         std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) +
         ".net");
    io::NetWriter::write(outputPath, *model, network);
    std::ifstream input(outputPath);
    REQUIRE(input.good());
    std::string line;
    bool found = false;
    while (std::getline(input, line)) {
        std::istringstream fields(line);
        std::size_t index;
        std::string name;
        double value;
        if (fields >> index >> name >> value && name == "precise") {
            found = true;
            CHECK(value == expected);
        }
    }
    input.close();
    std::filesystem::remove(outputPath);
    CHECK(found);
}

TEST_CASE("CVODE executes recurring native events between output times", "[OdeOptions][Events]") {
    auto model = parseDecayModel();
    ast::Event event;
    event.id = "reset";
    event.trigger = ast::Expression::binary("<=", ast::Expression::identifier("Xtot"),
                                           ast::Expression::number(50));
    event.assignments.push_back({"Xtot", ast::Expression::number(100)});
    model->setEventFormatVersion(1);
    model->addEvent(std::move(event));
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 20;
    options.nSteps = 1;
    const auto result = integrator.integrate(options);
    REQUIRE(result.timePoints.size() == 2);
    REQUIRE(result.observables.back().size() == 1);
    CHECK_THAT(result.observables.back()[0], Catch::Matchers::WithinRel(400 * std::exp(-2.0), 2e-6));
    const auto repeated = integrator.integrate(options);
    CHECK(repeated.observables == result.observables);
}

TEST_CASE("CVODE defers a native event until its delay elapses", "[OdeOptions][Events]") {
    auto model = parseDecayModel();
    ast::Event event;
    event.id = "reset";
    // A strict trigger needs no monotone proof: the root function is positive
    // exactly where the trigger holds.
    event.trigger = ast::Expression::binary("<", ast::Expression::identifier("Xtot"),
                                           ast::Expression::number(50));
    event.delay = ast::Expression::number(10.0);
    event.assignments.push_back({"Xtot", ast::Expression::number(100)});
    model->setEventFormatVersion(1);
    model->addEvent(std::move(event));
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 20.0;
    options.nSteps = 1;
    const auto result = integrator.integrate(options);
    REQUIRE(result.timePoints.size() == 2);
    // X decays as 100 * exp(-0.1 t) and crosses 50 at t = log(2) / 0.1.  The
    // assignment runs ten seconds later, so the reported value at t = 20 is
    // the reset value decayed for the remaining time.
    const double crossing = std::log(2.0) / 0.1;
    const double expected = 100 * std::exp(-0.1 * (20.0 - (crossing + 10.0)));
    CHECK_THAT(result.observables.back()[0], Catch::Matchers::WithinRel(expected, 1e-6));
}

TEST_CASE("CVODE keeps a delayed native event on its trigger-time values",
          "[OdeOptions][Events]") {
    auto model = parseDecayModel();
    ast::Event event;
    event.id = "snapshot";
    event.trigger = ast::Expression::binary("<", ast::Expression::identifier("Xtot"),
                                           ast::Expression::number(50));
    event.delay = ast::Expression::number(1.0);
    event.useValuesFromTriggerTime = true;
    // The assignment records the value the trigger saw, not the value at the
    // execution instant.
    event.assignments.push_back({"Xtot", ast::Expression::number(0)});
    model->setEventFormatVersion(1);
    model->addEvent(std::move(event));
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 20.0;
    options.nSteps = 1;
    const auto result = integrator.integrate(options);
    REQUIRE(result.observables.back().size() == 1);
    // The reset to zero happens one second after the crossing, so the value
    // reported at t = 20 is the zero that was written at the execution time.
    CHECK_THAT(result.observables.back()[0], Catch::Matchers::WithinAbs(0.0, 1e-12));
}

TEST_CASE("CVODE reevaluates pending native event priorities at execution time",
          "[OdeOptions][Events]") {
    auto model = parser::parseModel(R"(
begin molecule types
    S()
    O()
end molecule types
begin seed species
    S() 0
    O() 0
end seed species
begin observables
    Molecules Signal S()
    Molecules Result O()
end observables
begin bng3_events version 1
    event "raise_signal"
        trigger: time >= 1
        initial_value: false
        persistent: true
        use_values_from_trigger_time: false
        delay: 1
        priority: 100
        assignment: Signal = 10
    end event
    event "set_first"
        trigger: time >= 1
        initial_value: false
        persistent: true
        use_values_from_trigger_time: false
        delay: 1
        priority: 10 - Signal + time
        assignment: Result = 1
    end event
    event "set_last"
        trigger: time >= 1
        initial_value: false
        persistent: true
        use_values_from_trigger_time: false
        delay: 1
        priority: 5 + Signal - time
        assignment: Result = 2
    end event
end bng3_events
)");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 3.0;
    options.nSteps = 3;

    const auto result = integrator.integrate(options);

    REQUIRE(result.observables.back().size() == 2);
    // All three events are due at t=2.  raise_signal executes first and
    // changes the remaining priorities to 2 and 13, so set_last precedes
    // set_first.  Evaluating priorities at trigger time or only once before
    // the first assignment would instead leave set_first ahead of set_last.
    CHECK_THAT(result.observables.back()[1], Catch::Matchers::WithinAbs(1.0, 1e-12));
}

TEST_CASE("CVODE executes a delayed event for a conjunction of state roots",
          "[OdeOptions][Events]") {
    auto model = parser::parseModel(R"(
begin molecule types
    K()
end molecule types
begin seed species
    K() 1
end seed species
begin observables
    Molecules k1_amt K()
end observables
begin functions
    __rate_rule__k1() = 1
end functions
begin reaction rules
    __rate_rule_k1: 0 -> K() __rate_rule__k1() TotalRate
end reaction rules
begin bng3_events version 1
    event "reset"
        trigger: (k1_amt > 3.5) && (k1_amt < 4)
        initial_value: true
        persistent: true
        use_values_from_trigger_time: true
        delay: 1.1
        assignment: k1_amt = 1
    end event
end bng3_events
)");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 10.0;
    options.nSteps = 10;

    const auto result = integrator.integrate(options);

    REQUIRE(result.observables.size() == 11);
    CHECK_THAT(result.observables[4][0], Catch::Matchers::WithinAbs(1.4, 1e-8));
}

TEST_CASE("CVODE rejects a nonfinite dynamic native event priority",
          "[OdeOptions][Events]") {
    auto model = parser::parseModel(R"(
begin molecule types
    S()
    O()
end molecule types
begin seed species
    S() 1e200
    O() 0
end seed species
begin observables
    Molecules Signal S()
    Molecules Result O()
end observables
begin bng3_events version 1
    event "overflowing_priority"
        trigger: time > 1
        initial_value: false
        persistent: true
        use_values_from_trigger_time: false
        delay: 1
        priority: Signal * Signal
        assignment: Result = 1
    end event
    event "finite_priority"
        trigger: time > 1
        initial_value: false
        persistent: true
        use_values_from_trigger_time: false
        delay: 1
        priority: 1
        assignment: Result = 2
    end event
end bng3_events
)");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeIntegrator integrator(*model, network);
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 3.0;
    options.nSteps = 3;

    REQUIRE_THROWS_WITH(
        integrator.integrate(options),
        Catch::Matchers::ContainsSubstring("bng3_events expression is nonfinite"));
}

TEST_CASE("CVODE refuses a native trigger that rises at the first instant",
          "[OdeOptions][Events]") {
    auto model = parseDecayModel();
    ast::Event event;
    event.id = "rising";
    // The trigger holds immediately, so the crossing has no instant to be
    // attributed to.
    event.trigger = ast::Expression::binary(">", ast::Expression::identifier("time"),
                                            ast::Expression::number(0));
    event.assignments.push_back({"Xtot", ast::Expression::number(1)});
    model->setEventFormatVersion(1);
    model->addEvent(std::move(event));
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 1.0;
    options.nSteps = 1;
    REQUIRE_THROWS_WITH(
        engine::OdeIntegrator(*model, network).integrate(options),
        Catch::Matchers::ContainsSubstring(
            "strict trigger equals its threshold at the initial time"));
}

TEST_CASE("CVODE carries a non-finite native event assignment to output",
          "[OdeOptions][Events]") {
    auto model = parseDecayModel();
    ast::Event event;
    event.id = "assign_nan";
    event.trigger = ast::Expression::binary(
        ">=", ast::Expression::identifier("time"), ast::Expression::number(1.0));
    event.useValuesFromTriggerTime = false;
    event.assignments.push_back(
        {"Xtot", ast::Expression::number(std::numeric_limits<double>::quiet_NaN())});
    model->setEventFormatVersion(1);
    model->addEvent(std::move(event));
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 1.0;
    options.nSteps = 2;

    const auto result = engine::OdeIntegrator(*model, network).integrate(options);

    REQUIRE(result.observables.size() == 3);
    CHECK(std::isnan(result.observables.back().front()));
}

TEST_CASE("OdeIntegrator recovers after late stop condition failure", "[OdeOptions][Lifecycle]") {
    auto model = parseDecayModel();
    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 1.0;
    options.nSteps = 2;
    // Lazy if succeeds at t=0, then throws after CVODE allocated its state.
    options.stopIf = "if(time > 0, missing_name, 0)";
    REQUIRE_THROWS_WITH(
        engine::OdeIntegrator(*model, network).integrate(options),
        Catch::Matchers::ContainsSubstring("Unknown parameter 'missing_name'"));
    options.stopIf.clear();
    const auto recovered = engine::OdeIntegrator(*model, network).integrate(options);
    auto freshModel = parseDecayModel();
    engine::NetworkGenerator freshGenerator(*freshModel);
    auto freshNetwork = freshGenerator.generateNative();
    const auto fresh = engine::OdeIntegrator(*freshModel, freshNetwork).integrate(options);
    CHECK(recovered.timePoints == fresh.timePoints);
    CHECK(recovered.concentrations == fresh.concentrations);
    // The existing ASan job runs this test alone with leak detection enabled.
    // Functional recovery does not itself demonstrate native resource cleanup.
}
