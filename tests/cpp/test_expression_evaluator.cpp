#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

#include "ast/Expression.hpp"

using namespace bng::ast;
using Catch::Matchers::WithinRel;

static double noResolver(const std::string& name) {
    throw std::runtime_error("Unknown identifier: " + name);
}

TEST_CASE("Expression: numeric literals", "[Expression]") {
    auto expr = Expression::number(42.0);
    REQUIRE(expr.evaluate(noResolver) == 42.0);
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
