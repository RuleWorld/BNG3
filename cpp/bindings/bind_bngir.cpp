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
#include "ast/Function.hpp"
#include "ast/Model.hpp"
#include "ast/MoleculeType.hpp"
#include "ast/Observable.hpp"
#include "ast/Parameter.hpp"
#include "ast/ReactionRule.hpp"
#include "ast/SeedSpecies.hpp"
#include "ast/SpeciesGraph.hpp"
#include "compile/CompiledRateLaw.hpp"
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

bool pythonObjectsEqual(const py::handle& left, const py::handle& right) {
    const int result = PyObject_RichCompareBool(left.ptr(), right.ptr(), Py_EQ);
    if (result < 0) {
        throw py::error_already_set();
    }
    return result == 1;
}

void requireReversibleDirectionMutations(
    const py::dict& direction,
    const std::vector<SpeciesGraph>& reactants,
    const std::vector<SpeciesGraph>& products,
    const std::string& where) {
    if (reactants.empty() || products.empty()) {
        throw std::runtime_error(
            "native BNGIR " + where +
            " requires reactant and product patterns for reversible rules");
    }
    std::set<std::string> reactantTypes;
    std::set<std::string> productTypes;
    for (const auto& graph : reactants) {
        const auto nodes = graph.getGraph();
        if (nodes.size() != 1) {
            throw std::runtime_error(
                "native BNGIR " + where +
                " reversible patterns must contain one molecule each");
        }
        reactantTypes.insert((*nodes.begin())->get_type().get_type_name());
    }
    for (const auto& graph : products) {
        const auto nodes = graph.getGraph();
        if (nodes.size() != 1) {
            throw std::runtime_error(
                "native BNGIR " + where +
                " reversible patterns must contain one molecule each");
        }
        productTypes.insert((*nodes.begin())->get_type().get_type_name());
    }
    for (const auto& moleculeType : productTypes) {
        if (reactantTypes.count(moleculeType)) {
            throw std::runtime_error(
                "native BNGIR " + where +
                " reversible rules cannot carry molecule types across directions");
        }
    }

    std::vector<std::string> observed;
    for (const auto& rawMutation : py::cast<py::list>(direction["mutations"])) {
        const auto mutation = py::cast<py::dict>(rawMutation);
        const auto reference = py::cast<py::dict>(mutation["molecule"]);
        const auto kind = py::cast<std::string>(mutation["kind"]);
        const auto side = py::cast<std::string>(reference["side"]);
        const auto pattern = indexFromBngir(
            reference["pattern"], "reversible mutation pattern reference");
        const auto molecule = indexFromBngir(
            reference["molecule"], "reversible mutation molecule reference");
        if (molecule != 0) {
            throw std::runtime_error(
                "native BNGIR " + where +
                " has an out-of-slice reversible molecule reference");
        }
        observed.push_back(kind + ":" + side + ":" + std::to_string(pattern));
    }
    std::vector<std::string> expected;
    for (std::size_t index = 0; index < reactants.size(); ++index) {
        expected.push_back("delete_molecule:reactant:" + std::to_string(index));
    }
    for (std::size_t index = 0; index < products.size(); ++index) {
        expected.push_back("add_molecule:product:" + std::to_string(index));
    }
    std::sort(expected.begin(), expected.end());
    std::sort(observed.begin(), observed.end());
    if (observed != expected) {
        throw std::runtime_error(
            "native BNGIR " + where +
            ".mutations do not state the delete-and-add operations represented by its patterns");
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

// Read a wire symbol and require it to name the expected kind. The index is
// returned so the caller can resolve the name it points at.
std::size_t requireSymbolIndex(const py::dict& symbol,
                                const std::string& where,
                                const std::string& kind,
                                const std::string& indexWhere) {
    static const std::vector<std::string> keys = {"kind", "index"};
    requireObjectKeys(symbol, keys, keys, where);
    if (!py::isinstance<py::str>(symbol["kind"]) ||
        py::cast<std::string>(symbol["kind"]) != kind) {
        throw std::runtime_error("native BNGIR " + where + " kind must be " + kind);
    }
    return indexFromBngir(symbol["index"], indexWhere);
}

void requireExpressionProperties(const py::dict& expression,
                                 const std::vector<std::string>& allowed) {
    requireObjectKeys(expression, {}, allowed, "expression");
}

void rejectUnsupportedModelSections(const py::dict& document) {
    static const std::vector<std::string> sections = {
        "energy_patterns", "barrier_patterns", "population_maps",
        "population_types",
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

// The names a wire expression can point at. The compiler resolves a bare name
// to a parameter, an observable or a function in that order, so the importer
// has to know every name in the model to rebuild a reference faithfully.
struct BngirNames {
    std::vector<std::string> parameterNames;
    std::vector<std::string> functionNames;
    std::vector<std::size_t> functionArities;
    std::vector<std::string> observableNames;
};

// The scope an expression is rebuilt in. A model-level expression has no
// arguments; a function body is rebuilt with the arguments of the function
// that owns it, because a local reference is only meaningful there.
struct BngirScope {
    const BngirNames* names = nullptr;
    std::vector<std::string> localNames;
    bool functionBody = false;
};

bool containsName(const std::vector<std::string>& names, const std::string& name) {
    return std::find(names.begin(), names.end(), name) != names.end();
}

Expression expressionFromBngir(const py::dict& value, const BngirScope& scope) {
    const auto& names = *scope.names;
    const auto kind = py::cast<std::string>(value["kind"]);
    if (kind == "number") {
        requireExpressionProperties(value, {"kind", "value"});
        return Expression::number(
            finiteNumberFromBngir(value["value"], "expression value"));
    }
    if (kind == "parameter_ref") {
        requireExpressionProperties(value, {"kind", "symbol"});
        const auto symbol = py::cast<py::dict>(value["symbol"]);
        const auto index = requireSymbolIndex(
            symbol, "parameter reference symbol", "parameter", "parameter reference");
        if (index >= names.parameterNames.size()) {
            throw std::runtime_error("native BNGIR parameter reference is out of range");
        }
        const auto& name = names.parameterNames[index];
        // The compiler resolves an argument before a parameter, so a parameter
        // that shares a name with an argument is unreachable in the body.
        if (containsName(scope.localNames, name)) {
            throw std::runtime_error(
                "native BNGIR function parameter reference is shadowed by an argument");
        }
        return Expression::identifier(name);
    }
    if (kind == "local_ref") {
        requireExpressionProperties(value, {"kind", "name"});
        if (!scope.functionBody) {
            throw std::runtime_error(
                "native BNGIR local reference is only supported inside a function body");
        }
        if (!py::isinstance<py::str>(value["name"])) {
            throw std::runtime_error(
                "native BNGIR local reference name must be a string");
        }
        const auto name = py::cast<std::string>(value["name"]);
        if (!containsName(scope.localNames, name)) {
            throw std::runtime_error(
                "native BNGIR local reference is not a function argument");
        }
        return Expression::identifier(name);
    }
    if (kind == "function_ref") {
        requireExpressionProperties(value, {"kind", "symbol", "call", "arguments"});
        const auto symbol = py::cast<py::dict>(value["symbol"]);
        const auto index = requireSymbolIndex(
            symbol, "function reference symbol", "function", "function reference");
        if (index >= names.functionNames.size()) {
            throw std::runtime_error("native BNGIR function reference is out of range");
        }
        const auto& name = names.functionNames[index];
        bool isCall = false;
        if (value.contains(py::str("call"))) {
            const auto call = value["call"];
            if (!PyBool_Check(call.ptr())) {
                throw std::runtime_error(
                    "native BNGIR function reference call must be boolean");
            }
            isCall = py::cast<bool>(call);
        }
        std::vector<Expression> arguments;
        if (value.contains(py::str("arguments"))) {
            const auto raw = py::cast<py::list>(value["arguments"]);
            arguments.reserve(raw.size());
            for (const auto& item : raw) {
                arguments.push_back(
                    expressionFromBngir(py::cast<py::dict>(item), scope));
            }
        }
        if (!isCall) {
            if (!arguments.empty()) {
                throw std::runtime_error(
                    "native BNGIR function reference arguments require a call");
            }
            // A bare name reaches the function only when no parameter, no
            // observable and no argument answers to it first.
            if (containsName(names.parameterNames, name) ||
                containsName(names.observableNames, name) ||
                containsName(scope.localNames, name)) {
                throw std::runtime_error(
                    "native BNGIR function reference is shadowed by another symbol");
            }
            return Expression::identifier(name);
        }
        if (arguments.size() != names.functionArities[index]) {
            throw std::runtime_error(
                "native BNGIR function call arity does not match the declaration");
        }
        return Expression::function(name, std::move(arguments));
    }
    if (kind == "observable_ref") {
        requireExpressionProperties(value, {"kind", "symbol", "call", "arguments"});
        const auto symbol = py::cast<py::dict>(value["symbol"]);
        const auto index = requireSymbolIndex(
            symbol, "observable reference symbol", "observable",
            "observable reference");
        if (index >= names.observableNames.size()) {
            throw std::runtime_error("native BNGIR observable reference is out of range");
        }
        if (!scope.functionBody) {
            throw std::runtime_error(
                "native BNGIR observable reference is only supported inside a function body");
        }
        if (value.contains(py::str("arguments")) &&
            !py::cast<py::list>(value["arguments"]).empty()) {
            throw std::runtime_error(
                "native BNGIR scoped observable reference is not supported");
        }
        const auto& name = names.observableNames[index];
        bool isCall = false;
        if (value.contains(py::str("call"))) {
            const auto call = value["call"];
            if (!PyBool_Check(call.ptr())) {
                throw std::runtime_error(
                    "native BNGIR observable reference call must be boolean");
            }
            isCall = py::cast<bool>(call);
        }
        if (isCall) {
            return Expression::observableRef(name, {});
        }
        // A bare observable name is an identifier, and an identifier reaches
        // an argument or a parameter before it reaches the observable.
        if (containsName(scope.localNames, name) ||
            containsName(names.parameterNames, name)) {
            throw std::runtime_error(
                "native BNGIR function observable reference is shadowed by another symbol");
        }
        return Expression::identifier(name);
    }

    if (kind == "unary") {
        requireExpressionProperties(value, {"kind", "operator", "arguments"});
        const auto arguments = py::cast<py::list>(value["arguments"]);
        if (arguments.size() != 1) {
            throw std::runtime_error(
                "native BNGIR unary expression must have one argument");
        }
        const auto op = py::cast<std::string>(value["operator"]);
        if (op == "plus") return Expression::unary("+", expressionFromBngir(arguments[0], scope));
        if (op == "negate") return Expression::unary("-", expressionFromBngir(arguments[0], scope));
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
            expressionFromBngir(arguments[0], scope),
            expressionFromBngir(arguments[1], scope));
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
        // The compiled snapshot includes a resolved compartment id even when
        // it is inherited from the enclosing pattern. Preserve inheritance
        // when only that redundant id is present, while retaining an explicit
        // molecule compartment string from the BNGIR document.
        if (!moleculeCompartment.empty() &&
            (molecule.contains(py::str("compartment")) ||
             moleculeCompartment != outerCompartment)) {
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

// A model function declared by the wire document.
struct BngirFunction {
    std::string name;
    std::vector<std::string> arguments;
};

// Read the function declarations. The compiler resolves a bare name to a
// parameter, an observable or a function in that order, so a function whose
// name answers to an earlier symbol can never be reached and is refused here
// instead of being rebuilt into a reference that means something else.
std::vector<BngirFunction> functionsFromBngir(
    const py::list& functions,
    const std::vector<std::string>& parameterNames,
    const std::vector<std::string>& observableNames) {
    std::vector<BngirFunction> result;
    result.reserve(functions.size());
    std::set<std::string> uniqueNames;
    for (const auto& rawFunction : functions) {
        const auto function = py::cast<py::dict>(rawFunction);
        static const std::vector<std::string> functionKeys = {
            "id", "name", "arguments", "expression",
        };
        requireObjectKeys(function, functionKeys, functionKeys, "function");
        const auto name = py::cast<std::string>(function["name"]);
        if (name.empty() || !uniqueNames.insert(name).second) {
            throw std::runtime_error(
                "native BNGIR function names must be nonempty and unique");
        }
        if (containsName(parameterNames, name)) {
            throw std::runtime_error(
                "native BNGIR function names must not collide with parameter names");
        }
        if (containsName(observableNames, name)) {
            throw std::runtime_error(
                "native BNGIR function names must not collide with observable names");
        }
        if (bng::compile::isBuiltinFunctionName(name)) {
            throw std::runtime_error(
                "native BNGIR function names must not shadow a builtin function");
        }
        const auto rawArguments = py::cast<py::list>(function["arguments"]);
        std::vector<std::string> arguments;
        arguments.reserve(rawArguments.size());
        for (const auto& rawArgument : rawArguments) {
            if (!py::isinstance<py::str>(rawArgument)) {
                throw std::runtime_error(
                    "native BNGIR function arguments must be strings");
            }
            const auto argument = py::cast<std::string>(rawArgument);
            if (argument.empty()) {
                throw std::runtime_error(
                    "native BNGIR function arguments must be nonempty strings");
            }
            if (containsName(arguments, argument)) {
                throw std::runtime_error(
                    "native BNGIR function argument names must be unique");
            }
            arguments.push_back(argument);
        }
        result.push_back(BngirFunction{name, std::move(arguments)});
    }
    return result;
}

std::unique_ptr<Model> modelFromBngirV02(const py::dict& document) {
    rejectUnsupportedModelSections(document);
    const auto parameters = py::cast<py::list>(document["parameters"]);
    const auto moleculeTypes = py::cast<py::list>(document["molecule_types"]);
    const auto seeds = py::cast<py::list>(document["seeds"]);
    const auto rules = py::cast<py::list>(document["rules"]);
    const auto functions = py::cast<py::list>(document["functions"]);
    const auto observables = py::cast<py::list>(document["observables"]);
    for (const auto& rawParameter : parameters) {
        requireParameterKeys(py::cast<py::dict>(rawParameter));
    }
    requireDenseOrderedIds(parameters, "parameter");
    requireDenseOrderedIds(moleculeTypes, "molecule type");
    requireDenseOrderedIds(seeds, "seed");
    requireDenseOrderedIds(rules, "rule");
    requireDenseOrderedIds(functions, "function");
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

    // The observables are rebuilt before the function declarations: a
    // function that answers to an observable name can never be reached,
    // because the compiler resolves a bare name to the observable first.
    std::vector<std::string> observableNames;
    std::set<std::string> uniqueObservableNames;
    for (const auto& rawObservable : observables) {
        const auto observable = py::cast<py::dict>(rawObservable);
        static const std::vector<std::string> observableKeys = {
            "name", "type", "patterns",
        };
        requireObjectKeys(
            observable, observableKeys, observableKeys, "observable");
        if (!py::isinstance<py::str>(observable["name"]) ||
            !py::isinstance<py::str>(observable["type"])) {
            throw std::runtime_error(
                "native BNGIR observable name and type must be strings");
        }
        const auto name = py::cast<std::string>(observable["name"]);
        const auto type = py::cast<std::string>(observable["type"]);
        if (name.empty() || !uniqueObservableNames.insert(name).second) {
            throw std::runtime_error(
                "native BNGIR observable names must be nonempty and unique");
        }
        if (type != "Molecules" && type != "Species") {
            throw std::runtime_error(
                "native BNGIR observable type must be Molecules or Species");
        }
        if (!py::isinstance<py::list>(observable["patterns"])) {
            throw std::runtime_error(
                "native BNGIR observable patterns must be an array of strings");
        }
        const auto rawPatterns = py::cast<py::list>(observable["patterns"]);
        std::vector<std::string> patterns;
        patterns.reserve(rawPatterns.size());
        for (const auto& rawPattern : rawPatterns) {
            if (!py::isinstance<py::str>(rawPattern)) {
                throw std::runtime_error(
                    "native BNGIR observable patterns must be strings");
            }
            patterns.push_back(py::cast<std::string>(rawPattern));
        }
        observableNames.push_back(name);
        model->addObservable(Observable(name, type, std::move(patterns)));
    }

    const auto declaredFunctions =
        functionsFromBngir(functions, parameterNames, observableNames);

    BngirNames names;
    names.parameterNames = parameterNames;
    for (const auto& function : declaredFunctions) {
        names.functionNames.push_back(function.name);
        names.functionArities.push_back(function.arguments.size());
    }
    names.observableNames = observableNames;
    const BngirScope modelScope{&names, {}, false};

    for (const auto& rawParameter : parameters) {
        const auto parameter = py::cast<py::dict>(rawParameter);
        model->addParameter(Parameter(
            py::cast<std::string>(parameter["name"]),
            expressionFromBngir(
                py::cast<py::dict>(parameter["expression"]), modelScope)));
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
    std::vector<std::string> compartmentNames;
    compartmentNames.reserve(compartments.size());
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
        compartmentNames.push_back(name);
    }

    for (std::size_t index = 0; index < compartments.size(); ++index) {
        const auto compartment = py::cast<py::dict>(compartments[index]);
        const auto name = compartmentNames[index];
        const auto volume = finiteNumberFromBngir(
            compartment["volume"], "compartment volume");
        const auto dimension = py::cast<int>(compartment["dimension"]);
        if (dimension < 1 || dimension > 3) {
            throw std::runtime_error(
                "native BNGIR compartment dimension must be 1, 2, or 3");
        }
        std::string parent;
        if (compartment.contains(py::str("parent"))) {
            if (!py::isinstance<py::str>(compartment["parent"])) {
                throw std::runtime_error(
                    "native BNGIR compartment parent must be a string");
            }
            parent = py::cast<std::string>(compartment["parent"]);
            if (!parent.empty() &&
                std::find(compartmentNames.begin(), compartmentNames.end(), parent) ==
                    compartmentNames.end()) {
                throw std::runtime_error(
                    "native BNGIR compartment parent references an unknown compartment");
            }
        }
        if (compartment.contains(py::str("parent_id"))) {
            const auto parentId =
                indexFromBngir(compartment["parent_id"], "compartment parent id");
            if (parentId >= compartmentNames.size()) {
                throw std::runtime_error(
                    "native BNGIR compartment parent id is out of range");
            }
            const auto& parentById = compartmentNames[parentId];
            if (!parent.empty() && parent != parentById) {
                throw std::runtime_error(
                    "native BNGIR compartment parent name and id disagree");
            }
            parent = parentById;
        }
        if (parent == name) {
            throw std::runtime_error(
                "native BNGIR compartment cannot be its own parent");
        }
        model->addCompartment(Compartment(name, volume, dimension, parent));
    }

    for (const auto& rawSeed : seeds) {
        const auto seed = py::cast<py::dict>(rawSeed);
        auto graph = patternFromBngir(*model, py::cast<py::dict>(seed["pattern"]));
        auto amount = expressionFromBngir(
            py::cast<py::dict>(seed["amount"]), modelScope);
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
        static const std::vector<std::string> requiredRuleKeys = {
            "id", "name", "label", "bidirectional", "modifiers", "forward",
            "molecule_mappings", "component_mappings",
        };
        static const std::vector<std::string> allowedRuleKeys = {
            "id", "name", "label", "bidirectional", "modifiers", "forward",
            "reverse", "molecule_mappings", "component_mappings",
        };
        requireObjectKeys(
            rule, requiredRuleKeys, allowedRuleKeys, "rule");
        const py::handle bidirectional = rule["bidirectional"];
        if (!PyBool_Check(bidirectional.ptr())) {
            throw std::runtime_error(
                "native BNGIR rule bidirectional field must be boolean");
        }
        const bool isBidirectional = py::cast<bool>(bidirectional);
        const bool hasReverse = rule.contains(py::str("reverse"));
        if (isBidirectional != hasReverse) {
            throw std::runtime_error(
                "native BNGIR bidirectional rule requires an explicit reverse direction");
        }
        if (!py::cast<py::list>(rule["modifiers"]).empty()) {
            throw std::runtime_error(
                "native BNGIR does not support rule modifiers");
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
        if (reactants.empty() || products.empty()) {
            throw std::runtime_error(
                "native BNGIR does not support a rule direction without a "
                "reactant and product pattern");
        }
        std::vector<SpeciesGraph> reactantGraphs;
        std::vector<SpeciesGraph> productGraphs;
        for (const auto& rawReactant : reactants) {
            reactantGraphs.push_back(
                patternFromBngir(*model, py::cast<py::dict>(rawReactant)));
        }
        for (const auto& rawProduct : products) {
            productGraphs.push_back(
                patternFromBngir(*model, py::cast<py::dict>(rawProduct)));
        }
        if (isBidirectional) {
            requireReversibleDirectionMutations(
                direction, reactantGraphs, productGraphs, "forward rule direction");
        }
        if (reactantGraphs.size() > 1 || productGraphs.size() > 1) {
            // The rule is rebuilt from its patterns, and the pattern structure
            // decides the rule's operations. A direction with more than one
            // pattern is only rebuilt faithfully when the document states the
            // same operations: every reactant molecule deleted and every
            // product molecule added, with no molecule carried over.
            if (!py::cast<py::list>(rule["molecule_mappings"]).empty()) {
                throw std::runtime_error(
                    "native BNGIR rule carries a molecule mapping that a "
                    "multi-pattern rule direction cannot rebuild");
            }
            std::vector<std::string> expected;
            for (std::size_t index = 0; index < reactantGraphs.size(); ++index) {
                expected.push_back("delete_molecule:reactant:" +
                                   std::to_string(index));
            }
            for (std::size_t index = 0; index < productGraphs.size(); ++index) {
                expected.push_back("add_molecule:product:" +
                                   std::to_string(index));
            }
            std::vector<std::string> observed;
            for (const auto& rawMutation :
                 py::cast<py::list>(direction["mutations"])) {
                const auto mutation = py::cast<py::dict>(rawMutation);
                const auto reference = py::cast<py::dict>(mutation["molecule"]);
                observed.push_back(
                    py::cast<std::string>(mutation["kind"]) + ":" +
                    py::cast<std::string>(reference["side"]) + ":" +
                    std::to_string(indexFromBngir(
                        reference["pattern"], "mutation pattern reference")));
            }
            std::sort(expected.begin(), expected.end());
            std::sort(observed.begin(), observed.end());
            if (observed != expected) {
                throw std::runtime_error(
                    "native BNGIR rule direction does not state the "
                    "delete-and-add operations of a multi-pattern direction");
            }
            std::set<std::string> reactantTypes;
            for (const auto& graph : reactantGraphs) {
                for (const auto* node : graph.getGraph()) {
                    reactantTypes.insert(node->get_type().get_type_name());
                }
            }
            for (const auto& graph : productGraphs) {
                for (const auto* node : graph.getGraph()) {
                    if (reactantTypes.count(node->get_type().get_type_name())) {
                        throw std::runtime_error(
                            "native BNGIR rule direction carries a "
                            "transformation the native slice cannot rebuild");
                    }
                }
            }
        }
        const auto rate = py::cast<py::dict>(direction["rate"]);
        std::vector<Expression> rates;
        rates.push_back(expressionFromBngir(
            py::cast<py::dict>(rate["expression"]), modelScope));

        if (isBidirectional) {
            const auto reverse = py::cast<py::dict>(rule["reverse"]);
            requireObjectKeys(reverse, directionKeys, directionKeys,
                              "reverse rule direction");
            if (!py::cast<py::list>(reverse["filters"]).empty() ||
                !py::cast<py::list>(reverse["local_scopes"]).empty()) {
                throw std::runtime_error(
                    "native BNGIR does not support reverse filters or local scopes");
            }
            if (!PyBool_Check(reverse["transformations_complete"].ptr()) ||
                !py::cast<bool>(reverse["transformations_complete"])) {
                throw std::runtime_error(
                    "native BNGIR reverse rule direction has incomplete transformations");
            }
            if (!pythonObjectsEqual(reverse["reactants"], direction["products"]) ||
                !pythonObjectsEqual(reverse["products"], direction["reactants"])) {
                throw std::runtime_error(
                    "native BNGIR reverse direction must invert forward patterns");
            }
            requireReversibleDirectionMutations(
                reverse, productGraphs, reactantGraphs, "reverse rule direction");
            const auto reverseRate = py::cast<py::dict>(reverse["rate"]);
            static const std::vector<std::string> rateKeys = {"kind", "expression"};
            requireObjectKeys(reverseRate, rateKeys, rateKeys,
                              "reverse rule rate");
            if (indexFromBngir(reverseRate["kind"], "reverse rule rate kind") != 0) {
                throw std::runtime_error(
                    "native BNGIR requires an expression reverse rate");
            }
            rates.push_back(expressionFromBngir(
                py::cast<py::dict>(reverseRate["expression"]), modelScope));
        }
        model->addReactionRule(ReactionRule::fromResolvedPatterns(
            py::cast<std::string>(rule["name"]),
            py::cast<std::string>(rule["label"]),
            std::move(rates),
            std::move(reactantGraphs), std::move(productGraphs),
            isBidirectional));
    }

    // The function bodies are rebuilt last: a body may name a parameter, one
    // of its own arguments, another model function or an observable, and the
    // compiler resolves those names in that order.
    for (std::size_t index = 0; index < functions.size(); ++index) {
        const auto function = py::cast<py::dict>(functions[index]);
        const auto& declared = declaredFunctions[index];
        const BngirScope functionScope{&names, declared.arguments, true};
        model->addFunction(Function(
            declared.name,
            declared.arguments,
            expressionFromBngir(
                py::cast<py::dict>(function["expression"]), functionScope)));
    }
    return model;
}

} // namespace

void bind_bngir(py::module_& module) {
    module.def("_model_from_bngir_v02", &modelFromBngirV02,
               py::arg("model"),
               "Build the supported BNGIR v0.2 subset directly from native structures.");
}
