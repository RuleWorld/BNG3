#pragma once

#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "Species.hpp"

namespace bng::ast {

class SpeciesList {
public:
    std::pair<std::size_t, bool> add(Species species);
    // Insert using an exact key already computed by findExact().
    std::pair<std::size_t, bool> addWithExactKey(Species species, std::string exact);
    // Check the exact compartment-aware key without canonicalizing the graph.
    std::optional<std::size_t> findExact(const Species& species) const;
    std::optional<std::size_t> findExact(const Species& species, std::string& exact) const;
    const Species& get(std::size_t index) const;
    Species& get(std::size_t index);
    bool containsLabel(const std::string& canonicalLabel) const;
    std::size_t indexOfLabel(const std::string& canonicalLabel) const;
    std::size_t size() const;
    std::size_t capacity() const;
    const std::vector<Species>& all() const;

    /// When false, skip isomorphism/dedup checks during add().
    /// Species are added unconditionally (useful for debugging/speed).
    void setCheckIso(bool enabled);
    bool getCheckIso() const;

private:
    std::pair<std::size_t, bool> addChecked(Species species, std::string exact, bool hasExact);
    std::vector<Species> species_;
    std::unordered_map<std::string, std::vector<std::size_t>> indicesByLabel_;
    std::unordered_map<std::string, std::vector<std::size_t>> indicesByExactString_;
    std::unordered_map<std::string, std::vector<std::size_t>> indicesByFingerprint_;
    bool checkIso_ = true;
};

} // namespace bng::ast
