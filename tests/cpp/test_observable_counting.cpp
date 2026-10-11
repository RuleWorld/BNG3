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
///   Species   + CountUnique  a qualified term applies `last` even when the
///                            relation is false; an unqualified term applies
///                            `last` only after a structural match
///
/// Symmetry correction is commented out on the Species branch in BNG2, which
/// is why the Species flag short-circuits instead of dividing. Confusing the
/// two would produce plausible-looking but wrong observable values, so the
/// distinction is asserted directly.

#include <catch2/catch_test_macros.hpp>

#include <memory>
#include <string>
#include <vector>

#include "ast/Model.hpp"
#include "ast/Observable.hpp"
#include "compile/CompiledModel.hpp"
#include "compile/Document.hpp"
#include "compile/PatternLowering.hpp"
#include "core/PatternMatching.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/ObservableProjection.hpp"
#include "io/RegulatoryGraphWriter.hpp"
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

std::string relationalMoleculesModel(const std::string& option) {
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
  Molecules Dimer A(b!1).A(b!1)>5
  Species MatchCountAboveOne A(b!1).A(b!1)>1
  Species MatchCountAboveTwo A(b!1).A(b!1)>2
end observables
end model
)BNGL";
}

std::string compartmentPrefixObservableModel() {
    return R"BNGL(
begin model
begin parameters
  n_pm 5
  n_cp 7
end parameters
begin molecule types
  L(x)
  R(y)
end molecule types
begin compartments
  PM 2 1
  CP 3 1 PM
end compartments
begin seed species
  @PM:L(x!1)@CP.R(y!1) n_pm
  @CP:L(x!1).R(y!1) n_cp
end seed species
begin observables
  Molecules PrefixAndNode @PM:L(x!1)@CP.R(y!1)
  Molecules NodeOnly L(x!1)@CP.R(y!1)
  Molecules MixedTerms @PM:L(x!1)@CP.R(y!1), L(x!1)@CP.R(y!1)
end observables
end model
)BNGL";
}

std::string allExplicitCompartmentPrefixModel() {
    return R"BNGL(
begin model
begin parameters
  n 5
end parameters
begin molecule types
  L(x)
  R(y)
end molecule types
begin compartments
  PM 2 1
  CP 3 1 PM
end compartments
begin seed species
  @PM:L@CP(x!1).R@PM(y!1) n
end seed species
begin observables
  Molecules AllExplicitPrefix @PM:L@CP(x!1).R@PM(y!1)
end observables
end model
)BNGL";
}

std::string regulatoryGraphCompartmentPrefixModel() {
    return R"BNGL(
begin model
begin parameters
  k 1
  n_pm 5
  n_cp 7
end parameters
begin molecule types
  L(x)
  R(y~u~p)
end molecule types
begin compartments
  PM 2 1
  CP 3 1 PM
end compartments
begin seed species
  @PM:L(x!1)@CP.R(y~u!1) n_pm
  @CP:L(x!1).R(y~u!1) n_cp
end seed species
begin observables
  Molecules PrefixAndNode @PM:L(x!1)@CP.R(y~u!1)
  Molecules NodeOnly L(x!1)@CP.R(y~u!1)
end observables
begin reaction rules
  cp_only: @CP:L(x!1).R(y~u!1) -> @CP:L(x!1).R(y~p!1) k
end reaction rules
end model
)BNGL";
}

std::string qualifiedSpeciesCountUniqueModel() {
    return R"BNGL(
begin model
setOption("SpeciesObservables", "CountUnique")
begin parameters
  n 5
  k 1
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) n
end seed species
begin observables
  Species FalseThenTrue A(s~1)>0, A(s~0)>0
end observables
begin reaction rules
  change: A(s~0) -> A(s~1) k
end reaction rules
end model
)BNGL";
}

std::string prefixZeroSourceModel() {
    return R"BNGL(
begin model
begin parameters
  n 5
end parameters
begin molecule types
  A()
end molecule types
begin compartments
  PM 2 1
  CP 3 1 PM
end compartments
begin seed species
  @CP:A() n
  @PM:A() n
end seed species
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
        CHECK(projection.weight(0, seedSpeciesGraph(compiled), "") == 2);
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
    CHECK(projection.weight(0, seedSpeciesGraph(compiled), "") == 1);
}

