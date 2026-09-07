#include <catch2/catch_test_macros.hpp>

#include "compile/CompiledRateLaw.hpp"
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
