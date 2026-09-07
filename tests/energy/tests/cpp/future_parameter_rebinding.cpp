// RED CONTRACT: compile-once structure must not freeze trajectory-specific energy parameters.
#include <catch2/catch_test_macros.hpp>
#include "compile/CompiledNfBlueprint.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("energy parameter rebinding changes rates without rebuilding structural blueprint") {
    auto model=bng::parser::parseModel(R"BNG(
begin model
begin parameters
 G 1
 phi 0.5
 Ea 1
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin seed species
 A(s~U) 100
end seed species
begin energy patterns
 A(s~P) G
end energy patterns
begin reaction rules
 A(s~U)<->A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model
)BNG");
    REQUIRE(model);
    auto bp=bng::compile::CompiledNfBlueprint::compile(*model);
    const auto builds=bp.structuralBuildCount();
    auto one=bp.instantiate(1,{{"G",1.0}});
    auto two=bp.instantiate(1,{{"G",2.0}});
    REQUIRE(one); REQUIRE(two);
    CHECK(bp.structuralBuildCount()==builds);
    CHECK(one->getAllReactions()[0]->get_a()!=two->getAllReactions()[0]->get_a());
}

TEST_CASE("phi rebinding changes forward/reverse partition without changing compiled graph") {
    auto model=bng::parser::parseModel(R"BNG(
begin model
begin parameters
 G 2
 phi 0.25
 Ea 1
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin seed species
 A(s~U) 100
end seed species
begin energy patterns
 A(s~P) G
end energy patterns
begin reaction rules
 A(s~U)<->A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model
)BNG");
    REQUIRE(model);
    auto bp=bng::compile::CompiledNfBlueprint::compile(*model);
    const auto hash=bp.structuralHash();
    auto a=bp.instantiate(1,{{"phi",0.25}});
    auto b=bp.instantiate(1,{{"phi",0.75}});
    REQUIRE(a); REQUIRE(b);
    CHECK(bp.structuralHash()==hash);
    CHECK(a->getAllReactions()[0]->get_a()!=b->getAllReactions()[0]->get_a());
}

TEST_CASE("same seed and same parameter binding from shared blueprint is deterministic") {
    auto model=bng::parser::parseModel(R"BNG(
begin parameters
 k 1
end parameters
begin molecule types
 A(x)
end molecule types
begin seed species
 A(x) 100
end seed species
begin reaction rules
 A(x)->0 k
end reaction rules
)BNG");
    REQUIRE(model);
    auto bp=bng::compile::CompiledNfBlueprint::compile(*model);
    auto a=bp.instantiate(424242,{{"k",1.5}});
    auto b=bp.instantiate(424242,{{"k",1.5}});
    REQUIRE(a); REQUIRE(b);
    a->stepTo(5.0,true); b->stepTo(5.0,true);
    CHECK(a->getGlobalEventCounter()==b->getGlobalEventCounter());
}

TEST_CASE("structural hash ignores numeric parameter values but includes parameter dependency identity") {
    auto m1=bng::parser::parseModel(R"BNG(
begin parameters
 G 1
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin energy patterns
 A(s~P) G
end energy patterns
end model
)BNG");
    auto m2=bng::parser::parseModel(R"BNG(
begin parameters
 G 99
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin energy patterns
 A(s~P) G
end energy patterns
end model
)BNG");
    auto m3=bng::parser::parseModel(R"BNG(
begin parameters
 H 1
end parameters
begin molecule types
 A(s~U~P)
end molecule types
begin energy patterns
 A(s~P) H
end energy patterns
end model
)BNG");
    REQUIRE(m1);REQUIRE(m2);REQUIRE(m3);
    auto b1=bng::compile::CompiledNfBlueprint::compile(*m1);
    auto b2=bng::compile::CompiledNfBlueprint::compile(*m2);
    auto b3=bng::compile::CompiledNfBlueprint::compile(*m3);
    CHECK(b1.structuralHash()==b2.structuralHash());
    CHECK(b1.structuralHash()!=b3.structuralHash());
}
