// Barrier reaction-center keying and the shared driven-Arrhenius rate math.
#include <cmath>
#include <cstdlib>
#include <string>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "compile/energy/BarrierTable.hpp"
#include "compile/energy/DrivenEnergy.hpp"
#include "compile/energy/ThermodynamicConstraints.hpp"

using namespace bng::compile::energy;

TEST_CASE("a barrier key is symmetric under reversal") {
    // Forward and reverse traversals cross the same transition state, so they
    // must resolve to one key rather than two.
    CHECK(ReactionCenterKey::stateChange("A", "s", "U", "P") ==
          ReactionCenterKey::stateChange("A", "s", "P", "U"));
    CHECK(ReactionCenterKey::binding("A", "x", "B", "y") ==
          ReactionCenterKey::binding("B", "y", "A", "x"));
}

TEST_CASE("binding and state-change centers never collide") {
    CHECK_FALSE(ReactionCenterKey::binding("A", "s", "A", "s") ==
                ReactionCenterKey::stateChange("A", "s", "U", "P"));
}

TEST_CASE("distinct components and states stay distinct") {
    CHECK_FALSE(ReactionCenterKey::stateChange("A", "s", "U", "P") ==
                ReactionCenterKey::stateChange("A", "t", "U", "P"));
    CHECK_FALSE(ReactionCenterKey::stateChange("A", "s", "U", "P") ==
                ReactionCenterKey::stateChange("A", "s", "U", "Q"));
    CHECK_FALSE(ReactionCenterKey::binding("A", "x", "B", "y") ==
                ReactionCenterKey::binding("A", "x", "B", "z"));
}

TEST_CASE("barrier contributions accumulate and absent centers are neutral") {
    BarrierTable table;
    std::string diagnostic;
    const auto key = ReactionCenterKey::stateChange("A", "s", "U", "P");

    CHECK(table.empty());
    // Zero is the correct neutral element: exp(-(Ea + 0)/RT) is unmodified.
    CHECK(table.lookup(key) == 0.0);

    REQUIRE(table.add(key, 2.0, "Gbar1", diagnostic));
    REQUIRE(table.add(ReactionCenterKey::stateChange("A", "s", "P", "U"), 0.5,
                      "Gbar2", diagnostic));
    CHECK(table.size() == 1);
    CHECK(table.lookup(key) == Catch::Approx(2.5));

    const auto* entry = table.find(key);
    REQUIRE(entry != nullptr);
    CHECK(entry->contributingPatterns == 2);
    REQUIRE(entry->sources.size() == 2);
    CHECK(entry->sources[0] == "Gbar1");
}

TEST_CASE("a non-finite barrier is rejected rather than dropped") {
    BarrierTable table;
    std::string diagnostic;
    const auto key = ReactionCenterKey::stateChange("A", "s", "U", "P");
    CHECK_FALSE(table.add(key, std::nan(""), "bad", diagnostic));
    CHECK_FALSE(diagnostic.empty());
    CHECK_FALSE(table.add(key, INFINITY, "bad", diagnostic));
}

TEST_CASE("a negative barrier is legal catalysis") {
    BarrierTable table;
    std::string diagnostic;
    const auto key = ReactionCenterKey::binding("A", "x", "B", "y");
    REQUIRE(table.add(key, -1.5, "catalyst", diagnostic));
    CHECK(table.lookup(key) == Catch::Approx(-1.5));
}

TEST_CASE("canonical keys round-trip through their printable form") {
    const ReactionCenterKey keys[] = {
        ReactionCenterKey::binding("A", "x", "B", "y"),
        ReactionCenterKey::binding("A", "x", "A", "x"),
        ReactionCenterKey::stateChange("A", "s", "U", "P"),
        ReactionCenterKey::stateChange("Rec", "Y1", "0", "2P"),
    };
    for (const auto& key : keys) {
        ReactionCenterKey parsed;
        REQUIRE(ReactionCenterKey::parse(key.toString(), parsed));
        CHECK(parsed == key);
        CHECK(parsed.toString() == key.toString());
    }
}

TEST_CASE("a malformed key is rejected rather than guessed at") {
    const char* malformed[] = {
        "", "bond", "bond:", "bond:A.x", "bond:A.x|", "bond:|A.x",
        "weird:A.x|B.y", "bond:Ax|B.y", "state:A.s|A.s",
        "state:A.s~U|B.s~P",  // mismatched molecule type
        "state:A.s~U|A.t~P",  // mismatched component
        "bond:A.x|B.y|C.z",   // too many halves
        "bond:B.y|A.x",       // non-canonical half order
        "state:A.s~U|A.s~P",  // non-canonical state order
    };
    ReactionCenterKey key;
    for (const char* text : malformed) {
        CHECK_FALSE(ReactionCenterKey::parse(text, key));
    }
}

