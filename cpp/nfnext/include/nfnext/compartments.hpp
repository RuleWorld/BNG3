#pragma once

#include "nfnext/dependency_dag.hpp"
#include "nfnext/types.hpp"

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace nfnext {

class CompartmentError : public std::runtime_error {
public:
    explicit CompartmentError(const std::string& message) : std::runtime_error(message) {}
};

struct CompartmentRecord {
    CompartmentId id{0};
    std::string name;
    int dimensions{3};
    double size{1.0};
    CompartmentId parent{std::numeric_limits<CompartmentId>::max()};
};

class CompartmentTable {
public:
    CompartmentId add(const std::string& name, int dimensions, double size,
                      CompartmentId parent = std::numeric_limits<CompartmentId>::max()) {
        if (dimensions < 1 || dimensions > 3) throw CompartmentError("compartment dimension must be 1, 2, or 3");
        if (!std::isfinite(size) || !(size > 0.0)) throw CompartmentError("compartment size must be finite and positive");
        if (by_name_.find(name) != by_name_.end()) throw CompartmentError("duplicate compartment name");
        if (parent != invalid() && parent >= records_.size()) throw CompartmentError("unknown parent compartment");
        const auto id = static_cast<CompartmentId>(records_.size());
        records_.push_back({id, name, dimensions, size, parent});
        by_name_.emplace(name, id);
        return id;
    }

    void setParent(CompartmentId id, CompartmentId parent) {
        if (id >= records_.size() || (parent != invalid() && parent >= records_.size()))
            throw CompartmentError("unknown compartment");
        records_[id].parent = parent;
    }
    CompartmentId parent(CompartmentId id) const { return record(id).parent; }
    const CompartmentRecord& record(CompartmentId id) const {
        if (id >= records_.size()) throw CompartmentError("unknown compartment");
        return records_[id];
    }
    void validate() const {
        for (const auto& record : records_) {
            std::vector<std::uint8_t> visited(records_.size(), 0);
            auto current = record.id;
            while (current != invalid()) {
                if (current >= records_.size() || visited[current] != 0)
                    throw CompartmentError("cyclic compartment hierarchy");
                visited[current] = 1;
                current = records_[current].parent;
            }
        }
    }
    static constexpr CompartmentId invalid() noexcept { return std::numeric_limits<CompartmentId>::max(); }

private:
    std::vector<CompartmentRecord> records_;
    std::unordered_map<std::string, CompartmentId> by_name_;
};

struct CompartmentPattern {
    CompartmentId id{CompartmentTable::invalid()};
};

struct CompartmentParticleState {
    std::map<std::pair<std::uint32_t, std::uint32_t>, CompartmentId> compartments;
    CompartmentId compartment(ParticleId id) const {
        const auto it = compartments.find({id.index, id.generation});
        if (it == compartments.end()) throw CompartmentError("unknown particle compartment");
        return it->second;
    }
    void setCompartment(ParticleId id, CompartmentId compartment_id) {
        compartments[{id.index, id.generation}] = compartment_id;
    }
};

struct CompartmentMutationSet {
    struct Change { ParticleId particle; CompartmentId from; CompartmentId to; };
    struct MutationSet {
        std::vector<Change> changes;
        bool containsCompartmentChange(ParticleId particle, CompartmentId from, CompartmentId to) const noexcept {
            for (const auto& change : changes)
                if (change.particle == particle && change.from == from && change.to == to) return true;
            return false;
        }
    } mutations;
};

struct CompartmentMatcher {
    std::map<std::pair<std::uint32_t, std::uint32_t>, CompartmentId> compartments;
    bool matches(const CompartmentPattern& pattern, ParticleId particle) const noexcept {
        const auto it = compartments.find({particle.index, particle.generation});
        return it != compartments.end() && it->second == pattern.id;
    }
};

struct CompartmentStateFixture {
    CompartmentTable table;
    CompartmentParticleState state;
    CompartmentMatcher matcher;
    CompartmentId cyto{0};
    CompartmentId nuc{1};
    ParticleId cyto_particle{0, 1};

    CompartmentPattern patternIn(const std::string& name) const {
        return {name == "cyto" ? cyto : nuc};
    }
    CompartmentMutationSet move(ParticleId particle, const std::string& name) {
        const auto target = name == "cyto" ? cyto : nuc;
        const auto from = state.compartment(particle);
        state.setCompartment(particle, target);
        matcher.compartments[{particle.index, particle.generation}] = target;
        CompartmentMutationSet result;
        result.mutations.changes.push_back({particle, from, target});
        return result;
    }
};

inline CompartmentStateFixture makeCompartmentStateFixture() {
    CompartmentStateFixture fixture;
    fixture.cyto = fixture.table.add("cyto", 3, 1.0);
    fixture.nuc = fixture.table.add("nuc", 3, 1.0, fixture.cyto);
    fixture.state.setCompartment(fixture.cyto_particle, fixture.cyto);
    fixture.matcher.compartments[{fixture.cyto_particle.index, fixture.cyto_particle.generation}] = fixture.cyto;
    return fixture;
}

inline CompartmentTable makeCyclicCompartmentFixture() {
    CompartmentTable table;
    const auto a = table.add("a", 3, 1.0);
    const auto b = table.add("b", 3, 1.0, a);
    table.setParent(a, b);
    return table;
}

} // namespace nfnext
