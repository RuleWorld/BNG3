#pragma once

// Accelerator abstraction for the batched direct-SSA kernel.
//
// Every backend runs the same algorithm over the same flattened network and
// returns the same BatchSsaMetrics, so a backend only has to translate the
// network to device memory, launch one thread/queue-item per trajectory, and
// aggregate the results. Adding a backend means adding one translation unit
// that implements GpuSsaBackend plus a probe; nothing else changes.
//
// Backends compiled into this binary:
//   * engine/gpu/MetalSsaBackend.mm (Apple Metal)
//   * engine/gpu/CudaSsaBackend.cu  (NVIDIA CUDA)

#include "engine/BatchSsa.hpp"

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace bng::engine {

enum class GpuBackendKind { Auto, Cuda, Metal, None };

// Simulation parameters handed to a device kernel. The layout must match the
// device-side copy compiled into the kernel, so it lives here instead of in a
// backend translation unit.
struct GpuSimParams {
    uint32_t numSpecies = 0;
    uint32_t numReactions = 0;
    uint32_t numObservables = 0;
    uint32_t numOutputPoints = 0;
    uint32_t batchSize = 0;
    uint32_t maxSimSteps = 0;
    float tStart = 0.0f;
    float tEnd = 0.0f;
    uint64_t baseSeed = 0;
};

// One accelerator that can run a batch of SSA trajectories.
class GpuSsaBackend {
public:
    virtual ~GpuSsaBackend() = default;

    // Stable lowercase identifier: "cuda", "metal".
    virtual const char* name() const noexcept = 0;

    // Runs options.batchSize independent trajectories of net and returns the
    // aggregated mean/std-dev trajectories. Throws std::runtime_error when the
    // device cannot run the batch; callers are expected to fall back to the CPU
    // pool rather than approximate the result.
    virtual BatchSsaMetrics simulate(const FlattenedReactionNetwork& net,
                                     const BatchSsaOptions& options) = 0;
};
// Result of asking a backend whether it can run: the device description when
// it can, otherwise why it cannot.
struct GpuBackendProbe {
    std::string device;   // empty when the backend is not compiled in
    std::string failure;  // empty when the backend is usable

    bool usable() const { return failure.empty(); }
};

struct GpuBackendStatus {
    GpuBackendKind kind = GpuBackendKind::None;
    std::string name;      // "cuda" / "metal"
    bool compiled = false; // backend translation unit is part of this binary
    bool available = false;// compiled and a usable device was found
    std::string detail;    // device description, or why it is unusable
};

// Backends this binary knows about, whether or not they were compiled in.
std::vector<GpuBackendStatus> gpuBackendInventory();

// Best compiled and available backend; GpuBackendKind::None when there is none.
GpuBackendKind defaultGpuBackend();

bool gpuBackendAvailable(GpuBackendKind kind);

// Accepts "auto", "cuda", "metal", "none" (case-insensitive).
// Throws std::runtime_error on anything else so a typo fails closed.
GpuBackendKind gpuBackendFromName(const std::string& name);

const char* gpuBackendName(GpuBackendKind kind) noexcept;

// Instantiates a backend for net. GpuBackendKind::Auto resolves to
// defaultGpuBackend(). Returns nullptr when the backend was not compiled into
// this binary, and throws when it was compiled but no device is usable.
std::unique_ptr<GpuSsaBackend> makeGpuSsaBackend(GpuBackendKind kind,
                                                 const FlattenedReactionNetwork& net);

// Launch-overhead thresholds measured in docs/GPU_BATCH_SSA_EVALUATION.md.
// Below them the CPU pool is faster than any accelerator, so the GPU path is
// not worth attempting.
constexpr std::size_t kGpuBatchMinReactions = 50;
constexpr std::size_t kGpuBatchMinTrajectories = 1000;



inline bool gpuBatchSsaWorthwhile(std::size_t reactions,
                                  std::size_t trajectories) noexcept {
    return reactions >= kGpuBatchMinReactions &&
           trajectories >= kGpuBatchMinTrajectories;
}

} // namespace bng::engine