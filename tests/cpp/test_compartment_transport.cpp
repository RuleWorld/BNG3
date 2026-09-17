#include <catch2/catch_test_macros.hpp>

#include "parser/BNGAstVisitor.hpp"
#include "engine/NetworkGenerator.hpp"

using namespace bng;

static std::unique_ptr<ast::Model> parseModel(const std::string& bngl) {
    return parser::parseModel(bngl);
}

TEST_CASE("Compartment transport: endocytosis PM -> EM", "[Compartment]") {
    auto model = parseModel(R"(
begin parameters
    k_endo 0.1
end parameters
begin compartments
    EC 3 1.0
    PM 2 1.0 EC
    CP 3 1.0 PM
    EM 2 1.0 CP
    EN 3 1.0 EM
end compartments
begin molecule types
    R(l)
end molecule types
begin seed species
    @PM:R(l) 100
end seed species
begin reaction rules
    @PM:R(l) -> @EM:R(l) k_endo
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Compartment transport: exocytosis EM -> PM", "[Compartment]") {
    auto model = parseModel(R"(
begin parameters
    k_exo 0.05
end parameters
begin compartments
    EC 3 1.0
    PM 2 1.0 EC
    CP 3 1.0 PM
    EM 2 1.0 CP
    EN 3 1.0 EM
end compartments
begin molecule types
    R(l)
end molecule types
begin seed species
    @EM:R(l) 100
end seed species
begin reaction rules
    @EM:R(l) -> @PM:R(l) k_exo
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Compartment transport: volume-to-volume", "[Compartment]") {
    auto model = parseModel(R"(
begin parameters
    k_trans 0.01
end parameters
begin compartments
    EC 3 1.0
    PM 2 1.0 EC
    CP 3 1.0 PM
end compartments
begin molecule types
    L()
end molecule types
begin seed species
    @EC:L() 100
end seed species
begin reaction rules
    @EC:L() -> @CP:L() k_trans
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Compartment transport: population reaction may consume distinct volumes", "[Compartment]") {
    auto model = parseModel(R"(
begin parameters
    k_bind 0.1
end parameters
begin compartments
    left 3 1.0
    right 3 1.0
end compartments
begin molecule types
    R()
    G()
    RG()
end molecule types
begin seed species
    @left:R() 10
    @right:G() 20
end seed species
begin reaction rules
    @left:R() + @right:G() -> @left:RG() k_bind
end reaction rules
)");

    engine::NetworkGenerator gen(*model);
    const auto network = gen.generateNative(1);

    REQUIRE(network.species.size() == 3);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Compartment transport: cross-volume bond formation remains rejected", "[Compartment]") {
    auto model = parseModel(R"(
begin parameters
    k_bind 0.1
end parameters
begin compartments
    left 3 1.0
    right 3 1.0
end compartments
begin molecule types
    R(b)
    G(a)
end molecule types
begin seed species
    @left:R(b) 1
    @right:G(a) 1
end seed species
begin reaction rules
    @left:R(b) + @right:G(a) -> @left:R(b!1).G(a!1) k_bind
end reaction rules
)");

    engine::NetworkGenerator gen(*model);
    const auto network = gen.generateNative(1);

    REQUIRE(network.reactions.size() == 0);
}

TEST_CASE("Compartment transport: replacement does not dereference deleted reactant", "[Compartment]") {
    auto model = parseModel(R"(
begin compartments
    outer 3 1.0
    inner 3 1.0
end compartments
begin molecule types
    A()
    B()
end molecule types
begin seed species
    @outer:A() 1
end seed species
begin reaction rules
    @outer:A() -> @inner:B() 1
end reaction rules
)");

    engine::NetworkGenerator gen(*model);
    const auto network = gen.generateNative(1);

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 1);
}
