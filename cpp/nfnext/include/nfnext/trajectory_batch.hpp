#pragma once

#include "nfnext/counter_rng.hpp"
#include "nfnext/replay.hpp"

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <thread>
#include <vector>

namespace nfnext {

struct BatchRequest {
    std::uint64_t seed{0};
    std::uint64_t events{0};
    bool logging{false};
    bool profiling{false};
};

struct BatchResult {
    std::uint64_t trajectory_id{0};
    std::uint64_t traceHash{0};
    std::uint64_t stateHash{0};
    std::uint64_t finalTimeBits{0};
};

inline std::uint64_t batchMix(std::uint64_t x) noexcept {
    return replayMix(x);
}

inline BatchResult runBatchTrajectory(const BatchRequest& request, std::uint64_t id) {
    CounterRng rng(request.seed, id);
    std::uint64_t trace = batchMix(request.seed ^ id);
    std::uint64_t state = batchMix(id + 1);
    double time = 0.0;
    for (std::uint64_t event = 0; event < request.events; ++event) {
        const auto wait_word = RngLayout::exactSSA().word(RngPurpose::WaitingTime, event);
        const auto choice_word = RngLayout::exactSSA().word(RngPurpose::FamilyChoice, event);
        const auto wait = rng.u64(wait_word);
        const auto choice = rng.u64(choice_word);
        trace = batchMix(trace ^ wait ^ (choice + event));
        state = batchMix(state ^ choice);
        time += (static_cast<double>(wait >> 11) + 0.5) / 9007199254740992.0;
    }
    std::uint64_t time_bits = 0;
    static_assert(sizeof(time_bits) == sizeof(time));
    std::memcpy(&time_bits, &time, sizeof(time_bits));
    return BatchResult{id, trace, state, time_bits};
}

class TrajectoryBatch {
public:
    static std::vector<BatchResult> run(const BatchRequest& request, std::size_t trajectories,
                                        std::size_t threads = 0) {
        std::vector<BatchResult> result(trajectories);
        if (trajectories == 0) return result;
        if (threads == 0) threads = std::max<std::size_t>(1, std::thread::hardware_concurrency());
        threads = std::min(threads, trajectories);
        std::atomic<std::size_t> next{0};
        std::vector<std::thread> workers;
        workers.reserve(threads);
        for (std::size_t worker = 0; worker < threads; ++worker) workers.emplace_back([&] {
            for (;;) {
                const auto id = next.fetch_add(1, std::memory_order_relaxed);
                if (id >= trajectories) return;
                result[id] = runBatchTrajectory(request, id);
            }
        });
        for (auto& worker : workers) worker.join();
        return result;
    }
};

inline BatchRequest makeDeterministicBatchFixture(std::uint64_t seed, std::uint64_t events) {
    return BatchRequest{seed, events, false, false};
}

inline BatchRequest makeVariableRuntimeBatchFixture() {
    return BatchRequest{0xA11CEULL, 257, false, false};
}

inline std::vector<std::uint64_t> batchHashes(const std::vector<BatchResult>& results) {
    std::vector<std::uint64_t> hashes;
    hashes.reserve(results.size());
    for (const auto& result : results) hashes.push_back(batchMix(result.traceHash ^ result.stateHash ^ result.finalTimeBits));
    return hashes;
}

} // namespace nfnext
