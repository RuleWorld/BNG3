#pragma once

#include "engine/gpu/NfnextGpuBackend.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace bng::engine::detail {

struct NfnextUnaryStatePlan {
    std::vector<std::int32_t> initialStates;
    std::vector<std::uint32_t> transitionOffsets;
    std::vector<std::int32_t> transitionDestinations;
    std::vector<float> transitionRates;
    std::vector<std::int32_t> observableStates;
    std::vector<std::string> observableNames;
};

struct NfnextDeviceOutput {
    std::string device;
    std::vector<float> observables;
    std::vector<std::uint64_t> eventCounts;
    double wallTimeMs{0.0};
    double dispatchWaitTimeMs{0.0};
    // Shader compilation, pipeline creation and device-buffer allocation are
    // cold-start costs; dispatchWaitTimeMs covers only the kernel execution.
    double setupTimeMs{0.0};
    std::size_t deviceMemoryBytes{0};
};

using NfnextMetalOutput = NfnextDeviceOutput;

NfnextDeviceOutput simulateNfnextUnaryStateMetal(
    const NfnextUnaryStatePlan& plan, const NfnextGpuRequest& request);

NfnextDeviceOutput simulateNfnextUnaryStateCuda(
    const NfnextUnaryStatePlan& plan, const NfnextGpuRequest& request);

} // namespace bng::engine::detail
