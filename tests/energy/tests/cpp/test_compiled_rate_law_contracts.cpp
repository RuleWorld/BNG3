#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>

#include "compile/CompiledRateLaw.hpp"
#include "compile/CompiledModel.hpp"
#include "compile/SymbolTable.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("rate-law classifier recognizes all supported top-level families") {
    struct Case { const char* expr; bng::compile::RateLawKind expected; };
    const Case cases[] = {
        {"Arrhenius(phi,Ea)", bng::compile::RateLawKind::ArrheniusEnergy},
        {"Sat(k0,K)", bng::compile::RateLawKind::Saturation},
        {"MM(kcat,Km)", bng::compile::RateLawKind::MichaelisMenten},
        {"Hill(Vmax,Kh,n)", bng::compile::RateLawKind::Hill},
        {"FunctionProduct(k,f)", bng::compile::RateLawKind::FunctionProduct},
    };
    for (const auto& c : cases) {
        INFO(c.expr);
        const auto rate = bng::compile::CompiledRateLaw::compile(bng::parser::parseExpression(c.expr));
        CHECK(rate.kind == c.expected);
        CHECK(rate.sourceExpression.size() > 0);
    }
}

TEST_CASE("nested arithmetic containing Arrhenius is not misclassified as top-level Arrhenius") {
    const auto rate = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("2*Arrhenius(phi,Ea)"));
    CHECK(rate.kind != bng::compile::RateLawKind::ArrheniusEnergy);
}

TEST_CASE("rate-law classifier is case-insensitive for builtin families") {
    const auto a=bng::compile::CompiledRateLaw::compile(bng::parser::parseExpression("ARRHENIUS(phi,Ea)"));
    const auto h=bng::compile::CompiledRateLaw::compile(bng::parser::parseExpression("Hybrid(k1,k2)"));
    CHECK(a.kind==bng::compile::RateLawKind::ArrheniusEnergy);
    CHECK(h.kind==bng::compile::RateLawKind::Hybrid);
}

TEST_CASE("unknown top-level function remains generic expression") {
    const auto r=bng::compile::CompiledRateLaw::compile(bng::parser::parseExpression("custom_rate(k)"));
    CHECK(r.kind==bng::compile::RateLawKind::Expression);
    CHECK_FALSE(r.isEnergyCoupled());
}

TEST_CASE("SBML factorial lowers as a typed builtin") {
    const auto expression = bng::parser::parseExpression("factorial(5)");
    const bng::compile::SymbolTable symbols;
    const auto rate = bng::compile::CompiledRateLaw::compile(expression, symbols);
    REQUIRE(rate.diagnostics().empty());
    CHECK(rate.resolvedExpression().kind ==
          bng::compile::ResolvedExpressionKind::BuiltinCall);
    REQUIRE(rate.resolvedExpression().builtin.has_value());
    CHECK(*rate.resolvedExpression().builtin ==
          bng::compile::BuiltinFunction::Factorial);
}

TEST_CASE("rate-law references resolve through typed semantic symbols") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
  k 1
end parameters
begin molecule types
  A(x)
end molecule types
begin seed species
  A(x) 1
end seed species
begin observables
  Molecules count A(x)
end observables
)BNG");
    REQUIRE(model != nullptr);
    const auto symbols = bng::compile::SymbolTable::fromModel(*model);

    const auto resolved = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("k + count"), symbols);
    CHECK(resolved.diagnostics().empty());
    CHECK(resolved.references().size() == 2);
    CHECK(resolved.resolvedExpression().kind ==
          bng::compile::ResolvedExpressionKind::Binary);
    REQUIRE(resolved.resolvedExpression().arguments.size() == 2);
    CHECK(resolved.resolvedExpression().arguments[0].kind ==
          bng::compile::ResolvedExpressionKind::ParameterRef);
    CHECK(resolved.resolvedExpression().arguments[0].symbol->kind ==
          bng::compile::SymbolKind::Parameter);
    CHECK(resolved.resolvedExpression().arguments[1].kind ==
          bng::compile::ResolvedExpressionKind::ObservableRef);
    CHECK(resolved.resolvedExpression().arguments[1].symbol->kind ==
          bng::compile::SymbolKind::Observable);

    const auto unresolved = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("k + missing"), symbols);
    REQUIRE(unresolved.diagnostics().size() == 1);
    CHECK(unresolved.diagnostics().front().category ==
          bng::compile::ValidationCategory::Expressions);
    CHECK(unresolved.diagnostics().front().severity == bng::compile::Severity::Error);
}