TEST_CASE("Observables: Species CountUnique counts a species once, not per pattern",
          "[observables][counting]") {
    // `A()` and `A(s~0)` both match the seed species. CountAll adds one per
    // matching pattern; CountUnique stops after the first.
    const auto all = compileModel(
        overlappingSpeciesModel("setOption(\"SpeciesObservables\",\"CountAll\")\n"));
    const bng::engine::ObservableProjection allProjection(all.compiled());
    REQUIRE(allProjection.size() == 1);
    CHECK(allProjection.weight(0, seedSpeciesGraph(all), "") == 2);

    const auto unique = compileModel(
        overlappingSpeciesModel("setOption(\"SpeciesObservables\",\"CountUnique\")\n"));
    const bng::engine::ObservableProjection uniqueProjection(unique.compiled());
    REQUIRE(uniqueProjection.size() == 1);
    CHECK(uniqueProjection.weight(0, seedSpeciesGraph(unique), "") == 1);
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
    CHECK(projection.weight(0, seedSpeciesGraph(compiled), "") == 2);
}

TEST_CASE("Observables: Molecules qualifiers are inert while Species qualifiers apply",
          "[observables][counting]") {
    // BNG2 ignores the relation on Molecules terms, but applies it to the
    // pattern match count for Species terms. A symmetric dimer has two matches.
    const auto all = compileModel(
        relationalMoleculesModel("setOption(\"MoleculesObservables\",\"CountAll\")\n"));
    const bng::engine::ObservableProjection allProjection(all.compiled());
    REQUIRE(allProjection.size() == 3);
    const auto allSpecies = seedSpeciesGraph(all);
    CHECK(allProjection.weight(0, allSpecies, "") == 2);
    CHECK(allProjection.weight(1, allSpecies, "") == 1);
    CHECK(allProjection.weight(2, allSpecies, "") == 0);

    const auto unique = compileModel(relationalMoleculesModel(
        "setOption(\"MoleculesObservables\",\"CountUnique\")\n"));
    const bng::engine::ObservableProjection uniqueProjection(unique.compiled());
    REQUIRE(uniqueProjection.size() == 3);
    const auto uniqueSpecies = seedSpeciesGraph(unique);
    CHECK(uniqueProjection.weight(0, uniqueSpecies, "") == 1);
    CHECK(uniqueProjection.weight(1, uniqueSpecies, "") == 1);
    CHECK(uniqueProjection.weight(2, uniqueSpecies, "") == 0);
}

TEST_CASE("Observables: graph prefixes filter species scope independently of node qualifiers",
          "[observables][compartments]") {
    const auto compiled = compileModel(compartmentPrefixObservableModel());
    const auto& model = compiled.compiled();
    bng::engine::NetworkGenerator generator(*compiled.document);
    const auto network = generator.generateNative();
    REQUIRE(network.species.size() == 2);
    REQUIRE(network.species.get(0).getCompartment() == "PM");
    REQUIRE(network.species.get(1).getCompartment() == "CP");
    const auto& pm = network.species.get(0);
    const auto& cp = network.species.get(1);
    const bng::engine::ObservableProjection projection(model);

    REQUIRE(projection.size() == 3);
    CHECK(projection.weight(0, pm.getSpeciesGraph().getGraph(), pm.getCompartment()) == 1);
    CHECK(projection.weight(0, cp.getSpeciesGraph().getGraph(), cp.getCompartment()) == 0);

    // BNG2 treats an unspecified target molecule compartment as a wildcard;
    // the local CP qualifier must not be mistaken for the outer graph prefix.
    CHECK(projection.weight(1, pm.getSpeciesGraph().getGraph(), pm.getCompartment()) == 1);
    CHECK(projection.weight(1, cp.getSpeciesGraph().getGraph(), cp.getCompartment()) == 1);
    CHECK(projection.weight(0, pm.getSpeciesGraph().getGraph(), "") == 0);
    CHECK(projection.weight(0, pm.getSpeciesGraph().getGraph(), "unknown-compartment") == 0);
    CHECK(projection.weight(1, pm.getSpeciesGraph().getGraph(), "unknown-compartment") == 1);

    // Prefix semantics are stored per term: the unprefixed second term still
    // contributes to the CP species after the prefixed first term is filtered.
    CHECK(projection.weight(2, pm.getSpeciesGraph().getGraph(), pm.getCompartment()) == 2);
    CHECK(projection.weight(2, cp.getSpeciesGraph().getGraph(), cp.getCompartment()) == 1);
}

