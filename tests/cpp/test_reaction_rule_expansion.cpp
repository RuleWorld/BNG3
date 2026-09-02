#include <catch2/catch_test_macros.hpp>
#include <utility>

#include "parser/BNGAstVisitor.hpp"
#include "engine/NetworkGenerator.hpp"

using namespace bng;

static std::unique_ptr<ast::Model> parseModel(const std::string& bngl) {
    return parser::parseModel(bngl);
}

TEST_CASE("Rule expansion: pattern metadata survives reinitialization and move", "[ReactionRule]") {
    // Source-derived from akutuva21/bionetgen commit 7ee2db11: immutable
    // pattern metadata is rebuilt on initialize() and must survive moving a
    // fully initialized rule into the owning model before expansion.
    auto model = parseModel(R"(
begin parameters
    kf 1.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
end seed species
begin reaction rules
    A() -> B() kf
end reaction rules
)");

    auto rule = std::move(model->getReactionRules().front());
    model->getReactionRules().clear();
    rule.initialize();
    model->addReactionRule(std::move(rule));

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(5);

    REQUIRE(network.species.size() == 2);
    REQUIRE(network.reactions.size() == 1);
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

TEST_CASE("Rule expansion: deleting a bound molecule preserves a free site", "[ReactionRule]") {
    // BNG2 serializes an unbound component without an edge marker.  A
    // DeleteMolecules product must therefore remain the same species as the
    // independently seeded BNG2-equivalent graph, even when the deleted bond
    // was the component's only explicit internal unbound marker.
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    DNA(p1,p2)
    P1(dna)
    TF(d,dna)
    Sink()
end molecule types
begin seed species
    DNA(p1!1!2,p2).TF(d!3,dna!2).TF(d!3,dna!1) 1
    DNA(p1!1!2,p2!4).P1(dna!4).TF(d!3,dna!1).TF(d!3,dna!2) 1
end seed species
begin reaction rules
    P1 -> Sink() k DeleteMolecules
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(4);

    std::size_t targetCount = 0;
    for (std::size_t index = 0; index < network.species.size(); ++index) {
        const auto text = network.species.get(index).getSpeciesGraph().toString();
        REQUIRE_FALSE(text.empty());
        if (text.find("DNA(p1!1!2,p2)") == 0 && text.find("TF(") != std::string::npos &&
            text.find("P1(") == std::string::npos) {
            ++targetCount;
        }
    }
    REQUIRE(targetCount == 1);
    REQUIRE(network.reactions.size() == 1);
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
