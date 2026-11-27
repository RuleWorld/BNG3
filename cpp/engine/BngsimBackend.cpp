#include "BngsimBackend.hpp"

#ifdef BNG3_HAS_BNGSIM_ADAPTER

#include <cmath>
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
    const ast::Model& model,
    const GeneratedNetwork& network) {
    OdeResult out;
    const auto nTimes = bngsimResult.n_times();
    out.timePoints.reserve(static_cast<std::size_t>(nTimes));
    const auto& tvec = bngsimResult.time();
    for (int i = 0; i < nTimes; ++i) {
        out.timePoints.push_back(tvec.at(static_cast<std::size_t>(i)));
    }
    const auto totalSpecies = bngsimResult.n_species();
    // Promoted event-assigned parameters are appended as unreported continuous
    // species after network.species. Project trajectory rows back to the
    // model's real network species (0 .. network.species.size() - 1).
    const std::size_t reportedSpecies = std::min(
        network.species.size(),
        static_cast<std::size_t>(std::max(0, totalSpecies)));
    out.concentrations.resize(static_cast<std::size_t>(nTimes));
    const auto& sd = bngsimResult.species_data();
    // BNGsim's species_data is time-major flat: sd[ti * totalSpecies + si].
    for (int ti = 0; ti < nTimes; ++ti) {
        out.concentrations[static_cast<std::size_t>(ti)].resize(reportedSpecies);
        for (std::size_t si = 0; si < reportedSpecies; ++si) {
            if (static_cast<std::size_t>(sd.size()) ==
                static_cast<std::size_t>(nTimes) * static_cast<std::size_t>(totalSpecies)) {
                out.concentrations[static_cast<std::size_t>(ti)][si] =
                    sd[static_cast<std::size_t>(ti) * static_cast<std::size_t>(totalSpecies) + si];
            } else if (static_cast<std::size_t>(sd.size()) == static_cast<std::size_t>(nTimes) &&
                       totalSpecies == 1) {
                out.concentrations[static_cast<std::size_t>(ti)][0] =
                    sd[static_cast<std::size_t>(ti)];
            } else if (!sd.empty()) {
                const std::size_t idx =
                    static_cast<std::size_t>(ti) * static_cast<std::size_t>(totalSpecies) + si;
                out.concentrations[static_cast<std::size_t>(ti)][si] =
                    idx < sd.size() ? sd[idx] : 0.0;
            }
        }
    }
    const auto totalObs = bngsimResult.n_observables();
    // Promoted event-assigned parameters may append helper observables after
    // the model's declared observables; project back to model.getObservables().
    const std::size_t reportedObs = std::min(
        model.getObservables().size(),
        static_cast<std::size_t>(std::max(0, totalObs)));
    if (reportedObs > 0) {
        out.observables.resize(static_cast<std::size_t>(nTimes));
        const auto& od = bngsimResult.observable_data();
        // Flat time-major: od[ti * totalObs + oi]
        for (int ti = 0; ti < nTimes; ++ti) {
            out.observables[static_cast<std::size_t>(ti)].resize(reportedObs);
            for (std::size_t oi = 0; oi < reportedObs; ++oi) {
                if (static_cast<std::size_t>(od.size()) ==
                    static_cast<std::size_t>(nTimes) * static_cast<std::size_t>(totalObs)) {
                    out.observables[static_cast<std::size_t>(ti)][oi] =
                        od[static_cast<std::size_t>(ti) * static_cast<std::size_t>(totalObs) + oi];
                } else if (static_cast<std::size_t>(od.size()) == static_cast<std::size_t>(totalObs)) {
                    out.observables[static_cast<std::size_t>(ti)][oi] = od[oi];
                } else if (!od.empty()) {
                    const std::size_t idx =
                        static_cast<std::size_t>(ti) * static_cast<std::size_t>(totalObs) + oi;
                    out.observables[static_cast<std::size_t>(ti)][oi] =
                        idx < od.size() ? od[idx] : 0.0;
                }
            }
        }
    } else {
        out.observables.clear();
    }
    return out;
}

} // namespace

std::string bngsimPinnedVersion() {
    return "3295c4d31f2e8c75d07372f33ec2e6b578850540";
}

bool bngsimSupportsOde() { return true; }
bool bngsimSupportsSsa() {
    // BNGsim exposes SSA via its C++ API (Gillespie).
    return true;
}
bool bngsimSupportsPsa() {
    // BNGsim v0.18.0 exposes PSA via SsaSimulator::run_psa().
    return true;
}

