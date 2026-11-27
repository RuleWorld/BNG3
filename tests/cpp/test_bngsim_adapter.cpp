#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <memory>
#include <cmath>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <stdexcept>

#include <bngsim/bngsim.hpp>

#include "engine/BngsimAdapter.hpp"
#include "engine/FiniteBackend.hpp"
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

std::unique_ptr<ast::Model> parseTwoSpeciesDecayModel() {
    return parser::parseModel(R"(
begin parameters
    k 1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
    B() 1
end seed species
begin observables
    Molecules Atot A()
    Molecules Btot B()
end observables
begin reaction rules
    A() -> 0 k
    B() -> 0 k
end reaction rules
)");
}

std::unique_ptr<ast::Model> parseEmptySpeciesModel() {
    return parser::parseModel(R"(
begin model
begin parameters
    k 1
end parameters
end model
)");
}

} // namespace

TEST_CASE("BNGsim adapter maps generated network without .net serialization", "[bngsim]") {
    auto model = parseDecayModel();
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();

    auto adapted = engine::buildBngsimNetwork(*model, network);

    REQUIRE(adapted->n_species() == static_cast<int>(network.species.size()));
    REQUIRE(adapted->n_reactions() == static_cast<int>(network.reactions.size()));
    REQUIRE(adapted->n_observables() == 1);
    REQUIRE(adapted->species().at(0).name == network.species.get(0).getSpeciesGraph().toString());
    REQUIRE(adapted->reactions().at(0).rate_law_type == bngsim::RateLawType::Elementary);
    REQUIRE(adapted->reactions().at(0).stat_factor == network.reactions.all().at(0).getFactor());

    bngsim::TimeSpec times;
    times.t_start = 0.0;
    times.t_end = 1.0;
    times.n_points = 3;
    bngsim::CvodeSimulator bngsimSolver(*adapted);
    const auto bngsimResult = bngsimSolver.run(times);

    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = times.t_start;
    options.tEnd = times.t_end;
    options.nSteps = static_cast<std::size_t>(times.n_points - 1);
    const auto bng3Result = engine::OdeIntegrator(*model, network).integrate(options);

    REQUIRE(bngsimResult.n_times() == static_cast<int>(bng3Result.timePoints.size()));
    for (std::size_t timeIndex = 0; timeIndex < bng3Result.timePoints.size(); ++timeIndex) {
        CHECK_THAT(bngsimResult.time().at(timeIndex),
                   Catch::Matchers::WithinAbs(bng3Result.timePoints.at(timeIndex), 1e-12));
        CHECK_THAT(bngsimResult.species_data().at(timeIndex),
                   Catch::Matchers::WithinAbs(bng3Result.concentrations.at(timeIndex).at(0), 1e-7));
    }
}

TEST_CASE("BNGsim ODE preserves native steady-state stopping semantics", "[bngsim]") {
    auto model = parseTwoSpeciesDecayModel();
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "cvode";
    options.tStart = 0.0;
    options.tEnd = 3.0;
    options.nSteps = 3;
    options.rtol = 1e-10;
    options.atol = 1e-12;
    options.steadyState = true;

    SECTION("normalizes the derivative norm by species count") {
        options.steadyStateTol = 0.1;
        const auto native = engine::simulateFiniteOde(
            *model, network, options, engine::FiniteBackend::Native);
        const auto bngsim = engine::simulateFiniteOde(
            *model, network, options, engine::FiniteBackend::Bngsim);

        REQUIRE(native.timePoints == std::vector<double>{0.0, 1.0, 2.0});
        REQUIRE(bngsim.timePoints == native.timePoints);
        REQUIRE(bngsim.concentrations.size() == native.concentrations.size());
        for (std::size_t timeIndex = 0; timeIndex < native.timePoints.size(); ++timeIndex) {
            for (std::size_t speciesIndex = 0;
                 speciesIndex < native.concentrations.at(timeIndex).size();
                 ++speciesIndex) {
                CHECK_THAT(
                    bngsim.concentrations.at(timeIndex).at(speciesIndex),
                    Catch::Matchers::WithinAbs(
                        native.concentrations.at(timeIndex).at(speciesIndex), 1e-7));
            }
        }
    }

    SECTION("checks after recording the initial row") {
        // At t=0, sqrt(sum(dy/dt^2))/n_species = sqrt(2)/2 < 0.8.
        // Both engines must still record t=1 before testing the cutoff.
        options.steadyStateTol = 0.8;
        const auto native = engine::simulateFiniteOde(
            *model, network, options, engine::FiniteBackend::Native);
        const auto bngsim = engine::simulateFiniteOde(
            *model, network, options, engine::FiniteBackend::Bngsim);

        REQUIRE(native.timePoints == std::vector<double>{0.0, 1.0});
        REQUIRE(bngsim.timePoints == native.timePoints);
        REQUIRE(bngsim.concentrations.size() == native.concentrations.size());
        for (std::size_t timeIndex = 0; timeIndex < native.timePoints.size(); ++timeIndex) {
            for (std::size_t speciesIndex = 0;
                 speciesIndex < native.concentrations.at(timeIndex).size();
                 ++speciesIndex) {
                CHECK_THAT(
                    bngsim.concentrations.at(timeIndex).at(speciesIndex),
                    Catch::Matchers::WithinAbs(
                        native.concentrations.at(timeIndex).at(speciesIndex), 1e-7));
            }
        }
    }
}

TEST_CASE("BNGsim ODE rejects unqualified native-only options", "[bngsim]") {
    auto model = parseTwoSpeciesDecayModel();
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "cvode";
    options.tEnd = 1.0;
    options.nSteps = 2;

    SECTION("stop_if") {
        options.stopIf = "Atot < 0.5";
        REQUIRE_THROWS_WITH(
            engine::simulateFiniteOde(*model, network, options,
                                      engine::FiniteBackend::Bngsim),
            Catch::Matchers::ContainsSubstring("BNGsim adapter rejected stop_if"));
    }

    SECTION("sparse solver request") {
        options.sparse = true;
        REQUIRE_THROWS_WITH(
            engine::simulateFiniteOde(*model, network, options,
                                      engine::FiniteBackend::Bngsim),
            Catch::Matchers::ContainsSubstring("BNGsim adapter rejected sparse"));
    }

    SECTION("product-scale warning") {
        options.checkProductScale = 0.5;
        REQUIRE_THROWS_WITH(
            engine::simulateFiniteOde(*model, network, options,
                                      engine::FiniteBackend::Bngsim),
            Catch::Matchers::ContainsSubstring(
                "BNGsim adapter rejected check_product_scale"));
    }

    SECTION("non-positive steady-state tolerance") {
        options.steadyState = true;
        options.steadyStateTol = 0.0;
        REQUIRE_THROWS_WITH(
            engine::simulateFiniteOde(*model, network, options,
                                      engine::FiniteBackend::Bngsim),
            Catch::Matchers::ContainsSubstring(
                "BNGsim adapter rejected steady_state_tol"));
    }

    SECTION("empty species set") {
        auto emptyModel = parseEmptySpeciesModel();
        engine::NetworkGenerator emptyGenerator(*emptyModel);
        const auto emptyNetwork = emptyGenerator.generateNative();
        options.steadyState = true;
        const auto native = engine::simulateFiniteOde(
            *emptyModel, emptyNetwork, options, engine::FiniteBackend::Native);
        REQUIRE(native.timePoints == std::vector<double>{0.0, 0.5});
        REQUIRE_THROWS_WITH(
            engine::simulateFiniteOde(*emptyModel, emptyNetwork, options,
                                      engine::FiniteBackend::Bngsim),
            Catch::Matchers::ContainsSubstring(
                "empty-state steady-state truncation differs"));
    }
}

