// Post-parse lowering of the synthetic thermodynamic metadata, plus the
// cross-convention equivalence of the two Arrhenius rate paths.
//
// Both are exercised here without going through a full parse: the lowering
// takes an injected expression parser, and the rate helpers are pure. That
// keeps the failure signal pointed at the lowering rules rather than at the
// grammar.
#include <cmath>
#include <functional>
#include <memory>
#include <map>
#include <string>
#include <vector>

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include "ast/Expression.hpp"
#include "ast/Model.hpp"
#include "ast/ReactionRule.hpp"
#include "compile/energy/DrivenEnergy.hpp"
#include "parser/ThermoModelFinalize.hpp"

using namespace bng;
using namespace bng::compile::energy;

namespace {

// Stand-in for the generated parser: identifiers suffice for these cases, and
// a sentinel lets the unparseable path be exercised.
ast::Expression fakeParse(const std::string& text) {
    if (text == "!bad") throw std::runtime_error("synthetic parse failure");
    return ast::Expression::identifier(text);
}

ast::ReactionRule makeRule(
    const std::string& name,
    const std::string& label,
    const std::vector<ast::Expression>& rates) {
    return ast::ReactionRule(name, label, {"A(s~U)"}, {"A(s~P)"}, rates, {}, false,
                             {}, {});
}

bool rejects(const std::function<void()>& action) {
    try {
        action();
    } catch (const std::exception&) {
        return true;
    }
    return false;
}

} // namespace

TEST_CASE("an ordinary model is left untouched by finalization") {
    ast::Model model;
    model.addReactionRule(makeRule("R1", "", {ast::Expression::number(1.0)}));
    model.addReactionRule(makeRule("R2", "myrule:", {ast::Expression::number(2.0)}));

    CHECK_FALSE(parser::finalizeThermodynamicMetadata(model, {}, {}, fakeParse));
    CHECK(model.getBarrierPatterns().empty());
    REQUIRE(model.getReactionRules().size() == 2);
    // No renumbering and no relabelling for a model that used neither feature.
    CHECK(model.getReactionRules()[1].getRuleName() == "R2");
    CHECK(model.getReactionRules()[1].getLabel() == "myrule:");
    CHECK_FALSE(model.getReactionRules()[0].hasDrivingWork());
}

TEST_CASE("barrier rules leave the rule list and survivors are renumbered") {
    ast::Model model;
    // Barrier first in source order: without renumbering the surviving
    // ordinary rule would keep the name R2.
    model.addReactionRule(
        makeRule("R1", "__bng3_barrier_0:", {ast::Expression::identifier("Gbar")}));
    model.addReactionRule(makeRule("R2", "", {ast::Expression::identifier("k1")}));

    CHECK(parser::finalizeThermodynamicMetadata(model, {}, {}, fakeParse));
    REQUIRE(model.getBarrierPatterns().size() == 1);
    REQUIRE(model.getReactionRules().size() == 1);
    CHECK(model.getReactionRules()[0].getRuleName() == "R1");
    CHECK(model.getBarrierPatterns()[0].expression().toString() == "Gbar");
    CHECK(model.getBarrierPatterns()[0].transition().getRuleName() == "B1");
}

TEST_CASE("barrier patterns are ordered by index and keep their labels") {
    ast::Model model;
    // Added out of index order to show the sort is by barrier index, not by
    // position in the rule list.
    model.addReactionRule(
        makeRule("R1", "__bng3_barrier_1:", {ast::Expression::identifier("Gb")}));
    model.addReactionRule(
        makeRule("R2", "__bng3_barrier_0:", {ast::Expression::identifier("Ga")}));

    parser::finalizeThermodynamicMetadata(model, {{0, "slow"}, {1, "fast"}}, {},
                                          fakeParse);
    CHECK(model.getReactionRules().empty());
    REQUIRE(model.getBarrierPatterns().size() == 2);
    CHECK(model.getBarrierPatterns()[0].getLabel() == "slow");
    CHECK(model.getBarrierPatterns()[0].expression().toString() == "Ga");
    CHECK(model.getBarrierPatterns()[1].getLabel() == "fast");
}

