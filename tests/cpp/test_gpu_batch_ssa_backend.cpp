// Contract test for the batched-SSA GPU backend registry.
//
// The registry is what decides whether a batch runs on an accelerator or on the
// CPU pool, so its selection, naming, and fail-closed behaviour are
// user-visible: a typo in a backend name must never silently degrade to the CPU
// pool, and a build without any backend must say so instead of pretending.

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <algorithm>
#include <stdexcept>
#include <string>
#include <vector>

#include "engine/BatchSsa.hpp"
#include "engine/gpu/GpuSsaBackend.hpp"

using namespace bng::engine;

namespace {

FlattenedReactionNetwork emptyNetwork() {
    return FlattenedReactionNetwork{};
}

} // anonymous namespace

TEST_CASE("every known GPU backend is reported with a stable name", "[gpu]") {
    const auto inventory = gpuBackendInventory();

    std::vector<std::string> names;
    for (const auto& status : inventory) {
        names.push_back(status.name);
        // A backend that was not compiled in must say so rather than claim a device.
        if (!status.compiled) {
            CHECK_FALSE(status.available);
            CHECK(status.detail == "not compiled into this build");
        }
        if (status.available) {
            CHECK(status.compiled);
            CHECK_FALSE(status.detail.empty());
        }
    }
    // Order is stable so "the first available backend" is deterministic.
    REQUIRE(names == std::vector<std::string>{"cuda", "metal"});
}

TEST_CASE("the default backend is one that is actually available", "[gpu]") {
    const auto selected = defaultGpuBackend();
    const auto inventory = gpuBackendInventory();

    if (selected == GpuBackendKind::None) {
        CHECK(std::none_of(inventory.begin(), inventory.end(),
                           [](const GpuBackendStatus& s) { return s.available; }));
    } else {
        REQUIRE(gpuBackendAvailable(selected));
    }
    // Nothing may be reported available that the default selection skipped over
    // without an error; the name must match an inventory entry.
    const std::string name = gpuBackendName(selected);
    CHECK((name == "none" || name == "cuda" || name == "metal"));
}

TEST_CASE("backend names round-trip and unknown names fail closed", "[gpu]") {
    CHECK(gpuBackendFromName("") == GpuBackendKind::Auto);
    CHECK(gpuBackendFromName("auto") == GpuBackendKind::Auto);
    CHECK(gpuBackendFromName("CUDA") == GpuBackendKind::Cuda);
    CHECK(gpuBackendFromName("Metal") == GpuBackendKind::Metal);
    CHECK(gpuBackendFromName("none") == GpuBackendKind::None);
    CHECK(gpuBackendFromName("cpu") == GpuBackendKind::None);

    // A typo must be an error, not a silent CPU fallback.
    CHECK_THROWS_AS(gpuBackendFromName("opencl"), std::runtime_error);
    CHECK_THROWS_AS(gpuBackendFromName("vulkan"), std::runtime_error);

    for (const auto kind : {GpuBackendKind::Cuda, GpuBackendKind::Metal, GpuBackendKind::None}) {
        CHECK(gpuBackendFromName(gpuBackendName(kind)) == kind);
    }
}

TEST_CASE("selecting 'none' yields no backend instead of an error", "[gpu]") {
    CHECK(makeGpuSsaBackend(GpuBackendKind::None, emptyNetwork()) == nullptr);
}

TEST_CASE("selecting an unavailable backend raises rather than approximating", "[gpu]") {
    for (const auto& status : gpuBackendInventory()) {
        if (status.available) {
            continue;
        }
        if (status.compiled) {
            // Compiled in but no device: constructing must fail loudly.
            CHECK_THROWS_AS(makeGpuSsaBackend(status.kind, emptyNetwork()),
                            std::runtime_error);
        } else {
            // Not compiled in: the message must name the configure switch.
            CHECK_THROWS_WITH(
                makeGpuSsaBackend(status.kind, emptyNetwork()),
                Catch::Matchers::ContainsSubstring("not compiled into this build"));
        }
    }
}

TEST_CASE("accelerators are only attempted above the launch-overhead threshold", "[gpu]") {
    // Documented in docs/GPU_BATCH_SSA_EVALUATION.md: below these sizes the CPU
    // pool wins, so a small batch must not pay for a device round trip.
    CHECK_FALSE(gpuBatchSsaWorthwhile(kGpuBatchMinReactions, kGpuBatchMinTrajectories - 1));
    CHECK_FALSE(gpuBatchSsaWorthwhile(kGpuBatchMinReactions - 1, kGpuBatchMinTrajectories));
    CHECK(gpuBatchSsaWorthwhile(kGpuBatchMinReactions, kGpuBatchMinTrajectories));
}