TEST_CASE("BNGsim SSA rejects controls it cannot represent", "[bngsim]") {
    auto model = parseTwoSpeciesDecayModel();
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    engine::OdeOptions options;
    options.method = "ssa";
    options.tEnd = 1.0;
    options.nSteps = 2;
    options.seed = 17;

    SECTION("stop_if") {
        options.stopIf = "Atot < 0.5";
        REQUIRE_THROWS_WITH(
            engine::simulateFiniteSsa(*model, network, options,
                                      engine::FiniteBackend::Bngsim),
            Catch::Matchers::ContainsSubstring("BNGsim adapter rejected stop_if"));
    }

    SECTION("maximum reaction events") {
        options.maxSimSteps = 1;
        REQUIRE_THROWS_WITH(
            engine::simulateFiniteSsa(*model, network, options,
                                      engine::FiniteBackend::Bngsim),
            Catch::Matchers::ContainsSubstring(
                "BNGsim adapter rejected max_sim_steps"));
    }

    SECTION("event interval without explicit sample times") {
        options.outputStepInterval = 2;
        REQUIRE_THROWS_WITH(
            engine::simulateFiniteSsa(*model, network, options,
                                      engine::FiniteBackend::Bngsim),
            Catch::Matchers::ContainsSubstring(
                "BNGsim adapter rejected output_step_interval"));
    }

    SECTION("explicit sample times supersede event interval") {
        options.sampleTimes = {0.0, 0.5, 1.0};
        options.outputStepInterval = 2;
        const auto native = engine::simulateFiniteSsa(
            *model, network, options, engine::FiniteBackend::Native);
        const auto bngsim = engine::simulateFiniteSsa(
            *model, network, options, engine::FiniteBackend::Bngsim);

        REQUIRE(native.timePoints == options.sampleTimes);
        REQUIRE(bngsim.timePoints == options.sampleTimes);
    }
}

TEST_CASE("BNGsim adapter fails closed on non-reference rate expressions", "[bngsim]") {
    auto model = parser::parseModel(R"(
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin reaction rules
    X() -> 0 k*2
end reaction rules
)");
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();

    REQUIRE_THROWS_WITH(
        engine::buildBngsimNetwork(*model, network),
        Catch::Matchers::ContainsSubstring("is not a direct parameter or function reference"));
}

TEST_CASE("BNGsim adapter preserves bounded functional rate references", "[bngsim]") {
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

    auto adapted = engine::buildBngsimNetwork(*model, network);

    REQUIRE(adapted->n_functions() == 1);
    REQUIRE(adapted->reactions().at(0).rate_law_type == bngsim::RateLawType::Functional);

    bngsim::TimeSpec times;
    times.t_start = 0.0;
    times.t_end = 0.1;
    times.n_points = 2;
    bngsim::CvodeSimulator solver(*adapted);
    const auto result = solver.run(times);
    REQUIRE(result.n_times() == 2);
    CHECK_THAT(result.species_data().back(),
               Catch::Matchers::WithinAbs(std::exp(-0.2), 1e-6));
}

