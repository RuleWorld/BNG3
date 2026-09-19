// Executes the post-parse thermodynamic lowering directly, without the
// generated parser: barrier/ordinary partitioning, driving-work attachment by
// ordinary-rule index, renumbering, and every fail-closed path.
#include "parser/ThermoModelFinalize.hpp"
#include "ast/Model.hpp"
#include "ast/ReactionRule.hpp"
#include "ast/Expression.hpp"
#include <cstdio>
#include <string>
#include <vector>

using namespace bng;
static int failures = 0;
#define CHECK(c) do { if(!(c)){ std::printf("  FAIL line %d: %s\n", __LINE__, #c); ++failures; } } while(0)

// Stand-in for parseExpressionImpl: identifiers are enough for these cases.
static ast::Expression fakeParse(const std::string& text) {
    if (text == "!bad") throw std::runtime_error("synthetic parse failure");
    return ast::Expression::identifier(text);
}

static ast::ReactionRule makeRule(const std::string& name, const std::string& label,
                                  const std::vector<ast::Expression>& rates) {
    return ast::ReactionRule(name, label, {"A(s~U)"}, {"A(s~P)"}, rates, {}, false, {}, {});
}

static bool threw(const std::function<void()>& fn, std::string& message) {
    try { fn(); return false; }
    catch (const std::exception& e) { message = e.what(); return true; }
}

