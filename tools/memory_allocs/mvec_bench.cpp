// swarm-memory population benchmark for the Ullmann M-matrix allocation
// strategy (Ullmann.cpp:73-85, UllmannBase::initialize_M_vec).
//
// This is a STANDALONE reproduction of the measured allocation pattern, not a
// patch: it builds the same `std::vector<ullmann_M_t>` shape (one std::map
// row per node of Ga, each row an owning `new std::vector<Node*>`, at every
// recursion level) and counts allocations for each candidate strategy.
//
// It exists so the population table has allocs/op and bytes/op per candidate in
// the same units as the headline, WITHOUT editing production files that belong
// to another agent's declared area. The winner is then implemented in cpp/core
// by whoever owns it, with these numbers as the target.
//
// Usage: mvec_bench <levels> <nodes> <reps>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <map>
#include <vector>
#include <memory>
#include <new>

namespace alloc_count {
static bool enabled = false;
static std::size_t count = 0;
static std::size_t bytes = 0;
static std::size_t peak_live = 0;
static std::size_t live = 0;
inline void onAlloc(std::size_t n) {
    ++count; bytes += n; live += n; if (live > peak_live) peak_live = live;
}
inline void onFree(std::size_t n) { live = (live >= n) ? live - n : 0; }
inline void reset() { count = 0; bytes = 0; peak_live = 0; live = 0; }
} // namespace alloc_count

namespace {
inline void* doAlloc(std::size_t n) {
    void* p = malloc(n ? n : 1);
    if (!p) throw std::bad_alloc();
    if (alloc_count::enabled) alloc_count::onAlloc(n);
    return p;
}
inline void* doAllocAligned(std::size_t n, std::size_t a) {
    const std::size_t r = ((n + a - 1) / a) * a;
    void* p = aligned_alloc(a, r ? r : a);
    if (!p) throw std::bad_alloc();
    if (alloc_count::enabled) alloc_count::onAlloc(n);
    return p;
}
} // namespace

void* operator new(std::size_t n) { return doAlloc(n); }
void* operator new[](std::size_t n) { return doAlloc(n); }
void* operator new(std::size_t n, std::align_val_t a) { return doAllocAligned(n, static_cast<std::size_t>(a)); }
void* operator new[](std::size_t n, std::align_val_t a) { return doAllocAligned(n, static_cast<std::size_t>(a)); }
void operator delete(void* p) noexcept { free(p); }
void operator delete[](void* p) noexcept { free(p); }
void operator delete(void* p, std::size_t) noexcept { free(p); }
void operator delete[](void* p, std::size_t) noexcept { free(p); }
void operator delete(void* p, std::align_val_t) noexcept { free(p); }
void operator delete[](void* p, std::align_val_t) noexcept { free(p); }
void operator delete(void* p, std::size_t, std::align_val_t) noexcept { free(p); }
void operator delete[](void* p, std::size_t, std::align_val_t) noexcept { free(p); }

// --- The shape under test -------------------------------------------------
// ullmann_M_t in cpp/core/BNGcore.hpp is std::map<Node*, node_container_t*>,
// where node_container_t is std::vector<Node*>. M_vec is a vector of those,
// one per recursion level.
struct FakeNode { int id; };

using node_container_t = std::vector<FakeNode*>;
using ullmann_M_t = std::map<FakeNode*, node_container_t*>;

struct RowOwnership {
    // Deleter matching the production code, which `delete`s each row pointer.
    using deleter = std::default_delete<node_container_t>;
    std::unique_ptr<node_container_t, deleter> owned;
    node_container_t* raw = nullptr;
};

// CANDIDATE A — baseline: exactly what initialize_M_vec does today.
static void candidateA(std::vector<ullmann_M_t>& M_vec, std::vector<FakeNode*>& Ga) {
    for (auto& level : M_vec) {
        for (auto* n : Ga) {
            level.insert(std::pair<FakeNode*, node_container_t*>(n, new node_container_t));
        }
    }
}

// CANDIDATE B — arena/pooling: one contiguous block for all rows at a level,
// rows handed out by bump pointer. Destructor frees the block once.
struct Arena {
    node_container_t* base = nullptr;
    std::size_t used = 0;
    std::size_t cap = 0;
    explicit Arena(std::size_t n) : base(new node_container_t[n]), cap(n) {}
    ~Arena() { delete[] base; }
    node_container_t* take() { return base + used++; }
};

// CANDIDATE C — reserve/sizing + in-place row reuse: keep the row containers
// alive across calls in a caller-owned pool, and reserve the map.
static void candidateC(std::vector<ullmann_M_t>& M_vec, std::vector<FakeNode*>& Ga,
                       std::vector<std::vector<node_container_t>>& pool) {
    for (std::size_t li = 0; li < M_vec.size(); ++li) {
        auto& level = M_vec[li];
        auto& rows = pool[li];
        rows.resize(Ga.size());
        for (std::size_t i = 0; i < Ga.size(); ++i) {
            rows[i].clear();
            level.insert(std::pair<FakeNode*, node_container_t*>(Ga[i], &rows[i]));
        }
    }
}

