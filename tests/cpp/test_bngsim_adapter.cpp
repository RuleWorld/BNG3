#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <memory>
#include <cmath>
#include <string>

#include <bngsim/bngsim.hpp>

#include "engine/BngsimAdapter.hpp"
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
    X() -> 0 k*X
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
