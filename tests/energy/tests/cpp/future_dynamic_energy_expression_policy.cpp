// RED CONTRACT: dynamic state-energy expressions must be explicitly supported or explicitly rejected.
#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>
#include "compile/energy/EnergyPatternCompiler.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("parameter-only energy expression is compile-time bindable") {
    auto model=bng::parser::parseModel(R"BNG(
begin parameters
 G0 1
 scale 2
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin energy patterns
 A(s~P) G0*scale
end energy patterns
end model
)BNG");
    REQUIRE(model);
    const auto result=bng::compile::energy::EnergyPatternCompiler::fromModel(*model).diagnostics();
    CHECK(result.dynamicEnergyFactorCount==0);
    CHECK(result.parameterDependentFactorCount==1);
}

TEST_CASE("time-dependent energy factor is never silently frozen at construction time") {
    auto model=bng::parser::parseModel(R"BNG(
begin parameters
 G0 1
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin energy patterns
 A(s~P) G0*time
end energy patterns
end model
)BNG");
    REQUIRE(model);
    const auto compiler=bng::compile::energy::EnergyPatternCompiler::fromModel(*model);
    CHECK_THROWS_WITH(compiler.requireStaticStateEnergies(),
        Catch::Matchers::ContainsSubstring("time-dependent energy"));
}