TEST_CASE("driving work is indexed over ordinary rules only") {
    ast::Model model;
    // A barrier rule sits between the two ordinary rules. Work index 1 must
    // land on the second ORDINARY rule, not on the third rule overall.
    model.addReactionRule(makeRule("R1", "", {ast::Expression::identifier("k1")}));
    model.addReactionRule(
        makeRule("R2", "__bng3_barrier_0:", {ast::Expression::identifier("Gbar")}));
    model.addReactionRule(makeRule("R3", "", {ast::Expression::identifier("k2")}));

    parser::finalizeThermodynamicMetadata(model, {}, {{1, "muATP"}}, fakeParse);
    REQUIRE(model.getReactionRules().size() == 2);
    CHECK_FALSE(model.getReactionRules()[0].hasDrivingWork());
    CHECK(model.getReactionRules()[1].hasDrivingWork());
    CHECK(model.getReactionRules()[1].drivingWorkExpression().toString() == "muATP");
    CHECK(model.getReactionRules()[0].getRuleName() == "R1");
    CHECK(model.getReactionRules()[1].getRuleName() == "R2");
}

TEST_CASE("absent driving work reads as the neutral zero") {
    ast::Model model;
    model.addReactionRule(makeRule("R1", "", {ast::Expression::identifier("k1")}));
    model.addReactionRule(
        makeRule("R2", "__bng3_barrier_0:", {ast::Expression::identifier("G")}));
    parser::finalizeThermodynamicMetadata(model, {}, {}, fakeParse);
    CHECK_FALSE(model.getReactionRules()[0].hasDrivingWork());
    // dG - 0 recovers the undriven rate, so a backend that ignores the flag is
    // still numerically correct.
    CHECK(model.getReactionRules()[0].drivingWorkExpression().toString() == "0");
}

TEST_CASE("inconsistent thermodynamic metadata fails closed") {
    const auto withRules =
        [](const std::vector<std::pair<std::string, std::vector<ast::Expression>>>& rules) {
            auto model = std::make_unique<ast::Model>();
            int index = 0;
            for (const auto& [label, rates] : rules) {
                model->addReactionRule(
                    makeRule("R" + std::to_string(++index), label, rates));
            }
            return model;
        };
    const ast::Expression energy = ast::Expression::identifier("G");

    // A work index past the end of the ordinary rules.
    auto a = withRules({{"__bng3_barrier_0:", {energy}}});
    CHECK(rejects([&] {
        parser::finalizeThermodynamicMetadata(*a, {}, {{0, "w"}}, fakeParse);
    }));

    // Two barrier rules claiming the same index.
    auto b = withRules({{"__bng3_barrier_0:", {energy}}, {"__bng3_barrier_0:", {energy}}});
    CHECK(rejects(
        [&] { parser::finalizeThermodynamicMetadata(*b, {}, {}, fakeParse); }));

    // A barrier with no energy: silently a no-op otherwise.
    auto c = withRules({{"__bng3_barrier_0:", {}}});
    CHECK(rejects(
        [&] { parser::finalizeThermodynamicMetadata(*c, {}, {}, fakeParse); }));

    // A barrier with a rate pair: meaningless for a symmetric transition state.
    auto d = withRules({{"__bng3_barrier_0:", {energy, energy}}});
    CHECK(rejects(
        [&] { parser::finalizeThermodynamicMetadata(*d, {}, {}, fakeParse); }));

    // The `__bng3_barrier_` namespace is reserved, so a malformed index in it
    // is an error rather than an ordinary rule with an odd name.
    auto e = withRules({{"__bng3_barrier_x:", {energy}}});
    CHECK(rejects(
        [&] { parser::finalizeThermodynamicMetadata(*e, {}, {}, fakeParse); }));
    auto f = withRules({{"__bng3_barrier_:", {energy}}});
    CHECK(rejects(
        [&] { parser::finalizeThermodynamicMetadata(*f, {}, {}, fakeParse); }));

    // A label annotation with no matching barrier rule means metadata was lost.
    auto g = withRules({{"__bng3_barrier_0:", {energy}}});
    CHECK(rejects([&] {
        parser::finalizeThermodynamicMetadata(*g, {{7, "ghost"}}, {}, fakeParse);
    }));

    // An unparseable work expression is reported, not swallowed.
    auto h = withRules({{"", {energy}}, {"__bng3_barrier_0:", {energy}}});
    CHECK(rejects([&] {
        parser::finalizeThermodynamicMetadata(*h, {}, {{0, "!bad"}}, fakeParse);
    }));
}

