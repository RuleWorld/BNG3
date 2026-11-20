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

struct NfnextMetalOutput {
    std::string device;
    std::vector<float> observables;
    std::vector<std::uint64_t> eventCounts;
    double wallTimeMs{0.0};
    double dispatchWaitTimeMs{0.0};
};

NfnextMetalOutput simulateNfnextUnaryStateMetal(
    const NfnextUnaryStatePlan& plan, const NfnextGpuRequest& request);

} // namespace bng::engine::detail
