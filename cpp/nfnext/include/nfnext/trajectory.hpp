#pragma once

#include "nfnext/lattice.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace nfnext {

struct TrajectoryRequest {
    LatticeConfig lattice;
    std::vector<Position> initial_positions;
    std::uint64_t max_events{0};
    double max_time{0.0};
    std::uint64_t seed{0};
};

struct TrajectoryResult {
    std::uint64_t trajectory_id{0};
    LatticeRunResult run;
};

class TrajectoryBatchRunner {
public:
    static std::vector<TrajectoryResult> run(
        const TrajectoryRequest& request,
        std::size_t trajectories,
        std::size_t threads = 0);
};

} // namespace nfnext
