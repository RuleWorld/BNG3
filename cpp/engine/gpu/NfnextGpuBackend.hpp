#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace bng::compile { class CompiledModel; }

namespace bng::engine {

struct NfnextGpuRequest {
    std::vector<double> sampleTimes;
    std::uint64_t seed{0};
    std::size_t batchSize{1024};
    std::uint64_t maxEvents{1'000'000};
    std::size_t maxParticles{1'000'000};
    std::string backend{"metal"};
};

struct NfnextGpuResult {
    std::vector<double> sampleTimes;
    std::vector<std::string> observableNames;
    // Row-major [trajectory, sample time, observable].
    std::vector<float> observables;
    std::vector<std::uint64_t> eventCounts;
    std::size_t batchSize{0};
    std::string backend;
    std::string device;
    double wallTimeMs{0.0};
    double dispatchWaitTimeMs{0.0};
    double setupTimeMs{0.0};
    std::size_t deviceMemoryBytes{0};
};

// Execute the bounded NFnext single-molecule, single-site state-change family
// on an explicitly selected GPU. Unsupported model semantics fail closed.
NfnextGpuResult simulateNfnextGpu(const bng::compile::CompiledModel& model,
                                  const NfnextGpuRequest& request);

} // namespace bng::engine
