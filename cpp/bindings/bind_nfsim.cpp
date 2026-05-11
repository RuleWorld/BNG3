#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <map>
#include <memory>

#include "ast/Model.hpp"
#include "io/XmlWriter.hpp"

#include "NFcore/NFcore.hh"
#include "NFutil/NFutil.hh"
#include "NFinput/NFinput.hh"

namespace py = pybind11;
using namespace bng::ast;

void bind_nfsim(py::module_& m) {

    m.def("simulate_nf", [](Model& model, double t_end, int n_steps,
                            int seed, int equilibrate, bool verbose) -> py::dict {

        // Step 1: Serialize model to XML string via BNG's XmlWriter
        std::string xml_content = bng::io::XmlWriter::write(model);

        // Step 2: Write XML to a temp file (NFSim's reader needs a file path)
        std::string tmp_xml = "._nfsim_temp_model.xml";
        {
            std::ofstream out(tmp_xml);
            out << xml_content;
        }

        // Step 3: Seed RNG
        if (seed > 0) {
            NFutil::SEED_RANDOM(seed);
        }

        // Step 4: Initialize NFSim system from XML
        int suggestedTraversalLimit = -1;
        NFcore::System* system = nullptr;

        {
            py::gil_scoped_release release;
            system = NFinput::initializeFromXML(
                tmp_xml,
                false,    // blockSameComplexBinding
                -1,       // globalMoleculeLimit (unlimited)
                verbose,
                suggestedTraversalLimit,
                false,    // evaluateComplexScopedLocalFunctions
                false     // connectivityFlag
            );
        }

        if (!system) {
            std::remove(tmp_xml.c_str());
            throw std::runtime_error("Failed to initialize NFSim system from model XML");
        }

        // Step 5: Run equilibration if requested
        if (equilibrate > 0) {
            py::gil_scoped_release release;
            system->equilibrate(static_cast<double>(equilibrate));
        }

        // Step 6: Run simulation
        {
            py::gil_scoped_release release;
            system->sim(t_end, static_cast<long int>(n_steps), verbose);
        }

        // Step 7: Extract observable names and final counts from obsToOutput
        std::vector<std::string> obs_names;
        std::vector<double> obs_values;

        for (auto* obs : system->getObsToOutput()) {
            if (obs) {
                obs_names.push_back(obs->getName());
                obs_values.push_back(static_cast<double>(obs->getCount()));
            }
        }
        int n_obs = static_cast<int>(obs_names.size());

        // Cleanup
        delete system;
        std::remove(tmp_xml.c_str());

        // Build result dict
        py::dict result;

        py::array_t<double> time_arr(1);
        time_arr.mutable_at(0) = t_end;
        result["time"] = time_arr;

        py::dict obs_dict;
        for (int i = 0; i < n_obs; ++i) {
            py::array_t<double> arr(1);
            arr.mutable_at(0) = obs_values[i];
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
        "Run network-free (NFSim) simulation on a model");
}
