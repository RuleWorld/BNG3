#pragma once

#include <cmath>
#include <cstdint>
#include <limits>

namespace nfnext {

// Stateless counter-based RNG. Results depend only on (seed, stream, counter),
// so batched trajectories are reproducible independent of thread scheduling.
class CounterRng {
public:
    CounterRng(std::uint64_t seed, std::uint64_t stream) noexcept : seed_(seed), stream_(stream) {}

    std::uint64_t u64(std::uint64_t counter) const noexcept {
        std::uint64_t x = seed_ ^ (stream_ * 0x9E3779B97F4A7C15ULL) ^ (counter * 0xD2B74407B1CE6E93ULL);
        x += 0x9E3779B97F4A7C15ULL;
        x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
        x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
        return x ^ (x >> 31);
    }

    double uniformOpen01(std::uint64_t counter) const noexcept {
        // 53 random bits mapped strictly inside (0,1).
        const std::uint64_t bits = u64(counter) >> 11;
        return (static_cast<double>(bits) + 0.5) * (1.0 / 9007199254740992.0);
    }

    double exponential(std::uint64_t counter, double rate) const noexcept {
        if (!(rate > 0.0)) return std::numeric_limits<double>::infinity();
        return -std::log(uniformOpen01(counter)) / rate;
    }

private:
    std::uint64_t seed_;
    std::uint64_t stream_;
};

} // namespace nfnext
