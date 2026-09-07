#pragma once

#include "nfnext/fenwick.hpp"

#include <cstddef>
#include <stdexcept>
#include <vector>

namespace nfnext {

struct ScheduledChannel {
    std::size_t family{0};
    std::size_t channel{0};
};

// Two-level exact weighted selector: a top tree chooses a parameterized rule
// family and a family-local tree chooses the concrete coordinate/channel.
class HierarchicalScheduler {
public:
    explicit HierarchicalScheduler(const std::vector<std::size_t>& channels_per_family)
        : family_totals_(channels_per_family.size()) {
        families_.reserve(channels_per_family.size());
        for (std::size_t n : channels_per_family) families_.emplace_back(n);
    }

    std::size_t familyCount() const noexcept { return families_.size(); }
    double total() const noexcept { return family_totals_.total(); }

    void set(std::size_t family, std::size_t channel, double propensity) {
        if (family >= families_.size()) throw std::out_of_range("scheduler family");
        auto& local = families_[family];
        local.set(channel, propensity);
        family_totals_.set(family, local.total());
    }

    double get(std::size_t family, std::size_t channel) const {
        return families_.at(family).value(channel);
    }

    ScheduledChannel sample(double target) const {
        const std::size_t family = family_totals_.lowerBound(target);
        const double before = family_totals_.prefix(family);
        return ScheduledChannel{family, families_[family].lowerBound(target - before)};
    }

private:
    std::vector<FenwickTree> families_;
    FenwickTree family_totals_;
};

} // namespace nfnext
