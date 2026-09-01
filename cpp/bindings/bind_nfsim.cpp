#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <cstdio>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <map>
#include <memory>
#include <random>

#include "ast/Model.hpp"
#include "io/XmlWriter.hpp"

#include "NFcore/NFcore.hh"
#include "NFinput/NFinput.hh"
#include "NFinput/NFinput_fromAst.hh"

namespace py = pybind11;
namespace fs = std::filesystem;
using namespace bng::ast;

namespace {

struct TempFileGuard {
    std::string path;
    ~TempFileGuard() { if (!path.empty()) std::remove(path.c_str()); }
};

std::string make_temp_xml_path() {
    auto tmp_dir = fs::temp_directory_path();
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dist(100000, 999999);
    return (tmp_dir / ("nfsim_" + std::to_string(dist(gen)) + ".xml")).string();
}

} // anonymous namespace

void bind_nfsim(py::module_& m) {

        m.def("simulate_nf", [](Model& model, double t_end, int n_steps,
                            int seed, double equilibrate, bool verbose,
                            const std::string& source_path,
                            const std::vector<double>& sample_times,
                            int traversal_limit) -> py::dict {
        if (t_end < 0.0) {
            throw std::invalid_argument("t_end must be non-negative");
        }
        if (n_steps < 0 || (n_steps == 0 && sample_times.empty())) {
            throw std::invalid_argument(
                "n_steps must be positive unless sample_times is set");
        }
        if (!std::isfinite(equilibrate) || equilibrate < 0.0) {
            throw std::invalid_argument(
                "equilibrate must be finite and non-negative");
        }
        if (traversal_limit < -1) {
            throw std::invalid_argument(
                "traversal_limit must be -1 (automatic) or non-negative");
        }

        std::vector<double> output_times = sample_times;
        if (!output_times.empty()) {
            for (std::size_t index = 0; index < output_times.size(); ++index) {
                const double time = output_times[index];
                if (!std::isfinite(time) || time < 0.0 || time > t_end ||
                    (index > 0 && time <= output_times[index - 1])) {
                    throw std::invalid_argument(
                        "sample_times must be finite, strictly increasing, "
                        "and within [0, t_end]");
                }
            }
            if (output_times.back() < t_end) {
                output_times.push_back(t_end);
            }
        }

        // The direct adapter is deliberately fail-closed.  XML compatibility
        // construction is available only when the caller explicitly opts in;
        // unsupported direct semantics must not silently change execution
        // paths.
        TempFileGuard tmp_guard;
        int suggestedTraversalLimit = -1;
        std::unique_ptr<NFcore::System> system;
        std::string construction_path = "direct";

        {
            py::gil_scoped_release release;
            system.reset(NFinput::buildSystemFromAst(
                model,
                false,    // blockSameComplexBinding
                -1,       // globalMoleculeLimit (unlimited)
                verbose,
                suggestedTraversalLimit,
                fs::path(source_path)
            ));

            if (!system) {
                if (std::getenv("BNG_NFSIM_REQUIRE_DIRECT") != nullptr) {
                    throw std::runtime_error(
                        "NFsim direct AST initialization required but unavailable");
                }
                if (std::getenv("BNG_NFSIM_ALLOW_XML_FALLBACK") == nullptr) {
                    throw std::runtime_error(
                        "NFsim direct AST initialization unavailable; XML fallback disabled "
                        "(set BNG_NFSIM_ALLOW_XML_FALLBACK=1 to opt in)");
                }
                construction_path = "in-memory-xml";
                if (verbose) {
                    std::cerr << "[bind_nfsim] Direct AST initialization unavailable; "
                                 "using compatibility XML path...\n";
                }
                // initializeFromModel is the old in-memory XML path and does
                // not touch the filesystem.  Keep it as the first fallback so
                // migration builds remain usable without granting the direct
                // adapter any unproven semantics.
                system.reset(NFinput::initializeFromModel(
                    &model,
                    false,    // blockSameComplexBinding
                    -1,       // globalMoleculeLimit (unlimited)
                    verbose,
                    suggestedTraversalLimit
                ));
            }

            if (!system) {
                construction_path = "on-disk-xml";
                // Preserve the historical on-disk initializer as a last-resort
                // compatibility mode.  This branch is expected to be rare and
                // is intentionally visible in verbose diagnostics.
                if (verbose) {
                    std::cerr << "[bind_nfsim] In-memory XML initialization failed; "
                                 "using on-disk XML fallback...\n";
                }
                const std::string xml_content = bng::io::XmlWriter::write(model);
                tmp_guard.path = make_temp_xml_path();
                {
                    std::ofstream out(tmp_guard.path);
                    if (!out) {
                        throw std::runtime_error("Failed to create temp file for NFSim XML");
                    }
                    out << xml_content;
                    if (!out) {
                        throw std::runtime_error("Failed to write temp file for NFSim XML");
                    }
                }
                system.reset(NFinput::initializeFromXML(
                    tmp_guard.path,
                    false,    // blockSameComplexBinding
                    -1,       // globalMoleculeLimit (unlimited)
                    verbose,
                    suggestedTraversalLimit,
                    false,    // evaluateComplexScopedLocalFunctions
                    false     // connectivityFlag
                ));
            }
        }

        if (!system) {
            throw std::runtime_error("Failed to initialize NFSim system from model XML");
        }

        // NFsim's XML entry point applies the parser's recommended traversal
        // depth before preparing reactions.  The direct path must do the same
        // or large complexes silently fall back to an unrestricted graph walk.
        // A caller-supplied non-negative value retains the native -utl escape
        // hatch; -1 uses the recommendation computed while building the system.
        const int effectiveTraversalLimit =
            traversal_limit >= 0 ? traversal_limit : suggestedTraversalLimit;
        system->setUniversalTraversalLimit(effectiveTraversalLimit);
        if (verbose) {
            std::cerr << "[bind_nfsim] Universal traversal limit = "
                      << effectiveTraversalLimit << "\n";
        }

        // Step 5: Seed per-instance RNG (after system creation, before prepareForSimulation)
        if (seed > 0) {
            system->seedRNG(static_cast<unsigned long>(seed));
        }

        // Step 6: Prepare the system before any equilibration or simulation.
        {
            py::gil_scoped_release release;
            system->prepareForSimulation();
        }

        // Step 6: Run equilibration if requested
        if (equilibrate > 0) {
            py::gil_scoped_release release;
            system->equilibrate(equilibrate);
        }

        // Step 7: Collect observable names
        std::vector<std::string> obs_names;
        for (auto* obs : system->getObsToOutput()) {
            if (obs) obs_names.push_back(obs->getName());
        }
        int n_obs = static_cast<int>(obs_names.size());

        // Step 8: Run simulation in steps, collecting time-series data.
        // NFsim's System supports arbitrary stopping times through stepTo;
        // use that path when the caller requests explicit sample times.
        std::vector<double> time_points;
        std::vector<std::vector<double>> obs_series(n_obs);

        const auto record_observables = [&]() {
            int idx = 0;
            for (auto* obs : system->getObsToOutput()) {
                if (obs) {
                    obs_series[idx].push_back(static_cast<double>(obs->getCount()));
                    idx++;
                }
            }
        };

        {
            py::gil_scoped_release release;
            if (output_times.empty()) {
                const double dt = t_end / static_cast<double>(n_steps);
                double t_current = 0.0;
                time_points.push_back(0.0);
                record_observables();
                for (int step = 1; step <= n_steps; ++step) {
                    // Match NFsim::sim's repeated checkpoint accumulation.
                    // Multiplication can round a final boundary differently
                    // and change whether an event is included at that edge.
                    t_current += dt;
                    system->stepTo(t_current);
                    time_points.push_back(t_current);
                    record_observables();
                }
            } else {
                time_points.reserve(output_times.size());
                for (const double time : output_times) {
                    system->stepTo(time);
                    time_points.push_back(time);
                    record_observables();
                }
            }
        }

        // Step 9: Build result dict matching ODE/SSA format
        int total_points = static_cast<int>(time_points.size());
        py::dict result;

        py::array_t<double> time_arr(total_points);
        auto time_buf = time_arr.mutable_unchecked<1>();
        for (int i = 0; i < total_points; ++i) time_buf(i) = time_points[i];
        result["time"] = time_arr;

        py::dict obs_dict;
        for (int i = 0; i < n_obs; ++i) {
            py::array_t<double> arr(total_points);
            auto buf = arr.mutable_unchecked<1>();
            for (int j = 0; j < total_points; ++j) buf(j) = obs_series[i][j];
            obs_dict[py::cast(obs_names[i])] = arr;
        }
        result["observables"] = obs_dict;
        result["construction_path"] = construction_path;

        return result;
    },
        py::arg("model"),
        py::arg("t_end") = 100.0,
        py::arg("n_steps") = 100,
        py::arg("seed") = 0,
        py::arg("equilibrate") = 0,
        py::arg("verbose") = false,
        py::arg("source_path") = "",
        py::arg("sample_times") = std::vector<double>{},
        py::arg("traversal_limit") = -1,
        "Run network-free (NFSim) simulation on a model.\n\n"
        "Returns a dict with 'time' (numpy array of time points) and\n"
        "'observables' (dict of name -> numpy array of values at each time point).");
}
