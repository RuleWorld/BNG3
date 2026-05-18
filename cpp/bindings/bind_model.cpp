#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "ast/Model.hpp"
#include "ast/Parameter.hpp"
#include "ast/ParameterList.hpp"
#include "ast/Observable.hpp"
#include "ast/MoleculeType.hpp"
#include "ast/SeedSpecies.hpp"
#include "ast/ReactionRule.hpp"
#include "ast/Function.hpp"
#include "ast/Compartment.hpp"
#include "ast/EnergyPattern.hpp"
#include "ast/Expression.hpp"

namespace py = pybind11;
using namespace bng::ast;

void bind_model(py::module_& m) {

    py::class_<Expression>(m, "Expression")
        .def("__str__", &Expression::toString)
        .def("to_string", &Expression::toString);

    py::class_<Parameter>(m, "Parameter")
        .def_property_readonly("name", &Parameter::getName)
        .def_property_readonly("expression", &Parameter::getExpression,
                               py::return_value_policy::reference_internal)
        .def_property("value",
            [](const Parameter& p) -> py::object {
                if (p.hasValue()) return py::cast(p.getValue());
                return py::none();
            },
            &Parameter::setValue)
        .def("__repr__", [](const Parameter& p) {
            return "<Parameter '" + p.getName() + "'>";
        });

    py::class_<ParameterList>(m, "ParameterList")
        .def("__len__", &ParameterList::size)
        .def("__contains__", &ParameterList::contains)
        .def("__getitem__", [](const ParameterList& pl, const std::string& name) {
            return pl.get(name);
        }, py::return_value_policy::reference_internal)
        .def("all", [](const ParameterList& pl) { return pl.all(); })
        .def("evaluate_all", &ParameterList::evaluateAll, py::arg("t") = 0.0);

    py::class_<ComponentType>(m, "ComponentType")
        .def_readonly("name", &ComponentType::name)
        .def_readonly("allowed_states", &ComponentType::allowedStates);

    py::class_<MoleculeType>(m, "MoleculeType")
        .def_property_readonly("name", &MoleculeType::getName)
        .def_property_readonly("components", &MoleculeType::getComponents,
                               py::return_value_policy::reference_internal)
        .def_property_readonly("is_population", &MoleculeType::isPopulation)
        .def("__repr__", [](const MoleculeType& mt) {
            return "<MoleculeType '" + mt.getName() + "'>";
        });

    py::class_<Observable>(m, "Observable")
        .def_property_readonly("name", &Observable::getName)
        .def_property_readonly("type", &Observable::getType)
        .def_property_readonly("patterns", &Observable::getPatterns,
                               py::return_value_policy::reference_internal)
        .def("__repr__", [](const Observable& o) {
            return "<Observable '" + o.getName() + "' type='" + o.getType() + "'>";
        });

    py::class_<SeedSpecies>(m, "SeedSpecies")
        .def_property_readonly("pattern", &SeedSpecies::getPattern)
        .def_property_readonly("amount", &SeedSpecies::getAmount,
                               py::return_value_policy::reference_internal)
        .def_property_readonly("is_constant", &SeedSpecies::isConstant)
        .def_property_readonly("compartment", &SeedSpecies::getCompartment)
        .def("__repr__", [](const SeedSpecies& ss) {
            return "<SeedSpecies '" + ss.getPattern() + "'>";
        });

    py::class_<ReactionRule>(m, "ReactionRule")
        .def_property_readonly("label", &ReactionRule::getLabel)
        .def_property_readonly("is_bidirectional", &ReactionRule::isBidirectional)
        .def_property_readonly("rule_name", &ReactionRule::getRuleName)
        .def_property_readonly("reactant_patterns", [](const ReactionRule& rr) {
            std::vector<std::string> result;
            for (const auto& sg : rr.getReactantPatterns()) {
                result.push_back(sg.toString());
            }
            return result;
        })
        .def_property_readonly("product_patterns", [](const ReactionRule& rr) {
            std::vector<std::string> result;
            for (const auto& sg : rr.getProductPatterns()) {
                result.push_back(sg.toString());
            }
            return result;
        })
        .def_property_readonly("rates", [](const ReactionRule& rr) {
            std::vector<std::string> result;
            for (const auto& expr : rr.getRates()) {
                result.push_back(expr.toString());
            }
            return result;
        })
        .def_property_readonly("modifiers", &ReactionRule::getModifiers)
        .def("__repr__", [](const ReactionRule& rr) {
            std::string label = rr.getLabel();
            if (label.empty()) label = "(unnamed)";
            return "<ReactionRule '" + label + "'>";
        });

    py::class_<Function>(m, "Function")
        .def_property_readonly("name", &Function::getName)
        .def_property_readonly("args", &Function::getArgs)
        .def_property_readonly("expression", &Function::getExpression,
                               py::return_value_policy::reference_internal)
        .def("__repr__", [](const Function& f) {
            return "<Function '" + f.getName() + "'>";
        });

    py::class_<Compartment>(m, "Compartment")
        .def_property_readonly("name", &Compartment::getName)
        .def_property_readonly("dimension", &Compartment::getDimension)
        .def("__repr__", [](const Compartment& c) {
            return "<Compartment '" + c.getName() + "'>";
        });

    py::class_<Action>(m, "Action")
        .def_readonly("name", &Action::name)
        .def_readonly("arguments", &Action::arguments)
        .def("__repr__", [](const Action& a) {
            return "<Action '" + a.name + "'>";
        });

    py::class_<Model, std::unique_ptr<Model>>(m, "Model")
        .def_property_readonly("parameters", [](const Model& m) {
            return m.getParameters().all();
        })
        .def_property_readonly("parameter_list",
            py::overload_cast<>(&Model::getParameters),
            py::return_value_policy::reference_internal)
        .def_property_readonly("molecule_types", &Model::getMoleculeTypes,
                               py::return_value_policy::reference_internal)
        .def_property_readonly("seed_species", &Model::getSeedSpecies,
                               py::return_value_policy::reference_internal)
        .def_property_readonly("observables", &Model::getObservables,
                               py::return_value_policy::reference_internal)
        .def_property_readonly("reaction_rules",
            py::overload_cast<>(&Model::getReactionRules, py::const_),
            py::return_value_policy::reference_internal)
        .def_property_readonly("functions", &Model::getFunctions,
                               py::return_value_policy::reference_internal)
        .def_property_readonly("compartments",
            py::overload_cast<>(&Model::getCompartments, py::const_),
            py::return_value_policy::reference_internal)
        .def_property_readonly("actions", [](const Model& m) {
            return m.getActions();
        })
        .def_property_readonly("model_name", &Model::getModelName)
        .def_property_readonly("version", &Model::getVersion)
        .def("set_parameter", [](Model& model, const std::string& name, double value) {
            auto& params = model.getParameters();
            if (!params.contains(name)) {
                throw py::key_error("Parameter '" + name + "' not found");
            }
            // Replace the parameter with a literal-value expression so that
            // evaluateAll() picks up the new value instead of re-evaluating
            // the original parsed expression.
            params.add(Parameter(name, Expression::number(value)));
        })
        .def("get_parameter", [](const Model& m, const std::string& name) -> const Parameter& {
            return m.getParameters().get(name);
        }, py::return_value_policy::reference_internal)
        .def("__repr__", [](const Model& model) {
            std::string name = model.getModelName();
            if (name.empty()) name = "(unnamed)";
            return "<Model '" + name + "' rules=" +
                   std::to_string(model.getReactionRules().size()) +
                   " species=" + std::to_string(model.getSeedSpecies().size()) + ">";
        });
}
