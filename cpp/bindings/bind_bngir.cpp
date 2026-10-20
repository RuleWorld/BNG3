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

#include "ast/BarrierPattern.hpp"
#include "ast/EnergyPattern.hpp"
#include "ast/Expression.hpp"
#include "ast/Function.hpp"
#include "ast/Model.hpp"
#include "ast/MoleculeType.hpp"
#include "ast/Observable.hpp"
#include "ast/Parameter.hpp"
#include "ast/PopulationMap.hpp"
#include "ast/ReactionRule.hpp"
#include "ast/SeedSpecies.hpp"
#include "ast/SpeciesGraph.hpp"
#include "compile/CompiledRateLaw.hpp"
#include "compile/energy/BarrierCompiler.hpp"
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

// Read a model section that a document may leave out. The wire format makes
// the barrier and population-map sections optional, so an absent section
// means the model has none of that kind rather than a malformed document.
py::list optionalSection(const py::dict& document, const std::string& key) {
    if (!document.contains(py::str(key))) return py::list();
    return py::cast<py::list>(document[py::str(key)]);
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
// that owns it, because a local reference is only meaningful there. A rule
// rate is rebuilt with the local scopes the rule declares, because a local
// reference there names one of those scopes.
struct BngirScope {
    const BngirNames* names = nullptr;
    std::vector<std::string> localNames;
    bool functionBody = false;
    // A local reference is only meaningful where a local name exists: inside
    // a function body or inside a rule that declares local scopes.
    bool localScopes = false;
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
        // that shares a name with an argument is unreachable in the body. The
        // same holds for a rule's local scopes.
        if (containsName(scope.localNames, name)) {
            if (scope.functionBody) {
                throw std::runtime_error(
                    "native BNGIR function parameter reference is shadowed by an argument");
            }
            throw std::runtime_error(
                "native BNGIR rule parameter reference is shadowed by a local scope");
        }
        return Expression::identifier(name);
    }
    if (kind == "local_ref") {
        requireExpressionProperties(value, {"kind", "name"});
        if (!scope.functionBody && !scope.localScopes) {
            throw std::runtime_error(
                "native BNGIR local reference is only supported inside a "
                "function body or a rule with local scopes");
        }
        if (!py::isinstance<py::str>(value["name"])) {
            throw std::runtime_error(
                "native BNGIR local reference name must be a string");
        }
        const auto name = py::cast<std::string>(value["name"]);
        if (!containsName(scope.localNames, name)) {
            if (scope.functionBody) {
                throw std::runtime_error(
                    "native BNGIR local reference is not a function argument");
            }
            throw std::runtime_error(
                "native BNGIR local reference is not a local scope of the rule");
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
    // A bond group is shared by the sites it joins, and those sites can live on
    // different molecules of the same pattern, so the bond node is shared per
    // pattern rather than per molecule.
    std::map<int, BNGcore::Node*> bondNodesByGroup;
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

        auto* moleculeNode = graph.add_node(node);
        // A site is a component of the molecule type with a state constraint.
        // The native pattern graph keeps each component as its own node joined
        // to the molecule node, which is how the parser lowers a site too.
        for (const auto& rawSite : sites) {
            const auto site = py::cast<py::dict>(rawSite);
            const auto componentName = py::cast<std::string>(site["component"]);
            const bng::ast::ComponentType* componentType = nullptr;
            for (const auto& candidate : moleculeType.getComponents()) {
                if (candidate.name == componentName) {
                    componentType = &candidate;
                    break;
                }
            }
            if (componentType == nullptr) {
                throw std::runtime_error(
                    "native BNGIR pattern molecule names a component the "
                    "molecule type does not declare");
            }
            BNGcore::Node componentNodeValue(
                model.getGraphTypeRegistry().ensureComponentType(
                    moleculeType, *componentType));
            auto* componentNode = graph.add_node(componentNodeValue);
            graph.add_edge(moleculeNode, componentNode);

            const auto state = py::cast<py::dict>(site["state"]);
            const auto stateKind = py::cast<std::string>(state["kind"]);
            const auto& runtimeStateType =
                componentNode->get_type().get_state_type();
            if (const auto* labelStateType =
                    dynamic_cast<const BNGcore::LabelStateType*>(&runtimeStateType)) {
                if (stateKind == "exact") {
                    componentNode->set_state(BNGcore::LabelState(
                        *labelStateType, py::cast<std::string>(state["value"])));
                } else if (stateKind == "any") {
                    componentNode->set_state(
                        BNGcore::LabelState(*labelStateType, "?"));
                } else {
                    throw std::runtime_error(
                        "native BNGIR pattern molecule site state kind is not "
                        "supported: " + stateKind);
                }
            }

            const auto bond = py::cast<py::dict>(site["bond"]);
            const auto bondKind = py::cast<std::string>(bond["kind"]);
            BNGcore::Node* bondNode = nullptr;
            if (bondKind == "bound" || bondKind == "exact") {
                const int group = bond.contains("group")
                    ? py::cast<int>(bond["group"])
                    : 0;
                const auto found = bondNodesByGroup.find(group);
                if (found != bondNodesByGroup.end()) {
                    bondNode = found->second;
                } else {
                    BNGcore::Node bondNodeValue(BNGcore::BOND_NODE_TYPE);
                    bondNode = graph.add_node(bondNodeValue);
                    bondNode->set_state(BNGcore::BOUND_STATE);
                    bondNodesByGroup.emplace(group, bondNode);
                }
            } else {
                BNGcore::Node bondNodeValue(BNGcore::BOND_NODE_TYPE);
                bondNode = graph.add_node(bondNodeValue);
                if (bondKind == "any") {
                    bondNode->set_state(BNGcore::BondState(
                        BNGcore::BOND_STATE_TYPE, BNGcore::WILDCARD_STRING));
                } else {
                    // An unbound or unspecified bond cannot be a bound one.
                    bondNode->set_state(BNGcore::UNBOUND_STATE);
                }
            }
            graph.add_edge(componentNode, bondNode);
        }
    }
    SpeciesGraph result(graph, outerCompartment);
    result.setCompartmentIsPrefix(isPrefix);
    return result;
}

// The population map's pattern is compiled from the map's pattern text, so
// the importer renders the document's structured pattern back to that text.
// The compartment form the document states is preserved, because the text is
// the only representation the compiler reads.
std::string patternTextFromBngir(const SpeciesGraph& graph) {
    // The per-molecule compartments belong to the pattern, so each molecule
    // is annotated with the compartment it carries.
    std::vector<std::string> moleculeCompartments;
    const auto body = graph.getGraph().get_BNG2_string(moleculeCompartments);
    std::string rendered = body;
    bool hasMoleculeCompartment = false;
    for (const auto& compartment : moleculeCompartments) {
        if (!compartment.empty()) {
            hasMoleculeCompartment = true;
            break;
        }
    }
    if (hasMoleculeCompartment) {
        std::string annotated;
        std::size_t moleculeIndex = 0;
        std::size_t position = 0;
        while (position < body.size()) {
            int depth = 0;
            std::size_t moleculeEnd = position;
            while (moleculeEnd < body.size()) {
                const auto character = body[moleculeEnd];
                if (character == '(') {
                    ++depth;
                } else if (character == ')') {
                    --depth;
                } else if (character == '.' && depth == 0) {
                    break;
                }
                ++moleculeEnd;
            }
            annotated.append(body, position, moleculeEnd - position);
            if (moleculeIndex < moleculeCompartments.size() &&
                !moleculeCompartments[moleculeIndex].empty()) {
                annotated += "@" + moleculeCompartments[moleculeIndex];
            }
            ++moleculeIndex;
            if (moleculeEnd < body.size()) {
                annotated += '.';
                position = moleculeEnd + 1;
            } else {
                position = moleculeEnd;
            }
        }
        rendered = annotated;
    }
    const auto& compartment = graph.getCompartment();
    if (compartment.empty()) return rendered;
    if (graph.isCompartmentPrefix()) return "@" + compartment + ":" + rendered;
    return rendered + "@" + compartment;
}

// Build the population map the compiler expects: the pattern, the population
// target, its arguments, and the mapping rate. A map without a rate would
// compile to a zero rate, so the rate is required here rather than defaulted.
PopulationMap populationMapFromBngir(Model& model,
                                     const py::dict& mapping,
                                     const BngirScope& scope) {
    static const std::vector<std::string> requiredKeys = {
        "index", "label", "pattern", "arguments", "rate",
    };
    static const std::vector<std::string> allowedKeys = {
        "arguments", "function", "index", "label", "pattern", "population",
        "population_id", "rate",
    };
    requireObjectKeys(mapping, requiredKeys, allowedKeys, "population map");

    PopulationMap result;
    result.label = py::cast<std::string>(mapping["label"]);
    const auto pattern =
        patternFromBngir(model, py::cast<py::dict>(mapping["pattern"]));
    result.patternText = patternTextFromBngir(pattern);

    std::string populationName;
    if (mapping.contains(py::str("population"))) {
        populationName = py::cast<std::string>(mapping["population"]);
    }
    if (mapping.contains(py::str("function"))) {
        // `function` is the legacy alias for the canonical population name.
        const auto legacy = py::cast<std::string>(mapping["function"]);
        if (!populationName.empty() && populationName != legacy) {
            throw std::runtime_error(
                "native BNGIR population map population name and function alias "
                "disagree");
        }
        populationName = legacy;
    }
    if (populationName.empty()) {
        throw std::runtime_error(
            "native BNGIR population map has no population name");
    }
    result.populationName = populationName;

    const auto rawArguments = py::cast<py::list>(mapping["arguments"]);
    result.populationArgs.reserve(rawArguments.size());
    for (const auto& rawArgument : rawArguments) {
        if (!py::isinstance<py::str>(rawArgument)) {
            throw std::runtime_error(
                "native BNGIR population map arguments must be strings");
        }
        result.populationArgs.push_back(py::cast<std::string>(rawArgument));
    }

    const auto rate =
        expressionFromBngir(py::cast<py::dict>(mapping["rate"]), scope);
    result.rateExpression = rate;
    result.rateText = rate.toString();
    result.hasExplicitRate = true;

    // Compatibility aliases retained for older callers while they migrate.
    result.populationFunction = result.populationName;
    result.functionArgs = result.populationArgs;
    return result;
}

// A model function declared by the wire document.
struct BngirFunction {
    std::string name;
    std::vector<std::string> arguments;
};

// Build the barrier pattern the compiler expects: a transition rule whose
// single rewrite is the reaction center the barrier applies to, plus the
// transition-state energy. The document's transition text is kept as the
// barrier's own representation of that rewrite, so the wire form round-trips
// exactly; the transition's semantics come from the structured patterns.
BarrierPattern barrierPatternFromBngir(Model& model,
                                       const py::dict& barrier,
                                       const BngirScope& scope,
                                       std::size_t index) {
    static const std::vector<std::string> requiredKeys = {
        "index", "label", "transition", "expression", "reaction_center",
        "center_resolved", "value", "reactants", "products", "bidirectional",
    };
    static const std::vector<std::string> allowedKeys = {
        "bidirectional", "center_resolved", "expression", "index", "label",
        "products", "reactants", "reaction_center", "transition", "value",
    };
    requireObjectKeys(barrier, requiredKeys, allowedKeys, "barrier pattern");

    const auto label = py::cast<std::string>(barrier["label"]);
    const py::handle resolved = barrier["center_resolved"];
    if (!PyBool_Check(resolved.ptr()) || !py::cast<bool>(resolved)) {
        throw std::runtime_error(
            "native BNGIR barrier pattern does not carry a resolved reaction center");
    }
    const auto reactionCenter = py::cast<std::string>(barrier["reaction_center"]);
    if (reactionCenter.empty()) {
        throw std::runtime_error(
            "native BNGIR barrier pattern does not carry a resolved reaction center");
    }

    std::vector<SpeciesGraph> reactantGraphs;
    std::vector<std::string> reactantTexts;
    for (const auto& rawPattern :
         py::cast<py::list>(barrier["reactants"])) {
        const auto graph =
            patternFromBngir(model, py::cast<py::dict>(rawPattern));
        reactantTexts.push_back(patternTextFromBngir(graph));
        reactantGraphs.push_back(std::move(graph));
    }
    std::vector<SpeciesGraph> productGraphs;
    std::vector<std::string> productTexts;
    for (const auto& rawPattern :
         py::cast<py::list>(barrier["products"])) {
        const auto graph =
            patternFromBngir(model, py::cast<py::dict>(rawPattern));
        productTexts.push_back(patternTextFromBngir(graph));
        productGraphs.push_back(std::move(graph));
    }
    if (reactantGraphs.empty() || productGraphs.empty()) {
        throw std::runtime_error(
            "native BNGIR barrier pattern transition has no reactant or product pattern");
    }

    const auto bidirectional = py::cast<bool>(barrier["bidirectional"]);
    std::vector<Expression> rates;
    rates.push_back(expressionFromBngir(
        py::cast<py::dict>(barrier["expression"]), scope));

    ReactionRule transition(
        "__bng3_barrier_" + std::to_string(index), label,
        std::move(reactantTexts), std::move(productTexts), std::move(rates), {},
        bidirectional, std::move(reactantGraphs), std::move(productGraphs));
    BarrierPattern result(label, std::move(transition));

    // The reaction center the compiler derives from the rebuilt transition
    // must be the one the document states, or the two disagree about which
    // rewrite the barrier applies to.
    bng::compile::energy::ReactionCenterKey key;
    std::string diagnostic;
    if (!bng::compile::energy::compileBarrierCenter(
            result.transition(), key, diagnostic)) {
        throw std::runtime_error(
            "native BNGIR barrier pattern transition is unsupported: " + diagnostic);
    }
    if (key.toString() != reactionCenter) {
        throw std::runtime_error(
            "native BNGIR barrier pattern reaction center does not match its transition");
    }
    result.setSourceText(py::cast<std::string>(barrier["transition"]));
    return result;
}

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


// Build the include/exclude filter modifier text the native rule parser
// understands: the pattern index is one-based and the molecule name selects
// the molecule the filter applies to.
std::string filterModifierText(const py::dict& filter) {
    const auto include = py::cast<bool>(filter["include"]);
    const auto side = py::cast<std::string>(filter["side"]);
    if (side != "reactant" && side != "product") {
        throw std::runtime_error("native BNGIR filter side is not supported");
    }
    const auto patternIndex = indexFromBngir(
        filter["pattern_index"], "filter pattern index");
    const auto patterns = py::cast<py::list>(filter["patterns"]);
    if (patterns.size() == 0) {
        throw std::runtime_error("native BNGIR filter has no pattern");
    }
    const auto pattern = py::cast<py::dict>(patterns[0]);
    const auto molecules = py::cast<py::list>(pattern["molecules"]);
    if (molecules.size() == 0) {
        throw std::runtime_error("native BNGIR filter pattern has no molecule");
    }
    const auto molecule = py::cast<py::dict>(molecules[0]);
    const auto moleculeName = py::cast<std::string>(molecule["type"]);
    return std::string(include ? "include_" : "exclude_") +
           (side == "product" ? "products" : "reactants") + "(" +
           std::to_string(patternIndex + 1) + "," + moleculeName + ")";
}

// Read the local-function scopes a direction declares.
//
// The wire form names the scope, its kind, the side it is anchored on, the
// pattern it indexes and, for a molecule scope, the molecule occurrence
// inside that pattern. A scope anchored on the reactants names that reactant
// pattern; a scope anchored on the products has no reactant pattern of its
// own.
std::vector<ReactionRule::LocalScope> localScopesFromBngir(
    const py::list& scopes,
    std::size_t reactantCount,
    std::size_t productCount,
    const std::string& where) {
    std::vector<ReactionRule::LocalScope> result;
    result.reserve(scopes.size());
    std::set<std::string> names;
    for (const auto& rawScope : scopes) {
        const auto scope = py::cast<py::dict>(rawScope);
        static const std::vector<std::string> required = {
            "name", "kind", "side", "pattern_index", "reactant_pattern",
        };
        static const std::vector<std::string> allowed = {
            "name", "kind", "side", "pattern_index", "reactant_pattern",
            "molecule_occurrence",
        };
        requireObjectKeys(scope, required, allowed, where);
        if (!py::isinstance<py::str>(scope["name"])) {
            throw std::runtime_error(
                "native BNGIR " + where + " name must be a string");
        }
        const auto name = py::cast<std::string>(scope["name"]);
        if (name.empty() || !names.insert(name).second) {
            throw std::runtime_error(
                "native BNGIR " + where + " names must be nonempty and unique");
        }
        ReactionRule::LocalScope localScope;
        localScope.name = name;

        const auto kind = py::cast<std::string>(scope["kind"]);
        if (kind == "species") {
            localScope.kind = ReactionRule::LocalScope::Kind::Species;
        } else if (kind == "molecule") {
            localScope.kind = ReactionRule::LocalScope::Kind::Molecule;
        } else {
            throw std::runtime_error(
                "native BNGIR " + where + " kind must be molecule or species");
        }

        const auto side = py::cast<std::string>(scope["side"]);
        const bool reactantSide = side == "reactant";
        if (!reactantSide && side != "product") {
            throw std::runtime_error(
                "native BNGIR " + where + " side must be reactant or product");
        }
        localScope.side = reactantSide
            ? ReactionRule::LocalScope::Side::Reactant
            : ReactionRule::LocalScope::Side::Product;

        const auto patternIndex =
            indexFromBngir(scope["pattern_index"], where + " pattern index");
        const auto patternCount = reactantSide ? reactantCount : productCount;
        if (patternIndex >= patternCount) {
            throw std::runtime_error(
                "native BNGIR " + where + " pattern index is out of range");
        }
        localScope.patternIndex = patternIndex;

        if (reactantSide) {
            const auto reactantPattern = indexFromBngir(
                scope["reactant_pattern"], where + " reactant pattern");
            if (reactantPattern != patternIndex) {
                throw std::runtime_error(
                    "native BNGIR " + where +
                    " reactant pattern does not match its pattern index");
            }
        } else if (!scope["reactant_pattern"].is_none()) {
            throw std::runtime_error(
                "native BNGIR " + where +
                " product-side scope must not name a reactant pattern");
        }

        if (scope.contains(py::str("molecule_occurrence"))) {
            if (localScope.kind != ReactionRule::LocalScope::Kind::Molecule) {
                throw std::runtime_error(
                    "native BNGIR " + where +
                    " species scope must not name a molecule occurrence");
            }
            localScope.moleculeOccurrence = indexFromBngir(
                scope["molecule_occurrence"], where + " molecule occurrence");
        }
        result.push_back(std::move(localScope));
    }
    return result;
}

// The names a direction declares as local scopes.
std::vector<std::string> localScopeNames(
    const std::vector<ReactionRule::LocalScope>& scopes) {
    std::vector<std::string> names;
    names.reserve(scopes.size());
    for (const auto& scope : scopes) names.push_back(scope.name);
    return names;
}

std::unique_ptr<Model> modelFromBngirV02(const py::dict& document,
                                        const py::object& protocol) {
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
        std::vector<bng::ast::ComponentType> componentTypes;
        for (const auto& rawComponent :
             py::cast<py::list>(moleculeType["components"])) {
            const auto component = py::cast<py::dict>(rawComponent);
            bng::ast::ComponentType componentType;
            componentType.name = py::cast<std::string>(component["name"]);
            for (const auto& rawState :
                 py::cast<py::list>(component["states"])) {
                componentType.allowedStates.push_back(
                    py::cast<std::string>(rawState));
            }
            componentTypes.push_back(std::move(componentType));
        }
        model->addMoleculeType(MoleculeType(
            name, std::move(componentTypes),
            py::cast<bool>(moleculeType[py::str("population")])));
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
        static const std::vector<std::string> ruleKeys = {
            "id", "name", "label", "bidirectional", "modifiers", "forward",
            "molecule_mappings", "component_mappings", "reverse",
            "driving_work",
        };
        static const std::vector<std::string> requiredRuleKeys = {
            "id", "name", "label", "bidirectional", "modifiers", "forward",
            "molecule_mappings", "component_mappings",
        };
        requireObjectKeys(rule, requiredRuleKeys, ruleKeys, "rule");
        const py::handle bidirectional = rule["bidirectional"];
        if (!PyBool_Check(bidirectional.ptr())) {
            throw std::runtime_error(
                "native BNGIR rule bidirectional flag must be a boolean");
        }
        // The keyword modifiers the compiler understands. Include/exclude
        // semantics live in direction.filters and are not modifier text.
        static const std::map<std::string, std::string> modifierNames = {
            {"delete_molecules", "DeleteMolecules"},
            {"move_connected", "MoveConnected"},
            {"match_once", "MatchOnce"},
            {"total_rate", "TotalRate"},
        };
        std::vector<std::string> modifiers;
        for (const auto& rawModifier : py::cast<py::list>(rule["modifiers"])) {
            if (!py::isinstance<py::dict>(rawModifier)) {
                throw std::runtime_error(
                    "native BNGIR rule modifier must be an object");
            }
            const auto modifier = py::cast<py::dict>(rawModifier);
            if (!modifier.contains("kind")) {
                throw std::runtime_error(
                    "native BNGIR rule modifier is missing its kind");
            }
            const auto kind = py::cast<std::string>(modifier["kind"]);
            const auto found = modifierNames.find(kind);
            if (found == modifierNames.end()) {
                throw std::runtime_error(
                    "native BNGIR rule modifier kind is not supported: " + kind);
            }
            modifiers.push_back(found->second);
        }
        if (!py::cast<bool>(bidirectional) && rule.contains("reverse")) {
            throw std::runtime_error(
                "native BNGIR rule carries a reverse direction on a forward rule");
        }
        const auto direction = py::cast<py::dict>(rule["forward"]);
        static const std::vector<std::string> directionKeys = {
            "reactants", "products", "rate", "filters", "local_scopes",
            "mutations", "transformations_complete",
        };
        requireObjectKeys(direction, directionKeys, directionKeys, "rule direction");
        const auto reactants = py::cast<py::list>(direction["reactants"]);
        const auto products = py::cast<py::list>(direction["products"]);
        if (reactants.empty() || products.empty()) {
            throw std::runtime_error(
                "native BNGIR does not support a rule direction without a "
                "reactant and product pattern");
        }
        // The local scopes a direction declares are part of the rule's
        // semantics: they bind a local function argument to a reactant.
        const auto forwardScopes = localScopesFromBngir(
            py::cast<py::list>(direction["local_scopes"]),
            reactants.size(), products.size(), "rule direction local scope");
        std::vector<ReactionRule::LocalScope> localScopes = forwardScopes;
        if (py::cast<bool>(bidirectional)) {
            // A bidirectional rule states its reverse direction. The compiler
            // materializes the reverse rule from the forward one and takes the
            // reverse rate from the second rate, so the document's reverse
            // rate is what the reverse direction must use.
            if (!rule.contains("reverse")) {
                throw std::runtime_error(
                    "native BNGIR bidirectional rule is missing its reverse direction");
            }
            const auto reverse = py::cast<py::dict>(rule["reverse"]);
            const auto reverseScopes = localScopesFromBngir(
                py::cast<py::list>(reverse["local_scopes"]),
                products.size(), reactants.size(),
                "rule reverse direction local scope");
            // The reverse direction's reactants are the forward direction's
            // products, so a scope of the reverse direction is anchored on the
            // opposite side of the forward direction.
            for (auto scope : reverseScopes) {
                scope.side = scope.side == ReactionRule::LocalScope::Side::Reactant
                                 ? ReactionRule::LocalScope::Side::Product
                                 : ReactionRule::LocalScope::Side::Reactant;
                localScopes.push_back(std::move(scope));
            }
            // Both directions of a rule share the tags of the rule, so the
            // scopes of the two directions must name the same scopes.
            const auto forwardNames = localScopeNames(forwardScopes);
            const auto reverseNames = localScopeNames(reverseScopes);
            std::vector<std::string> sortedForward = forwardNames;
            std::vector<std::string> sortedReverse = reverseNames;
            std::sort(sortedForward.begin(), sortedForward.end());
            std::sort(sortedReverse.begin(), sortedReverse.end());
            if (sortedForward != sortedReverse) {
                throw std::runtime_error(
                    "native BNGIR bidirectional rule declares different local "
                    "scopes for its two directions");
            }
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
        std::vector<std::string> filterModifiers;
        for (const auto& rawFilter :
             py::cast<py::list>(direction["filters"])) {
            filterModifiers.push_back(
                filterModifierText(py::cast<py::dict>(rawFilter)));
        }
        if (rule.contains("reverse")) {
            const auto reverse = py::cast<py::dict>(rule["reverse"]);
            for (const auto& rawFilter :
                 py::cast<py::list>(reverse["filters"])) {
                filterModifiers.push_back(
                    filterModifierText(py::cast<py::dict>(rawFilter)));
            }
        }
        // The include/exclude filters are carried as the modifier text the
        // native rule parser understands; they are the semantic content of the
        // filter, not a separate field.
        modifiers.insert(
            modifiers.end(), filterModifiers.begin(), filterModifiers.end());
        const auto rate = py::cast<py::dict>(direction["rate"]);
        // A rate may name the rule's local scopes. The compiler resolves a
        // local name before a parameter, so the rate is rebuilt in the scope
        // of the local scopes the rule declares.
        BngirScope ruleScope{&names, localScopeNames(forwardScopes), false};
        ruleScope.localScopes = !forwardScopes.empty();
        std::vector<Expression> rates;
        rates.push_back(expressionFromBngir(
            py::cast<py::dict>(rate["expression"]), ruleScope));
        if (py::cast<bool>(bidirectional)) {
            // A bidirectional rule states its reverse direction. The compiler
            // materializes the reverse rule from the forward one and takes the
            // reverse rate from the second rate, so the document's reverse
            // rate is what the reverse direction must use.
            const auto reverse = py::cast<py::dict>(rule["reverse"]);
            const auto reverseRate = py::cast<py::dict>(reverse["rate"]);
            rates.push_back(expressionFromBngir(
                py::cast<py::dict>(reverseRate["expression"]), ruleScope));
        }
        auto reactionRule = ReactionRule::fromResolvedPatterns(
            py::cast<std::string>(rule["name"]),
            py::cast<std::string>(rule["label"]),
            std::move(rates),
            std::move(reactantGraphs), std::move(productGraphs),
            std::move(modifiers), py::cast<bool>(bidirectional),
            !filterModifiers.empty());
        reactionRule.setLocalScopes(std::move(localScopes));
        // The reservoir work is part of the rule's thermodynamics. It is a
        // model-level quantity, so it is rebuilt in the model scope.
        if (rule.contains(py::str("driving_work"))) {
            reactionRule.setDrivingWorkExpression(expressionFromBngir(
                py::cast<py::dict>(rule["driving_work"]), modelScope));
        }
        model->addReactionRule(std::move(reactionRule));
    }

    // The energy patterns give a transition-state energy to the patterns they
    // match. The compiled factor takes the expression and the graph as its
    // semantic content, so the document's structured pattern is lowered the
    // same way a rule pattern is.
    for (const auto& rawEnergyPattern :
         py::cast<py::list>(document["energy_patterns"])) {
        const auto energyPattern = py::cast<py::dict>(rawEnergyPattern);
        const auto label = py::cast<std::string>(energyPattern["label"]);
        const auto pattern =
            patternFromBngir(*model, py::cast<py::dict>(energyPattern["pattern"]));
        const auto expression = expressionFromBngir(
            py::cast<py::dict>(energyPattern["expression"]), modelScope);
        model->addEnergyPattern(bng::ast::EnergyPattern(
            label, pattern.toString(), std::move(expression), std::move(pattern)));
    }

    // The barrier patterns add a transition-state energy to the reaction
    // center their transition lowers to. The transition is rebuilt from the
    // document's structured patterns, so the barrier keeps its center instead
    // of being dropped.
    const auto barrierPatterns = optionalSection(document, "barrier_patterns");
    for (std::size_t index = 0; index < barrierPatterns.size(); ++index) {
        const auto barrier = py::cast<py::dict>(barrierPatterns[index]);
        if (indexFromBngir(barrier["index"], "barrier pattern index") != index) {
            throw std::runtime_error(
                "native BNGIR barrier pattern ids must be dense and ordered");
        }
        model->addBarrierPattern(
            barrierPatternFromBngir(*model, barrier, modelScope, index));
    }

    // The population maps bind a species pattern to a population-level target
    // with a mapping rate. The compiler reads the map's pattern from its
    // pattern text, so the importer renders the document's structured pattern
    // back to that text instead of dropping the map.
    const auto populationMaps = optionalSection(document, "population_maps");
    for (std::size_t index = 0; index < populationMaps.size(); ++index) {
        const auto mapping = py::cast<py::dict>(populationMaps[index]);
        if (indexFromBngir(mapping["index"], "population map index") != index) {
            throw std::runtime_error(
                "native BNGIR population map ids must be dense and ordered");
        }
        model->addPopulationMap(
            populationMapFromBngir(*model, mapping, modelScope));
    }

    // The protocol actions are execution instructions. The native model keeps
    // them beside the model scope so a document that states an action does not
    // lose it.
    if (!protocol.is_none()) {
        const auto protocolObject = py::cast<py::dict>(protocol);
        for (const auto& rawAction :
             py::cast<py::list>(protocolObject["actions"])) {
            const auto actionObject = py::cast<py::dict>(rawAction);
            bng::ast::Action action;
            action.name = py::cast<std::string>(actionObject["name"]);
            const auto arguments = py::cast<py::dict>(actionObject["arguments"]);
            for (const auto& entry : arguments) {
                action.arguments[py::cast<std::string>(entry.first)] =
                    py::cast<std::string>(entry.second);
            }
            if (py::cast<std::string>(actionObject["scope"]) == "model") {
                model->addAction(std::move(action));
            } else {
                model->addProtocolAction(std::move(action));
            }
        }
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
               py::arg("model"), py::arg("protocol") = py::none(),
               "Build the supported BNGIR v0.2 subset directly from native structures.");
}
