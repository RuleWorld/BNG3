// Surface syntax for barrier patterns and driven_by(), tested as a pure
// string-to-string transformation so the accepted and rejected grammar is
// pinned down without constructing a model.
#include <catch2/catch_test_macros.hpp>
#include <string>

#include "parser/ThermoSourceNormalization.hpp"

using bng::parser::normalizeThermodynamicSyntax;

namespace {
bool contains(const std::string& haystack, const std::string& needle) {
    return haystack.find(needle) != std::string::npos;
}
std::size_t lineCount(const std::string& text) {
    std::size_t count = 0;
    for (const char character : text) {
        if (character == '\n') ++count;
    }
    return count;
}
} // namespace

TEST_CASE("a model without either construct is returned unchanged") {
    const std::string source =
        "begin model\nbegin reaction rules\n A -> B k\nend reaction rules\nend model\n";
    CHECK(normalizeThermodynamicSyntax(source) == source);
}

TEST_CASE("a barrier block becomes a reaction rules block with synthetic labels") {
    const auto output = normalizeThermodynamicSyntax(
        "begin model\n"
        "begin barrier patterns\n"
        " A(s~U) -> A(s~P) Gbar\n"
        " B(x) + C(y) -> B(x!1).C(y!1) Gb2\n"
        "end barrier patterns\n"
        "end model\n");
    CHECK(contains(output, "begin reaction rules"));
    CHECK(contains(output, "end reaction rules"));
    CHECK_FALSE(contains(output, "barrier patterns"));
    CHECK(contains(output, "__bng3_barrier_0: A(s~U) -> A(s~P) Gbar"));
    CHECK(contains(output, "__bng3_barrier_1: B(x) + C(y) -> B(x!1).C(y!1) Gb2"));
}

TEST_CASE("a user label on a barrier pattern survives through the option channel") {
    const auto output = normalizeThermodynamicSyntax(
        "begin barrier patterns\n b1: A(s~U) -> A(s~P) Gbar\nend barrier patterns\n");
    CHECK(contains(output, "setOption(\"__bng3_barrier_label:0\",\"b1\")"));
    CHECK(contains(output, "__bng3_barrier_0: A(s~U) -> A(s~P) Gbar"));
}

TEST_CASE("driven_by is hoisted and indexed over ordinary rules only") {
    const auto output = normalizeThermodynamicSyntax(
        "begin reaction rules\n"
        " A(s~U) <-> A(s~P) Arrhenius(phi,Ea)\n"
        " B(x) <-> B(x!+) Arrhenius(phi,Ea) driven_by(muATP)\n"
        " C -> D k3\n"
        "end reaction rules\n");
    CHECK(contains(output, "setOption(\"__bng3_driving_work:1\",\"muATP\")"));
    CHECK_FALSE(contains(output, "driven_by"));
    CHECK(contains(output, "Arrhenius(phi,Ea)"));
}

TEST_CASE("the driving-work index is independent of barrier block placement") {
    const auto before = normalizeThermodynamicSyntax(
        "begin barrier patterns\n A(s~U) -> A(s~P) Gbar\nend barrier patterns\n"
        "begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by(w)\nend reaction rules\n");
    const auto after = normalizeThermodynamicSyntax(
        "begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by(w)\nend reaction rules\n"
        "begin barrier patterns\n A(s~U) -> A(s~P) Gbar\nend barrier patterns\n");
    CHECK(contains(before, "__bng3_driving_work:0"));
    CHECK(contains(after, "__bng3_driving_work:0"));
    CHECK(contains(before, "__bng3_barrier_0:"));
    CHECK(contains(after, "__bng3_barrier_0:"));
}

TEST_CASE("a compound work expression keeps its parentheses") {
    const auto output = normalizeThermodynamicSyntax(
        "begin reaction rules\n"
        " A <-> B Arrhenius(phi,Ea) driven_by((muATP - muADP)/2)\n"
        "end reaction rules\n");
    CHECK(contains(output, "setOption(\"__bng3_driving_work:0\",\"(muATP - muADP)/2\")"));
}

TEST_CASE("commented-out annotations are not scanned") {
    const auto output = normalizeThermodynamicSyntax(
        "begin reaction rules\n"
        " A <-> B Arrhenius(phi,Ea) # driven_by(ignored)\n"
        "end reaction rules\n");
    CHECK_FALSE(contains(output, "__bng3_driving_work"));
    CHECK(contains(output, "# driven_by(ignored)"));
}

