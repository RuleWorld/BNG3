#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <string>
#include <stdexcept>
#include <cstring>
#include <vector>

#include "ast/Model.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "engine/PlaSimulator.hpp"
#include "engine/PsaSimulator.hpp"
#include "engine/FiniteBackend.hpp"
#include "engine/BngsimBackend.hpp"
#include "actions/ActionDispatch.hpp"
#include "engine/BatchSsa.hpp"
#include "engine/gpu/GpuSsaBackend.hpp"

namespace py = pybind11;
using namespace bng::engine;
using namespace bng::ast;
using namespace bng::actions;

// TEMPORARY measurement probe (reverted before commit): reports engine vs
// conversion wall split in the returned dict when BNG3_BOUND is set.
namespace {

bool probeOn() { return std::getenv("BNG3_BOUND") != nullptr; }
double msSince(std::chrono::steady_clock::time_point t0) {
    return std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - t0).count();
}
double msBetween(std::chrono::steady_clock::time_point t0,
                 std::chrono::steady_clock::time_point t1) {
    return std::chrono::duration<double, std::milli>(t1 - t0).count();
}

template <typename T>
py::array_t<T> vector_to_array(const std::vector<T>& values) {
    py::array_t<T> array(values.size());
    if (!values.empty()) {
        std::memcpy(array.mutable_data(), values.data(), values.size() * sizeof(T));
    }
    return array;
}
} // namespace

