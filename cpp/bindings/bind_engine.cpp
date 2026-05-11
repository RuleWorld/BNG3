#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <string>
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
        .def_readwrite("steady_state_tol", &OdeOptions::steadyStateTol);

    m.def("generate_network", [](Model& model, size_t max_iter) {
        py::gil_scoped_release release;
        NetworkGenerator gen(model);
        return gen.generateNative(max_iter);
    }, py::arg("model"), py::arg("max_iter") = 100,
       "Generate the reaction network from a model");

    m.def("simulate_ode", [](Model& model, GeneratedNetwork& network,
                             double t_end, int n_steps, double t_start,
                             double rtol, double atol, const std::string& method) {
        py::gil_scoped_release release;

        OdeOptions opts;
        opts.tStart = t_start;
        opts.tEnd = t_end;
        opts.nSteps = n_steps;
        opts.rtol = rtol;
        opts.atol = atol;
        opts.method = method;

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
        "Run ODE simulation on a generated network");

    m.def("simulate_ssa", [](Model& model, GeneratedNetwork& network,
                             double t_end, int n_steps, double t_start, int seed) {
        py::gil_scoped_release release;

        OdeOptions opts;
        opts.tStart = t_start;
        opts.tEnd = t_end;
        opts.nSteps = n_steps;
        opts.method = "ssa";
        opts.seed = seed;

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
        "Run SSA simulation on a generated network");

    m.def("simulate_pla", [](Model& model, GeneratedNetwork& network,
                             double t_end, int n_steps, const std::string& config_str) {
        py::gil_scoped_release release;

        OdeOptions opts;
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
        "Run PLA simulation on a generated network");

    m.def("simulate_psa", [](Model& model, GeneratedNetwork& network,
                             double t_end, int n_steps, double poplevel) {
        py::gil_scoped_release release;

        OdeOptions opts;
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
        "Run PSA simulation on a generated network");

    m.def("execute", [](Model& model, const std::string& source_path, bool verbose) {
        py::gil_scoped_release release;
        ActionDispatch::execute(model, source_path, verbose);
    }, py::arg("model"), py::arg("source_path"), py::arg("verbose") = false,
       "Execute all actions defined in the model");
}
