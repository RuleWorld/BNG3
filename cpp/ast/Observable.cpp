#include "Observable.hpp"

#include <utility>

namespace bng::ast {

Observable::Observable(std::string name, std::string type, std::vector<std::string> patterns)
    : name_(std::move(name)), type_(std::move(type)), patterns_(std::move(patterns)) {}

const std::string& Observable::getName() const {
    return name_;
}

const std::string& Observable::getType() const {
    return type_;
}

const std::vector<std::string>& Observable::getPatterns() const {
    return patterns_;
}

void Observable::setIndexedSpeciesWeights(IndexedSpeciesWeights weights) {
    indexedSpeciesWeights_ = std::move(weights);
}

const std::optional<Observable::IndexedSpeciesWeights>&
Observable::getIndexedSpeciesWeights() const {
    return indexedSpeciesWeights_;
}

} // namespace bng::ast
