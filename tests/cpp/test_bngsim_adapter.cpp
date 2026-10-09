#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <memory>
#include <cmath>
#include <chrono>
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

TEST_CASE("BNGsim adapter rejects unsupported semantic surfaces", "[bngsim]") {
    auto model = parser::parseModel(R"(
begin model
begin compartments
    CYT 3 1
end compartments
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
end model
)");
    REQUIRE(model != nullptr);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();

    REQUIRE_THROWS_WITH(
        engine::buildBngsimNetwork(*model, network),
        Catch::Matchers::ContainsSubstring("compartments require a volume-aware bridge"));
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