TEST_CASE("BNGsim adapter rejects unsupported dynamic compartment surface", "[bngsim]") {
    auto model = parser::parseModel(R"(
begin model
begin compartments
    CYT 3 1+time
end compartments
begin molecule types
    X()
end molecule types
begin seed species
    @CYT:X() 1
end seed species
end model
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();

    REQUIRE_THROWS_WITH(
        engine::buildBngsimNetwork(*model, network),
        Catch::Matchers::ContainsSubstring("dynamic/time-dependent compartment volumes are unsupported"));
}

TEST_CASE("BNGsim adapter preserves BNGL observable matching semantics", "[bngsim]") {
    auto model = parser::parseModel(R"(
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b!1).B(a!1) 2
    A(b) 3
end seed species
begin observables
    Molecules A_molecules A()
    Molecules A_free A(b)
    Molecules A_bound A(b!+)
    Species A_complex A(b!1).B(a!1)
end observables
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    auto adapted = engine::buildBngsimNetwork(*model, network);

    REQUIRE(adapted->n_observables() == 4);
    const auto findObservable = [&](const std::string& name) -> const bngsim::Observable& {
        for (const auto& observable : adapted->observables()) {
            if (observable.name == name) return observable;
        }
        throw std::runtime_error("missing BNGsim observable");
    };
    CHECK(findObservable("A_molecules").entries.size() == 2);
    CHECK(findObservable("A_free").entries.size() == 1);
    CHECK(findObservable("A_bound").entries.size() == 1);
    CHECK(findObservable("A_complex").entries.size() == 1);
    CHECK(findObservable("A_complex").entries.front().factor == 1.0);

    bngsim::TimeSpec times;
    times.t_start = 0.0;
    times.t_end = 0.1;
    times.n_points = 2;
    bngsim::CvodeSimulator solver(*adapted);
    const auto result = solver.run(times);
    REQUIRE(result.n_observables() == 4);
    REQUIRE(result.observable_data().size() >= 4);
    CHECK(result.observable_data()[0] == 5.0);
    CHECK(result.observable_data()[1] == 3.0);
    CHECK(result.observable_data()[2] == 2.0);
    CHECK(result.observable_data()[3] == 2.0);
}

TEST_CASE("BNGsim adapter maps inline TFUN function rates", "[bngsim]") {
    auto model = parser::parseModel(R"(
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin functions
    rate() = TFUN([0, 1], [2, 4], time)
end functions
begin reaction rules
    X() -> 0 rate
end reaction rules
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    auto adapted = engine::buildBngsimNetwork(*model, network);

    bngsim::TimeSpec times;
    times.t_start = 0.0;
    times.t_end = 1.0;
    times.n_points = 2;
    bngsim::CvodeSimulator solver(*adapted);
    const auto result = solver.run(times);
    REQUIRE(result.n_times() == 2);
    CHECK_THAT(result.species_data().back(),
               Catch::Matchers::WithinAbs(std::exp(-3.0), 1e-6));
}

TEST_CASE("BNGsim adapter maps absolute-file TFUN function rates", "[bngsim]") {
    const auto suffix = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto tablePath = std::filesystem::temp_directory_path() /
                           ("bng3_bngsim_adapter_tfun_" + std::to_string(suffix) + ".dat");
    {
        std::ofstream table(tablePath);
        REQUIRE(table.good());
        table << "# time rate__tfun0\n0 2\n1 4\n";
    }

    const std::string modelText =
        "begin molecule types\n"
        "    X()\n"
        "end molecule types\n"
        "begin seed species\n"
        "    X() 1\n"
        "end seed species\n"
        "begin functions\n"
        "    rate() = TFUN('" + tablePath.string() + "', time)\n"
        "end functions\n"
        "begin reaction rules\n"
        "    X() -> 0 rate\n"
        "end reaction rules\n";
    auto model = parser::parseModel(modelText);
    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    auto adapted = engine::buildBngsimNetwork(*model, network);

    bngsim::TimeSpec times;
    times.t_start = 0.0;
    times.t_end = 1.0;
    times.n_points = 2;
    bngsim::CvodeSimulator solver(*adapted);
    const auto result = solver.run(times);
    CHECK_THAT(result.species_data().back(),
               Catch::Matchers::WithinAbs(std::exp(-3.0), 1e-6));

    std::error_code error;
    std::filesystem::remove(tablePath, error);
}

TEST_CASE("BNGsim adapter rejects relative TFUN provenance", "[bngsim]") {
    auto model = parser::parseModel(R"(
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin functions
    rate() = TFUN('forcing.dat', time)
end functions
begin reaction rules
    X() -> 0 rate
end reaction rules
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();

    REQUIRE_THROWS_WITH(
        engine::buildBngsimNetwork(*model, network),
        Catch::Matchers::ContainsSubstring("relative table path requires source-directory provenance"));
}

TEST_CASE("BNGsim adapter resolves relative TFUN with source_path provenance", "[bngsim]") {
    const auto suffix = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto tempDir = std::filesystem::temp_directory_path() /
                         ("bng3_bngsim_rel_tfun_" + std::to_string(suffix));
    std::filesystem::create_directories(tempDir);
    const auto tablePath = tempDir / "forcing.dat";
    const auto sourcePath = tempDir / "model.bngl";
    {
        std::ofstream table(tablePath);
        REQUIRE(table.good());
        table << "# time rate__tfun0\n0 2\n1 4\n";
    }

    auto model = parser::parseModel(R"(
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin functions
    rate() = TFUN('forcing.dat', time)
end functions
begin reaction rules
    X() -> 0 rate
end reaction rules
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();

    engine::BngsimLoweringOptions options;
    options.sourcePath = sourcePath;
    const auto check = engine::checkBngsimLowering(*model, network, options);
    REQUIRE(check.supported);
    REQUIRE(check.blockers.empty());

    auto adapted = engine::buildBngsimNetwork(*model, network, options);
    bngsim::TimeSpec times;
    times.t_start = 0.0;
    times.t_end = 1.0;
    times.n_points = 2;
    bngsim::CvodeSimulator solver(*adapted);
    const auto result = solver.run(times);
    CHECK_THAT(result.species_data().back(),
               Catch::Matchers::WithinAbs(std::exp(-3.0), 1e-6));

    std::error_code error;
    std::filesystem::remove_all(tempDir, error);
}

TEST_CASE("BNGsim adapter wraps supported inline rate expressions when enabled", "[bngsim]") {
    SECTION("parameter arithmetic matches native ODE") {
        auto model = parser::parseModel(R"(
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k*2
end reaction rules
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();

        engine::BngsimLoweringOptions options;
        options.allowRateExpressionWrapping = true;
        const auto check = engine::checkBngsimLowering(*model, network, options);
        REQUIRE(check.supported);

        auto adapted = engine::buildBngsimNetwork(*model, network, options);
        REQUIRE(adapted->n_functions() == 1);
        REQUIRE(adapted->reactions().at(0).rate_law_type == bngsim::RateLawType::Functional);

        bngsim::TimeSpec times;
        times.t_start = 0.0;
        times.t_end = 1.0;
        times.n_points = 3;
        bngsim::SolverOptions solverOpts;
        solverOpts.rtol = 1e-10;
        solverOpts.atol = 1e-12;
        bngsim::CvodeSimulator bngsimSolver(*adapted);
        const auto bngsimResult = bngsimSolver.run(times, solverOpts);

        engine::OdeOptions odeOptions;
        odeOptions.method = "cvode";
        odeOptions.tStart = 0.0;
        odeOptions.tEnd = 1.0;
        odeOptions.nSteps = 2;
        odeOptions.rtol = 1e-10;
        odeOptions.atol = 1e-12;
        const auto nativeResult = engine::OdeIntegrator(*model, network).integrate(odeOptions);

        for (std::size_t i = 0; i < nativeResult.timePoints.size(); ++i) {
            CHECK_THAT(bngsimResult.species_data().at(i),
                       Catch::Matchers::WithinAbs(nativeResult.concentrations.at(i).at(0), 1e-6));
        }
    }

    SECTION("observable-dependent inline expression matches native ODE") {
        auto model = parser::parseModel(R"(
begin parameters
    k 0.05
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 4
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k*(1 + Xtot)
end reaction rules
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();

        engine::BngsimLoweringOptions options;
        options.allowRateExpressionWrapping = true;
        auto adapted = engine::buildBngsimNetwork(*model, network, options);

        bngsim::TimeSpec times;
        times.t_start = 0.0;
        times.t_end = 1.0;
        times.n_points = 3;
        bngsim::SolverOptions solverOpts;
        solverOpts.rtol = 1e-10;
        solverOpts.atol = 1e-12;
        bngsim::CvodeSimulator bngsimSolver(*adapted);
        const auto bngsimResult = bngsimSolver.run(times, solverOpts);

        engine::OdeOptions odeOptions;
        odeOptions.method = "cvode";
        odeOptions.tStart = 0.0;
        odeOptions.tEnd = 1.0;
        odeOptions.nSteps = 2;
        odeOptions.rtol = 1e-10;
        odeOptions.atol = 1e-12;
        const auto nativeResult = engine::OdeIntegrator(*model, network).integrate(odeOptions);

        for (std::size_t i = 0; i < nativeResult.timePoints.size(); ++i) {
            CHECK_THAT(bngsimResult.species_data().at(i),
                       Catch::Matchers::WithinAbs(nativeResult.concentrations.at(i).at(0), 1e-6));
        }
    }

    SECTION("unsupported builtin function stays fail-closed even with wrapping enabled") {
        auto model = parser::parseModel(R"(
begin parameters
    kcat 3.0
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin reaction rules
    X() -> 0 factorial(kcat)
end reaction rules
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();

        engine::BngsimLoweringOptions options;
        options.allowRateExpressionWrapping = true;
        REQUIRE_THROWS_WITH(
            engine::buildBngsimNetwork(*model, network, options),
            Catch::Matchers::ContainsSubstring("unsupported function"));
    }
}

TEST_CASE("BNGsim adapter rejects ungated or dynamic energy, barrier, and driven_by surfaces", "[bngsim]") {
    SECTION("dynamic energy pattern expression fails closed") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    phi 0.5
    Ea 1.0
end parameters
begin molecule types
    A(s~u~p)
end molecule types
begin seed species
    A(s~u) 10
end seed species
begin energy patterns
    ep1: A(s~p) 1.0 + time
end energy patterns
begin reaction rules
    A(s~u) -> A(s~p) Arrhenius(phi, Ea)
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE_THROWS_WITH(
            engine::buildBngsimNetwork(*model, network),
            Catch::Matchers::ContainsSubstring("energy pattern expression must be statically evaluable"));
    }

    SECTION("barrier patterns fail closed when BNG_NFSIM_GENERAL_ENERGY is unset") {
        unsetenv("BNG_NFSIM_GENERAL_ENERGY");
        auto model = parser::parseModel(R"(
begin model
begin molecule types
    A(s~u~p)
end molecule types
begin parameters
    phi 0.5
    Ea 1.0
    Gb 2.0
end parameters
begin seed species
    A(s~u) 10
end seed species
begin energy patterns
    ep1: A(s~p) 1.0
end energy patterns
begin barrier patterns
    bp1: A(s~u) -> A(s~p) Gb
end barrier patterns
begin reaction rules
    A(s~u) <-> A(s~p) Arrhenius(phi, Ea)
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        const auto check = engine::checkBngsimLowering(*model, network);
        REQUIRE_FALSE(check.supported);
        bool sawBarrier = false;
        for (const auto& blocker : check.blockers) {
            if (blocker.find("BNG_NFSIM_GENERAL_ENERGY=1") != std::string::npos) {
                sawBarrier = true;
            }
        }
        REQUIRE(sawBarrier);
    }

    SECTION("driven_by reservoir work fails closed when BNG_NFSIM_GENERAL_ENERGY is unset") {
        unsetenv("BNG_NFSIM_GENERAL_ENERGY");
        auto model = parser::parseModel(R"(
begin model
begin parameters
    phi 0.5
    Ea 1.0
    W 0.5
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin reaction rules
    A() -> B() Arrhenius(phi, Ea) driven_by(W)
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE_THROWS_WITH(
            engine::buildBngsimNetwork(*model, network),
            Catch::Matchers::ContainsSubstring("BNG_NFSIM_GENERAL_ENERGY=1"));
    }
}

TEST_CASE("BNGsim adapter rejects population maps, protocol, actions, local functions, and TotalRate", "[bngsim]") {
    SECTION("population maps") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    k 1.0
end parameters
begin molecule types
    A()
    P() population
end molecule types
begin seed species
    A() 10
end seed species
begin population maps
    m1: A() -> P() k
end population maps
begin reaction rules
    A() -> 0 k
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE_THROWS_WITH(
            engine::buildBngsimNetwork(*model, network),
            Catch::Matchers::ContainsSubstring("population maps are not a generated-network feature"));
    }

    SECTION("simulation protocol") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    k 1.0
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin reaction rules
    X() -> 0 k
end reaction rules
begin protocol
    simulate({method=>"ode", t_end=>1, n_steps=>2})
end protocol
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE_THROWS_WITH(
            engine::buildBngsimNetwork(*model, network),
            Catch::Matchers::ContainsSubstring("simulation protocol requires a protocol bridge"));
    }

    SECTION("actions other than generate_network") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    k 1.0
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin reaction rules
    X() -> 0 k
end reaction rules
end model
setParameter("k", 2.0)
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE_THROWS_WITH(
            engine::buildBngsimNetwork(*model, network),
            Catch::Matchers::ContainsSubstring("action execution requires a protocol bridge"));
    }

    SECTION("local function arguments") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    k 1.0
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin functions
    local_rate(x) = k
end functions
begin reaction rules
    X() -> 0 k
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE_THROWS_WITH(
            engine::buildBngsimNetwork(*model, network),
            Catch::Matchers::ContainsSubstring("function arguments require a local-function bridge"));
    }

    SECTION("absolute-flux reactions fail closed under PSA") {
        auto model = parser::parseModel(R"(
setOption("BNG3AbsoluteFluxRules","r")
begin model
begin parameters
    k 1.0
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin reaction rules
    r: X() -> 0 k TotalRate
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        engine::OdeOptions opts;
        opts.method = "psa";
        opts.tStart = 0.0;
        opts.tEnd = 1.0;
        opts.nSteps = 2;
        opts.seed = 7;
        REQUIRE_THROWS_WITH(
            engine::simulateFinitePsa(*model, network, opts, 10.0, engine::FiniteBackend::Bngsim, true),
            Catch::Matchers::ContainsSubstring("absolute-flux reactions are unsupported in BNGsim PSA"));
    }
}

TEST_CASE("BNGsim adapter bridges TotalRate with exact ODE and SSA parity", "[bngsim]") {
    SECTION("homodimer TotalRate omits symmetry factor 0.5 and matches native ODE") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    k 0.05
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
    Molecules Atot A()
    Molecules Dtot D()
end observables
begin reaction rules
    A() + A() -> D() k TotalRate
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();

        const auto check = engine::checkBngsimLowering(*model, network);
        REQUIRE(check.supported);

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 2.0;
        opts.nSteps = 10;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Bngsim);

        REQUIRE(bngsimRes.timePoints.size() == nativeRes.timePoints.size());
        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            CHECK_THAT(bngsimRes.observables[ti][0],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][0], 1e-6));
            CHECK_THAT(bngsimRes.observables[ti][1],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][1], 1e-6));
        }
    }

    SECTION("homodimer TotalRate SSA firing probability matches exact propensity") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    k 1.0
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
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();

        engine::OdeOptions opts;
        opts.method = "ssa";
        opts.tStart = 0.0;
        opts.tEnd = 0.1;
        opts.nSteps = 1;

        constexpr std::size_t kTrials = 2048;
        std::size_t fired = 0;
        for (std::size_t seed = 1; seed <= kTrials; ++seed) {
            opts.seed = seed;
            const auto res = engine::simulateFiniteSsa(
                *model, network, opts, engine::FiniteBackend::Bngsim);
            fired += static_cast<std::size_t>(std::llround(res.observables.back()[0]));
        }
        // Propensity = 1.0 * 1.0 * 2 * 1 = 2.0 -> P(fire by t=0.1) = 1 - exp(-0.2)
        const double fraction = static_cast<double>(fired) / static_cast<double>(kTrials);
        CHECK_THAT(fraction, Catch::Matchers::WithinAbs(1.0 - std::exp(-0.2), 0.035));
    }

    SECTION("compartment TotalRate omits volume unit conversion factor") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    k 0.2
