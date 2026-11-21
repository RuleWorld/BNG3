#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include "ast/Model.hpp"
#include "compile/CompiledModel.hpp"
#include "nfnext/from_bng.hpp"

namespace py = pybind11;

namespace {
using StageState = std::shared_ptr<nfnext::BngExecutionState>;
constexpr const char* kStageState = "bionetgen.nfnext.stage";
}

void bind_nfnext(py::module_& m) {
    m.def("simulate_nfnext", [](bng::ast::Model& model,
                                const std::vector<double>& sample_times,
                                std::uint64_t seed,
                                std::uint64_t max_events,
                                std::size_t max_particles,
                                double t_start,
                                const py::object& continuation,
                                bool retain_state,
                                std::uint64_t population_threshold) -> py::dict {
        bng::compile::CompiledModel compiled(model);
        nfnext::BngExecutionRequest req;
        req.sample_times = sample_times;
        req.seed = seed;
        req.start_time = t_start;
        req.retain_state = retain_state;
        req.population_threshold = population_threshold;
        if (!continuation.is_none()) {
            auto* pointer = PyCapsule_GetPointer(continuation.ptr(), kStageState);
            if (!pointer) throw py::error_already_set();
            req.continuation = *static_cast<StageState*>(pointer);
        }
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
        if (result.final_state) {
            auto state = std::make_unique<StageState>(std::move(result.final_state));
            auto capsule = py::capsule(state.get(), kStageState, [](void* pointer) {
                delete static_cast<StageState*>(pointer);
            });
            state.release();
            out["_continuation"] = std::move(capsule);
        }
        return out;
    },
    py::arg("model"),
    py::arg("sample_times"),
    py::arg("seed") = 0,
    py::arg("max_events") = 1000000,
    py::arg("max_particles") = 1000000,
    py::arg("t_start") = 0.0,
    py::arg("continuation") = py::none(),
    py::arg("retain_state") = false,
    py::arg("population_threshold") = 0,
    "Run NFnext simulation directly from CompiledModel.");
}
