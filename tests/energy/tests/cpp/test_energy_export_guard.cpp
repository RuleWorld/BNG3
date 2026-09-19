// Fail-closed guard for export formats that cannot represent eBNGL energy
// semantics.
//
// A generated network carries `Arrhenius(phi, Ea)` as the rate law text of
// every energy-derived reaction, and only the .net writer resolves those into
// numeric per-reaction rates. Every other kinetics exporter would emit a
// literal Arrhenius call or drop the energy contribution, so these models are
// refused rather than exported with changed kinetics.
#include <string>
#include <vector>

#include <catch2/catch_test_macros.hpp>

#include "ast/BarrierPattern.hpp"
#include "ast/EnergyPattern.hpp"
#include "ast/Expression.hpp"
#include "ast/Model.hpp"
#include "ast/ReactionRule.hpp"
#include "io/EnergyExportGuard.hpp"

using namespace bng;

namespace {

ast::ReactionRule makeRule(
    const std::string& name,
    const std::vector<ast::Expression>& rates) {
    return ast::ReactionRule(name, "", {"A(s~U)"}, {"A(s~P)"}, rates, {}, false, {},
                             {});
}

ast::Expression arrhenius(const std::string& spelling) {
    return ast::Expression::function(
        spelling,
        {ast::Expression::identifier("phi"), ast::Expression::identifier("Ea")});
}

// Returns the rejection message, or an empty string when the model is accepted.
std::string rejectionFor(const ast::Model& model) {
    try {
        io::requireNoEnergySemantics(model, "TestFormat");
    } catch (const std::exception& error) {
        return error.what();
    }
    return {};
}

bool mentions(const std::string& message, const std::string& fragment) {
    return message.find(fragment) != std::string::npos;
}

} // namespace

TEST_CASE("an ordinary kinetic model exports without complaint") {
    ast::Model model;
    model.addReactionRule(makeRule("R1", {ast::Expression::identifier("k1")}));
    CHECK_FALSE(io::usesEnergySemantics(model));
    CHECK(rejectionFor(model).empty());
}

TEST_CASE("an empty model exports without complaint") {
    const ast::Model model;
    CHECK_FALSE(io::usesEnergySemantics(model));
    CHECK(rejectionFor(model).empty());
}

TEST_CASE("energy patterns are refused and the format is named") {
    ast::Model model;
    model.addEnergyPattern(ast::EnergyPattern(
        "GU", "A(s~U)", ast::Expression::identifier("GU"), ast::SpeciesGraph {}));
    CHECK(io::usesEnergySemantics(model));
    const auto message = rejectionFor(model);
    REQUIRE_FALSE(message.empty());
    CHECK(mentions(message, "energy patterns"));
    CHECK(mentions(message, "TestFormat"));
}

TEST_CASE("an Arrhenius rate law is refused even without energy patterns") {
    // The rate law itself is inexpressible, so this must not depend on the
    // energy patterns still being present in the model.
    ast::Model model;
    model.addReactionRule(makeRule("R1", {arrhenius("Arrhenius")}));
    const auto message = rejectionFor(model);
    REQUIRE_FALSE(message.empty());
    CHECK(mentions(message, "Arrhenius"));
    CHECK(mentions(message, "R1"));
}

TEST_CASE("Arrhenius detection is case-insensitive and checks every rate") {
    // Matches the spelling NetWriter's parseArrhenius accepts.
    ast::Model lowercase;
    lowercase.addReactionRule(makeRule("R1", {arrhenius("arrhenius")}));
    CHECK_FALSE(rejectionFor(lowercase).empty());

    // A reverse-direction Arrhenius in the second rate slot still counts.
    ast::Model reverseOnly;
    reverseOnly.addReactionRule(makeRule(
        "R1", {ast::Expression::identifier("k1"), arrhenius("Arrhenius")}));
    CHECK_FALSE(rejectionFor(reverseOnly).empty());
}

TEST_CASE("barrier patterns are named ahead of accompanying energy patterns") {
    // The message should point at the construct the user wrote, not at a
    // downstream consequence of it.
    ast::Model model;
    model.addEnergyPattern(ast::EnergyPattern(
        "GU", "A(s~U)", ast::Expression::identifier("GU"), ast::SpeciesGraph {}));
    model.addBarrierPattern(ast::BarrierPattern(
        "slow", makeRule("B1", {ast::Expression::identifier("Gbar")})));
    const auto message = rejectionFor(model);
    REQUIRE_FALSE(message.empty());
    CHECK(mentions(message, "barrier patterns"));
}

TEST_CASE("reservoir work is refused and the offending rule is named") {
    ast::Model model;
    auto rule = makeRule("R7", {ast::Expression::identifier("k1")});
    rule.setDrivingWorkExpression(ast::Expression::identifier("muATP"));
    model.addReactionRule(std::move(rule));
    const auto message = rejectionFor(model);
    REQUIRE_FALSE(message.empty());
    CHECK(mentions(message, "driven_by"));
    CHECK(mentions(message, "R7"));
}

TEST_CASE("an unrelated function rate law is not energy semantics") {
    // The guard must not overreach into ordinary rate-law families.
    ast::Model model;
    model.addReactionRule(makeRule(
        "R1", {ast::Expression::function("Sat",
                                         {ast::Expression::identifier("k"),
                                          ast::Expression::identifier("K")})}));
    CHECK_FALSE(io::usesEnergySemantics(model));
    CHECK(rejectionFor(model).empty());
}
