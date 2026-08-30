#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <string>
#include <stdexcept>
#include <vector>

#include "ast/Model.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "engine/PlaSimulator.hpp"
#include "engine/PsaSimulator.hpp"
#include "actions/ActionDispatch.hpp"

namespace py = pybind11;
using namespace bng::engine;
using namespace bng::ast;
using namespace bng::actions;

namespace {

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
        .def_readwrite("check_product_scale", &OdeOptions::checkProductScale);

    m.def("generate_network", [](Model& model, size_t max_iter) {
        py::gil_scoped_release release;
        NetworkGenerator gen(model);
        return gen.generateNative(max_iter);
    }, py::arg("model"), py::arg("max_iter") = 100,
       "Generate the reaction network from a model");

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
        py::arg("rtol") = 1e-8,
        py::arg("atol") = 1e-8,
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
                             std::size_t output_step_interval) {
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
        "Run SSA simulation on a generated network");

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

    m.def("execute", [](Model& model, const std::string& source_path, bool verbose) {
        py::gil_scoped_release release;
        ActionDispatch::execute(model, source_path, verbose);
    }, py::arg("model"), py::arg("source_path"), py::arg("verbose") = false,
       "Execute all actions defined in the model");
}