// CANDIDATE D — structure change: flat index-keyed rows (SoA), no std::map
// node and no per-row pointer at all.
struct FlatM {
    std::vector<node_container_t> rows;
    void init(std::size_t n) { rows.assign(n, node_container_t{}); }
    node_container_t* row(std::size_t i) { return &rows[i]; }
};

static void candidateD(std::vector<FlatM>& M_vec, std::size_t n) {
    for (auto& level : M_vec) level.init(n);
}

struct Result { std::size_t allocs; std::size_t bytes; double seconds; };

template <typename F>
static Result run(int reps, F&& fn) {
    alloc_count::reset();
    const auto t0 = std::chrono::steady_clock::now();
    alloc_count::enabled = true;
    for (int r = 0; r < reps; ++r) fn();
    alloc_count::enabled = false;
    const auto t1 = std::chrono::steady_clock::now();
    return {alloc_count::count, alloc_count::bytes,
            std::chrono::duration<double>(t1 - t0).count()};
}

int main(int argc, char** argv) {
    const std::size_t levels = argc > 1 ? std::strtoul(argv[1], nullptr, 10) : 12;
    const std::size_t nodes = argc > 2 ? std::strtoul(argv[2], nullptr, 10) : 6;
    const int reps = argc > 3 ? std::atoi(argv[3]) : 10;

    std::vector<FakeNode*> Ga;
    for (std::size_t i = 0; i < nodes; ++i) Ga.push_back(new FakeNode{static_cast<int>(i)});

    std::printf("# mvec_bench levels=%zu nodes=%zu reps=%d\n", levels, nodes, reps);
    std::printf("# ops_per_rep = levels*nodes = %zu row allocations in the baseline\n", levels * nodes);

    // A — baseline
    {
        std::vector<ullmann_M_t> M_vec(levels);
        Result best{0, 0, 0};
        for (int trial = 0; trial < 5; ++trial) {
            std::vector<ullmann_M_t> mv(levels);
            Result r = run(reps, [&] {
                for (int k = 0; k < reps; ++k) {
                    for (auto& level : mv) {
                        for (auto* n : Ga) level.insert({n, new node_container_t});
                    }
                    for (auto& level : mv) { for (auto& kv : level) delete kv.second; level.clear(); }
                }
            });
            (void)best;
            if (trial == 0 || r.allocs < best.allocs) best = r;
        }
        std::printf("A_baseline_new_per_row        allocs=%-9zu bytes=%-11zu seconds=%.5f\n",
                    best.allocs, best.bytes, best.seconds);
    }

    // B — arena
    {
        Result best{0, 0, 0};
        for (int trial = 0; trial < 5; ++trial) {
            Result r = run(reps, [&] {
                for (int k = 0; k < reps; ++k) {
                    std::vector<std::unique_ptr<Arena>> arenas;
                    arenas.reserve(levels);
                    for (std::size_t li = 0; li < levels; ++li) {
                        arenas.push_back(std::make_unique<Arena>(nodes));
                    }
                    for (auto& a : arenas) { (void)a->take(); }
                }
            });
            if (trial == 0 || r.allocs < best.allocs) best = r;
        }
        std::printf("B_arena_one_block_per_level  allocs=%-9zu bytes=%-11zu seconds=%.5f\n",
                    best.allocs, best.bytes, best.seconds);
    }

    // C — caller-owned row pool + map
    {
        Result best{0, 0, 0};
        for (int trial = 0; trial < 5; ++trial) {
            std::vector<std::vector<node_container_t>> pool(levels);
            Result r = run(reps, [&] {
                for (int k = 0; k < reps; ++k) {
                    std::vector<ullmann_M_t> mv(levels);
                    for (std::size_t li = 0; li < levels; ++li) {
                        auto& rows = pool[li];
                        rows.resize(nodes);
                        for (std::size_t i = 0; i < nodes; ++i) {
                            rows[i].clear();
                            mv[li].insert({Ga[i], &rows[i]});
                        }
                    }
                    for (auto& level : mv) level.clear();
                }
            });
            if (trial == 0 || r.allocs < best.allocs) best = r;
        }
        std::printf("C_row_pool_plus_map          allocs=%-9zu bytes=%-11zu seconds=%.5f\n",
                    best.allocs, best.bytes, best.seconds);
    }

    // D — flat SoA rows, no map, no per-row pointer
    {
        Result best{0, 0, 0};
        for (int trial = 0; trial < 5; ++trial) {
            std::vector<FlatM> mv(levels);
            Result r = run(reps, [&] {
                for (int k = 0; k < reps; ++k) {
                    for (auto& level : mv) level.init(nodes);
                }
            });
            if (trial == 0 || r.allocs < best.allocs) best = r;
        }
        std::printf("D_flat_soa_rows              allocs=%-9zu bytes=%-11zu seconds=%.5f\n",
                    best.allocs, best.bytes, best.seconds);
    }

    for (auto* n : Ga) delete n;
    return 0;
}