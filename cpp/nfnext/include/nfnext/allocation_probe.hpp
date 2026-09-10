#pragma once

#include <atomic>
#include <cstddef>
#include <cstdlib>
#include <new>
#include <string>
#include <vector>

namespace nfnext {
namespace allocation_probe_detail {
inline std::atomic<std::size_t> allocations{0};
inline thread_local bool enabled = false;
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

#ifndef _MSC_VER
#if defined(__has_feature)
#if __has_feature(address_sanitizer)
#define NFNEXT_ASAN 1
#endif
#endif
#ifndef NFNEXT_ASAN
void* operator new(std::size_t size);
void* operator new[](std::size_t size);
void operator delete(void* memory) noexcept;
void operator delete[](void* memory) noexcept;
void operator delete(void* memory, std::size_t) noexcept;
void operator delete[](void* memory, std::size_t) noexcept;
#endif
#endif
