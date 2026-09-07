#include <algorithm>
#include <cmath>
#include <cstdint>
#include <random>
#include <vector>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "compile/energy/EnergyDeltaPlan.hpp"
#include "energy_test_helpers.hpp"

TEST_CASE("randomized EnergyDeltaPlan agrees with literal conjunction oracle") {
    using namespace bng::compile::energy;
    auto rng = bng3_test::deterministic_rng();
    std::uniform_real_distribution<double> energy(-5.0, 5.0);
    std::uniform_real_distribution<double> phi_dist(0.0, 1.0);
    std::uniform_int_distribution<int> ncond_dist(1, 8);
    std::uniform_int_distribution<int> nterm_dist(1, 24);

    for (int trial = 0; trial < 10000; ++trial) {
        const int ncond = ncond_dist(rng);
        std::vector<EnergyCondition> conditions;
        for (int i = 0; i < ncond; ++i) {
            EnergyCondition c;
            c.kind = (i % 2 == 0) ? ConditionKind::Bond : ConditionKind::State;
            c.reactantIndex = i % 2;
            c.moleculeType = (i % 2 == 0) ? "A" : "B";
            c.componentName = "s" + std::to_string(i);
            c.expectedBound = (i % 3 != 0);
            c.expectedState = (i % 2 == 0) ? "" : ((i % 3 == 0) ? "P" : "U");
            conditions.push_back(c);
        }

        const std::uint64_t valid = (std::uint64_t{1} << ncond) - 1;
        std::vector<EnergyTerm> terms;
        std::vector<std::pair<double, std::uint64_t>> literal;
        const int nterm = nterm_dist(rng);
        std::uniform_int_distribution<std::uint64_t> mask_dist(1, valid);
        for (int i = 0; i < nterm; ++i) {
            const double e = energy(rng);
            const std::uint64_t mask = mask_dist(rng);
            terms.push_back({e, mask, static_cast<std::size_t>(i)});
            literal.push_back({e, mask});
        }

        const double base = energy(rng);
        auto plan = EnergyDeltaPlan::factorized(base, conditions, terms);
        REQUIRE(plan.has_value());
        const double phi = phi_dist(rng);
        const double rt = 0.25 + std::fabs(energy(rng));

        for (std::uint64_t mask = 0; mask <= valid; ++mask) {
            const double expected = bng3_test::literal_delta_g(base, mask, literal);
            REQUIRE(plan->tryDeltaG(mask).has_value());
            CHECK(*plan->tryDeltaG(mask) == Catch::Approx(expected).margin(1e-12));
            CHECK(*plan->tryArrheniusFactor(mask, phi, rt, true) ==
                  Catch::Approx(bng3_test::arrhenius_factor(expected, phi, rt, true)).epsilon(1e-12));
            CHECK(*plan->tryArrheniusFactor(mask, phi, rt, false) ==
                  Catch::Approx(bng3_test::arrhenius_factor(expected, phi, rt, false)).epsilon(1e-12));
        }
    }
}
