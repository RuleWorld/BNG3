#include "nfnext/allocation_probe.hpp"

#ifndef _MSC_VER
#ifndef NFNEXT_ASAN
void* operator new(std::size_t size) {
    void* memory = std::malloc(size == 0 ? 1 : size);
    if (memory == nullptr) throw std::bad_alloc();
    if (::nfnext::allocation_probe_detail::enabled)
        ::nfnext::allocation_probe_detail::allocations.fetch_add(1, std::memory_order_relaxed);
    return memory;
}

void* operator new[](std::size_t size) { return ::operator new(size); }
void operator delete(void* memory) noexcept { std::free(memory); }
void operator delete[](void* memory) noexcept { std::free(memory); }
void operator delete(void* memory, std::size_t) noexcept { std::free(memory); }
void operator delete[](void* memory, std::size_t) noexcept { std::free(memory); }
#endif
#endif
