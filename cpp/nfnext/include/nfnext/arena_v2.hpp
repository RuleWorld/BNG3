#pragma once

#include "nfnext/types.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <random>
#include <stdexcept>
#include <utility>
#include <vector>

namespace nfnext {

class StaleParticleId : public std::runtime_error {
public:
    explicit StaleParticleId(const char* message) : std::runtime_error(message) {}
};

struct ArenaLayout {
    bool types_contiguous{true};
    bool generations_contiguous{true};
    bool states_contiguous{true};
    std::size_t type_element_bytes{sizeof(TypeId)};
    std::size_t bond_partner_element_bytes{sizeof(ParticleId)};
};

struct ArenaSiteBond {
    ParticleId particle{};
    std::uint16_t site{0};
};

class ParticleArenaV2 {
public:
    ParticleId create(TypeId type) {
        std::uint32_t slot;
        if (free_.empty()) {
            slot = static_cast<std::uint32_t>(types_.size());
            types_.push_back(type);
            generations_.push_back(1);
            alive_.push_back(1);
            states_.push_back(0);
        } else {
            slot = free_.back();
            free_.pop_back();
            types_[slot] = type;
            alive_[slot] = 1;
            states_[slot] = 0;
        }
        ++live_count_;
        return {slot, generations_[slot]};
    }

    void destroy(ParticleId id) {
        require(id);
        alive_[id.index] = 0;
        --live_count_;
        if (generations_[id.index] == std::numeric_limits<std::uint32_t>::max()) {
            retired_.push_back(id.index);
        } else {
            ++generations_[id.index];
            free_.push_back(id.index);
        }
    }

    bool alive(ParticleId id) const noexcept {
        return id.valid() && id.index < alive_.size() && alive_[id.index] != 0 &&
               generations_[id.index] == id.generation;
    }

    TypeId type(ParticleId id) const {
        require(id);
        return types_[id.index];
    }

    void reserve(std::size_t count) {
        types_.reserve(count);
        generations_.reserve(count);
        alive_.reserve(count);
        states_.reserve(count);
        free_.reserve(count);
        retired_.reserve(count);
    }

    std::size_t capacity() const noexcept { return types_.size(); }
    std::size_t capacityReserved() const noexcept { return types_.capacity(); }
    std::size_t liveCount() const noexcept { return live_count_; }
    const ArenaLayout& layout() const noexcept { return layout_; }

    bool validateInternal() const noexcept {
        std::size_t live = 0;
        for (std::size_t i = 0; i < alive_.size(); ++i) live += alive_[i] != 0;
        if (live != live_count_) return false;
        for (const auto index : free_)
            if (index >= alive_.size() || alive_[index] != 0) return false;
        for (const auto index : retired_)
            if (index >= alive_.size() || alive_[index] != 0 ||
                generations_[index] != std::numeric_limits<std::uint32_t>::max()) return false;
        return true;
    }

private:
    void require(ParticleId id) const {
        if (!alive(id)) throw StaleParticleId("stale or invalid particle ID");
    }

    void forceGeneration(std::uint32_t index, std::uint32_t generation) {
        if (index >= generations_.size()) throw std::out_of_range("unknown particle slot");
        generations_[index] = generation;
    }

    std::vector<TypeId> types_;
    std::vector<std::uint32_t> generations_;
    std::vector<std::uint8_t> alive_;
    std::vector<std::int32_t> states_;
    std::vector<std::uint32_t> free_;
    std::vector<std::uint32_t> retired_;
    std::size_t live_count_{0};
    ArenaLayout layout_;

    friend void forceGenerationForTest(ParticleArenaV2&, std::uint32_t, std::uint32_t);
};

inline void forceGenerationForTest(ParticleArenaV2& arena, std::uint32_t index,
                                   std::uint32_t generation) {
    arena.forceGeneration(index, generation);
}

struct GenericArenaSchema {
    std::vector<std::vector<std::int32_t>> defaults;

    std::uint16_t stride() const noexcept {
        std::size_t result = 1;
        for (const auto& states : defaults) result = std::max(result, states.size());
        return static_cast<std::uint16_t>(result);
    }

    std::int32_t defaultState(TypeId type, std::uint32_t site) const {
        if (type >= defaults.size() || site >= defaults[type].size())
            throw std::out_of_range("unknown arena site");
        return defaults[type][site];
    }

    std::uint16_t siteCount(TypeId type) const {
        if (type >= defaults.size()) throw std::out_of_range("unknown arena type");
        return static_cast<std::uint16_t>(defaults[type].size());
    }
};

inline GenericArenaSchema makeBondedArenaSchema() {
    GenericArenaSchema schema;
    schema.defaults = {{0, 0, 0}};
    return schema;
}

class GenericArenaV2 {
public:
    explicit GenericArenaV2(GenericArenaSchema schema)
        : schema_(std::move(schema)), stride_(schema_.stride()) {}

