/// test_signaling_rate_laws.cpp
///
/// Two rate-law defects that a cellular-signaling model hits immediately,
/// both found by checking a phosphorylation pair against the closed form of a
/// closed two-state cycle.
///
/// 1. A second rate law on a UNIDIRECTIONAL arrow was accepted and then
///    silently discarded.
///
///    `A(s~U) -> A(s~P) ka, kb` parsed, and because the reverse direction is
///    only ever built for a bidirectional rule, the generated network held a
///    single reaction `1 1 2 ka`. The `kb` the model declared vanished. A
///    two-state phosphorylation pair is then a one-way drain: the substrate
///    goes entirely to the product and the closed cycle never equilibrates.
///    BNG2 refuses the spelling outright -- "Unidirection reaction may have
///    only one rate law" -- and the same diagnostic already guarded population
///    mapping rules in this tree, so BNG3 was the outlier. Failing closed with
///    BNG2's wording is the fix; guessing that the second law was meant as the
///    reverse rate would invent semantics the model never declared.
///
/// 2. A parameter name was looked up under a mangled spelling.
///
///    `parseScalarValue` rewrote 'd'/'D' to 'e'/'E' across the whole value
///    string before consulting the parameter table, so that any name
///    containing 'd' -- `t_end`, `n_steps`, `tend` -- was searched for under
///    its mangled twin and refused with "Unsupported scalar action value".
///    The rewrite exists to accept a Fortran double-precision exponent
///    (`1D-10`), which is a property of the NUMERIC spelling, not of the
///    identifier. `simulate_ode({t_end=>t_end})` is the ordinary way to write a
///    run horizon and it did not work.
///
/// Oracle for both: `RuleWorld/bionetgen` (BNG2), `legacy/perl/Perl2/`.

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <stdexcept>
#include <string>

#include "ast/Model.hpp"
#include "parser/BNGAstVisitor.hpp"

namespace {

/// A single-site two-state cycle. `arrow` is what the model actually says, so
/// the three spellings of the same reversible pair differ only in that token.
std::string phosphorylationPair(const std::string& arrow,
                                 const std::string& rates) {
    return "begin model\n"
           "begin parameters\n"
           "  ka 0.8\n"
           "  kb 0.3\n"
           "end parameters\n"
           "begin molecule types\n"
           "  A(s~U~P)\n"
           "end molecule types\n"
           "begin seed species\n"
           "  A(s~U) 1000\n"
           "end seed species\n"
           "begin observables\n"
           "  Molecules P A(s~P)\n"
           "end observables\n"
           "begin reaction rules\n"
           "  A(s~U) " + arrow + " A(s~P) " + rates + "\n"
           "end reaction rules\n"
           "end model\n";
}

} // namespace

// ---------------------------------------------------------------------------
// 1. Two rate laws on `->` must be refused, not silently truncated to one.
// ---------------------------------------------------------------------------

TEST_CASE("a unidirectional arrow with two rate laws is refused",
          "[signaling][rate-laws]") {
    REQUIRE_THROWS_WITH(
        bng::parser::parseModel(phosphorylationPair("->", "ka, kb")),
        Catch::Matchers::ContainsSubstring("only one rate law"));
}

TEST_CASE("a unidirectional arrow with one rate law is still accepted",
          "[signaling][rate-laws]") {
    // The guard must not reject the ordinary one-way phosphorylation step,
    // which is the whole point of the rule it is protecting.
    auto model = bng::parser::parseModel(phosphorylationPair("->", "ka"));
    REQUIRE(model != nullptr);
    REQUIRE(model->getReactionRules().size() == 1);
    const auto& rule = model->getReactionRules().front();
    REQUIRE(rule.getRates().size() == 1);
    REQUIRE_FALSE(rule.isBidirectional());
}

TEST_CASE("a bidirectional arrow still carries both rate laws",
          "[signaling][rate-laws]") {
    // The same two laws on `<->` are the supported reversible spelling and
    // must keep working: forward `ka`, reverse `kb`.
    auto model = bng::parser::parseModel(phosphorylationPair("<->", "ka, kb"));
    REQUIRE(model != nullptr);
    REQUIRE(model->getReactionRules().size() == 1);
    const auto& rule = model->getReactionRules().front();
    REQUIRE(rule.getRates().size() == 2);
    REQUIRE(rule.getRates()[0].toString() == "ka");
    REQUIRE(rule.getRates()[1].toString() == "kb");
    REQUIRE(rule.isBidirectional());
}

