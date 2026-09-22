#include "engine/ObservableProjection.hpp"

#include "core/PatternMatching.hpp"

#include <stdexcept>

namespace bng::engine {
namespace {

bool compare(std::size_t lhs, const std::string& relation, int rhs) {
    const auto value = static_cast<long long>(lhs);
    if (relation.empty()) return lhs > 0;
    if (relation == "==") return value == rhs;
    if (relation == "!=") return value != rhs;
    if (relation == "<") return value < rhs;
    if (relation == "<=") return value <= rhs;
    if (relation == ">") return value > rhs;
    if (relation == ">=") return value >= rhs;
    throw std::runtime_error("unsupported observable relation: " + relation);
}

} // namespace

ObservableProjection::ObservableProjection(const compile::CompiledModel& model)
    : loweringContext_(model) {
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
        Observable observable;
        observable.name = source.name;
        observable.kind = source.kind;
        observable.terms.reserve(source.terms.size());
        for (const auto& term : source.terms) {
            if (source.kind == compile::ObservableKind::Molecules && !term.relation.empty()) {
                throw std::runtime_error(
                    "relational Molecules observable '" + source.name +
                    "' is not representable by the shared observable projector");
            }
            auto lowered = compile::lowerPatternToBNGcore(term.pattern, loweringContext_);
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
            observable.terms.push_back(Term{
                std::move(lowered), term.relation, term.quantity, automorphisms});
        }
        observables_.push_back(std::move(observable));
    }
}

int ObservableProjection::weight(std::size_t observableIndex,
                                 const BNGcore::PatternGraph& species) const {
    const auto& observable = observables_.at(observableIndex);
    int total = 0;
    for (const auto& term : observable.terms) {
        const auto count = core::countPatternMatches(term.pattern, species);
        if (observable.kind == compile::ObservableKind::Species) {
            if (compare(count, term.relation, term.quantity)) {
                ++total;
                // CountUnique: a species contributes once regardless of how
                // many of this observable's patterns it matches. Mirrors
                // `last if ($mode)` on the Species branch of
                // legacy/perl/Perl2/Observable.pm.
                if (speciesMode_ == CountMode::CountUnique) break;
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

std::vector<int> ObservableProjection::weights(const BNGcore::PatternGraph& species) const {
    std::vector<int> result;
    result.reserve(observables_.size());
    for (std::size_t i = 0; i < observables_.size(); ++i) result.push_back(weight(i, species));
    return result;
}

} // namespace bng::engine
