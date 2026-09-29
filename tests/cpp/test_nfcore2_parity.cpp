#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "NFinput_fromAst.hh"
#include "NFcore.hh"
#include "parser/BNGAstVisitor.hpp"
#include "driver.hh"
#include "seed.hh"
#include "nfsim_native_reader.hh"

namespace {

const char* kReversibleBngl = R"(
begin molecule types
A()
B()
end molecule types
begin seed species
A() 20
end seed species
begin reaction rules
A() -> B() 2.0
B() -> A() 1.0
end reaction rules
)";

NFcore::System* buildSystem(bng::ast::Model& model) {
    int suggestedTraversalLimit = 0;
    return NFinput::buildSystemFromAst(
        model, false, 100, false, suggestedTraversalLimit);
}

int countOf(NFcore::System* system, const std::string& typeName) {
    NFcore::MoleculeType* mt = system->getMoleculeTypeByName(typeName);
    REQUIRE(mt != nullptr);
    return mt->getMoleculeCount();
}

std::uint64_t fireTotal(NFcore::System* system) {
    std::uint64_t total = 0;
    for (NFcore::ReactionClass* rxn : system->getAllReactions())
        total += static_cast<std::uint64_t>(rxn->getFireCounter());
    return total;
}

} // namespace

TEST_CASE("NFcore2 driver matches NFcore ensemble on reversible isomerization") {
    auto model = bng::parser::parseModel(kReversibleBngl);
    REQUIRE(model != nullptr);

    // Lower once from a representative system; the executable model is
    // immutable and shared across driver trajectories.
    std::unique_ptr<NFcore::System> proto(buildSystem(*model));
    REQUIRE(proto != nullptr);
    const NFcore2::NativeModelSnapshot snapshot =
        NFcore2::snapshotLegacyNFsim(*proto);
    const NFcore2::LegacyLoweringResult lowered =
        NFcore2::lowerLegacyNFsim(*proto);
    REQUIRE(lowered.fallback_rule_count == 0u);
    REQUIRE(lowered.rules.size() == snapshot.rules.size());

    std::vector<NFcore2::SsaMemberSignature> sigs;
    for (std::size_t i = 0; i < lowered.rules.size(); ++i) {
        REQUIRE(lowered.rules[i].supported());
        NFcore2::SsaMemberSignature sig;
        sig.family = lowered.rules[i].family;
        sig.member = lowered.rules[i].member;
        for (std::uint32_t t : snapshot.rules[i].reactant_types)
            sig.reactantTypes.push_back(NFcore2::MoleculeTypeId(t));
        sigs.push_back(sig);
    }

    const double tEnd = 10.0;
    const int runs = 60;
    double sumLegacyB = 0.0, sumDriverB = 0.0;
    double sumLegacyEvents = 0.0, sumDriverEvents = 0.0;

    for (int run = 0; run < runs; ++run) {
        // NFcore trajectory from a fresh system.
        std::unique_ptr<NFcore::System> legacy(buildSystem(*model));
        REQUIRE(legacy != nullptr);
        legacy->prepareForSimulation();
        legacy->seedRNG(static_cast<unsigned int>(5000 + run));
        legacy->stepTo(tEnd);
        const int legacyA = countOf(legacy.get(), "A");
        const int legacyB = countOf(legacy.get(), "B");
        REQUIRE(legacyA + legacyB == 20);
        sumLegacyB += legacyB;
        sumLegacyEvents += static_cast<double>(fireTotal(legacy.get()));

        // NFcore2 trajectory seeded from a fresh system's initial state.
        std::unique_ptr<NFcore::System> seed(buildSystem(*model));
        REQUIRE(seed != nullptr);
        NFcore2::SsaDriver driver(lowered.executable, sigs);
        NFcore2::seedStateFromSystem(*seed, snapshot, driver.state());
        NFcore2::SsaDriverOptions opts;
        opts.tEnd = tEnd;
        opts.seed = static_cast<std::uint64_t>(5000 + run);
        const NFcore2::SsaDriverResult result = driver.run(opts);
        const std::size_t driverA =
            driver.state().molecules(NFcore2::MoleculeTypeId(0)).liveCount();
        const std::size_t driverB =
            driver.state().molecules(NFcore2::MoleculeTypeId(1)).liveCount();
        REQUIRE(driverA + driverB == 20u);
        sumDriverB += static_cast<double>(driverB);
        sumDriverEvents += static_cast<double>(result.events);
    }

    const double meanLegacyB = sumLegacyB / runs;
    const double meanDriverB = sumDriverB / runs;
    // Both engines estimate equilibrium P(B) = 2/3 (20 particles -> 13.33).
    // Cross-engine tolerance spans several SEMs of either ensemble.
    CHECK_THAT(meanLegacyB, Catch::Matchers::WithinAbs(40.0 / 3.0, 0.8));
    CHECK_THAT(meanDriverB, Catch::Matchers::WithinAbs(40.0 / 3.0, 0.8));
    CHECK_THAT(meanDriverB, Catch::Matchers::WithinAbs(meanLegacyB, 0.8));

    const double meanLegacyEvents = sumLegacyEvents / runs;
    const double meanDriverEvents = sumDriverEvents / runs;
    CHECK(meanLegacyEvents > 0.0);
    CHECK_THAT(meanDriverEvents,
               Catch::Matchers::WithinRel(meanLegacyEvents, 0.2));
}
