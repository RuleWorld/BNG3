#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <pybind11/pybind11.h>

#include "ast/Expression.hpp"
#include "ast/Model.hpp"
#include "ast/MoleculeType.hpp"
#include "ast/Parameter.hpp"
#include "ast/ReactionRule.hpp"
#include "ast/SeedSpecies.hpp"
#include "ast/SpeciesGraph.hpp"
#include "core/BNGcore.hpp"

namespace py = pybind11;
using namespace bng::ast;

namespace {

std::size_t indexFromBngir(const py::handle& value, const std::string& where) {
    if (PyBool_Check(value.ptr()) || !PyLong_Check(value.ptr())) {
        throw std::runtime_error(
            "native BNGIR " + where + " must be a non-boolean integer index");
    }

    const auto raw = PyLong_AsUnsignedLongLong(value.ptr());
    if (PyErr_Occurred()) {
        PyErr_Clear();
        throw std::runtime_error("native BNGIR " + where + " is out of range");
    }
    if (raw > std::numeric_limits<std::size_t>::max()) {
        throw std::runtime_error("native BNGIR " + where + " is out of range");
    }
    return static_cast<std::size_t>(raw);
}

void requireDenseOrderedIds(const py::list& entries, const std::string& section) {
    for (std::size_t index = 0; index < entries.size(); ++index) {
        const auto entry = py::cast<py::dict>(entries[index]);
        const auto id = indexFromBngir(entry["id"], section + " id");
        if (id != index) {
            throw std::runtime_error(
                "native BNGIR " + section + " ids must be dense and ordered");
        }
    }
}

void rejectUnsupportedModelSections(const py::dict& document) {
    static const std::vector<std::string> sections = {
        "compartments", "observables", "functions", "energy_patterns",
        "barrier_patterns", "population_maps", "population_types",
    };
    for (const auto& section : sections) {
        const py::str key(section);
        if (!document.contains(key)) continue;
        const auto entries = py::cast<py::list>(document[key]);
        if (!entries.empty()) {
            throw std::runtime_error(
                "native BNGIR model." + section + " is not supported");
        }
    }
}

Expression expressionFromBngir(const py::dict& value,
                               const std::vector<std::string>& parameterNames) {
    const auto kind = py::cast<std::string>(value["kind"]);
    if (kind == "number") {
        return Expression::number(py::cast<double>(value["value"]));
    }
    if (kind == "parameter_ref") {
        const auto symbol = py::cast<py::dict>(value["symbol"]);
        const auto index = indexFromBngir(symbol["index"], "parameter reference");
        if (index >= parameterNames.size()) {
            throw std::runtime_error("native BNGIR parameter reference is out of range");
        }
        return Expression::identifier(parameterNames[index]);
    }

    const auto arguments = py::cast<py::list>(value["arguments"]);
    if (kind == "unary") {
        const auto op = py::cast<std::string>(value["operator"]);
        if (op == "plus") return Expression::unary("+", expressionFromBngir(arguments[0], parameterNames));
        if (op == "negate") return Expression::unary("-", expressionFromBngir(arguments[0], parameterNames));
        throw std::runtime_error("unsupported native BNGIR unary operator");
    }
    if (kind == "binary") {
        const auto op = py::cast<std::string>(value["operator"]);
        static const std::map<std::string, std::string> operators = {
            {"add", "+"}, {"subtract", "-"}, {"multiply", "*"},
            {"divide", "/"}, {"power", "^"},
        };
        const auto found = operators.find(op);
        if (found == operators.end()) {
            throw std::runtime_error("unsupported native BNGIR binary operator");
        }
        return Expression::binary(
            found->second,
            expressionFromBngir(arguments[0], parameterNames),
            expressionFromBngir(arguments[1], parameterNames));
    }
    throw std::runtime_error("unsupported native BNGIR expression kind: " + kind);
}

BNGcore::PatternGraph patternFromBngir(Model& model, const py::dict& pattern) {
    BNGcore::PatternGraph graph;
    const auto molecules = py::cast<py::list>(pattern["molecules"]);
    for (const auto& rawMolecule : molecules) {
        const auto molecule = py::cast<py::dict>(rawMolecule);
        const auto typeId =
            indexFromBngir(molecule["type_id"], "molecule type reference");
        if (typeId >= model.getMoleculeTypes().size()) {
            throw std::runtime_error("native BNGIR molecule type reference is out of range");
        }
        const auto& moleculeType = model.getMoleculeTypes()[typeId];
        const auto& nodeType = model.getGraphTypeRegistry().ensureMoleculeType(moleculeType);
        BNGcore::Node node(nodeType);
        graph.add_node(node);
    }
    return graph;
}

std::unique_ptr<Model> modelFromBngirV02(const py::dict& document) {
    rejectUnsupportedModelSections(document);
    const auto parameters = py::cast<py::list>(document["parameters"]);
    const auto moleculeTypes = py::cast<py::list>(document["molecule_types"]);
    const auto seeds = py::cast<py::list>(document["seeds"]);
    const auto rules = py::cast<py::list>(document["rules"]);
    requireDenseOrderedIds(parameters, "parameter");
    requireDenseOrderedIds(moleculeTypes, "molecule type");
    requireDenseOrderedIds(seeds, "seed");
    requireDenseOrderedIds(rules, "rule");

    auto model = std::make_unique<Model>();
    const auto metadata = py::cast<py::dict>(document["metadata"]);
    model->setVersion(py::cast<std::string>(metadata["version"]));
    model->setSubstanceUnits(py::cast<std::string>(metadata["substance_units"]));
    model->setModelName(py::cast<std::string>(metadata["name"]));
    const auto options = py::cast<py::dict>(metadata["options"]);
    for (const auto& entry : options) {
        model->setOption(py::cast<std::string>(entry.first),
                         py::cast<std::string>(entry.second));
    }

    std::vector<std::string> parameterNames;
    parameterNames.reserve(parameters.size());
    for (const auto& rawParameter : parameters) {
        const auto parameter = py::cast<py::dict>(rawParameter);
        parameterNames.push_back(py::cast<std::string>(parameter["name"]));
    }
    for (const auto& rawParameter : parameters) {
        const auto parameter = py::cast<py::dict>(rawParameter);
        model->addParameter(Parameter(
            py::cast<std::string>(parameter["name"]),
            expressionFromBngir(py::cast<py::dict>(parameter["expression"]), parameterNames)));
    }

    for (const auto& rawMoleculeType : moleculeTypes) {
        const auto moleculeType = py::cast<py::dict>(rawMoleculeType);
        model->addMoleculeType(MoleculeType(
            py::cast<std::string>(moleculeType["name"]), {}, false));
    }

    for (const auto& rawSeed : seeds) {
        const auto seed = py::cast<py::dict>(rawSeed);
        auto graph = patternFromBngir(*model, py::cast<py::dict>(seed["pattern"]));
        auto amount = expressionFromBngir(
            py::cast<py::dict>(seed["amount"]), parameterNames);
        model->addSeedSpecies(SeedSpecies(
            {}, std::move(amount), py::cast<bool>(seed["constant"]), {}, std::move(graph)));
    }

    for (const auto& rawRule : rules) {
        const auto rule = py::cast<py::dict>(rawRule);
        const auto direction = py::cast<py::dict>(rule["forward"]);
        const auto reactants = py::cast<py::list>(direction["reactants"]);
        const auto products = py::cast<py::list>(direction["products"]);
        std::vector<SpeciesGraph> reactantGraphs;
        std::vector<SpeciesGraph> productGraphs;
        reactantGraphs.emplace_back(patternFromBngir(*model, py::cast<py::dict>(reactants[0])));
        productGraphs.emplace_back(patternFromBngir(*model, py::cast<py::dict>(products[0])));
        const auto rate = py::cast<py::dict>(direction["rate"]);
        std::vector<Expression> rates;
        rates.push_back(expressionFromBngir(
            py::cast<py::dict>(rate["expression"]), parameterNames));
        model->addReactionRule(ReactionRule::fromResolvedPatterns(
            py::cast<std::string>(rule["name"]),
            py::cast<std::string>(rule["label"]),
            std::move(rates),
            std::move(reactantGraphs), std::move(productGraphs)));
    }
    return model;
}

} // namespace

void bind_bngir(py::module_& module) {
    module.def("_model_from_bngir_v02", &modelFromBngirV02,
               py::arg("model"),
               "Build the supported BNGIR v0.2 subset directly from native structures.");
}
