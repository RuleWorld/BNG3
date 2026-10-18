#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <set>
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

double finiteNumberFromBngir(const py::handle& value, const std::string& where) {
    if (PyBool_Check(value.ptr())) {
        throw std::runtime_error(
            "native BNGIR " + where + " must be numeric, not boolean");
    }
    if (!PyLong_Check(value.ptr()) && !PyFloat_Check(value.ptr())) {
        throw std::runtime_error("native BNGIR " + where + " must be numeric");
    }

    const auto number = PyFloat_AsDouble(value.ptr());
    if (PyErr_Occurred()) {
        PyErr_Clear();
        throw std::runtime_error("native BNGIR " + where + " must be finite");
    }
    if (!std::isfinite(number)) {
        throw std::runtime_error("native BNGIR " + where + " must be finite");
    }
    return number;
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

void requireObjectKeys(const py::dict& object,
                       const std::vector<std::string>& required,
                       const std::vector<std::string>& allowed,
                       const std::string& where) {
    for (const auto& key : required) {
        if (!object.contains(py::str(key))) {
            throw std::runtime_error("native BNGIR " + where + " is missing " + key);
        }
    }
    for (const auto& entry : object) {
        if (!py::isinstance<py::str>(entry.first)) {
            throw std::runtime_error("native BNGIR " + where + " has a non-string key");
        }
        const auto key = py::cast<std::string>(entry.first);
        if (std::find(allowed.begin(), allowed.end(), key) == allowed.end()) {
            throw std::runtime_error(
                "native BNGIR " + where + " has unsupported " + key);
        }
    }
}

void requireParameterKeys(const py::dict& parameter) {
    static const std::vector<std::string> required = {"id", "name", "expression"};
    static const std::vector<std::string> allowed = {
        "id", "name", "expression", "constant_value",
    };
    requireObjectKeys(parameter, required, allowed, "parameter");
    const py::str constantValueKey("constant_value");
    if (parameter.contains(constantValueKey)) {
        finiteNumberFromBngir(parameter[constantValueKey], "parameter constant_value");
    }
}

void requireParameterReferenceSymbol(const py::dict& symbol) {
    static const std::vector<std::string> keys = {"kind", "index"};
    requireObjectKeys(symbol, keys, keys, "parameter reference symbol");
    if (!py::isinstance<py::str>(symbol["kind"]) ||
        py::cast<std::string>(symbol["kind"]) != "parameter") {
        throw std::runtime_error(
            "native BNGIR parameter reference symbol kind must be parameter");
    }
}

void requireExpressionProperties(const py::dict& expression,
                                 const std::vector<std::string>& allowed) {
    requireObjectKeys(expression, {}, allowed, "expression");
}

void rejectUnsupportedModelSections(const py::dict& document) {
    static const std::vector<std::string> sections = {
        "observables", "functions", "energy_patterns",
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
        requireExpressionProperties(value, {"kind", "value"});
        return Expression::number(
            finiteNumberFromBngir(value["value"], "expression value"));
    }
    if (kind == "parameter_ref") {
        requireExpressionProperties(value, {"kind", "symbol"});
        const auto symbol = py::cast<py::dict>(value["symbol"]);
        requireParameterReferenceSymbol(symbol);
        const auto index = indexFromBngir(symbol["index"], "parameter reference");
        if (index >= parameterNames.size()) {
            throw std::runtime_error("native BNGIR parameter reference is out of range");
        }
        return Expression::identifier(parameterNames[index]);
    }

    if (kind == "unary") {
        requireExpressionProperties(value, {"kind", "operator", "arguments"});
        const auto arguments = py::cast<py::list>(value["arguments"]);
        if (arguments.size() != 1) {
            throw std::runtime_error(
                "native BNGIR unary expression must have one argument");
        }
        const auto op = py::cast<std::string>(value["operator"]);
        if (op == "plus") return Expression::unary("+", expressionFromBngir(arguments[0], parameterNames));
        if (op == "negate") return Expression::unary("-", expressionFromBngir(arguments[0], parameterNames));
        throw std::runtime_error("unsupported native BNGIR unary operator");
    }
    if (kind == "binary") {
        requireExpressionProperties(value, {"kind", "operator", "arguments"});
        const auto arguments = py::cast<py::list>(value["arguments"]);
        if (arguments.size() != 2) {
            throw std::runtime_error(
                "native BNGIR binary expression must have two arguments");
        }
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

SpeciesGraph patternFromBngir(Model& model, const py::dict& pattern) {
    static const std::vector<std::string> requiredPatternKeys = {
        "compartment_prefix", "molecules",
    };
    static const std::vector<std::string> allowedPatternKeys = {
        "compartment", "compartment_prefix", "molecules",
    };
    requireObjectKeys(pattern, requiredPatternKeys, allowedPatternKeys, "pattern");
    const py::handle prefix = pattern["compartment_prefix"];
    if (!PyBool_Check(prefix.ptr())) {
        throw std::runtime_error(
            "native BNGIR pattern compartment_prefix must be boolean");
    }
    const bool isPrefix = py::cast<bool>(prefix);

    std::string outerCompartment;
    if (pattern.contains(py::str("compartment"))) {
        if (!py::isinstance<py::str>(pattern["compartment"])) {
            throw std::runtime_error(
                "native BNGIR pattern compartment must be a string");
        }
        outerCompartment = py::cast<std::string>(pattern["compartment"]);
        if (outerCompartment.empty()) {
            throw std::runtime_error(
                "native BNGIR pattern compartment must not be empty");
        }
        const auto& compartments = model.getCompartments();
        if (std::find_if(compartments.begin(), compartments.end(),
                          [&](const Compartment& compartment) {
                              return compartment.getName() == outerCompartment;
                          }) == compartments.end()) {
            throw std::runtime_error(
                "native BNGIR pattern references an unknown compartment");
        }
    }

    BNGcore::PatternGraph graph;
    const auto molecules = py::cast<py::list>(pattern["molecules"]);
    if (molecules.size() != 1) {
        throw std::runtime_error(
            "native BNGIR pattern requires exactly one molecule");
    }
    for (const auto& rawMolecule : molecules) {
        const auto molecule = py::cast<py::dict>(rawMolecule);
        static const std::vector<std::string> requiredMoleculeKeys = {
            "occurrence", "sites", "type", "type_id",
        };
        static const std::vector<std::string> allowedMoleculeKeys = {
            "compartment", "compartment_id", "occurrence", "sites",
            "type", "type_id",
        };
        requireObjectKeys(molecule, requiredMoleculeKeys, allowedMoleculeKeys,
                          "pattern molecule");
        if (indexFromBngir(molecule["occurrence"], "molecule occurrence") != 0) {
            throw std::runtime_error(
                "native BNGIR pattern requires molecule occurrence zero");
        }
        const auto sites = py::cast<py::list>(molecule["sites"]);
        if (!sites.empty()) {
            throw std::runtime_error(
                "native BNGIR pattern does not support molecule sites");
        }
        const auto typeId =
            indexFromBngir(molecule["type_id"], "molecule type reference");
        if (typeId >= model.getMoleculeTypes().size()) {
            throw std::runtime_error("native BNGIR molecule type reference is out of range");
        }
        const auto& moleculeType = model.getMoleculeTypes()[typeId];
        if (!py::isinstance<py::str>(molecule["type"]) ||
            py::cast<std::string>(molecule["type"]) != moleculeType.getName()) {
            throw std::runtime_error(
                "native BNGIR molecule type name does not match type_id");
        }
        const auto& nodeType = model.getGraphTypeRegistry().ensureMoleculeType(moleculeType);
        BNGcore::Node node(nodeType);

        std::string moleculeCompartment;
        if (molecule.contains(py::str("compartment"))) {
            if (!py::isinstance<py::str>(molecule["compartment"])) {
                throw std::runtime_error(
                    "native BNGIR pattern molecule compartment must be a string");
            }
            moleculeCompartment = py::cast<std::string>(molecule["compartment"]);
            if (moleculeCompartment.empty()) {
                throw std::runtime_error(
                    "native BNGIR pattern molecule compartment must not be empty");
            }
        } else if (molecule.contains(py::str("compartment_id"))) {
            const auto compartmentId = indexFromBngir(
                molecule["compartment_id"], "pattern molecule compartment id");
            const auto& compartments = model.getCompartments();
            if (compartmentId >= compartments.size()) {
                throw std::runtime_error(
                    "native BNGIR pattern molecule compartment id is out of range");
            }
            moleculeCompartment = compartments[compartmentId].getName();
        }
        if (!moleculeCompartment.empty()) {
            const auto& compartments = model.getCompartments();
            if (std::find_if(compartments.begin(), compartments.end(),
                              [&](const Compartment& compartment) {
                                  return compartment.getName() == moleculeCompartment;
                              }) == compartments.end()) {
                throw std::runtime_error(
                    "native BNGIR pattern molecule references an unknown compartment");
            }
            node.set_compartment(moleculeCompartment);
        }

        graph.add_node(node);
    }
    SpeciesGraph result(graph, outerCompartment);
    result.setCompartmentIsPrefix(isPrefix);
    return result;
}

std::unique_ptr<Model> modelFromBngirV02(const py::dict& document) {
    rejectUnsupportedModelSections(document);
    const auto parameters = py::cast<py::list>(document["parameters"]);
    const auto moleculeTypes = py::cast<py::list>(document["molecule_types"]);
    const auto seeds = py::cast<py::list>(document["seeds"]);
    const auto rules = py::cast<py::list>(document["rules"]);
    for (const auto& rawParameter : parameters) {
        requireParameterKeys(py::cast<py::dict>(rawParameter));
    }
    requireDenseOrderedIds(parameters, "parameter");
    requireDenseOrderedIds(moleculeTypes, "molecule type");
    requireDenseOrderedIds(seeds, "seed");
    requireDenseOrderedIds(rules, "rule");
    for (const auto& rawMoleculeType : moleculeTypes) {
        const auto moleculeType = py::cast<py::dict>(rawMoleculeType);
        const py::str populationKey("population");
        if (!moleculeType.contains(populationKey)) {
            throw std::runtime_error(
                "native BNGIR molecule type is missing population");
        }
        const py::handle population = moleculeType[populationKey];
        if (!PyBool_Check(population.ptr())) {
            throw std::runtime_error(
                "native BNGIR molecule type population must be boolean");
        }
        if (py::cast<bool>(population)) {
            throw std::runtime_error(
                "native BNGIR population molecule types are unsupported");
        }
        const auto components = py::cast<py::list>(moleculeType["components"]);
        if (!components.empty()) {
            throw std::runtime_error(
                "native BNGIR molecule type components are unsupported");
        }
    }

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
    std::set<std::string> uniqueParameterNames;
    for (const auto& rawParameter : parameters) {
        const auto parameter = py::cast<py::dict>(rawParameter);
        const auto name = py::cast<std::string>(parameter["name"]);
        if (!uniqueParameterNames.insert(name).second) {
            throw std::runtime_error(
                "native BNGIR parameter names must be unique");
        }
        parameterNames.push_back(name);
    }
    for (const auto& rawParameter : parameters) {
        const auto parameter = py::cast<py::dict>(rawParameter);
        model->addParameter(Parameter(
            py::cast<std::string>(parameter["name"]),
            expressionFromBngir(py::cast<py::dict>(parameter["expression"]), parameterNames)));
    }

    std::set<std::string> uniqueMoleculeTypeNames;
    for (const auto& rawMoleculeType : moleculeTypes) {
        const auto moleculeType = py::cast<py::dict>(rawMoleculeType);
        const auto name = py::cast<std::string>(moleculeType["name"]);
        if (!uniqueMoleculeTypeNames.insert(name).second) {
            throw std::runtime_error(
                "native BNGIR molecule type names must be unique");
        }
        model->addMoleculeType(MoleculeType(
            name, {}, false));
    }

    std::set<std::string> uniqueCompartmentNames;
    const auto compartments = py::cast<py::list>(document["compartments"]);
    requireDenseOrderedIds(compartments, "compartment");
    for (const auto& rawCompartment : compartments) {
        const auto compartment = py::cast<py::dict>(rawCompartment);
        static const std::vector<std::string> required = {
            "id", "name", "dimension", "volume",
        };
        static const std::vector<std::string> allowed = {
            "id", "name", "dimension", "volume", "unit",
            "declared_unit", "normalized_volume", "parent_id", "parent",
        };
        requireObjectKeys(compartment, required, allowed, "compartment");
        const auto name = py::cast<std::string>(compartment["name"]);
        if (!uniqueCompartmentNames.insert(name).second) {
            throw std::runtime_error(
                "native BNGIR compartment names must be unique");
        }
        const auto volume = finiteNumberFromBngir(
            compartment["volume"], "compartment volume");
        const auto dimension = py::cast<int>(compartment["dimension"]);
        if (dimension < 1 || dimension > 3) {
            throw std::runtime_error(
                "native BNGIR compartment dimension must be 1, 2, or 3");
        }
        const auto parent = compartment.contains(py::str("parent"))
            ? py::cast<std::string>(compartment["parent"])
            : std::string{};
        model->addCompartment(Compartment(name, volume, dimension, parent));
    }

    for (const auto& rawSeed : seeds) {
        const auto seed = py::cast<py::dict>(rawSeed);
        auto graph = patternFromBngir(*model, py::cast<py::dict>(seed["pattern"]));
        auto amount = expressionFromBngir(
            py::cast<py::dict>(seed["amount"]), parameterNames);
        std::string seedCompartment;
        if (seed.contains(py::str("compartment")) &&
            py::isinstance<py::str>(seed["compartment"])) {
            seedCompartment = py::cast<std::string>(seed["compartment"]);
        } else {
            seedCompartment = graph.getCompartment();
        }
        model->addSeedSpecies(SeedSpecies(
            {}, std::move(amount), py::cast<bool>(seed["constant"]),
            seedCompartment, graph.getGraph()));
    }

    for (const auto& rawRule : rules) {
        const auto rule = py::cast<py::dict>(rawRule);
        static const std::vector<std::string> ruleKeys = {
            "id", "name", "label", "bidirectional", "modifiers", "forward",
            "molecule_mappings", "component_mappings",
        };
        requireObjectKeys(rule, ruleKeys, ruleKeys, "rule");
        const py::handle bidirectional = rule["bidirectional"];
        if (!PyBool_Check(bidirectional.ptr()) || py::cast<bool>(bidirectional) ||
            !py::cast<py::list>(rule["modifiers"]).empty()) {
            throw std::runtime_error(
                "native BNGIR requires a forward ordinary rule");
        }
        const auto direction = py::cast<py::dict>(rule["forward"]);
        static const std::vector<std::string> directionKeys = {
            "reactants", "products", "rate", "filters", "local_scopes",
            "mutations", "transformations_complete",
        };
        requireObjectKeys(direction, directionKeys, directionKeys, "rule direction");
        if (!py::cast<py::list>(direction["filters"]).empty() ||
            !py::cast<py::list>(direction["local_scopes"]).empty()) {
            throw std::runtime_error(
                "native BNGIR does not support filters or local scopes");
        }
        const auto reactants = py::cast<py::list>(direction["reactants"]);
        const auto products = py::cast<py::list>(direction["products"]);
        if (reactants.size() != 1 || products.size() != 1) {
            throw std::runtime_error(
                "native BNGIR rule direction requires exactly one reactant and product pattern");
        }
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
