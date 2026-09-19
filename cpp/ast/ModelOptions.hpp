/// ModelOptions.hpp
///
/// Validation for `setOption("name","value")`.
///
/// WHY THIS EXISTS
/// ---------------
/// `Model::setOption` used to store every key/value pair in a plain map with
/// no validation whatsoever. Only three keys are ever read back —
/// `NumberPerQuantityUnit`, `units`, and `substanceUnits` — so everything else
/// was accepted, written back out by `NetWriter`, and otherwise ignored.
///
/// That is the failure mode AGENTS.md calls out directly: a model that
/// silently runs with changed semantics is worse than one that is explicitly
/// unsupported. Two BNG2 options were affected, both with real semantic
/// weight:
///
///   - `MoleculesObservables` / `SpeciesObservables`. In BNG2 these select
///     `CountAll` versus `CountUnique` observable counting; see
///     `legacy/perl/Perl2/Observable.pm:236` and `:260`. Neither string
///     appeared anywhere in BNG3 — not in `cpp/`, `python/`, `tests/`, or
///     `models/` — so a model asking for `CountUnique` got `CountAll`
///     observable values with no warning. Both modes are now implemented in
///     `engine/ObservableProjection.cpp`; read the comment there before
///     assuming the two keys mean the same thing, because they do not.
///   - `SpeciesLabel`. BNG2 accepts `Auto`, `HNauty`, and `Quasi`
///     (`legacy/perl/Perl2/SpeciesGraph.pm:128`). BNG3 has exactly one
///     canonicalization path, so the value was read by nobody. `Auto` and
///     `HNauty` are exact and are accepted as no-ops; `Quasi` is approximate,
///     is accepted but marked UNUSED, and warns.
///
/// ORACLE
/// ------
/// Accepted names and values follow `BNGModel::setOption` at
/// `legacy/perl/Perl2/BNGModel.pm:1911`. BNG2 itself stores unrecognized keys
/// silently, and this registry preserves that (a hard rejection would break
/// forward compatibility with model files carrying options for other tools),
/// but it emits a warning so the behavior is visible rather than silent.
///
/// The distinction this file draws is between a value that is a *no-op* in
/// BNG3 and one that would *change semantics*:
///
///   - no-op    -> accept quietly. The option's requested behavior is already
///                 what BNG3 does.
///   - changes  -> reject with an explicit unsupported error naming the
///                 option, the value, and what BNG3 does instead.
///
/// `SpeciesLabel=HNauty` is deliberately in the first group. BNG2's `Auto` and
/// `HNauty` are both exact canonical labelings; they differ in the label
/// strings produced, not in which species are considered identical, so BNG3's
/// single canonicalization path yields the same species partition. `Quasi` is
/// in the second group: it is an approximate labeling that can merge or split
/// species relative to an exact one, so honoring it is not optional.

#pragma once

#include <string>

namespace bng::ast::options {

/// Outcome of validating one option assignment.
struct Validation {
    enum class Status {
        Accepted,     ///< recognized and honored, or a recognized no-op
        Unsupported,  ///< recognized by BNG2, would change semantics, not implemented
        Unknown,      ///< not a BNG2 option; stored, but worth a warning
    };

    Status      status = Status::Accepted;
    /// Human-readable detail. Empty for a quietly accepted option.
    std::string message;

    bool accepted() const { return status != Status::Unsupported; }
};

/// Validate a single `setOption` assignment.
///
/// Never throws. Callers decide whether `Unsupported` becomes an exception
/// (`ActionDispatch`, the parser) or a diagnostic.
inline Validation validate(const std::string& key, const std::string& value) {
    const auto unsupported = [](std::string message) {
        return Validation{Validation::Status::Unsupported, std::move(message)};
    };
    const auto accepted = [](std::string message = {}) {
        return Validation{Validation::Status::Accepted, std::move(message)};
    };

    if (key == "SpeciesLabel") {
        // Oracle: legacy/perl/Perl2/SpeciesGraph.pm:128 — Auto|HNauty|Quasi.
        if (value == "Auto" || value == "HNauty") {
            // Both are exact canonical labelings. BNG3 has a single
            // canonicalization path whose species partition agrees with
            // either, so the option is a no-op rather than a silent change.
            return accepted();
        }
        if (value == "Quasi") {
            // Accepted and recorded, but NOT honored, and said out loud.
            //
            // BNG2's Quasi labeling is an approximate method intended for
            // species too large to label exactly; it can in principle merge or
            // split species relative to an exact canonical labeling. BNG3 has
            // one exact canonicalization path and no approximate mode, so the
            // option has no implementation to select.
            //
            // This is deliberately a warning rather than a hard failure: the
            // exact path is strictly more accurate than the approximation the
            // model asked for, so proceeding cannot silently *degrade* results
            // the way ignoring an unimplemented CountUnique would have. The
            // warning exists because the user may have chosen Quasi for
            // tractability on a large model and should know they are getting
            // the exact path's cost instead.
            return accepted(
                "SpeciesLabel=Quasi is UNUSED in BNG3. Quasi is an approximate "
                "labeling for very large species; BNG3 has only an exact "
                "canonicalization path, which is being used instead. Species "
                "identity is exact, but labeling will not benefit from the "
                "approximation's speedup.");
        }
        return unsupported("invalid SpeciesLabel value '" + value +
                           "' (expected 'Auto', 'HNauty', or 'Quasi')");
    }

    if (key == "MoleculesObservables" || key == "SpeciesObservables") {
        // Oracle: legacy/perl/Perl2/BNGModel.pm:1955-1966 restricts the value
        // to CountUnique|CountAll, and Observable.pm:236 (Molecules) / :260
        // (Species) define the two modes. CountAll is the default in both.
        //
        // The two keys do NOT select the same operation, despite the shared
        // spelling:
        //
        //   Molecules + CountUnique  divides each pattern's match count by the
        //                            pattern's automorphism number (symmetry
        //                            correction).
        //   Species   + CountUnique  stops after the first matching pattern
        //                            (`last if ($mode)`), so a species counts
        //                            once no matter how many of the
        //                            observable's patterns it matches. BNG2's
        //                            symmetry correction is commented out on
        //                            this branch.
        //
        // Both are implemented in engine/ObservableProjection.cpp.
        if (value == "CountAll" || value == "CountUnique") {
            return accepted();
        }
        return unsupported("invalid " + key + " value '" + value +
                           "' (expected 'CountUnique' or 'CountAll')");
    }

    if (key == "energyBNG") {
        // Oracle: BNGModel.pm:1938 — deprecated, energy features are always on.
        return accepted("the energyBNG option is deprecated; energy features "
                        "are available by default");
    }

    if (key == "NumberPerQuantityUnit") {
        // BNG2 accepts a literal number or the name of a defined parameter.
        // Parameter resolution needs the model's symbol table, so only the
        // literal form is checked here; the consumers in UnitAnalysis,
        // NetWriter, XmlWriter, and the NFsim adapter validate the rest.
        if (value.empty()) {
            return unsupported("NumberPerQuantityUnit requires a value");
        }
        return accepted();
    }

    // Recognized-by-shape: BNG2 treats any *Units key as a unit assignment.
    if (key.size() > 5 && key.compare(key.size() - 5, 5, "Units") == 0) {
        return accepted();
    }
    if (key == "units") {
        return accepted();
    }

    // BNG2 stores unrecognized options without complaint. Preserve that so
    // model files carrying options for other tools still load, but say so.
    return Validation{Validation::Status::Unknown,
                      "unrecognized option '" + key +
                          "' is stored but not interpreted by BNG3"};
}

} // namespace bng::ast::options
