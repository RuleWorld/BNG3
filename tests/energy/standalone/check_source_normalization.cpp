#include "parser/ThermoSourceNormalization.hpp"
#include <cstdio>
#include <stdexcept>
#include <string>
using bng::parser::normalizeThermodynamicSyntax;
static int failures = 0;
#define CHECK(c) do { if(!(c)){ std::printf("  FAIL line %d: %s\n", __LINE__, #c); ++failures; } } while(0)
static bool has(const std::string& h, const std::string& n) { return h.find(n) != std::string::npos; }
static bool throws(const std::string& src, std::string& msg) {
    try { normalizeThermodynamicSyntax(src); return false; }
    catch (const std::exception& e) { msg = e.what(); return true; }
}
static std::size_t countLines(const std::string& s) {
    std::size_t n = 0; for (char c : s) if (c == '\n') ++n; return n;
}

int main() {
    // Untouched when neither construct is present.
    {
        std::string src = "begin model\nbegin reaction rules\n A -> B k\nend reaction rules\nend model\n";
        CHECK(normalizeThermodynamicSyntax(src) == src);
    }
    // Barrier block becomes a reaction rules block with synthetic labels.
    {
        std::string out = normalizeThermodynamicSyntax(
            "begin model\n"
            "begin barrier patterns\n"
            " A(s~U) -> A(s~P) Gbar\n"
            " B(x) + C(y) -> B(x!1).C(y!1) Gb2\n"
            "end barrier patterns\n"
            "end model\n");
        std::printf("---- barrier block ----\n%s\n", out.c_str());
        CHECK(has(out, "begin reaction rules"));
        CHECK(has(out, "end reaction rules"));
        CHECK(!has(out, "barrier patterns"));
        CHECK(has(out, "__bng3_barrier_0: A(s~U) -> A(s~P) Gbar"));
        CHECK(has(out, "__bng3_barrier_1: B(x) + C(y) -> B(x!1).C(y!1) Gb2"));
    }
    // A user label on a barrier pattern is preserved via the option channel.
    {
        std::string out = normalizeThermodynamicSyntax(
            "begin barrier patterns\n b1: A(s~U) -> A(s~P) Gbar\nend barrier patterns\n");
        std::printf("---- labelled barrier ----\n%s\n", out.c_str());
        CHECK(has(out, "setOption(\"__bng3_barrier_label:0\",\"b1\")"));
        CHECK(has(out, "__bng3_barrier_0: A(s~U) -> A(s~P) Gbar"));
    }
    // driven_by is stripped and hoisted, indexed over ordinary rules.
    {
        std::string out = normalizeThermodynamicSyntax(
            "begin model\n"
            "begin reaction rules\n"
            " A(s~U) <-> A(s~P) Arrhenius(phi,Ea)\n"
            " B(x) <-> B(x!+) Arrhenius(phi,Ea) driven_by(muATP)\n"
            " C -> D k3\n"
            "end reaction rules\n"
            "end model\n");
        std::printf("---- driven_by ----\n%s\n", out.c_str());
        CHECK(has(out, "setOption(\"__bng3_driving_work:1\",\"muATP\")"));
        CHECK(!has(out, "driven_by"));
        CHECK(has(out, "Arrhenius(phi,Ea)"));
    }
    // Compound work expressions and nested parens survive.
    {
        std::string out = normalizeThermodynamicSyntax(
            "begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by((muATP - muADP)/2)\nend reaction rules\n");
        CHECK(has(out, "setOption(\"__bng3_driving_work:0\",\"(muATP - muADP)/2\")"));
        CHECK(!has(out, "driven_by"));
    }
    // Barrier indices are independent of where the barrier block sits
    // relative to the ordinary rules.
    {
        std::string before = normalizeThermodynamicSyntax(
            "begin barrier patterns\n A(s~U) -> A(s~P) Gbar\nend barrier patterns\n"
            "begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by(w)\nend reaction rules\n");
        std::string after = normalizeThermodynamicSyntax(
            "begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by(w)\nend reaction rules\n"
            "begin barrier patterns\n A(s~U) -> A(s~P) Gbar\nend barrier patterns\n");
        CHECK(has(before, "__bng3_driving_work:0"));
        CHECK(has(after,  "__bng3_driving_work:0"));
        CHECK(has(before, "__bng3_barrier_0:"));
        CHECK(has(after,  "__bng3_barrier_0:"));
    }
    // Comments are preserved and never scanned for annotations.
    {
        std::string out = normalizeThermodynamicSyntax(
            "begin reaction rules\n A <-> B Arrhenius(phi,Ea) # driven_by(ignored)\nend reaction rules\n");
        std::printf("---- comment ----\n%s\n", out.c_str());
        CHECK(!has(out, "__bng3_driving_work"));
        CHECK(has(out, "# driven_by(ignored)"));
    }
    // Line numbering is preserved for continuation lines.
    {
        std::string src =
            "begin reaction rules\n"
            " A <-> B \\\n"
            "   Arrhenius(phi,Ea) driven_by(w)\n"
            "end reaction rules\n";
        std::string out = normalizeThermodynamicSyntax(src);
        std::printf("---- continuation ----\n%s\n", out.c_str());
        CHECK(has(out, "__bng3_driving_work:0"));
        // one hoisted setOption line + the original four lines
        CHECK(countLines(out) == countLines(src) + 1);
    }
    // Identifier-boundary safety: a parameter whose name contains the keyword
    // must not be treated as an annotation.
    {
        std::string out = normalizeThermodynamicSyntax(
            "begin reaction rules\n A <-> B Arrhenius(phi,not_driven_by_x)\nend reaction rules\n");
        CHECK(!has(out, "__bng3_driving_work"));
        CHECK(has(out, "not_driven_by_x"));
    }
    // Fail-closed cases.
    {
        std::string msg;
        CHECK(throws("begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by\nend reaction rules\n", msg));
        std::printf("  err: %s\n", msg.c_str());
        CHECK(throws("begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by()\nend reaction rules\n", msg));
        std::printf("  err: %s\n", msg.c_str());
        CHECK(throws("begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by(w\nend reaction rules\n", msg));
        std::printf("  err: %s\n", msg.c_str());
        CHECK(throws("begin reaction rules\n A <-> B Arrhenius(phi,Ea) driven_by(w) driven_by(v)\nend reaction rules\n", msg));
        std::printf("  err: %s\n", msg.c_str());
        CHECK(throws("begin barrier patterns\n A(s~U) -> A(s~P) Gb, Gb2\nend barrier patterns\n", msg));
        std::printf("  err: %s\n", msg.c_str());
        CHECK(throws("begin barrier patterns\n A(s~U) Gbar\nend barrier patterns\n", msg));
        std::printf("  err: %s\n", msg.c_str());
        CHECK(throws("begin barrier patterns\n A(s~U) -> A(s~P) Gb\n", msg));
        std::printf("  err: %s\n", msg.c_str());
        CHECK(throws("begin barrier patterns\nbegin reaction rules\n A -> B k\nend reaction rules\nend barrier patterns\n", msg));
        std::printf("  err: %s\n", msg.c_str());
    }
    // Empty barrier block is legal.
    {
        std::string out = normalizeThermodynamicSyntax(
            "begin barrier patterns\nend barrier patterns\n");
        CHECK(has(out, "begin reaction rules"));
        CHECK(!has(out, "__bng3_barrier_"));
    }
    // Bidirectional barrier transitions are accepted (a barrier is symmetric).
    {
        std::string out = normalizeThermodynamicSyntax(
            "begin barrier patterns\n A(s~U) <-> A(s~P) Gbar\nend barrier patterns\n");
        CHECK(has(out, "__bng3_barrier_0: A(s~U) <-> A(s~P) Gbar"));
    }
    // Round-trip contract with BnglWriter: the exact text BnglWriter emits for
    // barrier patterns and driven rules must be re-readable. If either writer
    // format drifts from what the normalizer accepts, a written model would
    // silently come back without its thermodynamics.
    {
        // BnglWriter indents two spaces and prefixes rules with their rule name.
        const std::string written =
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
            "end model\n";
        const std::string out = normalizeThermodynamicSyntax(written);
        std::printf("---- BnglWriter round trip ----\n%s\n", out.c_str());
        CHECK(has(out, "setOption(\"__bng3_barrier_label:0\",\"slow\")"));
        CHECK(has(out, "__bng3_barrier_0: A(s~U) -> A(s~P) Gbar"));
        CHECK(has(out, "__bng3_barrier_1: B(x) + C(y) -> B(x!1).C(y!1) Gb2"));
        CHECK(has(out, "setOption(\"__bng3_driving_work:0\",\"muATP\")"));
        CHECK(!has(out, "driven_by"));
        // The energy patterns block and the rule label must be untouched.
        CHECK(has(out, "begin energy patterns"));
        CHECK(has(out, "R1: A(s~U) <-> A(s~P) Arrhenius(phi, Ea)"));
    }
    std::printf(failures ? "NORMALIZE: %d failure(s)\n" : "NORMALIZE: all checks passed\n", failures);
    return failures ? 1 : 0;
}
