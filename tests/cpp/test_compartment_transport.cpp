#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <string>

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

TEST_CASE("Issue 232 preserves both seeded reversible compartment directions",
          "[Compartment][issue-232]") {
    auto model = parseModel(R"(
begin parameters
    kf 2
    kr 3
end parameters
begin compartments
    C1 3 1
    C2 2 1 C1
    C3 3 1 C2
end compartments
begin molecule types
    A()
    B()
    C()
end molecule types
begin seed species
    A()@C1 1
    B()@C3 1
    C()@C3 1
end seed species
begin reaction rules
    R1: A()@C1 + B()@C3 <-> C()@C3 kf,kr
end reaction rules
)");
    REQUIRE(model != nullptr);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(1);

    REQUIRE(network.reactions.size() == 2);
    const auto reverseCount = std::count_if(
        network.reactions.all().begin(), network.reactions.all().end(),
        [](const auto& reaction) {
            return reaction.getOriginRuleName().find("reverse") !=
                std::string::npos;
        });
    CHECK(reverseCount == 1);
}

TEST_CASE("Issue 246 does not infer adjacency for parentless compartments",
          "[Compartment][issue-246]") {
    auto model = parseModel(R"(
begin parameters
    kon 1.0e-4
end parameters
begin compartments
    EC 3 1
    mem 2 1
end compartments
begin molecule types
    Lig(Site0)
    Receptor(Site0~U~P)
end molecule types
begin seed species
    @mem:Receptor(Site0~U) 1
    @EC:Lig(Site0) 1
end seed species
begin reaction rules
    @EC:Lig(Site0) + @mem:Receptor(Site0~U) -> @mem:Lig(Site0!1).Receptor(Site0~U!1) kon
end reaction rules
)");
    REQUIRE(model != nullptr);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(1);

    CHECK(network.reactions.size() == 0);
}

TEST_CASE("Issue 124 permits parameters after rules and seed species",
          "[Parser][issue-124]") {
    auto model = parseModel(R"(
begin reaction rules
    A() -> B() k2
end reaction rules
begin seed species
    A() 2
    B() 0
end seed species
begin molecule types
    A()
    B()
end molecule types
begin parameters
    k1 1
    k2 k1 + 1
end parameters
)");
    REQUIRE(model != nullptr);
    CHECK(model->getParameters().get("k2").getValue() == 2.0);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative();
    CHECK(network.reactions.size() == 1);
}
