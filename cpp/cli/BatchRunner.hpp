#pragma once

#include <cstddef>
#include <filesystem>
#include <vector>

namespace bng::cli {

struct ParallelBatchOptions {
    std::filesystem::path executable;
    std::vector<std::filesystem::path> inputs;
    std::size_t maxJobs = 1;
    std::filesystem::path outputRoot;
    bool checkOnly = false;
    bool verbose = false;
};

// Run independent model files in isolated child processes. Each child gets a
// private working directory and input copy, so generated artifacts and mutable
// runtime state cannot collide across jobs.
int runParallelBatch(const ParallelBatchOptions& options);

} // namespace bng::cli
