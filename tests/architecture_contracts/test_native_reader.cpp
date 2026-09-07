#include <algorithm>
#include <memory>
#include <catch2/catch_test_macros.hpp>
#include "NFcore.hh"
#include "NFinput_fromAst.hh"
#include "parser/BNGAstVisitor.hpp"
#include "nfsim_native_reader.hh"
#include "legacy_bridge.hh"

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

TEST_CASE("native NFcore2 reader does not treat synthesis as an empty supported rule") {
    auto system = systemFor("birth: 0 -> B(a) 1");
    auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK(snapshot.rules[0].uses_connected_to);
}
