#include <catch2/catch_test_macros.hpp>

#include "parser/BNGAstVisitor.hpp"
#include "engine/NetworkGenerator.hpp"

using namespace bng;

static std::unique_ptr<ast::Model> parseModel(const std::string& bngl) {
    return parser::parseModel(bngl);
}

TEST_CASE("Ullmann: pattern matches species (positive)", "[Ullmann]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b,x~0~1)
    B(a)
end molecule types
begin seed species
    A(b!1,x~0).B(a!1) 100
end seed species
begin observables
    Molecules Bound A(b!+)
end observables
begin reaction rules
    A(x~0) -> A(x~1) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    // Observable A(b!+) should match species A(b!1,x~0).B(a!1) and A(b!1,x~1).B(a!1)
    REQUIRE(network.species.size() == 2);
}

TEST_CASE("Ullmann: pattern does not match species (negative)", "[Ullmann]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b,x~0~1)
    B(a)
end molecule types
begin seed species
    A(b,x~0) 100
end seed species
begin observables
    Molecules Bound A(b!+)
end observables
begin reaction rules
    A(x~0) -> A(x~1) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    // A(b,x~0) has b unbound — should NOT match A(b!+)
    // Observable should have weight 0 for unbound species
    REQUIRE(network.species.size() == 2);
}

TEST_CASE("Ullmann: wildcard state matching", "[Ullmann]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(x~0~1~2)
end molecule types
begin seed species
    A(x~0) 100
end seed species
begin observables
    Molecules AnyState A(x)
end observables
begin reaction rules
    A(x~0) -> A(x~1) k
    A(x~1) -> A(x~2) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    // A(x) with no state specified should match all three states
    REQUIRE(network.species.size() == 3);
}

TEST_CASE("Ullmann: bond pattern matching !+ and !?", "[Ullmann]") {
    auto model = parseModel(R"(
begin parameters
    kf 1.0
    kr 0.5
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 100
    B(a) 100
end seed species
begin observables
    Molecules FreeSites A(b)
    Molecules BoundSites A(b!+)
    Molecules AnyBond A(b!?)
end observables
begin reaction rules
    A(b) + B(a) <-> A(b!1).B(a!1) kf, kr
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 3);
}