TEST_CASE("Observables: all-explicit node compartments remain valid with a graph prefix",
          "[observables][compartments]") {
    const auto compiled = compileModel(allExplicitCompartmentPrefixModel());
    const auto& model = compiled.compiled();
    REQUIRE(model.seeds().size() == 1);
    bng::compile::BNGcoreLoweringContext context(model);
    const auto species = bng::compile::lowerPatternToBNGcore(
        model.seeds()[0].pattern, context);
    const bng::engine::ObservableProjection projection(model);

    REQUIRE(projection.size() == 1);
    CHECK(projection.weight(0, species, model.seeds()[0].compartment) == 1);
}

TEST_CASE("Observables: a compartment miss still evaluates a zero-count relation",
          "[observables][compartments][relations]") {
    auto source = bng::parser::parseModel(prefixZeroSourceModel());
    REQUIRE(source != nullptr);
    source->addObservable(bng::ast::Observable(
        "PrefixZero", "Species", {"@PM:A()<1"}));
    const bng::compile::Document document(*source);
    REQUIRE(document.valid());

    const auto& model = document.model();
    bng::engine::NetworkGenerator generator(document);
    const auto network = generator.generateNative();
    REQUIRE(network.species.size() == 2);
    const auto& cp = network.species.get(0);
    const auto& pm = network.species.get(1);
    const bng::engine::ObservableProjection projection(model);

    REQUIRE(projection.size() == 1);
    CHECK(projection.weight(0, cp.getSpeciesGraph().getGraph(), cp.getCompartment()) == 1);
    CHECK(projection.weight(0, pm.getSpeciesGraph().getGraph(), pm.getCompartment()) == 0);
    CHECK(projection.weight(0, cp.getSpeciesGraph().getGraph(), "") == 1);
    CHECK(projection.weight(0, cp.getSpeciesGraph().getGraph(), "unknown-compartment") == 1);
}

TEST_CASE("Observables: CountUnique stops after a false qualified term",
          "[observables][counting][relations]") {
    const auto compiled = compileModel(qualifiedSpeciesCountUniqueModel());
    const auto& model = compiled.compiled();
    bng::engine::NetworkGenerator generator(*compiled.document);
    const auto network = generator.generateNative();
    REQUIRE(network.species.size() == 2);

    const bng::engine::ObservableProjection projection(model);
    REQUIRE(projection.size() == 1);
    CHECK(projection.weight(
              0, network.species.get(0).getSpeciesGraph().getGraph(),
              network.species.get(0).getCompartment()) == 0);
    CHECK(projection.weight(
              0, network.species.get(1).getSpeciesGraph().getGraph(),
              network.species.get(1).getCompartment()) == 1);
}

TEST_CASE("Regulatory graph observables use the candidate species compartment",
          "[observables][compartments]") {
    auto source = bng::parser::parseModel(regulatoryGraphCompartmentPrefixModel());
    REQUIRE(source != nullptr);
    const bng::compile::Document document(*source);
    REQUIRE(document.valid());

    bng::engine::NetworkGenerator generator(document);
    const auto network = generator.generateNative();
    REQUIRE(network.species.size() == 3);
    REQUIRE(network.reactions.size() == 1);

    const auto graph = bng::io::RegulatoryGraphWriter::build(document.model(), network);
    REQUIRE(graph.observableNames == std::vector<std::string>{"PrefixAndNode", "NodeOnly"});
    const auto& reaction = network.reactions.all().front();
    const auto runtimeRuleName = reaction.getOriginRuleName().empty()
                                     ? reaction.getLabel()
                                     : reaction.getOriginRuleName();
    REQUIRE(graph.ruleNames == std::vector<std::string>{runtimeRuleName});
    REQUIRE(graph.edges.size() == 1);
    CHECK(graph.edges.front().ruleIndex == 0);
    CHECK(graph.edges.front().observableIndex == 1);
    CHECK(graph.edges.front().effect == -1);
}