TEST_CASE("resolved rate laws retain lexical local references") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
 k 1
end parameters
begin molecule types
 A(x)
end molecule types
begin functions
 local(x) = k
end functions
begin reaction rules
 r: %x::A() -> %x::A() local(x)
end reaction rules
)BNG");
    REQUIRE(model);
    const bng::compile::CompiledModel compiled(*model);
    REQUIRE(compiled.diagnostics().empty());
    REQUIRE(compiled.rules().size() == 1);
    const auto& expression = compiled.rules()[0].rateLaws()[0].resolvedExpression();
    REQUIRE(expression.arguments.size() == 1);
    CHECK(expression.arguments[0].kind ==
          bng::compile::ResolvedExpressionKind::LocalRef);
    CHECK(expression.arguments[0].localName == "x");
}

TEST_CASE("compiled rate law exposes typed dependency kinds") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
  k 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules count A()
end observables
begin functions
  f(x) = x
end functions
)BNG");
    REQUIRE(model != nullptr);
    const auto symbols = bng::compile::SymbolTable::fromModel(*model);
    const auto rate = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression(
            "k + count + f(x) + time + reactant_1 + TFUN([0, 1], [1, 2], time)"),
        symbols, {"x"});

    REQUIRE(rate.diagnostics().empty());
    CHECK(rate.fullyResolved());
    const auto& dependencies = rate.dependencies();
    CHECK(dependencies.parameter);
    CHECK(dependencies.observable);
    CHECK(dependencies.function);
    CHECK(dependencies.local);
    CHECK(dependencies.reactantCount);
    CHECK(dependencies.time);
    CHECK(dependencies.tableFunction);
    CHECK_FALSE(dependencies.unresolved);

    const auto repeated = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("k + k"), symbols);
    CHECK_FALSE(repeated.dependencies().requiresRuntimeEvaluation());
    CHECK(repeated.references().size() == 1);
    REQUIRE(repeated.resolvedExpression().arguments.size() == 2);
    REQUIRE(repeated.resolvedExpression().arguments[0].symbol.has_value());
    REQUIRE(repeated.resolvedExpression().arguments[1].symbol.has_value());
    CHECK(repeated.resolvedExpression().arguments[0].symbol->kind ==
          repeated.resolvedExpression().arguments[1].symbol->kind);
    CHECK(repeated.resolvedExpression().arguments[0].symbol->index ==
          repeated.resolvedExpression().arguments[1].symbol->index);

    const auto fileTable = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("TFUN('rates.dat', time)"), symbols);
    REQUIRE(fileTable.resolvedExpression().kind ==
            bng::compile::ResolvedExpressionKind::TableFunction);
    CHECK(fileTable.resolvedExpression().tableFile == "rates.dat");
    CHECK(fileTable.dependencies().tableFunction);
    CHECK(fileTable.dependencies().time);

    const auto untyped = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("k"));
    CHECK(untyped.dependencies().unresolved);
    CHECK(untyped.dependencies().requiresRuntimeEvaluation());
}

TEST_CASE("CompiledRateLaw evaluates constant and parametric rate expressions directly") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
  k 2.5
  c 3.0
end parameters
begin molecule types
  A()
end molecule types
)BNG");
    REQUIRE(model != nullptr);
    const auto symbols = bng::compile::SymbolTable::fromModel(*model);
    const auto rate = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("k * 2.0 + c"), symbols);
    REQUIRE(rate.diagnostics().empty());
    REQUIRE(rate.fullyResolved());

    bng::compile::RateEvaluationContext ctx;
    ctx.resolveParameter = [&](std::size_t index, const std::string& name) -> double {
        if (name == "k" || index == 0) return 2.5;
        if (name == "c" || index == 1) return 3.0;
        return 0.0;
    };
    CHECK(rate.evaluate(ctx) == Catch::Approx(8.0));

    // Also test convenience overload with name resolver
    CHECK(rate.evaluate([](const std::string& name) {
        if (name == "k") return 2.5;
        if (name == "c") return 3.0;
        return 0.0;
    }) == Catch::Approx(8.0));
}

