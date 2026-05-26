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
