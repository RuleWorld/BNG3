#include <catch2/catch_test_macros.hpp>

#include "parser/BNGAstVisitor.hpp"
#include "engine/NetworkGenerator.hpp"

using namespace bng;

static std::unique_ptr<ast::Model> parseModel(const std::string& bngl) {
    return parser::parseModel(bngl);
}

TEST_CASE("Rule expansion: simple binding A + B -> AB", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    kf 1.0
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
    Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) kf
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() == 3);
    REQUIRE(network.reactions.size() == 1);
}

TEST_CASE("Rule expansion: DeleteMolecules degradation", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    kd 0.1
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b!1).B(a!1) 100
end seed species
begin reaction rules
    A(b!1).B(a!1) -> B(a) kd DeleteMolecules
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.species.size() >= 2);
    REQUIRE(network.reactions.size() >= 1);
}

TEST_CASE("Rule expansion: bidirectional rule decomposition", "[ReactionRule]") {
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
    REQUIRE(network.reactions.size() == 2);
}

TEST_CASE("Rule expansion: MatchOnce modifier", "[ReactionRule]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b,b)
    B(a)
end molecule types
begin seed species
    A(b,b) 100
    B(a) 200
end seed species
begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) k MatchOnce
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    REQUIRE(network.reactions.size() >= 1);
}