OdeResult simulateOdeViaBngsim(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const OdeOptions& options) {

    // These options change stopping, solver selection, or diagnostics in the
    // native backend. Do not silently drop them at the BNGsim boundary.
    if (!options.stopIf.empty()) {
        throw std::runtime_error(
            "BNGsim adapter rejected stop_if: native stop expressions are not supported");
    }
    if (options.sparse) {
        throw std::runtime_error(
            "BNGsim adapter rejected sparse: BNG3 GMRES selection is not equivalent to BNGsim KLU selection");
    }
    if (options.checkProductScale > 0.0) {
        throw std::runtime_error(
            "BNGsim adapter rejected check_product_scale: native threshold warnings are not emitted by BNGsim");
    }
    if (options.steadyState) {
        if (network.species.size() == 0) {
            throw std::runtime_error(
                "BNGsim adapter rejected steady_state: empty-state steady-state truncation differs; native stops at the first non-initial output point while BNGsim returns the full algebraic-only grid");
        }
        if (!(options.steadyStateTol > 0.0) ||
            !std::isfinite(options.steadyStateTol)) {
            throw std::runtime_error(
                "BNGsim adapter rejected steady_state_tol: a finite positive tolerance is required to match native semantics");
        }
    }

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
    // Both solvers test ||f(t,y)||_2 / n_species < tolerance after recording
    // each non-initial output row. This mapping is limited to non-empty species
    // vectors and positive finite tolerances, checked above.
    solverOpts.steady_state = options.steadyState;
    solverOpts.steady_state_tol = options.steadyStateTol;

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
        out = convertBngsimResult(bngsimResult, model, network);
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

    if (!options.stopIf.empty()) {
        throw std::runtime_error(
            "BNGsim adapter rejected stop_if: native event stop expressions are not supported");
    }
    if (options.maxSimSteps > 0 || options.maxSimStepsSpecified) {
        throw std::runtime_error(
            "BNGsim adapter rejected max_sim_steps: BNGsim SSA has no reaction-event cap");
    }
    if (options.outputStepInterval > 0 && options.sampleTimes.empty()) {
        throw std::runtime_error(
            "BNGsim adapter rejected output_step_interval: event-indexed output is not represented by TimeSpec");
    }

    auto bngsimModel = buildBngsimNetwork(model, network);
    if (!bngsimModel) {
        throw std::runtime_error("BNGsim backend failed to lower network: null model");
    }

    bngsim::TimeSpec times = toBngsimTimeSpec(options);

    try {
        bngsim::SsaSimulator solver(*bngsimModel);
        bngsim::Result r = solver.run(times, static_cast<uint64_t>(options.seed));
        auto out = convertBngsimResult(r, model, network);
        if (!options.sampleTimes.empty() && out.timePoints.size() != options.sampleTimes.size()) {
            throw std::runtime_error(
                "BNGsim adapter rejected sample_times: BNGsim TimeSpec does not support explicit sample times in this build");
        }
        return out;
    } catch (const std::exception& ex) {
        const std::string msg = ex.what();
        if (msg.find("BNGsim adapter rejected") != std::string::npos) {
            throw;
        }
        throw std::runtime_error(std::string("BNGsim numerical failure (SSA): ") + msg);
    }
}

OdeResult simulatePsaViaBngsim(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const OdeOptions& options,
    double poplevel) {

    if (!std::isfinite(poplevel) || !(poplevel > 1.0)) {
        throw std::runtime_error(
            "BNGsim adapter rejected poplevel: BNGsim PSA requires finite poplevel > 1 (use method='ssa' for exact unscaled SSA)");
    }
    if (!options.stopIf.empty()) {
        throw std::runtime_error(
            "BNGsim adapter rejected stop_if: native event stop expressions are not supported");
    }
    if (options.maxSimSteps > 0 || options.maxSimStepsSpecified) {
        throw std::runtime_error(
            "BNGsim adapter rejected max_sim_steps: BNGsim PSA has no reaction-event cap");
    }
    if (options.outputStepInterval > 0 && options.sampleTimes.empty()) {
        throw std::runtime_error(
            "BNGsim adapter rejected output_step_interval: event-indexed output is not represented by TimeSpec");
    }
    if (options.batchSize > 0) {
        throw std::runtime_error(
            "BNGsim backend does not support batch_size; use backend='native' or 'auto'");
    }

    auto bngsimModel = buildBngsimNetwork(model, network);
    if (!bngsimModel) {
        throw std::runtime_error("BNGsim backend failed to lower network: null model");
    }

    bngsim::TimeSpec times = toBngsimTimeSpec(options);

    try {
        bngsim::SsaSimulator solver(*bngsimModel);
        bngsim::Result r = solver.run_psa(
            times, static_cast<uint64_t>(options.seed), poplevel);
        auto out = convertBngsimResult(r, model, network);
        if (!options.sampleTimes.empty() && out.timePoints.size() != options.sampleTimes.size()) {
            throw std::runtime_error(
                "BNGsim adapter rejected sample_times: BNGsim TimeSpec does not support explicit sample times in this build");
        }
        return out;
    } catch (const std::exception& ex) {
        const std::string msg = ex.what();
        if (msg.find("BNGsim adapter rejected") != std::string::npos) {
            throw;
        }
        throw std::runtime_error(std::string("BNGsim numerical failure (PSA): ") + msg);
    }
}

} // namespace bng::engine

#else // !BNG3_HAS_BNGSIM_ADAPTER
// Non-adapter TU — no BNGsim headers included.
#endif
