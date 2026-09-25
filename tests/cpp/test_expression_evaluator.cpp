#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <cmath>

#include "ast/Expression.hpp"
#include "ast/ExpressionBuiltins.hpp"
#include "ast/ExpressionEval.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng::ast;
using Catch::Matchers::WithinRel;

static double noResolver(const std::string& name) {
    throw std::runtime_error("Unknown identifier: " + name);
}

TEST_CASE("Expression: numeric literals", "[Expression]") {
    auto expr = Expression::number(42.0);
    REQUIRE(expr.evaluate(noResolver) == 42.0);
}

TEST_CASE("Expression numeric rendering preserves round-trip precision", "[Expression]") {
    const auto rendered = Expression::number(3.141592653589793).toString();
    CHECK(rendered == "3.1415926535897931");
}

TEST_CASE("Expression: parameter references", "[Expression]") {
    auto expr = Expression::identifier("k1");
    auto resolver = [](const std::string& name) -> double {
        if (name == "k1") return 3.14;
        return 0.0;
    };
    REQUIRE_THAT(expr.evaluate(resolver), WithinRel(3.14, 1e-10));
}

TEST_CASE("Expression: nested arithmetic", "[Expression]") {
    // (2 + 3) * 4 = 20
    auto sum = Expression::binary("+", Expression::number(2.0), Expression::number(3.0));
    auto expr = Expression::binary("*", std::move(sum), Expression::number(4.0));
    REQUIRE_THAT(expr.evaluate(noResolver), WithinRel(20.0, 1e-10));
}

TEST_CASE("Expression: power operator", "[Expression]") {
    auto expr = Expression::binary("^", Expression::number(2.0), Expression::number(10.0));
    REQUIRE_THAT(expr.evaluate(noResolver), WithinRel(1024.0, 1e-10));
}

TEST_CASE("Legacy expression operators remain accepted", "[Expression][issue-54]") {
    const auto evaluate = [](const std::string& source) {
        return bng::parser::parseExpression(source).evaluate(noResolver);
    };

    CHECK(evaluate("2**3") == 8.0);
    CHECK(evaluate("1~=2") == 1.0);
    CHECK(evaluate("!0") == 1.0);
    CHECK(evaluate("~1") == 0.0);
}

TEST_CASE("Expression: built-in functions", "[Expression]") {
    SECTION("sin") {
        auto expr = Expression::function("sin", {Expression::number(0.0)});
        REQUIRE_THAT(expr.evaluate(noResolver), WithinRel(0.0, 1e-10));
    }
    SECTION("cos") {
        auto expr = Expression::function("cos", {Expression::number(0.0)});
        REQUIRE_THAT(expr.evaluate(noResolver), WithinRel(1.0, 1e-10));
    }
    SECTION("exp") {
        auto expr = Expression::function("exp", {Expression::number(0.0)});
        REQUIRE_THAT(expr.evaluate(noResolver), WithinRel(1.0, 1e-10));
    }
    SECTION("log/ln") {
        auto expr = Expression::function("ln", {Expression::number(1.0)});
        REQUIRE_THAT(expr.evaluate(noResolver), WithinRel(0.0, 1e-10));
    }
    SECTION("sqrt") {
        auto expr = Expression::function("sqrt", {Expression::number(9.0)});
        REQUIRE_THAT(expr.evaluate(noResolver), WithinRel(3.0, 1e-10));
    }
    SECTION("abs") {
        auto expr = Expression::function("abs", {Expression::number(-5.0)});
        REQUIRE_THAT(expr.evaluate(noResolver), WithinRel(5.0, 1e-10));
    }
    SECTION("factorial") {
        auto expr = Expression::function("factorial", {Expression::number(5.0)});
        REQUIRE_THAT(expr.evaluate(noResolver), WithinRel(120.0, 1e-10));
    }
    SECTION("min") {
        auto expr = Expression::function("min", {Expression::number(3.0), Expression::number(7.0)});
        REQUIRE_THAT(expr.evaluate(noResolver), WithinRel(3.0, 1e-10));
    }
    SECTION("max") {
        auto expr = Expression::function("max", {Expression::number(3.0), Expression::number(7.0)});
        REQUIRE_THAT(expr.evaluate(noResolver), WithinRel(7.0, 1e-10));
    }
    SECTION("if") {
        auto exprTrue = Expression::function("if", {Expression::number(1.0), Expression::number(10.0), Expression::number(20.0)});
        REQUIRE_THAT(exprTrue.evaluate(noResolver), WithinRel(10.0, 1e-10));
        auto exprFalse = Expression::function("if", {Expression::number(0.0), Expression::number(10.0), Expression::number(20.0)});
        REQUIRE_THAT(exprFalse.evaluate(noResolver), WithinRel(20.0, 1e-10));
    }
}

