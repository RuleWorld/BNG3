// Executes the fail-closed export guard against real ast::Model instances.
#include "io/EnergyExportGuard.hpp"
#include "ast/Model.hpp"
#include "ast/ReactionRule.hpp"
#include "ast/BarrierPattern.hpp"
#include "ast/EnergyPattern.hpp"
#include "ast/Expression.hpp"
#include <cstdio>
#include <string>
#include <vector>
using namespace bng;
static int failures = 0;
#define CHECK(c) do { if(!(c)){ std::printf("  FAIL line %d: %s\n", __LINE__, #c); ++failures; } } while(0)

static ast::ReactionRule rule(const std::string& name,
                              const std::vector<ast::Expression>& rates) {
    return ast::ReactionRule(name, "", {"A(s~U)"}, {"A(s~P)"}, rates, {}, false, {}, {});
}
static bool rejected(const ast::Model& m, std::string& msg) {
    try { io::requireNoEnergySemantics(m, "TestFormat"); return false; }
    catch (const std::exception& e) { msg = e.what(); return true; }
}

int main() {
    std::string msg;

    // An ordinary kinetic model must export without complaint.
    {
        ast::Model m;
        m.addReactionRule(rule("R1", {ast::Expression::identifier("k1")}));
        CHECK(!io::usesEnergySemantics(m));
        CHECK(!rejected(m, msg));
    }
    // An empty model is fine too.
    {
        ast::Model m;
        CHECK(!io::usesEnergySemantics(m));
        CHECK(!rejected(m, msg));
    }
    // Energy patterns alone are enough to reject.
    {
        ast::Model m;
        m.addEnergyPattern(ast::EnergyPattern("GU", "A(s~U)",
            ast::Expression::identifier("GU"), ast::SpeciesGraph{}));
        CHECK(io::usesEnergySemantics(m));
        CHECK(rejected(m, msg));
        CHECK(msg.find("energy patterns") != std::string::npos);
        CHECK(msg.find("TestFormat") != std::string::npos);
        std::printf("  %s\n", msg.c_str());
    }
    // An Arrhenius rate law is rejected even with no energy patterns present:
    // the rate law itself is inexpressible in these formats.
    {
        ast::Model m;
        m.addReactionRule(rule("R1", {ast::Expression::function("Arrhenius",
            {ast::Expression::identifier("phi"), ast::Expression::identifier("Ea")})}));
        CHECK(io::usesEnergySemantics(m));
        CHECK(rejected(m, msg));
        CHECK(msg.find("Arrhenius") != std::string::npos);
        CHECK(msg.find("R1") != std::string::npos);
        std::printf("  %s\n", msg.c_str());
    }
    // Case-insensitive, matching NetWriter's parseArrhenius.
    {
        ast::Model m;
        m.addReactionRule(rule("R1", {ast::Expression::function("arrhenius",
            {ast::Expression::identifier("phi"), ast::Expression::identifier("Ea")})}));
        CHECK(rejected(m, msg));
    }
    // A reverse-rate Arrhenius in position 1 is also caught.
    {
        ast::Model m;
        m.addReactionRule(rule("R1", {ast::Expression::identifier("k1"),
            ast::Expression::function("Arrhenius",
                {ast::Expression::identifier("phi"), ast::Expression::identifier("Ea")})}));
        CHECK(rejected(m, msg));
    }
    // Barrier patterns are named ahead of the energy patterns they accompany,
    // so the message points at the construct the user actually wrote.
    {
        ast::Model m;
        m.addEnergyPattern(ast::EnergyPattern("GU", "A(s~U)",
            ast::Expression::identifier("GU"), ast::SpeciesGraph{}));
        m.addBarrierPattern(ast::BarrierPattern("slow",
            rule("B1", {ast::Expression::identifier("Gbar")})));
        CHECK(rejected(m, msg));
        CHECK(msg.find("barrier patterns") != std::string::npos);
        std::printf("  %s\n", msg.c_str());
    }
    // Reservoir work is reported with the offending rule name.
    {
        ast::Model m;
        auto r = rule("R7", {ast::Expression::identifier("k1")});
        r.setDrivingWorkExpression(ast::Expression::identifier("muATP"));
        m.addReactionRule(std::move(r));
        CHECK(rejected(m, msg));
        CHECK(msg.find("driven_by") != std::string::npos);
        CHECK(msg.find("R7") != std::string::npos);
        std::printf("  %s\n", msg.c_str());
    }
    // A rule that merely has a function rate law is NOT energy semantics.
    {
        ast::Model m;
        m.addReactionRule(rule("R1", {ast::Expression::function("Sat",
            {ast::Expression::identifier("k"), ast::Expression::identifier("K")})}));
        CHECK(!io::usesEnergySemantics(m));
        CHECK(!rejected(m, msg));
    }
    std::printf(failures ? "EXPORTGUARD: %d failure(s)\n" : "EXPORTGUARD: all checks passed\n", failures);
    return failures ? 1 : 0;
}
