#pragma once

#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace nfnext {

class PopulationError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class PopulationOverflow : public PopulationError {
public:
    using PopulationError::PopulationError;
};

using SpeciesId = std::uint32_t;

class PopulationState {
public:
    SpeciesId addSpecies(const std::string& name, std::uint64_t initial_count = 0) {
        auto it = name_to_id_.find(name);
        if (it != name_to_id_.end()) {
            counts_[it->second] = initial_count;
            return it->second;
        }
        SpeciesId id = static_cast<SpeciesId>(species_.size());
        species_.push_back(name);
        counts_.push_back(initial_count);
        name_to_id_[name] = id;
        return id;
    }

    std::uint64_t count(SpeciesId id) const {
        if (id >= counts_.size()) return 0;
        return counts_[id];
    }

    void setCount(SpeciesId id, std::uint64_t c) {
        if (id >= counts_.size()) counts_.resize(id + 1, 0);
        counts_[id] = c;
    }

    std::vector<std::uint64_t> snapshot() const {
        return counts_;
    }

    void restore(const std::vector<std::uint64_t>& snap) {
        counts_ = snap;
    }

    std::size_t numSpecies() const noexcept { return counts_.size(); }
    const std::string& speciesName(SpeciesId id) const { return species_.at(id); }

private:
    std::vector<std::string> species_;
    std::vector<std::uint64_t> counts_;
    std::unordered_map<std::string, SpeciesId> name_to_id_;
};

class PopulationReaction {
public:
    double rate{0.0};
    std::vector<std::pair<SpeciesId, std::uint32_t>> consumed;
    std::vector<std::pair<SpeciesId, std::uint32_t>> produced;

    void consume(SpeciesId sp, std::uint32_t stoich) {
        consumed.emplace_back(sp, stoich);
    }

    void produce(SpeciesId sp, std::uint32_t stoich) {
        produced.emplace_back(sp, stoich);
    }

    double propensity(const PopulationState& s) const {
        double p = rate;
        for (const auto& [sp, stoich] : consumed) {
            std::uint64_t n = s.count(sp);
            if (n < stoich) return 0.0;
            double comb = 1.0;
            for (std::uint32_t i = 0; i < stoich; ++i) {
                comb *= static_cast<double>(n - i);
                comb /= static_cast<double>(i + 1);
            }
            p *= comb;
        }
        return p;
    }

    void fire(PopulationState& s) const {
        for (const auto& [sp, stoich] : consumed) {
            if (s.count(sp) < stoich) {
                throw PopulationError("population underflow");
            }
        }
        for (const auto& [sp, stoich] : produced) {
            if (s.count(sp) > std::numeric_limits<std::uint64_t>::max() - stoich) {
                throw PopulationOverflow("population overflow");
            }
        }
        for (const auto& [sp, stoich] : consumed) {
            s.setCount(sp, s.count(sp) - stoich);
        }
        for (const auto& [sp, stoich] : produced) {
            s.setCount(sp, s.count(sp) + stoich);
        }
    }
};

} // namespace nfnext
