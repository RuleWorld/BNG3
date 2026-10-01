// Benchmark + bit-identity driver for the CPU batch-SSA pool
// (bng::engine::CpuBatchSsaSimulator).
//
// The pool is reachable in production only through the Python binding
// `simulate_batch_ssa_cpu`, so there is no CLI entry point to drive it; this
// driver links the same engine library and calls the pool directly.
//
// Two modes:
//   bench  timed repetitions, one CSV row each (trajectories/sec, events/sec)
//   dump   one run, every output array written as raw little-endian bytes, so
//          two binaries can be compared with `cmp` for BIT identity.
//
// Nothing here is used by the shipped binaries; it lives under bench/.

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <future>
#include <iostream>
#include <thread>
#include <sstream>
#include <string>
#include <vector>

#include "BNGAstVisitor.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/BatchSsa.hpp"

using namespace bng::engine;

namespace {

template <typename T>
void dumpArray(std::ofstream& out, const std::vector<T>& v) {
    const std::uint64_t n = v.size();
    out.write(reinterpret_cast<const char*>(&n), sizeof(n));
    if (n != 0) {
        out.write(reinterpret_cast<const char*>(v.data()),
                  static_cast<std::streamsize>(n * sizeof(T)));
    }
}

template <typename T>
void dumpMatrix(std::ofstream& out, const std::vector<std::vector<T>>& m) {
    const std::uint64_t rows = m.size();
    out.write(reinterpret_cast<const char*>(&rows), sizeof(rows));
    for (const auto& r : m) dumpArray(out, r);
}

void dumpMetrics(const std::string& path, const BatchSsaMetrics& m) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
        std::cerr << "cannot open dump file " << path << "\n";
        std::exit(2);
    }
    const std::uint64_t batch = m.batchSize;
    const std::uint64_t events = m.totalEvents;
    out.write(reinterpret_cast<const char*>(&batch), sizeof(batch));
    out.write(reinterpret_cast<const char*>(&events), sizeof(events));
    const std::uint64_t numNames = m.observableNames.size();
    out.write(reinterpret_cast<const char*>(&numNames), sizeof(numNames));
    for (const auto& name : m.observableNames) {
        const std::uint64_t len = name.size();
        out.write(reinterpret_cast<const char*>(&len), sizeof(len));
        out.write(name.data(), static_cast<std::streamsize>(len));
    }
    dumpArray(out, m.timePoints);
    dumpArray(out, m.timePointsDouble);
    dumpArray(out, m.trajectoryEventCounts);
    dumpArray(out, m.finalSpecies);
    dumpArray(out, m.finalObservables);
    dumpMatrix(out, m.observableMeans);
    dumpMatrix(out, m.observableStdDevs);
    dumpMatrix(out, m.meanSpecies);
    dumpMatrix(out, m.stdSpecies);
    dumpMatrix(out, m.meanObservables);
    dumpMatrix(out, m.stdObservables);
}

[[noreturn]] void usage(const char* argv0) {
    std::cerr << "usage: " << argv0
              << " --model M.bngl [--batch N] [--t-end X] [--n-steps K]"
              << " [--seed S] [--threads T] [--reps R] [--mode bench|dump|fanout]"
              << " [--dump FILE]\n";
    std::exit(2);
}

// Cost of the pool's own fan-out, isolated from any simulation: spawn `threads`
// std::async tasks that do nothing, join them, repeat `reps` times. This is the
// fixed per-batch cost that a persistent worker pool would amortise away.
void measureFanOut(unsigned int threads, int reps) {
    std::printf("mode=fanout threads=%u reps=%d\n", threads, reps);
    std::printf("rep,fanout_ms,per_thread_ms\n");
    for (int r = 0; r < reps; ++r) {
        const auto t0 = std::chrono::high_resolution_clock::now();
        std::vector<std::future<void>> futures;
        futures.reserve(threads);
        for (unsigned int t = 0; t < threads; ++t) {
            futures.push_back(std::async(std::launch::async, [] {}));
        }
        for (auto& f : futures) f.get();
        const auto t1 = std::chrono::high_resolution_clock::now();
        const double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
        std::printf("%d,%.4f,%.4f\n", r, ms, ms / threads);
        std::fflush(stdout);
    }
}


} // namespace

int main(int argc, char** argv) {
    std::string modelPath;
    std::size_t batchSize = 1000;
    double tEnd = 10.0;
    int nSteps = 10;
    uint64_t baseSeed = 42;
    unsigned int threads = 0; // 0 = hardware_concurrency
    int reps = 5;
    std::string mode = "bench";
    std::string dumpPath;

    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) usage(argv[0]);
            return argv[++i];
        };
        if (a == "--model") modelPath = next();
        else if (a == "--batch") batchSize = std::stoull(next());
        else if (a == "--t-end") tEnd = std::stod(next());
        else if (a == "--n-steps") nSteps = std::stoi(next());
        else if (a == "--seed") baseSeed = std::stoull(next());
        else if (a == "--threads") threads = static_cast<unsigned int>(std::stoul(next()));
        else if (a == "--reps") reps = std::stoi(next());
        else if (a == "--mode") mode = next();
        else if (a == "--dump") dumpPath = next();
        else usage(argv[0]);
    }
    if (modelPath.empty() && mode != "fanout") usage(argv[0]);

    if (mode == "fanout") {
        if (threads == 0) threads = std::thread::hardware_concurrency();
        measureFanOut(threads, reps);
        return 0;
    }

    auto model = bng::parser::parseModelFromFile(modelPath);
    if (!model) {
        std::cerr << "failed to parse " << modelPath << "\n";
        return 2;
    }
    NetworkGenerator generator(*model);
    GeneratedNetwork network = generator.generateNative();

    BatchSsaOptions opts;
    opts.tStart = 0.0;
    opts.tEnd = tEnd;
    opts.nSteps = nSteps;
    opts.baseSeed = baseSeed;
    opts.batchSize = batchSize;

    CpuBatchSsaSimulator simulator(*model, network);

    if (mode == "dump") {
        BatchSsaMetrics m = (threads == 1)
            ? simulator.simulateSingleWorker(opts)
            : simulator.simulateMultiCore(opts, threads);
        dumpMetrics(dumpPath, m);
        std::cerr << "dumped " << dumpPath << " batch=" << m.batchSize
                  << " events=" << m.totalEvents << "\n";
        return 0;
    }

    std::printf("model=%s batch=%zu t_end=%g n_steps=%d seed=%llu threads=%u reps=%d\n",
                modelPath.c_str(), batchSize, tEnd, nSteps,
                static_cast<unsigned long long>(baseSeed),
                threads ? threads : std::thread::hardware_concurrency(), reps);
    std::printf("rep,prep_ms,sim_ms,total_ms,events,traj_per_s_sim,events_per_s_sim,"
                "traj_per_s_total,events_per_s_total\n");

    for (int r = 0; r < reps; ++r) {
        BatchSsaMetrics m = (threads == 1)
            ? simulator.simulateSingleWorker(opts)
            : simulator.simulateMultiCore(opts, threads);
        std::printf("%d,%.3f,%.3f,%.3f,%llu,%.1f,%.1f,%.1f,%.1f\n",
                    r, m.modelPrepTimeMs, m.simulationTimeMs, m.totalWallTimeMs,
                    static_cast<unsigned long long>(m.totalEvents),
                    m.trajectoriesPerSecSim, m.eventsPerSecSim,
                    m.trajectoriesPerSecTotal, m.eventsPerSecTotal);
        std::fflush(stdout);
    }
    return 0;
}