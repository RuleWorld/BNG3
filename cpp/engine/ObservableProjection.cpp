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
            observable.terms.push_back(Term{
                compile::lowerPatternToBNGcore(term.pattern, loweringContext_),
                term.relation, term.quantity});
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
            if (compare(count, term.relation, term.quantity)) ++total;
        } else if (observable.kind == compile::ObservableKind::Molecules) {
            total += static_cast<int>(count);
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