end parameters
begin compartments
    CYT 3 4.0
end compartments
begin molecule types
    A()
    B()
    C()
end molecule types
begin seed species
    @CYT:A() 5
    @CYT:B() 5
end seed species
begin observables
    Molecules Ctot C()
end observables
begin reaction rules
    @CYT:A() + @CYT:B() -> @CYT:C() k TotalRate
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 1.0;
        opts.nSteps = 5;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Bngsim);

        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            CHECK_THAT(bngsimRes.observables[ti][0],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][0], 1e-6));
        }
    }
}

TEST_CASE("BNGsim adapter bridges static 2D/3D compartments with exact ODE parity", "[bngsim]") {
    SECTION("3D volume, 2D surface anchor, transport, and zero-order synthesis match native ODE") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    kbind 0.5
    kunbind 0.1
    ktrans 0.3
    ksyn 2.0
    kdimer 0.04
end parameters
begin compartments
    EC 3 10.0
    PM 2 2.0 EC
    CYT 3 5.0 PM
end compartments
begin molecule types
    L(r)
    R(l)
    X()
    D()
end molecule types
begin seed species
    @EC:L(r) 40
    @PM:R(l) 20
    @EC:X() 30
    @CYT:X() 10
end seed species
begin observables
    Molecules RL @PM:L(r!1).R(l!1)
    Molecules X_ec @EC:X()
    Molecules X_cyt @CYT:X()
    Molecules D_cyt @CYT:D()
end observables
begin reaction rules
    @EC:L(r) + @PM:R(l) <-> @PM:L(r!1).R(l!1) kbind, kunbind
    @EC:X() -> @CYT:X() ktrans
    0 -> @CYT:X() ksyn
    @CYT:X() + @CYT:X() -> @CYT:D() kdimer
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();

        const auto check = engine::checkBngsimLowering(*model, network);
        REQUIRE(check.supported);
        REQUIRE(check.blockers.empty());

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 2.0;
        opts.nSteps = 10;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Bngsim);

        REQUIRE(bngsimRes.observables.size() == nativeRes.observables.size());
        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            for (std::size_t oi = 0; oi < nativeRes.observables[ti].size(); ++oi) {
                CHECK_THAT(
                    bngsimRes.observables[ti][oi],
                    Catch::Matchers::WithinAbs(nativeRes.observables[ti][oi], 1e-5));
            }
        }
    }

    SECTION("event-modified compartment volume remains fail-closed") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    V 2.0
    k 0.1
