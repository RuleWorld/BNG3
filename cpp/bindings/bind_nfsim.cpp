#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <cstdio>
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
#include "NFutil/NFutil.hh"
#include "NFinput/NFinput.hh"

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
                            int seed, int equilibrate, bool verbose) -> py::dict {
        if (t_end < 0.0) {
            throw std::invalid_argument("t_end must be non-negative");
        }
        if (n_steps <= 0) {
            throw std::invalid_argument("n_steps must be positive");
        }

        // Step 1: Serialize model to XML string
        std::string xml_content = bng::io::XmlWriter::write(model);

        // Step 2: Write XML to a temp file with RAII cleanup
        TempFileGuard tmp_guard;
        tmp_guard.path = make_temp_xml_path();
        {
            std::ofstream out(tmp_guard.path);
            if (!out) throw std::runtime_error("Failed to create temp file for NFSim XML");
            out << xml_content;
        }

        // Step 3: Seed RNG
        if (seed > 0) {
            NFutil::SEED_RANDOM(seed);
        }

        // Step 4: Initialize NFSim system from XML with RAII
        int suggestedTraversalLimit = -1;
        std::unique_ptr<NFcore::System> system;

        {
            py::gil_scoped_release release;
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

        if (!system) {
            throw std::runtime_error("Failed to initialize NFSim system from model XML");
        }

        // Step 5: Prepare the system before any equilibration or simulation.
        {
            py::gil_scoped_release release;
            system->prepareForSimulation();
        }

        // Step 6: Run equilibration if requested
        if (equilibrate > 0) {
            py::gil_scoped_release release;
            system->equilibrate(static_cast<double>(equilibrate));
        }

        // Step 7: Collect observable names
        std::vector<std::string> obs_names;
        for (auto* obs : system->getObsToOutput()) {
            if (obs) obs_names.push_back(obs->getName());
        }
        int n_obs = static_cast<int>(obs_names.size());

        // Step 8: Run simulation in steps, collecting time-series data
        double dt = t_end / static_cast<double>(n_steps);
        std::vector<double> time_points;
        std::vector<std::vector<double>> obs_series(n_obs);

        // Record initial state
        time_points.push_back(0.0);
        {
            int idx = 0;
            for (auto* obs : system->getObsToOutput()) {
                if (obs) {
                    obs_series[idx].push_back(static_cast<double>(obs->getCount()));
                    idx++;
                }
            }
        }

        // Simulate in chunks to get time-series
        {
            py::gil_scoped_release release;
            for (int step = 1; step <= n_steps; ++step) {
                double t_current = step * dt;
                system->stepTo(t_current);

                time_points.push_back(t_current);
                int idx = 0;
                for (auto* obs : system->getObsToOutput()) {
                    if (obs) {
                        obs_series[idx].push_back(static_cast<double>(obs->getCount()));
                        idx++;
                    }
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

        return result;
    },
        py::arg("model"),
        py::arg("t_end") = 100.0,
        py::arg("n_steps") = 100,
        py::arg("seed") = 0,
        py::arg("equilibrate") = 0,
        py::arg("verbose") = false,
        "Run network-free (NFSim) simulation on a model.\n\n"
        "Returns a dict with 'time' (numpy array of time points) and\n"
        "'observables' (dict of name -> numpy array of values at each time point).");
}
