#include "engine/ObservableProjection.hpp"

#include "core/PatternMatching.hpp"

#include <stdexcept>

namespace bng::engine {

ObservableProjection::ObservableProjection(const compile::CompiledModel& model)
    : loweringContext_(model) {
    for (const auto& compartment : model.compartments()) {
        if (compartment.id.valid() && model.compartment(compartment.id) != nullptr)
            compartmentIds_.emplace(compartment.name, compartment.id);
    }

    // Counting modes. BNG2 restricts the value to CountUnique|CountAll and
    // defaults to CountAll when the option is absent; bng::ast::options
    // validates the spelling at setOption time, so an unexpected value here
    // means the option bypassed that seam.
    const auto& options = model.metadata().options;
    const auto readMode = [&options](const std::string& key) {
        const auto found = options.find(key);
        if (found == options.end()) return CountMode::CountAll;
        if (found->second == "CountUnique") return CountMode::CountUnique;
        if (found->second == "CountAll") return CountMode::CountAll;
        throw std::runtime_error("unsupported " + key + " value '" + found->second +
                                 "' (expected 'CountUnique' or 'CountAll')");
    };
    moleculesMode_ = readMode("MoleculesObservables");
    speciesMode_ = readMode("SpeciesObservables");

    observables_.reserve(model.observables().size());
    for (const auto& source : model.observables()) {
        if (source.kind != compile::ObservableKind::Molecules &&
            source.kind != compile::ObservableKind::Species) {
            throw std::runtime_error("unsupported observable type '" + source.type +
                                     "' for observable '" + source.name + "'");
        }

        Observable observable;
        observable.name = source.name;
        observable.kind = source.kind;
        observable.terms.reserve(source.terms.size());
        for (const auto& term : source.terms) {
            // BNG2 treats a relation on a Molecules term as an inert
            // qualifier. Relations are applied only by the Species branch
            // in weight(), so keep lowering the pattern without rejecting it.
            auto lowered = compile::lowerPatternToBNGcore(term.pattern, loweringContext_);
            std::optional<compile::CompartmentId> compartmentPrefix;
            if (term.pattern.compartmentIsPrefix()) {
                compartmentPrefix = term.pattern.compartmentId();
                if (!compartmentPrefix.has_value() || !compartmentPrefix->valid() ||
                    model.compartment(*compartmentPrefix) == nullptr) {
                    throw std::runtime_error(
                        "observable '" + source.name +
                        "': graph compartment prefix has no resolved compartment ID");
                }
            }
            // Automorphism count = embeddings of the pattern into itself.
            // Only the Molecules CountUnique mode consumes it, so skip the
            // self-match entirely otherwise; it is pure cost for every other
            // configuration.
            std::size_t automorphisms = 1;
            if (source.kind == compile::ObservableKind::Molecules &&
                moleculesMode_ == CountMode::CountUnique) {
                automorphisms = core::countPatternMatches(lowered, lowered);
                if (automorphisms == 0) {
                    // A pattern always embeds into itself at least once, so
                    // zero means the matcher disagrees with itself. Fail
                    // rather than divide by zero or silently fall back to
                    // CountAll.
                    throw std::runtime_error(
                        "observable '" + source.name +
                        "': pattern has no self-embedding, so its automorphism "
                        "count cannot be established for CountUnique");
                }
            }
            observable.terms.push_back(Term{std::move(lowered), compartmentPrefix,
                                            term.relation, term.quantity, automorphisms});
        }
        observables_.push_back(std::move(observable));
    }
}

int ObservableProjection::weight(std::size_t observableIndex,
                                 const BNGcore::PatternGraph& species,
                                 std::string_view speciesCompartment) const {
    const auto& observable = observables_.at(observableIndex);
    int total = 0;
    for (const auto& term : observable.terms) {
        bool compartmentMatches = true;
        if (term.compartmentPrefix.has_value()) {
            const auto candidate = compartmentIds_.find(speciesCompartment);
            compartmentMatches = candidate != compartmentIds_.end() &&
                                 candidate->second == *term.compartmentPrefix;
        }
        // A prefix mismatch means zero structural matches, but Species
        // relations still apply to that zero (for example `A()==0`).
        const std::size_t count = compartmentMatches
                                      ? core::countPatternMatches(term.pattern, species)
                                      : 0;
        if (observable.kind == compile::ObservableKind::Species) {
            const bool matches = compile::observablePatternCountMatches(
                count, term.relation, term.quantity);
            if (matches) ++total;
            // BNG2's Species CountUnique branch places `last if ($mode)`
            // inside the qualified relation branch, even when false; the
            // unqualified branch stops only after a positive structural match.
            // See legacy/perl/Perl2/Observable.pm:260.
            if (speciesMode_ == CountMode::CountUnique &&
                (!term.relation.empty() || matches)) {
                break;
            }
        } else if (observable.kind == compile::ObservableKind::Molecules) {
            if (moleculesMode_ == CountMode::CountUnique) {
                // Symmetry correction: divide out the pattern's automorphisms.
                //
                // The division is always exact. Aut(pattern) acts freely on
                // the set of embeddings by precomposition, so the embeddings
                // partition into orbits of size exactly |Aut(pattern)|. A
                // non-zero remainder would mean the matcher and the
                // automorphism count disagree, which is a defect rather than
                // a modelling situation, so it fails loudly instead of
                // truncating a fractional observable value.
                if (count % term.automorphisms != 0) {
                    throw std::runtime_error(
                        "observable '" + observable.name + "': match count " +
                        std::to_string(count) + " is not divisible by the pattern's "
                        "automorphism count " + std::to_string(term.automorphisms) +
                        "; CountUnique cannot produce an exact value");
                }
                total += static_cast<int>(count / term.automorphisms);
            } else {
                total += static_cast<int>(count);
            }
        } else {
            throw std::runtime_error("unknown compiled observable kind: " + observable.name);
        }
    }
    return total;
}

std::vector<int> ObservableProjection::weights(
    const BNGcore::PatternGraph& species, std::string_view speciesCompartment) const {
    std::vector<int> result;
    result.reserve(observables_.size());
    for (std::size_t i = 0; i < observables_.size(); ++i)
        result.push_back(weight(i, species, speciesCompartment));
    return result;
}

} // namespace bng::engine
