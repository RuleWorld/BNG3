#include "SpeciesList.hpp"

#include <stdexcept>
#include <utility>

#include "core/List.hpp"
#include "core/Ullmann.hpp"

namespace bng::ast {

namespace {

// Cheap sufficient witness for isomorphism. If node i of `a` and node i of `b`
// agree on type, state, compartment and out-edge index set, then the
// index-for-index correspondence is itself a type/state/compartment preserving
// bijection - exactly the witness the general search below looks for - at
// O(nodes + edges) instead of a full subgraph search.
//
// The correspondence is verified directly rather than inferred from the
// canonical label, so it holds for any node ordering. When it does not apply
// the general search runs unchanged, so the answer is never affected.
bool indexCorrespondenceIsWitness(const BNGcore::PatternGraph& a,
                                  const BNGcore::PatternGraph& b) {
    const std::size_t n = a.size();
    if (n != b.size()) {
        return false;
    }

    std::vector<const BNGcore::Node*> an(n, nullptr);
    std::vector<const BNGcore::Node*> bn(n, nullptr);
    const auto indexNodes = [n](const BNGcore::PatternGraph& g,
                                std::vector<const BNGcore::Node*>& slots) {
        for (auto it = g.begin(); it != g.end(); ++it) {
            const int index = (*it)->get_index();
            if (index < 0 || static_cast<std::size_t>(index) >= n ||
                slots[index] != nullptr) {
                return false;
            }
            slots[index] = *it;
        }
        return true;
    };
    if (!indexNodes(a, an) || !indexNodes(b, bn)) {
        return false;
    }

    std::vector<int> marked(n, -1);
    for (std::size_t i = 0; i < n; ++i) {
        const BNGcore::Node* x = an[i];
        const BNGcore::Node* y = bn[i];
        if (x == nullptr || y == nullptr) {
            return false;
        }
        if (!(x->get_type() == y->get_type()) || !(x->get_state() == y->get_state()) ||
            x->get_compartment() != y->get_compartment()) {
            return false;
        }
        if (x->out_degree() != y->out_degree()) {
            return false;
        }
        for (auto e = x->edges_out_begin(); e != x->edges_out_end(); ++e) {
            const int target = (*e)->get_index();
            if (target < 0 || static_cast<std::size_t>(target) >= n) {
                return false;
            }
            marked[target] = static_cast<int>(i);
        }
        for (auto e = y->edges_out_begin(); e != y->edges_out_end(); ++e) {
            const int target = (*e)->get_index();
            if (target < 0 || static_cast<std::size_t>(target) >= n ||
                marked[target] != static_cast<int>(i)) {
                return false;
            }
        }
    }
    return true;
}
bool isIsomorphic(const SpeciesGraph& lhs, const SpeciesGraph& rhs) {
    // For raw-string species (loaded from .net files), skip graph isomorphism
    if (lhs.getGraph().empty() || rhs.getGraph().empty()) {
        return lhs.toString() == rhs.toString();
    }
    // Quick size check: graphs of different sizes can't be isomorphic
    if (lhs.getGraph().size() != rhs.getGraph().size()) {
        return false;
    }
    // Cheap sufficient witness first; the general search runs unchanged when
    // it does not apply, so this only changes how fast we get the answer.
    if (indexCorrespondenceIsWitness(lhs.getGraph(), rhs.getGraph())) {
        return true;
    }
    BNGcore::UllmannSGIso matcher(lhs.getGraph(), rhs.getGraph());
    BNGcore::List<BNGcore::Map> maps;
    matcher.find_maps(maps);
    for (auto mapIter = maps.begin(); mapIter != maps.end(); ++mapIter) {
        bool compatible = true;
        for (auto nodeIter = lhs.getGraph().begin(); nodeIter != lhs.getGraph().end(); ++nodeIter) {
            auto* mapped = mapIter->mapf(*nodeIter);
            if (mapped == nullptr || !((*nodeIter)->get_type() == mapped->get_type()) ||
                !((*nodeIter)->get_state() == mapped->get_state()) ||
                (*nodeIter)->get_compartment() != mapped->get_compartment()) {
                compatible = false;
                break;
            }
        }
        if (compatible) {
            return true;
        }
    }
    return false;
}

} // namespace

void SpeciesList::setCheckIso(bool enabled) {
    checkIso_ = enabled;
}

bool SpeciesList::getCheckIso() const {
    return checkIso_;
}

std::optional<std::size_t> SpeciesList::findExact(const Species& species) const {
    std::string exact;
    return findExact(species, exact);
}

std::optional<std::size_t> SpeciesList::findExact(
    const Species& species, std::string& exact) const {
    exact.clear();
    if (!checkIso_) {
        return std::nullopt;
    }

    exact = species.getSpeciesGraph().toStringForDedup();
    const auto exactBucket = indicesByExactString_.find(exact);
    if (exactBucket == indicesByExactString_.end()) {
        return std::nullopt;
    }

    for (const auto index : exactBucket->second) {
        if (species_[index].getCompartment() == species.getCompartment()) {
            return index;
        }
    }
    return std::nullopt;
}

std::pair<std::size_t, bool> SpeciesList::add(Species species) {
    // When check_iso is disabled, skip all dedup and add unconditionally
    if (!checkIso_) {
        const std::size_t index = species_.size();
        species.setIndex(index);
        species_.push_back(std::move(species));
        return {index, true};
    }

    return addChecked(std::move(species), {}, false);
}

std::pair<std::size_t, bool> SpeciesList::addWithExactKey(
    Species species, std::string exact) {
    // When check_iso is disabled, skip all dedup and add unconditionally
    if (!checkIso_) {
        const std::size_t index = species_.size();
        species.setIndex(index);
        species_.push_back(std::move(species));
        return {index, true};
    }

    return addChecked(std::move(species), std::move(exact), true);
}

std::pair<std::size_t, bool> SpeciesList::addChecked(
    Species species, std::string exact, bool hasExact) {
    // Use compartment-aware string for dedup to distinguish species that differ
    // only by per-molecule compartments (e.g., Im@CP.NP vs Im@NU.NP).
    if (!hasExact) {
        exact = species.getSpeciesGraph().toStringForDedup();
    }

    // Fast path 1: exact string match (O(1))
    const auto exactBucket = indicesByExactString_.find(exact);
    if (exactBucket != indicesByExactString_.end()) {
        for (const auto index : exactBucket->second) {
            auto& existingSpecies = species_[index];
            if (existingSpecies.getCompartment() != species.getCompartment()) {
                continue;
            }
            if (existingSpecies.getCompartment().empty() && !species.getCompartment().empty()) {
                existingSpecies.setCompartment(species.getCompartment());
            }
            return {index, false};
        }
    }

    // Canonical labeling is substantially more expensive than exact string
    // serialization. Only compute it after the exact-key fast path misses;
    // product graphs are frequently exact duplicates of an existing species.
    const std::string label = species.getSpeciesGraph().canonicalLabel();
    // Fingerprint is only consulted by fast path 3 and the insert, and
    // computeFingerprint() is a pure read of the graph, so compute it there
    // rather than for every candidate that reaches canonical labeling.
    // Canonical labeling may change node-index tie breakers used by the
    // serializer, so use the canonicalized key for compartmented fallback and
    // insert paths. Unscoped species retain the pre-label exact key and avoid
    // serializing every new species a second time.
    if (!species.getCompartment().empty()) {
        exact = species.getSpeciesGraph().toStringForDedup();
    }

    // Canonical labeling can reorder symmetric nodes and change the
    // compartment-aware serialization. Check that normalized key before
    // falling back to graph isomorphism.
    const auto canonicalExactBucket = indicesByExactString_.find(exact);
    if (canonicalExactBucket != indicesByExactString_.end()) {
        for (const auto index : canonicalExactBucket->second) {
            if (species_[index].getCompartment() == species.getCompartment()) {
                return {index, false};
            }
        }
    }

    // Fast path 2: canonical label match (O(1))
    // Note: canonical label is compartment-blind. Species with same graph structure
    // and same species-level compartment but different per-molecule compartments
    // (e.g., Im@CP.NP vs Im@NU.NP, both at species @NM) must NOT be merged.
    // Check dedup string to distinguish them.
    const auto existing = indicesByLabel_.find(label);
    if (existing != indicesByLabel_.end()) {
        for (const auto index : existing->second) {
            auto& existingSpecies = species_[index];
            if (existingSpecies.getCompartment() != species.getCompartment()) {
                continue;
            }
            // Fingerprints can differ for equivalent graphs with ambiguous
            // repeated subgraphs. Confirm graph isomorphism and molecule
            // compartments directly.
            if (!isIsomorphic(
                    existingSpecies.getSpeciesGraph(), species.getSpeciesGraph())) {
                continue;
            }
            if (existingSpecies.getCompartment().empty() && !species.getCompartment().empty()) {
                existingSpecies.setCompartment(species.getCompartment());
            }
            return {index, false};
        }
    }

    // Fast path 3: structural fingerprint match. This catches equivalent
    // species when canonical labels differ, with isomorphism as confirmation.
    const std::string fp = species.getSpeciesGraph().fingerprint();
    const auto fpBucket = indicesByFingerprint_.find(fp);
    if (fpBucket != indicesByFingerprint_.end()) {
        for (const auto index : fpBucket->second) {
            auto& existingSpecies = species_[index];
            if (existingSpecies.getCompartment() != species.getCompartment()) {
                continue;
            }
            if (!isIsomorphic(existingSpecies.getSpeciesGraph(), species.getSpeciesGraph())) {
                continue;
            }
            if (existingSpecies.getCompartment().empty() && !species.getCompartment().empty()) {
                existingSpecies.setCompartment(species.getCompartment());
            }
            indicesByLabel_[label].push_back(index);
            return {index, false};
        }
    }

    const std::size_t index = species_.size();
    species.setIndex(index);
    species_.push_back(std::move(species));
    indicesByLabel_[label].push_back(index);
    indicesByExactString_[exact].push_back(index);
    indicesByFingerprint_[fp].push_back(index);
    return {index, true};
}

const Species& SpeciesList::get(std::size_t index) const {
    return species_.at(index);
}

Species& SpeciesList::get(std::size_t index) {
    return species_.at(index);
}

bool SpeciesList::containsLabel(const std::string& canonicalLabel) const {
    const auto found = indicesByLabel_.find(canonicalLabel);
    return found != indicesByLabel_.end() && !found->second.empty();
}

std::size_t SpeciesList::indexOfLabel(const std::string& canonicalLabel) const {
    const auto found = indicesByLabel_.find(canonicalLabel);
    if (found == indicesByLabel_.end() || found->second.empty()) {
        throw std::runtime_error("Unknown species label: " + canonicalLabel);
    }
    return found->second.front();
}

std::size_t SpeciesList::size() const {
    return species_.size();
}

std::size_t SpeciesList::capacity() const {
    return species_.capacity();
}

const std::vector<Species>& SpeciesList::all() const {
    return species_;
}

} // namespace bng::ast