TEST_CASE("CompiledRateLaw evaluates time, observable, and reactant count dependencies") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
end molecule types
begin observables
  Molecules count A()
end observables
)BNG");
    REQUIRE(model != nullptr);
    const auto symbols = bng::compile::SymbolTable::fromModel(*model);
    const auto rate = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("k * count + time * reactant_1"), symbols);
    REQUIRE(rate.diagnostics().empty());
    REQUIRE(rate.fullyResolved());
    CHECK(rate.dependsOnTime());
    CHECK(rate.dependsOnObservables());
    CHECK(rate.dependsOnReactantCounts());
    CHECK(rate.dependsOnParameters());

    bng::compile::RateEvaluationContext ctx;
    ctx.time = 2.0;
    ctx.resolveParameter = [](std::size_t, const std::string&) { return 0.5; };
    ctx.resolveObservable = [](std::size_t, const std::string&) { return 5.0; };
    ctx.resolveReactantCount = [](std::size_t idx) { return (idx == 0) ? 3.0 : 0.0; };

    // 0.5 * 5.0 + 2.0 * 3.0 = 2.5 + 6.0 = 8.5
    CHECK(rate.evaluate(ctx) == Catch::Approx(8.5));
}

TEST_CASE("CompiledRateLaw evaluates special rate law families") {
    const bng::compile::SymbolTable emptySymbols;

    // Saturation: Sat(k0, K, S) -> k0 * S / (K + S)
    const auto satRate = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("Sat(0.4, 10.0, 20.0)"), emptySymbols);
    REQUIRE(satRate.fullyResolved());
    CHECK(satRate.evaluate(bng::compile::RateEvaluationContext{}) ==
          Catch::Approx(0.4 * 20.0 / (10.0 + 20.0)));

    // Hill: Hill(Vmax, Kh, n, S) -> Vmax * S^n / (Kh^n + S^n)
    const auto hillRate = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("Hill(1.0, 5.0, 2.0, 5.0)"), emptySymbols);
    REQUIRE(hillRate.fullyResolved());
    CHECK(hillRate.evaluate(bng::compile::RateEvaluationContext{}) == Catch::Approx(0.5));

    // FunctionProduct: FunctionProduct(v1, v2) -> v1 * v2
    const auto fpRate = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("FunctionProduct(3.0, 4.0)"), emptySymbols);
    REQUIRE(fpRate.fullyResolved());
    CHECK(fpRate.evaluate(bng::compile::RateEvaluationContext{}) == Catch::Approx(12.0));

    // Arrhenius: Arrhenius(A, Ea) with Ea=0 -> A
    const auto arrRate = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("Arrhenius(100.0, 0.0)"), emptySymbols);
    REQUIRE(arrRate.fullyResolved());
    CHECK(arrRate.evaluate(bng::compile::RateEvaluationContext{}) == Catch::Approx(100.0));
}

TEST_CASE("CompiledRateLaw evaluates table functions with interpolation") {
    const bng::compile::SymbolTable emptySymbols;
    const auto tfunLinear = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("TFUN([0.0, 1.0, 2.0], [10.0, 20.0, 30.0], time)"),
        emptySymbols);
    REQUIRE(tfunLinear.fullyResolved());

    bng::compile::RateEvaluationContext ctx;
    ctx.time = 0.5;
    CHECK(tfunLinear.evaluate(ctx) == Catch::Approx(15.0));
    ctx.time = 1.5;
    CHECK(tfunLinear.evaluate(ctx) == Catch::Approx(25.0));
    ctx.time = 3.0; // clamp upper
    CHECK(tfunLinear.evaluate(ctx) == Catch::Approx(30.0));
}

TEST_CASE("CompiledRateLaw dependency invalidation accurately tracks parameters, observables, and time") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
  k1 1.0
  k2 2.0
end parameters
begin molecule types
  A()
end molecule types
begin observables
  Molecules obs1 A()
