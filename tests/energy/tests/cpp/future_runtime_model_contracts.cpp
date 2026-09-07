// RED CONTRACT: end-to-end generalized energy lowering through direct AST -> NFsim.
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <memory>
#include <numeric>
#include <sstream>
#include <string>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "NFcore/NFcore.hh"
#include "NFinput/NFinput_fromAst.hh"
#include "parser/BNGAstVisitor.hpp"

namespace fs = std::filesystem;

namespace {
class ScopedGeneralEnergy {
public:
    explicit ScopedGeneralEnergy(bool enabled) {
#ifdef _WIN32
        _putenv_s("BNG_NFSIM_GENERAL_ENERGY", enabled ? "1" : "");
#else
        if (enabled) setenv("BNG_NFSIM_GENERAL_ENERGY", "1", 1);
        else unsetenv("BNG_NFSIM_GENERAL_ENERGY");
#endif
    }
    ~ScopedGeneralEnergy() {
#ifdef _WIN32
        _putenv_s("BNG_NFSIM_GENERAL_ENERGY", "");
#else
        unsetenv("BNG_NFSIM_GENERAL_ENERGY");
#endif
    }
};

std::string slurp(const fs::path& path) {
    std::ifstream in(path);
    REQUIRE(in.good());
    std::ostringstream s; s << in.rdbuf(); return s.str();
}

std::unique_ptr<NFcore::System> build(const fs::path& path, bool generalized) {
    ScopedGeneralEnergy mode(generalized);
    auto model = bng::parser::parseModel(slurp(path));
    REQUIRE(model);
    int suggested = -1;
    std::unique_ptr<NFcore::System> sys(NFinput::buildSystemFromAst(
        *model, false, -1, false, suggested, path));
    REQUIRE(sys);
    sys->setUniversalTraversalLimit(suggested);
    sys->seedRNG(424242);
    sys->prepareForSimulation();
    return sys;
}

double total_propensity(const NFcore::System& system) {
    double sum = 0.0;
    for (auto* r : system.getAllReactions()) sum += r->get_a();
    return sum;
}
}

TEST_CASE("generalized state-context lowering preserves initial total propensity") {
    const fs::path fixture = fs::path(BNG_ENERGY_FIXTURE_DIR) / "state_change_local_context.bngl";
    auto legacy = build(fixture, false);
    auto general = build(fixture, true);
    CHECK(total_propensity(*general) == Catch::Approx(total_propensity(*legacy)).epsilon(1e-12));
    CHECK(general->getAllReactions().size() <= legacy->getAllReactions().size());
}

TEST_CASE("reactant-1 binding context lowers without changing initial propensity") {
    const fs::path fixture = fs::path(BNG_ENERGY_FIXTURE_DIR) / "reactant1_state_context.bngl";
    auto legacy = build(fixture, false);
    auto general = build(fixture, true);
    CHECK(total_propensity(*general) == Catch::Approx(total_propensity(*legacy)).epsilon(1e-12));
}

TEST_CASE("mixed-reactant binding context lowers by category aggregation") {
    const fs::path fixture = fs::path(BNG_ENERGY_FIXTURE_DIR) / "mixed_reactant_state_context.bngl";
    auto legacy = build(fixture, false);
    auto general = build(fixture, true);
    CHECK(total_propensity(*general) == Catch::Approx(total_propensity(*legacy)).epsilon(1e-12));
    CHECK(general->getAllReactions().size() < legacy->getAllReactions().size());
}

TEST_CASE("correlated topology remains on materialized fallback") {
    const fs::path fixture = fs::path(BNG_ENERGY_FIXTURE_DIR) / "correlated_two_hop_fallback.bngl";
    auto legacy = build(fixture, false);
    auto general = build(fixture, true);
    CHECK(general->getAllReactions().size() == legacy->getAllReactions().size());
    CHECK(total_propensity(*general) == Catch::Approx(total_propensity(*legacy)).epsilon(1e-12));
}

TEST_CASE("same-type binding cannot corrupt orientation-sensitive context") {
    const fs::path fixture = fs::path(BNG_ENERGY_FIXTURE_DIR) / "same_type_binding.bngl";
    auto legacy = build(fixture, false);
    auto general = build(fixture, true);
    CHECK(total_propensity(*general) == Catch::Approx(total_propensity(*legacy)).epsilon(1e-12));
}

TEST_CASE("symmetric-site multiplicity is unchanged by generalized lowering") {
    const fs::path fixture = fs::path(BNG_ENERGY_FIXTURE_DIR) / "symmetric_sites.bngl";
    auto legacy = build(fixture, false);
    auto general = build(fixture, true);
    CHECK(total_propensity(*general) == Catch::Approx(total_propensity(*legacy)).epsilon(1e-12));
}
