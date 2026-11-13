#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include "ast/Model.hpp"
#include "compile/CompiledModel.hpp"
#include "nfnext/from_bng.hpp"

namespace py = pybind11;

void bind_nfnext(py::module_& m) {
    m.def("simulate_nfnext", [](bng::ast::Model& model,
                                const std::vector<double>& sample_times,
                                std::uint64_t seed,
                                std::uint64_t max_events,
                                std::size_t max_particles) -> py::dict {
        bng::compile::CompiledModel compiled(model);
        nfnext::BngExecutionRequest req;
        req.sample_times = sample_times;
        req.seed = seed;
        if (max_events > 0) req.max_events = max_events;
        if (max_particles > 0) req.max_particles = max_particles;

        nfnext::BngExecutionResult result;
        {
            py::gil_scoped_release release;
            result = nfnext::executeFromBioNetGen(compiled, req);
        }

        py::dict out;
        py::array_t<double> time_arr(static_cast<py::ssize_t>(result.rows.size()));
        auto time_buf = time_arr.mutable_unchecked<1>();
        for (std::size_t i = 0; i < result.rows.size(); ++i) {
            time_buf(static_cast<py::ssize_t>(i)) = result.rows[i][0];
        }
        out["time"] = time_arr;

        py::dict obs_dict;
        for (std::size_t col = 1; col < result.columns.size(); ++col) {
            py::array_t<double> arr(static_cast<py::ssize_t>(result.rows.size()));
            auto buf = arr.mutable_unchecked<1>();
            for (std::size_t i = 0; i < result.rows.size(); ++i) {
                buf(static_cast<py::ssize_t>(i)) = result.rows[i][col];
            }
            obs_dict[py::cast(result.columns[col])] = arr;
        }
        out["observables"] = obs_dict;
        out["event_count"] = result.event_count;
        out["engine"] = "nfnext";
        return out;
    },
    py::arg("model"),
    py::arg("sample_times"),
    py::arg("seed") = 0,
    py::arg("max_events") = 1000000,
    py::arg("max_particles") = 1000000,
    "Run NFnext simulation directly from CompiledModel.");
}
