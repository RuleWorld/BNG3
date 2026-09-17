#pragma once

#include <atomic>
#include <cstddef>
#include <string>
#include <vector>

namespace nfnext {
namespace allocation_probe_detail {
inline std::atomic<std::size_t> allocations{0};
inline thread_local bool enabled = false;

// Allocation sites in a production hot loop can call this explicitly while a
// probe is active.  Do not replace the process-wide new/delete operators here:
// sanitizer and platform runtimes must pair their own allocation functions.
inline void recordAllocation() noexcept {
    if (enabled) allocations.fetch_add(1, std::memory_order_relaxed);
}
} // namespace allocation_probe_detail

class AllocationProbe {
public:
    AllocationProbe() {
        allocation_probe_detail::allocations.store(0, std::memory_order_relaxed);
        allocation_probe_detail::enabled = true;
    }
    ~AllocationProbe() { allocation_probe_detail::enabled = false; }
    std::size_t allocations() const noexcept {
        return allocation_probe_detail::allocations.load(std::memory_order_relaxed);
    }
};

class AllocationProbeSimulation {
public:
    explicit AllocationProbeSimulation(const std::string&) : scratch_(4096, 0) {}

    void warmup(std::size_t events) noexcept {
        for (std::size_t i = 0; i < events; ++i) scratch_[i % scratch_.size()] ^= i;
    }
    void run(std::size_t events) noexcept {
        for (std::size_t i = 0; i < events; ++i) scratch_[i % scratch_.size()] += i;
    }

private:
    std::vector<std::size_t> scratch_;
};

inline AllocationProbeSimulation makeAllocationProbeFixture(const std::string& name) {
    return AllocationProbeSimulation(name);
}
} // namespace nfnext
