#include <algorithm>
#include <memory>
#include <catch2/catch_test_macros.hpp>
#include "NFcore.hh"
#include "NFinput_fromAst.hh"
#include "parser/BNGAstVisitor.hpp"
#include "nfsim_native_reader.hh"
#include "legacy_bridge.hh"
#include "engine.hh"

namespace {
std::unique_ptr<NFcore::System> systemFor(const std::string& rule) {
    auto model = bng::parser::parseModel(
        "begin molecule types\n A(s~U~P,b)\n B(a)\nend molecule types\n"
        "begin seed species\n A(s~U,b) 2\n B(a) 2\nend seed species\n"
        "begin reaction rules\n" + rule + "\nend reaction rules\n");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}
}

TEST_CASE("native NFcore2 reader preserves root state and transformation") {
    auto system = systemFor("flip: A(s~U)->A(s~P) 2");
    auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto& rule = snapshot.rules[0];
    CHECK(rule.base_rate == 2);
    CHECK_FALSE(rule.uses_connected_to);
    REQUIRE(rule.dependencies.size() >= 1);
    const auto state_dependency = std::find_if(
        rule.dependencies.begin(), rule.dependencies.end(), [](const auto& dependency) {
            return dependency.kind == NFcore2::NATIVE_STATE_REQUIRED;
        });
    REQUIRE(state_dependency != rule.dependencies.end());
    CHECK(state_dependency->state == 0);
    REQUIRE(rule.transforms.size() == 1);
    CHECK(rule.transforms[0].kind == NFcore2::NATIVE_STATE_CHANGE);
    CHECK(rule.transforms[0].new_value == 1);
}

TEST_CASE("native NFcore2 reader resolves both halves of a binding transform") {
    auto system = systemFor("bind: A(b)+B(a)->A(b!1).B(a!1) 3");
    auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto& rule = snapshot.rules[0];
    CHECK_FALSE(rule.uses_connected_to);
    REQUIRE(rule.dependencies.size() == 2);
    REQUIRE(rule.transforms.size() == 1);
    CHECK(rule.transforms[0].kind == NFcore2::NATIVE_BINDING);
    CHECK(rule.transforms[0].reactant != rule.transforms[0].other_reactant);
}

TEST_CASE("native NFcore2 reader rejects unresolved internal graph topology") {
    auto system = systemFor("flip: A(s~U,b!1).B(a!1)->A(s~P,b!1).B(a!1) 2");
    auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK(snapshot.rules[0].uses_connected_to);
}

TEST_CASE("native NFcore2 reader captures zero-reactant synthesis") {
    auto system = systemFor("birth: 0 -> B(a) 1");
    auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK_FALSE(snapshot.rules[0].uses_connected_to);
    REQUIRE(snapshot.rules[0].transforms.size() == 1);
    CHECK(snapshot.rules[0].transforms[0].kind == NFcore2::NATIVE_ADD);
    CHECK(snapshot.rules[0].transforms[0].added_molecule_type == 1);

    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    REQUIRE(lowered.supported_rule_count == 1);
    NFcore2::Engine engine(lowered.executable);
    NFcore2::MatchContext context;
    NFcore2::FeatureDelta delta;
    CHECK(engine.fire(lowered.rules[0].family, lowered.rules[0].member, context, delta));
    CHECK(engine.state().molecules(NFcore2::MoleculeTypeId(1)).liveCount() == 1);
}

TEST_CASE("native NFcore2 lowering executes the real state-rule adapter path") {
    auto system = systemFor("flip: A(s~U)->A(s~P) 2");
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    REQUIRE(lowered.rules.size() == 1);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    REQUIRE(lowered.executable.metadata().ruleFamilies().size() == 1);
    CHECK(lowered.executable.metadata().ruleFamilies()[0].members.size() == 1);

    NFcore2::SimulationState state(lowered.executable.metadata());
    const NFcore2::MoleculeHandle molecule =
        state.molecules(NFcore2::MoleculeTypeId(0)).create();
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(
        NFcore2::MoleculeTypeId(0), molecule));
    NFcore2::ScaffoldStore scaffolds;
    const auto& family = lowered.executable.metadata().ruleFamilies()[0];
    CHECK(lowered.executable.matchers().at(family.matcher).evaluate(
        state, scaffolds, context));
    NFcore2::FeatureDelta delta;
    lowered.executable.transforms().at(family.transform).execute(
        state, scaffolds, context, delta);
    CHECK(state.molecules(NFcore2::MoleculeTypeId(0)).stateWord(molecule, 0) == 1);
    REQUIRE(delta.changed.size() == 1);
    CHECK(delta.changed[0].value() == 0);
}

TEST_CASE("native NFcore2 lowering keeps unresolved topology on legacy fallback") {
    auto system = systemFor("flip: A(s~U,b!1).B(a!1)->A(s~P,b!1).B(a!1) 2");
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    REQUIRE(lowered.rules.size() == 1);
    CHECK(lowered.supported_rule_count == 0);
    CHECK(lowered.fallback_rule_count == 1);
    CHECK(lowered.rules[0].reason == NFcore2::LOWERING_CONNECTED_TO);
}

TEST_CASE("native NFcore2 lowering executes a reciprocal binding transform") {
    auto system = systemFor("bind: A(b)+B(a)->A(b!1).B(a!1) 3");
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    REQUIRE(lowered.supported_rule_count == 1);
    REQUIRE(lowered.executable.metadata().ruleFamilies().size() == 1);

    NFcore2::SimulationState state(lowered.executable.metadata());
    const NFcore2::MoleculeHandle a =
        state.molecules(NFcore2::MoleculeTypeId(0)).create();
    const NFcore2::MoleculeHandle b =
        state.molecules(NFcore2::MoleculeTypeId(1)).create();
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    context.setMoleculeAt(1, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(1), b));
    NFcore2::ScaffoldStore scaffolds;
    const auto& family = lowered.executable.metadata().ruleFamilies()[0];
    CHECK(lowered.executable.matchers().at(family.matcher).evaluate(
        state, scaffolds, context));
    NFcore2::FeatureDelta delta;
    lowered.executable.transforms().at(family.transform).execute(
        state, scaffolds, context, delta);
    CHECK(state.molecules(NFcore2::MoleculeTypeId(0)).bondRef(a, 1) ==
          NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(1), b));
    CHECK(state.molecules(NFcore2::MoleculeTypeId(1)).bondRef(b, 0) ==
          NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    REQUIRE(delta.changed.size() == 2);
    CHECK(delta.changed[0].value() == 3);
    CHECK(delta.changed[1].value() == 5);
}
