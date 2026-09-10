#pragma once

#include "nfnext/types.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <unordered_map>
#include <vector>

namespace nfnext {

enum class GenomeState : std::uint8_t { Default = 0, Active = 1, Blocked = 2 };

class IntervalGenome {
public:
    explicit IntervalGenome(Position length) : length_(length) {
        if (length_ == 0) throw std::invalid_argument("genome length must be positive");
        segments_.push_back({0, length_, GenomeState::Default});
    }

    Position length() const noexcept { return length_; }
    std::size_t segmentCount() const noexcept { return segments_.size(); }
    std::size_t memoryBytes() const noexcept { return segments_.capacity() * sizeof(Segment); }

    GenomeState state(Position coordinate) const {
        check(coordinate);
        const auto& segment = segments_[find(coordinate)];
        return segment.state;
    }

    void setState(Position coordinate, GenomeState state_value) {
        setRange(coordinate, coordinate, state_value);
    }

    void setRange(Position first, Position last, GenomeState state_value) {
        if (first > last) throw std::out_of_range("invalid genome range");
        check(first);
        check(last);
        std::vector<Segment> next;
        next.reserve(segments_.size() + 2);
        for (const auto& segment : segments_) {
            if (segment.last <= first || segment.first > last) {
                next.push_back(segment);
                continue;
            }
            if (segment.first < first) next.push_back({segment.first, first, segment.state});
            next.push_back({std::max(segment.first, first), std::min(segment.last, last + 1), state_value});
            if (segment.last > last + 1) next.push_back({last + 1, segment.last, segment.state});
        }
        segments_ = std::move(next);
        coalesce();
    }

private:
    struct Segment {
        Position first{0};
        Position last{0}; // exclusive
        GenomeState state{GenomeState::Default};
    };

    void check(Position coordinate) const {
        if (coordinate >= length_) throw std::out_of_range("genome coordinate out of range");
    }
    std::size_t find(Position coordinate) const {
        const auto it = std::upper_bound(
            segments_.begin(), segments_.end(), coordinate,
            [](Position value, const Segment& segment) { return value < segment.first; });
        return static_cast<std::size_t>(std::distance(segments_.begin(), it)) - 1;
    }
    void coalesce() {
        std::vector<Segment> compact;
        compact.reserve(segments_.size());
        for (const auto& segment : segments_) {
            if (segment.first == segment.last) continue;
            if (!compact.empty() && compact.back().last == segment.first &&
                compact.back().state == segment.state) compact.back().last = segment.last;
            else compact.push_back(segment);
        }
        segments_ = std::move(compact);
    }

    Position length_;
    std::vector<Segment> segments_;
};

enum class TranscriptFeature : std::uint8_t { Pause = 0, Start = 1, Stop = 2 };

class TranscriptState {
public:
    explicit TranscriptState(Position length) : length_(length) {}

    void markFeature(Position coordinate, TranscriptFeature feature) {
        if (coordinate >= length_) throw std::out_of_range("transcript coordinate out of range");
        features_[coordinate] = feature;
    }
    std::size_t materializedCoordinateCount() const noexcept { return features_.size(); }
    std::size_t memoryBytes() const noexcept {
        return features_.size() * (sizeof(Position) + sizeof(TranscriptFeature) + 32);
    }

private:
    Position length_;
    std::unordered_map<Position, TranscriptFeature> features_;
};

} // namespace nfnext
