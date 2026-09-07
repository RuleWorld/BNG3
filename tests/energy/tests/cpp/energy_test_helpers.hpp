#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <limits>
#include <numeric>
#include <random>
#include <string>
#include <utility>
#include <vector>

namespace bng3_test {

inline bool nearly_equal(double a, double b, double atol = 1e-12, double rtol = 1e-12) {
    if (std::isnan(a) || std::isnan(b)) return false;
    if (std::isinf(a) || std::isinf(b)) return a == b;
    const double scale = std::max(std::fabs(a), std::fabs(b));
    return std::fabs(a - b) <= atol + rtol * scale;
}

inline double literal_delta_g(
    double base,
    std::uint64_t mask,
    const std::vector<std::pair<double, std::uint64_t>>& terms) {
    double value = base;
    for (const auto& term : terms) {
        if ((mask & term.second) == term.second) value += term.first;
    }
    return value;
}

inline double arrhenius_factor(double delta_g, double phi, double rt, bool forward) {
    const double slope = forward ? phi : (phi - 1.0);
    return std::exp(-slope * delta_g / rt);
}

inline std::vector<std::uint64_t> all_masks(std::size_t n) {
    std::vector<std::uint64_t> masks;
    const std::uint64_t total = std::uint64_t{1} << n;
    masks.reserve(static_cast<std::size_t>(total));
    for (std::uint64_t mask = 0; mask < total; ++mask) masks.push_back(mask);
    return masks;
}

inline std::mt19937_64 deterministic_rng() {
    return std::mt19937_64(0xB1A3E5ULL);
}

inline double total_variation_distance(
    const std::vector<double>& p,
    const std::vector<double>& q) {
    if (p.size() != q.size()) return std::numeric_limits<double>::infinity();
    double sum = 0.0;
    for (std::size_t i = 0; i < p.size(); ++i) sum += std::fabs(p[i] - q[i]);
    return 0.5 * sum;
}

} // namespace bng3_test
