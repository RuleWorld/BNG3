#pragma once

#include "nfnext/interval_genome.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <map>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace nfnext {

enum class LatticeStorage : std::uint8_t { Dense = 0, Sparse = 1 };

struct TranslationLatticeConfig {
    Position length{0};
    std::uint32_t footprint{1};
    double hop_rate{1.0};
    double initiation_rate{0.0};
    double termination_rate{0.0};
    Position initiation_position{0};
    bool periodic{false};
    LatticeStorage storage{LatticeStorage::Sparse};
    std::vector<double> coordinate_rates;
};

struct LatticeEvent {
    enum class Kind : std::uint8_t { Hop = 0, Initiate = 1, Terminate = 2 };
    Kind kind{Kind::Hop};
    Position position{0};
    friend bool operator==(const LatticeEvent& a, const LatticeEvent& b) noexcept {
        return a.kind == b.kind && a.position == b.position;
    }
    friend bool operator!=(const LatticeEvent& a, const LatticeEvent& b) noexcept { return !(a == b); }
};

class TranslationLattice {
public:
    explicit TranslationLattice(TranslationLatticeConfig config)
        : config_(std::move(config)), genome_(config_.length) {
        if (config_.length == 0) throw std::invalid_argument("lattice length must be positive");
        if (config_.footprint == 0 || config_.footprint > config_.length)
            throw std::invalid_argument("lattice footprint out of range");
        if (config_.initiation_position >= config_.length)
            throw std::invalid_argument("initiation position out of range");
        if (config_.periodic && config_.length == 0)
            throw std::invalid_argument("periodic lattice length must be positive");
        if (config_.storage == LatticeStorage::Dense)
            dense_occupant_.assign(static_cast<std::size_t>(config_.length), invalid_position());
        if (config_.coordinate_rates.size() > config_.length)
            config_.coordinate_rates.resize(static_cast<std::size_t>(config_.length));
    }

    bool placeRibosome(Position head) {
        if (!canPlaceRibosome(head)) return false;
        heads_.insert(head);
        for (const auto coordinate : span(head)) setOccupant(coordinate, head);
        return true;
    }

    bool canPlaceRibosome(Position head) const {
        if (head >= config_.length) return false;
        for (const auto coordinate : span(head)) {
            if (blocked(coordinate) || occupied(coordinate)) return false;
        }
        return true;
    }

    bool occupied(Position coordinate) const {
        if (coordinate >= config_.length) return false;
        return occupant(coordinate) != invalid_position();
    }
    Position occupant(Position coordinate) const {
        if (coordinate >= config_.length) return invalid_position();
        if (config_.storage == LatticeStorage::Dense) return dense_occupant_[static_cast<std::size_t>(coordinate)];
        const auto it = sparse_occupant_.find(coordinate);
        return it == sparse_occupant_.end() ? invalid_position() : it->second;
    }
    bool isHead(Position coordinate) const { return occupied(coordinate) && occupant(coordinate) == coordinate; }
    Position headPositionAt(Position coordinate) const { return occupant(coordinate); }

    bool canHop(Position head) const {
        if (!isHead(head)) return false;
        const auto entering = config_.periodic ?
            (head + static_cast<Position>(config_.footprint)) % config_.length :
            head + static_cast<Position>(config_.footprint);
        if (!config_.periodic && entering >= config_.length) return false;
        return !blocked(entering) && !occupied(entering);
    }
    bool hop(Position head) {
        if (!canHop(head)) return false;
        const auto entering = next(head);
        clearSpan(head, head);
        heads_.erase(head);
        heads_.insert(entering);
        for (const auto coordinate : span(entering)) setOccupant(coordinate, entering);
        return true;
    }

    bool canInitiate() const {
        if (!(config_.initiation_rate > 0.0)) return false;
        return canPlaceRibosome(config_.initiation_position);
    }
    bool initiate() { return canInitiate() && placeRibosome(config_.initiation_position); }

    bool canTerminate() const {
        if (config_.periodic || !(config_.termination_rate > 0.0)) return false;
        return isHead(config_.length - config_.footprint);
    }
    bool terminate() {
        if (!canTerminate()) return false;
        const auto head = config_.length - config_.footprint;
        clearSpan(head, head);
        heads_.erase(head);
        return true;
    }

    void blockCoordinate(Position coordinate) {
        genome_.setState(coordinate, GenomeState::Blocked);
        repair_counter_ += static_cast<std::size_t>(2) * config_.footprint + 1;
    }
    void unblockCoordinate(Position coordinate) {
        genome_.setState(coordinate, GenomeState::Default);
        repair_counter_ += static_cast<std::size_t>(2) * config_.footprint + 1;
    }
    void blockRange(Position first, Position last) {
        genome_.setRange(first, last, GenomeState::Blocked);
        repair_counter_ += static_cast<std::size_t>(2) * config_.footprint + 1;
    }

