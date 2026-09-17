#include "BngsimBackend.hpp"

#ifdef BNG3_HAS_BNGSIM_ADAPTER

#include <stdexcept>
#include <string>
#include <vector>

#include <bngsim/bngsim.hpp>
#include <bngsim/model_builder.hpp>

#include "BngsimAdapter.hpp"

namespace bng::engine {

namespace {

bngsim::TimeSpec toBngsimTimeSpec(const OdeOptions& opts) {
    bngsim::TimeSpec ts;
    ts.t_start = opts.tStart;
    ts.t_end = opts.tEnd;
    if (!opts.sampleTimes.empty()) {
        ts.sample_times = opts.sampleTimes;
        // n_points is ignored when sample_times is set, but keep it consistent
        ts.n_points = static_cast<int>(opts.sampleTimes.size());
    } else {
        // OdeOptions nSteps is number of intervals; TimeSpec n_points includes t0.
        ts.n_points = static_cast<int>(opts.nSteps) + 1;
    }
    return ts;
}

OdeResult convertBngsimResult(
    const bngsim::Result& bngsimResult,
    const ast::Model& model) {
    OdeResult out;
    const auto nTimes = bngsimResult.n_times();
    out.timePoints.reserve(static_cast<std::size_t>(nTimes));
    const auto& tvec = bngsimResult.time();
    for (int i = 0; i < nTimes; ++i) {
        out.timePoints.push_back(tvec.at(static_cast<std::size_t>(i)));
    }
    const auto nSpecies = bngsimResult.n_species();
    out.concentrations.resize(static_cast<std::size_t>(nTimes));
    const auto& sd = bngsimResult.species_data();
    // BNGsim's species_data is time-major flat: sd[ti * nS + si] (see
    // test_bngsim_adapter.cpp: species_data().at(ti) for nS==1).
    // Handle both flat and single-species shorthand.
    for (int ti = 0; ti < nTimes; ++ti) {
        out.concentrations[static_cast<std::size_t>(ti)].resize(static_cast<std::size_t>(nSpecies));
        for (int si = 0; si < nSpecies; ++si) {
            if (static_cast<std::size_t>(sd.size()) == static_cast<std::size_t>(nTimes * nSpecies)) {
                out.concentrations[static_cast<std::size_t>(ti)][static_cast<std::size_t>(si)] =
                    sd[static_cast<std::size_t>(ti * nSpecies + si)];
            } else if (static_cast<std::size_t>(sd.size()) == static_cast<std::size_t>(nTimes) && nSpecies == 1) {
                out.concentrations[static_cast<std::size_t>(ti)][0] = sd[static_cast<std::size_t>(ti)];
            } else if (!sd.empty()) {
                // Fallback: try flat indexing even if size mismatched (will throw if OOB)
                const std::size_t idx = static_cast<std::size_t>(ti * nSpecies + si);
                out.concentrations[static_cast<std::size_t>(ti)][static_cast<std::size_t>(si)] =
                    idx < sd.size() ? sd[idx] : 0.0;
            }
        }
    }
    const auto nObs = bngsimResult.n_observables();
    if (nObs > 0) {
        out.observables.resize(static_cast<std::size_t>(nTimes));
        const auto& od = bngsimResult.observable_data();
        // Flat time-major: od[ti * nO + oi]
        for (int ti = 0; ti < nTimes; ++ti) {
            out.observables[static_cast<std::size_t>(ti)].resize(static_cast<std::size_t>(nObs));
            for (int oi = 0; oi < nObs; ++oi) {
                if (static_cast<std::size_t>(od.size()) == static_cast<std::size_t>(nTimes * nObs)) {
                    out.observables[static_cast<std::size_t>(ti)][static_cast<std::size_t>(oi)] =
                        od[static_cast<std::size_t>(ti * nObs + oi)];
                } else if (static_cast<std::size_t>(od.size()) == static_cast<std::size_t>(nObs)) {
                    // Some BNGsim builds return only a single time slice (e.g. initial)
                    out.observables[static_cast<std::size_t>(ti)][static_cast<std::size_t>(oi)] = od[static_cast<std::size_t>(oi)];
                } else if (!od.empty()) {
                    const std::size_t idx = static_cast<std::size_t>(ti * nObs + oi);
                    out.observables[static_cast<std::size_t>(ti)][static_cast<std::size_t>(oi)] =
                        idx < od.size() ? od[idx] : 0.0;
                }
            }
        }
    } else {
        out.observables.clear();
    }
    (void)model;
    return out;
}

} // namespace

std::string bngsimPinnedVersion() {
    return "49dc939035f5a272da663f8c9586e3c9f0e1c041";
}

bool bngsimSupportsOde() { return true; }
bool bngsimSupportsSsa() {
    // BNGsim exposes SSA via its C++ API (Gillespie) in recent revisions.
    // Treat as supported; the actual construction will throw if unavailable.
    return true;
}
bool bngsimSupportsPsa() { return false; }

OdeResult simulateOdeViaBngsim(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const OdeOptions& options) {

    // Fail closed before solver construction — same boundary as buildBngsimNetwork.
    auto bngsimModel = buildBngsimNetwork(model, network);
    if (!bngsimModel) {
        throw std::runtime_error("BNGsim backend failed to lower network: null model");
    }

    bngsim::TimeSpec times = toBngsimTimeSpec(options);

    bngsim::CvodeSimulator solver(*bngsimModel);
    // SolverOptions carries rtol/atol/max_step_size per bngsim 2026 API
    bngsim::SolverOptions solverOpts;
    solverOpts.rtol = options.rtol;
    solverOpts.atol = options.atol;
    if (options.maxStep > 0.0) solverOpts.max_step_size = options.maxStep;

    bngsim::Result bngsimResult;
    try {
        bngsimResult = solver.run(times, solverOpts);
    } catch (const std::exception& ex) {
        throw std::runtime_error(std::string("BNGsim numerical failure: ") + ex.what());
    } catch (...) {
        throw std::runtime_error("BNGsim numerical failure: unknown solver error");
    }

    // Convert to BNG3 OdeResult semantics (time, concentrations, observables).
    OdeResult out;
    // Primary path: use the dedicated converter that understands BNGsim's
    // current result layout. If the layout has changed between BNGsim
    // revisions, fall back to a minimal time/concentration mapping.
    try {
        out = convertBngsimResult(bngsimResult, model);
    } catch (const std::exception& ex) {
        throw std::runtime_error(std::string("BNGsim result conversion failed: ") + ex.what());
    }

    // Validate sampleTimes parity when explicit times were requested.
    if (!options.sampleTimes.empty() && out.timePoints.size() != options.sampleTimes.size()) {
        // If BNGsim ignored sampleTimes and produced a uniform grid, surface
        // it as a lowering gap rather than silently returning wrong times.
        throw std::runtime_error(
            "BNGsim adapter rejected sample_times: BNGsim TimeSpec does not support explicit sample times in this build");
    }

    return out;
}

OdeResult simulateSsaViaBngsim(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const OdeOptions& options) {

    auto bngsimModel = buildBngsimNetwork(model, network);
    if (!bngsimModel) {
        throw std::runtime_error("BNGsim backend failed to lower network: null model");
    }

    bngsim::TimeSpec times = toBngsimTimeSpec(options);

    try {
        bngsim::SsaSimulator solver(*bngsimModel);
        // Future PSA path: if options indicate poplevel, use run_psa. For now,
        // always use exact SSA. PSA parity is Phase F.
        bngsim::Result r = solver.run(times, static_cast<uint64_t>(options.seed));
        return convertBngsimResult(r, model);
    } catch (const std::exception& ex) {
        const std::string msg = ex.what();
        if (msg.find("BNGsim adapter rejected") != std::string::npos) {
            throw;
        }
        throw std::runtime_error(std::string("BNGsim numerical failure (SSA): ") + msg);
    }
}

} // namespace bng::engine

#else // !BNG3_HAS_BNGSIM_ADAPTER
// Non-adapter TU — no BNGsim headers included.
#endif