TEST_CASE("Expression: factorial rejects non-integer and overflowing domains", "[Expression]") {
    CHECK_THROWS_WITH(
        Expression::function("factorial", {Expression::number(-1.0)}).evaluate(noResolver),
        "Function 'factorial' expects a non-negative integer");
    CHECK_THROWS_WITH(
        Expression::function("factorial", {Expression::number(2.5)}).evaluate(noResolver),
        "Function 'factorial' expects a non-negative integer");
    CHECK_THROWS_WITH(
        Expression::function("factorial", {Expression::number(171.0)}).evaluate(noResolver),
        "Function 'factorial' overflows double precision");
}

TEST_CASE("Expression: TFUN resolution via resolver", "[Expression]") {
    auto expr = Expression::function("TFUN", {Expression::identifier("myTfun")});
    auto resolver = [](const std::string& name) -> double {
        if (name == "__tfun_myTfun__") return 42.5;
        return 0.0;
    };
    REQUIRE_THAT(expr.evaluate(resolver, 5.0), WithinRel(42.5, 1e-10));
}

TEST_CASE("Expression: evaluateLocal with context overrides", "[Expression]") {
    auto expr = Expression::binary("+", Expression::identifier("x"), Expression::identifier("k"));
    auto globalResolver = [](const std::string& name) -> double {
        if (name == "k") return 10.0;
        return 0.0;
    };
    std::unordered_map<std::string, double> local = {{"x", 5.0}};
    REQUIRE_THAT(expr.evaluateLocal(globalResolver, local), WithinRel(15.0, 1e-10));
}

TEST_CASE("Expression: checkLocalDependency", "[Expression]") {
    auto expr = Expression::binary("*", Expression::identifier("x"), Expression::identifier("k"));
    std::set<std::string> localNames = {"x"};
    REQUIRE(expr.checkLocalDependency(localNames) == true);

    std::set<std::string> otherNames = {"y", "z"};
    REQUIRE(expr.checkLocalDependency(otherNames) == false);
}

TEST_CASE("Expression: getDependencies completeness", "[Expression]") {
    auto expr = Expression::binary("+",
        Expression::binary("*", Expression::identifier("a"), Expression::identifier("b")),
        Expression::function("sin", {Expression::identifier("c")})
    );
    auto deps = expr.getDependencies();
    REQUIRE(deps.count("a") == 1);
    REQUIRE(deps.count("b") == 1);
    REQUIRE(deps.count("c") == 1);
    REQUIRE(deps.size() == 3);
}

TEST_CASE("Expression: time alias 't'", "[Expression]") {
    auto expr = Expression::identifier("t");
    auto resolver = [](const std::string& name) -> double {
        if (name == "time") return 99.0;
        throw std::runtime_error("Unknown: " + name);
    };
    // 't' should be recognized as time alias
    auto deps = expr.getDependencies();
    REQUIRE(deps.empty());
}

TEST_CASE("ExpressionEval facade binds time and symbols", "[ExpressionEval]") {
    auto expr = Expression::binary(
        "+", Expression::identifier("k"),
        Expression::function("sin", {Expression::identifier("time")}));
    const std::unordered_map<std::string, double> symbols = {{"k", 2.0}};

    REQUIRE_THAT(bng::eval::evaluate(expr, 0.0, symbols), WithinRel(2.0, 1e-10));
    REQUIRE_THAT(bng::eval::evaluate(expr, 1.0, symbols),
                 WithinRel(2.8414709848, 1e-10));
}

TEST_CASE("ExpressionEval facade reports missing symbols", "[ExpressionEval]") {
    const auto expr = Expression::identifier("missing");
    CHECK_THROWS_WITH(
        bng::eval::evaluate(expr, 0.0, {}),
        "Unknown expression symbol 'missing'");
    CHECK_THROWS_WITH(
        bng::eval::evaluate(expr, bng::eval::Context {}),
        "Expression evaluation requires a symbol resolver");
}

// ---------------------------------------------------------------------------
// Convergence regressions: the shared builtin table and the two engines that
// consume it. Each case below is a behavior that previously differed between
// bng::ast::Expression (ODE RHS / SSA propensity) and the NFsim ExprTk path.
// ---------------------------------------------------------------------------

TEST_CASE("Expression: rint matches the BNG2 oracle at half-integers",
          "[Expression][builtins]") {
    // Oracle: legacy/perl/Perl2/Expression.pm:74
    //   "rint" => { FPTR => sub { floor( $_[0] + 0.5 ) }, NARGS => 1 }
    //
    // This used to be std::rint here (round-half-to-EVEN) and std::round in
    // cpp/nfsim/NFfunction/nfsim_funcparser.h (round-half-AWAY-from-zero), so
    // the two engines disagreed with each other and each disagreed with BNG2
    // at different inputs. Verified against `perl -e 'use POSIX qw/floor/;
    // print floor($x+0.5)'` for every value below.
    struct Case { double input; double expected; };
    const Case cases[] = {
        {-2.5, -2.0},  // std::round gave -3
        {-1.5, -1.0},  // std::rint gave -2, std::round gave -2
        {-0.5,  0.0},  // std::rint gave -0, std::round gave -1
        { 0.5,  1.0},  // std::rint gave 0
        { 1.5,  2.0},  // both engines already agreed
        { 2.5,  3.0},  // std::rint gave 2
        { 3.5,  4.0},
    };
    for (const auto& c : cases) {
        const auto expr = Expression::function("rint", {Expression::number(c.input)});
        CHECK_THAT(expr.evaluate(noResolver), WithinRel(c.expected, 1e-12));
    }
}