namespace {

bool isResultFunction(const std::string& name) {
    return !name.empty() && name.front() != '_' &&
           name.rfind("__assign_rule__", 0) != 0 &&
           name.rfind("__rate_rule_in_", 0) != 0 &&
           name.rfind("__rate_rule_out_", 0) != 0 &&
           name.rfind("__rate_rule__", 0) != 0 &&
           name.rfind("__rate_rule_pos__", 0) != 0 &&
           name.rfind("__rate_rule_neg__", 0) != 0;
}

py::dict result_to_dict(const OdeResult& result, const Model& model) {
    py::dict d;

    // Time array
    py::array_t<double> time_arr(result.timePoints.size());
    auto time_buf = time_arr.mutable_unchecked<1>();
    for (size_t i = 0; i < result.timePoints.size(); ++i) {
        time_buf(i) = result.timePoints[i];
    }
    d["time"] = time_arr;

    // Concentrations: (n_steps × n_species)
    if (!result.concentrations.empty()) {
        size_t n_steps = result.concentrations.size();
        size_t n_species = result.concentrations[0].size();
        py::array_t<double> conc({n_steps, n_species});
        auto conc_buf = conc.mutable_unchecked<2>();
        for (size_t i = 0; i < n_steps; ++i) {
            for (size_t j = 0; j < n_species; ++j) {
                conc_buf(i, j) = result.concentrations[i][j];
            }
        }
        d["concentrations"] = conc;
    }

    // Observables: dict of name → numpy array
    if (!result.observables.empty()) {
        py::dict obs_dict;
        const auto& obs_defs = model.getObservables();
        size_t n_steps = result.observables.size();
        size_t n_obs = result.observables.empty() ? 0 : result.observables[0].size();

        for (size_t j = 0; j < n_obs && j < obs_defs.size(); ++j) {
            py::array_t<double> obs_arr(n_steps);
            auto obs_buf = obs_arr.mutable_unchecked<1>();
            for (size_t i = 0; i < n_steps; ++i) {
                obs_buf(i) = result.observables[i][j];
            }
            obs_dict[py::cast(obs_defs[j].getName())] = obs_arr;
        }
        d["observables"] = obs_dict;
    }

    // Zero-argument BNGL functions are algebraic model outputs as well as
    // rate-law helpers.  Expose them separately so an SBML assignment rule
    // lowered from a species can still be compared on the same time grid.
    if (!result.functions.empty()) {
        py::dict function_dict;
        std::size_t function_index = 0;
        for (const auto& function : model.getFunctions()) {
            if (function.getArgs().empty() && isResultFunction(function.getName())) {
                if (function_index >= result.functions.front().size()) break;
                py::array_t<double> function_arr(result.functions.size());
                auto function_buf = function_arr.mutable_unchecked<1>();
                for (std::size_t i = 0; i < result.functions.size(); ++i) {
                    if (function_index < result.functions[i].size()) {
                        function_buf(i) = result.functions[i][function_index];
                    } else {
                        function_buf(i) = 0.0;
                    }
                }
                function_dict[py::cast(function.getName())] = function_arr;
                ++function_index;
            }
        }
        if (function_dict.size() > 0) {
            d["functions"] = function_dict;
        }
    }

    // Batch SSA fields (populated only when opts.batchSize > 0)
    d["batch_size"] = result.batchSize;
    if (result.batchSize > 0 && !result.batchObsStdDevs.empty()) {
        py::dict std_dict;
        const auto& obs_defs = model.getObservables();
        size_t n_steps = result.batchObsStdDevs.size();
        size_t n_obs   = result.batchObsStdDevs.empty() ? 0 : result.batchObsStdDevs[0].size();
        for (size_t j = 0; j < n_obs && j < obs_defs.size(); ++j) {
            py::array_t<double> sd_arr(n_steps);
            auto sd_buf = sd_arr.mutable_unchecked<1>();
            for (size_t i = 0; i < n_steps; ++i)
                sd_buf(i) = result.batchObsStdDevs[i][j];
            std_dict[py::cast(obs_defs[j].getName())] = sd_arr;
        }
        d["batch_std_devs"] = std_dict;
    }

    return d;
}
py::dict metrics_to_dict(const BatchSsaMetrics& m) {
    py::dict d;
    d["batch_size"] = m.batchSize;
    d["total_events"] = m.totalEvents;
    d["model_prep_time_ms"] = m.modelPrepTimeMs;
    d["h2d_transfer_ms"] = m.hostToDeviceTransferMs;
    d["sim_time_ms"] = m.simulationTimeMs;
    d["d2h_transfer_ms"] = m.deviceToHostTransferMs;
    d["total_wall_time_ms"] = m.totalWallTimeMs;
    d["trajectories_per_sec_sim"] = m.trajectoriesPerSecSim;
    d["trajectories_per_sec_total"] = m.trajectoriesPerSecTotal;
    d["events_per_sec_sim"] = m.eventsPerSecSim;
    d["events_per_sec_total"] = m.eventsPerSecTotal;
    d["memory_usage_bytes"] = m.memoryUsageBytes;

    py::array_t<float> times(m.timePoints.size());
    auto tb = times.mutable_unchecked<1>();
    for (size_t i = 0; i < m.timePoints.size(); ++i) tb(i) = m.timePoints[i];
    d["time"] = times;

    py::dict obs_means;
    py::dict obs_stds;
    for (size_t g = 0; g < m.observableNames.size(); ++g) {
        py::array_t<float> m_arr(m.timePoints.size());
        py::array_t<float> s_arr(m.timePoints.size());
        auto mb = m_arr.mutable_unchecked<1>();
        auto sb = s_arr.mutable_unchecked<1>();
        for (size_t step = 0; step < m.timePoints.size(); ++step) {
            mb(step) = m.observableMeans[step][g];
            sb(step) = m.observableStdDevs[step][g];
        }
        obs_means[py::cast(m.observableNames[g])] = m_arr;
        obs_stds[py::cast(m.observableNames[g])] = s_arr;
    }
    d["observable_means"] = obs_means;
    d["observable_stds"] = obs_stds;

    if (!m.finalObservables.empty() && !m.observableNames.empty()) {
        size_t B = m.batchSize;
        size_t G = m.observableNames.size();
        py::array_t<float> f_obs({B, G});
        auto fb = f_obs.mutable_unchecked<2>();
        for (size_t b = 0; b < B; ++b) {
            for (size_t g = 0; g < G; ++g) {
                fb(b, g) = m.finalObservables[b * G + g];
            }
        }
        d["final_observables"] = f_obs;
        py::list names;
        for (const auto& name : m.observableNames) names.append(name);
        d["observable_names"] = names;
    }

    if (!m.finalSpecies.empty() && m.batchSize > 0) {
        size_t B = m.batchSize;
        size_t S = m.finalSpecies.size() / B;
        py::array_t<int32_t> f_spec({B, S});
        auto sb = f_spec.mutable_unchecked<2>();
        for (size_t b = 0; b < B; ++b) {
            for (size_t s = 0; s < S; ++s) {
                sb(b, s) = m.finalSpecies[b * S + s];
            }
        }
        d["final_species"] = f_spec;
    }

    py::array_t<uint32_t> ev_counts(m.trajectoryEventCounts.size());
    auto eb = ev_counts.mutable_unchecked<1>();
    for (size_t i = 0; i < m.trajectoryEventCounts.size(); ++i) eb(i) = m.trajectoryEventCounts[i];
    d["event_counts"] = ev_counts;

    return d;
}

} // namespace

