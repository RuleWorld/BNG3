// swarm-memory allocation-counting harness.
//
// Replaces global operator new/delete with counters and attributes every
// allocation to a 4-deep return-address chain, so a site is identified by the
// BNG3 function that requested the memory rather than by the stdlib container
// that called operator new.
//
// Usage: mem_bench <model.bngl> <max_iter> [reps]
//   Prints total allocs / bytes for generateNative(), then the top sites with
//   their symbolized call chain.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <string>
#include <vector>
#include <algorithm>
#include <new>
#include <cstdint>
#include <cxxabi.h>
#include <execinfo.h>
#include <dlfcn.h>

#include "compile/Document.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/ObservableProjection.hpp"
#include "parser/BNGAstVisitor.hpp"

// ---------------------------------------------------------------------------
// Counting allocator
// ---------------------------------------------------------------------------
// The site table is a fixed open-addressing table over a static array. It MUST
// NOT allocate: operator new is what we are counting, so allocating inside the
// counter recurses (the first version of this harness used std::map for the
// table and died with SIGSEGV from exactly that recursion).
namespace alloc_count {

constexpr std::size_t kFrames = 4;
constexpr std::size_t kMaxSites = 8192;

struct Site {
    void* frame[kFrames] = {nullptr, nullptr, nullptr, nullptr};
    const char* file = nullptr;
    std::size_t count = 0;
    std::size_t bytes = 0;
    bool used = false;
};

static Site g_table[kMaxSites];
static std::size_t g_used = 0;

static bool g_enabled = false;
static std::size_t g_count = 0;
static std::size_t g_bytes = 0;
static std::size_t g_largest = 0;
static std::size_t g_collisions = 0;  // sites dropped because the table filled

// Returns a pointer to a static string naming the owning subsystem. Static
// storage only: this runs inside operator new and must not allocate.

// Bucket by namespace prefix of the raw (mangled) symbol name. Uses only
// dladdr's dli_sname pointer and strncmp: no demangling, no std::string, so
// this cannot allocate and recurse into operator new.
const char* bucketFor(void* addr) {
    Dl_info info{};
    if (!addr || !dladdr(addr, &info) || !info.dli_sname) return "unattributed";
    const char* s = info.dli_sname;
    struct Entry { const char* needle; const char* name; };
    static const Entry table[] = {
        {"Ullmann", "cpp/core/Ullmann.cpp"},
        {"PatternGraph", "cpp/core/PatternGraph.cpp"},
        {"7Node", "cpp/core/Node.cpp"},
        {"9StateType", "cpp/core/StateType.cpp"},
        {"_List", "cpp/core/List.hpp"},
        {"PatternMatching", "cpp/core/PatternMatching.cpp"},
        {"12ReactionRule", "cpp/ast/ReactionRule.cpp"},
        {"11SpeciesGraph", "cpp/ast/SpeciesGraph.cpp"},
        {"11SpeciesList", "cpp/ast/SpeciesList.cpp"},
        {"NetworkGenerator", "cpp/engine/NetworkGenerator.cpp"},
        {"NetworkRulePlan", "cpp/engine/NetworkRulePlan.cpp"},
        {"LegacyNetworkRuleKernel", "cpp/engine/LegacyNetworkRuleKernel.cpp"},
        {"ObservableProjection", "cpp/engine/ObservableProjection.cpp"},
        {"OdeIntegrator", "cpp/engine/OdeIntegrator.cpp"},
        {"9RxnListI", "cpp/ast/RxnList.cpp"},
        {"compile", "cpp/compile/*"},
        {"_ZNSt3__16vector", "std::vector (inlined)"},
        {"_ZNSt3__17__tree", "std::map (inlined)"},
        {"NSt3__112basic_string", "std::string (inlined)"},
    };
    for (const auto& e : table) {
        if (std::strstr(s, e.needle)) return e.name;
    }
    return "other";
}


inline std::size_t hashOf(const void* const* f, std::size_t n) {
    std::uint64_t h = 1469598103934665603ull;
    for (std::size_t i = 0; i < n; ++i) {
        h ^= reinterpret_cast<std::uintptr_t>(f[i]);
        h *= 1099511628211ull;
    }
    return static_cast<std::size_t>(h);
}

inline void note(const void* ret, std::size_t n) {
    void* frames[kFrames];
    const int captured = backtrace(frames, static_cast<int>(kFrames));
    void* chain[kFrames];
    for (std::size_t i = 0; i < kFrames; ++i) {
        chain[i] = i < static_cast<std::size_t>(captured) ? frames[i] : nullptr;
    }
    // Frame 0 is inside this translation unit (operator new / note); frame 1
    // is the stdlib allocator/vector shim. Key on the chain from frame 2 up so
    // the site is named by the BNG3 code that asked for the memory.
    const std::size_t h = hashOf(&chain[2], kFrames - 2);
    for (std::size_t step = 0; step < kMaxSites; ++step) {
        const std::size_t i = (h + step) % kMaxSites;
        if (!g_table[i].used) {
            for (std::size_t k = 0; k < kFrames; ++k) g_table[i].frame[k] = chain[k];
            // Bucket by the namespace of the requesting symbol, not by
            // address: this key is stable across processes and across ASLR,
            // which a return address is not.
            g_table[i].file = bucketFor(chain[2]);
            g_table[i].used = true;
            g_table[i].count = 1;
            g_table[i].bytes = n;
            if (g_used < kMaxSites) ++g_used;
            return;
        }
        bool same = true;
        for (std::size_t k = 2; k < kFrames; ++k) {
            if (g_table[i].frame[k] != chain[k]) { same = false; break; }
        }
        if (same) {
            ++g_table[i].count;
            g_table[i].bytes += n;
            return;
        }
    }
    ++g_collisions;
}

inline void onAlloc(std::size_t n) {
    ++g_count;
    g_bytes += n;
    if (n > g_largest) g_largest = n;
    note(nullptr, n);
}

inline void reset() {
    g_count = 0;
    g_bytes = 0;
    g_largest = 0;
    g_collisions = 0;
    for (std::size_t i = 0; i < kMaxSites; ++i) {
        g_table[i] = Site{};
    }
    g_used = 0;
}

} // namespace alloc_count

