#pragma once

#include "nfnext/fenwick.hpp"
#include "nfnext/scheduler.hpp"

#include <cmath>
#include <cstdint>
#include <cstddef>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace nfnext {

enum class SchedulerRepresentation : std::uint8_t {
    DenseFenwick = 0,
    SparseActive = 1
};

struct ChannelUpdate {
    std::size_t family{0};
    std::size_t channel{0};
    double propensity{0.0};
};

class SchedulerError : public std::runtime_error {
public:
    explicit SchedulerError(const std::string& message) : std::runtime_error(message) {}
};

class AdaptiveScheduler {
public:
    void reset(const std::vector<std::size_t>& channels,
               SchedulerRepresentation representation = SchedulerRepresentation::DenseFenwick) {
        representation_ = representation;
        local_.clear();
        local_.reserve(channels.size());
        for (const auto count : channels) local_.emplace_back(count);
        totals_.reset(channels.size());
    }

    std::size_t channels(std::size_t family) const { return local_.at(family).size(); }
    double total() const noexcept { return totals_.total(); }

    void set(std::size_t family, std::size_t channel, double propensity) {
        if (!std::isfinite(propensity) || propensity < 0.0)
            throw SchedulerError("propensity must be finite and non-negative");
        if (family >= local_.size()) throw SchedulerError("scheduler family out of range");
        try {
            local_[family].set(channel, propensity);
            totals_.set(family, local_[family].total());
        } catch (const std::out_of_range& error) {
            throw SchedulerError(error.what());
        }
    }

    ScheduledChannel sample(double target) const {
        if (!(target >= 0.0) || !(target < total()))
            throw SchedulerError("scheduler target out of range");
        const auto family = totals_.lowerBound(target);
        const auto before = totals_.prefix(family);
        return {family, local_[family].lowerBound(target - before)};
    }

    std::vector<double> familySnapshot(std::size_t family) const {
        const auto& tree = local_.at(family);
        std::vector<double> values;
        values.reserve(tree.size());
        for (std::size_t i = 0; i < tree.size(); ++i) values.push_back(tree.value(i));
        return values;
    }

    std::vector<std::vector<double>> snapshot() const {
        std::vector<std::vector<double>> result;
        result.reserve(local_.size());
        for (std::size_t family = 0; family < local_.size(); ++family)
            result.push_back(familySnapshot(family));
        return result;
    }

    void apply(const std::vector<ChannelUpdate>& updates) {
        for (const auto& update : updates)
            set(update.family, update.channel, update.propensity);
    }

private:
    SchedulerRepresentation representation_{SchedulerRepresentation::DenseFenwick};
    std::vector<FenwickTree> local_;
    FenwickTree totals_;
};

} // namespace nfnext