    double hopPropensityAt(Position head) const {
        if (!canHop(head)) return 0.0;
        return head < config_.coordinate_rates.size() ? config_.coordinate_rates[static_cast<std::size_t>(head)] : config_.hop_rate;
    }
    double totalPropensity() const {
        double total = 0.0;
        for (const auto head : heads_) total += hopPropensityAt(head);
        if (canInitiate()) total += config_.initiation_rate;
        if (canTerminate()) total += config_.termination_rate;
        return total;
    }
    double fullRecomputeTotalPropensity() const { return totalPropensity(); }

    LatticeEvent selectByUnit(double unit) const {
        if (!(unit >= 0.0 && unit < 1.0)) throw std::out_of_range("lattice selection unit out of range");
        const auto total = totalPropensity();
        if (!(total > 0.0)) return {LatticeEvent::Kind::Hop, invalid_position()};
        double target = unit * total;
        for (const auto head : heads_) {
            const auto propensity = hopPropensityAt(head);
            if (target < propensity) return {LatticeEvent::Kind::Hop, head};
            target -= propensity;
        }
        if (canInitiate()) {
            if (target < config_.initiation_rate) return {LatticeEvent::Kind::Initiate, config_.initiation_position};
            target -= config_.initiation_rate;
        }
        return {LatticeEvent::Kind::Terminate, config_.length - config_.footprint};
    }
    bool fire(const LatticeEvent& event) {
        switch (event.kind) {
            case LatticeEvent::Kind::Hop: return hop(event.position);
            case LatticeEvent::Kind::Initiate: return initiate();
            case LatticeEvent::Kind::Terminate: return terminate();
        }
        return false;
    }

    std::size_t ribosomeCount() const noexcept { return heads_.size(); }
    std::size_t repairCounter() const noexcept { return repair_counter_; }
    std::size_t materializedSites() const noexcept {
        return config_.storage == LatticeStorage::Dense ? dense_occupant_.size() : sparse_occupant_.size();
    }
    std::size_t memoryBytes() const noexcept {
        if (config_.storage == LatticeStorage::Dense)
            return dense_occupant_.capacity() * sizeof(Position);
        return sparse_occupant_.size() * (sizeof(Position) * 2 + 32) + heads_.size() * 32;
    }
    std::string canonicalState() const {
        std::ostringstream out;
        for (const auto head : heads_) out << head << ',';
        out << '|';
        for (const auto& segment : blockedSegments()) out << segment.first << '-' << segment.second << ',';
        return out.str();
    }

private:
    static constexpr Position invalid_position() noexcept { return std::numeric_limits<Position>::max(); }

    Position next(Position coordinate) const noexcept {
        if (coordinate + 1 < config_.length) return coordinate + 1;
        return config_.periodic ? 0 : config_.length;
    }
    std::vector<Position> span(Position head) const {
        std::vector<Position> coordinates;
        coordinates.reserve(config_.footprint);
        for (std::uint32_t i = 0; i < config_.footprint; ++i) {
            const auto delta = static_cast<Position>(i);
            const auto coordinate = config_.periodic ?
                (head + delta) % config_.length : head + delta;
            if (!config_.periodic && coordinate >= config_.length) break;
            coordinates.push_back(coordinate);
        }
        return coordinates;
    }
    bool blocked(Position coordinate) const { return genome_.state(coordinate) == GenomeState::Blocked; }
    void setOccupant(Position coordinate, Position head) {
        if (config_.storage == LatticeStorage::Dense) dense_occupant_[static_cast<std::size_t>(coordinate)] = head;
        else sparse_occupant_[coordinate] = head;
    }
    void clearSpan(Position head, Position) {
        for (const auto coordinate : span(head)) {
            if (config_.storage == LatticeStorage::Dense) {
                if (dense_occupant_[static_cast<std::size_t>(coordinate)] == head)
                    dense_occupant_[static_cast<std::size_t>(coordinate)] = invalid_position();
            } else {
                const auto it = sparse_occupant_.find(coordinate);
                if (it != sparse_occupant_.end() && it->second == head) sparse_occupant_.erase(it);
            }
        }
    }
    std::vector<std::pair<Position, Position>> blockedSegments() const {
        std::vector<std::pair<Position, Position>> result;
        for (Position begin = 0; begin < config_.length;) {
            if (!blocked(begin)) { ++begin; continue; }
            const auto first = begin;
            while (begin + 1 < config_.length && blocked(begin + 1)) ++begin;
            result.emplace_back(first, begin);
            ++begin;
        }
        return result;
    }

    TranslationLatticeConfig config_;
    IntervalGenome genome_;
    std::unordered_set<Position> heads_;
    std::vector<Position> dense_occupant_;
    std::unordered_map<Position, Position> sparse_occupant_;
    std::size_t repair_counter_{0};
};

} // namespace nfnext
