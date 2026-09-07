// RED CONTRACT: compiler hashes are stable to formatting but preserve execution-significant ordering.
#include <catch2/catch_test_macros.hpp>
#include "compile/CompiledModel.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("whitespace and comments do not change compiled structural hash") {
    auto a=bng::parser::parseModel(R"BNG(
begin molecule types
 A(x)
end molecule types
begin seed species
 A(x) 1
end seed species
begin reaction rules
 r: A(x)->0 1
end reaction rules
)BNG");
    auto b=bng::parser::parseModel(R"BNG(
# comment
begin molecule types
    A( x )
end molecule types
begin seed species
 A(x)    1
end seed species
begin reaction rules
 r: A(x) -> 0  1   # comment
end reaction rules
)BNG");
    REQUIRE(a);REQUIRE(b);
    CHECK(bng::compile::CompiledModel(*a).structuralHash()==bng::compile::CompiledModel(*b).structuralHash());
}

TEST_CASE("reaction ordering remains structural-hash significant") {
    const char* first=R"BNG(
begin molecule types
 A(x~U~P)
end molecule types
begin seed species
 A(x~U) 1
end seed species
begin reaction rules
 r1: A(x~U)->A(x~P) 1
 r2: A(x~P)->A(x~U) 2
end reaction rules
)BNG";
    const char* second=R"BNG(
begin molecule types
 A(x~U~P)
end molecule types
begin seed species
 A(x~U) 1
end seed species
begin reaction rules
 r2: A(x~P)->A(x~U) 2
 r1: A(x~U)->A(x~P) 1
end reaction rules
)BNG";
    auto a=bng::parser::parseModel(first),b=bng::parser::parseModel(second);REQUIRE(a);REQUIRE(b);
    CHECK(bng::compile::CompiledModel(*a).structuralHash()!=bng::compile::CompiledModel(*b).structuralHash());
}