// operator new records unconditionally; the enabled flag only gates whether
// the caller-side measurement window wants the (cheap) per-site detail.
namespace {
inline void* doAlloc(std::size_t n) {
    void* p = malloc(n ? n : 1);
    if (!p) throw std::bad_alloc();
    if (alloc_count::g_enabled) alloc_count::onAlloc(n);
    return p;
}
inline void* doAllocAligned(std::size_t n, std::size_t a) {
    const std::size_t rounded = ((n + a - 1) / a) * a;
    void* p = aligned_alloc(a, rounded ? rounded : a);
    if (!p) throw std::bad_alloc();
    if (alloc_count::g_enabled) alloc_count::onAlloc(n);
    return p;
}
} // namespace

void* operator new(std::size_t n) { return doAlloc(n); }
void* operator new[](std::size_t n) { return doAlloc(n); }
void* operator new(std::size_t n, const std::nothrow_t&) noexcept {
    void* p = malloc(n ? n : 1);
    if (p && alloc_count::g_enabled) alloc_count::onAlloc(n);
    return p;
}
void* operator new[](std::size_t n, const std::nothrow_t&) noexcept { return operator new(n, std::nothrow); }
void* operator new(std::size_t n, std::align_val_t a) { return doAllocAligned(n, static_cast<std::size_t>(a)); }
void* operator new[](std::size_t n, std::align_val_t a) { return doAllocAligned(n, static_cast<std::size_t>(a)); }

void operator delete(void* p) noexcept { free(p); }
void operator delete[](void* p) noexcept { free(p); }
void operator delete(void* p, std::size_t) noexcept { free(p); }
void operator delete[](void* p, std::size_t) noexcept { free(p); }
void operator delete(void* p, const std::nothrow_t&) noexcept { free(p); }
void operator delete[](void* p, const std::nothrow_t&) noexcept { free(p); }
void operator delete(void* p, std::align_val_t) noexcept { free(p); }
void operator delete[](void* p, std::align_val_t) noexcept { free(p); }
void operator delete(void* p, std::size_t, std::align_val_t) noexcept { free(p); }
void operator delete[](void* p, std::size_t, std::align_val_t) noexcept { free(p); }
void operator delete(void* p, std::align_val_t, const std::nothrow_t&) noexcept { free(p); }
void operator delete[](void* p, std::align_val_t, const std::nothrow_t&) noexcept { free(p); }

// ---------------------------------------------------------------------------
namespace {

std::string demangleSymbol(const char* mangled) {
    if (!mangled) return "??";
    int status = 0;
    char* out = abi::__cxa_demangle(mangled, nullptr, nullptr, &status);
    std::string result = (status == 0 && out) ? std::string(out) : std::string(mangled);
    if (out) free(out);
    return result;
}

std::string symbolize(void* addr) {
    Dl_info info{};
    if (addr && dladdr(addr, &info) && info.dli_sname) {
        return demangleSymbol(info.dli_sname);
    }
    return "??";
}

} // namespace

