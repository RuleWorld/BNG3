#include "nfnext/trajectory.hpp"

#include <algorithm>
#include <atomic>
#include <thread>

namespace nfnext {

std::vector<TrajectoryResult> TrajectoryBatchRunner::run(
    const TrajectoryRequest& request, std::size_t trajectories, std::size_t threads) {
    std::vector<TrajectoryResult> results(trajectories);
    if (trajectories == 0) return results;
    if (threads == 0) threads = std::max<std::size_t>(1, std::thread::hardware_concurrency());
    threads = std::min(threads, trajectories);
    std::atomic<std::size_t> next{0};
    std::vector<std::thread> workers;
    workers.reserve(threads);
    for (std::size_t t = 0; t < threads; ++t) {
        workers.emplace_back([&] {
            for (;;) {
                const std::size_t i = next.fetch_add(1, std::memory_order_relaxed);
                if (i >= trajectories) break;
                GenomeLattice lattice(request.lattice);
                for (Position p : request.initial_positions) lattice.place(p);
                results[i] = TrajectoryResult{static_cast<std::uint64_t>(i),
                    lattice.run(request.max_events, request.max_time, request.seed, static_cast<std::uint64_t>(i))};
            }
        });
    }
    for (auto& w : workers) w.join();
    return results;
}

} // namespace nfnext