end parameters
begin compartments
    CYT 3 V
end compartments
begin molecule types
    X()
end molecule types
begin seed species
    @CYT:X() 10
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    @CYT:X() + @CYT:X() -> 0 k
end reaction rules
begin bng3_events version 1
    event "resize"
    trigger: time >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: V = 4.0
    end event
end bng3_events
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE_THROWS_WITH(
            engine::buildBngsimNetwork(*model, network),
            Catch::Matchers::ContainsSubstring("event-modified compartment volumes are unsupported"));
    }
}

TEST_CASE("BNGsim adapter bridges bng3_events to add_event with exact ODE and SSA parity", "[bngsim]") {
    SECTION("state-threshold reset event matches native ODE") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    k 0.5
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules X A()
end observables
begin reaction rules
    A() -> 0 k
end reaction rules
begin bng3_events version 1
    event "reset"
    trigger: X <= 5
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: X = 10
    end event
end bng3_events
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE(engine::checkBngsimLowering(*model, network).supported);

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 4.0;
        opts.nSteps = 20;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Bngsim);

        REQUIRE(bngsimRes.observables.size() == nativeRes.observables.size());
        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            CHECK_THAT(bngsimRes.observables[ti][0],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][0], 1e-4));
        }
    }

    SECTION("delayed event with parameter mutation and priority ordering matches native ODE") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    k 0.2
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
    B() 0
end seed species
begin observables
    Molecules Aobs A()
    Molecules Bobs B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
begin bng3_events version 1
    event "boost_rate"
    trigger: time >= 1.0
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    delay: 0.5
    priority: 10
    assignment: k = 1.0
    end event
    event "pulse_a"
    trigger: time >= 1.0
    initial_value: false
    persistent: true
    use_values_from_trigger_time: false
    delay: 0.5
    priority: 1
    assignment: Aobs = Aobs + 20
    end event
end bng3_events
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE(engine::checkBngsimLowering(*model, network).supported);

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 3.0;
        opts.nSteps = 15;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Bngsim);

        // Result must project out promoted unreported parameter species/observables.
        REQUIRE(bngsimRes.concentrations[0].size() == network.species.size());
        REQUIRE(bngsimRes.observables[0].size() == model->getObservables().size());
        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            CHECK_THAT(bngsimRes.observables[ti][0],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][0], 1e-4));
            CHECK_THAT(bngsimRes.observables[ti][1],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][1], 1e-4));
        }
    }

    SECTION("time-triggered SSA dose event preserves exact conservation shift") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    k 0.2
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 50
    B() 0
end seed species
begin observables
    Molecules Aobs A()
    Molecules Bobs B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
begin bng3_events version 1
    event "dose"
    trigger: time >= 1.0
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: Aobs = Aobs + 25
    end event