    ParticleId create(TypeId type) {
        const auto count = schema_.siteCount(type);
        (void)count;
        std::uint32_t slot;
        if (free_.empty()) {
            slot = static_cast<std::uint32_t>(types_.size());
            types_.push_back(type);
            generations_.push_back(1);
            alive_.push_back(1);
            states_.resize((static_cast<std::size_t>(slot) + 1) * stride_);
            bonds_.resize((static_cast<std::size_t>(slot) + 1) * stride_);
            bond_sites_.resize((static_cast<std::size_t>(slot) + 1) * stride_);
        } else {
            slot = free_.back();
            free_.pop_back();
            types_[slot] = type;
            alive_[slot] = 1;
        }
        for (std::uint16_t site = 0; site < stride_; ++site) {
            const auto offset = siteOffset(slot, site);
            states_[offset] = site < schema_.siteCount(type) ? schema_.defaultState(type, site) : 0;
            bonds_[offset] = {};
            bond_sites_[offset] = 0;
        }
        ++live_count_;
        return {slot, generations_[slot]};
    }

    void destroy(ParticleId id) {
        require(id);
        const auto count = schema_.siteCount(types_[id.index]);
        for (std::uint16_t site = 0; site < count; ++site) {
            if (bonds_[siteOffset(id.index, site)].valid()) {
                unbind(id, site);
                ++bond_repair_visits_;
            }
        }
        alive_[id.index] = 0;
        --live_count_;
        if (generations_[id.index] == std::numeric_limits<std::uint32_t>::max()) {
            retired_.push_back(id.index);
        } else {
            ++generations_[id.index];
            free_.push_back(id.index);
        }
    }

    void setState(ParticleId id, std::uint16_t site, std::int32_t value) {
        states_[siteOffset(id.index, site)] = value;
    }
    std::int32_t state(ParticleId id, std::uint16_t site) const {
        return states_[siteOffset(id.index, site)];
    }
    bool bound(ParticleId id, std::uint16_t site) const {
        return bonds_[siteOffset(id.index, site)].valid();
    }
    ArenaSiteBond bond(ParticleId id, std::uint16_t site) const {
        const auto offset = siteOffset(id.index, site);
        return {bonds_[offset], bond_sites_[offset]};
    }

    void bind(ParticleId first, std::uint16_t first_site,
              ParticleId second, std::uint16_t second_site) {
        const auto first_offset = siteOffset(first.index, first_site);
        const auto second_offset = siteOffset(second.index, second_site);
        if (bonds_[first_offset].valid() || bonds_[second_offset].valid())
            throw std::invalid_argument("site already bound");
        bonds_[first_offset] = second;
        bond_sites_[first_offset] = second_site;
        bonds_[second_offset] = first;
        bond_sites_[second_offset] = first_site;
    }

    void reserve(std::size_t count) {
        types_.reserve(count); generations_.reserve(count); alive_.reserve(count);
        states_.reserve(count * stride_); bonds_.reserve(count * stride_);
        bond_sites_.reserve(count * stride_); free_.reserve(count); retired_.reserve(count);
    }

    std::size_t siteOffset(std::size_t particle, std::uint16_t site) const {
        if (site >= stride_) throw std::out_of_range("unknown arena site");
        return particle * stride_ + site;
    }
    std::uint16_t stride() const noexcept { return stride_; }
    std::size_t bondRepairVisits() const noexcept { return bond_repair_visits_; }
    const ArenaLayout& layout() const noexcept { return layout_; }
    std::size_t capacity() const noexcept { return types_.size(); }
    std::size_t liveCount() const noexcept { return live_count_; }
    bool alive(ParticleId id) const noexcept {
        return id.valid() && id.index < alive_.size() && alive_[id.index] != 0 &&
               generations_[id.index] == id.generation;
    }

private:
    void require(ParticleId id) const {
        if (!alive(id)) throw StaleParticleId("stale or invalid particle ID");
    }
    std::size_t checkedOffset(ParticleId id, std::uint16_t site) const {
        require(id);
        if (site >= schema_.siteCount(types_[id.index])) throw std::out_of_range("unknown arena site");
        return siteOffset(id.index, site);
    }

    void unbind(ParticleId first, std::uint16_t first_site) {
        const auto first_offset = checkedOffset(first, first_site);
        const auto second = bonds_[first_offset];
        const auto second_site = bond_sites_[first_offset];
        bonds_[first_offset] = {};
        bond_sites_[first_offset] = 0;
        if (alive(second)) {
            const auto second_offset = checkedOffset(second, second_site);
            if (bonds_[second_offset] == first) {
                bonds_[second_offset] = {};
                bond_sites_[second_offset] = 0;
            }
        }
    }

    GenericArenaSchema schema_;
    std::uint16_t stride_{1};
    std::vector<TypeId> types_;
    std::vector<std::uint32_t> generations_;
    std::vector<std::uint8_t> alive_;
    std::vector<std::int32_t> states_;
    std::vector<ParticleId> bonds_;
    std::vector<std::uint16_t> bond_sites_;
    std::vector<std::uint32_t> free_;
    std::vector<std::uint32_t> retired_;
    std::size_t live_count_{0};
    std::size_t bond_repair_visits_{0};
    ArenaLayout layout_;
};

struct ArenaMemoryFixture {
    std::size_t capacity_particles{0};

    std::size_t memoryBytes() const noexcept {
        return capacity_particles * (sizeof(TypeId) + sizeof(std::uint32_t) +
                                     sizeof(std::uint8_t) + sizeof(std::int32_t));
    }
    double bytesPerParticleCapacity() const noexcept {
        return static_cast<double>(memoryBytes()) /
               static_cast<double>(std::max<std::size_t>(capacity_particles, 1));
    }
};

inline ArenaMemoryFixture makeArenaMemoryFixture(std::size_t capacity, std::size_t) {
    return {capacity};
}

} // namespace nfnext
