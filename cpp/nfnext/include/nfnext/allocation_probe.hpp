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
inline void* operator new(std::size_t size) {
    void* memory = std::malloc(size == 0 ? 1 : size);
    if (memory == nullptr) throw std::bad_alloc();
    if (::nfnext::allocation_probe_detail::enabled)
        ::nfnext::allocation_probe_detail::allocations.fetch_add(1, std::memory_order_relaxed);
    return memory;
}

inline void* operator new[](std::size_t size) { return ::operator new(size); }
inline void operator delete(void* memory) noexcept { std::free(memory); }
inline void operator delete[](void* memory) noexcept { std::free(memory); }
inline void operator delete(void* memory, std::size_t) noexcept { std::free(memory); }
inline void operator delete[](void* memory, std::size_t) noexcept { std::free(memory); }
