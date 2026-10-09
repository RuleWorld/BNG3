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
#include "ast/Observable.hpp"
#include "ast/ReactionRule.hpp"
#include "compile/CompiledModel.hpp"
#include "io/EnergyExportGuard.hpp"
#include "io/SbmlWriter.hpp"

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

std::string rejectionFor(const compile::CompiledModel& model) {
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
    CHECK(message ==
          "TestFormat export rejected model: energy patterns cannot be represented in this "
          "format. Energy-derived rates are only resolved by the .net writer and the NFsim "
          "backends; exporting here would silently change the model's kinetics.");
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
    CHECK(message ==
          "TestFormat export rejected model: an Arrhenius rate law on rule 'R1' cannot be "
          "represented in this format. Energy-derived rates are only resolved by the .net "
          "writer and the NFsim backends; exporting here would silently change the model's "
          "kinetics.");
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
    CHECK(rejectionFor(reverseOnly) ==
          "TestFormat export rejected model: an Arrhenius rate law on rule 'R1' cannot be "
          "represented in this format. Energy-derived rates are only resolved by the .net "
          "writer and the NFsim backends; exporting here would silently change the model's "
          "kinetics.");
}

TEST_CASE("barrier patterns are named ahead of accompanying energy patterns") {
    // The message should point at the construct the user wrote, not at a
    // downstream consequence of it.
    ast::Model model;
    model.addEnergyPattern(ast::EnergyPattern(
        "GU", "A(s~U)", ast::Expression::identifier("GU"), ast::SpeciesGraph {}));
    model.addBarrierPattern(ast::BarrierPattern(
        "slow", makeRule("B1", {ast::Expression::identifier("Gbar")})));
    auto driven = makeRule("R7", {arrhenius("Arrhenius")});
    driven.setDrivingWorkExpression(ast::Expression::identifier("muATP"));
    model.addReactionRule(std::move(driven));
    const auto message = rejectionFor(model);
    REQUIRE_FALSE(message.empty());
    CHECK(mentions(message, "barrier patterns"));
    CHECK(message ==
          "TestFormat export rejected model: barrier patterns cannot be represented in this "
          "format. Energy-derived rates are only resolved by the .net writer and the NFsim "
          "backends; exporting here would silently change the model's kinetics.");
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
    CHECK(message ==
          "TestFormat export rejected model: driven_by() reservoir work on rule 'R7' cannot "
          "be represented in this format. Energy-derived rates are only resolved by the .net "
          "writer and the NFsim backends; exporting here would silently change the model's "
          "kinetics.");
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

TEST_CASE("compiled export guard preserves top-level Arrhenius semantics") {
    ast::Model model;
    model.addReactionRule(makeRule(
        "R1", {ast::Expression::identifier("k1"), arrhenius("ARRHENIUS")}));
    const compile::CompiledModel compiled(model);

    CHECK(io::usesEnergySemantics(compiled));
    CHECK(rejectionFor(compiled) ==
          "TestFormat export rejected model: an Arrhenius rate law on rule 'R1' cannot be "
          "represented in this format. Energy-derived rates are only resolved by the .net "
          "writer and the NFsim backends; exporting here would silently change the model's "
          "kinetics.");
}

TEST_CASE("compiled export guard preserves driving-work and energy priority") {
    ast::Model driven;
    driven.addEnergyPattern(ast::EnergyPattern(
        "GU", "A(s~U)", ast::Expression::identifier("GU"), ast::SpeciesGraph {}));
    auto drivenRule = makeRule("R7", {arrhenius("Arrhenius")});
    drivenRule.setDrivingWorkExpression(ast::Expression::identifier("muATP"));
    driven.addReactionRule(std::move(drivenRule));
    const compile::CompiledModel compiledDriven(driven);
    CHECK(rejectionFor(compiledDriven) ==
          "TestFormat export rejected model: driven_by() reservoir work on rule 'R7' cannot "
          "be represented in this format. Energy-derived rates are only resolved by the .net "
          "writer and the NFsim backends; exporting here would silently change the model's "
          "kinetics.");

    ast::Model energy;
    energy.addEnergyPattern(ast::EnergyPattern(
        "GU", "A(s~U)", ast::Expression::identifier("GU"), ast::SpeciesGraph {}));
    energy.addReactionRule(makeRule("R1", {arrhenius("Arrhenius")}));
    const compile::CompiledModel compiledEnergy(energy);
    CHECK(rejectionFor(compiledEnergy) ==
          "TestFormat export rejected model: energy patterns cannot be represented in this "
          "format. Energy-derived rates are only resolved by the .net writer and the NFsim "
          "backends; exporting here would silently change the model's kinetics.");
}

TEST_CASE("a rate symbol named Arrhenius is not a top-level Arrhenius call") {
    ast::Model model;
    model.addReactionRule(makeRule(
        "R1", {ast::Expression::identifier("Arrhenius")}));
    const compile::CompiledModel compiled(model);

    CHECK_FALSE(io::usesEnergySemantics(compiled));
    CHECK(rejectionFor(compiled).empty());
}

TEST_CASE("an observable reference named Arrhenius is not the built-in rate law") {
    ast::Model model;
    model.addObservable(ast::Observable("Arrhenius", "Molecules", {"A"}));
    model.addReactionRule(makeRule(
        "R1", {ast::Expression::observableRef("Arrhenius", {})}));
    const compile::CompiledModel compiled(model);

    CHECK_FALSE(io::usesEnergySemantics(compiled));
    CHECK(rejectionFor(compiled).empty());
}

TEST_CASE("nested Arrhenius syntax is not a top-level energy rate law") {
    ast::Model model;
    model.addReactionRule(makeRule(
        "R1", {ast::Expression::binary("*", ast::Expression::number(2.0),
                                        arrhenius("Arrhenius"))}));
    const compile::CompiledModel compiled(model);

    CHECK_FALSE(io::usesEnergySemantics(compiled));
    CHECK(rejectionFor(compiled).empty());
}

TEST_CASE("the SBML writer refuses Arrhenius-only kinetics at the export boundary") {
    ast::Model model;
    model.addReactionRule(makeRule("R1", {arrhenius("Arrhenius")}));
    std::string message;
    try {
        (void)io::SbmlWriter::write(model, nullptr);
    } catch (const std::exception& error) {
        message = error.what();
    }

    CHECK(message ==
          "SBML export rejected model: an Arrhenius rate law on rule 'R1' cannot be "
          "represented in this format. Energy-derived rates are only resolved by the .net "
          "writer and the NFsim backends; exporting here would silently change the model's "
          "kinetics.");
}
