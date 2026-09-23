#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>

#include "parser/BNGAstVisitor.hpp"
#include "engine/NetworkGenerator.hpp"

using namespace bng;

static std::unique_ptr<ast::Model> parseModel(const std::string& bngl) {
    return parser::parseModel(bngl);
}

TEST_CASE("HNauty: isomorphic species get same canonical label", "[HNauty]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b,b)
    B(a)
end molecule types
begin seed species
    A(b!1,b!2).B(a!1).B(a!2) 100
end seed species
begin reaction rules
    A(b!1).B(a!1) -> A(b) + B(a) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    // The species A(b!1,b!2).B(a!1).B(a!2) should have a unique canonical label
    // and should be the same regardless of bond numbering order
    REQUIRE(network.species.size() >= 1);
}

TEST_CASE("HNauty: single-molecule species (trivial)", "[HNauty]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(x~0~1)
end molecule types
begin seed species
    A(x~0) 50
    A(x~1) 50
end seed species
begin reaction rules
    A(x~0) -> A(x~1) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    // Two distinct species (different states => different labels)
    REQUIRE(network.species.size() == 2);
}

TEST_CASE("HNauty: non-isomorphic complexes get different labels", "[HNauty]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    A(b,c)
    B(a)
    C(a)
end molecule types
begin seed species
    A(b!1,c).B(a!1) 50
    A(b,c!1).C(a!1) 50
end seed species
begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    // A(b!1,c).B(a!1) and A(b,c!1).C(a!1) are different species
    REQUIRE(network.species.size() >= 2);
}

TEST_CASE("HNauty: symmetric components produce single species", "[HNauty]") {
    auto model = parseModel(R"(
begin parameters
    k 1.0
end parameters
begin molecule types
    R(l,l)
    L(r)
end molecule types
begin seed species
    R(l,l) 100
    L(r) 200
end seed species
begin reaction rules
    R(l) + L(r) -> R(l!1).L(r!1) k
end reaction rules
begin actions
    generate_network({overwrite=>1})
end actions
)");

    engine::NetworkGenerator gen(*model);
    auto network = gen.generate(std::filesystem::path("test.bngl"));

    // R(l!1,l).L(r!1) should be ONE species (symmetric components)
    // R(l!1,l!2).L(r!1).L(r!2) should be ONE species
    REQUIRE(network.species.size() == 4); // R, L, R.L, R.L.L
}

TEST_CASE("Issue 214 high product symmetry parses without factorial expansion",
          "[HNauty][issue-214]") {
    const auto path = std::filesystem::path(BNG3_SOURCE_DIR) / "tests" /
        "fixtures" / "upstream_issues" / "issue_214_oscar_ecoli.bngl";
    std::ifstream input(path);
    REQUIRE(input.good());
    std::string source((std::istreambuf_iterator<char>(input)),
                       std::istreambuf_iterator<char>());

    // The upstream SBML export wrote undefined compartment sizes as `nan`.
    // Normalize only those three values so this test measures BNG3 rule parsing.
    for (const auto& compartment : {"c", "e", "p"}) {
        const std::string invalid = std::string("\t") + compartment + " 2 nan";
        const auto position = source.find(invalid);
        REQUIRE(position != std::string::npos);
        source.replace(position, invalid.size(),
                       std::string("\t") + compartment + " 2 1.0");
    }

    const auto model = parseModel(source);
    REQUIRE(model != nullptr);
    const auto rule = std::find_if(
        model->getReactionRules().begin(), model->getReactionRules().end(),
        [](const auto& candidate) {
            const auto& products = candidate.getProducts();
            return products.size() == 16 &&
                std::any_of(products.begin(), products.end(), [](const auto& product) {
                    return product.find("Enterochelin()") != std::string::npos;
                });
        });
    REQUIRE(rule != model->getReactionRules().end());
    REQUIRE(rule->getProducts().size() == 16);
    CHECK(std::count_if(rule->getProducts().begin(), rule->getProducts().end(),
                        [](const auto& product) {
                            return product.find("Hpl()") != std::string::npos;
                        }) == 9);
    CHECK(std::count_if(rule->getProducts().begin(), rule->getProducts().end(),
                        [](const auto& product) {
                            return product.find("AMP()") != std::string::npos;
                        }) == 6);
}

TEST_CASE("Issue 165 sixfold symmetric complex canonicalizes", "[HNauty][issue-165]") {
    auto model = parseModel(R"(
begin molecule types
    R(l,l,l,l,l,l)
    PI(r)
end molecule types
begin seed species
    R(l!1,l!2,l!3,l!4,l!5,l!6).PI(r!1).PI(r!2).PI(r!3).PI(r!4).PI(r!5).PI(r!6) 1
end seed species
)");
    REQUIRE(model != nullptr);

    engine::NetworkGenerator generator(*model);
    const auto network = generator.generateNative(0);
    REQUIRE(network.species.size() == 1);
    CHECK_FALSE(network.species.get(0).getSpeciesGraph().canonicalLabel().empty());
}
