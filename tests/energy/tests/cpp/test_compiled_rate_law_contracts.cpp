#include <catch2/catch_test_macros.hpp>

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
