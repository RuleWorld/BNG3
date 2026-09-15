#include "NFinput_fromCompiled.hh"

#include "compile/CompiledModel.hpp"
#include "NFcore/NFcore.hh"
#include "NFcore/compartment.hh"
#include "NFcore2/nfsim_pattern_lowering.hh"
#include "NFinput_energy.hh"
#include "NFfunction/NFfunction.hh"
#include "NFreactions/reactions/reaction.hh"
#include "NFreactions/transformations/moleculeCreator.hh"
#include "NFreactions/transformations/transformation.hh"
#include "NFreactions/transformations/transformationSet.hh"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace NFinput {
namespace {

using bng::compile::BinaryOp;
using bng::compile::BondConstraintKind;
using bng::compile::CompiledFilter;
using bng::compile::CompiledModel;
using bng::compile::CompiledRule;
using bng::compile::CompiledRuleDirection;
using bng::compile::ModifierKind;
using bng::compile::MutationKind;
using bng::compile::Pattern;
using bng::compile::PatternMoleculeRef;
using bng::compile::PatternSide;
using bng::compile::PatternSiteRef;
using bng::compile::ResolvedExpression;
using bng::compile::ResolvedExpressionKind;
using bng::compile::UnaryOp;

bool hasModifier(const CompiledRule& rule, ModifierKind kind) {
    return std::any_of(rule.modifiers().begin(), rule.modifiers().end(),
                       [&](const auto& modifier) { return modifier.kind == kind; });
}

const Pattern* referencedPattern(const CompiledRuleDirection& direction,
                                 PatternSide side,
                                 std::size_t patternIndex) {
    const auto& patterns = side == PatternSide::Reactant
                               ? direction.reactantPatterns
                               : direction.productPatterns;
    return patternIndex < patterns.size() ? &patterns[patternIndex] : nullptr;
}

const bng::compile::PatternMoleculeDescriptor* referencedMolecule(
    const CompiledRuleDirection& direction, const PatternMoleculeRef& ref) {
    const auto* pattern = referencedPattern(direction, ref.side, ref.patternIndex);
    if (pattern == nullptr || ref.moleculeIndex >= pattern->molecules().size()) return nullptr;
    return &pattern->molecules()[ref.moleculeIndex];
}

const bng::compile::PatternSiteDescriptor* referencedSite(
    const CompiledRuleDirection& direction, const PatternSiteRef& ref) {
    const auto* molecule = referencedMolecule(
        direction, PatternMoleculeRef{ref.side, ref.patternIndex, ref.moleculeIndex});
    if (molecule == nullptr || ref.siteIndex >= molecule->sites.size()) return nullptr;
    return &molecule->sites[ref.siteIndex];
}

std::string runtimeComponentName(const CompiledModel& model,
                                 bng::compile::ComponentTypeId id) {
    const auto* molecule = model.moleculeType(id.moleculeType);
    const auto* component = model.component(id);
    if (molecule == nullptr || component == nullptr) return {};
    std::size_t total = 0;
    std::size_t ordinal = 0;
    for (std::size_t index = 0; index < molecule->components.size(); ++index) {
        if (molecule->components[index].name != component->name) continue;
        ++total;
        if (index <= id.index) ordinal = total;
    }
    if (total <= 1) return component->name;
    return component->name + std::to_string(ordinal);
}

bool isSymmetricComponent(const CompiledModel& model,
                          bng::compile::ComponentTypeId id) {
    const auto* molecule = model.moleculeType(id.moleculeType);
    const auto* component = model.component(id);
    if (molecule == nullptr || component == nullptr) return false;
    return std::count_if(molecule->components.begin(), molecule->components.end(),
                         [&](const auto& candidate) {
                             return candidate.name == component->name;
                         }) > 1;
}

std::vector<std::string> equivalentRuntimeNames(
    const CompiledModel& model, bng::compile::ComponentTypeId id) {
    const auto* molecule = model.moleculeType(id.moleculeType);
    const auto* component = model.component(id);
    if (molecule == nullptr || component == nullptr) return {};

    std::size_t count = 0;
    for (const auto& candidate : molecule->components) {
        if (candidate.name == component->name) ++count;
    }
    if (count <= 1) return {component->name};

    std::vector<std::string> names;
    names.reserve(count);
    for (std::size_t ordinal = 1; ordinal <= count; ++ordinal) {
        names.push_back(component->name + std::to_string(ordinal));
    }
    return names;
}

std::string compartmentName(const CompiledModel& model,
                            const Pattern& pattern,
                            const bng::compile::PatternMoleculeDescriptor& molecule) {
    if (!molecule.compartment.empty()) return molecule.compartment;
    if (molecule.compartmentId.has_value()) {
        if (const auto* declaration = model.compartment(*molecule.compartmentId))
            return declaration->name;
    }
    if (!pattern.compartment().empty()) return pattern.compartment();
    if (pattern.compartmentId().has_value()) {
        if (const auto* declaration = model.compartment(*pattern.compartmentId()))
            return declaration->name;
    }
    return {};
}

NFcore::Compartment* resolveCompartment(NFcore::System& system,
                                        const std::string& name,
                                        std::string& diagnostic) {
    if (name.empty()) return nullptr;
    auto* compartment = system.getCompartment(name);
    if (compartment == nullptr) diagnostic = "unknown compartment '" + name + "'";
    return compartment;
}

std::optional<double> evaluateStatic(const CompiledModel& model,
                                     const ResolvedExpression& expression,
                                     std::unordered_set<std::size_t>& activeFunctions,
                                     std::string& diagnostic);

std::optional<double> evaluateBuiltin(const CompiledModel& model,
                                      const ResolvedExpression& expression,
                                      std::unordered_set<std::size_t>& activeFunctions,
                                      std::string& diagnostic) {
    using Fn = bng::compile::BuiltinFunction;
    if (!expression.builtin.has_value()) return std::nullopt;
    std::vector<double> args;
    for (const auto& argument : expression.arguments) {
        const auto value = evaluateStatic(model, argument, activeFunctions, diagnostic);
        if (!value.has_value()) return std::nullopt;
        args.push_back(*value);
    }
    const auto unary = [&](auto fn) -> std::optional<double> {
        return args.size() == 1 ? std::optional<double>(fn(args[0])) : std::nullopt;
    };
    switch (*expression.builtin) {
    case Fn::Abs: return unary([](double x) { return std::fabs(x); });
    case Fn::Acos: return unary([](double x) { return std::acos(x); });
    case Fn::Acosh: return unary([](double x) { return std::acosh(x); });
    case Fn::Asin: return unary([](double x) { return std::asin(x); });
    case Fn::Asinh: return unary([](double x) { return std::asinh(x); });
    case Fn::Atan: return unary([](double x) { return std::atan(x); });
    case Fn::Atanh: return unary([](double x) { return std::atanh(x); });
    case Fn::Ceil: return unary([](double x) { return std::ceil(x); });
    case Fn::Cos: return unary([](double x) { return std::cos(x); });
    case Fn::Cosh: return unary([](double x) { return std::cosh(x); });
    case Fn::Exp: return unary([](double x) { return std::exp(x); });
    case Fn::Floor: return unary([](double x) { return std::floor(x); });
    case Fn::Ln: return unary([](double x) { return std::log(x); });
    case Fn::Log10: return unary([](double x) { return std::log10(x); });
    case Fn::Log2: return unary([](double x) { return std::log2(x); });
    case Fn::Rint: return unary([](double x) { return std::rint(x); });
    case Fn::Sin: return unary([](double x) { return std::sin(x); });
    case Fn::Sinh: return unary([](double x) { return std::sinh(x); });
    case Fn::Sqrt: return unary([](double x) { return std::sqrt(x); });
    case Fn::Tan: return unary([](double x) { return std::tan(x); });
    case Fn::Tanh: return unary([](double x) { return std::tanh(x); });
    case Fn::Min:
        if (args.empty()) return std::nullopt;
        return *std::min_element(args.begin(), args.end());
    case Fn::Max:
        if (args.empty()) return std::nullopt;
        return *std::max_element(args.begin(), args.end());
    case Fn::Sum: {
        double total = 0.0;
        for (const auto value : args) total += value;
        return total;
    }
    case Fn::Avg: {
        if (args.empty()) return std::nullopt;
        double total = 0.0;
        for (const auto value : args) total += value;
        return total / static_cast<double>(args.size());
    }
    case Fn::If:
        return args.size() == 3 ? std::optional<double>(args[0] != 0.0 ? args[1] : args[2])
                                : std::nullopt;
    case Fn::E: return 2.71828182845904523536;
    case Fn::Pi: return 3.14159265358979323846;
    default:
        diagnostic = "rate expression requires runtime or specialized builtin evaluation";
        return std::nullopt;
    }
}

std::optional<double> evaluateStatic(const CompiledModel& model,
                                     const ResolvedExpression& expression,
                                     std::unordered_set<std::size_t>& activeFunctions,
                                     std::string& diagnostic) {
    switch (expression.kind) {
    case ResolvedExpressionKind::Number:
        return std::isfinite(expression.numberValue)
                   ? std::optional<double>(expression.numberValue) : std::nullopt;
    case ResolvedExpressionKind::ParameterRef: {
        if (!expression.symbol.has_value()) return std::nullopt;
        const auto* parameter = model.parameter(
            bng::compile::ParameterId::fromDenseIndex(expression.symbol->index));
        return parameter == nullptr ? std::nullopt : parameter->constantValue;
    }
    case ResolvedExpressionKind::FunctionRef: {
        if (!expression.symbol.has_value() || !expression.arguments.empty()) return std::nullopt;
        const auto index = expression.symbol->index;
        if (!activeFunctions.insert(index).second) {
            diagnostic = "cyclic model function in static rate";
            return std::nullopt;
        }
        const auto* function = model.function(
            bng::compile::FunctionId::fromDenseIndex(index));
        const auto value = function == nullptr
                               ? std::optional<double>{}
                               : evaluateStatic(model, function->expression,
                                                activeFunctions, diagnostic);
        activeFunctions.erase(index);
        return value;
    }
    case ResolvedExpressionKind::Unary: {
        if (!expression.unaryOp.has_value() || expression.arguments.size() != 1)
            return std::nullopt;
        const auto value = evaluateStatic(model, expression.arguments[0],
                                          activeFunctions, diagnostic);
        if (!value.has_value()) return std::nullopt;
        switch (*expression.unaryOp) {
        case UnaryOp::Plus: return *value;
        case UnaryOp::Negate: return -*value;
        case UnaryOp::LogicalNot: return *value == 0.0 ? 1.0 : 0.0;
        case UnaryOp::Unknown: return std::nullopt;
        }
        return std::nullopt;
    }
    case ResolvedExpressionKind::Binary: {
        if (!expression.binaryOp.has_value() || expression.arguments.size() != 2)
            return std::nullopt;
        const auto lhs = evaluateStatic(model, expression.arguments[0],
                                        activeFunctions, diagnostic);
        const auto rhs = evaluateStatic(model, expression.arguments[1],
                                        activeFunctions, diagnostic);
        if (!lhs.has_value() || !rhs.has_value()) return std::nullopt;
        switch (*expression.binaryOp) {
        case BinaryOp::Add: return *lhs + *rhs;
        case BinaryOp::Subtract: return *lhs - *rhs;
        case BinaryOp::Multiply: return *lhs * *rhs;
        case BinaryOp::Divide: return *rhs == 0.0 ? std::nullopt : std::optional<double>(*lhs / *rhs);
        case BinaryOp::Power: return std::pow(*lhs, *rhs);
        case BinaryOp::Less: return *lhs < *rhs ? 1.0 : 0.0;
        case BinaryOp::LessEqual: return *lhs <= *rhs ? 1.0 : 0.0;
        case BinaryOp::Greater: return *lhs > *rhs ? 1.0 : 0.0;
        case BinaryOp::GreaterEqual: return *lhs >= *rhs ? 1.0 : 0.0;
        case BinaryOp::Equal: return *lhs == *rhs ? 1.0 : 0.0;
        case BinaryOp::NotEqual: return *lhs != *rhs ? 1.0 : 0.0;
        case BinaryOp::LogicalAnd: return (*lhs != 0.0 && *rhs != 0.0) ? 1.0 : 0.0;
        case BinaryOp::LogicalOr: return (*lhs != 0.0 || *rhs != 0.0) ? 1.0 : 0.0;
        case BinaryOp::Unknown: return std::nullopt;
        }
        return std::nullopt;
    }
    case ResolvedExpressionKind::BuiltinCall:
        return evaluateBuiltin(model, expression, activeFunctions, diagnostic);
    case ResolvedExpressionKind::ObservableRef:
    case ResolvedExpressionKind::LocalRef:
    case ResolvedExpressionKind::ReactantCountRef:
    case ResolvedExpressionKind::TimeRef:
    case ResolvedExpressionKind::TableFunction:
    case ResolvedExpressionKind::Unresolved:
        return std::nullopt;
    }
    return std::nullopt;
}

std::optional<double> evaluateStatic(const CompiledModel& model,
                                     const ResolvedExpression& expression,
                                     std::string& diagnostic) {
    std::unordered_set<std::size_t> active;
    const auto value = evaluateStatic(model, expression, active, diagnostic);
    if (value.has_value() && !std::isfinite(*value)) return std::nullopt;
    return value;
}

struct DirectProductMolecule {
    NFcore::TemplateMolecule* templateMolecule = nullptr;
    NFcore::MoleculeCreator* creator = nullptr;
    std::vector<std::string> runtimeComponentNames;
};

bool buildDirectProductMolecule(const CompiledModel& model,
                                const Pattern& pattern,
                                std::size_t moleculeIndex,
                                NFcore::System& system,
                                DirectProductMolecule& result,
                                std::string& diagnostic) {
    if (moleculeIndex >= pattern.molecules().size()) {
        diagnostic = "AddMolecule refers to an unknown product molecule";
        return false;
    }
    const auto& molecule = pattern.molecules()[moleculeIndex];
    if (!molecule.moleculeTypeId.has_value()) {
        diagnostic = "product molecule has no resolved molecule-type ID";
        return false;
    }
    const auto* declaration = model.moleculeType(*molecule.moleculeTypeId);
    if (declaration == nullptr) {
        diagnostic = "product molecule type ID is invalid";
        return false;
    }
    const std::string lowerName = [&]() {
        std::string value = declaration->name;
        std::transform(value.begin(), value.end(), value.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return value;
    }();
    if (lowerName == "null" || lowerName == "trash") return true;

    auto* moleculeType = system.getMoleculeTypeByName(declaration->name);
    if (moleculeType == nullptr || moleculeType->isPopulationType()) {
        diagnostic = "product molecule type cannot be materialized directly";
        return false;
    }
    auto* templateMolecule = new NFcore::TemplateMolecule(moleculeType);
    const auto compName = compartmentName(model, pattern, molecule);
    auto* compartment = resolveCompartment(system, compName, diagnostic);
    if (!compName.empty() && compartment == nullptr) {
        delete templateMolecule;
        return false;
    }
    templateMolecule->setCompartment(compartment);
    for (int component = 0; component < moleculeType->getNumOfComponents(); ++component)
        templateMolecule->addEmptyComponent(moleculeType->getComponentName(component));

    std::vector<std::pair<int, int>> componentStates;
    result.runtimeComponentNames.reserve(molecule.sites.size());
    for (const auto& site : molecule.sites) {
        if (!site.componentType.has_value()) {
            diagnostic = "product site has no resolved component-type ID";
            delete templateMolecule;
            return false;
        }
        const auto runtimeName = runtimeComponentName(model, *site.componentType);
        if (runtimeName.empty()) {
            diagnostic = "product site cannot be mapped to an NFsim component";
            delete templateMolecule;
            return false;
        }
        result.runtimeComponentNames.push_back(runtimeName);
        if (site.stateConstraintResolved.kind == bng::compile::StateConstraintKind::Set) {
            diagnostic = "new product molecule has a state-set constraint";
            delete templateMolecule;
            return false;
        }
        if (site.stateConstraintResolved.kind == bng::compile::StateConstraintKind::Exact) {
            if (!site.stateConstraintResolved.exact.has_value()) {
                diagnostic = "product state constraint is unresolved";
                delete templateMolecule;
                return false;
            }
            const auto* state = model.stateName(*site.stateConstraintResolved.exact);
            if (state == nullptr) {
                diagnostic = "product state ID is invalid";
                delete templateMolecule;
                return false;
            }
            try {
                const int componentIndex = moleculeType->getCompIndexFromName(runtimeName);
                const int stateValue = moleculeType->getStateValueFromName(componentIndex, *state);
                componentStates.emplace_back(componentIndex, stateValue);
                templateMolecule->addComponentConstraint(runtimeName, stateValue);
            } catch (const std::exception& error) {
                diagnostic = error.what();
                delete templateMolecule;
                return false;
            }
        }
        if (site.bondKind == BondConstraintKind::Bound ||
            site.bondKind == BondConstraintKind::Any) {
            diagnostic = "new product molecule has a non-concrete bond constraint";
            delete templateMolecule;
            return false;
        }
    }
    result.templateMolecule = templateMolecule;
    result.creator = new NFcore::MoleculeCreator(templateMolecule, moleculeType,
                                                  componentStates, compartment);
    return true;
}

struct MoleculeRefLess {
    bool operator()(const PatternMoleculeRef& a, const PatternMoleculeRef& b) const noexcept {
        if (a.side != b.side) return a.side < b.side;
        if (a.patternIndex != b.patternIndex) return a.patternIndex < b.patternIndex;
        return a.moleculeIndex < b.moleculeIndex;
    }
};
using MoleculeMap = std::map<PatternMoleculeRef, PatternMoleculeRef, MoleculeRefLess>;
using SiteMap = std::map<PatternSiteRef, PatternSiteRef>;

void directionMappings(const CompiledRule& rule, bool reverse,
                       MoleculeMap& molecules, SiteMap& sites) {
    molecules.clear();
    sites.clear();
    if (!reverse) {
        for (const auto& mapping : rule.moleculeMappings()) molecules.emplace(mapping);
        for (const auto& mapping : rule.componentMappings()) sites.emplace(mapping);
        return;
    }
    for (const auto& [product, reactant] : rule.moleculeMappings()) {
        molecules.emplace(
            PatternMoleculeRef{PatternSide::Product, reactant.patternIndex, reactant.moleculeIndex},
            PatternMoleculeRef{PatternSide::Reactant, product.patternIndex, product.moleculeIndex});
    }
    for (const auto& [product, reactant] : rule.componentMappings()) {
        sites.emplace(
            PatternSiteRef{PatternSide::Product, reactant.patternIndex,
                           reactant.moleculeIndex, reactant.siteIndex},
            PatternSiteRef{PatternSide::Reactant, product.patternIndex,
                           product.moleculeIndex, product.siteIndex});
    }
}

bool templateForRef(const PatternMoleculeRef& ref,
                    const std::vector<std::vector<NFcore::TemplateMolecule*>>& templates,
                    NFcore::TemplateMolecule*& result,
                    std::string& diagnostic) {
    if (ref.side != PatternSide::Reactant || ref.patternIndex >= templates.size() ||
        ref.moleculeIndex >= templates[ref.patternIndex].size()) {
        diagnostic = "reaction mapping refers outside reactant templates";
        return false;
    }
    result = templates[ref.patternIndex][ref.moleculeIndex];
    return result != nullptr;
}

bool componentForRef(const CompiledModel& model,
                     const CompiledRuleDirection& direction,
                     const PatternSiteRef& ref,
                     const std::vector<std::vector<NFcore::TemplateMolecule*>>& templates,
                     NFcore::TemplateMolecule*& molecule,
                     std::string& component,
                     std::string& diagnostic) {
    if (ref.side != PatternSide::Reactant) {
        diagnostic = "transformation endpoint is not on the reactant side";
        return false;
    }
    const auto* site = referencedSite(direction, ref);
    if (site == nullptr || !site->componentType.has_value()) {
        diagnostic = "transformation endpoint has no resolved component";
        return false;
    }
    if (isSymmetricComponent(model, *site->componentType)) {
        diagnostic = "symmetric reaction-center component requires permutation lowering";
        return false;
    }
    component = runtimeComponentName(model, *site->componentType);
    return !component.empty() && templateForRef(
        PatternMoleculeRef{PatternSide::Reactant, ref.patternIndex, ref.moleculeIndex},
        templates, molecule, diagnostic);
}

bool addFilters(const CompiledRuleDirection& direction,
                NFcore::System& system,
                NFcore::TransformationSet& transformations,
                const std::vector<NFcore::TemplateMolecule*>& roots,
                bool& hasDisjointSets,
                int& suggestedTraversalLimit,
                std::string& diagnostic) {
    std::size_t ordinal = 0;
    for (const auto& filter : direction.filters) {
        if (filter.products) {
            if (filter.patternIndex >= direction.productPatterns.size()) {
                diagnostic = "product filter pattern index is out of range";
                return false;
            }
            const auto& product = direction.productPatterns[filter.patternIndex];
            for (const auto& wanted : filter.patterns) {
                if (wanted.molecules().size() != 1 ||
                    !wanted.molecules().front().sites.empty()) {
                    diagnostic = "NFsim direct product filters support one bare molecule";
                    return false;
                }
                const auto& type = wanted.molecules().front().moleculeType;
                const bool contains = std::any_of(
                    product.molecules().begin(), product.molecules().end(),
                    [&](const auto& molecule) { return molecule.moleculeType == type; });
                if ((filter.include && !contains) || (!filter.include && contains)) {
                    // The rule is statically filtered out. Use a distinctive
                    // diagnostic understood by the caller as a non-error skip.
                    diagnostic = "__BNG_STATIC_PRODUCT_FILTER_REJECT__";
                    return false;
                }
            }
            continue;
        }
        if (filter.patternIndex >= roots.size()) {
            diagnostic = "reactant filter pattern index is out of range";
            return false;
        }
        for (const auto& filterPattern : filter.patterns) {
            std::vector<NFcore::TemplateMolecule*> templates;
            bool disjoint = false;
            if (!NFcore2::lowerPatternToNFsim(filterPattern, system, templates,
                                              disjoint, suggestedTraversalLimit,
                                              diagnostic) || templates.empty()) {
                return false;
            }
            std::map<std::string, NFcore::TemplateMolecule*> named;
            for (std::size_t index = 0; index < templates.size(); ++index)
                named.emplace("filter_" + std::to_string(ordinal) + "_M" +
                                  std::to_string(index + 1), templates[index]);
            if (filter.include)
                transformations.addIncludeReactant(
                    static_cast<int>(filter.patternIndex), templates.front(), named);
            else
                transformations.addExcludeReactant(
                    static_cast<int>(filter.patternIndex), templates.front(), named);
            hasDisjointSets = hasDisjointSets || disjoint;
            ++ordinal;
        }
    }
    return true;
}

struct ProductBondEndpoint {
    PatternSiteRef ref;
    const bng::compile::PatternSiteDescriptor* site = nullptr;
};

std::map<std::pair<std::size_t, std::size_t>, std::vector<ProductBondEndpoint>>
productBondGroups(const CompiledRuleDirection& direction) {
    std::map<std::pair<std::size_t, std::size_t>, std::vector<ProductBondEndpoint>> result;
    for (std::size_t patternIndex = 0; patternIndex < direction.productPatterns.size(); ++patternIndex) {
        const auto& pattern = direction.productPatterns[patternIndex];
        for (std::size_t moleculeIndex = 0; moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
            const auto& molecule = pattern.molecules()[moleculeIndex];
            for (std::size_t siteIndex = 0; siteIndex < molecule.sites.size(); ++siteIndex) {
                const auto& site = molecule.sites[siteIndex];
                const auto collect = [&](const bng::compile::PatternBondDescriptor& bond) {
                    if (bond.kind != BondConstraintKind::Exact || bond.group.value == 0) return;
                    result[{patternIndex, bond.group.value}].push_back(
                        ProductBondEndpoint{
                            PatternSiteRef{PatternSide::Product, patternIndex,
                                           moleculeIndex, siteIndex}, &site});
                };
                if (site.bondConstraints.empty())
                    collect({site.bondConstraint, site.bondKind, site.bondGroup});
                else
                    for (const auto& bond : site.bondConstraints) collect(bond);
            }
        }
    }
    return result;
}

bool renderExpression(const CompiledModel& model,
                      const ResolvedExpression& expression,
                      std::string& result,
                      std::set<std::string>& parameters,
                      std::set<std::string>& observables,
                      std::set<std::string>& functions,
                      std::set<std::string>& localNames,
                      bool& usesTime,
                      std::string& diagnostic) {
    const auto child = [&](const ResolvedExpression& value, std::string& text) {
        return renderExpression(model, value, text, parameters, observables,
                                functions, localNames, usesTime, diagnostic);
    };
    switch (expression.kind) {
    case ResolvedExpressionKind::Number: {
        std::ostringstream output; output.precision(17); output << expression.numberValue;
        result = output.str(); return true;
    }
    case ResolvedExpressionKind::ParameterRef: {
        if (!expression.symbol.has_value()) return false;
        const auto* parameter = model.parameter(
            bng::compile::ParameterId::fromDenseIndex(expression.symbol->index));
        if (parameter == nullptr) return false;
        parameters.insert(parameter->name); result = parameter->name; return true;
    }
    case ResolvedExpressionKind::ObservableRef: {
        if (!expression.symbol.has_value()) return false;
        const auto* observable = model.observable(
            bng::compile::ObservableId::fromDenseIndex(expression.symbol->index));
        if (observable == nullptr || !expression.arguments.empty()) return false;
        observables.insert(observable->name); result = observable->name; return true;
    }
    case ResolvedExpressionKind::FunctionRef: {
        if (!expression.symbol.has_value()) return false;
        const auto* function = model.function(
            bng::compile::FunctionId::fromDenseIndex(expression.symbol->index));
        if (function == nullptr) return false;
        functions.insert(function->name);
        result = function->name;
        if (!expression.arguments.empty()) {
            result += '(';
            for (std::size_t index = 0; index < expression.arguments.size(); ++index) {
                if (index != 0) result += ',';
                std::string arg;
                if (!child(expression.arguments[index], arg)) return false;
                result += arg;
            }
            result += ')';
        } else {
            result += "()";
        }
        return true;
    }
    case ResolvedExpressionKind::LocalRef:
        localNames.insert(expression.localName); result = expression.localName; return true;
    case ResolvedExpressionKind::ReactantCountRef:
        result = "reactant_" + std::to_string(expression.reactantIndex + 1);
        functions.insert(result); return true;
    case ResolvedExpressionKind::TimeRef:
        usesTime = true; result = "time"; return true;
    case ResolvedExpressionKind::Unary: {
        if (!expression.unaryOp.has_value() || expression.arguments.size() != 1) return false;
        std::string arg; if (!child(expression.arguments[0], arg)) return false;
        const char* op = *expression.unaryOp == UnaryOp::Plus ? "+" :
                         *expression.unaryOp == UnaryOp::Negate ? "-" :
                         *expression.unaryOp == UnaryOp::LogicalNot ? "!" : nullptr;
        if (op == nullptr) return false; result = std::string(op) + arg; return true;
    }
    case ResolvedExpressionKind::Binary: {
        if (!expression.binaryOp.has_value() || expression.arguments.size() != 2) return false;
        std::string lhs, rhs; if (!child(expression.arguments[0], lhs) || !child(expression.arguments[1], rhs)) return false;
        const char* op = nullptr;
        switch (*expression.binaryOp) {
        case BinaryOp::Add: op = "+"; break; case BinaryOp::Subtract: op = "-"; break;
        case BinaryOp::Multiply: op = "*"; break; case BinaryOp::Divide: op = "/"; break;
        case BinaryOp::Power: op = "^"; break; case BinaryOp::Less: op = "<"; break;
        case BinaryOp::LessEqual: op = "<="; break; case BinaryOp::Greater: op = ">"; break;
        case BinaryOp::GreaterEqual: op = ">="; break; case BinaryOp::Equal: op = "=="; break;
        case BinaryOp::NotEqual: op = "!="; break; case BinaryOp::LogicalAnd: op = "&&"; break;
        case BinaryOp::LogicalOr: op = "||"; break; case BinaryOp::Unknown: break;
        }
        if (op == nullptr) return false; result = "(" + lhs + " " + op + " " + rhs + ")"; return true;
    }
    case ResolvedExpressionKind::BuiltinCall: {
        if (!expression.builtin.has_value()) return false;
        using Fn = bng::compile::BuiltinFunction;
        const char* name = nullptr;
        switch (*expression.builtin) {
        case Fn::Abs: name="abs"; break; case Fn::Acos: name="acos"; break;
        case Fn::Acosh: name="acosh"; break; case Fn::Asin: name="asin"; break;
        case Fn::Asinh: name="asinh"; break; case Fn::Atan: name="atan"; break;
        case Fn::Atanh: name="atanh"; break; case Fn::Ceil: name="ceil"; break;
        case Fn::Cos: name="cos"; break; case Fn::Cosh: name="cosh"; break;
        case Fn::Exp: name="exp"; break; case Fn::Floor: name="floor"; break;
        case Fn::If: name="if"; break; case Fn::Ln: name="ln"; break;
        case Fn::Log10: name="log10"; break; case Fn::Log2: name="log2"; break;
        case Fn::Max: name="max"; break; case Fn::Min: name="min"; break;
        case Fn::Rint: name="rint"; break; case Fn::Sin: name="sin"; break;
        case Fn::Sinh: name="sinh"; break; case Fn::Sqrt: name="sqrt"; break;
        case Fn::Sum: name="sum"; break; case Fn::Tan: name="tan"; break;
        case Fn::Tanh: name="tanh"; break;
        case Fn::Time:
            // The legacy NFsim parser accepts time() at the source boundary,
            // but the live runtime binding is a variable named time.
            usesTime = true;
            result = "time";
            return true;
        default: diagnostic = "specialized rate builtin cannot be rendered as a generic function"; return false;
        }
        result = std::string(name) + '(';
        for (std::size_t index = 0; index < expression.arguments.size(); ++index) {
            if (index != 0) result += ',';
            std::string arg; if (!child(expression.arguments[index], arg)) return false; result += arg;
        }
        result += ')'; return true;
    }
    case ResolvedExpressionKind::TableFunction:
        result = "__TFUN_VAL__";
        return true;
    case ResolvedExpressionKind::Unresolved:
        diagnostic = "unresolved expression requires the compatibility backend";
        return false;
    }
    return false;
}

void collectTableFunctions(
    const ResolvedExpression& expression,
    std::vector<const ResolvedExpression*>& tables) {
    if (expression.kind == ResolvedExpressionKind::TableFunction)
        tables.push_back(&expression);
    for (const auto& argument : expression.arguments)
        collectTableFunctions(argument, tables);
}

bool tableCounterUsesTime(const ResolvedExpression& table) {
    return table.kind == ResolvedExpressionKind::TableFunction &&
           table.arguments.size() == 1 &&
           table.arguments.front().kind == ResolvedExpressionKind::TimeRef;
}

std::string replaceNamedReferences(
    const std::string& expression,
    const std::map<std::string, std::string>& replacements) {
    if (replacements.empty()) return expression;

    std::string result;
    result.reserve(expression.size());
    std::size_t index = 0;
    while (index < expression.size()) {
        const unsigned char first = static_cast<unsigned char>(expression[index]);
        if (!std::isalpha(first) && expression[index] != '_') {
            result.push_back(expression[index++]);
            continue;
        }

        const std::size_t start = index++;
        while (index < expression.size()) {
            const unsigned char current = static_cast<unsigned char>(expression[index]);
            if (!std::isalnum(current) && expression[index] != '_') break;
            ++index;
        }
        const std::string token = expression.substr(start, index - start);
        const auto replacement = replacements.find(token);
        if (replacement == replacements.end()) {
            result.append(expression, start, index - start);
            continue;
        }

        std::size_t lookahead = index;
        while (lookahead < expression.size() &&
               std::isspace(static_cast<unsigned char>(expression[lookahead]))) {
            ++lookahead;
        }
        if (lookahead < expression.size() && expression[lookahead] == '(') {
            std::size_t close = lookahead + 1;
            while (close < expression.size() &&
                   std::isspace(static_cast<unsigned char>(expression[close]))) {
                ++close;
            }
            if (close < expression.size() && expression[close] == ')') {
                result += replacement->second;
                result += "()";
                index = close + 1;
                continue;
            }
        }
        result += replacement->second;
    }
    return result;
}

bool addDynamicGlobalRate(const CompiledModel& model,
                          const ResolvedExpression& expression,
                          NFcore::System& system,
                          const std::string& name,
                          NFcore::GlobalFunction*& global,
                          std::string& diagnostic) {
    std::string text;
    std::set<std::string> parameters, observables, functions, localNames;
    bool usesTime = false;
    if (!renderExpression(model, expression, text, parameters, observables,
                          functions, localNames, usesTime, diagnostic) ||
        !localNames.empty() || !functions.empty()) return false;
    std::vector<std::string> refs(observables.begin(), observables.end());
    std::vector<std::string> refTypes(refs.size(), "Observable");
    std::vector<std::string> parameterNames(parameters.begin(), parameters.end());
    global = new NFcore::GlobalFunction(name, text, refs, refTypes, parameterNames, &system);
    if (!system.addGlobalFunction(global)) { delete global; global = nullptr; return false; }
    if (usesTime) {
        global->setCounterFromTime(&system);
        system.setHasTimeDependentFunctions(true);
    }
    return true;
}


struct LocalRateOperand {
    const bng::compile::CompiledFunction* function = nullptr;
    std::string argument;
    const bng::compile::CompiledLocalScope* scope = nullptr;
};

bool localRateOperand(const CompiledModel& model,
                      const CompiledRuleDirection& direction,
                      const ResolvedExpression& expression,
                      LocalRateOperand& operand) {
    if (expression.kind != ResolvedExpressionKind::FunctionRef ||
        !expression.symbol.has_value() || expression.arguments.size() != 1 ||
        expression.arguments.front().kind != ResolvedExpressionKind::LocalRef) {
        return false;
    }
    const auto* function = model.function(
        bng::compile::FunctionId::fromDenseIndex(expression.symbol->index));
    if (function == nullptr || function->arguments.size() != 1) return false;
    const auto& argument = expression.arguments.front().localName;
    const auto* scope = direction.findLocalScope(argument);
    if (scope == nullptr) return false;
    operand = LocalRateOperand{function, argument, scope};
    return true;
}

bool addLocalRateReference(const LocalRateOperand& operand,
                           const std::vector<NFcore::TemplateMolecule*>& roots,
                           NFcore::TransformationSet& transformations,
                           std::string& diagnostic) {
    if (operand.scope == nullptr || operand.scope->reactantPatternIndex >= roots.size()) {
        diagnostic = "local-function scope is outside the reactant list";
        return false;
    }
    auto* root = roots[operand.scope->reactantPatternIndex];
    if (root == nullptr || root->getMoleculeType()->isPopulationType()) {
        diagnostic = "local functions cannot scope population reactants";
        return false;
    }
    const int scope = operand.scope->kind == bng::compile::LocalScopeKind::Species
                          ? NFcore::LocalFunction::SPECIES
                          : NFcore::LocalFunction::MOLECULE;
    if (!transformations.addLocalFunctionReference(root, operand.argument, scope)) {
        diagnostic = "could not add local-function scope reference";
        return false;
    }
    return true;
}

bool addLocalScopeReferences(
    const CompiledRuleDirection& direction,
    const std::set<std::string>& localNames,
    const std::vector<NFcore::TemplateMolecule*>& roots,
    NFcore::TransformationSet& transformations,
    std::vector<std::string>& argumentNames,
    std::string& diagnostic) {
    argumentNames.clear();
    std::optional<std::size_t> commonPattern;
    for (const auto& name : localNames) {
        const auto* scope = direction.findLocalScope(name);
        if (scope == nullptr || scope->reactantPatternIndex >= roots.size()) {
            diagnostic = "local-function scope identifier '" + name +
                         "' has no matching compiled reactant";
            return false;
        }
        if (commonPattern.has_value() && *commonPattern != scope->reactantPatternIndex) {
            diagnostic = "local-function scope identifiers must refer to one reactant";
            return false;
        }
        commonPattern = scope->reactantPatternIndex;
        auto* root = roots[scope->reactantPatternIndex];
        if (root == nullptr || root->getMoleculeType()->isPopulationType()) {
            diagnostic = "local functions cannot scope population reactants";
            return false;
        }
        const int nfScope = scope->kind == bng::compile::LocalScopeKind::Species
                                ? NFcore::LocalFunction::SPECIES
                                : NFcore::LocalFunction::MOLECULE;
        if (!transformations.addLocalFunctionReference(root, name, nfScope)) {
            diagnostic = "could not add local-function scope reference '" + name + "'";
            return false;
        }
        argumentNames.push_back(name);
    }
    return true;
}

bool isReactantCountFunctionName(const std::string& name) {
    return name.size() == 10 && name.compare(0, 9, "reactant_") == 0 &&
           name.back() >= '1' && name.back() <= '9';
}

bool addDynamicCompiledRateFunction(
    const CompiledModel& model,
    const CompiledRuleDirection& direction,
    const ResolvedExpression& expression,
    NFcore::System& system,
    const std::filesystem::path& sourcePath,
    std::size_t ordinal,
    NFcore::TransformationSet& transformations,
    const std::vector<NFcore::TemplateMolecule*>& roots,
    NFcore::GlobalFunction*& global,
    NFcore::CompositeFunction*& composite,
    std::vector<std::string>& localArguments,
    std::string& diagnostic) {
    global = nullptr;
    composite = nullptr;
    localArguments.clear();

    std::string text;
    std::set<std::string> parameters, observables, functions, localNames;
    bool usesTime = false;
    if (!renderExpression(model, expression, text, parameters, observables,
                          functions, localNames, usesTime, diagnostic)) {
        return false;
    }

    std::vector<const ResolvedExpression*> tables;
    collectTableFunctions(expression, tables);
    if (tables.size() > 1) {
        diagnostic = "dynamic reaction rates support at most one TFUN expression";
        return false;
    }
    if (usesTime && !tables.empty() && !tableCounterUsesTime(*tables.front())) {
        diagnostic = "dynamic reaction rates cannot combine a non-time TFUN counter "
                     "with a time-dependent expression";
        return false;
    }
    if (!usesTime && observables.empty() && functions.empty() && localNames.empty() &&
        tables.empty()) {
        diagnostic = "rate expression is not a supported dynamic function";
        return false;
    }

    // Keep the generated names identical to the direct AST adapter's public
    // NFsim contract.  Callers and the XML bridge both use these names when
    // inspecting or wrapping reaction-owned rate functions.
    std::string name = "__bng3_reaction_rate_" + std::to_string(ordinal + 1);
    std::size_t suffix = 1;
    while (system.getGlobalFunctionByName(name) != nullptr ||
           system.getCompositeFunctionByName(name) != nullptr ||
           system.getLocalFunctionByName(name) != nullptr) {
        name = "__bng3_reaction_rate_" + std::to_string(ordinal + 1) +
               "_" + std::to_string(suffix++);
    }

    std::vector<std::string> parameterNames(parameters.begin(), parameters.end());
    const bool needsComposite = !functions.empty() || !localNames.empty();
    if (!needsComposite) {
        std::vector<std::string> refs(observables.begin(), observables.end());
        std::vector<std::string> refTypes(refs.size(), "Observable");
        auto candidate = std::make_unique<NFcore::GlobalFunction>(
            name, text, refs, refTypes, parameterNames, &system);
        if (!tables.empty() &&
            !NFinput::configureTableFunctionFromCompiled(
                model, *tables.front(), sourcePath, &system,
                candidate.get(), nullptr, nullptr, diagnostic)) {
            return false;
        }
        if (!system.addGlobalFunction(candidate.get())) {
            diagnostic = "failed to register generated compiled reaction-rate global";
            return false;
        }
        global = candidate.release();
        if (usesTime && tables.empty()) {
            global->setCounterFromTime(&system);
            system.setHasTimeDependentFunctions(true);
        }
        return true;
    }

    for (const auto& dependency : functions) {
        if (isReactantCountFunctionName(dependency)) continue;
        if (system.getGlobalFunctionByName(dependency) == nullptr &&
            system.getLocalFunctionByName(dependency) == nullptr &&
            system.getCompositeFunctionByName(dependency) == nullptr) {
            diagnostic = "dynamic reaction rate refers to an unavailable function '" +
                         dependency + "'";
            return false;
        }
    }
    if (!addLocalScopeReferences(direction, localNames, roots, transformations,
                                 localArguments, diagnostic)) {
        return false;
    }

    // CompositeFunction cannot bind observables directly.  Mirror the native
    // NFsim adapter by generating zero-argument GlobalFunction aliases, then
    // rewrite the semantic expression to call those aliases instead.
    std::map<std::string, std::string> observableAliases;
    std::size_t aliasIndex = 1;
    for (const auto& observableName : observables) {
        std::string aliasName = "__bng3_reaction_observable_" +
                                std::to_string(ordinal + 1) + "_" +
                                std::to_string(aliasIndex++);
        std::size_t aliasSuffix = 1;
        while (system.getGlobalFunctionByName(aliasName) != nullptr ||
               system.getCompositeFunctionByName(aliasName) != nullptr ||
               system.getLocalFunctionByName(aliasName) != nullptr) {
            aliasName = "__bng3_reaction_observable_" +
                        std::to_string(ordinal + 1) + "_" +
                        std::to_string(aliasIndex - 1) + "_" +
                        std::to_string(aliasSuffix++);
        }
        std::vector<std::string> refs{observableName};
        std::vector<std::string> refTypes{"Observable"};
        std::vector<std::string> noParameters;
        auto* alias = new NFcore::GlobalFunction(
            aliasName, observableName, refs, refTypes, noParameters, &system);
        if (!system.addGlobalFunction(alias)) {
            delete alias;
            diagnostic = "failed to register generated compiled observable alias '" +
                         aliasName + "'";
            return false;
        }
        observableAliases.emplace(observableName, std::move(aliasName));
    }

    std::vector<std::string> functionsCalled(functions.begin(), functions.end());
    for (const auto& [observableName, aliasName] : observableAliases) {
        (void)observableName;
        functionsCalled.push_back(aliasName);
    }
    const auto compositeExpression = replaceNamedReferences(text, observableAliases);
    auto candidate = std::make_unique<NFcore::CompositeFunction>(
        &system, name, compositeExpression, functionsCalled,
        localArguments, parameterNames);
    if (!tables.empty() &&
        !NFinput::configureTableFunctionFromCompiled(
            model, *tables.front(), sourcePath, &system,
            nullptr, candidate.get(), nullptr, diagnostic)) {
        return false;
    }
    if (!system.addCompositeFunction(candidate.get())) {
        diagnostic = "failed to register generated compiled reaction-rate composite";
        return false;
    }
    composite = candidate.release();
    composite->finalizeInitialization(&system);
    if (usesTime && tables.empty()) {
        composite->setCounterFromTime(&system);
        system.setHasTimeDependentFunctions(true);
    }
    return true;
}

struct ScopedCompositeRate {
    std::string expression;
    std::vector<std::string> functionNames;
    std::vector<std::string> argumentNames;
    std::vector<std::string> parameterNames;
    std::vector<LocalRateOperand> localOperands;
    bool usesTime = false;
};

bool collectScopedRateOperands(
    const CompiledModel& model,
    const CompiledRuleDirection& direction,
    const ResolvedExpression& expression,
    std::map<std::string, LocalRateOperand>& locals,
    std::set<std::string>& globals,
    std::string& diagnostic) {
    if (expression.kind == ResolvedExpressionKind::FunctionRef) {
        if (!expression.symbol.has_value()) {
            diagnostic = "function rate reference has no resolved symbol";
            return false;
        }
        const auto* function = model.function(
            bng::compile::FunctionId::fromDenseIndex(expression.symbol->index));
        if (function == nullptr) {
            diagnostic = "function rate reference does not resolve to a compiled function";
            return false;
        }
        if (function->arguments.empty()) {
            if (!expression.arguments.empty()) {
                diagnostic = "zero-argument model function was called with arguments";
                return false;
            }
            globals.insert(function->name);
            return true;
        }
        LocalRateOperand operand;
        if (!localRateOperand(model, direction, expression, operand)) {
            diagnostic = "mapping-local rate functions must be one-argument calls on a declared local scope";
            return false;
        }
        const auto found = locals.find(operand.argument);
        if (found != locals.end() &&
            found->second.scope->reactantPatternIndex != operand.scope->reactantPatternIndex) {
            diagnostic = "local pointer name resolves to more than one reactant";
            return false;
        }
        locals.emplace(operand.argument, operand);
        return true;
    }
    if (expression.kind == ResolvedExpressionKind::LocalRef) {
        diagnostic = "bare local-scope names are not valid rate values";
        return false;
    }
    if (expression.kind == ResolvedExpressionKind::TableFunction ||
        expression.kind == ResolvedExpressionKind::Unresolved) {
        diagnostic = "table/unresolved rate expression requires compatibility lowering";
        return false;
    }
    for (const auto& child : expression.arguments) {
        if (!collectScopedRateOperands(model, direction, child, locals, globals, diagnostic))
            return false;
    }
    return true;
}

bool prepareScopedCompositeRate(const CompiledModel& model,
                                const CompiledRuleDirection& direction,
                                const ResolvedExpression& expression,
                                NFcore::System& system,
                                ScopedCompositeRate& rate,
                                std::string& diagnostic) {
    std::set<std::string> parameters, observables, functions, localNames;
    bool usesTime = false;
    if (!renderExpression(model, expression, rate.expression, parameters, observables,
                          functions, localNames, usesTime, diagnostic)) {
        return false;
    }
    if (!observables.empty()) {
        diagnostic = "rates mixing mapping-local functions with direct observable references require compatibility lowering";
        return false;
    }

    std::map<std::string, LocalRateOperand> locals;
    std::set<std::string> globals;
    if (!collectScopedRateOperands(model, direction, expression, locals, globals, diagnostic))
        return false;
    if (locals.empty()) return false;

    std::optional<std::size_t> dorReactant;
    for (const auto& [argument, operand] : locals) {
        (void)argument;
        if (operand.scope == nullptr) return false;
        if (!dorReactant.has_value()) dorReactant = operand.scope->reactantPatternIndex;
        else if (*dorReactant != operand.scope->reactantPatternIndex) {
            diagnostic = "NFsim generic DOR rates can reference local functions on only one reactant";
            return false;
        }
        if (system.getLocalFunctionByName(operand.function->name) == nullptr) {
            diagnostic = "compiled scoped rate refers to an unregistered local function '" +
                         operand.function->name + "'";
            return false;
        }
        rate.localOperands.push_back(operand);
        rate.argumentNames.push_back(operand.argument);
    }
    for (const auto& name : globals) {
        if (system.getGlobalFunctionByName(name) == nullptr) {
            diagnostic = "compiled scoped rate refers to a non-global zero-argument function '" + name + "'";
            return false;
        }
        rate.functionNames.push_back(name);
    }
    for (const auto& operand : rate.localOperands)
        rate.functionNames.push_back(operand.function->name);
    std::sort(rate.functionNames.begin(), rate.functionNames.end());
    rate.functionNames.erase(std::unique(rate.functionNames.begin(), rate.functionNames.end()),
                             rate.functionNames.end());
    rate.parameterNames.assign(parameters.begin(), parameters.end());
    rate.usesTime = usesTime;
    return true;
}

bool functionProductOperands(const CompiledModel& model,
                             const CompiledRuleDirection& direction,
                             const ResolvedExpression& expression,
                             LocalRateOperand& first,
                             LocalRateOperand& second) {
    const bool explicitProduct =
        expression.kind == ResolvedExpressionKind::BuiltinCall &&
        expression.builtin.has_value() &&
        *expression.builtin == bng::compile::BuiltinFunction::FunctionProduct;
    const bool rawProduct =
        expression.kind == ResolvedExpressionKind::Binary &&
        expression.binaryOp.has_value() && *expression.binaryOp == BinaryOp::Multiply;
    if ((!explicitProduct && !rawProduct) || expression.arguments.size() != 2) return false;
    return localRateOperand(model, direction, expression.arguments[0], first) &&
           localRateOperand(model, direction, expression.arguments[1], second);
}

bool addCompiledArrheniusDirection(const CompiledModel& model,
                                   const CompiledRule& rule,
                                   const CompiledRuleDirection& direction,
                                   NFcore::System& system,
                                   bool blockSameComplexBinding,
                                   bool verbose,
                                   int& suggestedTraversalLimit,
                                   std::string& diagnostic) {
    if (!direction.rateLaw.has_value() ||
        direction.rateLaw->kind != bng::compile::RateLawKind::ArrheniusEnergy) {
        return false;
    }
    if (!direction.filters.empty()) {
        diagnostic = "Arrhenius rules with include/exclude filters require compatibility lowering";
        return false;
    }
    for (const auto& modifier : rule.modifiers()) {
        if (modifier.kind != ModifierKind::TotalRate &&
            modifier.kind != ModifierKind::MatchOnce) {
            diagnostic = "Arrhenius rule uses a modifier unsupported by structural energy lowering";
            return false;
        }
    }
    const auto& expression = direction.rateLaw->resolvedExpression();
    if (expression.arguments.size() != 2) {
        diagnostic = "Arrhenius requires phi and activation-energy arguments";
        return false;
    }
    const auto phi = evaluateStatic(model, expression.arguments[0], diagnostic);
    const auto activationEnergy = evaluateStatic(model, expression.arguments[1], diagnostic);
    if (!phi.has_value() || !activationEnergy.has_value()) {
        if (diagnostic.empty()) diagnostic = "Arrhenius arguments are not statically resolvable";
        return false;
    }
    if (system.getEnergyFunction() == nullptr) {
        diagnostic = "Arrhenius reaction requires compiled energy patterns";
        return false;
    }
    if (direction.mutations.size() != 1) {
        diagnostic = "compiled Arrhenius lowering supports one reaction-center edit";
        return false;
    }

    const std::size_t firstReaction = system.getAllReactions().size();
    int reactionCount = 0;
    bool ok = false;
    const auto& mutation = direction.mutations.front();
    if (mutation.kind == MutationKind::AddBond) {
        if (direction.reactantPatterns.size() != 2 ||
            direction.reactantPatterns[0].molecules().size() != 1 ||
            direction.reactantPatterns[1].molecules().size() != 1 ||
            mutation.source.side != PatternSide::Reactant ||
            mutation.partner.side != PatternSide::Reactant) {
            diagnostic = "Arrhenius binding requires two one-molecule reactants";
            return false;
        }
        const auto* lhsMol = referencedMolecule(
            direction, PatternMoleculeRef{PatternSide::Reactant,
                                          mutation.source.patternIndex,
                                          mutation.source.moleculeIndex});
        const auto* rhsMol = referencedMolecule(
            direction, PatternMoleculeRef{PatternSide::Reactant,
                                          mutation.partner.patternIndex,
                                          mutation.partner.moleculeIndex});
        const auto* lhsSite = referencedSite(direction, mutation.source);
        const auto* rhsSite = referencedSite(direction, mutation.partner);
        if (lhsMol == nullptr || rhsMol == nullptr || lhsSite == nullptr || rhsSite == nullptr ||
            !lhsMol->moleculeTypeId.has_value() || !rhsMol->moleculeTypeId.has_value() ||
            !lhsSite->componentType.has_value() || !rhsSite->componentType.has_value()) {
            diagnostic = "Arrhenius binding has unresolved typed reaction-center references";
            return false;
        }
        const auto* lhsDecl = model.moleculeType(*lhsMol->moleculeTypeId);
        const auto* rhsDecl = model.moleculeType(*rhsMol->moleculeTypeId);
        if (lhsDecl == nullptr || rhsDecl == nullptr) return false;
        NFcore::MoleculeType* lhsType = nullptr;
        NFcore::MoleculeType* rhsType = nullptr;
        try {
            lhsType = system.getMoleculeTypeByName(lhsDecl->name);
            rhsType = system.getMoleculeTypeByName(rhsDecl->name);
        } catch (const std::exception& error) {
            diagnostic = error.what();
            return false;
        }
        std::map<std::string, double> parameters;
        std::map<std::string, int> states;
        const auto lhsSiteName = runtimeComponentName(model, *lhsSite->componentType);
        const auto rhsSiteName = runtimeComponentName(model, *rhsSite->componentType);
        const auto lhsEquivalentNames = equivalentRuntimeNames(
            model, *lhsSite->componentType);
        const auto rhsEquivalentNames = equivalentRuntimeNames(
            model, *rhsSite->componentType);
        if (lhsSiteName.empty() || rhsSiteName.empty() ||
            lhsEquivalentNames.empty() || rhsEquivalentNames.empty()) {
            diagnostic = "Arrhenius binding has invalid reaction-center component names";
            return false;
        }
        for (const auto& lhsName : lhsEquivalentNames) {
            for (const auto& rhsName : rhsEquivalentNames) {
                ok = NFinput::createExpandedBindingReactions(
                    rule.name(), *phi, *activationEnergy, lhsType, lhsName,
                    rhsType, rhsName, &system, parameters, states,
                    blockSameComplexBinding, verbose, reactionCount,
                    rule.isBidirectional(), lhsSiteName, rhsSiteName);
                if (!ok) return false;
            }
        }
        suggestedTraversalLimit = std::max(suggestedTraversalLimit, 2);
    } else if (mutation.kind == MutationKind::ChangeState) {
        if (direction.reactantPatterns.size() != 1 ||
            direction.reactantPatterns.front().molecules().size() != 1 ||
            mutation.source.side != PatternSide::Reactant ||
            mutation.newState == "PLUS" || mutation.newState == "MINUS") {
            diagnostic = "Arrhenius state change requires one one-molecule reactant and an exact target state";
            return false;
        }
        const auto* molecule = referencedMolecule(
            direction, PatternMoleculeRef{PatternSide::Reactant,
                                          mutation.source.patternIndex,
                                          mutation.source.moleculeIndex});
        const auto* site = referencedSite(direction, mutation.source);
        if (molecule == nullptr || site == nullptr ||
            !molecule->moleculeTypeId.has_value() || !site->componentType.has_value() ||
            site->stateConstraintResolved.kind != bng::compile::StateConstraintKind::Exact ||
            !site->stateConstraintResolved.exact.has_value()) {
            diagnostic = "Arrhenius state change requires an exact typed source state";
            return false;
        }
        const auto* sourceState = model.stateName(*site->stateConstraintResolved.exact);
        const auto* moleculeDecl = model.moleculeType(*molecule->moleculeTypeId);
        if (sourceState == nullptr || moleculeDecl == nullptr) return false;
        NFcore::MoleculeType* moleculeType = nullptr;
        try {
            moleculeType = system.getMoleculeTypeByName(moleculeDecl->name);
        } catch (const std::exception& error) {
            diagnostic = error.what();
            return false;
        }
        const auto componentName = runtimeComponentName(model, *site->componentType);
        const auto equivalentNames = equivalentRuntimeNames(
            model, *site->componentType);
        if (componentName.empty() || equivalentNames.empty()) {
            diagnostic = "Arrhenius state change has an invalid reaction-center component name";
            return false;
        }
        for (const auto& concreteName : equivalentNames) {
            ok = NFinput::createExpandedStateChangeReactions(
                rule.name(), *phi, *activationEnergy, moleculeType,
                concreteName, *sourceState, mutation.newState, &system,
                blockSameComplexBinding, verbose, reactionCount,
                rule.isBidirectional(), componentName);
            if (!ok) return false;
        }
        suggestedTraversalLimit = std::max(suggestedTraversalLimit, 1);
    } else {
        diagnostic = "Arrhenius structural lowering supports binding or state-change centers";
        return false;
    }
    if (!ok) return false;

    const auto reactions = system.getAllReactions();
    for (std::size_t index = firstReaction; index < reactions.size(); ++index) {
        auto* reaction = reactions[index];
        reaction->setTotalRateFlag(hasModifier(rule, ModifierKind::TotalRate));
        if (hasModifier(rule, ModifierKind::MatchOnce)) {
            for (std::size_t reactant = 0; reactant < direction.reactantPatterns.size(); ++reactant)
                reaction->setMatchOnce(static_cast<unsigned int>(reactant), true);
        }
    }
    return true;
}

NFcore::ReactionClass* makeReactionForRate(
    const CompiledModel& model,
    const CompiledRule& rule,
    const CompiledRuleDirection& direction,
    const std::string& reactionName,
    NFcore::TransformationSet* transformations,
    const std::vector<NFcore::TemplateMolecule*>& roots,
    NFcore::System& system,
    const std::filesystem::path& sourcePath,
    std::size_t ordinal,
    std::string& diagnostic) {
    if (!direction.rateLaw.has_value()) { diagnostic = "reaction has no rate law"; return nullptr; }
    const auto& rate = *direction.rateLaw;
    const auto& expression = rate.resolvedExpression();
    using RateKind = bng::compile::RateLawKind;

    if ((rate.kind == RateKind::MichaelisMenten || rate.kind == RateKind::Saturation ||
         rate.kind == RateKind::Hill) && hasModifier(rule, ModifierKind::TotalRate)) {
        diagnostic = "built-in saturating rates do not support TotalRate in NFsim";
        return nullptr;
    }

    if (rate.kind == RateKind::MichaelisMenten) {
        if (direction.reactantPatterns.size() != 2 || expression.arguments.size() != 2) {
            diagnostic = "MM requires exactly two reactants and two constants"; return nullptr;
        }
        const auto kcat = evaluateStatic(model, expression.arguments[0], diagnostic);
        const auto km = evaluateStatic(model, expression.arguments[1], diagnostic);
        if (!kcat.has_value() || !km.has_value() || *km < 0.0) return nullptr;
        transformations->finalize();
        return new NFcore::MMRxnClass(reactionName, *kcat, *km, transformations, &system);
    }
    if (rate.kind == RateKind::Saturation || rate.kind == RateKind::Hill) {
        std::vector<double> constants;
        for (const auto& argument : expression.arguments) {
            const auto value = evaluateStatic(model, argument, diagnostic);
            if (!value.has_value()) return nullptr;
            constants.push_back(*value);
        }
        if (rate.kind == RateKind::Saturation) {
            if (constants.size() < 2 || constants.size() > direction.reactantPatterns.size() + 1) {
                diagnostic = "Sat has invalid constant count"; return nullptr;
            }
            transformations->finalize();
            return new NFcore::SatRxnClass(reactionName, std::move(constants), transformations, &system);
        }
        if (constants.size() != 3) { diagnostic = "Hill requires three constants"; return nullptr; }
        transformations->finalize();
        return new NFcore::HillRxnClass(reactionName, constants[0], constants[1], constants[2], transformations, &system);
    }
    if (rate.kind == RateKind::ArrheniusEnergy || rate.kind == RateKind::Hybrid) {
        diagnostic = "specialized compiled rate requires dedicated NFsim lowering";
        return nullptr;
    }


    LocalRateOperand productFirst, productSecond;
    if (functionProductOperands(model, direction, expression, productFirst, productSecond)) {
        if (productFirst.scope->reactantPatternIndex == productSecond.scope->reactantPatternIndex) {
            diagnostic = "FunctionProduct requires two different scoped reactants";
            return nullptr;
        }
        auto* first = system.getCompositeFunctionByName(productFirst.function->name);
        auto* second = system.getCompositeFunctionByName(productSecond.function->name);
        if (first == nullptr || second == nullptr) {
            diagnostic = "FunctionProduct refers to an unregistered compiled local function";
            return nullptr;
        }
        if (!addLocalRateReference(productFirst, roots, *transformations, diagnostic) ||
            !addLocalRateReference(productSecond, roots, *transformations, diagnostic)) {
            return nullptr;
        }
        std::vector<std::string> firstArguments{productFirst.argument};
        std::vector<std::string> secondArguments{productSecond.argument};
        transformations->finalize();
        return new NFcore::DOR2RxnClass(
            reactionName, 1.0, "", transformations, first, second,
            firstArguments, secondArguments, &system);
    }

    LocalRateOperand localOperand;
    if (localRateOperand(model, direction, expression, localOperand)) {
        auto* composite = system.getCompositeFunctionByName(localOperand.function->name);
        if (composite == nullptr) {
            diagnostic = "local-function rate refers to an unregistered compiled function";
            return nullptr;
        }
        if (!addLocalRateReference(localOperand, roots, *transformations, diagnostic))
            return nullptr;
        std::vector<std::string> arguments{localOperand.argument};
        transformations->finalize();
        return new NFcore::DORRxnClass(
            reactionName, 1.0, "", transformations, composite, arguments, &system);
    }

    // General mapping-local arithmetic, e.g. k*(1-f(x)), is represented by
    // a reaction-owned CompositeFunction over the already-registered local
    // functions.  This is the same evaluator DORRxnClass consumes on the XML
    // path, but the expression and scopes come from the resolved compile IR.
    ScopedCompositeRate scopedRate;
    if (prepareScopedCompositeRate(model, direction, expression, system,
                                   scopedRate, diagnostic)) {
        for (const auto& operand : scopedRate.localOperands) {
            if (!addLocalRateReference(operand, roots, *transformations, diagnostic))
                return nullptr;
        }
        std::string compositeName =
            "__bng3_reaction_rate_" + std::to_string(ordinal + 1);
        std::size_t compositeSuffix = 1;
        while (system.getGlobalFunctionByName(compositeName) != nullptr ||
               system.getCompositeFunctionByName(compositeName) != nullptr ||
               system.getLocalFunctionByName(compositeName) != nullptr) {
            compositeName = "__bng3_reaction_rate_" + std::to_string(ordinal + 1) +
                            "_" + std::to_string(compositeSuffix++);
        }
        auto* composite = new NFcore::CompositeFunction(
            &system, compositeName, scopedRate.expression, scopedRate.functionNames,
            scopedRate.argumentNames, scopedRate.parameterNames);
        if (scopedRate.usesTime) {
            composite->setCounterFromTime(&system);
            system.setHasTimeDependentFunctions(true);
        }
        if (!system.addCompositeFunction(composite)) {
            delete composite;
            diagnostic = "could not register compiled scoped rate function";
            return nullptr;
        }
        // Model functions were finalized before reaction construction.  This
        // generated composite is intentionally late-bound and must be finalized
        // exactly once here before DORRxnClass starts using it.
        composite->finalizeInitialization(&system);
        transformations->finalize();
        return new NFcore::DORRxnClass(
            reactionName, 1.0, "", transformations, composite,
            scopedRate.argumentNames, &system);
    }

    if (expression.kind == ResolvedExpressionKind::FunctionRef &&
        expression.symbol.has_value() && expression.arguments.empty()) {
        const auto* function = model.function(
            bng::compile::FunctionId::fromDenseIndex(expression.symbol->index));
        if (function != nullptr) {
            if (auto* global = system.getGlobalFunctionByName(function->name)) {
                transformations->finalize();
                return new NFcore::FunctionalRxnClass(reactionName, global, transformations, &system);
            }
            if (auto* composite = system.getCompositeFunctionByName(function->name)) {
                transformations->finalize();
                return new NFcore::FunctionalRxnClass(reactionName, composite, transformations, &system);
            }
        }
    }

    if (const auto value = evaluateStatic(model, expression, diagnostic)) {
        if (*value < 0.0) { diagnostic = "reaction rate must be nonnegative"; return nullptr; }
        transformations->finalize();
        auto* reaction = new NFcore::BasicRxnClass(reactionName, 0.0, "", transformations, &system);
        std::string parameterName;
        if (expression.kind == ResolvedExpressionKind::ParameterRef && expression.symbol.has_value()) {
            if (const auto* parameter = model.parameter(
                    bng::compile::ParameterId::fromDenseIndex(expression.symbol->index)))
                parameterName = parameter->name;
        }
        reaction->setBaseRate(*value, parameterName);
        return reaction;
    }

    NFcore::GlobalFunction* dynamicGlobal = nullptr;
    NFcore::CompositeFunction* dynamicComposite = nullptr;
    std::vector<std::string> dynamicLocalArguments;
    if (!addDynamicCompiledRateFunction(
            model, direction, expression, system, sourcePath, ordinal,
            *transformations, roots, dynamicGlobal, dynamicComposite,
            dynamicLocalArguments, diagnostic)) {
        return nullptr;
    }
    transformations->finalize();
    if (dynamicGlobal != nullptr) {
        return new NFcore::FunctionalRxnClass(
            reactionName, dynamicGlobal, transformations, &system);
    }
    if (dynamicComposite != nullptr) {
        if (dynamicLocalArguments.empty()) {
            return new NFcore::FunctionalRxnClass(
                reactionName, dynamicComposite, transformations, &system);
        }
        auto* reaction = new NFcore::DORRxnClass(
            reactionName, 1.0, "", transformations, dynamicComposite,
            dynamicLocalArguments, &system);
        dynamicComposite->setGlobalObservableDependency(reaction, &system);
        return reaction;
    }
    diagnostic = "dynamic compiled reaction rate produced no NFsim function";
    return nullptr;
}


enum class SymmetricCompiledExpansionResult {
    NotApplicable,
    Added,
    Error,
};

struct ExpandedCompiledReactantPattern {
    std::vector<std::vector<NFcore::TemplateMolecule*>> builds;
    std::vector<NFcore2::RuntimeComponentNames> assignments;
};

bool expressionUsesLocalScope(const ResolvedExpression& expression) {
    if (expression.kind == ResolvedExpressionKind::LocalRef) return true;
    return std::any_of(
        expression.arguments.begin(), expression.arguments.end(),
        [](const auto& argument) { return expressionUsesLocalScope(argument); });
}

bool hasOnlySymmetricPermutationModifiers(const CompiledRule& rule) {
    return std::all_of(
        rule.modifiers().begin(), rule.modifiers().end(), [](const auto& modifier) {
            return modifier.kind == ModifierKind::TotalRate ||
                   modifier.kind == ModifierKind::MatchOnce;
        });
}

bool buildExpandedCompiledReactants(
    const CompiledRuleDirection& direction,
    NFcore::System& system,
    const std::set<PatternSiteRef>& reactionCenter,
    int& suggestedTraversalLimit,
    std::vector<ExpandedCompiledReactantPattern>& expandedPatterns,
    bool& hasDisjointSets,
    std::string& diagnostic) {
    expandedPatterns.clear();
    expandedPatterns.reserve(direction.reactantPatterns.size());
    hasDisjointSets = false;
    for (std::size_t patternIndex = 0;
         patternIndex < direction.reactantPatterns.size(); ++patternIndex) {
        std::set<std::pair<std::size_t, std::size_t>> localReactionCenter;
        for (const auto& ref : reactionCenter) {
            if (ref.side == PatternSide::Reactant && ref.patternIndex == patternIndex) {
                localReactionCenter.emplace(ref.moleculeIndex, ref.siteIndex);
            }
        }

        ExpandedCompiledReactantPattern expanded;
        bool disjoint = false;
        if (!NFcore2::lowerPatternToNFsimPermutations(
                direction.reactantPatterns[patternIndex], system,
                localReactionCenter, expanded.builds, expanded.assignments,
                disjoint, suggestedTraversalLimit, diagnostic) ||
            expanded.builds.empty() ||
            expanded.builds.size() != expanded.assignments.size()) {
            if (diagnostic.empty()) diagnostic = "invalid symmetric reactant pattern";
            return false;
        }
        hasDisjointSets = hasDisjointSets || disjoint;

        // Context-only symmetric sites constrain matching but do not identify a
        // distinct reaction class.  Keep one build for every unique assignment
        // of reaction-center sites, matching the legacy NFsim expansion.
        std::set<std::vector<std::string>> seen;
        std::vector<std::vector<NFcore::TemplateMolecule*>> uniqueBuilds;
        std::vector<NFcore2::RuntimeComponentNames> uniqueAssignments;
        for (std::size_t buildIndex = 0;
             buildIndex < expanded.builds.size(); ++buildIndex) {
            std::vector<std::string> key;
            for (const auto& ref : reactionCenter) {
                if (ref.side != PatternSide::Reactant ||
                    ref.patternIndex != patternIndex) continue;
                if (ref.moleculeIndex >= expanded.assignments[buildIndex].size() ||
                    ref.siteIndex >=
                        expanded.assignments[buildIndex][ref.moleculeIndex].size()) {
                    diagnostic = "reaction-center site is outside symmetric assignment";
                    return false;
                }
                key.push_back(
                    expanded.assignments[buildIndex][ref.moleculeIndex][ref.siteIndex]);
            }
            if (!seen.insert(key).second) continue;
            uniqueBuilds.push_back(std::move(expanded.builds[buildIndex]));
            uniqueAssignments.push_back(std::move(expanded.assignments[buildIndex]));
        }
        expanded.builds = std::move(uniqueBuilds);
        expanded.assignments = std::move(uniqueAssignments);
        expandedPatterns.push_back(std::move(expanded));
    }
    return !expandedPatterns.empty();
}

SymmetricCompiledExpansionResult addSymmetricCompiledDirection(
    const CompiledModel& model,
    const CompiledRule& rule,
    const CompiledRuleDirection& direction,
    bool reverse,
    NFcore::System& system,
    bool blockSameComplexBinding,
    bool verbose,
    int& suggestedTraversalLimit,
    const std::filesystem::path& sourcePath,
    std::size_t rateOrdinal,
    std::string& diagnostic) {
    if (direction.reactantPatterns.empty() || direction.productPatterns.empty() ||
        !direction.rateLaw.has_value() || !direction.filters.empty() ||
        !hasOnlySymmetricPermutationModifiers(rule)) {
        return SymmetricCompiledExpansionResult::NotApplicable;
    }
    // The legacy permutation path covers ordinary expression rates.  Keep
    // specialized kinetics on their dedicated/compatibility paths until their
    // symmetric parity fixtures exist.
    if (direction.rateLaw->kind != bng::compile::RateLawKind::Expression ||
        expressionUsesLocalScope(direction.rateLaw->resolvedExpression())) {
        return SymmetricCompiledExpansionResult::NotApplicable;
    }

    enum class CenterKind { State, Bond };
    CenterKind centerKind = CenterKind::State;
    std::set<PatternSiteRef> reactionCenter;
    if (!direction.mutations.empty() &&
        std::all_of(direction.mutations.begin(), direction.mutations.end(),
                    [](const auto& mutation) {
                        return mutation.kind == MutationKind::ChangeState;
                    })) {
        for (const auto& mutation : direction.mutations) {
            if (mutation.source.side != PatternSide::Reactant ||
                !reactionCenter.insert(mutation.source).second) {
                return SymmetricCompiledExpansionResult::NotApplicable;
            }
        }
    } else if (direction.mutations.size() == 1 &&
               (direction.mutations.front().kind == MutationKind::AddBond ||
                direction.mutations.front().kind == MutationKind::DeleteBond)) {
        centerKind = CenterKind::Bond;
        const auto& mutation = direction.mutations.front();
        if (mutation.source.side != PatternSide::Reactant ||
            mutation.partner.side != PatternSide::Reactant) {
            return SymmetricCompiledExpansionResult::NotApplicable;
        }
        reactionCenter.insert(mutation.source);
        reactionCenter.insert(mutation.partner);
    } else {
        return SymmetricCompiledExpansionResult::NotApplicable;
    }
    if (reactionCenter.empty()) return SymmetricCompiledExpansionResult::NotApplicable;

    bool hasSymmetricCenter = false;
    for (const auto& ref : reactionCenter) {
        const auto* site = referencedSite(direction, ref);
        if (site == nullptr || !site->componentType.has_value()) {
            diagnostic = "reaction-center site has no resolved component";
            return SymmetricCompiledExpansionResult::Error;
        }
        if (isSymmetricComponent(model, *site->componentType)) {
            hasSymmetricCenter = true;
        }
    }
    if (!hasSymmetricCenter) return SymmetricCompiledExpansionResult::NotApplicable;

    std::vector<ExpandedCompiledReactantPattern> expandedPatterns;
    bool hasDisjointSets = false;
    if (!buildExpandedCompiledReactants(
            direction, system, reactionCenter, suggestedTraversalLimit,
            expandedPatterns, hasDisjointSets, diagnostic)) {
        return SymmetricCompiledExpansionResult::Error;
    }

    std::vector<std::size_t> selected(expandedPatterns.size(), 0);
    std::size_t reactionOrdinal = 0;
    std::function<bool(std::size_t)> addCombination = [&](std::size_t patternIndex) {
        if (patternIndex < expandedPatterns.size()) {
            for (std::size_t buildIndex = 0;
                 buildIndex < expandedPatterns[patternIndex].builds.size(); ++buildIndex) {
                selected[patternIndex] = buildIndex;
                if (!addCombination(patternIndex + 1)) return false;
            }
            return true;
        }

        std::vector<NFcore::TemplateMolecule*> roots;
        roots.reserve(expandedPatterns.size());
        for (std::size_t index = 0; index < expandedPatterns.size(); ++index) {
            const auto& build = expandedPatterns[index].builds[selected[index]];
            if (build.empty()) {
                diagnostic = "symmetric reactant pattern produced no template";
                return false;
            }
            roots.push_back(build.front());
        }
        auto* transformations = new NFcore::TransformationSet(roots);
        transformations->setComplexBookkeeping(
            blockSameComplexBinding || hasDisjointSets);
        transformations->setNumProductPatterns(
            static_cast<unsigned int>(direction.productPatterns.size()));

        const auto runtimeComponent = [&](const PatternSiteRef& ref,
                                          NFcore::TemplateMolecule*& molecule,
                                          std::string& component) {
            if (ref.side != PatternSide::Reactant ||
                ref.patternIndex >= expandedPatterns.size()) {
                diagnostic = "reaction-center endpoint is outside expanded reactants";
                return false;
            }
            const auto& expanded = expandedPatterns[ref.patternIndex];
            const auto buildIndex = selected[ref.patternIndex];
            if (ref.moleculeIndex >= expanded.builds[buildIndex].size() ||
                ref.moleculeIndex >= expanded.assignments[buildIndex].size() ||
                ref.siteIndex >=
                    expanded.assignments[buildIndex][ref.moleculeIndex].size()) {
                diagnostic = "reaction-center endpoint is outside symmetric assignment";
                return false;
            }
            molecule = expanded.builds[buildIndex][ref.moleculeIndex];
            component = expanded.assignments[buildIndex][ref.moleculeIndex][ref.siteIndex];
            return molecule != nullptr && !component.empty();
        };

        bool applied = true;
        if (centerKind == CenterKind::State) {
            for (const auto& mutation : direction.mutations) {
                NFcore::TemplateMolecule* target = nullptr;
                std::string component;
                if (!runtimeComponent(mutation.source, target, component)) {
                    applied = false;
                    break;
                }
                try {
                    if (mutation.newState == "PLUS") {
                        applied = transformations->addIncrementStateTransform(
                            target, component);
                    } else if (mutation.newState == "MINUS") {
                        applied = transformations->addDecrementStateTransform(
                            target, component);
                    } else {
                        applied = transformations->addStateChangeTransform(
                            target, component, mutation.newState);
                    }
                } catch (const std::exception& error) {
                    diagnostic = error.what();
                    applied = false;
                }
                if (!applied) break;
            }
        } else {
            const auto& mutation = direction.mutations.front();
            NFcore::TemplateMolecule* lhs = nullptr;
            NFcore::TemplateMolecule* rhs = nullptr;
            std::string lhsName, rhsName;
            if (!runtimeComponent(mutation.source, lhs, lhsName) ||
                !runtimeComponent(mutation.partner, rhs, rhsName)) {
                applied = false;
            } else {
                try {
                    applied = mutation.kind == MutationKind::AddBond
                        ? transformations->addBindingTransform(
                              lhs, lhsName, rhs, rhsName)
                        : transformations->addUnbindingTransform(
                              lhs, lhsName, rhs, rhsName);
                } catch (const std::exception& error) {
                    diagnostic = error.what();
                    applied = false;
                }
            }
        }
        if (!applied) {
            if (diagnostic.empty()) diagnostic =
                centerKind == CenterKind::State
                    ? "could not add symmetric state-change transformation"
                    : "could not add symmetric bond transformation";
            delete transformations;
            return false;
        }

        const auto reactionName = rule.name() +
            (reverse ? "_reverse_sym" : "_sym") +
            std::to_string(reactionOrdinal + 1);
        auto* reaction = makeReactionForRate(
            model, rule, direction, reactionName, transformations, roots,
            system, sourcePath, rateOrdinal, diagnostic);
        if (reaction == nullptr) {
            delete transformations;
            return false;
        }
        reaction->setTotalRateFlag(hasModifier(rule, ModifierKind::TotalRate));
        if (hasModifier(rule, ModifierKind::MatchOnce)) {
            for (std::size_t index = 0; index < roots.size(); ++index) {
                reaction->setMatchOnce(static_cast<unsigned int>(index), true);
            }
        }
        ++reactionOrdinal;
        if (reaction->getRxnType() == NFcore::ReactionClass::BASIC_RXN &&
            reaction->getBaseRate() <= 0.0) {
            delete reaction;
            return true;
        }
        system.addReaction(reaction);
        if (verbose) {
            std::cerr << "[nfsim/compiled] reaction " << reaction->getName()
                      << " (compiled symmetric permutation)\n";
        }
        return true;
    };

    if (!addCombination(0)) return SymmetricCompiledExpansionResult::Error;
    return SymmetricCompiledExpansionResult::Added;
}

bool lowerDirection(const CompiledModel& model,
                    const CompiledRule& rule,
                    const CompiledRuleDirection& direction,
                    bool reverse,
                    NFcore::System& system,
                    bool blockSameComplexBinding,
                    bool verbose,
                    int& suggestedTraversalLimit,
                    const std::filesystem::path& sourcePath,
                    std::size_t ordinal,
                    std::string& diagnostic) {
    if (!direction.transformationsComplete) {
        diagnostic = "compiled transformation program is incomplete";
        return false;
    }
    for (const auto& modifier : rule.modifiers()) {
        if (modifier.kind == ModifierKind::Unknown) {
            diagnostic = "unknown reaction modifier requires compatibility lowering";
            return false;
        }
    }

    const auto symmetric = addSymmetricCompiledDirection(
        model, rule, direction, reverse, system, blockSameComplexBinding, verbose,
        suggestedTraversalLimit, sourcePath, ordinal, diagnostic);
    if (symmetric == SymmetricCompiledExpansionResult::Added) return true;
    if (symmetric == SymmetricCompiledExpansionResult::Error) return false;

    std::vector<std::vector<NFcore::TemplateMolecule*>> templates;
    std::vector<NFcore::TemplateMolecule*> roots;
    bool hasDisjointSets = false;
    for (const auto& pattern : direction.reactantPatterns) {
        std::vector<NFcore::TemplateMolecule*> lowered;
        bool disjoint = false;
        if (!NFcore2::lowerPatternToNFsim(pattern, system, lowered, disjoint,
                                          suggestedTraversalLimit, diagnostic) ||
            lowered.empty()) return false;
        roots.push_back(lowered.front());
        templates.push_back(std::move(lowered));
        hasDisjointSets = hasDisjointSets || disjoint;
    }

    std::vector<DirectProductMolecule> directProducts;
    std::vector<NFcore::TemplateMolecule*> addTemplates;
    std::vector<NFcore::MoleculeCreator*> creators;
    std::map<PatternMoleculeRef, std::size_t, MoleculeRefLess> added;
    auto addProduct = [&](const PatternMoleculeRef& ref) -> bool {
        if (ref.side != PatternSide::Product || ref.patternIndex >= direction.productPatterns.size()) {
            diagnostic = "AddMolecule has invalid product reference"; return false;
        }
        if (added.count(ref)) { diagnostic = "duplicate AddMolecule"; return false; }
        DirectProductMolecule product;
        if (!buildDirectProductMolecule(model, direction.productPatterns[ref.patternIndex],
                                        ref.moleculeIndex, system, product, diagnostic)) return false;
        if (product.creator == nullptr) return true; // Null/Trash sink
        added.emplace(ref, directProducts.size());
        addTemplates.push_back(product.templateMolecule);
        creators.push_back(product.creator);
        directProducts.push_back(std::move(product));
        return true;
    };

    for (const auto& mutation : direction.mutations)
        if (mutation.kind == MutationKind::AddMolecule && !addProduct(mutation.molecule)) return false;
    if (roots.empty() && addTemplates.empty()) {
        for (std::size_t pattern = 0; pattern < direction.productPatterns.size(); ++pattern)
            for (std::size_t molecule = 0; molecule < direction.productPatterns[pattern].molecules().size(); ++molecule)
                if (!addProduct(PatternMoleculeRef{PatternSide::Product, pattern, molecule})) return false;
    }

    auto* transformations = addTemplates.empty()
                                ? new NFcore::TransformationSet(roots)
                                : new NFcore::TransformationSet(roots, addTemplates);
    transformations->setComplexBookkeeping(blockSameComplexBinding || hasDisjointSets);
    transformations->setNumProductPatterns(static_cast<unsigned int>(direction.productPatterns.size()));
    for (auto* creator : creators)
        if (!transformations->addAddMolecule(creator)) { delete transformations; return false; }

    if (!addFilters(direction, system, *transformations, roots, hasDisjointSets,
                    suggestedTraversalLimit, diagnostic)) {
        if (diagnostic == "__BNG_STATIC_PRODUCT_FILTER_REJECT__") {
            delete transformations;
            return true; // valid rule, statically excluded
        }
        delete transformations; return false;
    }
    transformations->setComplexBookkeeping(blockSameComplexBinding || hasDisjointSets);

    MoleculeMap moleculeMappings;
    SiteMap siteMappings;
    directionMappings(rule, reverse, moleculeMappings, siteMappings);

    // Compartment transport is derived from the already-resolved molecule map.
    for (const auto& [productRef, reactantRef] : moleculeMappings) {
        const auto* productMolecule = referencedMolecule(direction, productRef);
        const auto* reactantMolecule = referencedMolecule(direction, reactantRef);
        const auto* productPattern = referencedPattern(direction, PatternSide::Product, productRef.patternIndex);
        const auto* reactantPattern = referencedPattern(direction, PatternSide::Reactant, reactantRef.patternIndex);
        if (productMolecule == nullptr || reactantMolecule == nullptr ||
            productPattern == nullptr || reactantPattern == nullptr) {
            diagnostic = "molecule mapping is outside the compiled direction";
            delete transformations; return false;
        }
        const auto destinationName = compartmentName(model, *productPattern, *productMolecule);
        const auto sourceName = compartmentName(model, *reactantPattern, *reactantMolecule);
        if (destinationName.empty() || destinationName == sourceName) continue;
        auto* destination = resolveCompartment(system, destinationName, diagnostic);
        if (destination == nullptr) { delete transformations; return false; }
        NFcore::TemplateMolecule* target = nullptr;
        if (!templateForRef(reactantRef, templates, target, diagnostic) ||
            !transformations->addMoveTransform(
                target, destination, hasModifier(rule, ModifierKind::MoveConnected))) {
            if (diagnostic.empty()) diagnostic = "could not lower compartment transport";
            delete transformations; return false;
        }
        system.setUsingComplex(true);
    }

    // Add creator transformations before edits; then unbind, bind, state-change.
    for (const auto& mutation : direction.mutations) {
        if (mutation.kind != MutationKind::DeleteBond) continue;
        NFcore::TemplateMolecule *lhs=nullptr, *rhs=nullptr; std::string lhsName, rhsName;
        if (!componentForRef(model, direction, mutation.source, templates, lhs, lhsName, diagnostic) ||
            !componentForRef(model, direction, mutation.partner, templates, rhs, rhsName, diagnostic) ||
            !transformations->addUnbindingTransform(lhs, lhsName, rhs, rhsName)) {
            delete transformations; return false;
        }
    }
    for (const auto& mutation : direction.mutations) {
        if (mutation.kind != MutationKind::AddBond) continue;
        NFcore::TemplateMolecule *lhs=nullptr, *rhs=nullptr; std::string lhsName, rhsName;
        if (!componentForRef(model, direction, mutation.source, templates, lhs, lhsName, diagnostic) ||
            !componentForRef(model, direction, mutation.partner, templates, rhs, rhsName, diagnostic) ||
            !transformations->addBindingTransform(lhs, lhsName, rhs, rhsName)) {
            delete transformations; return false;
        }
    }

    // Product bonds involving newly created molecules do not appear as ordinary
    // two-reactant AddBond mutations. Recover them structurally from product
    // bond groups and the resolved component mapping.
    std::map<PatternSiteRef, std::pair<NFcore::TemplateMolecule*, std::string>> addedSites;
    for (const auto& [moleculeRef, index] : added) {
        const auto* molecule = referencedMolecule(direction, moleculeRef);
        if (molecule == nullptr) { delete transformations; return false; }
        for (std::size_t site = 0; site < molecule->sites.size(); ++site) {
            if (site >= directProducts[index].runtimeComponentNames.size()) {
                diagnostic = "created molecule site mapping is incomplete";
                delete transformations; return false;
            }
            addedSites.emplace(
                PatternSiteRef{PatternSide::Product, moleculeRef.patternIndex,
                               moleculeRef.moleculeIndex, site},
                std::make_pair(directProducts[index].templateMolecule,
                               directProducts[index].runtimeComponentNames[site]));
        }
    }
    for (const auto& [group, endpoints] : productBondGroups(direction)) {
        (void)group;
        if (endpoints.size() != 2) { diagnostic = "product bond group has invalid arity"; delete transformations; return false; }
        const auto firstAdded = addedSites.find(endpoints[0].ref);
        const auto secondAdded = addedSites.find(endpoints[1].ref);
        if (firstAdded == addedSites.end() && secondAdded == addedSites.end()) continue;
        if (firstAdded != addedSites.end() && secondAdded != addedSites.end()) {
            if (!transformations->addNewMoleculeBindingTransform(
                    firstAdded->second.first, firstAdded->second.second,
                    secondAdded->second.first, secondAdded->second.second)) {
                diagnostic = "could not bind two created product molecules";
                delete transformations; return false;
            }
            continue;
        }
        const auto addedSite = firstAdded != addedSites.end() ? firstAdded : secondAdded;
        const auto existing = firstAdded != addedSites.end() ? endpoints[1].ref : endpoints[0].ref;
        const auto mapping = siteMappings.find(existing);
        if (mapping == siteMappings.end()) {
            diagnostic = "product bond refers to an unmapped existing component";
            delete transformations; return false;
        }
        NFcore::TemplateMolecule* existingTemplate = nullptr; std::string existingName;
        if (!componentForRef(model, direction, mapping->second, templates,
                             existingTemplate, existingName, diagnostic)) {
            delete transformations; return false;
        }
        existingTemplate->addEmptyComponent(existingName);
        if (!transformations->addNewMoleculeBindingTransform(
                existingTemplate, existingName,
                addedSite->second.first, addedSite->second.second)) {
            diagnostic = "could not bind existing and created product molecules";
            delete transformations; return false;
        }
    }

    for (const auto& mutation : direction.mutations) {
        if (mutation.kind != MutationKind::ChangeState) continue;
        NFcore::TemplateMolecule* target = nullptr; std::string component;
        if (!componentForRef(model, direction, mutation.source, templates,
                             target, component, diagnostic)) {
            delete transformations; return false;
        }
        bool applied = false;
        if (mutation.newState == "PLUS") applied = transformations->addIncrementStateTransform(target, component);
        else if (mutation.newState == "MINUS") applied = transformations->addDecrementStateTransform(target, component);
        else applied = transformations->addStateChangeTransform(target, component, mutation.newState);
        if (!applied) { diagnostic = "could not lower state change"; delete transformations; return false; }
    }

    const bool deleteMolecules = hasModifier(rule, ModifierKind::DeleteMolecules);
    if (direction.productPatterns.empty() && direction.mutations.empty()) {
        for (auto* root : roots) {
            const bool ok = root->getMoleculeType()->isPopulationType()
                ? transformations->addDecrementPopulation(root)
                : transformations->addDeleteMolecule(
                    root, deleteMolecules ? NFcore::TransformationFactory::DELETE_MOLECULES
                                          : NFcore::TransformationFactory::COMPLETE_SPECIES_REMOVAL);
            if (!ok) { delete transformations; return false; }
        }
    } else {
        for (const auto& mutation : direction.mutations) {
            if (mutation.kind != MutationKind::DeleteMolecule) continue;
            NFcore::TemplateMolecule* target = nullptr;
            if (!templateForRef(mutation.molecule, templates, target, diagnostic)) {
                delete transformations; return false;
            }
            const bool ok = target->getMoleculeType()->isPopulationType()
                ? transformations->addDecrementPopulation(target)
                : transformations->addDeleteMolecule(
                    target, deleteMolecules ? NFcore::TransformationFactory::DELETE_MOLECULES
                                            : NFcore::TransformationFactory::DELETE_MOLECULES_NO_KEYWORD);
            if (!ok) { delete transformations; return false; }
        }
    }

    auto* reaction = makeReactionForRate(model, rule, direction,
        reverse ? rule.name() + "_reverse" : rule.name(), transformations, roots,
        system, sourcePath, ordinal, diagnostic);
    if (reaction == nullptr) { delete transformations; return false; }
    reaction->setTotalRateFlag(hasModifier(rule, ModifierKind::TotalRate));
    if (hasModifier(rule, ModifierKind::MatchOnce))
        for (std::size_t index = 0; index < roots.size(); ++index)
            reaction->setMatchOnce(static_cast<unsigned int>(index), true);

    if (roots.empty()) {
        NFcore::Compartment* productCompartment = nullptr;
        bool same = true;
        for (const auto& pattern : direction.productPatterns) {
            for (const auto& molecule : pattern.molecules()) {
                const auto name = compartmentName(model, pattern, molecule);
                if (name.empty()) continue;
                auto* compartment = resolveCompartment(system, name, diagnostic);
                if (compartment == nullptr) { delete reaction; delete transformations; return false; }
                if (productCompartment == nullptr) productCompartment = compartment;
                else if (productCompartment != compartment) same = false;
            }
        }
        double factor = 1.0;
        if (productCompartment != nullptr && same) {
            factor = productCompartment->getSize();
            if (system.getNumberPerQuantityUnit() > 0.0)
                factor *= system.getNumberPerQuantityUnit();
        }
        reaction->volumeConversionFactor = factor;
        if (reaction->getRxnType() != NFcore::ReactionClass::OBS_DEPENDENT_RXN)
            reaction->setBaseRate(reaction->getBaseRate() * factor, "");
    }

    if (reaction->getRxnType() == NFcore::ReactionClass::BASIC_RXN &&
        reaction->getBaseRate() <= 0.0) {
        delete reaction;
        return true;
    }
    system.addReaction(reaction);
    if (verbose)
        std::cerr << "[nfsim/compiled] reaction " << reaction->getName()
                  << " (compiled direct)\n";
    return true;
}

} // namespace

bool addReactionRulesFromCompiled(const CompiledModel& model,
                                  NFcore::System* system,
                                  bool blockSameComplexBinding,
                                  bool verbose,
                                  int& suggestedTraversalLimit,
                                  const std::filesystem::path& sourcePath) {
    if (system == nullptr) return false;
    for (std::size_t index = 0; index < model.rules().size(); ++index) {
        const auto& rule = model.rules()[index];
        std::string diagnostic;
        if (rule.forward().rateLaw.has_value() &&
            rule.forward().rateLaw->kind == bng::compile::RateLawKind::ArrheniusEnergy) {
            if (!addCompiledArrheniusDirection(
                    model, rule, rule.forward(), *system, blockSameComplexBinding,
                    verbose, suggestedTraversalLimit, diagnostic)) {
                std::cerr << "[nfsim/compiled] reaction '" << rule.name()
                          << "' requires compatibility lowering: " << diagnostic << "\n";
                return false;
            }
            continue;
        }
        if (!lowerDirection(model, rule, rule.forward(), false, *system,
                            blockSameComplexBinding, verbose,
                            suggestedTraversalLimit, sourcePath,
                            index * 2, diagnostic)) {
            std::cerr << "[nfsim/compiled] reaction '" << rule.name()
                      << "' requires compatibility lowering: " << diagnostic << "\n";
            return false;
        }
        if (rule.reverse().has_value() &&
            !lowerDirection(model, rule, *rule.reverse(), true, *system,
                            blockSameComplexBinding, verbose,
                            suggestedTraversalLimit, sourcePath,
                            index * 2 + 1, diagnostic)) {
            std::cerr << "[nfsim/compiled] reverse reaction '" << rule.name()
                      << "' requires compatibility lowering: " << diagnostic << "\n";
            return false;
        }
    }
    return true;
}

} // namespace NFinput
