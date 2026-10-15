#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace bng::ast {

class Observable {
public:
    using IndexedSpeciesWeights = std::vector<std::pair<std::size_t, double>>;

    Observable(std::string name, std::string type, std::vector<std::string> patterns);

    const std::string& getName() const;
    const std::string& getType() const;
    const std::vector<std::string>& getPatterns() const;
    void setIndexedSpeciesWeights(IndexedSpeciesWeights weights);
    const std::optional<IndexedSpeciesWeights>& getIndexedSpeciesWeights() const;

private:
    std::string name_;
    std::string type_;
    std::vector<std::string> patterns_;
    std::optional<IndexedSpeciesWeights> indexedSpeciesWeights_;
};

} // namespace bng::ast
