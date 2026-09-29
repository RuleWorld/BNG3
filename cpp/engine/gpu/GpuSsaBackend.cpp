// Backend registry for the batched direct-SSA GPU path.
//
// This translation unit is always compiled. It knows which backends were built
// in (BNG3_HAS_CUDA / BNG3_HAS_METAL), probes them, and hands out backend
// instances. Backend code never sees each other.

#include "engine/gpu/GpuSsaBackend.hpp"

#include <algorithm>
#include <cctype>
#include <stdexcept>

namespace bng::engine {

#if defined(BNG3_HAS_CUDA)
// Implemented in engine/gpu/CudaSsaBackend.cu.
std::unique_ptr<GpuSsaBackend> makeCudaSsaBackend(const FlattenedReactionNetwork& net);
GpuBackendProbe probeCudaBackend();
#endif

#if defined(BNG3_HAS_METAL)
// Implemented in engine/gpu/MetalSsaBackend.mm.
std::unique_ptr<GpuSsaBackend> makeMetalSsaBackend(const FlattenedReactionNetwork& net);
GpuBackendProbe probeMetalBackend();
#endif

namespace {


std::string lowercase(const std::string& text) {
    std::string out = text;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return out;
}

GpuBackendStatus notCompiled(GpuBackendKind kind, const char* name) {
    GpuBackendStatus status;
    status.kind = kind;
    status.name = name;
    status.compiled = false;
    status.available = false;
    status.detail = "not compiled into this build";
    return status;
}

GpuBackendStatus statusFromProbe(GpuBackendKind kind, const char* name,
                                 GpuBackendProbe probe) {
    GpuBackendStatus status;
    status.kind = kind;
    status.name = name;
    status.compiled = true;
    status.available = probe.usable();
    status.detail = probe.usable() ? probe.device : probe.failure;
    return status;
}

} // anonymous namespace

std::vector<GpuBackendStatus> gpuBackendInventory() {
    std::vector<GpuBackendStatus> inventory;
    inventory.reserve(2);

#if defined(BNG3_HAS_CUDA)
    inventory.push_back(statusFromProbe(GpuBackendKind::Cuda, "cuda", probeCudaBackend()));
#else
    inventory.push_back(
        notCompiled(GpuBackendKind::Cuda, "cuda"));
#endif

#if defined(BNG3_HAS_METAL)
    inventory.push_back(statusFromProbe(GpuBackendKind::Metal, "metal", probeMetalBackend()));
#else
    inventory.push_back(
        notCompiled(GpuBackendKind::Metal, "metal"));
#endif

    return inventory;
}

GpuBackendKind defaultGpuBackend() {
    for (const auto& status : gpuBackendInventory()) {
        if (status.available) {
            return status.kind;
        }
    }
    return GpuBackendKind::None;
}

bool gpuBackendAvailable(GpuBackendKind kind) {
    for (const auto& status : gpuBackendInventory()) {
        if (status.kind == kind) {
            return status.available;
        }
    }
    return false;
}

const char* gpuBackendName(GpuBackendKind kind) noexcept {
    switch (kind) {
        case GpuBackendKind::Cuda:  return "cuda";
        case GpuBackendKind::Metal: return "metal";
        case GpuBackendKind::None:  return "none";
        case GpuBackendKind::Auto:  break;
    }
    return "auto";
}

GpuBackendKind gpuBackendFromName(const std::string& name) {
    const std::string key = lowercase(name);
    if (key.empty() || key == "auto") return GpuBackendKind::Auto;
    if (key == "cuda") return GpuBackendKind::Cuda;
    if (key == "metal") return GpuBackendKind::Metal;
    if (key == "none" || key == "cpu" || key == "off") return GpuBackendKind::None;
    throw std::runtime_error("Unknown GPU backend: '" + name +
                             "' (expected auto, cuda, metal, or none)");
}

std::unique_ptr<GpuSsaBackend> makeGpuSsaBackend(GpuBackendKind kind,
                                                 const FlattenedReactionNetwork& net) {
    if (kind == GpuBackendKind::Auto) {
        kind = defaultGpuBackend();
    }
    if (kind == GpuBackendKind::None) {
        return nullptr;
    }
    if (kind == GpuBackendKind::Cuda) {
#if defined(BNG3_HAS_CUDA)
        return makeCudaSsaBackend(net);
#else
        throw std::runtime_error(
            "CUDA backend not compiled into this build (configure with -DBNG3_ENABLE_CUDA=ON)");
#endif
    }
#if defined(BNG3_HAS_METAL)
    return makeMetalSsaBackend(net);
#else
    throw std::runtime_error(
        "Metal backend not compiled into this build (Apple platforms only)");
#endif
}

} // namespace bng::engine
