/// test_model_options.cpp
///
/// Regression coverage for `setOption` validation.
///
/// Before `cpp/ast/ModelOptions.hpp` existed, `Model::setOption` stored every
/// key/value pair unconditionally. Only `NumberPerQuantityUnit`, `units`, and
/// `substanceUnits` are ever read back, so every other option was accepted and
/// then ignored — including two BNG2 options that change observable or species
/// semantics. These tests pin the three behaviors that matter:
///
///   1. options present in the existing corpus still load;
///   2. recognized options whose behavior BNG3 does not implement fail closed
///      instead of silently running with different semantics;
///   3. values that are a no-op in BNG3 are accepted quietly.
///
/// Oracle: `legacy/perl/Perl2/BNGModel.pm:1911` (setOption),
/// `legacy/perl/Perl2/SpeciesGraph.pm:128` (SpeciesLabel values), and
/// `legacy/perl/Perl2/Observable.pm:236-275` (CountAll is the default mode;
/// CountUnique divides by pattern automorphisms).

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include "ast/Model.hpp"
#include "ast/ModelOptions.hpp"

using bng::ast::Model;
using Status = bng::ast::options::Validation::Status;
using bng::ast::options::validate;
using Catch::Matchers::ContainsSubstring;

TEST_CASE("setOption: options used by the existing corpus still load",
          "[options]") {
    // Every setOption call appearing under models/ and tests/. If any of these
    // starts throwing, the validation registry has become too strict and the
    // validation corpus will fail with it.
    CHECK(validate("SpeciesLabel", "HNauty").status == Status::Accepted);
    CHECK(validate("NumberPerQuantityUnit", "6.022e23").status == Status::Accepted);
    CHECK(validate("NumberPerQuantityUnit", "10").status == Status::Accepted);
    CHECK(validate("units", "strict").status == Status::Accepted);

    // tests/python/models/actions/all_actions.bngl carries setOption("test",10).
    // BNG2 stores unrecognized keys without complaint; so does BNG3. It is
    // reported as Unknown but must remain loadable.
    const auto unknown = validate("test", "10");
    CHECK(unknown.status == Status::Unknown);
    CHECK(unknown.accepted());
    CHECK_FALSE(unknown.message.empty());

    Model model;
    CHECK_NOTHROW(model.setOption("SpeciesLabel", "HNauty"));
    CHECK_NOTHROW(model.setOption("test", "10"));
    CHECK(model.getOptions().at("test") == "10");
}

TEST_CASE("setOption: SpeciesLabel exact values are no-ops, Quasi is unused",
          "[options]") {
    // Auto and HNauty are both exact canonical labelings. They differ in the
    // label strings produced, not in which species are identical, so BNG3's
    // single canonicalization path agrees with either and the option is a
    // genuine no-op.
    CHECK(validate("SpeciesLabel", "Auto").status == Status::Accepted);
    CHECK(validate("SpeciesLabel", "HNauty").status == Status::Accepted);
    CHECK(validate("SpeciesLabel", "Auto").message.empty());

    // Quasi is approximate: BNG2 uses it for species too large to label
    // exactly. BNG3 has no approximate mode, so the option is accepted,
    // recorded, and marked UNUSED with a warning rather than rejected. That
    // asymmetry with CountUnique is intentional -- falling back to the EXACT
    // path cannot silently degrade species identity, whereas silently
    // downgrading CountUnique to CountAll would have changed observable
    // values.
    const auto quasi = validate("SpeciesLabel", "Quasi");
    CHECK(quasi.status == Status::Accepted);
    CHECK(quasi.accepted());
    CHECK_THAT(quasi.message, ContainsSubstring("UNUSED"));

    // A value BNG2 itself rejects must not be stored as if it were fine.
    CHECK(validate("SpeciesLabel", "Nonsense").status == Status::Unsupported);

    Model model;
    CHECK_NOTHROW(model.setOption("SpeciesLabel", "Quasi"));
    CHECK(model.getOptions().at("SpeciesLabel") == "Quasi");

    Model rejecting;
    CHECK_THROWS_WITH(rejecting.setOption("SpeciesLabel", "Nonsense"),
                      ContainsSubstring("SpeciesLabel"));
    CHECK(rejecting.getOptions().find("SpeciesLabel") ==
          rejecting.getOptions().end());
}

TEST_CASE("setOption: observable counting modes are accepted and distinct",
          "[options]") {
    // Neither "MoleculesObservables" nor "SpeciesObservables" appeared
    // anywhere in BNG3 before this work, so a model requesting CountUnique
    // silently received CountAll values. Both modes are now implemented in
    // engine/ObservableProjection.cpp and both values validate.
    //
    // The two keys select DIFFERENT operations (Observable.pm:236 vs :260):
    // Molecules CountUnique divides by the pattern's automorphism number,
    // while Species CountUnique short-circuits the term loop so a species
    // counts once. This test pins the validation surface; the counting
    // behavior itself is covered by the engine tests.
    for (const char* key : {"MoleculesObservables", "SpeciesObservables"}) {
        INFO("key: " << key);
        CHECK(validate(key, "CountAll").status == Status::Accepted);
        CHECK(validate(key, "CountUnique").status == Status::Accepted);
        // BNG2 rejects anything else outright; so must BNG3.
        CHECK(validate(key, "Bogus").status == Status::Unsupported);
        CHECK(validate(key, "").status == Status::Unsupported);
    }

    Model model;
    CHECK_NOTHROW(model.setOption("MoleculesObservables", "CountUnique"));
    CHECK_NOTHROW(model.setOption("SpeciesObservables", "CountAll"));
    CHECK(model.getOptions().at("MoleculesObservables") == "CountUnique");

    Model rejecting;
    CHECK_THROWS_WITH(rejecting.setOption("SpeciesObservables", "CountEvery"),
                      ContainsSubstring("CountUnique"));
    // Fail-closed means not stored.
    CHECK(rejecting.getOptions().find("SpeciesObservables") ==
          rejecting.getOptions().end());
}

TEST_CASE("setOption: deprecated and unit-shaped options", "[options]") {
    // BNGModel.pm:1938 warns and ignores energyBNG; energy features are always
    // on in BNG3 too, so it is accepted with a note rather than rejected.
    const auto deprecated = validate("energyBNG", "1");
    CHECK(deprecated.status == Status::Accepted);
    CHECK_THAT(deprecated.message, ContainsSubstring("deprecated"));

    // BNG2 treats any *Units key as a unit assignment.
    CHECK(validate("ConcentrationUnits", "uM").status == Status::Accepted);
    CHECK(validate("TimeUnits", "s").status == Status::Accepted);

    // "Units" as a bare key is not a *Units suffix match on a longer name;
    // it is still unrecognized rather than silently interpreted.
    CHECK(validate("NumberPerQuantityUnit", "").status == Status::Unsupported);
}