end bng3_events
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        engine::OdeOptions opts;
        opts.method = "ssa";
        opts.tStart = 0.0;
        opts.tEnd = 2.0;
        opts.nSteps = 4;
        opts.seed = 42;
        const auto res = engine::simulateFiniteSsa(
            *model, network, opts, engine::FiniteBackend::Bngsim);
        REQUIRE(res.observables.size() == 5);
        // Before t=1.0 total mass = 50; at/after t=1.0 total mass = 75
        CHECK_THAT(res.observables[0][0] + res.observables[0][1],
                   Catch::Matchers::WithinAbs(50.0, 1e-9));
        CHECK_THAT(res.observables[1][0] + res.observables[1][1],
                   Catch::Matchers::WithinAbs(50.0, 1e-9));
        CHECK_THAT(res.observables[2][0] + res.observables[2][1],
                   Catch::Matchers::WithinAbs(75.0, 1e-9));
        CHECK_THAT(res.observables[4][0] + res.observables[4][1],
                   Catch::Matchers::WithinAbs(75.0, 1e-9));
    }

    SECTION("unsupported event constructs fail closed") {
        auto distribModel = parser::parseModel(R"(
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules X A()
end observables
begin reaction rules
    A() -> 0 k
end reaction rules
begin bng3_events version 1
    event "draw"
    trigger: time >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: X = distrib_uniform(1, 5)
    end event
end bng3_events
end model
)");
        REQUIRE(distribModel != nullptr);
        engine::NetworkGenerator distribGen(*distribModel);
        const auto distribNet = distribGen.generateNative();
        REQUIRE_THROWS_WITH(
            engine::buildBngsimNetwork(*distribModel, distribNet),
            Catch::Matchers::ContainsSubstring("distrib"));
    }

    SECTION("derived event-dependent parameter chain matches native ODE and analytic SBML semantics") {
        auto derivedParamModel = parser::parseModel(R"(
begin model
begin parameters
    k 0.1
    k2 2*k
    k3 k2 + 0.3
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
    B() 0
end seed species
begin observables
    Molecules Aobs A()
    Molecules Bobs B()
end observables
begin reaction rules
    A() -> B() k3
end reaction rules
begin bng3_events version 1
    event "mutate_k"
    trigger: time >= 1.0
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: k = 0.5
    end event
    event "read_k2"
    trigger: time >= 1.5
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: Bobs = Bobs + 10 * k2
    end event
end bng3_events
end model
)");
        REQUIRE(derivedParamModel != nullptr);
        engine::NetworkGenerator derivedGen(*derivedParamModel);
        const auto derivedNet = derivedGen.generateNative();
        REQUIRE(engine::checkBngsimLowering(*derivedParamModel, derivedNet).supported);

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 3.0;
        opts.nSteps = 15;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *derivedParamModel, derivedNet, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *derivedParamModel, derivedNet, opts, engine::FiniteBackend::Bngsim);

        REQUIRE(bngsimRes.observables.size() == nativeRes.observables.size());
        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            CHECK_THAT(bngsimRes.observables[ti][0],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][0], 1e-4));
            CHECK_THAT(bngsimRes.observables[ti][1],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][1], 1e-4));
        }

        // Also verify simultaneous priority-ordered derived-parameter expansion
        // against the exact analytic SBML L3v2 result: at t=1.0, A(1)=100*exp(-0.5),
        // B(1-)=100*(1-exp(-0.5)), priority-10 sets k=0.5 (k2=1.0), then priority-1
        // adds 10*k2=10 so B(1+)=100*(1-exp(-0.5))+10.
        auto simEventModel = parser::parseModel(R"(
begin model
begin parameters
    k 0.1
    k2 2*k
    k3 k2 + 0.3
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
    B() 0
end seed species
begin observables
    Molecules Aobs A()
    Molecules Bobs B()
end observables
begin reaction rules
    A() -> B() k3
end reaction rules
begin bng3_events version 1
    event "mutate_k"
    trigger: time >= 1.0
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    priority: 10
    assignment: k = 0.5
    end event
    event "read_k2"
    trigger: time >= 1.0
    initial_value: false
    persistent: true
    use_values_from_trigger_time: false
    priority: 1
    assignment: Bobs = Bobs + 10 * k2
    end event
end bng3_events
end model
)");
        REQUIRE(simEventModel != nullptr);
        engine::NetworkGenerator simGen(*simEventModel);
        const auto simNet = simGen.generateNative();
        const auto simRes = engine::simulateFiniteOde(
            *simEventModel, simNet, opts, engine::FiniteBackend::Bngsim);
        // Index 5 corresponds to t = 1.0 (15 steps on [0, 3])
        const double expectedBAt1 = 100.0 * (1.0 - std::exp(-0.5)) + 10.0;
        CHECK_THAT(simRes.observables[5][1], Catch::Matchers::WithinAbs(expectedBAt1, 1e-4));
    }

    SECTION("inline TFUN in event assignment matches native ODE") {
        auto tfunEventModel = parser::parseModel(R"(
begin model
begin parameters
    k 0.2
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules Aobs A()
end observables
begin functions
    dose_table() = TFUN([0, 1, 2], [0, 15, 30], time)
end functions
begin reaction rules
    A() -> 0 k
end reaction rules
begin bng3_events version 1
    event "tfun_dose"
    trigger: time >= 1.0
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: Aobs = Aobs + dose_table()
    end event
end bng3_events
end model
)");
        REQUIRE(tfunEventModel != nullptr);
        engine::NetworkGenerator tfunGen(*tfunEventModel);
        const auto tfunNet = tfunGen.generateNative();
        REQUIRE(engine::checkBngsimLowering(*tfunEventModel, tfunNet).supported);

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 3.0;
        opts.nSteps = 15;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *tfunEventModel, tfunNet, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *tfunEventModel, tfunNet, opts, engine::FiniteBackend::Bngsim);

        REQUIRE(bngsimRes.observables.size() == nativeRes.observables.size());
        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            CHECK_THAT(bngsimRes.observables[ti][0],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][0], 1e-4));
        }
    }
}

TEST_CASE("BNGsim adapter bridges Sat, MM, Hill, and Arrhenius rate laws with exact parity", "[bngsim]") {
    SECTION("Sat (with homodimer symmetry), MM (2-reactant tQSSA and 1-reactant), and Hill match native ODE") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    kcat 2.0
    Km 5.0
    Vmax 3.0
    Kh 4.0
    n 2.5
    kcat_dim 1.5
    Km_dim 3.0
end parameters
begin molecule types
    S()
    E()
    P()
    H()
    Q()
    D()
    A()
end molecule types
begin seed species
    S() 25
    E() 6
    P() 0
    H() 18
    Q() 0
    A() 12
    D() 0
end seed species
begin observables
    Molecules Sobs S()
    Molecules Pobs P()
    Molecules Hobs H()
    Molecules Qobs Q()
    Molecules Aobs A()
    Molecules Dobs D()
end observables
begin reaction rules
    S() + E() -> P() + E() MM(kcat, Km)
    P() -> Q() Sat(kcat, Km)
    H() -> Q() Hill(Vmax, Kh, n)
    A() + A() -> D() Sat(kcat_dim, Km_dim)
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE(engine::checkBngsimLowering(*model, network).supported);

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 4.0;
        opts.nSteps = 20;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Bngsim);

        // Helper observables for Sat/Hill must be projected out of result.
        REQUIRE(bngsimRes.observables[0].size() == model->getObservables().size());
        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            for (std::size_t oi = 0; oi < nativeRes.observables[ti].size(); ++oi) {
                CHECK_THAT(bngsimRes.observables[ti][oi],
                           Catch::Matchers::WithinAbs(nativeRes.observables[ti][oi], 1e-5));
            }
        }
    }

    SECTION("MM with event-mutated parameter uses functional tQSSA and matches native ODE") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    kcat 1.0
    Km 4.0
end parameters
begin molecule types
    S()
    E()
    P()
end molecule types
begin seed species
    S() 20
    E() 5
    P() 0
end seed species
begin observables
    Molecules Sobs S()
    Molecules Pobs P()
end observables
begin reaction rules
    S() + E() -> P() + E() MM(kcat, Km)
end reaction rules
begin bng3_events version 1
    event "boost"
    trigger: time >= 1.0
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: kcat = 4.0
    end event
end bng3_events
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE(engine::checkBngsimLowering(*model, network).supported);

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 3.0;
        opts.nSteps = 15;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Bngsim);

        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            CHECK_THAT(bngsimRes.observables[ti][0],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][0], 1e-4));
            CHECK_THAT(bngsimRes.observables[ti][1],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][1], 1e-4));
        }
    }

    SECTION("homodimer Sat SSA propensity includes discrete falling factorial and symmetry 0.5") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    kcat 6.0
    Km 4.0
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
    Molecules Dobs D()
