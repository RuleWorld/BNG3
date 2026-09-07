#pragma once

#include <algorithm>
#include <cstddef>
#include <stdexcept>
#include <vector>

namespace nfnext {

class FenwickTree {
public:
    FenwickTree() = default;
    explicit FenwickTree(std::size_t n) { reset(n); }

    void reset(std::size_t n) {
        values_.assign(n, 0.0);
        tree_.assign(n + 1, 0.0);
    }

    std::size_t size() const noexcept { return values_.size(); }
    double total() const noexcept { return prefix(values_.size()); }
    double value(std::size_t i) const { return values_.at(i); }

    void set(std::size_t i, double value) {
        if (i >= values_.size()) throw std::out_of_range("FenwickTree::set");
        const double delta = value - values_[i];
        values_[i] = value;
        for (std::size_t x = i + 1; x < tree_.size(); x += x & (~x + 1)) tree_[x] += delta;
    }

    double prefix(std::size_t count) const noexcept {
        double sum = 0.0;
        for (std::size_t x = std::min(count, values_.size()); x > 0; x -= x & (~x + 1)) sum += tree_[x];
        return sum;
    }

    // Return smallest index whose cumulative weight exceeds target.
    std::size_t lowerBound(double target) const {
        if (!(target >= 0.0) || !(target < total())) throw std::out_of_range("FenwickTree::lowerBound target");
        std::size_t idx = 0;
        double acc = 0.0;
        std::size_t bit = 1;
        while ((bit << 1) < tree_.size()) bit <<= 1;
        for (; bit != 0; bit >>= 1) {
            const std::size_t next = idx + bit;
            if (next < tree_.size() && acc + tree_[next] <= target) {
                idx = next;
                acc += tree_[next];
            }
        }
        return idx; // 0-based because idx is count of entries <= target
    }

private:
    std::vector<double> values_;
    std::vector<double> tree_;
};

} // namespace nfnext