TEST_CASE("the NFsim and network energy conventions describe the same kinetics") {
    // NFsim divides by an explicit RT and hands both directions the forward dG
    // and forward W, differing only via phi vs (phi - 1).
    //
    // The network path folds RT into the parameters (so RT == 1) and builds
    // each direction as its own reaction, whose dG is already negated and whose
    // phi is already (1 - phi). Work must therefore be negated there.
    //
    // This sweep is the guard against a sign error between the two.
    const double activationEnergy = 1.3;
    for (const double phi : {0.0, 0.25, 0.5, 0.75, 1.0}) {
        for (const double deltaG : {-3.0, -0.5, 0.0, 1.0, 2.5}) {
            for (const double work : {-1.5, 0.0, 0.4, 2.0}) {
                for (const double barrier : {-1.0, 0.0, 3.0}) {
                    const double nfsimForward = drivenArrheniusRate(
                        activationEnergy, barrier, deltaG, work, phi, 1.0, true);
                    const double nfsimReverse = drivenArrheniusRate(
                        activationEnergy, barrier, deltaG, work, phi, 1.0, false);

                    const double networkForward = networkArrheniusRate(
                        activationEnergy, barrier, deltaG, work, phi, false);
                    const double networkReverse = networkArrheniusRate(
                        activationEnergy, barrier, -deltaG, work, 1.0 - phi, true);

                    CHECK(networkForward == Catch::Approx(nfsimForward));
                    CHECK(networkReverse == Catch::Approx(nfsimReverse));
                }
            }
        }
    }
}

TEST_CASE("the reverse-direction work negation is load-bearing") {
    // Omitting the negation would silently change every driven reverse rate,
    // so this pins down that the guard actually does something.
    const double activationEnergy = 1.3;
    const double phi = 0.35;
    const double deltaG = 2.0;
    const double work = 0.8;

    const double nfsimReverse = drivenArrheniusRate(
        activationEnergy, 0.0, deltaG, work, phi, 1.0, false);
    const double correct = networkArrheniusRate(
        activationEnergy, 0.0, -deltaG, work, 1.0 - phi, true);
    const double withoutNegation = networkArrheniusRate(
        activationEnergy, 0.0, -deltaG, work, 1.0 - phi, false);

    CHECK(correct == Catch::Approx(nfsimReverse));
    CHECK(withoutNegation != Catch::Approx(nfsimReverse));
}

TEST_CASE("a barrier is never negated by direction on the network path") {
    const double activationEnergy = 1.3;
    const double phi = 0.4;
    const double deltaG = 1.5;
    for (const double barrier : {0.0, 2.0, -2.0}) {
        const double forward =
            networkArrheniusRate(activationEnergy, barrier, deltaG, 0.0, phi, false);
        const double reverse = networkArrheniusRate(
            activationEnergy, barrier, -deltaG, 0.0, 1.0 - phi, true);
        // RT is folded into the parameters on this path, hence exp(-dG).
        CHECK(forward / reverse == Catch::Approx(std::exp(-deltaG)));
    }
}
