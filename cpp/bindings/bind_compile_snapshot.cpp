#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "compile/CompiledModel.hpp"
#include "compile/Document.hpp"
#include "ast/Model.hpp"

#include <string>

namespace py = pybind11;

namespace {

using namespace bng::compile;

const char* expressionKindName(ResolvedExpressionKind kind) {
    switch (kind) {
    case ResolvedExpressionKind::Number: return "number";
    case ResolvedExpressionKind::ParameterRef: return "parameter_ref";
    case ResolvedExpressionKind::ObservableRef: return "observable_ref";
    case ResolvedExpressionKind::FunctionRef: return "function_ref";
    case ResolvedExpressionKind::LocalRef: return "local_ref";
    case ResolvedExpressionKind::ReactantCountRef: return "reactant_count_ref";
    case ResolvedExpressionKind::TimeRef: return "time_ref";
    case ResolvedExpressionKind::Unary: return "unary";
    case ResolvedExpressionKind::Binary: return "binary";
    case ResolvedExpressionKind::BuiltinCall: return "builtin_call";
    case ResolvedExpressionKind::TableFunction: return "table_function";
    case ResolvedExpressionKind::Unresolved: return "unresolved";
    }
    return "unresolved";
}

const char* unaryName(UnaryOp op) {
    switch (op) {
    case UnaryOp::Plus: return "plus";
    case UnaryOp::Negate: return "negate";
    case UnaryOp::LogicalNot: return "not";
    case UnaryOp::Unknown: return "unknown";
    }
    return "unknown";
}

const char* binaryName(BinaryOp op) {
    switch (op) {
    case BinaryOp::Add: return "add";
    case BinaryOp::Subtract: return "subtract";
    case BinaryOp::Multiply: return "multiply";
    case BinaryOp::Divide: return "divide";
    case BinaryOp::Power: return "power";
    case BinaryOp::Less: return "less";
    case BinaryOp::LessEqual: return "less_equal";
    case BinaryOp::Greater: return "greater";
    case BinaryOp::GreaterEqual: return "greater_equal";
    case BinaryOp::Equal: return "equal";
    case BinaryOp::NotEqual: return "not_equal";
    case BinaryOp::LogicalAnd: return "and";
    case BinaryOp::LogicalOr: return "or";
    case BinaryOp::Unknown: return "unknown";
    }
    return "unknown";
}

const char* builtinName(BuiltinFunction builtin) {
    switch (builtin) {
    case BuiltinFunction::Abs: return "abs";
    case BuiltinFunction::Acos: return "acos";
    case BuiltinFunction::Acosh: return "acosh";
    case BuiltinFunction::Asin: return "asin";
    case BuiltinFunction::Asinh: return "asinh";
    case BuiltinFunction::Atan: return "atan";
    case BuiltinFunction::Atanh: return "atanh";
    case BuiltinFunction::Avg: return "avg";
    case BuiltinFunction::Ceil: return "ceil";
    case BuiltinFunction::Cos: return "cos";
    case BuiltinFunction::Cosh: return "cosh";
    case BuiltinFunction::E: return "e";
    case BuiltinFunction::Exp: return "exp";
    case BuiltinFunction::Factorial: return "factorial";
    case BuiltinFunction::Floor: return "floor";
    case BuiltinFunction::If: return "if";
    case BuiltinFunction::Ln: return "ln";
    case BuiltinFunction::Log10: return "log10";
    case BuiltinFunction::Log2: return "log2";
    case BuiltinFunction::Max: return "max";
    case BuiltinFunction::Min: return "min";
    case BuiltinFunction::MRatio: return "mratio";
    case BuiltinFunction::Pi: return "pi";
    case BuiltinFunction::Rint: return "rint";
    case BuiltinFunction::Sin: return "sin";
    case BuiltinFunction::Sinh: return "sinh";
    case BuiltinFunction::Sqrt: return "sqrt";
    case BuiltinFunction::Sum: return "sum";
    case BuiltinFunction::Tan: return "tan";
    case BuiltinFunction::Tanh: return "tanh";
    case BuiltinFunction::Time: return "time";
    case BuiltinFunction::Arrhenius: return "arrhenius";
    case BuiltinFunction::Saturation: return "saturation";
    case BuiltinFunction::MichaelisMenten: return "michaelis_menten";
    case BuiltinFunction::Hill: return "hill";
    case BuiltinFunction::FunctionProduct: return "function_product";
    case BuiltinFunction::Hybrid: return "hybrid";
    case BuiltinFunction::TableFunction: return "table_function";
    case BuiltinFunction::Unknown: return "unknown";
    }
    return "unknown";
}

const char* symbolKindName(SymbolKind kind) {
    switch (kind) {
    case SymbolKind::Parameter: return "parameter";
    case SymbolKind::Function: return "function";
    case SymbolKind::MoleculeType: return "molecule_type";
    case SymbolKind::Observable: return "observable";
    case SymbolKind::Compartment: return "compartment";
    case SymbolKind::ReactionRule: return "reaction_rule";
    case SymbolKind::EnergyPattern: return "energy_pattern";
    case SymbolKind::BarrierPattern: return "barrier_pattern";
    case SymbolKind::PopulationType: return "population_type";
    case SymbolKind::Count: return "invalid";
    }
    return "invalid";
}

py::dict expressionSnapshot(const ResolvedExpression& expression) {
    py::dict result;
    result["kind"] = expressionKindName(expression.kind);
    if (expression.kind == ResolvedExpressionKind::Number) {
        result["value"] = expression.numberValue;
    }
    if (expression.symbol.has_value()) {
        py::dict symbol;
        symbol["kind"] = symbolKindName(expression.symbol->kind);
        symbol["index"] = expression.symbol->index;
        result["symbol"] = std::move(symbol);
    }
    if (!expression.localName.empty()) result["name"] = expression.localName;
    if (expression.kind == ResolvedExpressionKind::ReactantCountRef)
        result["reactant_index"] = expression.reactantIndex;
    if ((expression.kind == ResolvedExpressionKind::FunctionRef ||
         expression.kind == ResolvedExpressionKind::ObservableRef) &&
        !expression.operation.empty()) {
        result["call"] = true;
    }
    if (expression.unaryOp.has_value()) result["operator"] = unaryName(*expression.unaryOp);
    if (expression.binaryOp.has_value()) result["operator"] = binaryName(*expression.binaryOp);
    if (expression.builtin.has_value()) result["builtin"] = builtinName(*expression.builtin);
    py::list arguments;
    for (const auto& argument : expression.arguments)
        arguments.append(expressionSnapshot(argument));
    if (!expression.arguments.empty()) result["arguments"] = std::move(arguments);
    if (expression.kind == ResolvedExpressionKind::TableFunction) {
        result["x"] = expression.tableX;
        result["y"] = expression.tableY;
        result["file"] = expression.tableFile;
        result["method"] = expression.tableMethod;
    }
    // Retained only for unresolved diagnostics. A valid compiled model should
    // not need this field to reconstruct semantic expressions.
    if (expression.kind == ResolvedExpressionKind::Unresolved && !expression.source.empty())
        result["unresolved_source"] = expression.source;
    return result;
}

const char* stateConstraintName(StateConstraintKind kind) {
    switch (kind) {
    case StateConstraintKind::Any: return "any";
    case StateConstraintKind::Exact: return "exact";
    case StateConstraintKind::Set: return "set";
    }
    return "any";
}

const char* bondConstraintName(BondConstraintKind kind) {
    switch (kind) {
    case BondConstraintKind::Unspecified: return "unspecified";
    case BondConstraintKind::Unbound: return "unbound";
    case BondConstraintKind::Bound: return "bound";
    case BondConstraintKind::Any: return "any";
    case BondConstraintKind::Exact: return "exact";
    }
    return "unspecified";
}

py::dict patternSnapshot(const Pattern& pattern, const CompiledModel& model) {
    py::dict result;
    if (!pattern.compartment().empty()) result["compartment"] = pattern.compartment();
    result["compartment_prefix"] = pattern.compartmentIsPrefix();
    py::list molecules;
    for (const auto& molecule : pattern.molecules()) {
        py::dict mol;
        mol["occurrence"] = molecule.occurrence.value;
        mol["type"] = molecule.moleculeType;
        if (molecule.moleculeTypeId.has_value()) mol["type_id"] = molecule.moleculeTypeId->value();
        if (!molecule.compartment.empty()) mol["compartment"] = molecule.compartment;
        if (molecule.compartmentId.has_value()) mol["compartment_id"] = molecule.compartmentId->value();
        py::list sites;
        for (const auto& site : molecule.sites) {
            py::dict item;
            item["occurrence"] = site.occurrence.value;
            item["component"] = site.componentName;
            if (site.componentType.has_value()) item["component_index"] = site.componentType->index;
            if (!site.label.empty()) item["label"] = site.label;

            py::dict state;
            state["kind"] = stateConstraintName(site.stateConstraintResolved.kind);
            if (site.stateConstraintResolved.exact.has_value()) {
                if (const auto* name = model.stateName(*site.stateConstraintResolved.exact))
                    state["value"] = *name;
                state["index"] = site.stateConstraintResolved.exact->index;
            }
            if (!site.stateConstraintResolved.states.empty()) {
                py::list values;
                py::list indices;
                for (const auto stateId : site.stateConstraintResolved.states) {
                    if (const auto* name = model.stateName(stateId)) values.append(*name);
                    indices.append(stateId.index);
                }
                state["values"] = std::move(values);
                state["indices"] = std::move(indices);
            }
            item["state"] = std::move(state);

            py::dict bond;
            bond["kind"] = bondConstraintName(site.bondKind);
            if (site.bondKind == BondConstraintKind::Exact) bond["group"] = site.bondGroup.value;
            if (site.bondConstraints.size() > 1) {
                py::list alternatives;
                for (const auto& descriptor : site.bondConstraints) {
                    py::dict entry;
                    entry["kind"] = bondConstraintName(descriptor.kind);
                    if (descriptor.kind == BondConstraintKind::Exact) entry["group"] = descriptor.group.value;
                    alternatives.append(std::move(entry));
                }
                bond["alternatives"] = std::move(alternatives);
            }
            item["bond"] = std::move(bond);
            sites.append(std::move(item));
        }
        mol["sites"] = std::move(sites);
        molecules.append(std::move(mol));
    }
    result["molecules"] = std::move(molecules);
    return result;
}

const char* mutationName(MutationKind kind) {
    switch (kind) {
    case MutationKind::AddBond: return "add_bond";
    case MutationKind::DeleteBond: return "delete_bond";
    case MutationKind::ChangeState: return "change_state";
    case MutationKind::AddMolecule: return "add_molecule";
    case MutationKind::DeleteMolecule: return "delete_molecule";
    }
    return "unknown";
}

const char* modifierName(ModifierKind kind) {
    switch (kind) {
    case ModifierKind::DeleteMolecules: return "delete_molecules";
    case ModifierKind::MoveConnected: return "move_connected";
    case ModifierKind::MatchOnce: return "match_once";
    case ModifierKind::TotalRate: return "total_rate";
    case ModifierKind::IncludeReactants: return "include_reactants";
    case ModifierKind::ExcludeReactants: return "exclude_reactants";
    case ModifierKind::IncludeProducts: return "include_products";
    case ModifierKind::ExcludeProducts: return "exclude_products";
    case ModifierKind::Unknown: return "unknown";
    }
    return "unknown";
}

py::dict moleculeRefSnapshot(const PatternMoleculeRef& ref) {
    py::dict result;
    result["side"] = ref.side == PatternSide::Reactant ? "reactant" : "product";
    result["pattern"] = ref.patternIndex;
    result["molecule"] = ref.moleculeIndex;
    return result;
}

py::dict siteRefSnapshot(const PatternSiteRef& ref) {
    py::dict result = moleculeRefSnapshot(PatternMoleculeRef{ref.side, ref.patternIndex, ref.moleculeIndex});
    result["site"] = ref.siteIndex;
    return result;
}

py::dict directionSnapshot(const CompiledRuleDirection& direction,
                           const CompiledModel& model) {
    py::dict result;
    py::list reactants;
    for (const auto& pattern : direction.reactantPatterns)
        reactants.append(patternSnapshot(pattern, model));
    py::list products;
    for (const auto& pattern : direction.productPatterns)
        products.append(patternSnapshot(pattern, model));
    result["reactants"] = std::move(reactants);
    result["products"] = std::move(products);
    result["transformations_complete"] = direction.transformationsComplete;
    if (direction.rateLaw.has_value()) {
        py::dict rate;
        rate["kind"] = static_cast<int>(direction.rateLaw->kind);
        rate["expression"] = expressionSnapshot(direction.rateLaw->resolvedExpression());
        if (!direction.rateLaw->unitName.empty()) rate["unit"] = direction.rateLaw->unitName;
        if (direction.rateLaw->unit.has_value())
            rate["resolved_unit"] = bng::units::formatUnit(*direction.rateLaw->unit);
        result["rate"] = std::move(rate);
    }
    py::list mutations;
    for (const auto& mutation : direction.mutations) {
        py::dict item;
        item["kind"] = mutationName(mutation.kind);
        if (mutation.kind == MutationKind::AddMolecule || mutation.kind == MutationKind::DeleteMolecule) {
            item["molecule"] = moleculeRefSnapshot(mutation.molecule);
        } else {
            item["source"] = siteRefSnapshot(mutation.source);
            if (mutation.kind == MutationKind::AddBond || mutation.kind == MutationKind::DeleteBond)
                item["partner"] = siteRefSnapshot(mutation.partner);
            if (mutation.kind == MutationKind::ChangeState) {
                item["state"] = mutation.newState;
                if (mutation.newStateId.has_value()) item["state_index"] = mutation.newStateId->index;
            }
        }
        mutations.append(std::move(item));
    }
    result["mutations"] = std::move(mutations);

    py::list filters;
    for (const auto& filter : direction.filters) {
        py::dict item;
        item["include"] = filter.include;
        item["side"] = filter.products ? "product" : "reactant";
        item["pattern_index"] = filter.patternIndex;
        py::list patterns;
        for (const auto& pattern : filter.patterns)
            patterns.append(patternSnapshot(pattern, model));
        item["patterns"] = std::move(patterns);
        filters.append(std::move(item));
    }
    result["filters"] = std::move(filters);

    py::list localScopes;
    for (const auto& scope : direction.localScopes) {
        py::dict item;
        item["name"] = scope.name;
        item["kind"] = scope.kind == LocalScopeKind::Species ? "species" : "molecule";
        item["reactant_pattern"] = scope.reactantPatternIndex;
        if (scope.moleculeOccurrence.has_value())
            item["molecule_occurrence"] = *scope.moleculeOccurrence;
        localScopes.append(std::move(item));
    }
    result["local_scopes"] = std::move(localScopes);
    return result;
}

py::dict compiledSnapshot(const bng::ast::Model& astModel) {
    Document document(astModel);
    const auto& model = document.model();
    if (!document.valid()) {
        throw std::runtime_error("cannot create structural semantic snapshot from invalid model");
    }

    py::dict root;
    py::dict metadata;
    metadata["name"] = model.metadata().name;
    metadata["version"] = model.metadata().version;
    metadata["substance_units"] = model.metadata().substanceUnits;
    metadata["options"] = model.metadata().options;
    if (!model.metadata().unitDefaults.empty()) {
        metadata["unit_defaults"] = model.metadata().unitDefaults;
    }
    if (!model.metadata().unitDefinitions.empty()) {
        py::list unitDefinitions;
        for (const auto& definition : model.metadata().unitDefinitions) {
            py::dict item;
            item["id"] = definition.id;
            item["expression"] = definition.expression;
            item["builtin"] = definition.builtin;
            item["unit"] = bng::units::formatUnit(definition.unit);
            item["factor"] = definition.unit.factor;
            unitDefinitions.append(std::move(item));
        }
        metadata["unit_definitions"] = std::move(unitDefinitions);
    }
    root["metadata"] = std::move(metadata);

    py::list parameters;
    for (const auto& parameter : model.parameters()) {
        py::dict item;
        item["id"] = parameter.id.value();
        item["name"] = parameter.name;
        item["expression"] = expressionSnapshot(parameter.expression);
        if (parameter.constantValue.has_value()) item["constant_value"] = *parameter.constantValue;
        if (!parameter.unitName.empty()) item["unit"] = parameter.unitName;
        if (parameter.declaredUnit.has_value())
            item["declared_unit"] = bng::units::formatUnit(*parameter.declaredUnit);
        if (parameter.inferredUnit.has_value())
            item["inferred_unit"] = bng::units::formatUnit(*parameter.inferredUnit);
        if (parameter.normalizedValue.has_value()) item["normalized_value"] = *parameter.normalizedValue;
        parameters.append(std::move(item));
    }
    root["parameters"] = std::move(parameters);

    py::list moleculeTypes;
    for (const auto& molecule : model.moleculeTypes()) {
        py::dict item;
        item["id"] = molecule.id.value();
        item["name"] = molecule.name;
        item["population"] = molecule.population;
        py::list components;
        for (const auto& component : molecule.components) {
            py::dict componentItem;
            componentItem["index"] = component.id.index;
            componentItem["name"] = component.name;
            componentItem["states"] = component.stateNames;
            components.append(std::move(componentItem));
        }
        item["components"] = std::move(components);
        moleculeTypes.append(std::move(item));
    }
    root["molecule_types"] = std::move(moleculeTypes);

    py::list compartments;
    for (const auto& compartment : model.compartments()) {
        py::dict item;
        item["id"] = compartment.id.value();
        item["name"] = compartment.name;
        item["dimension"] = compartment.dimension;
        item["volume"] = compartment.volume;
        if (!compartment.unitName.empty()) item["unit"] = compartment.unitName;
        if (compartment.declaredUnit.has_value())
            item["declared_unit"] = bng::units::formatUnit(*compartment.declaredUnit);
        if (compartment.normalizedVolume.has_value()) item["normalized_volume"] = *compartment.normalizedVolume;
        if (compartment.parent.has_value()) item["parent_id"] = compartment.parent->value();
        if (!compartment.parentName.empty()) item["parent"] = compartment.parentName;
        compartments.append(std::move(item));
    }
    root["compartments"] = std::move(compartments);

    py::list seeds;
    for (const auto& seed : model.seeds()) {
        py::dict item;
        item["id"] = seed.id.value();
        item["pattern"] = patternSnapshot(seed.pattern, model);
        item["amount"] = expressionSnapshot(seed.amount);
        item["constant"] = seed.constant;
        if (!seed.unitName.empty()) item["unit"] = seed.unitName;
        if (seed.declaredUnit.has_value())
            item["declared_unit"] = bng::units::formatUnit(*seed.declaredUnit);
        if (seed.normalizedAmount.has_value()) item["normalized_amount"] = *seed.normalizedAmount;
        if (!seed.compartment.empty()) item["compartment"] = seed.compartment;
        seeds.append(std::move(item));
    }
    root["seeds"] = std::move(seeds);

    py::list observables;
    for (const auto& observable : model.observables()) {
        py::dict item;
        item["id"] = observable.id.value();
        item["name"] = observable.name;
        item["kind"] = observable.kind == ObservableKind::Molecules ? "molecules" :
                       observable.kind == ObservableKind::Species ? "species" : "unknown";
        py::list terms;
        for (const auto& term : observable.terms) {
            py::dict termItem;
            termItem["pattern"] = patternSnapshot(term.pattern, model);
            if (!term.relation.empty()) termItem["relation"] = term.relation;
            termItem["quantity"] = term.quantity;
            terms.append(std::move(termItem));
        }
        item["terms"] = std::move(terms);
        observables.append(std::move(item));
    }
    root["observables"] = std::move(observables);

    py::list functions;
    for (const auto& function : model.functions()) {
        py::dict item;
        item["id"] = function.id.value();
        item["name"] = function.name;
        item["arguments"] = function.arguments;
        item["expression"] = expressionSnapshot(function.expression);
        functions.append(std::move(item));
    }
    root["functions"] = std::move(functions);

    py::list energyPatterns;
    for (const auto& factor : model.energyFactors()) {
        py::dict item;
        item["id"] = factor.id.value();
        item["label"] = factor.label;
        item["pattern"] = patternSnapshot(factor.pattern, model);
        item["expression"] = expressionSnapshot(factor.expression);
        energyPatterns.append(std::move(item));
    }
    root["energy_patterns"] = std::move(energyPatterns);

    // Barrier factors are reported separately from energy factors: they carry a
    // reaction-center key instead of a pattern, and centerResolved=false must
    // stay visible so a consumer can tell a rejected barrier from an absent one.
    py::list barrierPatterns;
    for (const auto& barrier : model.barrierFactors()) {
        py::dict item;
        item["index"] = barrier.index;
        item["label"] = barrier.label;
        item["transition"] = barrier.sourceTransition;
        item["expression"] = barrier.energyExpression;
        item["reaction_center"] = barrier.reactionCenterKey;
        item["center_resolved"] = barrier.centerResolved;
        if (barrier.evaluatedValue.has_value()) {
            item["value"] = *barrier.evaluatedValue;
        } else {
            item["value"] = py::none();
        }
        barrierPatterns.append(std::move(item));
    }
    root["barrier_patterns"] = std::move(barrierPatterns);

    py::list populationTypes;
    for (const auto& type : model.populationTypes()) {
        py::dict item;
        item["id"] = type.id.value();
        item["name"] = type.name;
        populationTypes.append(std::move(item));
    }
    root["population_types"] = std::move(populationTypes);

    py::list populationMaps;
    for (const auto& mapping : model.populationMaps()) {
        py::dict item;
        item["index"] = mapping.index;
        item["label"] = mapping.label;
        item["pattern"] = patternSnapshot(mapping.pattern, model);
        item["population"] = mapping.populationName;
        if (mapping.population.has_value()) item["population_id"] = mapping.population->value();
        item["arguments"] = mapping.populationArguments;
        item["rate"] = expressionSnapshot(mapping.rate);
        populationMaps.append(std::move(item));
    }
    root["population_maps"] = std::move(populationMaps);

    py::list rules;
    for (const auto& rule : model.rules()) {
        py::dict item;
        item["id"] = rule.id().value();
        item["name"] = rule.name();
        item["label"] = rule.label();
        item["bidirectional"] = rule.isBidirectional();
        item["forward"] = directionSnapshot(rule.forward(), model);
        if (rule.reverse().has_value()) item["reverse"] = directionSnapshot(*rule.reverse(), model);
        py::list modifiers;
        for (const auto& modifier : rule.modifiers()) {
            py::dict modifierItem;
            modifierItem["kind"] = modifierName(modifier.kind);
            // Unknown modifiers cannot be represented structurally; retain their
            // text only as fail-closed diagnostic provenance.
            if (modifier.kind == ModifierKind::Unknown) modifierItem["unresolved_source"] = modifier.source;
            modifiers.append(std::move(modifierItem));
        }
        item["modifiers"] = std::move(modifiers);

        py::list moleculeMappings;
        for (const auto& [product, reactant] : rule.moleculeMappings()) {
            py::dict mapping;
            mapping["product"] = moleculeRefSnapshot(product);
            mapping["reactant"] = moleculeRefSnapshot(reactant);
            moleculeMappings.append(std::move(mapping));
        }
        item["molecule_mappings"] = std::move(moleculeMappings);

        py::list componentMappings;
        for (const auto& [product, reactant] : rule.componentMappings()) {
            py::dict mapping;
            mapping["product"] = siteRefSnapshot(product);
            mapping["reactant"] = siteRefSnapshot(reactant);
            componentMappings.append(std::move(mapping));
        }
        item["component_mappings"] = std::move(componentMappings);
        rules.append(std::move(item));
    }
    root["rules"] = std::move(rules);

    py::list actions;
    for (const auto& action : document.protocol().actions) {
        py::dict item;
        item["scope"] = action.scope == ActionScope::Model ? "model" : "simulation_protocol";
        item["name"] = action.name;
        item["arguments"] = action.arguments;
        actions.append(std::move(item));
    }
    root["actions"] = std::move(actions);
    return root;
}

} // namespace

void bind_compile_snapshot(py::module_& m) {
    m.def("_compiled_snapshot", &compiledSnapshot,
          py::arg("model"),
          "Return the resolved, backend-independent BioNetGen semantic model as Python values.");
}