end observables
begin reaction rules
    A() + A() -> D() Sat(kcat, Km)
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        engine::OdeOptions opts;
        opts.method = "ssa";
        opts.tStart = 0.0;
        opts.tEnd = 0.2;
        opts.nSteps = 1;

        // Propensity = 0.5 * (6 / (4 + 2)) * 2 * (2 - 1) = 1.0 -> P(fire by 0.2) = 1 - exp(-0.2)
        constexpr std::size_t kTrials = 2048;
        std::size_t fired = 0;
        for (std::size_t seed = 1; seed <= kTrials; ++seed) {
            opts.seed = seed;
            const auto res = engine::simulateFiniteSsa(
                *model, network, opts, engine::FiniteBackend::Bngsim);
            fired += static_cast<std::size_t>(std::llround(res.observables.back()[0]));
        }
        const double fraction = static_cast<double>(fired) / static_cast<double>(kTrials);
        CHECK_THAT(fraction, Catch::Matchers::WithinAbs(1.0 - std::exp(-0.2), 0.035));
    }

    SECTION("Sat PSA conserves mass and runs cleanly") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    kcat 2.0
    Km 500.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 2000
    B() 0
end seed species
begin observables
    Molecules Aobs A()
    Molecules Bobs B()
end observables
begin reaction rules
    A() -> B() Sat(kcat, Km)
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        engine::OdeOptions opts;
        opts.method = "psa";
        opts.tStart = 0.0;
        opts.tEnd = 1.0;
        opts.nSteps = 4;
        opts.seed = 42;
        const auto res = engine::simulateFinitePsa(
            *model, network, opts, 50.0, engine::FiniteBackend::Bngsim, true);
        for (std::size_t ti = 0; ti < res.timePoints.size(); ++ti) {
            CHECK_THAT(res.observables[ti][0] + res.observables[ti][1],
                       Catch::Matchers::WithinAbs(2000.0, 1e-6));
        }
    }
}

TEST_CASE("BNGsim adapter bridges eBNGL energy, barrier, and driven_by with exact parity", "[bngsim]") {
    SECTION("energy patterns with reversible Arrhenius match native ODE and SSA") {
        auto model = parser::parseModel(R"(
begin model
begin parameters
    phi 0.5
    Ea 1.0
    Gf_p 0.8
end parameters
begin molecule types
    A(s~u~p)
end molecule types
begin seed species
    A(s~u) 40
    A(s~p) 10
end seed species
begin observables
    Molecules Au A(s~u)
    Molecules Ap A(s~p)
end observables
begin energy patterns
    ep1: A(s~p) Gf_p
end energy patterns
begin reaction rules
    A(s~u) <-> A(s~p) Arrhenius(phi, Ea)
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE(engine::checkBngsimLowering(*model, network).supported);

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 10.0;
        opts.nSteps = 20;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Bngsim);

        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            CHECK_THAT(bngsimRes.observables[ti][0],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][0], 1e-5));
            CHECK_THAT(bngsimRes.observables[ti][1],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][1], 1e-5));
        }

        // SSA conservation and equilibrium check
        engine::OdeOptions ssaOpts;
        ssaOpts.method = "ssa";
        ssaOpts.tStart = 0.0;
        ssaOpts.tEnd = 5.0;
        ssaOpts.nSteps = 5;
        ssaOpts.seed = 99;
        const auto ssaRes = engine::simulateFiniteSsa(
            *model, network, ssaOpts, engine::FiniteBackend::Bngsim);
        for (std::size_t ti = 0; ti < ssaRes.timePoints.size(); ++ti) {
            CHECK_THAT(ssaRes.observables[ti][0] + ssaRes.observables[ti][1],
                       Catch::Matchers::WithinAbs(50.0, 1e-9));
        }
    }

    SECTION("barrier patterns and driven_by reservoir work under BNG_NFSIM_GENERAL_ENERGY=1 match native ODE") {
        setenv("BNG_NFSIM_GENERAL_ENERGY", "1", 1);
        auto model = parser::parseModel(R"(
begin model
begin parameters
    phi 0.5
    Ea 1.0
    Gf_p 0.6
    Gb 0.4
    W 0.9
end parameters
begin molecule types
    A(s~u~p)
end molecule types
begin seed species
    A(s~u) 30
    A(s~p) 10
end seed species
begin observables
    Molecules Au A(s~u)
    Molecules Ap A(s~p)
end observables
begin energy patterns
    ep1: A(s~p) Gf_p
end energy patterns
begin barrier patterns
    bp1: A(s~u) -> A(s~p) Gb
end barrier patterns
begin reaction rules
    A(s~u) <-> A(s~p) Arrhenius(phi, Ea) driven_by(W)
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE(engine::checkBngsimLowering(*model, network).supported);

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 10.0;
        opts.nSteps = 20;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Bngsim);

        unsetenv("BNG_NFSIM_GENERAL_ENERGY");

        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            CHECK_THAT(bngsimRes.observables[ti][0],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][0], 1e-5));
            CHECK_THAT(bngsimRes.observables[ti][1],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][1], 1e-5));
        }
    }
}