end observables
)BNG");
    REQUIRE(model != nullptr);
    const auto symbols = bng::compile::SymbolTable::fromModel(*model);

    const auto rate1 = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("k1 + obs1"), symbols);
    const auto rate2 = bng::compile::CompiledRateLaw::compile(
        bng::parser::parseExpression("k2 * time"), symbols);

    // Queries by parameter
    CHECK(rate1.dependsOnParameter(0)); // k1 is param index 0
    CHECK_FALSE(rate1.dependsOnParameter(1)); // k2 is param index 1
    CHECK(rate1.dependsOnParameter("k1"));
    CHECK_FALSE(rate1.dependsOnParameter("k2"));

    CHECK_FALSE(rate2.dependsOnParameter(0));
    CHECK(rate2.dependsOnParameter(1)); // k2 is param index 1
    CHECK(rate2.dependsOnParameter("k2"));

    // Queries by observable
    CHECK(rate1.dependsOnObservable(0)); // obs1 is obs index 0
    CHECK(rate1.dependsOnObservable("obs1"));
    CHECK_FALSE(rate2.dependsOnObservable(0));

    // Queries by time
    CHECK_FALSE(rate1.dependsOnTime());
    CHECK(rate2.dependsOnTime());

    // Invalidation behavior
    // Parameter 0 modified: rate1 invalidated, rate2 retained
    CHECK(rate1.isInvalidatedBy(false, {0}, {}));
    CHECK_FALSE(rate2.isInvalidatedBy(false, {0}, {}));

    // Parameter 1 modified: rate1 retained, rate2 invalidated
    CHECK_FALSE(rate1.isInvalidatedBy(false, {1}, {}));
    CHECK(rate2.isInvalidatedBy(false, {1}, {}));

    // Observable 0 modified: rate1 invalidated, rate2 retained
    CHECK(rate1.isInvalidatedBy(false, {}, {0}));
    CHECK_FALSE(rate2.isInvalidatedBy(false, {}, {0}));

    // Time advanced: rate1 retained, rate2 invalidated
    CHECK_FALSE(rate1.isInvalidatedBy(true, {}, {}));
    CHECK(rate2.isInvalidatedBy(true, {}, {}));
}

TEST_CASE("CompiledRateLaw evaluates after source ast::Model is destroyed (AST lifetime independence guard)") {
    bng::compile::CompiledRateLaw compiledRate;
    {
        auto model = bng::parser::parseModel(R"BNG(
begin parameters
  k 42.0
end parameters
begin molecule types
  A()
end molecule types
)BNG");
        REQUIRE(model != nullptr);
        const auto symbols = bng::compile::SymbolTable::fromModel(*model);
        const auto expr = bng::parser::parseExpression("k * 2.0");
        compiledRate = bng::compile::CompiledRateLaw::compile(expr, symbols);
        // `model` and `expr` go out of scope and are deleted here
    }

    REQUIRE(compiledRate.fullyResolved());
    bng::compile::RateEvaluationContext ctx;
    ctx.resolveParameter = [](std::size_t, const std::string&) { return 42.0; };

    // Evaluates completely independently of the destroyed AST
    CHECK(compiledRate.evaluate(ctx) == Catch::Approx(84.0));
}

TEST_CASE("Shared evaluateRateString evaluates nested expressions, unary signs, exponentials, and whitespace") {
    auto resolver = [](const std::string& name) -> double {
        if (name == "k") return 10.0;
        if (name == "c") return 4.0;
        return 0.0;
    };

    CHECK(bng::compile::evaluateRateString(" 12.5 ", resolver) == Catch::Approx(12.5));
    CHECK(bng::compile::evaluateRateString(" (k + c) * 2 ", resolver) == Catch::Approx(28.0));
    CHECK(bng::compile::evaluateRateString(" k - (-c) ", resolver) == Catch::Approx(14.0));
    CHECK(bng::compile::evaluateRateString(" exp(0) ", resolver) == Catch::Approx(1.0));
    CHECK(bng::compile::evaluateRateString(" (k * c) / 8 ", resolver) == Catch::Approx(5.0));
    CHECK(bng::compile::evaluateRateString(" -k ", resolver) == Catch::Approx(-10.0));
}