int main() {
    // --- An ordinary model is left completely untouched --------------------
    {
        ast::Model m;
        m.addReactionRule(makeRule("R1", "", {ast::Expression::number(1.0)}));
        m.addReactionRule(makeRule("R2", "myrule:", {ast::Expression::number(2.0)}));
        const bool rewritten = parser::finalizeThermodynamicMetadata(m, {}, {}, fakeParse);
        CHECK(!rewritten);
        CHECK(m.getBarrierPatterns().empty());
        CHECK(m.getReactionRules().size() == 2);
        CHECK(m.getReactionRules()[1].getRuleName() == "R2");
        CHECK(m.getReactionRules()[1].getLabel() == "myrule:");
        CHECK(!m.getReactionRules()[0].hasDrivingWork());
    }

    // --- Barrier rules are moved out; survivors renumbered ----------------
    // Barrier first in source order: without renumbering the ordinary rule
    // would keep the name R2.
    {
        ast::Model m;
        m.addReactionRule(makeRule("R1", "__bng3_barrier_0:", {ast::Expression::identifier("Gbar")}));
        m.addReactionRule(makeRule("R2", "", {ast::Expression::identifier("k1")}));
        const bool rewritten = parser::finalizeThermodynamicMetadata(m, {}, {}, fakeParse);
        CHECK(rewritten);
        CHECK(m.getBarrierPatterns().size() == 1);
        CHECK(m.getReactionRules().size() == 1);
        CHECK(m.getReactionRules()[0].getRuleName() == "R1");
        CHECK(m.getBarrierPatterns()[0].expression().toString() == "Gbar");
        CHECK(m.getBarrierPatterns()[0].transition().getRuleName() == "B1");
        CHECK(m.getBarrierPatterns()[0].getLabel().empty());
    }

    // --- Label reattachment, and ordering by barrier index ----------------
    {
        ast::Model m;
        // Deliberately out of index order to prove sorting.
        m.addReactionRule(makeRule("R1", "__bng3_barrier_1:", {ast::Expression::identifier("Gb")}));
        m.addReactionRule(makeRule("R2", "__bng3_barrier_0:", {ast::Expression::identifier("Ga")}));
        parser::finalizeThermodynamicMetadata(m, {{0, "slow"}, {1, "fast"}}, {}, fakeParse);
        CHECK(m.getReactionRules().empty());
        CHECK(m.getBarrierPatterns().size() == 2);
        CHECK(m.getBarrierPatterns()[0].getLabel() == "slow");
        CHECK(m.getBarrierPatterns()[0].expression().toString() == "Ga");
        CHECK(m.getBarrierPatterns()[1].getLabel() == "fast");
        CHECK(m.getBarrierPatterns()[1].expression().toString() == "Gb");
    }

    // --- Driving work indexes over ORDINARY rules only --------------------
    // A barrier rule sits between the two ordinary rules; work index 1 must
    // still land on the second ordinary rule, not the third overall rule.
    {
        ast::Model m;
        m.addReactionRule(makeRule("R1", "", {ast::Expression::identifier("k1")}));
        m.addReactionRule(makeRule("R2", "__bng3_barrier_0:", {ast::Expression::identifier("Gbar")}));
        m.addReactionRule(makeRule("R3", "", {ast::Expression::identifier("k2")}));
        parser::finalizeThermodynamicMetadata(m, {}, {{1, "muATP"}}, fakeParse);
        CHECK(m.getReactionRules().size() == 2);
        CHECK(!m.getReactionRules()[0].hasDrivingWork());
        CHECK(m.getReactionRules()[1].hasDrivingWork());
        CHECK(m.getReactionRules()[1].drivingWorkExpression().toString() == "muATP");
        CHECK(m.getReactionRules()[0].getRuleName() == "R1");
        CHECK(m.getReactionRules()[1].getRuleName() == "R2");
    }

    // --- Absent work is the neutral zero, not an error --------------------
    {
        ast::Model m;
        m.addReactionRule(makeRule("R1", "", {ast::Expression::identifier("k1")}));
        m.addReactionRule(makeRule("R2", "__bng3_barrier_0:", {ast::Expression::identifier("G")}));
        parser::finalizeThermodynamicMetadata(m, {}, {}, fakeParse);
        CHECK(!m.getReactionRules()[0].hasDrivingWork());
        CHECK(m.getReactionRules()[0].drivingWorkExpression().toString() == "0");
    }

    // --- Fail-closed paths -------------------------------------------------
    std::string msg;
    {   // work index past the end of the ordinary rules
        ast::Model m;
        m.addReactionRule(makeRule("R1", "__bng3_barrier_0:", {ast::Expression::identifier("G")}));
        CHECK(threw([&]{ parser::finalizeThermodynamicMetadata(m, {}, {{0, "w"}}, fakeParse); }, msg));
        std::printf("  err: %s\n", msg.c_str());
    }
    {   // duplicate barrier index
        ast::Model m;
        m.addReactionRule(makeRule("R1", "__bng3_barrier_0:", {ast::Expression::identifier("G")}));
        m.addReactionRule(makeRule("R2", "__bng3_barrier_0:", {ast::Expression::identifier("G")}));
        CHECK(threw([&]{ parser::finalizeThermodynamicMetadata(m, {}, {}, fakeParse); }, msg));
        std::printf("  err: %s\n", msg.c_str());
    }
    {   // barrier with no energy expression
        ast::Model m;
        m.addReactionRule(makeRule("R1", "__bng3_barrier_0:", {}));
        CHECK(threw([&]{ parser::finalizeThermodynamicMetadata(m, {}, {}, fakeParse); }, msg));
        std::printf("  err: %s\n", msg.c_str());
    }
    {   // barrier with a rate pair
        ast::Model m;
        m.addReactionRule(makeRule("R1", "__bng3_barrier_0:",
            {ast::Expression::identifier("G"), ast::Expression::identifier("G2")}));
        CHECK(threw([&]{ parser::finalizeThermodynamicMetadata(m, {}, {}, fakeParse); }, msg));
        std::printf("  err: %s\n", msg.c_str());
    }
    {   // non-numeric synthetic index
        ast::Model m;
        m.addReactionRule(makeRule("R1", "__bng3_barrier_x:", {ast::Expression::identifier("G")}));
        CHECK(threw([&]{ parser::finalizeThermodynamicMetadata(m, {}, {}, fakeParse); }, msg));
        std::printf("  err: %s\n", msg.c_str());
    }
    {   // label with no matching barrier rule
        ast::Model m;
        m.addReactionRule(makeRule("R1", "__bng3_barrier_0:", {ast::Expression::identifier("G")}));
        CHECK(threw([&]{ parser::finalizeThermodynamicMetadata(m, {{7, "ghost"}}, {}, fakeParse); }, msg));
        std::printf("  err: %s\n", msg.c_str());
    }
    {   // unparseable work expression is reported, not swallowed
        ast::Model m;
        m.addReactionRule(makeRule("R1", "", {ast::Expression::identifier("k")}));
        m.addReactionRule(makeRule("R2", "__bng3_barrier_0:", {ast::Expression::identifier("G")}));
        CHECK(threw([&]{ parser::finalizeThermodynamicMetadata(m, {}, {{0, "!bad"}}, fakeParse); }, msg));
        std::printf("  err: %s\n", msg.c_str());
    }
    {   // a label that merely starts with the prefix but has no index
        ast::Model m;
        m.addReactionRule(makeRule("R1", "__bng3_barrier_:", {ast::Expression::identifier("G")}));
        CHECK(threw([&]{ parser::finalizeThermodynamicMetadata(m, {}, {}, fakeParse); }, msg));
        std::printf("  err: %s\n", msg.c_str());
    }
    std::printf(failures ? "FINALIZE: %d failure(s)\n" : "FINALIZE: all checks passed\n", failures);
    return failures ? 1 : 0;
}
