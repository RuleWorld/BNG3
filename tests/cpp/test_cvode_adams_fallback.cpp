#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iterator>
#include <string>
#include <utility>

#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

TEST_CASE("CVODE retries a singular-zero Hill rate with Adams at the same controls",
          "[OdeOptions][CVODE][BioModels]") {
    std::ifstream fixture(BNG3_CVODE_ADAMS_FIXTURE_PATH);
    REQUIRE(fixture.good());
    const std::string source((std::istreambuf_iterator<char>(fixture)),
                             std::istreambuf_iterator<char>());
    const auto model = parser::parseModel(source);
    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();

    const auto speciesIndex = [&network](const std::string& id) {
        for (std::size_t index = 0; index < network.species.size(); ++index) {
            if (network.species.get(index).getSpeciesGraph().toString().find(
                    "M_" + id + "(") != std::string::npos) {
                return index;
            }
        }
        return network.species.size();
    };
    // Independent libRoadRunner 2.10.0 Adams integration of this reduced
    // fixture's SBML: t=0..1, rtol=1e-10, requested atol=1e-16.
    const std::array<std::pair<std::string, std::array<double, 2>>, 4> references{{
        {"s30", {4.404569871022636e-11, 4.026009739534826e-7}},
        {"s31", {1.761829022936136e-8, 1.6105177138623e-5}},
        {"s34", {0.004625184686117043, 0.04541711573412811}},
        {"s39", {0.009950165771675464, 0.09516257738142685}},
    }};

    for (const bool sparse : {false, true}) {
        DYNAMIC_SECTION("sparse=" << sparse) {
            engine::OdeOptions options;
            options.method = "cvode";
            options.tStart = 0.0;
            options.tEnd = 1.0;
            options.nSteps = 10;
            options.rtol = 1e-7;
            options.atol = 8e-14;
            options.sparse = sparse;

            const auto result = engine::OdeIntegrator(*model, network).integrate(options);

            REQUIRE(result.timePoints.size() == options.nSteps + 1);
            REQUIRE(result.concentrations.size() == result.timePoints.size());
            REQUIRE(result.timePoints.front() == options.tStart);
            REQUIRE(result.timePoints.back() == options.tEnd);
            for (const auto& row : result.concentrations) {
                REQUIRE(row.size() == network.species.size());
                for (const double value : row) {
                    CHECK(std::isfinite(value));
                }
            }
            for (const auto& [id, expected] : references) {
                const auto index = speciesIndex(id);
                REQUIRE(index < network.species.size());
                CHECK(result.concentrations.front()[index] == 0.0);
                for (const std::size_t sample : {1u, 10u}) {
                    const double actual = result.concentrations[sample][index];
                    const double tolerance = std::max(
                        5e-12, 1e-5 * std::abs(expected[sample == 1 ? 0 : 1]));
                    CHECK(std::abs(actual - expected[sample == 1 ? 0 : 1]) <=
                          tolerance);
                }
            }
        }
    }
}
