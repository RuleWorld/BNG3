#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <fstream>
#include <stdexcept>
#include <string>

#include "ast/Model.hpp"
#include "engine/NetworkGenerator.hpp"
#include "io/ContactMapWriter.hpp"
#include "io/RegulatoryGraphWriter.hpp"
#include "io/RuleInfluenceGraphWriter.hpp"
#include "io/ReactionNetworkGraphWriter.hpp"
#include "io/RulevizPatternWriter.hpp"
#include "io/RulevizOperationWriter.hpp"
#include "io/ProcessGraphWriter.hpp"
#include "io/SbmlMultiWriter.hpp"

namespace py = pybind11;
using namespace bng::ast;
using namespace bng::engine;
using namespace bng::io;

namespace {

std::string writeMaybeToPath(const std::string& content, const py::object& path) {
    if (!path.is_none()) {
        const std::string pathStr = py::str(path);
        std::ofstream out(pathStr);
        if (!out) {
            throw std::runtime_error("Cannot open file: " + pathStr);
        }
        out << content;
    }
    return content;
}

GeneratedNetwork ensureNetwork(Model& model) {
    NetworkGenerator generator(model);
    return generator.generateNative();
}

} // namespace

void bind_viz(py::module_& m) {
    auto viz = m.def_submodule("viz", "Visualization graph writers");

    viz.def(
        "write_contact_map",
        [](Model& model, const py::object& path) {
            auto graph = ContactMapWriter::buildContactMap(model);
            auto content = ContactMapWriter::toGML(graph);
            return writeMaybeToPath(content, path);
        },
        py::arg("model"), py::arg("path") = py::none(),
        "Write a contact map GraphML/GML string and optionally save it to disk");

    viz.def(
        "write_regulatory_graph",
        [](Model& model, const py::object& path) {
            auto network = ensureNetwork(model);
            auto graph = RegulatoryGraphWriter::build(model, network);
            auto content = RegulatoryGraphWriter::toGML(graph);
            return writeMaybeToPath(content, path);
        },
        py::arg("model"), py::arg("path") = py::none(),
        "Write a regulatory graph GraphML/GML string and optionally save it to disk");

    viz.def(
        "write_rule_influence_graph",
        [](Model& model, const py::object& path) {
            auto network = ensureNetwork(model);
            auto graph = RuleInfluenceGraphWriter::build(model, network);
            auto content = RuleInfluenceGraphWriter::toGML(graph);
            return writeMaybeToPath(content, path);
        },
        py::arg("model"), py::arg("path") = py::none(),
        "Write a rule influence graph GraphML/GML string and optionally save it to disk");

    viz.def(
        "write_reaction_network_graph",
        [](Model& model, const py::object& path) {
            auto network = ensureNetwork(model);
            auto graph = ReactionNetworkGraphWriter::build(model, network);
            auto content = ReactionNetworkGraphWriter::toGML(graph);
            return writeMaybeToPath(content, path);
        },
        py::arg("model"), py::arg("path") = py::none(),
        "Write a reaction network graph GraphML/GML string and optionally save it to disk");

    viz.def(
        "write_ruleviz_pattern",
        [](Model& model, const py::object& path) {
            auto graph = RulevizPatternWriter::build(model);
            auto content = RulevizPatternWriter::toGML(graph);
            return writeMaybeToPath(content, path);
        },
        py::arg("model"), py::arg("path") = py::none(),
        "Write a ruleviz pattern graph GraphML/GML string and optionally save it to disk");

    viz.def(
        "write_ruleviz_operation",
        [](Model& model, const py::object& path) {
            auto graph = RulevizOperationWriter::build(model);
            auto content = RulevizOperationWriter::toGML(graph);
            return writeMaybeToPath(content, path);
        },
        py::arg("model"), py::arg("path") = py::none(),
        "Write a ruleviz operation graph GraphML/GML string and optionally save it to disk");

    viz.def(
        "write_process_graph",
        [](Model& model, const py::object& path) {
            auto network = ensureNetwork(model);
            auto graph = ProcessGraphWriter::build(model, network);
            auto content = ProcessGraphWriter::toGML(graph);
            return writeMaybeToPath(content, path);
        },
        py::arg("model"), py::arg("path") = py::none(),
        "Write a process graph GraphML/GML string and optionally save it to disk");

    viz.def(
        "write_sbml_multi",
        [](Model& model, const py::object& path) {
            auto content = SbmlMultiWriter::write(model);
            return writeMaybeToPath(content, path);
        },
        py::arg("model"), py::arg("path") = py::none(),
        "Write an SBML Multi document and optionally save it to disk");
}