TEST_CASE("BNGsim adapter bridges Atomizer absolute-flux reactions with exact ODE and SSA parity", "[bngsim]") {
    SECTION("nonlinear absolute-flux ODE matches native BNG3") {
        auto model = parser::parseModel(R"(
setOption("BNG3AbsoluteFluxRules","r_flux")
begin model
begin parameters
    k 2.5
end parameters
begin molecule types
    X()
    Y()
end molecule types
begin seed species
    X() 10
    Y() 0
end seed species
begin observables
    Molecules Xobs X()
    Molecules Yobs Y()
end observables
begin functions
    flux_fn() = k * Xobs / (3.0 + Xobs)
end functions
begin reaction rules
    r_flux: X() -> Y() flux_fn() TotalRate
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE(engine::checkBngsimLowering(*model, network).supported);

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 5.0;
        opts.nSteps = 20;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Bngsim);

        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            CHECK_THAT(bngsimRes.observables[ti][0],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][0], 1e-5));
            CHECK_THAT(bngsimRes.observables[ti][1],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][1], 1e-5));
        }
    }

    SECTION("absolute-flux SSA clamps propensity to 0 when reactant is depleted") {
        auto model = parser::parseModel(R"(
setOption("BNG3AbsoluteFluxRules","r_const")
begin model
begin parameters
    k 5.0
end parameters
begin molecule types
    X()
    Y()
end molecule types
begin seed species
    X() 3
    Y() 0
end seed species
begin observables
    Molecules Xobs X()
    Molecules Yobs Y()
end observables
begin reaction rules
    r_const: X() -> Y() k TotalRate
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();

        engine::OdeOptions opts;
        opts.method = "ssa";
        opts.tStart = 0.0;
        opts.tEnd = 5.0;
        opts.nSteps = 10;
        opts.seed = 42;
        const auto bngsimRes = engine::simulateFiniteSsa(
            *model, network, opts, engine::FiniteBackend::Bngsim);
        // Must clamp cleanly at X=0, Y=3 without going negative!
        for (std::size_t ti = 0; ti < bngsimRes.timePoints.size(); ++ti) {
            CHECK(bngsimRes.observables[ti][0] >= 0.0);
            CHECK_THAT(bngsimRes.observables[ti][0] + bngsimRes.observables[ti][1],
                       Catch::Matchers::WithinAbs(3.0, 1e-9));
        }
        CHECK_THAT(bngsimRes.observables.back()[0], Catch::Matchers::WithinAbs(0.0, 1e-9));
        CHECK_THAT(bngsimRes.observables.back()[1], Catch::Matchers::WithinAbs(3.0, 1e-9));
    }

    SECTION("Atomizer-style dynamic volume differential channel matches native ODE") {
        auto model = parser::parseModel(R"(
setOption("BNG3AbsoluteFluxRules","__rate_rule_V,r_decay")
begin model
begin parameters
    v_growth 0.5
    k 0.4
end parameters
begin molecule types
    V()
    X()
end molecule types
begin seed species
    V() 2.0
    X() 20.0
end seed species
begin observables
    Molecules Vobs V()
    Molecules Xobs X()
end observables
begin functions
    __rate_rule__V() = v_growth
    decay_flux() = k * Xobs / Vobs
end functions
begin reaction rules
    __rate_rule_V: 0 -> V() __rate_rule__V() TotalRate
    r_decay: X() -> 0 decay_flux() TotalRate
end reaction rules
end model
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE(engine::checkBngsimLowering(*model, network).supported);

        engine::OdeOptions opts;
        opts.method = "cvode";
        opts.tStart = 0.0;
        opts.tEnd = 4.0;
        opts.nSteps = 16;
        opts.rtol = 1e-10;
        opts.atol = 1e-12;
        const auto nativeRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Native);
        const auto bngsimRes = engine::simulateFiniteOde(
            *model, network, opts, engine::FiniteBackend::Bngsim);

        for (std::size_t ti = 0; ti < nativeRes.timePoints.size(); ++ti) {
            CHECK_THAT(bngsimRes.observables[ti][0],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][0], 1e-5));
            CHECK_THAT(bngsimRes.observables[ti][1],
                       Catch::Matchers::WithinAbs(nativeRes.observables[ti][1], 1e-5));
        }
    }
}

TEST_CASE("BNGsim PSA routes method=psa with conservation and fail-closed guards", "[bngsim]") {
    auto model = parser::parseModel(R"(
begin model
begin parameters
    k 0.25
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10000
    B() 0
end seed species
begin observables
    Molecules Aobs A()
    Molecules Bobs B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();

    const auto caps = engine::getBngsimCapabilities();
    REQUIRE(caps.available);
    REQUIRE(caps.supportsPsa);

    engine::OdeOptions opts;
    opts.method = "psa";
    opts.tStart = 0.0;
    opts.tEnd = 2.0;
    opts.nSteps = 4;
    opts.seed = 123;

    const auto psaRes = engine::simulateFinitePsa(
        *model, network, opts, 100.0, engine::FiniteBackend::Bngsim, true);
    REQUIRE(psaRes.timePoints.size() == 5);
    for (std::size_t ti = 0; ti < psaRes.timePoints.size(); ++ti) {
        CHECK_THAT(psaRes.observables[ti][0] + psaRes.observables[ti][1],
                   Catch::Matchers::WithinAbs(10000.0, 1e-6));
    }
    // High-population PSA mean should closely track deterministic 10000*exp(-0.5)
    CHECK_THAT(psaRes.observables.back()[0],
               Catch::Matchers::WithinRel(10000.0 * std::exp(-0.5), 0.08));

    // Seed reproducibility
    const auto psaRes2 = engine::simulateFinitePsa(
        *model, network, opts, 100.0, engine::FiniteBackend::Bngsim, true);
    REQUIRE(psaRes.observables == psaRes2.observables);

    // Fail-closed guards
    REQUIRE_THROWS_WITH(
        engine::simulateFinitePsa(*model, network, opts, 1.0, engine::FiniteBackend::Bngsim, true),
        Catch::Matchers::ContainsSubstring("BNGsim adapter rejected poplevel"));
    REQUIRE_THROWS_WITH(
        engine::simulateFinitePsa(*model, network, opts, 100.0, engine::FiniteBackend::Bngsim, false),
        Catch::Matchers::ContainsSubstring("BNGsim adapter rejected check_product_scale=0"));

    auto badMaxSteps = opts;
    badMaxSteps.maxSimSteps = 5;
    REQUIRE_THROWS_WITH(
        engine::simulateFinitePsa(*model, network, badMaxSteps, 100.0, engine::FiniteBackend::Bngsim, true),
        Catch::Matchers::ContainsSubstring("BNGsim adapter rejected max_sim_steps"));

    auto badStopIf = opts;
    badStopIf.stopIf = "Aobs < 5000";
    REQUIRE_THROWS_WITH(
        engine::simulateFinitePsa(*model, network, badStopIf, 100.0, engine::FiniteBackend::Bngsim, true),
        Catch::Matchers::ContainsSubstring("BNGsim adapter rejected stop_if"));
}

TEST_CASE("BNGsim adapter validates TFUN counters and interpolation methods", "[bngsim]") {
    SECTION("observable counter is accepted") {
        auto model = parser::parseModel(R"(
begin molecule types
    X()
end molecule types
begin seed species
    X() 2
end seed species
begin observables
    Molecules Xtot X()
end observables
begin functions
    rate() = TFUN([0, 10], [1, 3], Xtot)
end functions
begin reaction rules
    X() -> 0 rate
end reaction rules
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        const auto check = engine::checkBngsimLowering(*model, network);
        REQUIRE(check.supported);
    }

    SECTION("expression counter is rejected") {
        auto model = parser::parseModel(R"(
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin functions
    rate() = TFUN([0, 1], [2, 4], 1 + 2)
end functions
begin reaction rules
    X() -> 0 rate
end reaction rules
)");
        REQUIRE(model != nullptr);
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE_THROWS_WITH(
            engine::buildBngsimNetwork(*model, network),
            Catch::Matchers::ContainsSubstring("counter must be time or a named parameter/observable"));
    }

    SECTION("unsupported interpolation method is rejected") {
        auto model = parser::parseModel(R"(
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
)");
        REQUIRE(model != nullptr);
        model->addFunction(ast::Function(
            "rate",
            {},
            ast::Expression::tableFunction(
                {0.0, 1.0}, {2.0, 4.0}, "", ast::Expression::identifier("time"), "cubic")));
        engine::NetworkGenerator generator(*model);
        const auto network = generator.generateNative();
        REQUIRE_THROWS_WITH(
            engine::buildBngsimNetwork(*model, network),
            Catch::Matchers::ContainsSubstring("unsupported interpolation method"));
    }
}