TEST_CASE("an identifier merely containing the keyword is not an annotation") {
    const auto output = normalizeThermodynamicSyntax(
        "begin reaction rules\n A <-> B Arrhenius(phi,not_driven_by_x)\nend reaction rules\n");
    CHECK_FALSE(contains(output, "__bng3_driving_work"));
    CHECK(contains(output, "not_driven_by_x"));
}

TEST_CASE("continuation lines keep the original source line numbering") {
    const std::string source =
        "begin reaction rules\n"
        " A <-> B \\\n"
        "   Arrhenius(phi,Ea) driven_by(w)\n"
        "end reaction rules\n";
    const auto output = normalizeThermodynamicSyntax(source);
    CHECK(contains(output, "__bng3_driving_work:0"));
    // Exactly one hoisted setOption line is added.
    CHECK(lineCount(output) == lineCount(source) + 1);
}

TEST_CASE("a bidirectional barrier transition is accepted") {
    const auto output = normalizeThermodynamicSyntax(
        "begin barrier patterns\n A(s~U) <-> A(s~P) Gbar\nend barrier patterns\n");
    CHECK(contains(output, "__bng3_barrier_0: A(s~U) <-> A(s~P) Gbar"));
}

TEST_CASE("an empty barrier block is legal and produces no rules") {
    const auto output = normalizeThermodynamicSyntax(
        "begin barrier patterns\nend barrier patterns\n");
    CHECK(contains(output, "begin reaction rules"));
    CHECK_FALSE(contains(output, "__bng3_barrier_"));
}

TEST_CASE("malformed thermodynamic syntax fails closed") {
    const auto rejects = [](const char* source) {
        try {
            normalizeThermodynamicSyntax(source);
        } catch (const std::exception&) {
            return true;
        }
        return false;
    };

    CHECK(rejects("begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by\n"
                  "end reaction rules\n"));
    CHECK(rejects("begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by()\n"
                  "end reaction rules\n"));
    CHECK(rejects("begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by(w\n"
                  "end reaction rules\n"));
    CHECK(rejects("begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by(w) driven_by(v)\n"
                  "end reaction rules\n"));
    // A barrier is symmetric, so a rate pair has no meaning.
    CHECK(rejects("begin barrier patterns\n A(s~U) -> A(s~P) Gb, Gb2\nend barrier patterns\n"));
    // A barrier pattern must be a transition, not a species pattern.
    CHECK(rejects("begin barrier patterns\n A(s~U) Gbar\nend barrier patterns\n"));
    CHECK(rejects("begin barrier patterns\n A(s~U) -> A(s~P) Gb\n"));
    CHECK(rejects("begin barrier patterns\nbegin reaction rules\n A -> B k\n"
                  "end reaction rules\nend barrier patterns\n"));
}

TEST_CASE("BnglWriter output round-trips back through normalization") {
    // Locks the text contract between BnglWriter and the normalizer. If either
    // format drifts, a model written to BNGL would come back without its
    // thermodynamics and with no diagnostic.
    const auto output = normalizeThermodynamicSyntax(
        "begin model\n"
        "begin energy patterns\n"
        "  A(s~U) GU\n"
        "end energy patterns\n"
        "\n"
        "begin barrier patterns\n"
        "  slow: A(s~U) -> A(s~P) Gbar\n"
        "  B(x) + C(y) -> B(x!1).C(y!1) Gb2\n"
        "end barrier patterns\n"
        "\n"
        "begin reaction rules\n"
        "  R1: A(s~U) <-> A(s~P) Arrhenius(phi, Ea) driven_by(muATP)\n"
        "end reaction rules\n"
        "end model\n");

    CHECK(contains(output, "setOption(\"__bng3_barrier_label:0\",\"slow\")"));
    CHECK(contains(output, "__bng3_barrier_0: A(s~U) -> A(s~P) Gbar"));
    CHECK(contains(output, "__bng3_barrier_1: B(x) + C(y) -> B(x!1).C(y!1) Gb2"));
    CHECK(contains(output, "setOption(\"__bng3_driving_work:0\",\"muATP\")"));
    CHECK_FALSE(contains(output, "driven_by"));
    // Neighbouring blocks and the rule's own label must be untouched.
    CHECK(contains(output, "begin energy patterns"));
    CHECK(contains(output, "R1: A(s~U) <-> A(s~P) Arrhenius(phi, Ea)"));
}