TEST_CASE("Expression: sign is implemented in the shared evaluator",
          "[Expression][builtins]") {
    // sign() was accepted by the direct-NFsim gate and registered in the
    // ExprTk shim, but had no implementation here, so it evaluated under
    // NFsim and fell through to the user-function resolver under ODE/SSA.
    // Definition matches detail::SignFunction in nfsim_funcparser.h.
    CHECK_THAT(Expression::function("sign", {Expression::number(3.5)})
                   .evaluate(noResolver), WithinRel(1.0, 1e-12));
    CHECK_THAT(Expression::function("sign", {Expression::number(-3.5)})
                   .evaluate(noResolver), WithinRel(-1.0, 1e-12));
    CHECK(Expression::function("sign", {Expression::number(0.0)})
              .evaluate(noResolver) == 0.0);
}

TEST_CASE("Expression: 'log' is rejected with the three explicit spellings",
          "[Expression][builtins]") {
    // BNGL has no bare `log`; the BNG2 table exposes ln, log10, and log2
    // only (Expression.pm:56). ExprTk's `log` is natural, so admitting the
    // name meant a model written expecting base 10 silently got base e.
    // It must not reach the user-function resolver either.
    const auto expr = Expression::function("log", {Expression::number(100.0)});
    CHECK_THROWS_WITH(expr.evaluate(noResolver),
                      Catch::Matchers::ContainsSubstring("ln") &&
                      Catch::Matchers::ContainsSubstring("log10") &&
                      Catch::Matchers::ContainsSubstring("log2"));

    // The three supported spellings each keep their own base.
    CHECK_THAT(Expression::function("ln", {Expression::number(std::exp(1.0))})
                   .evaluate(noResolver), WithinRel(1.0, 1e-10));
    CHECK_THAT(Expression::function("log10", {Expression::number(100.0)})
                   .evaluate(noResolver), WithinRel(2.0, 1e-10));
    CHECK_THAT(Expression::function("log2", {Expression::number(8.0)})
                   .evaluate(noResolver), WithinRel(3.0, 1e-10));
}

TEST_CASE("Builtin table: the two engines agree", "[builtins]") {
    using namespace bng::ast::builtins;

    // The invariant that matters. Before the table existed, the NFsim gate and
    // the shared evaluator kept independent lists and drifted: `sign` and
    // `log` were NFsim-only. If someone teaches one engine a new name, this
    // fails until the other learns it too.
    for (const auto& builtin : kBuiltins) {
        if (builtin.nfsim != NfsimBackend::Unavailable) {
            INFO("NFsim-evaluable builtin missing from the shared evaluator: "
                 << builtin.name);
            CHECK(builtin.sharedEvaluator);
        }
    }

    CHECK_FALSE(isBuiltin("log"));
    CHECK(isNfsimEvaluable("avg"));   // BNG2 builtin, was forcing an XML fallback
    CHECK(isNfsimEvaluable("sign"));

    // Case-SENSITIVE: the shim is compiled with
    // exprtk_disable_caseinsensitivity, so SIN(x) used to pass the gate and
    // then fail inside GlobalFunction::prepareForSimulation().
    CHECK(isNfsimEvaluable("sin"));
    CHECK_FALSE(isNfsimEvaluable("SIN"));

    // Rate-law and table constructs have dedicated lowering and must never be
    // admitted by a generic function gate.
    for (const char* name : {"Sat", "MM", "Hill", "Arrhenius",
                             "FunctionProduct", "TFUN", "tfun"}) {
        INFO("rate-law construct leaked into the generic builtin gate: " << name);
        CHECK_FALSE(isNfsimEvaluable(name));
    }
    // mratio is shared-evaluator only: BNG2 has it, ExprTk has no adapter.
    CHECK_FALSE(isNfsimEvaluable("mratio"));

    CHECK(acceptsArgumentCount("if", 3));
    CHECK_FALSE(acceptsArgumentCount("if", 2));
    CHECK(acceptsArgumentCount("min", 4));       // variadic
    CHECK_FALSE(acceptsArgumentCount("min", 0));
    CHECK(acceptsArgumentCount("sqrt", 1));
    CHECK_FALSE(acceptsArgumentCount("sqrt", 2));
}