TEST_CASE("the shared rate helper agrees with ThermodynamicRate") {
    const double Ea = 1.0;
    const double barrier = 0.7;
    const double deltaG = 2.0;
    const double work = 0.4;
    const double phi = 0.35;
    const double RT = 1.7;

    ThermodynamicRate rate;
    rate.activationBarrier = Ea;
    rate.barrierModifier = barrier;
    rate.stateDeltaG = deltaG;
    rate.reservoirWork = work;
    rate.phi = phi;
    rate.RT = RT;
    const auto pair = rate.rates();

    CHECK(drivenArrheniusRate(Ea, barrier, deltaG, work, phi, RT, true) ==
          Catch::Approx(pair.forward));
    CHECK(drivenArrheniusRate(Ea, barrier, deltaG, work, phi, RT, false) ==
          Catch::Approx(pair.reverse));
}

TEST_CASE("a barrier cancels in the rate ratio but reservoir work does not") {
    const double Ea = 1.0;
    const double deltaG = 2.0;
    const double phi = 0.35;
    const double RT = 1.7;
    const auto ratio = [&](double barrier, double work) {
        return drivenArrheniusRate(Ea, barrier, deltaG, work, phi, RT, true) /
               drivenArrheniusRate(Ea, barrier, deltaG, work, phi, RT, false);
    };

    CHECK(ratio(0.0, 0.4) == Catch::Approx(ratio(5.0, 0.4)));
    CHECK(ratio(0.0, 0.4) == Catch::Approx(std::exp(-(deltaG - 0.4) / RT)));
    // With no drive the original eBNGL detailed balance is recovered exactly.
    CHECK(ratio(0.0, 0.0) == Catch::Approx(std::exp(-deltaG / RT)));
}

TEST_CASE("reservoir work is antisymmetric under traversal direction") {
    CHECK(directedWork(1.5, true) == Catch::Approx(1.5));
    CHECK(directedWork(1.5, false) == Catch::Approx(-1.5));
}

TEST_CASE("the general-energy gate defaults off and honours an explicit zero") {
#ifndef _WIN32
    unsetenv("BNG_NFSIM_GENERAL_ENERGY");
    CHECK_FALSE(generalEnergyEnabled());
    setenv("BNG_NFSIM_GENERAL_ENERGY", "0", 1);
    CHECK_FALSE(generalEnergyEnabled());
    setenv("BNG_NFSIM_GENERAL_ENERGY", "1", 1);
    CHECK(generalEnergyEnabled());
    unsetenv("BNG_NFSIM_GENERAL_ENERGY");
    CHECK_FALSE(generalEnergyEnabled());
#endif
    CHECK(std::string(generalEnergyGateName()) == "BNG_NFSIM_GENERAL_ENERGY");
}

TEST_CASE("folding a barrier into the compact base rate is exact") {
    // The compact NFsim path multiplies a constant base rate by a per-mapping
    // context factor supplied by EnergyRxnClass. A barrier is direction- and
    // context-independent, so folding it into the base rate must reproduce the
    // materialized rate exactly. That equality is what licenses keeping
    // barrier-only rules on the compact path while driven rules fall back to
    // the materialized Sekar expansion.
    const double RT = 1.9;
    const double phi = 0.3;
    const double activationEnergy = 0.8;

    for (const double barrier : {0.0, 2.5, -1.25}) {
        const double baseRate = std::exp(-(activationEnergy + barrier) / RT);
        for (const double deltaG : {-2.0, 0.0, 1.75}) {
            const double forwardContext = std::exp(-phi * deltaG / RT);
            const double reverseContext = std::exp(-(phi - 1.0) * deltaG / RT);
            CHECK(baseRate * forwardContext ==
                  Catch::Approx(drivenArrheniusRate(
                      activationEnergy, barrier, deltaG, 0.0, phi, RT, true)));
            CHECK(baseRate * reverseContext ==
                  Catch::Approx(drivenArrheniusRate(
                      activationEnergy, barrier, deltaG, 0.0, phi, RT, false)));
        }
    }
    // With no barrier the folded base rate is bit-identical to the original.
    CHECK(std::exp(-(activationEnergy + 0.0) / RT) ==
          std::exp(-activationEnergy / RT));
}
