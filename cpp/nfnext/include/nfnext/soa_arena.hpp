#pragma once

#include "nfnext/types.hpp"

#include <cstdint>
#include <stdexcept>
#include <vector>

namespace nfnext {

// Compact generational arena. Identity is an integer handle rather than a C++
// pointer; hot particle fields live in independent contiguous arrays.
class ParticleArena {
public:
    ParticleId create(TypeId type, Position position = 0) {
        std::uint32_t slot;
        if (!free_.empty()) {
            slot = free_.back();
            free_.pop_back();
            alive_[slot] = 1;
            types_[slot] = type;
            positions_[slot] = position;
        } else {
            slot = static_cast<std::uint32_t>(types_.size());
            types_.push_back(type);
            positions_.push_back(position);
            generations_.push_back(1);
            alive_.push_back(1);
        }
        return ParticleId{slot, generations_[slot]};
    }

    bool alive(ParticleId id) const noexcept {
        return id.index < alive_.size() && alive_[id.index] != 0 && generations_[id.index] == id.generation;
    }

    void destroy(ParticleId id) {
        require(id);
        alive_[id.index] = 0;
        ++generations_[id.index];
        free_.push_back(id.index);
    }

    TypeId type(ParticleId id) const { require(id); return types_[id.index]; }
    Position position(ParticleId id) const { require(id); return positions_[id.index]; }
    void setPosition(ParticleId id, Position p) { require(id); positions_[id.index] = p; }

    std::size_t capacity() const noexcept { return types_.size(); }
    std::size_t freeCount() const noexcept { return free_.size(); }
    std::size_t liveCount() const noexcept { return capacity() - freeCount(); }

private:
    void require(ParticleId id) const {
        if (!alive(id)) throw std::out_of_range("stale or invalid ParticleId");
    }

    std::vector<TypeId> types_;
    std::vector<Position> positions_;
    std::vector<std::uint32_t> generations_;
    std::vector<std::uint8_t> alive_;
    std::vector<std::uint32_t> free_;
};

} // namespace nfnext