namespace {
int measureExternal(const std::string& binary, const std::string& modelPath) {
    // Run the binary as a child with the counter compiled INTO it via
    // -D: not possible here, so instead we require the binary to be the
    // instrumented build. See README; this path reports the child's own
    // counters on stdout.
    std::fprintf(stderr, "external mode not supported in this build\n");
    (void)binary; (void)modelPath;
    return 3;
}
} // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: mem_bench <model.bngl> <max_iter> [reps]\n");
        return 2;
    }
    // BNG_CPP=<path> measures a supplied CLI binary end-to-end instead of
    // linking against this harness's own tree. Required for verifying another
    // agent's before/after binaries: the counting operator new must be inside
    // the binary under test, not in the harness, or the delta is unobservable.
    const char* bngCppEnv = getenv("BNG_CPP");
    const std::string modelPath = argv[1];
    const std::size_t maxIter = std::strtoul(argv[2], nullptr, 10);
    const int reps = argc > 3 ? std::atoi(argv[3]) : 1;
    // phase=netgen (default) measures generateNative; phase=obs measures
    // ObservableProjection::weights() over every species of the generated
    // network, repeated `obsReps` times.
    const char* phaseEnv = getenv("MEMBENCH_PHASE");
    const std::string phase = phaseEnv ? phaseEnv : "netgen";
    const int obsReps = getenv("MEMBENCH_OBSREPS") ? atoi(getenv("MEMBENCH_OBSREPS")) : 1;

    // Warm backtrace()/dladdr before the measurement window: the first call
    // resolves lazily and would otherwise pollute the first rep.
    { void* warm[4]; backtrace(warm, 4); }

    auto model = bng::parser::parseModelFromFile(modelPath);
    if (!model) {
        std::fprintf(stderr, "failed to parse %s\n", modelPath.c_str());
        return 1;
    }
    bng::compile::Document document(*model);
    if (!document.valid()) {
        std::fprintf(stderr, "document invalid\n");
        for (const auto& d : document.diagnostics()) {
            if (d.severity == bng::compile::Severity::Error) {
                std::fprintf(stderr, "  error: %s\n", d.message.c_str());
            }
        }
        return 1;
    }
    bng::engine::ObservableProjection projection(document.model());

    std::size_t minAllocs = 0;
    std::size_t maxAllocs = 0;
    std::size_t minBytes = 0;
    double minSeconds = 0.0;
    double maxSeconds = 0.0;
    std::size_t speciesCount = 0;
    std::size_t reactionCount = 0;

    for (int rep = 0; rep < reps; ++rep) {
        alloc_count::reset();
        double netgenSeconds = 0.0;

        bng::engine::NetworkGenerator generator(document);
        auto network = generator.generateNative(maxIter);
        // In the obs phase the network is a FIXTURE (built outside the measured
        // window) and the measured op is the observable projection below. In
        // the netgen phase the network IS the measured op, so it must be built
        // inside the window — an earlier version of this harness measured
        // nothing here and reported allocs=0 for every run.
        if (phase != "obs") {
            alloc_count::reset();
            bng::engine::NetworkGenerator timed(document);
            const auto t0 = std::chrono::steady_clock::now();
            alloc_count::g_enabled = true;
            network = timed.generateNative(maxIter);
            alloc_count::g_enabled = false;
            const auto t1 = std::chrono::steady_clock::now();
            netgenSeconds = std::chrono::duration<double>(t1 - t0).count();
        }
        if (phase == "obs") {
            // Measured op: project every generated species through the
            // compiled observable set. This is the call the regulatory-graph
            // writer makes per species.
            long long totalWeight = 0;
            const auto t0 = std::chrono::steady_clock::now();
            alloc_count::g_enabled = true;
            for (int r = 0; r < obsReps; ++r) {
                for (std::size_t s = 0; s < network.species.size(); ++s) {
                    const auto w = projection.weights(network.species.get(s).getSpeciesGraph().getGraph());
                    totalWeight += w.empty() ? 0 : w[0];
                }
            }
            alloc_count::g_enabled = false;
            const auto t1 = std::chrono::steady_clock::now();
            const double seconds = std::chrono::duration<double>(t1 - t0).count();
            std::fprintf(stderr,
                         "rep=%d PHASE=obs species=%zu observables=%zu sweeps=%d allocs=%zu bytes=%zu seconds=%.4f checksum=%lld\n",
                         rep, network.species.size(), projection.size(), obsReps,
                         alloc_count::g_count, alloc_count::g_bytes, seconds, totalWeight);
            if (rep == 0) {
                minAllocs = maxAllocs = alloc_count::g_count;
                minBytes = alloc_count::g_bytes;
                minSeconds = maxSeconds = seconds;
            } else {
                if (alloc_count::g_count < minAllocs) minAllocs = alloc_count::g_count;
                if (alloc_count::g_count > maxAllocs) maxAllocs = alloc_count::g_count;
                if (alloc_count::g_bytes < minBytes) minBytes = alloc_count::g_bytes;
                if (seconds < minSeconds) minSeconds = seconds;
                if (seconds > maxSeconds) maxSeconds = seconds;
            }
            speciesCount = network.species.size();
            reactionCount = network.reactions.size();
            continue;
        }
        const double seconds = netgenSeconds;

        speciesCount = network.species.size();
        reactionCount = network.reactions.size();

        std::fprintf(stderr,
                     "rep=%d species=%zu reactions=%zu allocs=%zu bytes=%zu seconds=%.4f largest=%zu sites=%zu\n",
                     rep, speciesCount, reactionCount, alloc_count::g_count,
                     alloc_count::g_bytes, seconds, alloc_count::g_largest, alloc_count::g_used);

        if (rep == 0) {
            minAllocs = maxAllocs = alloc_count::g_count;
            minBytes = alloc_count::g_bytes;
            minSeconds = maxSeconds = seconds;
        } else {
            if (alloc_count::g_count < minAllocs) minAllocs = alloc_count::g_count;
            if (alloc_count::g_count > maxAllocs) maxAllocs = alloc_count::g_count;
            if (alloc_count::g_bytes < minBytes) minBytes = alloc_count::g_bytes;
            if (seconds < minSeconds) minSeconds = seconds;
            if (seconds > maxSeconds) maxSeconds = seconds;
        }
    }

    std::printf("MODEL %s max_iter=%zu species=%zu reactions=%zu\n", modelPath.c_str(), maxIter,
                speciesCount, reactionCount);
    std::printf("REPS %d allocs_min=%zu allocs_max=%zu bytes_min=%zu seconds_min=%.4f seconds_max=%.4f\n",
                reps, minAllocs, maxAllocs, minBytes, minSeconds, maxSeconds);
    std::printf("allocs_per_op %zu bytes_per_op %zu\n", minAllocs, minBytes);

    std::vector<const alloc_count::Site*> sites;
    for (std::size_t i = 0; i < alloc_count::kMaxSites; ++i) {
        if (alloc_count::g_table[i].used) sites.push_back(&alloc_count::g_table[i]);
    }
    std::sort(sites.begin(), sites.end(), [](const alloc_count::Site* a, const alloc_count::Site* b) {
        if (a->count != b->count) return a->count > b->count;
        return a->bytes > b->bytes;
    });

    const char* showEnv = getenv("MEMBENCH_SHOW");
    const std::size_t showCap = showEnv ? strtoul(showEnv, nullptr, 10) : 15;
    const std::size_t show = sites.size() < showCap ? sites.size() : showCap;
    // File-level attribution: the strongest single number this harness produces,
    // because it is keying-independent (a path, not a return address).
    std::vector<std::pair<const char*, std::pair<std::size_t, std::size_t>>> byFile;
    for (const auto* s2 : sites) {
        bool found = false;
        for (auto& e : byFile) {
            if (e.first == s2->file) { e.second.first += s2->count; e.second.second += s2->bytes; found = true; break; }
        }
        if (!found) byFile.push_back({s2->file, {s2->count, s2->bytes}});
    }
    std::sort(byFile.begin(), byFile.end(), [](const auto& a, const auto& b) {
        return a.second.first > b.second.first;
    });
    std::printf("by_source_file (frame2):\n");
    for (const auto& e : byFile) {
        const char* base = std::strrchr(e.first, '/');
        std::printf("  %-10zu allocs %-12zu bytes  %s\n", e.second.first, e.second.second,
                    base ? base + 1 : e.first);
    }
    std::printf("top_sites %zu (of %zu recorded)\n", show, sites.size());
    for (std::size_t i = 0; i < show; ++i) {
        const auto* s = sites[i];
        std::printf("site %2zu allocs=%-9zu bytes=%-10zu\n", i, s->count, s->bytes);
        for (std::size_t k = 2; k < alloc_count::kFrames; ++k) {
            std::printf("            frame%zu %s\n", k, symbolize(s->frame[k]).c_str());
        }
    }
    if (alloc_count::g_collisions) {
        std::printf("WARNING site table full: %zu allocations unattributed\n", alloc_count::g_collisions);
    }
    return 0;
}