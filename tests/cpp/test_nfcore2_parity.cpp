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

struct DriverCase {
    std::unique_ptr<NFcore::System> system;
    NFcore2::NativeModelSnapshot snapshot;
    std::unique_ptr<NFcore2::LegacyLoweringResult> lowered;
    std::vector<NFcore2::SsaMemberSignature> signatures;
    std::unique_ptr<NFcore2::SsaDriver> driver;
};

std::unique_ptr<DriverCase> makeDriverCase(bng::ast::Model& model) {
    auto result = std::make_unique<DriverCase>();
    result->system.reset(buildSystem(model));
    REQUIRE(result->system != nullptr);
    result->snapshot = NFcore2::snapshotLegacyNFsim(*result->system);
    result->lowered = std::make_unique<NFcore2::LegacyLoweringResult>(
        NFcore2::lowerLegacyNFsim(*result->system));
    REQUIRE(result->lowered->fallback_rule_count == 0u);
    REQUIRE(result->lowered->rules.size() == result->snapshot.rules.size());
    for (std::size_t i = 0; i < result->lowered->rules.size(); ++i) {
        REQUIRE(result->lowered->rules[i].supported());
        NFcore2::SsaMemberSignature sig;
        sig.family = result->lowered->rules[i].family;
        sig.member = result->lowered->rules[i].member;
        for (std::uint32_t type : result->snapshot.rules[i].reactant_types)
            sig.reactantTypes.push_back(NFcore2::MoleculeTypeId(type));
        result->signatures.push_back(sig);
    }
    result->driver = std::make_unique<NFcore2::SsaDriver>(
        result->lowered->executable, result->signatures);
    NFcore2::seedStateFromSystem(*result->system, result->snapshot,
                                result->driver->state());
    return result;
}

NFcore2::MoleculeTypeId moleculeType(const DriverCase& c,
                                     const std::string& name) {
    for (std::size_t i = 0; i < c.snapshot.molecule_types.size(); ++i)
        if (c.snapshot.molecule_types[i].name == name)
            return NFcore2::MoleculeTypeId(static_cast<std::uint32_t>(i));
    throw std::runtime_error("unknown molecule type: " + name);
}

std::size_t liveInCompartment(const DriverCase& c,
                              NFcore2::MoleculeTypeId type,
                              const std::string& compartment) {
    const NFcore2::MoleculeStore& store = c.driver->state().molecules(type);
    const std::uint32_t id = NFcore2::nativeCompartmentId(compartment);
    std::size_t count = 0;
    for (NFcore2::MoleculeHandle handle : store.liveHandles())
        if (store.compartment(handle) == id) ++count;
    return count;
}

std::size_t bondedMolecules(const DriverCase& c,
                            NFcore2::MoleculeTypeId type) {
    const NFcore2::MoleculeStore& store = c.driver->state().molecules(type);
    std::size_t count = 0;
    for (NFcore2::MoleculeHandle handle : store.liveHandles())
        for (std::uint16_t slot = 0; slot < store.bondSlotCount(); ++slot)
            if (store.bondRef(handle, slot).valid()) { ++count; break; }
    return count;
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

TEST_CASE("NFcore2 creates products in the reaction compartment") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 10.0
end parameters
begin compartments
    EC 3 1.0
    PM 2 1.0 EC
    CP 3 1.0 PM
end compartments
begin molecule types
    A()
    C()
end molecule types
begin seed species
    A()@EC 10
    A()@PM 10
    A()@CP 10
end seed species
begin reaction rules
    synth: A() -> A() + C() k
end reaction rules
)");
    REQUIRE(model != nullptr);
    auto c = makeDriverCase(*model);
    NFcore2::SsaDriverOptions options;
    options.tEnd = 10.0;
    options.seed = 123;
    c->driver->run(options);
    const NFcore2::MoleculeTypeId type = moleculeType(*c, "C");
    CHECK(liveInCompartment(*c, type, "EC") > 0);
    CHECK(liveInCompartment(*c, type, "PM") > 0);
    CHECK(liveInCompartment(*c, type, "CP") > 0);
}

TEST_CASE("NFcore2 seeds molecule compartments over the species compartment") {
    auto model = bng::parser::parseModel(R"(
begin compartments
    EC 3 1.0
    PM 2 1.0 EC
end compartments
begin molecule types
    L(r)
    R(l)
end molecule types
begin seed species
    L(r!1)@EC.R(l!1)@PM 4
end seed species
)");
    REQUIRE(model != nullptr);
    auto c = makeDriverCase(*model);
    CHECK(liveInCompartment(*c, moleculeType(*c, "L"), "EC") == 4u);
    CHECK(liveInCompartment(*c, moleculeType(*c, "R"), "PM") == 4u);
}

TEST_CASE("NFcore2 MoveConnected moves only the primary compartment") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin compartments
    c1 3 1.0
    c2 3 1.0
end compartments
begin molecule types
    A(site)
    B(site)
end molecule types
begin seed species
    A(site!1)@c1.B(site!1)@c1 1
end seed species
begin reaction rules
    A(site!1)@c1.B(site!1)@c1 -> A(site!1)@c2.B(site!1)@c1 k MoveConnected
end reaction rules
)");
    REQUIRE(model != nullptr);
    auto c = makeDriverCase(*model);
    NFcore2::SsaDriverOptions options;
    options.tEnd = 10.0;
    options.seed = 17;
    c->driver->run(options);
    CHECK(liveInCompartment(*c, moleculeType(*c, "A"), "c2") == 1u);
    CHECK(liveInCompartment(*c, moleculeType(*c, "B"), "c1") == 1u);
}

TEST_CASE("NFcore2 binds only compartment-compatible reactants") {
    const auto bound = [](const std::string& bCompartment) {
        auto model = bng::parser::parseModel("\n"
            "begin parameters\n k 1.0\nend parameters\n"
            "begin compartments\n EC 3 1.0\n PM 2 1.0 EC\n CP 3 1.0 PM\nend compartments\n"
            "begin molecule types\n A(b)\n B(a)\nend molecule types\n"
            "begin seed species\n A(b)@EC 10\n B(a)@" + bCompartment + " 10\nend seed species\n"
            "begin reaction rules\n bind: A(b) + B(a) -> A(b!1).B(a!1) k\nend reaction rules\n");
        REQUIRE(model != nullptr);
        auto c = makeDriverCase(*model);
        NFcore2::SsaDriverOptions options;
        options.tEnd = 1.0;
        options.seed = 7;
        c->driver->run(options);
        return bondedMolecules(*c, moleculeType(*c, "A"));
    };
    CHECK(bound("PM") > 0u); // directly adjacent surface/volume pair
    CHECK(bound("CP") == 0u); // separated by PM
}

TEST_CASE("NFcore2 honors explicit product compartments") {
    auto model = bng::parser::parseModel(R"(
begin parameters
    k 1.0
end parameters
begin compartments
    c1 3 1.0
    c2 3 1.0
end compartments
begin molecule types
    A()
    C()
end molecule types
begin seed species
    A()@c1 10
end seed species
begin reaction rules
    synth: A()@c1 -> A()@c1 + C()@c2 k
end reaction rules
)");
    REQUIRE(model != nullptr);
    auto c = makeDriverCase(*model);
    NFcore2::SsaDriverOptions options;
    options.tEnd = 10.0;
    options.seed = 123;
    c->driver->run(options);
    const NFcore2::MoleculeTypeId type = moleculeType(*c, "C");
    CHECK(liveInCompartment(*c, type, "c1") == 0u);
    CHECK(liveInCompartment(*c, type, "c2") > 0u);
}
