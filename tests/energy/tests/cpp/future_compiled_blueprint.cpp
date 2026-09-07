// RED CONTRACT: parse/compile once, instantiate many independent NFsim systems.
#include <catch2/catch_test_macros.hpp>
#include "compile/CompiledNfBlueprint.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("NF blueprint is immutable and creates independent trajectory state") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
 A(x)
 B(y)
end molecule types
begin seed species
 A(x) 10
 B(y) 10
end seed species
begin reaction rules
 A(x)+B(y)->A(x!1).B(y!1) 1
end reaction rules
)BNG");
    REQUIRE(model);
    const auto blueprint = bng::compile::CompiledNfBlueprint::compile(*model);
    auto a = blueprint.instantiate(1);
    auto b = blueprint.instantiate(2);
    REQUIRE(a);
    REQUIRE(b);
    CHECK(a.get() != b.get());
    CHECK(blueprint.structuralHash() == blueprint.structuralHash());
    a->stepTo(1.0);
    CHECK(b->getCurrentTime() == 0.0);
}

TEST_CASE("parameter-only instantiation does not rebuild structural matcher tables") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
 k 1
end parameters
begin molecule types
 A(x)
end molecule types
begin seed species
 A(x) 10
end seed species
begin reaction rules
 A(x)->A(x) k
end reaction rules
)BNG");
    REQUIRE(model);
    auto blueprint = bng::compile::CompiledNfBlueprint::compile(*model);
    const auto structuralBuilds = blueprint.structuralBuildCount();
    auto a = blueprint.instantiate(1, {{"k",1.0}});
    auto b = blueprint.instantiate(2, {{"k",2.0}});
    REQUIRE(a); REQUIRE(b);
    CHECK(blueprint.structuralBuildCount() == structuralBuilds);
}
