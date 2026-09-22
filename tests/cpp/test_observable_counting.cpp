/// test_observable_counting.cpp
///
/// Coverage for the two BNG2 observable counting modes, which were absent from
/// BNG3 entirely before this work: neither `MoleculesObservables` nor
/// `SpeciesObservables` occurred anywhere in `cpp/`, `python/`, `tests/`, or
/// `models/`, so a model setting either one silently received `CountAll`
/// values.
///
/// The two options share the `CountUnique`/`CountAll` spelling but select
/// different operations. Oracle: `legacy/perl/Perl2/Observable.pm`.
///
///   Molecules + CountAll     total += match_count
///   Molecules + CountUnique  total += match_count / Automorphisms
///   Species   + CountAll     total += 1 per matching pattern
///   Species   + CountUnique  total += 1, then `last` — a species contributes
///                            once however many of the observable's patterns
///                            it matches
///
/// Symmetry correction is commented out on the Species branch in BNG2, which
/// is why the Species flag short-circuits instead of dividing. Confusing the
/// two would produce plausible-looking but wrong observable values, so the
/// distinction is asserted directly.

#include <catch2/catch_test_macros.hpp>

#include <memory>
#include <string>

#include "ast/Model.hpp"
#include "compile/CompiledModel.hpp"
#include "compile/Document.hpp"
#include "compile/PatternLowering.hpp"
#include "core/PatternMatching.hpp"
#include "engine/ObservableProjection.hpp"
#include "parser/BNGAstVisitor.hpp"

namespace {

/// A symmetric homodimer. `A(b!1).A(b!1)` has two automorphisms because the
/// two A molecules are interchangeable, so it embeds into a dimer species
/// twice and CountAll/CountUnique must differ by exactly that factor. An
/// asymmetric pattern would make the two modes indistinguishable and the test
/// vacuous.
std::string symmetricDimerModel(const std::string& option) {
    return "begin model\n" + option + R"BNGL(
begin parameters
  n  100
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b!1).A(b!1)  n
end seed species
begin observables
  Molecules Dimer  A(b!1).A(b!1)
end observables
end model
)BNGL";
}

/// One Species observable with two patterns that both match the same species.
std::string overlappingSpeciesModel(const std::string& option) {
    return "begin model\n" + option + R"BNGL(
begin parameters
  n  10
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0)  n
end seed species
begin observables
  Species Both  A(), A(s~0)
end observables
end model
)BNGL";
}

struct Compiled {
    std::unique_ptr<bng::ast::Model> model;
    std::unique_ptr<bng::compile::Document> document;

    const bng::compile::CompiledModel& compiled() const { return document->model(); }
};

Compiled compileModel(const std::string& bngl) {
    Compiled out;
    out.model = bng::parser::parseModel(bngl);
    REQUIRE(out.model != nullptr);
    out.document = std::make_unique<bng::compile::Document>(*out.model);
    REQUIRE(out.document->valid());
    return out;
}

/// The single seed species, lowered to the matcher's representation.
BNGcore::PatternGraph seedSpeciesGraph(const Compiled& compiled) {
    const auto& model = compiled.compiled();
    REQUIRE(model.seeds().size() == 1);
    // The lowering context owns the BNGcore type objects the graph points
    // to, so returning a graph from a function-local context would leave it
    // with dangling pointers. Keep every context alive for the test lifetime.
    static std::vector<std::unique_ptr<bng::compile::BNGcoreLoweringContext>> keeps;
    keeps.push_back(std::make_unique<bng::compile::BNGcoreLoweringContext>(model));
    return bng::compile::lowerPatternToBNGcore(model.seeds().front().pattern, *keeps.back());
}

} // namespace

TEST_CASE("Observables: the symmetric dimer pattern really has two automorphisms",
          "[observables][counting]") {
    // Guard for the tests below. If the matcher ever stopped reporting both
    // embeddings of the homodimer into itself, CountAll and CountUnique would
    // agree and those tests would pass without proving anything.
    const auto compiled = compileModel(symmetricDimerModel(""));
    bng::compile::BNGcoreLoweringContext context(compiled.compiled());
    const auto pattern = bng::compile::lowerPatternToBNGcore(
        compiled.compiled().observables().front().terms.front().pattern, context);
    CHECK(bng::core::countPatternMatches(pattern, pattern) == 2);
}

TEST_CASE("Observables: Molecules CountAll counts every match",
          "[observables][counting]") {
    // Default behavior with the option absent, and explicitly with CountAll.
    // Both must report 2 for one symmetric dimer: the pattern embeds twice.
    for (const char* option : {"", "setOption(\"MoleculesObservables\",\"CountAll\")\n"}) {
        INFO("option: " << option);
        const auto compiled = compileModel(symmetricDimerModel(option));
        const bng::engine::ObservableProjection projection(compiled.compiled());
        REQUIRE(projection.size() == 1);
        REQUIRE(projection.name(0) == "Dimer");
        CHECK(projection.weight(0, seedSpeciesGraph(compiled)) == 2);
    }
}

TEST_CASE("Observables: Molecules CountUnique divides out pattern automorphisms",
          "[observables][counting]") {
    // Same species, same pattern, one option changed: 2 matches / 2
    // automorphisms = 1. The division is asserted exact in the projector
    // rather than truncated, because Aut(P) acts freely on embeddings so the
    // quotient is always an integer.
    const auto compiled = compileModel(
        symmetricDimerModel("setOption(\"MoleculesObservables\",\"CountUnique\")\n"));
    const bng::engine::ObservableProjection projection(compiled.compiled());
    REQUIRE(projection.size() == 1);
    CHECK(projection.weight(0, seedSpeciesGraph(compiled)) == 1);
}

TEST_CASE("Observables: Species CountUnique counts a species once, not per pattern",
          "[observables][counting]") {
    // `A()` and `A(s~0)` both match the seed species. CountAll adds one per
    // matching pattern; CountUnique stops after the first.
    const auto all = compileModel(
        overlappingSpeciesModel("setOption(\"SpeciesObservables\",\"CountAll\")\n"));
    const bng::engine::ObservableProjection allProjection(all.compiled());
    REQUIRE(allProjection.size() == 1);
    CHECK(allProjection.weight(0, seedSpeciesGraph(all)) == 2);

    const auto unique = compileModel(
        overlappingSpeciesModel("setOption(\"SpeciesObservables\",\"CountUnique\")\n"));
    const bng::engine::ObservableProjection uniqueProjection(unique.compiled());
    REQUIRE(uniqueProjection.size() == 1);
    CHECK(uniqueProjection.weight(0, seedSpeciesGraph(unique)) == 1);
}

TEST_CASE("Observables: the two counting options are independent",
          "[observables][counting]") {
    // Setting the Species mode must not silently change a Molecules
    // observable, which is the mistake the shared CountUnique spelling
    // invites.
    const auto compiled = compileModel(
        symmetricDimerModel("setOption(\"SpeciesObservables\",\"CountUnique\")\n"));
    const bng::engine::ObservableProjection projection(compiled.compiled());
    REQUIRE(projection.size() == 1);
    CHECK(projection.weight(0, seedSpeciesGraph(compiled)) == 2);
}