void bind_engine(py::module_& m) {

    py::class_<GeneratedNetwork>(m, "GeneratedNetwork")
        .def_property_readonly("num_species", [](const GeneratedNetwork& gn) {
            return gn.species.size();
        })
        .def_property_readonly("num_reactions", [](const GeneratedNetwork& gn) {
            return gn.reactions.size();
        })
        .def_property_readonly("species_names", [](const GeneratedNetwork& gn) {
            std::vector<std::string> names;
            for (const auto& sp : gn.species.all()) {
                names.push_back(sp.getSpeciesGraph().toString());
            }
            return names;
        })
        .def_property_readonly("reaction_strings", [](const GeneratedNetwork& gn) {
            std::vector<std::string> strs;
            for (const auto& rxn : gn.reactions.all()) {
                strs.push_back(rxn.getLabel());
            }
            return strs;
        })
        .def("__repr__", [](const GeneratedNetwork& gn) {
            return "<GeneratedNetwork species=" + std::to_string(gn.species.size()) +
                   " reactions=" + std::to_string(gn.reactions.size()) + ">";
        });

    py::class_<OdeOptions>(m, "OdeOptions")
        .def(py::init<>())
        .def_readwrite("t_start", &OdeOptions::tStart)
        .def_readwrite("t_end", &OdeOptions::tEnd)
        .def_readwrite("n_steps", &OdeOptions::nSteps)
        .def_readwrite("rtol", &OdeOptions::rtol)
        .def_readwrite("atol", &OdeOptions::atol)
        .def_readwrite("method", &OdeOptions::method)
        .def_readwrite("max_step", &OdeOptions::maxStep)
        .def_readwrite("steady_state", &OdeOptions::steadyState)
        .def_readwrite("steady_state_tol", &OdeOptions::steadyStateTol)
        .def_readwrite("stop_if", &OdeOptions::stopIf)
        .def_readwrite("sample_times", &OdeOptions::sampleTimes)
        .def_readwrite("max_sim_steps", &OdeOptions::maxSimSteps)
        .def_readwrite("output_step_interval", &OdeOptions::outputStepInterval)
        .def_readwrite("sparse", &OdeOptions::sparse)
        .def_readwrite("check_product_scale", &OdeOptions::checkProductScale)
        .def_readwrite("enforce_nonnegative", &OdeOptions::enforceNonnegative)
        .def_readwrite("batch_size", &OdeOptions::batchSize,
            "Number of independent SSA trajectories to run in batch mode (0 = single trajectory)")
        .def_readwrite("batch_gpu_preferred", &OdeOptions::batchGpuPreferred,
            "Try GPU first when running batch SSA; silently fall back to CPU thread pool on failure");

    m.def("generate_network", [](Model& model, size_t max_iter) {
        py::gil_scoped_release release;
        NetworkGenerator gen(model);
        return gen.generateNative(max_iter);
    }, py::arg("model"), py::arg("max_iter") = 100,
       "Generate the reaction network from a model");

    m.def("jax_ode_flatten", [](Model& model, GeneratedNetwork& network) {
        std::vector<double> initialState;
        std::vector<uint8_t> fixedSpecies;
        std::vector<double> rateConstants;
        std::vector<uint8_t> totalRates;
        std::vector<uint8_t> functionalRates;
        std::vector<uint8_t> timeDependentRates;
        std::vector<std::size_t> reactantOffsets{0};
        std::vector<std::size_t> reactantSpecies;
        std::vector<std::size_t> productOffsets{0};
        std::vector<std::size_t> productSpecies;

        {
            py::gil_scoped_release release;
            OdeIntegrator integrator(model, network);
            const auto& compiledReactions = integrator.getCompiledReactions();
            const auto& fixed = integrator.getFixedSpecies();
            initialState.reserve(network.species.size());
            fixedSpecies.reserve(network.species.size());
            for (std::size_t i = 0; i < network.species.size(); ++i) {
                initialState.push_back(network.species.get(i).getAmount());
                fixedSpecies.push_back(fixed[i] ? 1 : 0);
            }

            rateConstants.reserve(compiledReactions.size());
            totalRates.reserve(compiledReactions.size());
            functionalRates.reserve(compiledReactions.size());
            timeDependentRates.reserve(compiledReactions.size());
            for (const auto& reaction : compiledReactions) {
                rateConstants.push_back(reaction.rateConstant);
                totalRates.push_back(reaction.isTotalRate ? 1 : 0);
                functionalRates.push_back(reaction.isFunctional ? 1 : 0);
                timeDependentRates.push_back(reaction.isTimeDependent ? 1 : 0);
                reactantSpecies.insert(
                    reactantSpecies.end(), reaction.reactantIndices.begin(),
                    reaction.reactantIndices.end());
                reactantOffsets.push_back(reactantSpecies.size());
                productSpecies.insert(
                    productSpecies.end(), reaction.productIndices.begin(),
                    reaction.productIndices.end());
                productOffsets.push_back(productSpecies.size());
            }
        }

        py::dict result;
        result["num_species"] = network.species.size();
        result["initial_state"] = vector_to_array(initialState);
        result["fixed_species"] = vector_to_array(fixedSpecies);
        result["rate_constants"] = vector_to_array(rateConstants);
        result["total_rate"] = vector_to_array(totalRates);
        result["functional_rates"] = vector_to_array(functionalRates);
        result["time_dependent_rates"] = vector_to_array(timeDependentRates);
        result["reactant_offsets"] = vector_to_array(reactantOffsets);
        result["reactant_species"] = vector_to_array(reactantSpecies);
        result["product_offsets"] = vector_to_array(productOffsets);
        result["product_species"] = vector_to_array(productSpecies);
        return result;
    }, py::arg("model"), py::arg("network"),
       "Export the native compiled ODE reaction data used by the optional JAX ODE backend");

    // Private validation hook: parity tests need the engine's instantaneous
    // derivative at arbitrary documented states, without inferring it from a
    // short integration step. Keep this out of the supported Python API.
    m.def("_validation_ode_rhs", [](Model& model,
                                    GeneratedNetwork& network,
                                    double time,
                                    const std::vector<double>& state) {
        if (state.size() != network.species.size()) {
            throw std::invalid_argument(
                "RHS state length must match generated network species count");
        }
        std::vector<double> derivative(state.size(), 0.0);
        py::gil_scoped_release release;
        OdeIntegrator integrator(model, network);
        integrator.derivs(time, state.data(), derivative.data());
        return derivative;
    }, py::arg("model"), py::arg("network"), py::arg("time"), py::arg("state"),
       "Internal parity-validation hook for instantaneous ODE derivatives");

    // Private validation hook: return the engine's compiled per-reaction
    // coefficients before mass-action species factors are applied.
    m.def("_validation_ode_rate_coefficients", [](Model& model,
                                                  GeneratedNetwork& network,
                                                  double time,
                                                  const std::vector<double>& state) {
        if (state.size() != network.species.size()) {
            throw std::invalid_argument(
                "rate state length must match generated network species count");
        }
        py::gil_scoped_release release;
        OdeIntegrator integrator(model, network);
        return integrator.evaluateRateCoefficients(time, state.data());
    }, py::arg("model"), py::arg("network"), py::arg("time"), py::arg("state"),
       "Internal parity-validation hook for compiled per-reaction rate coefficients");

    m.def("simulate_ode", [](Model& model, GeneratedNetwork& network,
                             double t_end, int n_steps, double t_start,
                             double rtol, double atol, const std::string& method,
                             double max_step, bool steady_state,
                             double steady_state_tol, const std::string& stop_if,
                             const std::vector<double>& sample_times,
                             std::size_t max_sim_steps,
                             std::size_t output_step_interval, bool sparse,
                             double check_product_scale) {
        if (max_sim_steps > 0 || output_step_interval > 0) {
            throw std::runtime_error(
                "max_sim_steps and output_step_interval are supported only "
                "for simulate_ssa");
        }
        py::gil_scoped_release release;

        auto t_entry = std::chrono::steady_clock::now();

        OdeOptions opts;
        opts.tStart = t_start;
        opts.tEnd = t_end;
        opts.nSteps = n_steps;
        opts.rtol = rtol;
        opts.atol = atol;
        opts.method = method;
        opts.maxStep = max_step;
        opts.steadyState = steady_state;
        opts.steadyStateTol = steady_state_tol;
        opts.stopIf = stop_if;
        opts.sampleTimes = sample_times;
        opts.maxSimSteps = max_sim_steps;
        opts.outputStepInterval = output_step_interval;
        opts.sparse = sparse;
        opts.checkProductScale = check_product_scale;
        auto t_opts = std::chrono::steady_clock::now();

        OdeIntegrator integrator(model, network);
        auto t_ctor = std::chrono::steady_clock::now();
        const bool probe = probeOn();
        OdeResult result = integrator.integrate(opts);
        auto t_eng = std::chrono::steady_clock::now();

        py::gil_scoped_acquire acquire;
        auto tp1 = std::chrono::steady_clock::now();
        py::dict d = result_to_dict(result, model);
        if (probe) {
            d["_engine_ms"] = msBetween(t_ctor, t_eng); // integrate only
            d["_opts_ms"] = msBetween(t_entry, t_opts);
            d["_ctor_ms"] = msBetween(t_opts, t_ctor);
            d["_conv_ms"] = msBetween(tp1, std::chrono::steady_clock::now());
        }
        return d;
    },
        py::arg("model"),
        py::arg("network"),
        py::arg("t_end") = 100.0,
        py::arg("n_steps") = 100,
        py::arg("t_start") = 0.0,
        py::arg("rtol") = 1e-8,
        py::arg("atol") = 1e-12,
        py::arg("method") = "cvode",
        py::arg("max_step") = 0.0,
        py::arg("steady_state") = false,
        py::arg("steady_state_tol") = 1e-8,
        py::arg("stop_if") = "",
        py::arg("sample_times") = std::vector<double>{},
        py::arg("max_sim_steps") = 0,
        py::arg("output_step_interval") = 0,
        py::arg("sparse") = false,
        py::arg("check_product_scale") = 0.0,
        "Run ODE simulation on a generated network");

    m.def("simulate_ssa", [](Model& model, GeneratedNetwork& network,
                             double t_end, int n_steps, double t_start, int seed,
                             const std::string& stop_if,
                             const std::vector<double>& sample_times,
                             std::size_t max_sim_steps,
                             std::size_t output_step_interval,
                             std::size_t batch_size,
                             bool batch_gpu_preferred,
                             const std::string& batch_gpu_backend) {
        py::gil_scoped_release release;

        OdeOptions opts;
        opts.tStart = t_start;
        opts.tEnd = t_end;
        opts.nSteps = n_steps;
        opts.method = "ssa";
        opts.seed = seed;
        opts.stopIf = stop_if;
        opts.sampleTimes = sample_times;
        opts.maxSimSteps = max_sim_steps;
        opts.outputStepInterval = output_step_interval;
        opts.batchSize = batch_size;
        opts.batchGpuPreferred = batch_gpu_preferred;
        opts.batchGpuBackend = batch_gpu_backend;

        OdeIntegrator integrator(model, network);
        OdeResult result = integrator.integrate(opts);

        py::gil_scoped_acquire acquire;
        return result_to_dict(result, model);
    },
        py::arg("model"),
        py::arg("network"),
        py::arg("t_end") = 100.0,
        py::arg("n_steps") = 100,
        py::arg("t_start") = 0.0,
        py::arg("seed") = 0,
        py::arg("stop_if") = "",
        py::arg("sample_times") = std::vector<double>{},
        py::arg("max_sim_steps") = 0,
        py::arg("output_step_interval") = 0,
        py::arg("batch_size") = static_cast<std::size_t>(0),
        py::arg("batch_gpu_preferred") = true,
        py::arg("batch_gpu_backend") = std::string("auto"),
        "Run SSA simulation on a generated network. "
        "Set batch_size > 1 to run many independent trajectories and return mean + std-dev trajectories; "
        "uses a GPU backend (CUDA or Metal) when one is available and beneficial, "
        "otherwise the CPU thread pool. batch_gpu_backend selects 'auto', 'cuda', "
        "'metal', or 'none'.");

    m.def("simulate_pla", [](Model& model, GeneratedNetwork& network,
                             double t_end, int n_steps, const std::string& config_str,
                             double t_start) {
        py::gil_scoped_release release;

        OdeOptions opts;
        opts.tStart = t_start;
        opts.tEnd = t_end;
        opts.nSteps = n_steps;

        PlaConfig config;
        if (!config_str.empty()) {
            config = PlaConfig::parse(config_str);
        }

        PlaSimulator simulator(model, network);
        OdeResult result = simulator.simulate(opts, config);

        py::gil_scoped_acquire acquire;
        return result_to_dict(result, model);
    },
        py::arg("model"),
        py::arg("network"),
        py::arg("t_end") = 100.0,
        py::arg("n_steps") = 100,
        py::arg("config_str") = "",
        py::arg("t_start") = 0.0,
        "Run PLA simulation on a generated network");

    m.def("simulate_psa", [](Model& model, GeneratedNetwork& network,
                             double t_end, int n_steps, double poplevel,
                             double t_start) {
        py::gil_scoped_release release;

        OdeOptions opts;
        opts.tStart = t_start;
        opts.tEnd = t_end;
        opts.nSteps = n_steps;

        PsaSimulator simulator(model, network);
        OdeResult result = simulator.simulate(opts, poplevel);

        py::gil_scoped_acquire acquire;
        return result_to_dict(result, model);
    },
        py::arg("model"),
        py::arg("network"),
        py::arg("t_end") = 100.0,
        py::arg("n_steps") = 100,
        py::arg("poplevel") = 100,
        py::arg("t_start") = 0.0,
        "Run PSA simulation on a generated network");

    // --- Finite backend dispatch (BNGsim canonical backend) ---
    m.def("bngsim_available", []() { return isBngsimAvailable(); },
          "Whether the BNGsim finite backend is available in this build");
    m.def("bngsim_version", []() { return bngsimVersion(); },
          "Pinned BNGsim version/revision or 'unavailable'");
    m.def("bngsim_capabilities", []() {
        py::dict d;
        auto caps = getBngsimCapabilities();
        d["available"] = caps.available;
        d["version"] = caps.version;
        d["supports_ode"] = caps.supportsOde;
        d["supports_ssa"] = caps.supportsSsa;
        d["supports_psa"] = caps.supportsPsa;
        d["supports_pla"] = caps.supportsPla;
        return d;
    }, "BNGsim capability object for the current build");
    m.def("check_bngsim_lowering", [](Model& model, GeneratedNetwork& network) {
        py::dict d;
        auto check = checkBngsimLowering(model, network);
        d["supported"] = check.supported;
        d["blockers"] = check.blockers;
        return d;
    }, py::arg("model"), py::arg("network"),
       "Whether this generated network can be faithfully lowered to BNGsim");
    m.def("simulate_ode_bngsim", [](Model& model, GeneratedNetwork& network,
                                     double t_end, int n_steps, double t_start,
                                     double rtol, double atol, const std::string& method,
                                     double max_step, bool steady_state,
                                     double steady_state_tol, const std::string& stop_if,
                                     const std::vector<double>& sample_times,
                                     std::size_t max_sim_steps,
                                     std::size_t output_step_interval, bool sparse,
                                     double check_product_scale) {
        OdeOptions opts;
        opts.tStart = t_start;
        opts.tEnd = t_end;
        opts.nSteps = n_steps;
        opts.rtol = rtol;
        opts.atol = atol;
        opts.method = method;
        opts.maxStep = max_step;
        opts.steadyState = steady_state;
        opts.steadyStateTol = steady_state_tol;
        opts.stopIf = stop_if;
        opts.sampleTimes = sample_times;
        opts.maxSimSteps = max_sim_steps;
        opts.outputStepInterval = output_step_interval;
        opts.sparse = sparse;
        opts.checkProductScale = check_product_scale;
        py::gil_scoped_release release;
        OdeResult result = simulateFiniteOde(model, network, opts, FiniteBackend::Bngsim);
        py::gil_scoped_acquire acquire;
        py::dict d = result_to_dict(result, model);
        d["backend"] = py::cast(std::string("bngsim"));
        return d;
    }, py::arg("model"), py::arg("network"),
       py::arg("t_end") = 100.0, py::arg("n_steps") = 100,
       py::arg("t_start") = 0.0, py::arg("rtol") = 1e-8, py::arg("atol") = 1e-12,
       py::arg("method") = "cvode", py::arg("max_step") = 0.0,
       py::arg("steady_state") = false, py::arg("steady_state_tol") = 1e-8,
       py::arg("stop_if") = "", py::arg("sample_times") = std::vector<double>{},
       py::arg("max_sim_steps") = 0, py::arg("output_step_interval") = 0,
       py::arg("sparse") = false, py::arg("check_product_scale") = 0.0,
       "Run ODE via the BNGsim backend (fails closed if model not lowerable)");
    m.def("simulate_ssa_bngsim", [](Model& model, GeneratedNetwork& network,
                                     double t_end, int n_steps, double t_start, int seed,
                                     const std::string& stop_if,
                                     const std::vector<double>& sample_times,
                                     std::size_t max_sim_steps,
                                     std::size_t output_step_interval) {
        OdeOptions opts;
        opts.tStart = t_start;
        opts.tEnd = t_end;
        opts.nSteps = n_steps;
        opts.method = "ssa";
        opts.seed = seed;
        opts.stopIf = stop_if;
        opts.sampleTimes = sample_times;
        opts.maxSimSteps = max_sim_steps;
        opts.outputStepInterval = output_step_interval;
        py::gil_scoped_release release;
        OdeResult result = simulateFiniteSsa(model, network, opts, FiniteBackend::Bngsim);
        py::gil_scoped_acquire acquire;
        py::dict d = result_to_dict(result, model);
        d["backend"] = py::cast(std::string("bngsim"));
        return d;
    }, py::arg("model"), py::arg("network"),
       py::arg("t_end") = 100.0, py::arg("n_steps") = 100,
       py::arg("t_start") = 0.0, py::arg("seed") = 0,
       py::arg("stop_if") = "", py::arg("sample_times") = std::vector<double>{},
       py::arg("max_sim_steps") = 0, py::arg("output_step_interval") = 0,
       "Run SSA via the BNGsim backend (fails closed if not lowerable or not wired)");

    m.def("gpu_backends", []() {
        py::list out;
        for (const auto& status : gpuBackendInventory()) {
            py::dict entry;
            entry["name"] = status.name;
            entry["compiled"] = status.compiled;
            entry["available"] = status.available;
            entry["detail"] = status.detail;
            out.append(entry);
        }
        return out;
    }, "Report every batched-SSA GPU backend: whether it was compiled in and whether a usable device is present");

    m.def("default_gpu_backend", []() {
        return std::string(gpuBackendName(defaultGpuBackend()));
    }, "Name of the batched-SSA GPU backend that would be used by default ('none' when there is none)");

    m.def("simulate_batch_ssa_cpu", [](Model& model, GeneratedNetwork& network,
                                       std::size_t batch_size, double t_end, int n_steps,
                                       double t_start, uint64_t base_seed, unsigned int threads,
                                       std::size_t max_sim_steps) {
        py::gil_scoped_release release;

        BatchSsaOptions opts;
        opts.tStart = t_start;
        opts.tEnd = t_end;
        opts.nSteps = n_steps;
        opts.baseSeed = base_seed;
        opts.batchSize = batch_size;
        opts.maxSimSteps = max_sim_steps;

        CpuBatchSsaSimulator simulator(model, network);
        const bool probe = probeOn();
        auto tp0 = std::chrono::steady_clock::now();
        BatchSsaMetrics metrics = (threads == 1)
            ? simulator.simulateSingleWorker(opts)
            : simulator.simulateMultiCore(opts, threads);
        const double engine_ms = probe ? msSince(tp0) : 0.0;

        py::gil_scoped_acquire acquire;
        auto tp1 = std::chrono::steady_clock::now();
        py::dict d = metrics_to_dict(metrics);
        if (probe) {
            d["_engine_ms"] = engine_ms;
            d["_conv_ms"] = msSince(tp1);
        }
        return d;
    },
        py::arg("model"),
        py::arg("network"),
        py::arg("batch_size") = 1000,
        py::arg("t_end") = 10.0,
        py::arg("n_steps") = 10,
        py::arg("t_start") = 0.0,
        py::arg("base_seed") = 42,
        py::arg("threads") = 1,
        py::arg("max_sim_steps") = 0,
        "Run batched SSA simulation on CPU (single-worker or multi-core)");

    m.def("simulate_batch_ssa_gpu", [](Model& model, GeneratedNetwork& network,
                                       std::size_t batch_size, double t_end, int n_steps,
                                       double t_start, uint64_t base_seed,
                                       std::size_t max_sim_steps,
                                       const std::string& backend) {
        py::gil_scoped_release release;

        // Flatten and validate (fails closed on unsupported rate laws)
        FlattenedReactionNetwork flatNet = FlattenedReactionNetwork::fromModelAndNetwork(model, network);

        BatchSsaOptions opts;
        opts.tStart = t_start;
        opts.tEnd = t_end;
        opts.nSteps = n_steps;
        opts.baseSeed = base_seed;
        opts.batchSize = batch_size;
        opts.maxSimSteps = max_sim_steps;

        auto gpu = makeGpuSsaBackend(gpuBackendFromName(backend), flatNet);
        if (!gpu) {
            throw std::runtime_error(
                "No batched-SSA GPU backend selected (backend='" + backend + "')");
        }
        BatchSsaMetrics metrics = gpu->simulate(flatNet, opts);

        py::gil_scoped_acquire acquire;
        py::dict out = metrics_to_dict(metrics);
        out["backend"] = std::string(gpu->name());
        return out;
    },
        py::arg("model"),
        py::arg("network"),
        py::arg("batch_size") = 1000,
        py::arg("t_end") = 10.0,
        py::arg("n_steps") = 10,
        py::arg("t_start") = 0.0,
        py::arg("base_seed") = 42,
        py::arg("max_sim_steps") = 0,
        py::arg("backend") = std::string("auto"),
        "Run batched SSA on a GPU backend (auto/cuda/metal). Raises when the selected "
        "backend is unavailable; use simulate_batch_ssa_cpu for the CPU pool");
    m.def("execute", [](Model& model, const std::string& source_path, bool verbose) {
        py::gil_scoped_release release;
        ActionDispatch::execute(model, source_path, verbose);
    }, py::arg("model"), py::arg("source_path"), py::arg("verbose") = false,
       "Execute all actions defined in the model");
}
