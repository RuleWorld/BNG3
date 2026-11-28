#include "nfnext/from_bng.hpp"

#include "compile/CompiledModel.hpp"
#include "compile/RuleUnitConversion.hpp"
#include "compile/energy/BarrierTable.hpp"
#include "compile/energy/DrivenEnergy.hpp"
#include "nfnext/compiler.hpp"
#include "nfnext/counter_rng.hpp"
#include "nfnext/function_vm.hpp"
#include "nfnext/generic_matcher.hpp"
#include "nfnext/transformation.hpp"
#include "units/Unit.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <functional>
#include <limits>
#include <map>
#include <optional>
#include <queue>
#include <set>
#include <sstream>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace nfnext {
namespace {

using BngPattern = bng::compile::Pattern;
using BngPatternSide = bng::compile::PatternSide;
using BngMutationKind = bng::compile::MutationKind;

using BondEndpoint = std::tuple<std::size_t, std::size_t, std::size_t>;

// Delayed semantics are owned by the native DDE method-of-steps / delayed-SSA
// engines.  NFnext lowering does not carry a pending-completion queue, so a
// delayed rule lowered here would silently execute as an immediate reaction.
// Fail closed on any delay call so the runner never reports a wrong trajectory.
bool resolvedExpressionUsesDelay(const bng::compile::ResolvedExpression& expression) {
    if (expression.kind == bng::compile::ResolvedExpressionKind::BuiltinCall &&
        expression.builtin == bng::compile::BuiltinFunction::Delay) {
        return true;
    }
    for (const auto& argument : expression.arguments) {
        if (resolvedExpressionUsesDelay(argument)) return true;
    }
    return false;
}

std::vector<bng::compile::PatternBondDescriptor> patternBonds(
    const bng::compile::PatternSiteDescriptor& site) {
    if (!site.bondConstraints.empty()) return site.bondConstraints;
    return {{site.bondConstraint, site.bondKind, site.bondGroup}};
}

bng::compile::BondConstraintKind normalizedBondKind(
    bng::compile::BondConstraintKind kind) {
    return kind == bng::compile::BondConstraintKind::Unspecified
               ? bng::compile::BondConstraintKind::Unbound
               : kind;
}

bool moleculePatternShapeMatches(const BngPattern& left, std::size_t leftIndex,
                                 const BngPattern& right, std::size_t rightIndex) {
    const auto& leftMolecule = left.molecules()[leftIndex];
    const auto& rightMolecule = right.molecules()[rightIndex];
    const auto leftCompartment = leftMolecule.compartment.empty()
                                     ? left.compartment()
                                     : leftMolecule.compartment;
    const auto rightCompartment = rightMolecule.compartment.empty()
                                      ? right.compartment()
                                      : rightMolecule.compartment;
    if (leftMolecule.moleculeType != rightMolecule.moleculeType ||
        leftCompartment != rightCompartment ||
        leftMolecule.sites.size() != rightMolecule.sites.size())
        return false;
    for (std::size_t siteIndex = 0; siteIndex < leftMolecule.sites.size(); ++siteIndex) {
        const auto& leftSite = leftMolecule.sites[siteIndex];
        const auto& rightSite = rightMolecule.sites[siteIndex];
        if (leftSite.componentName != rightSite.componentName ||
            leftSite.stateConstraint != rightSite.stateConstraint ||
            leftSite.label != rightSite.label)
            return false;
        const auto leftBonds = patternBonds(leftSite);
        const auto rightBonds = patternBonds(rightSite);
        if (leftBonds.size() != rightBonds.size()) return false;
        for (std::size_t bondIndex = 0; bondIndex < leftBonds.size(); ++bondIndex) {
            if (normalizedBondKind(leftBonds[bondIndex].kind) !=
                normalizedBondKind(rightBonds[bondIndex].kind))
                return false;
        }
    }
    return true;
}

bool exactBondRelationMatches(const BngPattern& left, const BngPattern& right,
                              const std::vector<std::size_t>& mapping,
                              const std::vector<bool>& assigned) {
    for (std::size_t leftMolecule = 0; leftMolecule < mapping.size(); ++leftMolecule) {
        if (!assigned[leftMolecule]) continue;
        for (std::size_t rightMolecule = 0; rightMolecule <= leftMolecule;
             ++rightMolecule) {
            if (!assigned[rightMolecule]) continue;
            const auto& leftSites = left.molecules()[leftMolecule].sites;
            const auto& rightSites = right.molecules()[mapping[leftMolecule]].sites;
            const auto& leftOtherSites = left.molecules()[rightMolecule].sites;
            const auto& rightOtherSites = right.molecules()[mapping[rightMolecule]].sites;
            for (std::size_t site = 0; site < leftSites.size(); ++site) {
                const auto leftBonds = patternBonds(leftSites[site]);
                const auto rightBonds = patternBonds(rightSites[site]);
                for (std::size_t otherSite = 0; otherSite < leftOtherSites.size();
                     ++otherSite) {
                    const auto leftOtherBonds = patternBonds(leftOtherSites[otherSite]);
                    const auto rightOtherBonds = patternBonds(rightOtherSites[otherSite]);
                    for (std::size_t bond = 0; bond < leftBonds.size(); ++bond) {
                        if (leftBonds[bond].kind != bng::compile::BondConstraintKind::Exact)
                            continue;
                        for (std::size_t otherBond = 0;
                             otherBond < leftOtherBonds.size(); ++otherBond) {
                            if (leftOtherBonds[otherBond].kind !=
                                bng::compile::BondConstraintKind::Exact)
                                continue;
                            const bool sameLeft =
                                leftBonds[bond].group.value ==
                                leftOtherBonds[otherBond].group.value;
                            const bool sameRight =
                                rightBonds[bond].group.value ==
                                rightOtherBonds[otherBond].group.value;
                            if (sameLeft != sameRight) return false;
                        }
                    }
                }
            }
        }
    }
    return true;
}

std::optional<std::vector<std::size_t>> patternMoleculeMapping(
    const BngPattern& left, const BngPattern& right) {
    if (left.molecules().size() != right.molecules().size() ||
        left.compartmentIsPrefix() != right.compartmentIsPrefix())
        return std::nullopt;
    const std::size_t count = left.molecules().size();
    if (left == right) {
        std::vector<std::size_t> identity(count);
        for (std::size_t index = 0; index < count; ++index) identity[index] = index;
        return identity;
    }

    std::vector<std::vector<std::size_t>> candidates(count);
    std::vector<std::size_t> order(count);
    for (std::size_t leftIndex = 0; leftIndex < count; ++leftIndex) {
        order[leftIndex] = leftIndex;
        for (std::size_t rightIndex = 0; rightIndex < count; ++rightIndex) {
            if (moleculePatternShapeMatches(left, leftIndex, right, rightIndex))
                candidates[leftIndex].push_back(rightIndex);
        }
        if (candidates[leftIndex].empty()) return std::nullopt;
    }
    std::stable_sort(order.begin(), order.end(), [&](auto first, auto second) {
        return candidates[first].size() < candidates[second].size();
    });

    std::vector<std::size_t> mapping(count, 0);
    std::vector<bool> assigned(count, false);
    std::vector<bool> used(count, false);
    std::function<bool(std::size_t)> visit = [&](std::size_t depth) {
        if (depth == count) return true;
        const auto leftIndex = order[depth];
        for (const auto rightIndex : candidates[leftIndex]) {
            if (used[rightIndex]) continue;
            mapping[leftIndex] = rightIndex;
            assigned[leftIndex] = true;
            used[rightIndex] = true;
            if (exactBondRelationMatches(left, right, mapping, assigned) &&
                visit(depth + 1))
                return true;
            assigned[leftIndex] = false;
            used[rightIndex] = false;
        }
        return false;
    };
    if (!visit(0)) return std::nullopt;
    return mapping;
}

void issue(BngLoweringResult& result, BngLoweringSeverity severity,
           std::string entity, std::string message) {
    result.issues.push_back({severity, std::move(entity), std::move(message)});
}

bool validateNFnextIdPacking(const bng::compile::CompiledModel& source,
                             BngLoweringResult& result) {
    for (std::size_t moleculeIndex = 0;
         moleculeIndex < source.moleculeTypes().size(); ++moleculeIndex) {
        const auto& molecule = source.moleculeTypes()[moleculeIndex];
        if (!molecule.id.valid() || molecule.id.value() != moleculeIndex ||
            molecule.index != moleculeIndex || source.moleculeType(molecule.id) != &molecule) {
            issue(result, BngLoweringSeverity::Error, molecule.name,
                  "molecule type ID is not its canonical declaration index");
            return false;
        }
        if (moleculeIndex > static_cast<std::size_t>(std::numeric_limits<TypeId>::max())) {
            issue(result, BngLoweringSeverity::Error, molecule.name,
                  "molecule type index exceeds NFIR v5 uint32 type capacity");
            return false;
        }

        for (std::size_t componentIndex = 0;
             componentIndex < molecule.components.size(); ++componentIndex) {
            const auto& component = molecule.components[componentIndex];
            const auto entity = molecule.name + "." + component.name;
            if (!component.id.valid() || component.id.moleculeType != molecule.id ||
                component.id.index != componentIndex ||
                source.component(component.id) != &component) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "component ID is not its canonical molecule-local declaration index");
                return false;
            }
            if (componentIndex > static_cast<std::size_t>(
                                    std::numeric_limits<std::uint16_t>::max())) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "component index exceeds NFIR v5 uint16 site capacity");
                return false;
            }

            for (std::size_t stateIndex = 0;
                 stateIndex < component.stateNames.size(); ++stateIndex) {
                if (stateIndex > static_cast<std::size_t>(
                                     std::numeric_limits<std::int32_t>::max()) ||
                    source.stateName({component.id, stateIndex}) == nullptr) {
                    issue(result, BngLoweringSeverity::Error, entity,
                          "state ID is not representable by NFIR v5 int32 state values");
                    return false;
                }
            }
        }
    }
    return true;
}

std::optional<double> constantExpression(
    const bng::compile::ResolvedExpression& expression,
    const bng::compile::CompiledModel& model) {
    using Kind = bng::compile::ResolvedExpressionKind;
    using Unary = bng::compile::UnaryOp;
    using Binary = bng::compile::BinaryOp;
    using Builtin = bng::compile::BuiltinFunction;

    switch (expression.kind) {
    case Kind::Number:
        return expression.numberValue;
    case Kind::ParameterRef:
        if (expression.symbol && expression.symbol->kind == bng::compile::SymbolKind::Parameter) {
            const auto* parameter = model.parameter(
                bng::compile::ParameterId::fromDenseIndex(expression.symbol->index));
            if (parameter && !parameter->timeDependent && parameter->constantValue)
                return parameter->constantValue;
        }
        return std::nullopt;
    case Kind::Unary: {
        if (expression.arguments.size() != 1 || !expression.unaryOp) return std::nullopt;
        const auto value = constantExpression(expression.arguments.front(), model);
        if (!value) return std::nullopt;
        switch (*expression.unaryOp) {
        case Unary::Plus: return *value;
        case Unary::Negate: return -*value;
        case Unary::LogicalNot: return *value == 0.0 ? 1.0 : 0.0;
        case Unary::Unknown: return std::nullopt;
        }
        return std::nullopt;
    }
    case Kind::Binary: {
        if (expression.arguments.size() != 2 || !expression.binaryOp) return std::nullopt;
        const auto left = constantExpression(expression.arguments[0], model);
        const auto right = constantExpression(expression.arguments[1], model);
        if (!left || !right) return std::nullopt;
        switch (*expression.binaryOp) {
        case Binary::Add: return *left + *right;
        case Binary::Subtract: return *left - *right;
        case Binary::Multiply: return *left * *right;
        case Binary::Divide: return *right == 0.0 ? std::nullopt : std::optional<double>(*left / *right);
        case Binary::Modulo: return *right == 0.0 ? std::nullopt : std::optional<double>(std::fmod(*left, *right));
        case Binary::Power: return std::pow(*left, *right);
        case Binary::Less: return *left < *right ? 1.0 : 0.0;
        case Binary::LessEqual: return *left <= *right ? 1.0 : 0.0;
        case Binary::Greater: return *left > *right ? 1.0 : 0.0;
        case Binary::GreaterEqual: return *left >= *right ? 1.0 : 0.0;
        case Binary::Equal: return *left == *right ? 1.0 : 0.0;
        case Binary::NotEqual: return *left != *right ? 1.0 : 0.0;
        case Binary::LogicalAnd: return (*left != 0.0 && *right != 0.0) ? 1.0 : 0.0;
        case Binary::LogicalOr: return (*left != 0.0 || *right != 0.0) ? 1.0 : 0.0;
        case Binary::LogicalXor: return ((*left != 0.0) != (*right != 0.0)) ? 1.0 : 0.0;
        case Binary::Unknown: return std::nullopt;
        }
        return std::nullopt;
    }
    case Kind::BuiltinCall: {
        if (!expression.builtin) return std::nullopt;
        std::vector<double> args;
        for (const auto& argument : expression.arguments) {
            const auto value = constantExpression(argument, model);
            if (!value) return std::nullopt;
            args.push_back(*value);
        }
        if (*expression.builtin == Builtin::Pi && args.empty()) return std::acos(-1.0);
        if (*expression.builtin == Builtin::E && args.empty()) return std::exp(1.0);
        if (args.size() == 1) {
            switch (*expression.builtin) {
            case Builtin::Abs: return std::fabs(args[0]);
            case Builtin::Exp: return std::exp(args[0]);
            case Builtin::Ln: return std::log(args[0]);
            case Builtin::Log10: return std::log10(args[0]);
            case Builtin::Log2: return std::log2(args[0]);
            case Builtin::Sqrt: return std::sqrt(args[0]);
            case Builtin::Sin: return std::sin(args[0]);
            case Builtin::Cos: return std::cos(args[0]);
            case Builtin::Tan: return std::tan(args[0]);
            case Builtin::Sinh: return std::sinh(args[0]);
            case Builtin::Cosh: return std::cosh(args[0]);
            case Builtin::Tanh: return std::tanh(args[0]);
            case Builtin::Floor: return std::floor(args[0]);
            case Builtin::Ceil: return std::ceil(args[0]);
            default: break;
            }
        }
        if (*expression.builtin == Builtin::Min && !args.empty()) {
            double value = args.front(); for (double arg : args) value = std::min(value, arg); return value;
        }
        if (*expression.builtin == Builtin::Max && !args.empty()) {
            double value = args.front(); for (double arg : args) value = std::max(value, arg); return value;
        }
        if ((*expression.builtin == Builtin::Sum || *expression.builtin == Builtin::Avg) && !args.empty()) {
            double value = 0.0; for (double arg : args) value += arg;
            return *expression.builtin == Builtin::Avg ? value / static_cast<double>(args.size()) : value;
        }
        if (*expression.builtin == Builtin::Arrhenius && args.size() >= 2) {
            // BNGL Arrhenius(phi, Ea): base rate exp(-Ea) in canonical RT==1
            // convention when no deltaG/barrier/driving modulation applies.
            return std::exp(-args[1]);
        }
        return std::nullopt;
    }
    default:
        return std::nullopt;
    }
}

std::optional<bng::compile::ResolvedExpression> expandZeroArgumentRateFunctions(
    const bng::compile::ResolvedExpression& expression,
    const bng::compile::CompiledModel& model,
    std::set<std::size_t>& activeFunctions) {
    using Kind = bng::compile::ResolvedExpressionKind;
    if (expression.kind == Kind::FunctionRef) {
        if (!expression.symbol ||
            expression.symbol->kind != bng::compile::SymbolKind::Function ||
            !expression.arguments.empty())
            return std::nullopt;
        const auto index = expression.symbol->index;
        const auto* function = model.function(
            bng::compile::FunctionId::fromDenseIndex(index));
        if (!function || function->id.value() != index ||
            !function->arguments.empty() || !activeFunctions.insert(index).second)
            return std::nullopt;
        auto expanded = expandZeroArgumentRateFunctions(
            function->expression, model, activeFunctions);
        activeFunctions.erase(index);
        return expanded;
    }
    auto expanded = expression;
    expanded.arguments.clear();
    expanded.arguments.reserve(expression.arguments.size());
    for (const auto& argument : expression.arguments) {
        auto child = expandZeroArgumentRateFunctions(
            argument, model, activeFunctions);
        if (!child) return std::nullopt;
        expanded.arguments.push_back(std::move(*child));
    }
    return expanded;
}

double energyFactorValue(const bng::compile::CompiledEnergyFactor& ep,
                         const bng::compile::CompiledModel& source) {
    if (ep.evaluatedValue) return *ep.evaluatedValue;
    std::set<std::size_t> activeFunctions;
    if (const auto expanded = expandZeroArgumentRateFunctions(
            source.expandFunctions(ep.expression), source, activeFunctions)) {
        if (const auto value = constantExpression(*expanded, source)) return *value;
    }
    if (const auto value = constantExpression(ep.expression, source)) return *value;
    return 0.0;
}

// A dynamic energy factor has no static value. Its expression must be
// evaluated against runtime state instead of being folded into a constant
// rate; folding it to zero would silently change the model semantics.
bool isDynamicEnergyFactor(const bng::compile::CompiledEnergyFactor& ep,
                           const bng::compile::CompiledModel& source) {
    if (ep.evaluatedValue) return false;
    std::set<std::size_t> activeFunctions;
    if (const auto expanded = expandZeroArgumentRateFunctions(
            source.expandFunctions(ep.expression), source, activeFunctions)) {
        if (constantExpression(*expanded, source)) return false;
    }
    return !constantExpression(ep.expression, source);
}

struct FlattenedPattern {
    PatternIR pattern;
    std::vector<std::size_t> patternOffsets;
};

std::optional<std::string> observableRateExpression(
    const bng::compile::ResolvedExpression& expression,
    const bng::compile::CompiledModel& model,
    std::set<std::size_t>& observableIds,
    const std::vector<bng::compile::CompiledLocalScope>* localScopes = nullptr,
    const FlattenedPattern* flattened = nullptr,
    std::vector<LocalObservableBinding>* localBindings = nullptr) {
    using Kind = bng::compile::ResolvedExpressionKind;
    using Unary = bng::compile::UnaryOp;
    using Binary = bng::compile::BinaryOp;

    if (const auto constant = constantExpression(expression, model)) {
        if (!std::isfinite(*constant)) return std::nullopt;
        std::ostringstream out;
        out.precision(17);
        out << *constant;
        return out.str();
    }
    switch (expression.kind) {
    case Kind::ObservableRef: {
        if (!expression.symbol ||
            expression.symbol->kind != bng::compile::SymbolKind::Observable)
            return std::nullopt;
        const auto index = expression.symbol->index;
        const auto* observable = model.observable(
            bng::compile::ObservableId::fromDenseIndex(index));
        if (!observable || observable->id.value() != index ||
            (observable->kind != bng::compile::ObservableKind::Molecules &&
             observable->kind != bng::compile::ObservableKind::Species))
            return std::nullopt;
        if (!expression.arguments.empty()) {
            // Local observable reference: must bind to a reactant local scope.
            if (expression.arguments.size() != 1 ||
                expression.arguments.front().kind != Kind::LocalRef ||
                localScopes == nullptr || flattened == nullptr || localBindings == nullptr) {
                return std::nullopt;
            }
            const auto& localName = expression.arguments.front().localName;
            const bng::compile::CompiledLocalScope* matchedScope = nullptr;
            for (const auto& scope : *localScopes) {
                if (scope.name == localName && scope.side == BngPatternSide::Reactant) {
                    matchedScope = &scope;
                    break;
                }
            }
            if (!matchedScope || matchedScope->patternIndex >= flattened->patternOffsets.size()) {
                return std::nullopt;
            }
            const bool isMolScope =
                matchedScope->kind == bng::compile::LocalScopeKind::Molecule;
            const std::size_t reactantNode =
                flattened->patternOffsets[matchedScope->patternIndex] +
                (isMolScope ? matchedScope->moleculeOccurrence.value_or(0) : 0);
            if (reactantNode >= flattened->pattern.nodes.size()) return std::nullopt;
            for (const auto& existing : *localBindings) {
                if (existing.observable_index == index &&
                    existing.reactant_node == reactantNode &&
                    existing.molecule_scope == isMolScope) {
                    return "local_obs_" + std::to_string(existing.slot);
                }
            }
            const auto slot = static_cast<std::uint32_t>(localBindings->size());
            localBindings->push_back(LocalObservableBinding{slot, index, reactantNode, isMolScope});
            return "local_obs_" + std::to_string(slot);
        }
        observableIds.insert(index);
        return "observable_" + std::to_string(index);
    }
    case Kind::Unary: {
        if (!expression.unaryOp || expression.arguments.size() != 1)
            return std::nullopt;
        const auto child = observableRateExpression(
            expression.arguments.front(), model, observableIds,
            localScopes, flattened, localBindings);
        if (!child) return std::nullopt;
        if (*expression.unaryOp == Unary::Negate) return "(-" + *child + ")";
        if (*expression.unaryOp == Unary::Plus) return "(" + *child + ")";
        if (*expression.unaryOp == Unary::LogicalNot) return "if(" + *child + ",0,1)";
        return std::nullopt;
    }
    case Kind::Binary: {
        if (!expression.binaryOp || expression.arguments.size() != 2)
            return std::nullopt;
        const auto left = observableRateExpression(
            expression.arguments[0], model, observableIds,
            localScopes, flattened, localBindings);
        const auto right = observableRateExpression(
            expression.arguments[1], model, observableIds,
            localScopes, flattened, localBindings);
        if (!left || !right) return std::nullopt;
        if (*expression.binaryOp == Binary::LogicalAnd) {
            return "if(" + *left + ",if(" + *right + ",1,0),0)";
        }
        if (*expression.binaryOp == Binary::LogicalOr) {
            return "if(" + *left + ",1,if(" + *right + ",1,0))";
        }
        if (*expression.binaryOp == Binary::LogicalXor) {
            return "if(" + *left + ",if(" + *right + ",0,1),if(" + *right + ",1,0))";
        }
        const char* operation = nullptr;
        switch (*expression.binaryOp) {
        case Binary::Add: operation = "+"; break;
        case Binary::Subtract: operation = "-"; break;
        case Binary::Multiply: operation = "*"; break;
        case Binary::Divide: operation = "/"; break;
        case Binary::Power: operation = "^"; break;
        case Binary::Less: operation = "<"; break;
        case Binary::LessEqual: operation = "<="; break;
        case Binary::Greater: operation = ">"; break;
        case Binary::GreaterEqual: operation = ">="; break;
        case Binary::Equal: operation = "=="; break;
        case Binary::NotEqual: operation = "!="; break;
        default: return std::nullopt;
        }
        return "(" + *left + operation + *right + ")";
    }
    case Kind::BuiltinCall: {
        if (!expression.builtin) return std::nullopt;
        if (*expression.builtin == bng::compile::BuiltinFunction::Log10 &&
            expression.arguments.size() == 1) {
            const auto child = observableRateExpression(
                expression.arguments.front(), model, observableIds,
                localScopes, flattened, localBindings);
            if (!child) return std::nullopt;
            return "(log(" + *child + ")/log(10))";
        }
        if (*expression.builtin == bng::compile::BuiltinFunction::Log2 &&
            expression.arguments.size() == 1) {
            const auto child = observableRateExpression(
                expression.arguments.front(), model, observableIds,
                localScopes, flattened, localBindings);
            if (!child) return std::nullopt;
            return "(log(" + *child + ")/log(2))";
        }
        const char* name = nullptr;
        std::size_t arity = 0;
        switch (*expression.builtin) {
        case bng::compile::BuiltinFunction::Exp: name = "exp"; arity = 1; break;
        case bng::compile::BuiltinFunction::Ln: name = "log"; arity = 1; break;
        case bng::compile::BuiltinFunction::Sqrt: name = "sqrt"; arity = 1; break;
        case bng::compile::BuiltinFunction::Sin: name = "sin"; arity = 1; break;
        case bng::compile::BuiltinFunction::Cos: name = "cos"; arity = 1; break;
        case bng::compile::BuiltinFunction::Tan: name = "tan"; arity = 1; break;
        case bng::compile::BuiltinFunction::Abs: name = "abs"; arity = 1; break;
        case bng::compile::BuiltinFunction::Min: name = "min"; arity = 2; break;
        case bng::compile::BuiltinFunction::Max: name = "max"; arity = 2; break;
        case bng::compile::BuiltinFunction::If: name = "if"; arity = 3; break;
        default:
            // Builtins without a FunctionVM counterpart (time, delay, tables,
            // variadic reductions) stay unrepresentable rather than being
            // approximated.
            return std::nullopt;
        }
        if (expression.arguments.size() != arity) return std::nullopt;
        std::vector<std::string> arguments;
        arguments.reserve(arity);
        for (const auto& argument : expression.arguments) {
            const auto child = observableRateExpression(
                argument, model, observableIds,
                localScopes, flattened, localBindings);
            if (!child) return std::nullopt;
            arguments.push_back(*child);
        }
        std::ostringstream out;
        out << name << '(';
        for (std::size_t i = 0; i < arguments.size(); ++i) {
            if (i != 0) out << ',';
            out << arguments[i];
        }
        out << ')';
        return out.str();
    }
    default:
        return std::nullopt;
    }
}

bool appendPattern(const BngPattern& source, PatternIR& destination,
                   BngLoweringResult& result, const std::string& entity,
                   std::size_t& firstNode,
                   bool unspecifiedBondIsUnbound = false,
                   const bng::compile::CompiledModel* sourceModel = nullptr) {
    if (!source.isResolved()) {
        issue(result, BngLoweringSeverity::Error, entity,
              "pattern is not fully symbol-resolved");
        return false;
    }
    std::optional<CompartmentId> patternCompId;
    bool isSurfaceSpeciesPrefix = false;
    if (source.compartmentId().has_value()) {
        patternCompId = static_cast<CompartmentId>(source.compartmentId()->value());
        if (sourceModel && source.compartmentIsPrefix()) {
            const auto* comp = sourceModel->compartment(*source.compartmentId());
            if (comp && comp->dimension == 2) {
                isSurfaceSpeciesPrefix = true;
            }
        }
    }
    firstNode = destination.nodes.size();
    std::map<std::size_t, std::vector<std::pair<std::size_t, std::uint32_t>>> exactBonds;
    for (const auto& molecule : source.molecules()) {
        if (!molecule.moleculeTypeId) {
            issue(result, BngLoweringSeverity::Error, entity, "pattern molecule has no typed molecule ID");
            return false;
        }
        const auto node = destination.addNode(static_cast<TypeId>(molecule.moleculeTypeId->value()));
        std::optional<CompartmentId> molCompId;
        if (!molecule.compartment.empty() && molecule.compartmentId.has_value()) {
            molCompId = static_cast<CompartmentId>(molecule.compartmentId->value());
        } else if (!isSurfaceSpeciesPrefix) {
            molCompId = molecule.compartmentId.has_value()
                ? std::optional<CompartmentId>(static_cast<CompartmentId>(molecule.compartmentId->value()))
                : patternCompId;
        }
        destination.node(node).compartment = molCompId;
        const auto* molDecl = sourceModel ? sourceModel->moleculeType(*molecule.moleculeTypeId) : nullptr;
        for (const auto& site : molecule.sites) {
            if (!site.componentType) {
                issue(result, BngLoweringSeverity::Error, entity, "pattern site has no typed component ID");
                return false;
            }
            const auto siteIndex = static_cast<std::uint32_t>(site.componentType->index);
            bool emittedConstraintOrBond = false;
            const auto& state = site.stateConstraintResolved;
            if (state.kind == bng::compile::StateConstraintKind::Exact) {
                if (!state.exact) {
                    issue(result, BngLoweringSeverity::Error, entity, "exact state constraint has no state ID");
                    return false;
                }
                destination.node(node).siteState(siteIndex, static_cast<std::int32_t>(state.exact->index));
                emittedConstraintOrBond = true;
            } else if (state.kind == bng::compile::StateConstraintKind::Set) {
                std::vector<std::int32_t> states;
                for (const auto& value : state.states) states.push_back(static_cast<std::int32_t>(value.index));
                if (states.empty()) {
                    issue(result, BngLoweringSeverity::Error, entity, "empty state-set constraint");
                    return false;
                }
                destination.node(node).siteStateSet(siteIndex, std::move(states));
                emittedConstraintOrBond = true;
            }

            const auto bonds = site.bondConstraints.empty()
                ? std::vector<bng::compile::PatternBondDescriptor>{
                      {site.bondConstraint, site.bondKind, site.bondGroup}}
                : site.bondConstraints;
            for (const auto& bond : bonds) {
                switch (bond.kind) {
                case bng::compile::BondConstraintKind::Unspecified:
                    if (unspecifiedBondIsUnbound) {
                        destination.node(node).siteFree(siteIndex);
                        emittedConstraintOrBond = true;
                    }
                    break;
                case bng::compile::BondConstraintKind::Any:
                    break;
                case bng::compile::BondConstraintKind::Unbound:
                    destination.node(node).siteFree(siteIndex);
                    emittedConstraintOrBond = true;
                    break;
                case bng::compile::BondConstraintKind::Bound:
                    destination.node(node).siteBound(siteIndex);
                    emittedConstraintOrBond = true;
                    break;
                case bng::compile::BondConstraintKind::Exact:
                    exactBonds[bond.group.value].push_back({node, siteIndex});
                    emittedConstraintOrBond = true;
                    break;
                }
            }
            // Safeguard for duplicate-named stateful sites with wildcard state & bond (e.g. A(p~?!?)):
            // emit a full StateSet so GenericMatcher enumerates all equivalent site instances.
            if (!emittedConstraintOrBond && molDecl != nullptr &&
                siteIndex < molDecl->components.size() &&
                !molDecl->components[siteIndex].stateNames.empty()) {
                std::size_t sameNameCount = 0;
                for (const auto& c : molDecl->components) {
                    if (c.name == molDecl->components[siteIndex].name) ++sameNameCount;
                }
                if (sameNameCount > 1) {
                    std::vector<std::int32_t> allStates;
                    allStates.reserve(molDecl->components[siteIndex].stateNames.size());
                    for (std::size_t si = 0; si < molDecl->components[siteIndex].stateNames.size(); ++si) {
                        allStates.push_back(static_cast<std::int32_t>(si));
                    }
                    destination.node(node).siteStateSet(siteIndex, std::move(allStates));
                }
            }
        }
    }
    if (isSurfaceSpeciesPrefix && !source.molecules().empty()) {
        destination.species_compartments.emplace_back(firstNode, *patternCompId);
    }
    for (const auto& [group, endpoints] : exactBonds) {
        if (endpoints.size() != 2) {
            std::ostringstream message;
            message << "exact bond group " << group << " has " << endpoints.size()
                    << " endpoints; NFIR requires exactly two";
            issue(result, BngLoweringSeverity::Error, entity, message.str());
            return false;
        }
        destination.requireBond(endpoints[0].first, endpoints[0].second,
                                endpoints[1].first, endpoints[1].second);
    }
    // A single BNGL pattern denotes one complex even when some bonds are
    // unspecified. Preserve that relation; '+' boundaries are added separately
    // by flattenReactants as DifferentComplex constraints.
    for (std::size_t moleculeOffset = 1;
         moleculeOffset < source.molecules().size(); ++moleculeOffset) {
        destination.requireSameComplex(firstNode, firstNode + moleculeOffset);
    }
    return true;
}

std::optional<FlattenedPattern> flattenReactants(
    const std::vector<BngPattern>& patterns, BngLoweringResult& result,
    const std::string& entity, bool unspecifiedBondIsUnbound = false,
    const bng::compile::CompiledModel* sourceModel = nullptr) {
    const auto maxNodeIndex = static_cast<std::size_t>(
        std::numeric_limits<std::uint16_t>::max());
    const auto maxNodeCount = maxNodeIndex + 1;
    std::size_t nodeCount = 0;
    for (const auto& pattern : patterns) {
        const auto patternNodeCount = pattern.molecules().size();
        if (patternNodeCount > maxNodeCount - nodeCount) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "reactant pattern node index exceeds NFIR v5 uint16 molecularity capacity");
            return std::nullopt;
        }
        nodeCount += patternNodeCount;
    }

    FlattenedPattern flattened;
    flattened.patternOffsets.reserve(patterns.size());
    std::vector<std::size_t> representatives;
    for (const auto& pattern : patterns) {
        std::size_t first = 0;
        flattened.patternOffsets.push_back(flattened.pattern.nodes.size());
        if (!appendPattern(pattern, flattened.pattern, result, entity, first,
                           unspecifiedBondIsUnbound, sourceModel))
            return std::nullopt;
        representatives.push_back(first);
    }
    // A '+' between reactant patterns denotes distinct reactant complexes.
    for (std::size_t i = 0; i < patterns.size(); ++i) {
        if (patterns[i].molecules().empty()) continue;
        for (std::size_t j = i + 1; j < patterns.size(); ++j) {
            if (patterns[j].molecules().empty()) continue;
            flattened.pattern.requireDifferentComplex(representatives[i], representatives[j]);
        }
    }
    return flattened;
}

std::optional<PatternNodeId> nodeFor(const bng::compile::PatternMoleculeRef& ref,
                                     const FlattenedPattern& pattern) {
    if (ref.side != BngPatternSide::Reactant || ref.patternIndex >= pattern.patternOffsets.size())
        return std::nullopt;
    return static_cast<PatternNodeId>(pattern.patternOffsets[ref.patternIndex] + ref.moleculeIndex);
}

std::optional<PatternNodeId> nodeFor(const bng::compile::PatternSiteRef& ref,
                                     const FlattenedPattern& pattern) {
    return nodeFor(bng::compile::PatternMoleculeRef{ref.side, ref.patternIndex, ref.moleculeIndex}, pattern);
}

void addPredicates(const PatternIR& pattern, std::vector<PredicateIR>& predicates) {
    for (std::size_t nodeIndex = 0; nodeIndex < pattern.nodes.size(); ++nodeIndex) {
        const auto& node = pattern.nodes[nodeIndex];
        for (const auto& constraint : node.constraints) {
            PredicateIR predicate;
            predicate.node = static_cast<PatternNodeId>(nodeIndex);
            predicate.molecule_type = node.molecule_type;
            predicate.site = static_cast<std::uint16_t>(constraint.site);
            switch (constraint.kind) {
            case PatternIR::SiteConstraintKind::State:
                predicate.kind = PredicateKind::SiteStateEq;
                predicate.value = constraint.state;
                break;
            case PatternIR::SiteConstraintKind::StateSet:
                predicate.kind = PredicateKind::SiteStateEq;
                predicate.state_set = constraint.states;
                break;
            case PatternIR::SiteConstraintKind::Free:
                predicate.kind = PredicateKind::SiteFree;
                break;
            case PatternIR::SiteConstraintKind::Bound:
                predicate.kind = PredicateKind::SiteBound;
                break;
            }
            predicates.push_back(std::move(predicate));
        }
    }
}

using MoleculeKey = std::pair<std::size_t, std::size_t>;

struct DirectionNodeMap {
    std::map<MoleculeKey, PatternNodeId> productNodes;
    std::set<MoleculeKey> createdProducts;
    std::set<PatternNodeId> mappedReactants;
};

std::vector<std::pair<bng::compile::PatternMoleculeRef,
                      bng::compile::PatternMoleculeRef>>
directionMoleculeMappings(const bng::compile::CompiledRule& rule,
                          bool reverseDirection) {
    std::vector<std::pair<bng::compile::PatternMoleculeRef,
                          bng::compile::PatternMoleculeRef>> mappings;
    mappings.reserve(rule.moleculeMappings().size());
    for (const auto& [forwardProduct, forwardReactant] : rule.moleculeMappings()) {
        if (!reverseDirection) {
            mappings.push_back({
                {BngPatternSide::Product, forwardProduct.patternIndex, forwardProduct.moleculeIndex},
                {BngPatternSide::Reactant, forwardReactant.patternIndex, forwardReactant.moleculeIndex}});
        } else {
            mappings.push_back({
                {BngPatternSide::Product, forwardReactant.patternIndex, forwardReactant.moleculeIndex},
                {BngPatternSide::Reactant, forwardProduct.patternIndex, forwardProduct.moleculeIndex}});
        }
    }
    return mappings;
}

std::optional<DirectionNodeMap> buildDirectionNodeMap(
    const bng::compile::CompiledRule& rule,
    const bng::compile::CompiledRuleDirection& direction,
    const FlattenedPattern& reactants,
    bool reverseDirection,
    BngLoweringResult& result,
    const std::string& entity) {
    DirectionNodeMap nodes;
    for (const auto& [productRef, reactantRef] :
         directionMoleculeMappings(rule, reverseDirection)) {
        const auto reactantNode = nodeFor(reactantRef, reactants);
        if (!reactantNode) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "molecule identity mapping references an unknown reactant node");
            return std::nullopt;
        }
        const MoleculeKey key{productRef.patternIndex, productRef.moleculeIndex};
        if (!nodes.productNodes.emplace(key, *reactantNode).second) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "multiple molecule mappings target the same product occurrence");
            return std::nullopt;
        }
        nodes.mappedReactants.insert(*reactantNode);
    }

    PatternNodeId nextCreated = static_cast<PatternNodeId>(reactants.pattern.nodes.size());
    for (std::size_t patternIndex = 0; patternIndex < direction.productPatterns.size(); ++patternIndex) {
        const auto& pattern = direction.productPatterns[patternIndex];
        for (std::size_t moleculeIndex = 0; moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
            const MoleculeKey key{patternIndex, moleculeIndex};
            if (nodes.productNodes.count(key) != 0) continue;
            nodes.productNodes.emplace(key, nextCreated++);
            nodes.createdProducts.insert(key);
        }
    }
    return nodes;
}

bool appendCreateActions(
    const bng::compile::CompiledRuleDirection& direction,
    const bng::compile::CompiledModel& source,
    const FlattenedPattern& reactants,
    const DirectionNodeMap& nodes,
    std::vector<ActionIR>& actions,
    std::vector<std::pair<PatternNodeId, PatternNodeId>>& createdCompartmentInherit,
    BngLoweringResult& result,
    const std::string& entity) {
    const auto effectiveMolComp = [&](const BngPattern& pat,
                                      const bng::compile::PatternMoleculeDescriptor& mol)
        -> std::optional<bng::compile::CompartmentId> {
        if (!mol.compartment.empty() && mol.compartmentId) return mol.compartmentId;
        if (pat.compartmentId()) {
            const auto* c = source.compartment(*pat.compartmentId());
            if (c && c->dimension == 2 && pat.compartmentIsPrefix()) return std::nullopt;
            return pat.compartmentId();
        }
        return std::nullopt;
    };
    const std::size_t reactantNodeCount = reactants.pattern.nodes.size();
    for (const auto& key : nodes.createdProducts) {
        if (key.first >= direction.productPatterns.size() ||
            key.second >= direction.productPatterns[key.first].molecules().size()) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "created molecule occurrence is outside the product pattern");
            return false;
        }
        const auto& prodPattern = direction.productPatterns[key.first];
        const auto& molecule = prodPattern.molecules()[key.second];
        if (!molecule.moleculeTypeId) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "created product molecule has no typed molecule ID");
            return false;
        }
        ActionIR create;
        create.kind = ActionKind::Create;
        create.molecule_type = static_cast<TypeId>(molecule.moleculeTypeId->value());
        create.target_node = nodes.productNodes.at(key);
        actions.push_back(create);

        auto compId = effectiveMolComp(prodPattern, molecule);
        if (!compId && !source.compartments().empty()) {
            // Check if a surviving reactant in the same product pattern has an explicit compartment.
            std::optional<PatternNodeId> samePatternReactant;
            for (std::size_t mi = 0; mi < prodPattern.molecules().size(); ++mi) {
                const MoleculeKey sibling{key.first, mi};
                if (nodes.createdProducts.count(sibling) != 0) continue;
                const auto siblingComp = effectiveMolComp(prodPattern, prodPattern.molecules()[mi]);
                if (siblingComp) {
                    compId = siblingComp;
                    break;
                }
                const auto it = nodes.productNodes.find(sibling);
                if (it != nodes.productNodes.end() && it->second < reactantNodeCount &&
                    !samePatternReactant.has_value()) {
                    samePatternReactant = it->second;
                }
            }
            if (!compId) {
                if (samePatternReactant.has_value()) {
                    createdCompartmentInherit.emplace_back(create.target_node, *samePatternReactant);
                } else if (reactantNodeCount > 0) {
                    // Inherit from the first non-population reactant node (or node 0).
                    PatternNodeId donor = 0;
                    for (std::size_t ni = 0; ni < reactantNodeCount; ++ni) {
                        const auto* mt = source.moleculeType(
                            bng::compile::MoleculeTypeId::fromDenseIndex(
                                static_cast<std::size_t>(reactants.pattern.nodes[ni].molecule_type)));
                        if (mt && !mt->population) {
                            donor = static_cast<PatternNodeId>(ni);
                            break;
                        }
                    }
                    createdCompartmentInherit.emplace_back(create.target_node, donor);
                }
            }
        }
        if (compId) {
            ActionIR setComp;
            setComp.kind = ActionKind::SetCompartment;
            setComp.target_node = create.target_node;
            setComp.molecule_type = create.molecule_type;
            setComp.value = static_cast<std::int32_t>(compId->value());
            actions.push_back(std::move(setComp));
        }

        for (const auto& site : molecule.sites) {
            if (!site.componentType) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "created product molecule has an unresolved component");
                return false;
            }
            const auto& state = site.stateConstraintResolved;
            if (state.kind == bng::compile::StateConstraintKind::Set) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "created product molecule has a non-deterministic state-set constraint");
                return false;
            }
            if (state.kind != bng::compile::StateConstraintKind::Exact) continue;
            if (!state.exact) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "created product molecule exact state is unresolved");
                return false;
            }
            ActionIR setState;
            setState.kind = ActionKind::SetSiteState;
            setState.target_node = create.target_node;
            setState.molecule_type = create.molecule_type;
            setState.site = static_cast<std::uint16_t>(site.componentType->index);
            setState.value = static_cast<std::int32_t>(state.exact->index);
            actions.push_back(std::move(setState));
        }
    }
    return true;
}

bool appendCreatedProductBonds(
    const bng::compile::CompiledRuleDirection& direction,
    const DirectionNodeMap& nodes,
    std::vector<ActionIR>& actions,
    BngLoweringResult& result,
    const std::string& entity) {
    struct Endpoint {
        MoleculeKey molecule;
        const bng::compile::PatternMoleculeDescriptor* moleculeDescriptor = nullptr;
        const bng::compile::PatternSiteDescriptor* site = nullptr;
    };

    for (std::size_t patternIndex = 0; patternIndex < direction.productPatterns.size(); ++patternIndex) {
        const auto& pattern = direction.productPatterns[patternIndex];
        std::map<std::size_t, std::vector<Endpoint>> bonds;
        for (std::size_t moleculeIndex = 0; moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
            const auto& molecule = pattern.molecules()[moleculeIndex];
            for (const auto& site : molecule.sites) {
                const auto descriptors = site.bondConstraints.empty()
                    ? std::vector<bng::compile::PatternBondDescriptor>{
                          {site.bondConstraint, site.bondKind, site.bondGroup}}
                    : site.bondConstraints;
                for (const auto& bond : descriptors) {
                    if (bond.kind == bng::compile::BondConstraintKind::Exact) {
                        bonds[bond.group.value].push_back(
                            Endpoint{{patternIndex, moleculeIndex}, &molecule, &site});
                    }
                }
            }
        }
        for (const auto& [group, endpoints] : bonds) {
            if (endpoints.size() != 2) {
                std::ostringstream message;
                message << "product exact bond group " << group << " has "
                        << endpoints.size() << " endpoints";
                issue(result, BngLoweringSeverity::Error, entity, message.str());
                return false;
            }
            const bool firstCreated = nodes.createdProducts.count(endpoints[0].molecule) != 0;
            const bool secondCreated = nodes.createdProducts.count(endpoints[1].molecule) != 0;
            if (!firstCreated && !secondCreated) continue; // ordinary AddBond mutation owns this case
            if (!endpoints[0].moleculeDescriptor->moleculeTypeId ||
                !endpoints[0].site->componentType || !endpoints[1].site->componentType) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "product bond involving a created molecule is not fully typed");
                return false;
            }
            ActionIR bond;
            bond.kind = ActionKind::Bind;
            bond.target_node = nodes.productNodes.at(endpoints[0].molecule);
            bond.partner_node = nodes.productNodes.at(endpoints[1].molecule);
            bond.molecule_type = static_cast<TypeId>(
                endpoints[0].moleculeDescriptor->moleculeTypeId->value());
            bond.site = static_cast<std::uint16_t>(endpoints[0].site->componentType->index);
            bond.partner_site = static_cast<std::uint16_t>(endpoints[1].site->componentType->index);
            actions.push_back(std::move(bond));
        }
    }
    return true;
}

bool hasDeleteMoleculesModifier(const bng::compile::CompiledRule& rule) {
    return std::any_of(rule.modifiers().begin(), rule.modifiers().end(), [](const auto& modifier) {
        return modifier.kind == bng::compile::ModifierKind::DeleteMolecules;
    });
}

bool isWholeSpeciesDeletion(const bng::compile::CompiledRuleDirection& direction,
                            std::size_t patternIndex) {
    return std::find(direction.wholeSpeciesDeletions.begin(),
                     direction.wholeSpeciesDeletions.end(), patternIndex) !=
           direction.wholeSpeciesDeletions.end();
}

bool appendDeletionActions(
    const bng::compile::CompiledRule& rule,
    const bng::compile::CompiledRuleDirection& direction,
    const FlattenedPattern& reactants,
    const DirectionNodeMap& nodes,
    std::vector<ActionIR>& actions,
    BngLoweringResult& result,
    const std::string& entity) {
    const bool pureDegradation = direction.productPatterns.empty();
    const bool deleteMolecules = hasDeleteMoleculesModifier(rule);

    const auto appendWholeSpeciesDeletion = [&](std::size_t patternIndex) {
        if (patternIndex >= direction.reactantPatterns.size() ||
            direction.reactantPatterns[patternIndex].molecules().empty()) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "whole-species deletion has no reactant complex representative");
            return false;
        }
        const bng::compile::PatternMoleculeRef ref{
            BngPatternSide::Reactant, patternIndex, 0};
        const auto node = nodeFor(ref, reactants);
        if (!node) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "whole-species deletion could not identify a reactant complex representative");
            return false;
        }
        const auto& molecule = direction.reactantPatterns[patternIndex].molecules().front();
        if (!molecule.moleculeTypeId) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "whole-species deletion representative is not typed");
            return false;
        }
        ActionIR destroy;
        destroy.kind = ActionKind::DestroyComplex;
        destroy.target_node = *node;
        destroy.molecule_type = static_cast<TypeId>(molecule.moleculeTypeId->value());
        actions.push_back(std::move(destroy));
        return true;
    };

    if (pureDegradation && !deleteMolecules) {
        // Standard BNGL degradation removes the matched reactant species/complex,
        // including context not explicitly present in the pattern. One action per
        // '+' reactant pattern is sufficient because each pattern is a distinct
        // reactant complex in NFIR.
        for (std::size_t patternIndex = 0; patternIndex < direction.reactantPatterns.size(); ++patternIndex) {
            if (direction.reactantPatterns[patternIndex].molecules().empty()) continue;
            if (!appendWholeSpeciesDeletion(patternIndex)) return false;
        }
        return true;
    }

    // A simultaneous unmatched deletion + creation is the legacy molecule-
    // replacement case. BioNetGen's mature network engine suppresses orphaned
    // context when a molecule is replaced inside a surviving complex without an
    // explicit cleanup program. NFIR v5 has no such implicit cleanup.
    //
    // Allow the case where every unmapped reactant molecule belongs to a reactant
    // pattern with no mapped/surviving molecules (the whole pattern is being
    // removed or replaced explicitly). In that situation deletion is fully
    // determined by explicit mutations/actions and there is no surviving context
    // that could be orphaned.
    bool hasOrphanRiskUnmappedReactant = false;
    for (std::size_t patternIndex = 0; patternIndex < direction.reactantPatterns.size(); ++patternIndex) {
        const auto& pattern = direction.reactantPatterns[patternIndex];
        bool patternHasMapped = false;
        bool patternHasUnmapped = false;
        for (std::size_t moleculeIndex = 0; moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
            const bng::compile::PatternMoleculeRef ref{
                BngPatternSide::Reactant, patternIndex, moleculeIndex};
            const auto node = nodeFor(ref, reactants);
            if (!node) continue;
            if (nodes.mappedReactants.count(*node) != 0) patternHasMapped = true;
            else patternHasUnmapped = true;
        }
        if (patternHasUnmapped && patternHasMapped) {
            hasOrphanRiskUnmappedReactant = true;
            break;
        }
    }
    if (!hasDeleteMoleculesModifier(rule) && hasOrphanRiskUnmappedReactant &&
        !nodes.createdProducts.empty()) {
        issue(result, BngLoweringSeverity::Error, entity,
              "simultaneous molecule replacement requires orphan-context semantics "
              "not yet representable in NFIR v5");
        return false;
    }

    // The compiler resolves default whole-pattern deletion once. Remove each
    // matched species as a unit so connected, unspecified context is included.
    // DeleteMolecules deliberately bypasses this path and stays molecule-scoped.
    if (!deleteMolecules) {
        for (const auto patternIndex : direction.wholeSpeciesDeletions) {
            if (!appendWholeSpeciesDeletion(patternIndex)) return false;
        }
    }

    // DeleteMolecules and partial rule rewrites remove only explicit unmatched
    // molecule occurrences, preserving any unmatched surrounding context.
    for (std::size_t patternIndex = 0; patternIndex < direction.reactantPatterns.size(); ++patternIndex) {
        if (!deleteMolecules && isWholeSpeciesDeletion(direction, patternIndex)) continue;
        const auto& pattern = direction.reactantPatterns[patternIndex];
        for (std::size_t moleculeIndex = 0; moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
            const bng::compile::PatternMoleculeRef ref{
                BngPatternSide::Reactant, patternIndex, moleculeIndex};
            const auto node = nodeFor(ref, reactants);
            if (!node || nodes.mappedReactants.count(*node) != 0) continue;
            const auto& molecule = pattern.molecules()[moleculeIndex];
            if (!molecule.moleculeTypeId) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "deleted reactant molecule is not typed");
                return false;
            }
            ActionIR destroy;
            destroy.kind = ActionKind::Destroy;
            destroy.target_node = *node;
            destroy.molecule_type = static_cast<TypeId>(molecule.moleculeTypeId->value());
            actions.push_back(std::move(destroy));
        }
    }
    return true;
}

bool addActions(const bng::compile::CompiledRule& rule,
                const bng::compile::CompiledRuleDirection& direction,
                const bng::compile::CompiledModel& source,
                const FlattenedPattern& pattern,
                bool reverseDirection,
                std::vector<ActionIR>& actions,
                std::vector<std::pair<PatternNodeId, PatternNodeId>>& createdCompartmentInherit,
                DirectionNodeMap& outNodes,
                BngLoweringResult& result, const std::string& entity) {
    if (!direction.transformationsComplete) {
        issue(result, BngLoweringSeverity::Error, entity,
              "compiled rule transformation program is incomplete");
        return false;
    }

    const auto nodes = buildDirectionNodeMap(
        rule, direction, pattern, reverseDirection, result, entity);
    if (!nodes) return false;
    outNodes = *nodes;
    if (!appendCreateActions(direction, source, pattern, *nodes, actions,
                             createdCompartmentInherit, result, entity)) return false;

    const bool deleteMolecules = hasDeleteMoleculesModifier(rule);
    // RULEHUB-05: Always emit DeleteBond (Unbind) operations BEFORE AddBond (Bind)
    // operations so simultaneous bond-break + bond-form rules (e.g. bond transfer)
    // free the site before binding its new partner.
    std::vector<ActionIR> deferredBinds;
    for (const auto& mutation : direction.mutations) {
        if (mutation.kind == BngMutationKind::DeleteBond && !deleteMolecules &&
            (isWholeSpeciesDeletion(direction, mutation.source.patternIndex) ||
             isWholeSpeciesDeletion(direction, mutation.partner.patternIndex))) {
            // Keep the matched graph connected until DestroyComplex traverses it.
            continue;
        }
        ActionIR action;
        switch (mutation.kind) {
        case BngMutationKind::ChangeState: {
            const auto node = nodeFor(mutation.source, pattern);
            if (!node || !mutation.newStateId) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "state change could not be mapped to a typed reactant endpoint");
                return false;
            }
            action.kind = ActionKind::SetSiteState;
            action.target_node = *node;
            action.molecule_type = static_cast<TypeId>(mutation.newStateId->component.moleculeType.value());
            action.site = static_cast<std::uint16_t>(mutation.newStateId->component.index);
            action.value = static_cast<std::int32_t>(mutation.newStateId->index);
            actions.push_back(std::move(action));
            break;
        }
        case BngMutationKind::AddBond:
        case BngMutationKind::DeleteBond: {
            const auto first = nodeFor(mutation.source, pattern);
            const auto second = nodeFor(mutation.partner, pattern);
            if (!first || !second) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "bond edit could not be mapped to reactant pattern nodes");
                return false;
            }
            if (mutation.source.patternIndex >= direction.reactantPatterns.size() ||
                mutation.source.moleculeIndex >= direction.reactantPatterns[mutation.source.patternIndex].molecules().size()) {
                issue(result, BngLoweringSeverity::Error, entity, "bond edit source is outside reactant pattern");
                return false;
            }
            const auto& molecule = direction.reactantPatterns[mutation.source.patternIndex].molecules()[mutation.source.moleculeIndex];
            if (mutation.source.siteIndex >= molecule.sites.size() || !molecule.moleculeTypeId || !molecule.sites[mutation.source.siteIndex].componentType) {
                issue(result, BngLoweringSeverity::Error, entity, "bond edit source site is unresolved");
                return false;
            }
            action.kind = mutation.kind == BngMutationKind::AddBond ? ActionKind::Bind : ActionKind::Unbind;
            action.target_node = *first;
            action.partner_node = *second;
            action.molecule_type = static_cast<TypeId>(molecule.moleculeTypeId->value());
            action.site = static_cast<std::uint16_t>(molecule.sites[mutation.source.siteIndex].componentType->index);
            const auto& partnerMolecule = direction.reactantPatterns[mutation.partner.patternIndex].molecules()[mutation.partner.moleculeIndex];
            if (mutation.partner.siteIndex >= partnerMolecule.sites.size() ||
                !partnerMolecule.sites[mutation.partner.siteIndex].componentType) {
                issue(result, BngLoweringSeverity::Error, entity, "bond edit partner site is unresolved");
                return false;
            }
            action.partner_site = static_cast<std::uint16_t>(partnerMolecule.sites[mutation.partner.siteIndex].componentType->index);
            if (mutation.kind == BngMutationKind::AddBond) {
                deferredBinds.push_back(std::move(action));
            } else {
                actions.push_back(std::move(action));
            }
            break;
        }
        case BngMutationKind::AddMolecule:
        case BngMutationKind::DeleteMolecule:
            // Creation/deletion is derived from the authoritative product-to-
            // reactant identity mapping below. This also covers zero-order
            // synthesis/degradation where the legacy operation list is empty.
            break;
        }
    }
    for (auto& bindAction : deferredBinds) {
        actions.push_back(std::move(bindAction));
    }

    const auto effectiveMolComp = [&](const BngPattern& pat,
                                      const bng::compile::PatternMoleculeDescriptor& mol)
        -> std::optional<bng::compile::CompartmentId> {
        if (!mol.compartment.empty() && mol.compartmentId) return mol.compartmentId;
        if (pat.compartmentId()) {
            const auto* c = source.compartment(*pat.compartmentId());
            if (c && c->dimension == 2 && pat.compartmentIsPrefix()) return std::nullopt;
            return pat.compartmentId();
        }
        return std::nullopt;
    };

    // Compartment transport actions for mapped reactant molecules
    for (const auto& [productRef, reactantRef] :
         directionMoleculeMappings(rule, reverseDirection)) {
        if (productRef.patternIndex >= direction.productPatterns.size() ||
            reactantRef.patternIndex >= direction.reactantPatterns.size()) continue;
        const auto& prodPattern = direction.productPatterns[productRef.patternIndex];
        const auto& reactPattern = direction.reactantPatterns[reactantRef.patternIndex];
        if (productRef.moleculeIndex >= prodPattern.molecules().size() ||
            reactantRef.moleculeIndex >= reactPattern.molecules().size()) continue;
        const auto& prodMol = prodPattern.molecules()[productRef.moleculeIndex];
        const auto& reactMol = reactPattern.molecules()[reactantRef.moleculeIndex];
        const auto prodComp = effectiveMolComp(prodPattern, prodMol);
        const auto reactComp = effectiveMolComp(reactPattern, reactMol);
        if (prodComp.has_value() && prodComp != reactComp) {
            const auto node = nodeFor(reactantRef, pattern);
            if (node) {
                ActionIR setComp;
                setComp.kind = ActionKind::SetCompartment;
                setComp.target_node = *node;
                setComp.molecule_type = static_cast<TypeId>(reactMol.moleculeTypeId->value());
                setComp.value = static_cast<std::int32_t>(prodComp->value());
                actions.push_back(std::move(setComp));
            }
        }
    }

    if (!appendCreatedProductBonds(direction, *nodes, actions, result, entity)) return false;
    return appendDeletionActions(rule, direction, pattern, *nodes, actions, result, entity);
}

bool filtersInvariantUnderReactantSwap(
    const std::vector<bng::compile::CompiledFilter>& filters,
    std::size_t firstPattern, std::size_t secondPattern) {
    if (filters.empty()) return true;
    for (const auto& f : filters) {
        if (f.products) return false;
    }
    std::vector<bool> matched(filters.size(), false);
    for (const auto& f : filters) {
        const std::size_t mapped =
            (f.patternIndex == firstPattern) ? secondPattern :
            (f.patternIndex == secondPattern) ? firstPattern : f.patternIndex;
        bool found = false;
        for (std::size_t j = 0; j < filters.size(); ++j) {
            if (matched[j]) continue;
            const auto& g = filters[j];
            if (g.include == f.include && g.products == f.products &&
                g.patternIndex == mapped && g.patterns == f.patterns) {
                matched[j] = true;
                found = true;
                break;
            }
        }
        if (!found) return false;
    }
    return true;
}

// Compute within-pattern (node, site) rule-action symmetry divisor for a lowered rule.
// Cross-pattern symmetries are handled by PatternIR::interchangeable; whole-species
// deletions are deduplicated per complex at runtime. This computes the exact product
// of within-pattern automorphism counts leaving the pattern and action multiset invariant.
double computeWithinPatternSymmetry(
    const PatternIR& pattern,
    const std::vector<ActionIR>& actions,
    const std::vector<std::size_t>& reactantPatternOffsets,
    const std::vector<std::size_t>& destroyComplexPatterns,
    const bng::compile::CompiledModel& source) {
    const std::size_t n = pattern.nodes.size();
    if (n == 0) return 1.0;

    std::vector<std::size_t> offsets = reactantPatternOffsets;
    if (offsets.empty()) offsets.push_back(0);
    std::unordered_set<std::size_t> destroySet(
        destroyComplexPatterns.begin(), destroyComplexPatterns.end());

    // Precompute mentioned sites & per-site constraint signatures per node.
    using ConstraintSig = std::vector<std::tuple<int, std::int32_t, std::vector<std::int32_t>>>;
    std::vector<std::vector<std::uint16_t>> mentioned(n);
    std::vector<std::map<std::uint16_t, ConstraintSig>> siteSigs(n);
    for (std::size_t u = 0; u < n; ++u) {
        for (const auto& c : pattern.nodes[u].constraints) {
            const auto s = static_cast<std::uint16_t>(c.site);
            mentioned[u].push_back(s);
            siteSigs[u][s].emplace_back(static_cast<int>(c.kind), c.state, c.states);
        }
        for (auto& [_, sig] : siteSigs[u]) std::sort(sig.begin(), sig.end());
    }
    for (const auto& b : pattern.bonds) {
        mentioned[b.first].push_back(static_cast<std::uint16_t>(b.first_site));
        mentioned[b.second].push_back(static_cast<std::uint16_t>(b.second_site));
    }
    for (auto& m : mentioned) {
        std::sort(m.begin(), m.end());
        m.erase(std::unique(m.begin(), m.end()), m.end());
    }

    auto actionKeysFor = [&](const std::vector<std::size_t>& perm,
                             const std::vector<std::vector<std::uint16_t>>& smaps) {
        auto mapNode = [&](std::uint32_t node) -> std::uint32_t {
            return node < perm.size() ? static_cast<std::uint32_t>(perm[node]) : node;
        };
        auto mapSite = [&](std::uint32_t node, std::uint16_t site) -> std::uint16_t {
            if (node < smaps.size() && site < smaps[node].size()) return smaps[node][site];
            return site;
        };
        std::vector<std::vector<int>> keys;
        keys.reserve(actions.size());
        for (const auto& a : actions) {
            std::vector<int> k{static_cast<int>(a.kind), static_cast<int>(a.molecule_type)};
            if (a.kind == ActionKind::Bind || a.kind == ActionKind::Unbind) {
                std::pair<std::uint32_t, std::uint16_t> e1{mapNode(a.target_node), mapSite(a.target_node, a.site)};
                std::pair<std::uint32_t, std::uint16_t> e2{mapNode(a.partner_node), mapSite(a.partner_node, a.partner_site)};
                if (e2 < e1) std::swap(e1, e2);
                k.push_back(static_cast<int>(e1.first));
                k.push_back(static_cast<int>(e1.second));
                k.push_back(static_cast<int>(e2.first));
                k.push_back(static_cast<int>(e2.second));
            } else {
                k.push_back(static_cast<int>(mapNode(a.target_node)));
                k.push_back(static_cast<int>(mapSite(a.target_node, a.site)));
                k.push_back(static_cast<int>(a.value));
                k.push_back(static_cast<int>(a.aux));
            }
            keys.push_back(std::move(k));
        }
        std::sort(keys.begin(), keys.end());
        return keys;
    };

    std::vector<std::size_t> idPerm(n);
    std::iota(idPerm.begin(), idPerm.end(), 0);
    std::vector<std::vector<std::uint16_t>> idSiteMaps(n);
    for (std::size_t u = 0; u < n; ++u) {
        const auto* mt = source.moleculeType(
            bng::compile::MoleculeTypeId::fromDenseIndex(pattern.nodes[u].molecule_type));
        if (mt) {
            idSiteMaps[u].resize(mt->components.size());
            std::iota(idSiteMaps[u].begin(), idSiteMaps[u].end(), static_cast<std::uint16_t>(0));
        }
    }
    const auto baseActionKeys = actionKeysFor(idPerm, idSiteMaps);

    double divisor = 1.0;
    for (std::size_t pi = 0; pi < offsets.size(); ++pi) {
        if (destroySet.count(pi)) continue; // whole-species deletion deduplicated per complex
        const std::size_t start = offsets[pi];
        const std::size_t end = (pi + 1 < offsets.size()) ? offsets[pi + 1] : n;
        const std::size_t len = end - start;
        if (len == 0) continue;

        // Fast skip: single node with no duplicate mentioned site names.
        if (len == 1) {
            const auto* mt = source.moleculeType(
                bng::compile::MoleculeTypeId::fromDenseIndex(pattern.nodes[start].molecule_type));
            bool hasDupMentioned = false;
            if (mt && mentioned[start].size() >= 2) {
                for (std::size_t i = 0; i < mentioned[start].size() && !hasDupMentioned; ++i) {
                    for (std::size_t j = i + 1; j < mentioned[start].size(); ++j) {
                        if (mt->components[mentioned[start][i]].name ==
                            mt->components[mentioned[start][j]].name) {
                            hasDupMentioned = true;
                            break;
                        }
                    }
                }
            }
            if (!hasDupMentioned) continue;
        }

        // Collect undirected bonds inside [start, end).
        using UBond = std::tuple<std::size_t, std::uint16_t, std::size_t, std::uint16_t>;
        auto makeUBond = [](std::size_t a, std::uint16_t sa, std::size_t b, std::uint16_t sb) -> UBond {
            if (std::tie(b, sb) < std::tie(a, sa)) return {b, sb, a, sa};
            return {a, sa, b, sb};
        };
        std::vector<UBond> subBonds;
        std::vector<std::vector<std::size_t>> localAdj(len);
        for (const auto& b : pattern.bonds) {
            if (b.first >= start && b.first < end && b.second >= start && b.second < end) {
                subBonds.push_back(makeUBond(b.first, static_cast<std::uint16_t>(b.first_site),
                                             b.second, static_cast<std::uint16_t>(b.second_site)));
                if (b.first != b.second) {
                    localAdj[b.first - start].push_back(b.second - start);
                    localAdj[b.second - start].push_back(b.first - start);
                }
            }
        }
        std::sort(subBonds.begin(), subBonds.end());
        std::set<UBond> subBondSet(subBonds.begin(), subBonds.end());

        // Order local nodes by BFS along bonds.
        std::vector<std::size_t> order;
        std::vector<std::optional<std::size_t>> parentLocal(len);
        std::vector<bool> inOrder(len, false);
        while (order.size() < len) {
            std::size_t s0 = 0;
            while (inOrder[s0]) ++s0;
            std::vector<std::size_t> q{s0};
            inOrder[s0] = true;
            for (std::size_t h = 0; h < q.size(); ++h) {
                const std::size_t c = q[h];
                order.push_back(c);
                for (const std::size_t nb : localAdj[c]) {
                    if (!inOrder[nb]) {
                        inOrder[nb] = true;
                        parentLocal[nb] = c;
                        q.push_back(nb);
                    }
                }
            }
        }

        auto perm = idPerm;
        auto smaps = idSiteMaps;
        std::vector<bool> assigned(len, false);
        std::vector<bool> used(len, false);
        std::size_t autCount = 0;

        auto enumSiteMaps = [&](std::size_t u, std::size_t pu, auto&& cb) {
            const auto* mt = source.moleculeType(
                bng::compile::MoleculeTypeId::fromDenseIndex(pattern.nodes[u].molecule_type));
            if (!mt) return;
            const auto& uSites = mentioned[u];
            const auto& puSites = mentioned[pu];
            if (uSites.size() != puSites.size()) return;
            auto smap = idSiteMaps[u];
            if (uSites.empty()) { cb(smap); return; }
            std::vector<std::uint8_t> usedT(puSites.size(), 0);
            std::function<void(std::size_t)> assignS = [&](std::size_t idx) {
                if (idx == uSites.size()) { cb(smap); return; }
                const auto us = uSites[idx];
                const auto& uSig = siteSigs[u][us];
                for (std::size_t j = 0; j < puSites.size(); ++j) {
                    if (usedT[j]) continue;
                    const auto ps = puSites[j];
                    if (mt->components[us].name != mt->components[ps].name) continue;
                    if (uSig != siteSigs[pu][ps]) continue;
                    smap[us] = ps;
                    usedT[j] = 1;
                    assignS(idx + 1);
                    usedT[j] = 0;
                }
            };
            assignS(0);
        };

        auto checkSubBonds = [&](std::size_t lu) -> bool {
            const std::size_t u = start + lu;
            for (const auto& b : pattern.bonds) {
                if (b.first != u && b.second != u) continue;
                if (b.first < start || b.first >= end || b.second < start || b.second >= end) continue;
                if (!assigned[b.first - start] || !assigned[b.second - start]) continue;
                if (!subBondSet.count(makeUBond(
                        perm[b.first], smaps[b.first][b.first_site],
                        perm[b.second], smaps[b.second][b.second_site]))) {
                    return false;
                }
            }
            return true;
        };

        std::function<void(std::size_t)> dfs = [&](std::size_t depth) {
            if (depth == len) {
                if (actionKeysFor(perm, smaps) == baseActionKeys) ++autCount;
                return;
            }
            const std::size_t lu = order[depth];
            const std::size_t u = start + lu;
            auto tryLocal = [&](std::size_t lpu) {
                if (used[lpu]) return;
                const std::size_t pu = start + lpu;
                if (pattern.nodes[u].molecule_type != pattern.nodes[pu].molecule_type) return;
                if (pattern.nodes[u].compartment != pattern.nodes[pu].compartment) return;
                if (localAdj[lu].size() != localAdj[lpu].size()) return;
                if (mentioned[u].size() != mentioned[pu].size()) return;
                perm[u] = pu;
                assigned[lu] = true;
                used[lpu] = true;
                enumSiteMaps(u, pu, [&](const std::vector<std::uint16_t>& sm) {
                    smaps[u] = sm;
                    if (checkSubBonds(lu)) dfs(depth + 1);
                });
                assigned[lu] = false;
                used[lpu] = false;
            };
            if (parentLocal[lu].has_value()) {
                const std::size_t pParent = perm[start + *parentLocal[lu]] - start;
                std::unordered_set<std::size_t> tried;
                for (const std::size_t nb : localAdj[pParent]) {
                    if (tried.insert(nb).second) tryLocal(nb);
                }
            } else {
                for (std::size_t lpu = 0; lpu < len; ++lpu) tryLocal(lpu);
            }
        };
        dfs(0);
        if (autCount > 1) divisor *= static_cast<double>(autCount);
    }
    return divisor;
}

std::vector<MolecularityConstraint> computeProductMolecularity(
    const bng::compile::CompiledRuleDirection& direction,
    const FlattenedPattern& reactants,
    const DirectionNodeMap& nodes,
    const std::vector<ActionIR>& actions) {
    std::vector<MolecularityConstraint> result;
    const std::size_t reactantCount = reactants.pattern.nodes.size();
    if (reactantCount == 0 || direction.productPatterns.empty()) return result;

    // Identify destroyed reactant nodes and deleted bonds.
    std::unordered_set<PatternNodeId> destroyedNodes;
    using BondPair = std::tuple<PatternNodeId, std::uint16_t, PatternNodeId, std::uint16_t>;
    auto normBond = [](PatternNodeId a, std::uint16_t sa, PatternNodeId b, std::uint16_t sb) -> BondPair {
        if (std::tie(b, sb) < std::tie(a, sa)) return {b, sb, a, sa};
        return {a, sa, b, sb};
    };
    std::set<BondPair> deletedBonds;
    PatternNodeId maxNode = static_cast<PatternNodeId>(reactantCount);
    for (const auto& a : actions) {
        if (a.kind == ActionKind::Destroy || a.kind == ActionKind::DestroyComplex) {
            destroyedNodes.insert(a.target_node);
        } else if (a.kind == ActionKind::Unbind) {
            deletedBonds.insert(normBond(a.target_node, a.site, a.partner_node, a.partner_site));
        } else if (a.kind == ActionKind::Create) {
            maxNode = std::max(maxNode, a.target_node + 1);
        }
    }

    // Union-Find for static product connectivity (bonds surviving or added).
    std::vector<std::size_t> prodUf(maxNode);
    std::iota(prodUf.begin(), prodUf.end(), 0);
    auto findRoot = [](std::vector<std::size_t>& uf, std::size_t x) {
        while (uf[x] != x) { uf[x] = uf[uf[x]]; x = uf[x]; }
        return x;
    };
    auto unite = [&](std::vector<std::size_t>& uf, std::size_t a, std::size_t b) {
        a = findRoot(uf, a); b = findRoot(uf, b);
        if (a != b) uf[b] = a;
    };
    for (const auto& b : reactants.pattern.bonds) {
        const auto u = static_cast<PatternNodeId>(b.first);
        const auto v = static_cast<PatternNodeId>(b.second);
        if (destroyedNodes.count(u) || destroyedNodes.count(v)) continue;
        if (deletedBonds.count(normBond(u, static_cast<std::uint16_t>(b.first_site),
                                        v, static_cast<std::uint16_t>(b.second_site)))) continue;
        unite(prodUf, u, v);
    }
    for (const auto& a : actions) {
        if (a.kind == ActionKind::Bind && a.target_node < maxNode && a.partner_node < maxNode) {
            unite(prodUf, a.target_node, a.partner_node);
        }
    }

    // Union-Find for reactant pattern connectivity (including any cross-reactant Bind).
    std::vector<std::size_t> reactUf(maxNode);
    std::iota(reactUf.begin(), reactUf.end(), 0);
    for (std::size_t pi = 0; pi < reactants.patternOffsets.size(); ++pi) {
        const std::size_t start = reactants.patternOffsets[pi];
        const std::size_t end = (pi + 1 < reactants.patternOffsets.size())
                                    ? reactants.patternOffsets[pi + 1]
                                    : reactantCount;
        for (std::size_t u = start + 1; u < end; ++u) unite(reactUf, start, u);
    }
    for (const auto& a : actions) {
        if (a.kind == ActionKind::Bind && a.target_node < maxNode && a.partner_node < maxNode) {
            unite(reactUf, a.target_node, a.partner_node);
        }
    }

    // Collect surviving reactant nodes per product pattern.
    std::vector<std::vector<PatternNodeId>> prodSurviving(direction.productPatterns.size());
    for (std::size_t pi = 0; pi < direction.productPatterns.size(); ++pi) {
        const auto& pat = direction.productPatterns[pi];
        for (std::size_t mi = 0; mi < pat.molecules().size(); ++mi) {
            const auto it = nodes.productNodes.find({pi, mi});
            if (it == nodes.productNodes.end()) continue;
            if (it->second < reactantCount && !destroyedNodes.count(it->second)) {
                prodSurviving[pi].push_back(it->second);
            }
        }
        // Within each product pattern, surviving reactants must end up in the same complex.
        if (prodSurviving[pi].size() >= 2) {
            const auto rep = prodSurviving[pi].front();
            for (std::size_t k = 1; k < prodSurviving[pi].size(); ++k) {
                const auto other = prodSurviving[pi][k];
                if (findRoot(prodUf, rep) != findRoot(prodUf, other)) {
                    result.push_back(MolecularityConstraint::sameComplex(
                        static_cast<std::uint16_t>(rep), static_cast<std::uint16_t>(other)));
                }
            }
        }
    }

    // Across distinct '+'-separated product patterns, surviving reactants must end up
    // in different complexes whenever they could possibly be connected after transformation.
    for (std::size_t pi = 0; pi < prodSurviving.size(); ++pi) {
        if (prodSurviving[pi].empty()) continue;
        for (std::size_t pj = pi + 1; pj < prodSurviving.size(); ++pj) {
            if (prodSurviving[pj].empty()) continue;
            const auto a = prodSurviving[pi].front();
            const auto b = prodSurviving[pj].front();
            if (findRoot(reactUf, a) == findRoot(reactUf, b)) {
                result.push_back(MolecularityConstraint::differentComplex(
                    static_cast<std::uint16_t>(a), static_cast<std::uint16_t>(b)));
            }
        }
    }
    return result;
}

// Helper for ETH-13: add a state or state-set branch constraint to a PatternIR::Node
// while checking compatibility with any existing constraints from the rule pattern.
bool tryAddBranchStateConstraint(PatternIR::Node& node, std::uint32_t site,
                                 const std::vector<std::int32_t>& allowedStates) {
    if (allowedStates.empty()) return false;
    std::vector<std::int32_t> effective = allowedStates;
    for (auto it = node.constraints.begin(); it != node.constraints.end();) {
        if (it->site != site) { ++it; continue; }
        if (it->kind == PatternIR::SiteConstraintKind::State) {
            if (std::find(effective.begin(), effective.end(), it->state) == effective.end()) {
                return false; // Contradicts existing rule state constraint!
            }
            effective = {it->state};
            it = node.constraints.erase(it);
            continue;
        }
        if (it->kind == PatternIR::SiteConstraintKind::StateSet) {
            std::vector<std::int32_t> inter;
            for (const auto s : effective) {
                if (std::find(it->states.begin(), it->states.end(), s) != it->states.end()) {
                    inter.push_back(s);
                }
            }
            if (inter.empty()) return false;
            effective = std::move(inter);
            it = node.constraints.erase(it);
            continue;
        }
        ++it;
    }
    if (effective.size() == 1) node.siteState(site, effective.front());
    else node.siteStateSet(site, std::move(effective));
    return true;
}

bool tryAddBranchBondConstraint(PatternIR& pattern, std::size_t nodeIdx,
                                std::uint32_t site, bool requireBound) {
    for (const auto& b : pattern.bonds) {
        if ((b.first == nodeIdx && b.first_site == site) ||
            (b.second == nodeIdx && b.second_site == site)) {
            return requireBound; // Bond already implies bound; Free contradicts bond!
        }
    }
    auto& node = pattern.nodes[nodeIdx];
    for (const auto& c : node.constraints) {
        if (c.site != site) continue;
        if (c.kind == PatternIR::SiteConstraintKind::Free) return !requireBound;
        if (c.kind == PatternIR::SiteConstraintKind::Bound) return requireBound;
    }
    if (requireBound) node.siteBound(site);
    else node.siteFree(site);
    return true;
}

// Swap-insensitive key for one action. Bind/Unbind are undirected, so their
// endpoints are ordered by (node, site); that lets a bond action remain
// identical when interchangeable reactant nodes are exchanged. `swaps` holds
// the node pairs exchanged when two duplicate reactant patterns are swapped.
std::vector<int> actionSymmetryKey(
    const ActionIR& action,
    const std::vector<std::pair<std::size_t, std::size_t>>& swaps) {
    const auto node = [&](std::uint32_t n) -> std::uint32_t {
        for (const auto& [a, b] : swaps) {
            if (n == a) return static_cast<std::uint32_t>(b);
            if (n == b) return static_cast<std::uint32_t>(a);
        }
        return n;
    };
    std::vector<int> key{static_cast<int>(action.kind),
                         static_cast<int>(action.molecule_type)};
    if (action.kind == ActionKind::Bind || action.kind == ActionKind::Unbind) {
        std::array<std::pair<std::uint32_t, std::uint16_t>, 2> endpoints{{
            {node(action.target_node), action.site},
            {node(action.partner_node), action.partner_site},
        }};
        if (endpoints[1] < endpoints[0]) std::swap(endpoints[0], endpoints[1]);
        for (const auto& endpoint : endpoints) {
            key.push_back(static_cast<int>(endpoint.first));
            key.push_back(static_cast<int>(endpoint.second));
        }
    } else {
        key.push_back(static_cast<int>(node(action.target_node)));
        key.push_back(static_cast<int>(action.site));
        key.push_back(static_cast<int>(action.value));
        key.push_back(static_cast<int>(action.aux));
    }
    return key;
}

// True when exchanging whole duplicate reactant patterns leaves the
// transformation program unchanged (as a multiset of actions). Only then may
// the matcher collapse ordered embeddings into unordered combinations.
bool actionsInvariantUnderSwaps(
    const std::vector<ActionIR>& actions,
    const std::vector<std::pair<std::size_t, std::size_t>>& swaps) {
    if (swaps.empty()) return true;
    std::vector<std::vector<int>> before;
    std::vector<std::vector<int>> after;
    before.reserve(actions.size());
    after.reserve(actions.size());
    for (const auto& action : actions) {
        before.push_back(actionSymmetryKey(action, {}));
        after.push_back(actionSymmetryKey(action, swaps));
    }
    std::sort(before.begin(), before.end());
    std::sort(after.begin(), after.end());
    return before == after;
}

void addDirection(const bng::compile::CompiledRule& rule,
                  const bng::compile::CompiledRuleDirection& direction,
                  RuleId id, const std::string& suffix, bool reverseDirection,
                  const bng::compile::CompiledModel& source,
                  BngLoweringResult& result) {
    const std::string entity = rule.name() + suffix;
    const auto flattened = flattenReactants(
        direction.reactantPatterns, result, entity, false, &source);
    if (!flattened) return;

    // Lower filters into NFIR FilterIR. Filters constrain rule applicability
    // by requiring or excluding species matching specific patterns in the
    // reactant or product set. The filter patterns are lowered to PatternIR
    // with unspecifiedBondIsUnbound = true (NFN-07).
    std::vector<FilterIR> loweredFilters;
    bool hasProductFilter = false;
    if (!direction.filters.empty()) {
        loweredFilters.reserve(direction.filters.size());
        for (const auto& filter : direction.filters) {
            FilterIR irFilter;
            irFilter.include = filter.include;
            irFilter.products = filter.products;
            if (filter.products) hasProductFilter = true;
            irFilter.pattern_index = filter.patternIndex;
            irFilter.reactant_node_offset = (!filter.products && filter.patternIndex < flattened->patternOffsets.size())
                ? flattened->patternOffsets[filter.patternIndex]
                : 0;
            irFilter.patterns.reserve(filter.patterns.size());
            for (const auto& pattern : filter.patterns) {
                BngLoweringResult filterValidation;
                const auto loweredPattern = flattenReactants(
                    {pattern}, filterValidation, entity, true, &source);
                if (loweredPattern && filterValidation.ok()) {
                    irFilter.patterns.push_back(loweredPattern->pattern);
                } else {
                    issue(result, BngLoweringSeverity::Error, entity,
                          "include/exclude filter pattern could not be lowered to NFIR");
                    return;
                }
            }
            loweredFilters.push_back(std::move(irFilter));
        }
    }
    // Lower modifiers into NFIR rule annotations. Each modifier is carried
    // through as a boolean or structural annotation on the ExpandedRuleIR.
    // DeleteMolecules is already handled via the action lowering path.
    bool matchOnce = false;
    bool totalRate = false;
    bool moveConnected = false;
    for (const auto& modifier : rule.modifiers()) {
        switch (modifier.kind) {
        case bng::compile::ModifierKind::DeleteMolecules:
            // Already handled by deletion action lowering
            break;
        case bng::compile::ModifierKind::MatchOnce:
            matchOnce = true;
            break;
        case bng::compile::ModifierKind::TotalRate:
            totalRate = true;
            break;
        case bng::compile::ModifierKind::MoveConnected:
            moveConnected = true;
            break;
        case bng::compile::ModifierKind::IncludeReactants:
        case bng::compile::ModifierKind::ExcludeReactants:
        case bng::compile::ModifierKind::IncludeProducts:
        case bng::compile::ModifierKind::ExcludeProducts:
            // These are already represented by CompiledFilter entries
            break;
        case bng::compile::ModifierKind::Unknown:
            issue(result, BngLoweringSeverity::Error, entity,
                  "rule modifier '" + modifier.source +
                  "' is not recognized by NFIR lowering");
            return;
        }
    }
    if (!direction.rateLaw) {
        issue(result, BngLoweringSeverity::Error, entity, "rule direction has no rate law");
        return;
    }

    auto loweredPattern = flattened->pattern;
    // Actions must be lowered before deciding reactant interchangeability:
    // a symmetric transformation leaves the action program invariant under
    // the exchange, and only then may ordered embeddings be collapsed.
    std::vector<ActionIR> loweredActions;
    std::vector<std::pair<PatternNodeId, PatternNodeId>> createdCompartmentInherit;
    DirectionNodeMap directionNodes;
    if (!addActions(rule, direction, source, *flattened, reverseDirection,
                    loweredActions, createdCompartmentInherit, directionNodes,
                    result, entity)) return;

    // Resolve product filter target logical node offsets (NFN-06).
    for (auto& irFilter : loweredFilters) {
        if (!irFilter.products) continue;
        if (irFilter.pattern_index < direction.productPatterns.size() &&
            !direction.productPatterns[irFilter.pattern_index].molecules().empty()) {
            const auto it = directionNodes.productNodes.find({irFilter.pattern_index, 0});
            if (it != directionNodes.productNodes.end()) {
                irFilter.reactant_node_offset = it->second;
            }
        }
    }

    // Track which reactant patterns perform whole-species deletion (DestroyComplex).
    std::vector<std::size_t> destroyComplexPatterns;
    if (!hasDeleteMoleculesModifier(rule)) {
        if (direction.productPatterns.empty()) {
            for (std::size_t pi = 0; pi < direction.reactantPatterns.size(); ++pi) {
                if (!direction.reactantPatterns[pi].molecules().empty())
                    destroyComplexPatterns.push_back(pi);
            }
        } else {
            destroyComplexPatterns = direction.wholeSpeciesDeletions;
        }
    }

    // Cross-pattern reactant interchangeability (including DeleteMolecules and
    // symmetric reactant filters — NFN-11).
    const bool wholeDeletionSymmetry =
        !hasDeleteMoleculesModifier(rule) &&
        direction.wholeSpeciesDeletions.size() == direction.reactantPatterns.size();
    if (direction.localScopes.empty() && !hasProductFilter) {
        std::vector<bool> grouped(direction.reactantPatterns.size(), false);
        for (std::size_t first = 0; first < direction.reactantPatterns.size(); ++first) {
            if (grouped[first]) continue;
            const auto moleculeCount =
                direction.reactantPatterns[first].molecules().size();
            if (moleculeCount == 0) continue;
            std::vector<std::size_t> duplicates{first};
            std::vector<std::vector<std::size_t>> duplicateMappings;
            std::vector<std::size_t> selfMapping(moleculeCount);
            for (std::size_t m = 0; m < moleculeCount; ++m) selfMapping[m] = m;
            duplicateMappings.push_back(std::move(selfMapping));
            grouped[first] = true;
            for (std::size_t other = first + 1;
                 other < direction.reactantPatterns.size(); ++other) {
                if (grouped[other] ||
                    direction.reactantPatterns[other].molecules().size() != moleculeCount)
                    continue;
                const auto mapping = patternMoleculeMapping(
                    direction.reactantPatterns[first], direction.reactantPatterns[other]);
                if (!mapping) continue;
                duplicates.push_back(other);
                duplicateMappings.push_back(*mapping);
                grouped[other] = true;
            }
            if (duplicates.size() < 2) continue;
            bool allExchangesSymmetric = true;
            for (std::size_t dupIdx = 1; dupIdx < duplicates.size(); ++dupIdx) {
                if (!filtersInvariantUnderReactantSwap(
                        direction.filters, duplicates[0], duplicates[dupIdx])) {
                    allExchangesSymmetric = false;
                    break;
                }
                if (!wholeDeletionSymmetry) {
                    std::vector<std::pair<std::size_t, std::size_t>> swaps;
                    swaps.reserve(moleculeCount);
                    for (std::size_t m = 0; m < moleculeCount; ++m) {
                        swaps.emplace_back(
                            flattened->patternOffsets[duplicates[0]] + duplicateMappings[0][m],
                            flattened->patternOffsets[duplicates[dupIdx]] + duplicateMappings[dupIdx][m]);
                    }
                    if (!actionsInvariantUnderSwaps(loweredActions, swaps)) {
                        allExchangesSymmetric = false;
                        break;
                    }
                }
            }
            if (!allExchangesSymmetric) continue;
            for (std::size_t molecule = 0; molecule < moleculeCount; ++molecule) {
                std::vector<std::size_t> interchangeable;
                interchangeable.reserve(duplicates.size());
                for (std::size_t dupIdx = 0; dupIdx < duplicates.size(); ++dupIdx) {
                    const auto reactant = duplicates[dupIdx];
                    const auto targetMolecule = duplicateMappings[dupIdx][molecule];
                    interchangeable.push_back(
                        flattened->patternOffsets[reactant] + targetMolecule);
                }
                loweredPattern.interchangeable.push_back(std::move(interchangeable));
            }
        }
    }

    ExpandedRuleIR lowered;
    lowered.id = id;
    lowered.name = entity;
    lowered.pattern = std::move(loweredPattern);
    lowered.actions = std::move(loweredActions);
    lowered.reactant_pattern_offsets = flattened->patternOffsets;
    lowered.destroy_complex_patterns = std::move(destroyComplexPatterns);
    lowered.created_compartment_inherit = std::move(createdCompartmentInherit);
    lowered.product_molecularity = computeProductMolecularity(
        direction, *flattened, directionNodes, lowered.actions);
    if (direction.localScopes.empty()) {
        lowered.symmetry_divisor = computeWithinPatternSymmetry(
            lowered.pattern, lowered.actions, lowered.reactant_pattern_offsets,
            lowered.destroy_complex_patterns, source);
    }
    addPredicates(lowered.pattern, lowered.predicates);

    const auto partiallyExpandedRate = source.expandFunctions(
        direction.rateLaw->resolvedExpression());
    std::set<std::size_t> activeRateFunctions;
    const auto expandedRate = expandZeroArgumentRateFunctions(
        partiallyExpandedRate, source, activeRateFunctions);
    if (!expandedRate) {
        issue(result, BngLoweringSeverity::Error, entity,
              "rate references an invalid or recursive global function");
        return;
    }
    const bool energyModulatedArrhenius =
        direction.rateLaw->kind == bng::compile::RateLawKind::ArrheniusEnergy &&
        (!source.energyFactors().empty() || !source.barrierFactors().empty());
    const auto drivingWorkValue = rule.drivingWorkValue();
    const bool hasStaticDrivingWork =
        drivingWorkValue && std::isfinite(*drivingWorkValue);
    const bool expandableEnergyStateChange =
        energyModulatedArrhenius &&
        direction.mutations.size() == 1 &&
        direction.reactantPatterns.size() == 1 &&
        direction.mutations.front().kind == BngMutationKind::ChangeState &&
        direction.mutations.front().newStateId.has_value() &&
        direction.mutations.front().source.side == BngPatternSide::Reactant &&
        (!drivingWorkValue || hasStaticDrivingWork);
    const bool expandableEnergyBinding =
        energyModulatedArrhenius &&
        direction.mutations.size() == 1 &&
        direction.reactantPatterns.size() == 2 &&
        direction.reactantPatterns[0].molecules().size() == 1 &&
        direction.reactantPatterns[1].molecules().size() == 1 &&
        direction.mutations.front().kind == BngMutationKind::AddBond &&
        direction.mutations.front().source.side == BngPatternSide::Reactant &&
        direction.mutations.front().partner.side == BngPatternSide::Reactant &&
        (!drivingWorkValue || hasStaticDrivingWork);
    const bool expandableEnergyUnbinding =
        energyModulatedArrhenius &&
        direction.mutations.size() == 1 &&
        direction.reactantPatterns.size() == 1 &&
        direction.reactantPatterns[0].molecules().size() == 2 &&
        direction.mutations.front().kind == BngMutationKind::DeleteBond &&
        direction.mutations.front().source.side == BngPatternSide::Reactant &&
        direction.mutations.front().partner.side == BngPatternSide::Reactant &&
        (!drivingWorkValue || hasStaticDrivingWork);
    if (energyModulatedArrhenius && !expandableEnergyStateChange &&
        !expandableEnergyBinding && !expandableEnergyUnbinding) {
        issue(result, BngLoweringSeverity::Error, entity,
              "energy-modulated Arrhenius rule form is not yet supported in NFnext lowering");
        return;
    }
    const auto constant = (!energyModulatedArrhenius)
        ? constantExpression(*expandedRate, source)
        : std::optional<double>{};
    if (constant) {
        if (!std::isfinite(*constant) || *constant < 0.0) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "elementary BioNetGen rate must be finite and non-negative");
            return;
        }
        lowered.rate = *constant;
        lowered.rate_law.kind = RateLawKind::Elementary;
        std::ostringstream rateText;
        rateText.precision(17);
        rateText << *constant;
        lowered.rate_law.expression = rateText.str();
    } else if (!energyModulatedArrhenius) {
        if (!direction.rateLaw->dependencies().function &&
            !direction.rateLaw->dependencies().observable &&
            !direction.rateLaw->dependencies().parameter) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "dynamic NFIR rates require a resolved dependency on an observable, function or parameter");
            return;
        }
        std::set<std::size_t> observableIds;
        const auto expression = observableRateExpression(
            *expandedRate, source, observableIds,
            direction.localScopes.empty() ? nullptr : &direction.localScopes,
            &*flattened, &lowered.local_observable_bindings);
        if (!expression) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "dynamic rate expression could not be resolved to an NFIR arithmetic expression");
            return;
        }
        lowered.rate = 0.0;
        lowered.rate_law.kind = RateLawKind::Function;
        lowered.rate_law.expression = *expression;
    }
    lowered.annotations.emplace("bng.rule_label", rule.label());
    lowered.match_once = matchOnce;
    lowered.total_rate = totalRate;
    lowered.move_connected = moveConnected;
    lowered.filters = std::move(loweredFilters);

    // Honor NumberPerQuantityUnit even without typed physical units (NFN-09e).
    double numberPerQuantityUnit = 1.0;
    if (const auto option = source.metadata().options.find("NumberPerQuantityUnit");
        option != source.metadata().options.end()) {
        try {
            std::size_t consumed = 0;
            const double val = std::stod(option->second, &consumed);
            if (consumed == option->second.size() && std::isfinite(val) && val > 0.0) {
                numberPerQuantityUnit = val;
            }
        } catch (...) {
        }
    }

    double volumeFactor = 1.0;
    if (!source.compartments().empty()) {
        if (direction.reactantPatterns.empty()) {
            if (!direction.productPatterns.empty()) {
                const auto& prod = direction.productPatterns.front();
                auto pCompId = prod.compartmentId();
                if (!pCompId && !prod.molecules().empty()) pCompId = prod.molecules().front().compartmentId;
                if (pCompId) {
                    const auto* comp = source.compartment(*pCompId);
                    if (comp && std::isfinite(comp->volume) && comp->volume > 0.0) {
                        volumeFactor = comp->volume * numberPerQuantityUnit;
                    }
                }
            }
        } else if (direction.reactantPatterns.size() >= 2) {
            std::vector<bng::compile::ReactantCompartment> rcList;
            bool anyUnqualified = false;
            for (const auto& rPat : direction.reactantPatterns) {
                auto rCompId = rPat.compartmentId();
                if (!rCompId && !rPat.molecules().empty()) rCompId = rPat.molecules().front().compartmentId;
                if (rCompId) {
                    const auto* comp = source.compartment(*rCompId);
                    if (comp && std::isfinite(comp->volume) && comp->volume > 0.0) {
                        rcList.push_back({comp->dimension, comp->volume * numberPerQuantityUnit});
                    }
                } else {
                    anyUnqualified = true;
                }
            }
            if (anyUnqualified) {
                // Scale dynamically per candidate match from runtime complex compartments (NFN-09d).
                lowered.has_unqualified_compartments = true;
                volumeFactor = 1.0;
            } else {
                const auto factor = bng::compile::reactantUnitConversionFactor(rcList);
                if (factor) {
                    volumeFactor = *factor;
                }
            }
        }
    }
    lowered.volume_factor = volumeFactor;

    if (source.features().contains(bng::compile::Feature::Units) &&
        (!direction.rateLaw || !direction.rateLaw->unit.has_value())) {
        issue(result, BngLoweringSeverity::Error, entity,
              "every rate in a unit-bearing NFnext model must have a typed physical unit");
        return;
    }

    if (direction.rateLaw && direction.rateLaw->unit.has_value()) {
        if (!constant || lowered.rate_law.kind != RateLawKind::Elementary) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "physical unit rate conversion requires a constant elementary rate in NFnext");
            return;
        }
        const auto validStaticVolume = [&](bng::compile::CompartmentId cid) {
            const auto* comp = source.compartment(cid);
            return comp != nullptr && comp->dimension == 3 &&
                   !comp->volumeTimeDependent &&
                   std::isfinite(comp->volume) && comp->volume > 0.0 &&
                   comp->declaredUnit.has_value() &&
                   comp->declaredUnit->dimension.length == 3 &&
                   comp->declaredUnit->dimension.substance == 0 &&
                   comp->declaredUnit->dimension.time == 0;
        };
        const auto patternMolComp = [](const BngPattern& pat,
                                       const bng::compile::PatternMoleculeDescriptor& mol) {
            return mol.compartmentId.has_value() ? mol.compartmentId : pat.compartmentId();
        };
        bng::units::ConversionContext baseContext;
        if (const auto option = source.metadata().options.find("NumberPerQuantityUnit");
            option != source.metadata().options.end()) {
            try {
                std::size_t consumed = 0;
                const double value = std::stod(option->second, &consumed);
                if (consumed == option->second.size() && std::isfinite(value) && value > 0.0)
                    baseContext.numberPerQuantityUnit = value;
            } catch (...) {
            }
        }
        const auto molecularity = direction.reactantPatterns.size();
        bng::units::ConversionContext context = baseContext;
        if (molecularity == 0) {
            std::optional<bng::compile::CompartmentId> pCompId;
            std::size_t productMols = 0;
            for (const auto& prod : direction.productPatterns) {
                for (const auto& mol : prod.molecules()) {
                    ++productMols;
                    const auto cid = patternMolComp(prod, mol);
                    if (!cid) {
                        issue(result, BngLoweringSeverity::Error, entity,
                              "physical zero-order rate requires one declared product compartment");
                        return;
                    }
                    if (pCompId && *pCompId != *cid) {
                        issue(result, BngLoweringSeverity::Error, entity,
                              "physical zero-order products in multiple compartments are ambiguous");
                        return;
                    }
                    pCompId = cid;
                }
            }
            if (productMols == 0 || !pCompId) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "physical zero-order rate requires one declared product compartment");
                return;
            }
            if (!validStaticVolume(*pCompId)) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "physical zero-order rate requires a static declared product volume unit");
                return;
            }
            const auto* decl = source.compartment(*pCompId);
            context.compartmentVolume = decl->volume;
            context.volumeUnit = decl->declaredUnit;
            const auto conversion = bng::units::stochasticRateFactor(*direction.rateLaw->unit, 0, context);
            if (!conversion || !conversion.factor.has_value() || !std::isfinite(*conversion.factor) ||
                *conversion.factor < 0.0) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "physical zero-order rate unit cannot be converted to a count rate");
                return;
            }
            lowered.rate = *constant * *conversion.factor;
            // Typed conversion includes volume and any required mole/item bridge.
            lowered.volume_factor = 1.0;
        } else if (molecularity == 1) {
            for (const auto& pat : direction.reactantPatterns) {
                for (const auto& mol : pat.molecules()) {
                    const auto cid = patternMolComp(pat, mol);
                    if (cid && !validStaticVolume(*cid)) {
                        issue(result, BngLoweringSeverity::Error, entity,
                              "physical unimolecular rate requires a positive static declared 3D compartment");
                        return;
                    }
                }
            }
            for (const auto& pat : direction.productPatterns) {
                for (const auto& mol : pat.molecules()) {
                    const auto cid = patternMolComp(pat, mol);
                    if (cid && !validStaticVolume(*cid)) {
                        issue(result, BngLoweringSeverity::Error, entity,
                              "physical unimolecular rate requires a positive static declared 3D compartment");
                        return;
                    }
                }
            }
            const auto conversion = bng::units::stochasticRateFactor(*direction.rateLaw->unit, 1, context);
            if (!conversion || !conversion.factor.has_value() || !std::isfinite(*conversion.factor) ||
                *conversion.factor < 0.0) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "physical unimolecular rate unit cannot be converted to a count rate");
                return;
            }
            lowered.rate = *constant * *conversion.factor;
            lowered.volume_factor = 1.0;
        } else {
            const std::string missingVolumeMessage =
                molecularity == 2
                    ? "physical bimolecular rate requires one declared reactant volume unit"
                    : "physical multi-reactant rate requires one declared reactant volume unit";
            std::optional<bng::compile::CompartmentId> sharedCompId;
            for (const auto& rPat : direction.reactantPatterns) {
                for (const auto& mol : rPat.molecules()) {
                    const auto cid = patternMolComp(rPat, mol);
                    if (!cid) {
                        issue(result, BngLoweringSeverity::Error, entity, missingVolumeMessage);
                        return;
                    }
                    if (sharedCompId && *sharedCompId != *cid) {
                        issue(result, BngLoweringSeverity::Error, entity,
                              "physical multi-reactant rate spanning multiple compartments is ambiguous");
                        return;
                    }
                    sharedCompId = cid;
                }
            }
            if (!sharedCompId || !validStaticVolume(*sharedCompId)) {
                issue(result, BngLoweringSeverity::Error, entity, missingVolumeMessage);
                return;
            }
            const auto* decl = source.compartment(*sharedCompId);
            // Convert directly using the full compartment volume and volume
            // unit so every molecularity >= 2 gets exact 1/(N_A*V)^(m-1)
            // count-rate scaling once, and reset geometric volume_factor to 1.
            context.compartmentVolume = decl->volume;
            context.volumeUnit = decl->declaredUnit;
            const auto conversion = bng::units::stochasticRateFactor(
                *direction.rateLaw->unit, molecularity, context);
            if (!conversion || !conversion.factor.has_value() ||
                !std::isfinite(*conversion.factor) || *conversion.factor < 0.0) {
                issue(result, BngLoweringSeverity::Error, entity,
                      molecularity == 2
                          ? "physical bimolecular rate unit cannot be converted to a count rate"
                          : "physical multi-reactant rate unit cannot be converted to a count rate");
                return;
            }
            lowered.rate = *constant * (*conversion.factor);
            lowered.volume_factor = 1.0;
        }
        if (!std::isfinite(lowered.rate) || lowered.rate < 0.0) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "converted physical count rate must be finite and non-negative");
            return;
        }
        std::ostringstream rateText;
        rateText.precision(17);
        rateText << lowered.rate;
        lowered.rate_law.expression = rateText.str();
    }

    if (expandableEnergyStateChange) {
        const auto& mutation = direction.mutations.front();
        if (mutation.source.patternIndex >= direction.reactantPatterns.size() ||
            mutation.source.moleculeIndex >= lowered.pattern.nodes.size()) {
            issue(result, BngLoweringSeverity::Error, entity, "invalid energy state-change mutation source");
            return;
        }
        const auto& reactantMol = direction.reactantPatterns[mutation.source.patternIndex]
                                      .molecules().at(mutation.source.moleculeIndex);
        if (mutation.source.siteIndex >= reactantMol.sites.size() ||
            !reactantMol.moleculeTypeId || !reactantMol.sites[mutation.source.siteIndex].componentType ||
            reactantMol.sites[mutation.source.siteIndex].stateConstraintResolved.kind != bng::compile::StateConstraintKind::Exact ||
            !reactantMol.sites[mutation.source.siteIndex].stateConstraintResolved.exact) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "energy-modulated state change requires a typed exact-state reactant site");
            return;
        }
        const auto& rateExpr = direction.rateLaw->resolvedExpression();
        if (rateExpr.arguments.size() != 2) {
            issue(result, BngLoweringSeverity::Error, entity, "Arrhenius requires phi and activation energy");
            return;
        }
        const auto phi = constantExpression(rateExpr.arguments[0], source);
        const auto ea = constantExpression(rateExpr.arguments[1], source);
        if (!phi || !ea) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "energy-modulated Arrhenius requires static phi and activation energy");
            return;
        }

        const auto molTypeId = reactantMol.moleculeTypeId->value();
        const auto centerSiteTypeId = reactantMol.sites[mutation.source.siteIndex].componentType->index;
        const auto fromStateId = reactantMol.sites[mutation.source.siteIndex].stateConstraintResolved.exact->index;
        const auto toStateId = mutation.newStateId->index;

        double barrierContribution = 0.0;
        if (!source.barrierFactors().empty()) {
            const auto* molTypeDecl = source.moleculeType(*reactantMol.moleculeTypeId);
            const auto* compDecl = source.component(*reactantMol.sites[mutation.source.siteIndex].componentType);
            const auto* fromStateDecl = source.stateName(*reactantMol.sites[mutation.source.siteIndex].stateConstraintResolved.exact);
            const auto* toStateDecl = source.stateName(bng::compile::StateId{
                *reactantMol.sites[mutation.source.siteIndex].componentType, mutation.newStateId->index});
            if (!molTypeDecl || !compDecl || !fromStateDecl || !toStateDecl) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "energy-modulated state change barrier center could not be resolved");
                return;
            }
            const auto centerKey = bng::compile::energy::ReactionCenterKey::stateChange(
                molTypeDecl->name, compDecl->name, *fromStateDecl, *toStateDecl);
            for (const auto& barrier : source.barrierFactors()) {
                if (!barrier.centerResolved) {
                    issue(result, BngLoweringSeverity::Error, entity,
                          "barrier pattern has no supported reaction center");
                    return;
                }
                if (barrier.reactionCenter == centerKey) {
                    if (!barrier.evaluatedValue) {
                        issue(result, BngLoweringSeverity::Error, entity,
                              "barrier pattern energy is not statically evaluable");
                        return;
                    }
                    barrierContribution += *barrier.evaluatedValue;
                }
            }
        }

        // Decide whether any relevant energy pattern requires exact runtime per-match
        // deltaG evaluation (partner molecule/state, homotypic multi-molecule Ising
        // couplings, duplicate-site patterns, or center-site bond constraints).
        auto molTypeHasDupSites = [&](std::size_t mtId) -> bool {
            const auto* mt = source.moleculeType(bng::compile::MoleculeTypeId::fromDenseIndex(mtId));
            if (!mt) return false;
            for (std::size_t i = 0; i < mt->components.size(); ++i)
                for (std::size_t j = i + 1; j < mt->components.size(); ++j)
                    if (mt->components[i].name == mt->components[j].name) return true;
            return false;
        };
        bool useRuntimeArrhenius = molTypeHasDupSites(molTypeId);
        if (!useRuntimeArrhenius) {
            for (const auto& ep : source.energyFactors()) {
                bool relevant = false;
                int weighted = 0;
                for (const auto& mol : ep.pattern.molecules()) {
                    if (!mol.moleculeTypeId) continue;
                    if (mol.moleculeTypeId->value() == molTypeId) {
                        ++weighted;
                        for (const auto& site : mol.sites) {
                            if (site.componentType && site.componentType->index == centerSiteTypeId &&
                                site.stateConstraintResolved.kind == bng::compile::StateConstraintKind::Exact) {
                                relevant = true;
                            }
                        }
                    }
                }
                if (!relevant) continue;
                if (weighted != 1 || ep.pattern.molecules().size() > 1) {
                    useRuntimeArrhenius = true;
                    break;
                }
                // Check if center site itself has a bond constraint or any site has Exact bond.
                for (const auto& site : ep.pattern.molecules().front().sites) {
                    if (!site.componentType) continue;
                    for (const auto& b : patternBonds(site)) {
                        if (b.kind == bng::compile::BondConstraintKind::Exact) {
                            useRuntimeArrhenius = true;
                            break;
                        }
                        if (site.componentType->index == centerSiteTypeId &&
                            (b.kind == bng::compile::BondConstraintKind::Bound ||
                             b.kind == bng::compile::BondConstraintKind::Unbound)) {
                            // Only requires runtime Arrhenius when the rule's own center site
                            // does not already guarantee the exact same bond state (e.g. an
                            // unbound energy pattern A(x~u) on rule A(x~u) -> A(x~p) is static!).
                            bool ruleGuaranteesSame = false;
                            for (const auto& rb : patternBonds(reactantMol.sites[mutation.source.siteIndex])) {
                                if (rb.kind == b.kind) {
                                    ruleGuaranteesSame = true;
                                    break;
                                }
                            }
                            if (!ruleGuaranteesSame) {
                                useRuntimeArrhenius = true;
                                break;
                            }
                        }
                    }
                    if (useRuntimeArrhenius) break;
                }
                if (useRuntimeArrhenius) break;
            }
        }
        if (useRuntimeArrhenius) {
            const double work = drivingWorkValue ? *drivingWorkValue : 0.0;
            lowered.runtime_arrhenius = RuntimeArrheniusInfo{
                true, *phi, *ea, barrierContribution, work, reverseDirection};
            lowered.rate = 0.0;
            lowered.rate_law.kind = RateLawKind::Elementary;
            lowered.rate_law.expression = "0";
            result.model.expanded_rules.push_back(std::move(lowered));
            return;
        }

        struct BondCondSC {
            std::string key;
            std::uint32_t site{0};
            bool requireBound{true};
        };
        struct StateCond {
            std::string key;
            std::uint32_t site{0};
            std::int32_t state{0};
            std::vector<std::int32_t> otherStates;
        };
        std::map<std::string, BondCondSC> condMap;
        std::map<std::string, StateCond> stateCondMap;
        std::vector<int> always;
        // For each conditional energy pattern pi, track all required bond/state condition keys (AND semantics, ETH-08).
        std::map<int, std::vector<std::pair<bool, std::string>>> epRequiredConds; // (isState, key)

        struct CenterContribution {
            bool has_center{false};
            int coefficient{0};
        };
        auto signedCenterContribution = [&](std::size_t patternIndex) -> CenterContribution {
            const auto& ep = source.energyFactors()[patternIndex];
            CenterContribution res;
            for (const auto& mol : ep.pattern.molecules()) {
                if (!mol.moleculeTypeId || mol.moleculeTypeId->value() != molTypeId) continue;
                for (const auto& site : mol.sites) {
                    if (!site.componentType || site.componentType->index != centerSiteTypeId) continue;
                    if (site.stateConstraintResolved.kind != bng::compile::StateConstraintKind::Exact ||
                        !site.stateConstraintResolved.exact) continue;
                    res.has_center = true;
                    const auto st = site.stateConstraintResolved.exact->index;
                    if (st == toStateId) ++res.coefficient;
                    else if (st == fromStateId) --res.coefficient;
                }
            }
            return res;
        };
        auto appendDynamicEnergyTerm = [&](int coefficient,
                                           const bng::compile::CompiledEnergyFactor& ep,
                                           std::vector<std::string>& terms) -> bool {
            if (coefficient == 0) return true;
            std::set<std::size_t> activeFunctions;
            const auto expandedEp = expandZeroArgumentRateFunctions(
                source.expandFunctions(ep.expression), source, activeFunctions);
            if (!expandedEp) return false;
            std::set<std::size_t> observableIds;
            const auto expression = observableRateExpression(*expandedEp, source, observableIds);
            if (!expression) return false;
            std::ostringstream term;
            term << '(' << coefficient << "*(" << *expression << "))";
            terms.push_back(term.str());
            return true;
        };

        // Helper: returns true if (molTypeId, siteIdx) can ever hold a bond in any
        // seed species or rule product pattern. If a site can never be bound in the
        // model, an Unbound constraint on it is tautologically true and needs no
        // branch split.
        auto siteCanEverBeBound = [&](std::size_t mtId, std::size_t sIdx) -> bool {
            auto checkPattern = [&](const bng::compile::Pattern& pat) -> bool {
                for (const auto& pm : pat.molecules()) {
                    if (!pm.moleculeTypeId || pm.moleculeTypeId->value() != mtId) continue;
                    for (const auto& ps : pm.sites) {
                        if (!ps.componentType || ps.componentType->index != sIdx) continue;
                        for (const auto& pb : patternBonds(ps)) {
                            if (pb.kind == bng::compile::BondConstraintKind::Exact ||
                                pb.kind == bng::compile::BondConstraintKind::Bound) {
                                return true;
                            }
                        }
                    }
                }
                return false;
            };
            for (const auto& sd : source.seeds()) {
                if (checkPattern(sd.pattern)) return true;
            }
            for (const auto& r : source.rules()) {
                for (const auto& pp : r.forward().productPatterns) {
                    if (checkPattern(pp)) return true;
                }
                if (r.reverse()) {
                    for (const auto& pp : r.reverse()->productPatterns) {
                        if (checkPattern(pp)) return true;
                    }
                }
            }
            return false;
        };

        for (std::size_t pi = 0; pi < source.energyFactors().size(); ++pi) {
            const auto& ep = source.energyFactors()[pi];
            bool relevant = false;
            for (const auto& mol : ep.pattern.molecules()) {
                if (!mol.moleculeTypeId || mol.moleculeTypeId->value() != molTypeId) continue;
                for (const auto& site : mol.sites) {
                    if (site.componentType && site.componentType->index == centerSiteTypeId &&
                        site.stateConstraintResolved.kind == bng::compile::StateConstraintKind::Exact)
                        relevant = true;
                }
            }
            if (!relevant) continue;

            if (!signedCenterContribution(pi).has_center) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "energy-modulated state change requires a reaction-center state constraint in relevant energy patterns");
                return;
            }

            std::vector<std::pair<bool, std::string>> reqs;
            const auto& mol = ep.pattern.molecules().front();
            for (const auto& site : mol.sites) {
                if (!site.componentType || site.componentType->index == centerSiteTypeId) continue;
                const auto bonds = patternBonds(site);
                bool hasBound = false;
                bool hasUnbound = false;
                for (const auto& b : bonds) {
                    if (b.kind == bng::compile::BondConstraintKind::Exact ||
                        b.kind == bng::compile::BondConstraintKind::Bound) hasBound = true;
                    else if (b.kind == bng::compile::BondConstraintKind::Unbound) hasUnbound = true;
                }
                if (hasBound || (hasUnbound && siteCanEverBeBound(molTypeId, site.componentType->index))) {
                    const auto cname = source.component(*site.componentType)->name;
                    const std::string key = cname + (hasBound ? "!+" : "!-");
                    auto& cc = condMap[key];
                    cc.key = key;
                    cc.site = static_cast<std::uint32_t>(site.componentType->index);
                    cc.requireBound = hasBound;
                    reqs.emplace_back(false, key);
                }
                if (site.stateConstraintResolved.kind == bng::compile::StateConstraintKind::Exact &&
                    site.stateConstraintResolved.exact.has_value()) {
                    const auto* compDecl = source.component(*site.componentType);
                    if (!compDecl || compDecl->stateNames.size() < 2) {
                        issue(result, BngLoweringSeverity::Error, entity,
                              "state-conditioned energy pattern requires a multi-state site");
                        return;
                    }
                    const auto requiredState = static_cast<std::int32_t>(
                        site.stateConstraintResolved.exact->index);
                    const auto key = compDecl->name + "~" + std::to_string(requiredState);
                    auto& sc = stateCondMap[key];
                    if (sc.key.empty()) {
                        sc.key = key;
                        sc.site = static_cast<std::uint32_t>(site.componentType->index);
                        sc.state = requiredState;
                        for (std::size_t si = 0; si < compDecl->stateNames.size(); ++si) {
                            if (static_cast<std::int32_t>(si) != requiredState)
                                sc.otherStates.push_back(static_cast<std::int32_t>(si));
                        }
                    }
                    reqs.emplace_back(true, key);
                }
            }
            if (reqs.empty()) {
                always.push_back(static_cast<int>(pi));
            } else {
                epRequiredConds[static_cast<int>(pi)] = std::move(reqs);
            }
        }

        double baseEnergy = 0.0;
        std::vector<std::string> baseDynamicTerms;
        for (int pi : always) {
            const auto center = signedCenterContribution(static_cast<std::size_t>(pi));
            const auto& ep = source.energyFactors()[static_cast<std::size_t>(pi)];
            if (isDynamicEnergyFactor(ep, source)) {
                if (!appendDynamicEnergyTerm(center.coefficient, ep, baseDynamicTerms)) {
                    issue(result, BngLoweringSeverity::Error, entity,
                          "dynamic energy expression could not be resolved to NFIR arithmetic");
                    return;
                }
            } else {
                baseEnergy += static_cast<double>(center.coefficient) * energyFactorValue(ep, source);
            }
        }

        std::vector<BondCondSC> conditions;
        conditions.reserve(condMap.size());
        std::map<std::string, std::size_t> bondCondBit;
        for (auto& kv : condMap) {
            bondCondBit[kv.first] = conditions.size();
            conditions.push_back(std::move(kv.second));
        }
        std::vector<StateCond> stateConditions;
        stateConditions.reserve(stateCondMap.size());
        std::map<std::string, std::size_t> stateCondBit;
        for (auto& kv : stateCondMap) {
            stateCondBit[kv.first] = conditions.size() + stateConditions.size();
            stateConditions.push_back(std::move(kv.second));
        }

        const std::size_t totalConditionCount = conditions.size() + stateConditions.size();
        if (totalConditionCount >= 20) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "energy-modulated state change expansion too large for NFnext");
            return;
        }

        // Build per-EP required bitmasks (logical AND — ETH-08).
        std::vector<std::pair<int, std::uint32_t>> epMasks;
        epMasks.reserve(epRequiredConds.size());
        for (const auto& [pi, reqs] : epRequiredConds) {
            std::uint32_t mask = 0;
            for (const auto& [isState, key] : reqs) {
                const std::size_t bit = isState ? stateCondBit.at(key) : bondCondBit.at(key);
                mask |= (std::uint32_t{1} << bit);
            }
            epMasks.emplace_back(pi, mask);
        }

        const std::size_t targetNode = mutation.source.moleculeIndex;
        const int combos = 1 << static_cast<int>(totalConditionCount);
        for (int combo = 0; combo < combos; ++combo) {
            ExpandedRuleIR variant = lowered;
            variant.id = static_cast<RuleId>(id * 1024u + static_cast<RuleId>(combo));
            variant.name = entity + (reverseDirection ? "_rev_v" : "_v") + std::to_string(combo);
            variant.rate_law.kind = RateLawKind::Elementary;
            if (targetNode >= variant.pattern.nodes.size()) continue;
            bool feasible = true;
            for (std::size_t ci = 0; ci < conditions.size() && feasible; ++ci) {
                const bool met = (combo >> ci) & 1;
                const bool wantBound = met ? conditions[ci].requireBound : !conditions[ci].requireBound;
                if (!tryAddBranchBondConstraint(variant.pattern, targetNode, conditions[ci].site, wantBound)) {
                    feasible = false;
                }
            }
            for (std::size_t si = 0; si < stateConditions.size() && feasible; ++si) {
                const bool met = (combo >> (conditions.size() + si)) & 1;
                const auto& sc = stateConditions[si];
                const std::vector<std::int32_t> states =
                    met ? std::vector<std::int32_t>{sc.state} : sc.otherStates;
                if (!tryAddBranchStateConstraint(variant.pattern.nodes[targetNode], sc.site, states)) {
                    feasible = false;
                }
            }
            if (!feasible) continue;
            variant.predicates.clear();
            addPredicates(variant.pattern, variant.predicates);
            double deltaG = baseEnergy;
            std::vector<std::string> dynamicTerms = baseDynamicTerms;
            const auto comboMask = static_cast<std::uint32_t>(combo);
            for (const auto& [pi, reqMask] : epMasks) {
                if ((comboMask & reqMask) != reqMask) continue;
                const auto center = signedCenterContribution(static_cast<std::size_t>(pi));
                const auto& ep = source.energyFactors()[static_cast<std::size_t>(pi)];
                if (isDynamicEnergyFactor(ep, source)) {
                    if (!appendDynamicEnergyTerm(center.coefficient, ep, dynamicTerms)) {
                        issue(result, BngLoweringSeverity::Error, entity,
                              "dynamic energy expression could not be resolved to NFIR arithmetic");
                        return;
                    }
                } else {
                    deltaG += static_cast<double>(center.coefficient) * energyFactorValue(ep, source);
                }
            }
            const double work = drivingWorkValue ? *drivingWorkValue : 0.0;
            const double phiEff = reverseDirection ? (1.0 - *phi) : *phi;
            const double constantPart = *ea + barrierContribution + phiEff * deltaG +
                                         (reverseDirection ? phiEff * work : -phiEff * work);
            if (!std::isfinite(constantPart)) {
                issue(result, BngLoweringSeverity::Error, entity, "expanded energy-modulated rate is invalid");
                return;
            }
            if (dynamicTerms.empty()) {
                const double rate = std::exp(-constantPart);
                if (!std::isfinite(rate) || rate < 0.0) {
                    issue(result, BngLoweringSeverity::Error, entity, "expanded energy-modulated rate is invalid");
                    return;
                }
                variant.rate = rate;
                std::ostringstream rateText;
                rateText.precision(17);
                rateText << rate;
                variant.rate_law.expression = rateText.str();
            } else {
                std::ostringstream dynamicDelta;
                for (std::size_t i = 0; i < dynamicTerms.size(); ++i) {
                    if (i != 0) dynamicDelta << '+';
                    dynamicDelta << dynamicTerms[i];
                }
                std::ostringstream rateText;
                rateText.precision(17);
                rateText << "exp(-(" << constantPart << " + (" << phiEff
                         << ")*(" << dynamicDelta.str() << ")))";
                variant.rate = 0.0;
                variant.rate_law.kind = RateLawKind::Function;
                variant.rate_law.expression = rateText.str();
            }
            result.model.expanded_rules.push_back(std::move(variant));
        }
        return;
    }

    if (expandableEnergyBinding || expandableEnergyUnbinding) {
        const auto& mutation = direction.mutations.front();
        const auto nodeA = nodeFor(mutation.source, *flattened);
        const auto nodeB = nodeFor(mutation.partner, *flattened);
        if (!nodeA || !nodeB ||
            mutation.source.patternIndex >= direction.reactantPatterns.size() ||
            mutation.partner.patternIndex >= direction.reactantPatterns.size()) {
            issue(result, BngLoweringSeverity::Error, entity, "invalid energy bond mutation endpoints");
            return;
        }
        const auto& molA = direction.reactantPatterns[mutation.source.patternIndex]
                               .molecules().at(mutation.source.moleculeIndex);
        const auto& molB = direction.reactantPatterns[mutation.partner.patternIndex]
                               .molecules().at(mutation.partner.moleculeIndex);
        if (mutation.source.siteIndex >= molA.sites.size() ||
            mutation.partner.siteIndex >= molB.sites.size() ||
            !molA.moleculeTypeId || !molB.moleculeTypeId ||
            !molA.sites[mutation.source.siteIndex].componentType ||
            !molB.sites[mutation.partner.siteIndex].componentType) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "energy-modulated binding/unbinding requires typed reaction-center sites");
            return;
        }
        const auto& rateExpr = direction.rateLaw->resolvedExpression();
        if (rateExpr.arguments.size() != 2) {
            issue(result, BngLoweringSeverity::Error, entity, "Arrhenius requires phi and activation energy");
            return;
        }
        const auto phi = constantExpression(rateExpr.arguments[0], source);
        const auto ea = constantExpression(rateExpr.arguments[1], source);
        if (!phi || !ea) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "energy-modulated Arrhenius requires static phi and activation energy");
            return;
        }

        const auto molTypeA = molA.moleculeTypeId->value();
        const auto siteA = molA.sites[mutation.source.siteIndex].componentType->index;
        const auto molTypeB = molB.moleculeTypeId->value();
        const auto siteB = molB.sites[mutation.partner.siteIndex].componentType->index;
        const int bondSign = expandableEnergyBinding ? 1 : -1;

        const auto* molDeclA = source.moleculeType(*molA.moleculeTypeId);
        const auto* compDeclA = source.component(*molA.sites[mutation.source.siteIndex].componentType);
        const auto* molDeclB = source.moleculeType(*molB.moleculeTypeId);
        const auto* compDeclB = source.component(*molB.sites[mutation.partner.siteIndex].componentType);
        if (!molDeclA || !compDeclA || !molDeclB || !compDeclB) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "energy-modulated binding/unbinding declarations could not be resolved");
            return;
        }

        double barrierContribution = 0.0;
        if (!source.barrierFactors().empty()) {
            const auto centerKey = bng::compile::energy::ReactionCenterKey::binding(
                molDeclA->name, compDeclA->name, molDeclB->name, compDeclB->name);
            for (const auto& barrier : source.barrierFactors()) {
                if (!barrier.centerResolved) {
                    issue(result, BngLoweringSeverity::Error, entity,
                          "barrier pattern has no supported reaction center");
                    return;
                }
                if (barrier.reactionCenter == centerKey) {
                    if (!barrier.evaluatedValue) {
                        issue(result, BngLoweringSeverity::Error, entity,
                              "barrier pattern energy is not statically evaluable");
                        return;
                    }
                    barrierContribution += *barrier.evaluatedValue;
                }
            }
        }

        auto declHasDupSites = [](const bng::compile::CompiledMoleculeType* mt) -> bool {
            if (!mt) return false;
            for (std::size_t i = 0; i < mt->components.size(); ++i)
                for (std::size_t j = i + 1; j < mt->components.size(); ++j)
                    if (mt->components[i].name == mt->components[j].name) return true;
            return false;
        };

        // Route to exact runtime per-match deltaG evaluation when any energy pattern
        // has >=3 molecules (cooperativity, ETH-11), duplicate component names (e.g.
        // R(s,s) in energy_cooperativity_adh, ETH-13), wildcard !+ single-molecule
        // patterns (ETH-11), extra bond context (ETH-09), or homodimer asymmetry.
        bool useRuntimeArrhenius = declHasDupSites(molDeclA) || declHasDupSites(molDeclB);
        if (!useRuntimeArrhenius) {
            for (const auto& ep : source.energyFactors()) {
                const auto& mols = ep.pattern.molecules();
                if (mols.size() >= 3) {
                    useRuntimeArrhenius = true;
                    break;
                }
                if (mols.size() == 1 && mols[0].moleculeTypeId) {
                    const auto mType = mols[0].moleculeTypeId->value();
                    if (mType == molTypeA || mType == molTypeB) {
                        for (const auto& s : mols[0].sites) {
                            if (!s.componentType) continue;
                            for (const auto& b : patternBonds(s)) {
                                if (b.kind == bng::compile::BondConstraintKind::Bound) {
                                    useRuntimeArrhenius = true;
                                    break;
                                }
                            }
                            if (mols[0].sites.size() > 1 ||
                                s.stateConstraintResolved.kind != bng::compile::StateConstraintKind::Any) {
                                useRuntimeArrhenius = true;
                            }
                            if (useRuntimeArrhenius) break;
                        }
                    }
                } else if (mols.size() == 2) {
                    for (const auto& m : mols) {
                        if (!m.moleculeTypeId) continue;
                        if (m.moleculeTypeId->value() == molTypeA || m.moleculeTypeId->value() == molTypeB) {
                            // If a 2-mol EP has any extra bond constraint outside the center bond,
                            // or asymmetric homodimer constraints, use exact runtime deltaG.
                            std::size_t bondCount = 0;
                            for (const auto& s : m.sites) {
                                for (const auto& b : patternBonds(s)) {
                                    if (b.kind == bng::compile::BondConstraintKind::Exact ||
                                        b.kind == bng::compile::BondConstraintKind::Bound ||
                                        b.kind == bng::compile::BondConstraintKind::Unbound) {
                                        ++bondCount;
                                    }
                                }
                            }
                            if (bondCount > 1) {
                                useRuntimeArrhenius = true;
                                break;
                            }
                        }
                    }
                }
                if (useRuntimeArrhenius) break;
            }
        }
        if (useRuntimeArrhenius) {
            const double work = drivingWorkValue ? *drivingWorkValue : 0.0;
            lowered.runtime_arrhenius = RuntimeArrheniusInfo{
                true, *phi, *ea, barrierContribution, work, reverseDirection};
            lowered.rate = 0.0;
            lowered.rate_law.kind = RateLawKind::Elementary;
            lowered.rate_law.expression = "0";
            result.model.expanded_rules.push_back(std::move(lowered));
            return;
        }

        auto appendDynamicEnergyTerm = [&](int coefficient,
                                           const bng::compile::CompiledEnergyFactor& ep,
                                           std::vector<std::string>& terms) -> bool {
            if (coefficient == 0) return true;
            std::set<std::size_t> activeFunctions;
            const auto expandedEp = expandZeroArgumentRateFunctions(
                source.expandFunctions(ep.expression), source, activeFunctions);
            if (!expandedEp) return false;
            std::set<std::size_t> observableIds;
            const auto expression = observableRateExpression(*expandedEp, source, observableIds);
            if (!expression) return false;
            std::ostringstream term;
            term << '(' << coefficient << "*(" << *expression << "))";
            terms.push_back(term.str());
            return true;
        };

        struct BondCond {
            std::string key;
            std::size_t targetNode{0};
            std::uint32_t site{0};
            bool isState{false};
            std::int32_t state{0};
            std::vector<std::int32_t> otherStates;
        };
        std::map<std::string, BondCond> condMap;
        std::vector<std::pair<int, int>> alwaysTerms; // (energyPatternIndex, coeff)
        // Per-EP required condition keys + coeff (logical AND — ETH-08).
        std::vector<std::tuple<int, int, std::vector<std::string>>> conditionalTerms;

        // Helper: returns true if (molTypeId, siteIdx) can ever hold a bond in any
        // seed species or rule product pattern. If a site can never be bound in the
        // model, an Unbound constraint on it is tautologically true and needs no
        // branch split.
        auto siteCanEverBeBound = [&](std::size_t mtId, std::size_t sIdx) -> bool {
            auto checkPattern = [&](const bng::compile::Pattern& pat) -> bool {
                for (const auto& pm : pat.molecules()) {
                    if (!pm.moleculeTypeId || pm.moleculeTypeId->value() != mtId) continue;
                    for (const auto& ps : pm.sites) {
                        if (!ps.componentType || ps.componentType->index != sIdx) continue;
                        for (const auto& pb : patternBonds(ps)) {
                            if (pb.kind == bng::compile::BondConstraintKind::Exact ||
                                pb.kind == bng::compile::BondConstraintKind::Bound) {
                                return true;
                            }
                        }
                    }
                }
                return false;
            };
            for (const auto& sd : source.seeds()) {
                if (checkPattern(sd.pattern)) return true;
            }
            for (const auto& r : source.rules()) {
                for (const auto& pp : r.forward().productPatterns) {
                    if (checkPattern(pp)) return true;
                }
                if (r.reverse()) {
                    for (const auto& pp : r.reverse()->productPatterns) {
                        if (checkPattern(pp)) return true;
                    }
                }
            }
            return false;
        };

        for (std::size_t pi = 0; pi < source.energyFactors().size(); ++pi) {
            const auto& ep = source.energyFactors()[pi];
            const auto& mols = ep.pattern.molecules();
            if (mols.size() == 2) {
                struct EpEnd { std::size_t molIdx; std::size_t molType; std::size_t siteIdx; };
                std::map<std::size_t, std::vector<EpEnd>> bondGroups;
                for (std::size_t mi = 0; mi < 2; ++mi) {
                    if (!mols[mi].moleculeTypeId) continue;
                    for (const auto& s : mols[mi].sites) {
                        if (!s.componentType) continue;
                        for (const auto& b : patternBonds(s)) {
                            if (b.kind == bng::compile::BondConstraintKind::Exact) {
                                bondGroups[b.group.value].push_back(
                                    {mi, mols[mi].moleculeTypeId->value(), s.componentType->index});
                            }
                        }
                    }
                }
                int matchOrient = -1;
                for (const auto& [grp, ends] : bondGroups) {
                    if (ends.size() != 2 || ends[0].molIdx == ends[1].molIdx) continue;
                    const auto& e0 = ends[0].molIdx == 0 ? ends[0] : ends[1];
                    const auto& e1 = ends[0].molIdx == 0 ? ends[1] : ends[0];
                    if (e0.molType == molTypeA && e0.siteIdx == siteA &&
                        e1.molType == molTypeB && e1.siteIdx == siteB) {
                        matchOrient = 0;
                        break;
                    }
                    if (e0.molType == molTypeB && e0.siteIdx == siteB &&
                        e1.molType == molTypeA && e1.siteIdx == siteA) {
                        matchOrient = 1;
                        break;
                    }
                }
                if (matchOrient < 0) continue;

                std::vector<BondCond> epConditions;
                const std::array<std::size_t, 2> epToNode =
                    matchOrient == 0
                        ? std::array<std::size_t, 2>{static_cast<std::size_t>(*nodeA), static_cast<std::size_t>(*nodeB)}
                        : std::array<std::size_t, 2>{static_cast<std::size_t>(*nodeB), static_cast<std::size_t>(*nodeA)};
                const std::array<std::size_t, 2> epCenterSite =
                    matchOrient == 0
                        ? std::array<std::size_t, 2>{siteA, siteB}
                        : std::array<std::size_t, 2>{siteB, siteA};
                for (std::size_t mi = 0; mi < 2; ++mi) {
                    for (const auto& s : mols[mi].sites) {
                        if (!s.componentType) continue;
                        if (s.componentType->index == epCenterSite[mi]) continue;
                        if (s.stateConstraintResolved.kind == bng::compile::StateConstraintKind::Exact &&
                            s.stateConstraintResolved.exact.has_value()) {
                            const auto* cDecl = source.component(*s.componentType);
                            if (!cDecl || cDecl->stateNames.size() < 2) {
                                issue(result, BngLoweringSeverity::Error, entity,
                                      "state-conditioned bond energy pattern requires a multi-state site");
                                return;
                            }
                            BondCond c;
                            c.targetNode = epToNode[mi];
                            c.site = static_cast<std::uint32_t>(s.componentType->index);
                            c.isState = true;
                            c.state = static_cast<std::int32_t>(s.stateConstraintResolved.exact->index);
                            for (std::size_t si = 0; si < cDecl->stateNames.size(); ++si) {
                                if (static_cast<std::int32_t>(si) != c.state)
                                    c.otherStates.push_back(static_cast<std::int32_t>(si));
                            }
                            c.key = "n" + std::to_string(c.targetNode) + ":s:" + std::to_string(c.site) + "~" + std::to_string(c.state);
                            epConditions.push_back(std::move(c));
                        }
                    }
                }
                if (epConditions.empty()) {
                    alwaysTerms.emplace_back(static_cast<int>(pi), bondSign);
                } else {
                    if (molTypeA == molTypeB && siteA == siteB) {
                        // Homodimer conditional energy pattern -> route to exact runtime deltaG!
                        const double work = drivingWorkValue ? *drivingWorkValue : 0.0;
                        lowered.runtime_arrhenius = RuntimeArrheniusInfo{
                            true, *phi, *ea, barrierContribution, work, reverseDirection};
                        lowered.rate = 0.0;
                        lowered.rate_law.kind = RateLawKind::Elementary;
                        lowered.rate_law.expression = "0";
                        result.model.expanded_rules.push_back(std::move(lowered));
                        return;
                    }
                    std::vector<std::string> reqKeys;
                    for (auto& ec : epConditions) {
                        reqKeys.push_back(ec.key);
                        auto& slot = condMap[ec.key];
                        if (slot.key.empty()) slot = std::move(ec);
                    }
                    conditionalTerms.emplace_back(static_cast<int>(pi), bondSign, std::move(reqKeys));
                }
            } else if (mols.size() == 1 && mols[0].moleculeTypeId) {
                const auto mType = mols[0].moleculeTypeId->value();
                for (const auto& s : mols[0].sites) {
                    if (!s.componentType) continue;
                    const auto bkind = normalizedBondKind(s.bondKind);
                    const bool isUnboundConstraint =
                        bkind == bng::compile::BondConstraintKind::Unbound &&
                        s.bondConstraints.empty();
                    if (!isUnboundConstraint) continue;
                    int coeff = 0;
                    if (mType == molTypeA && s.componentType->index == siteA) coeff -= bondSign;
                    if (mType == molTypeB && s.componentType->index == siteB) coeff -= bondSign;
                    if (coeff != 0) alwaysTerms.emplace_back(static_cast<int>(pi), coeff);
                }
            }
        }

        double baseEnergy = 0.0;
        std::vector<std::string> baseDynamicTerms;
        for (const auto& [pi, coeff] : alwaysTerms) {
            const auto& ep = source.energyFactors()[static_cast<std::size_t>(pi)];
            if (isDynamicEnergyFactor(ep, source)) {
                if (!appendDynamicEnergyTerm(coeff, ep, baseDynamicTerms)) {
                    issue(result, BngLoweringSeverity::Error, entity,
                          "dynamic energy expression could not be resolved to NFIR arithmetic");
                    return;
                }
            } else {
                baseEnergy += static_cast<double>(coeff) * energyFactorValue(ep, source);
            }
        }

        std::vector<BondCond> conditions;
        conditions.reserve(condMap.size());
        std::map<std::string, std::size_t> condBit;
        for (auto& kv : condMap) {
            condBit[kv.first] = conditions.size();
            conditions.push_back(std::move(kv.second));
        }
        if (conditions.size() >= 20) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "energy-modulated binding/unbinding expansion too large for NFnext");
            return;
        }

        std::vector<std::tuple<int, int, std::uint32_t>> condMasks;
        condMasks.reserve(conditionalTerms.size());
        for (const auto& [pi, coeff, keys] : conditionalTerms) {
            std::uint32_t mask = 0;
            for (const auto& k : keys) mask |= (std::uint32_t{1} << condBit.at(k));
            condMasks.emplace_back(pi, coeff, mask);
        }

        const int combos = 1 << static_cast<int>(conditions.size());
        for (int combo = 0; combo < combos; ++combo) {
            ExpandedRuleIR variant = lowered;
            variant.id = static_cast<RuleId>(id * 1024u + static_cast<RuleId>(combo));
            variant.name = entity + (reverseDirection ? "_rev_v" : "_v") + std::to_string(combo);
            variant.rate_law.kind = RateLawKind::Elementary;
            bool feasible = true;
            for (std::size_t ci = 0; ci < conditions.size() && feasible; ++ci) {
                const bool met = (combo >> ci) & 1;
                const auto& c = conditions[ci];
                if (c.targetNode >= variant.pattern.nodes.size()) continue;
                if (c.isState) {
                    const std::vector<std::int32_t> states =
                        met ? std::vector<std::int32_t>{c.state} : c.otherStates;
                    if (!tryAddBranchStateConstraint(variant.pattern.nodes[c.targetNode], c.site, states)) {
                        feasible = false;
                    }
                } else {
                    if (!tryAddBranchBondConstraint(variant.pattern, c.targetNode, c.site, met)) {
                        feasible = false;
                    }
                }
            }
            if (!feasible) continue;
            variant.predicates.clear();
            addPredicates(variant.pattern, variant.predicates);

            double deltaG = baseEnergy;
            std::vector<std::string> dynamicTerms = baseDynamicTerms;
            const auto comboMask = static_cast<std::uint32_t>(combo);
            for (const auto& [pi, coeff, reqMask] : condMasks) {
                if ((comboMask & reqMask) != reqMask) continue;
                const auto& ep = source.energyFactors()[static_cast<std::size_t>(pi)];
                if (isDynamicEnergyFactor(ep, source)) {
                    if (!appendDynamicEnergyTerm(coeff, ep, dynamicTerms)) {
                        issue(result, BngLoweringSeverity::Error, entity,
                              "dynamic energy expression could not be resolved to NFIR arithmetic");
                        return;
                    }
                } else {
                    deltaG += static_cast<double>(coeff) * energyFactorValue(ep, source);
                }
            }

            const double work = drivingWorkValue ? *drivingWorkValue : 0.0;
            const double phiEff = reverseDirection ? (1.0 - *phi) : *phi;
            const double constantPart = *ea + barrierContribution + phiEff * deltaG +
                                         (reverseDirection ? phiEff * work : -phiEff * work);
            if (!std::isfinite(constantPart)) {
                issue(result, BngLoweringSeverity::Error, entity, "expanded energy-modulated rate is invalid");
                return;
            }
            if (dynamicTerms.empty()) {
                const double rate = std::exp(-constantPart);
                if (!std::isfinite(rate) || rate < 0.0) {
                    issue(result, BngLoweringSeverity::Error, entity, "expanded energy-modulated rate is invalid");
                    return;
                }
                variant.rate = rate;
                std::ostringstream rateText;
                rateText.precision(17);
                rateText << rate;
                variant.rate_law.expression = rateText.str();
            } else {
                std::ostringstream dynamicDelta;
                for (std::size_t i = 0; i < dynamicTerms.size(); ++i) {
                    if (i != 0) dynamicDelta << '+';
                    dynamicDelta << dynamicTerms[i];
                }
                std::ostringstream rateText;
                rateText.precision(17);
                rateText << "exp(-(" << constantPart << " + (" << phiEff
                         << ")*(" << dynamicDelta.str() << ")))";
                variant.rate = 0.0;
                variant.rate_law.kind = RateLawKind::Function;
                variant.rate_law.expression = rateText.str();
            }
            result.model.expanded_rules.push_back(std::move(variant));
        }
        return;
    }

    result.model.expanded_rules.push_back(std::move(lowered));
}

TransformationIR buildRuleTransformation(const ExpandedRuleIR& rule) {
    TransformationIR transformation;
    const std::size_t reactant_node_count = rule.pattern.nodes.size();

    std::map<PatternNodeId, CreatedMoleculeId> node_to_created;
    std::map<PatternNodeId, TypeId> created_types;
    std::map<PatternNodeId, std::vector<std::pair<std::uint32_t, std::int32_t>>> created_states;
    std::map<PatternNodeId, CompartmentId> created_compartments;

    CreatedMoleculeId next_created = 0;
    for (const auto& action : rule.actions) {
        if (action.kind == ActionKind::Create) {
            PatternNodeId node = action.target_node;
            if (node_to_created.find(node) == node_to_created.end()) {
                CreatedMoleculeId cid = next_created++;
                node_to_created[node] = cid;
                created_types[node] = action.molecule_type;
            }
        } else if (action.kind == ActionKind::SetSiteState && action.target_node >= reactant_node_count) {
            created_states[action.target_node].push_back({action.site, action.value});
        } else if (action.kind == ActionKind::SetCompartment && action.target_node >= reactant_node_count) {
            created_compartments[action.target_node] = static_cast<CompartmentId>(action.value);
        }
    }

    // 1. Create all newly synthesized molecules with their initial site states and compartments
    for (const auto& [node, cid] : node_to_created) {
        CompartmentId comp = 0;
        const auto it = created_compartments.find(node);
        if (it != created_compartments.end()) comp = it->second;
        transformation.createMoleculeWithId(cid, created_types[node], created_states[node], comp);
    }

    // 2. Perform state updates and unbinding BEFORE binding (RULEHUB-05).
    std::vector<ActionIR> binds;
    std::vector<ActionIR> destructions;
    for (const auto& action : rule.actions) {
        switch (action.kind) {
        case ActionKind::Create:
            break;
        case ActionKind::SetSiteState:
            if (action.target_node < reactant_node_count) {
                transformation.setState(action.target_node, action.site, action.value);
            }
            break;
        case ActionKind::SetCompartment:
            break;
        case ActionKind::Unbind:
            transformation.deleteBond(action.target_node, action.site,
                                      action.partner_node, action.partner_site);
            break;
        case ActionKind::Bind:
            binds.push_back(action);
            break;
        case ActionKind::Destroy:
        case ActionKind::DestroyComplex:
            destructions.push_back(action);
            break;
        case ActionKind::MovePosition:
            throw std::runtime_error("NFnext MovePosition action not supported in standard BNG");
        }
    }

    // 2b. Perform bindings after all unbindings have freed their sites.
    for (const auto& action : binds) {
        const bool first_created = (action.target_node >= reactant_node_count);
        const bool second_created = (action.partner_node >= reactant_node_count);
        if (!first_created && !second_created) {
            transformation.addBond(action.target_node, action.site,
                                   action.partner_node, action.partner_site);
        } else if (!first_created && second_created) {
            transformation.addBondExistingToCreated(
                action.target_node, action.site,
                node_to_created.at(action.partner_node), action.partner_site);
        } else if (first_created && !second_created) {
            transformation.addBondExistingToCreated(
                action.partner_node, action.partner_site,
                node_to_created.at(action.target_node), action.site);
        } else {
            transformation.addBondCreated(
                node_to_created.at(action.target_node), action.site,
                node_to_created.at(action.partner_node), action.partner_site);
        }
    }

    // 3. Perform destructions
    for (const auto& action : destructions) {
        if (action.kind == ActionKind::Destroy) {
            transformation.destroyMolecule(action.target_node);
        } else if (action.kind == ActionKind::DestroyComplex) {
            transformation.destroyComplexContaining(action.target_node);
        }
    }

    return transformation;
}

} // namespace

bool BngLoweringResult::ok() const noexcept {
    for (const auto& current : issues)
        if (current.severity == BngLoweringSeverity::Error) return false;
    return true;
}

BngLoweringResult lowerFromBioNetGen(const bng::compile::CompiledModel& source) {
    BngLoweringResult result;
    result.model.model_name = source.metadata().name;

    if (!source.valid()) {
        issue(result, BngLoweringSeverity::Error, source.metadata().name,
              "BioNetGen compiled model contains semantic errors");
        return result;
    }
    if (source.metadata().hasNativeEvents) {
        issue(result, BngLoweringSeverity::Error, source.metadata().name,
              "native events are not executable by NFnext");
        return result;
    }
    if (const auto declaredTime = source.metadata().unitDefaults.find("timeUnits");
        declaredTime != source.metadata().unitDefaults.end()) {
        const auto resolved = source.metadata().resolvedUnitReferences.find(declaredTime->second);
        bng::units::UnitSystem unitSystem;
        const auto second = unitSystem.parse("second");
        if (resolved == source.metadata().resolvedUnitReferences.end() || !second) {
            issue(result, BngLoweringSeverity::Error, source.metadata().name,
                  "declared timeUnits cannot be resolved for NFnext's second clock");
            return result;
        }
        const auto conv = bng::units::conversionFactor(resolved->second.unit, *second.unit);
        if (!conv || !conv.factor.has_value() || !std::isfinite(*conv.factor) || *conv.factor <= 0.0) {
            issue(result, BngLoweringSeverity::Error, source.metadata().name,
                  "declared timeUnits cannot be converted to seconds");
            return result;
        }
    }
    if (!validateNFnextIdPacking(source, result)) return result;
    // Lower compartment declarations into NFIR. Compartments are carried as
    // metadata; volume-dependent rate scaling is the responsibility of the
    // execution backend. When compartments are present the lowering produces a
    // warning that execution does not yet interpret compartment-specific volume
    // semantics, but all structural lowering proceeds normally.
    if (!source.compartments().empty()) {
        result.model.compartments.reserve(source.compartments().size());
        for (const auto& compartment : source.compartments()) {
            CompartmentIR irCompartment;
            irCompartment.id = static_cast<CompartmentId>(compartment.id.value());
            irCompartment.name = compartment.name;
            irCompartment.dimensions = compartment.dimension;
            irCompartment.volume = compartment.volume;
            if (compartment.parent)
                irCompartment.parent = static_cast<CompartmentId>(compartment.parent->value());
            result.model.compartments.push_back(std::move(irCompartment));
        }
    }
    // Lower energy patterns into NFIR. Energy patterns provide ground-state
    // free energy contributions that modify reaction rates through Boltzmann
    // factors. The pattern is lowered to the same PatternIR used for rules.
    if (!source.energyFactors().empty()) {
        result.model.energy_patterns.reserve(source.energyFactors().size());
        for (const auto& factor : source.energyFactors()) {
            EnergyPatternIR irEnergy;
            irEnergy.label = factor.label;
            irEnergy.expression = factor.energyExpression;
            if (factor.evaluatedValue) {
                irEnergy.energy = *factor.evaluatedValue;
            } else if (const auto value = constantExpression(factor.expression, source)) {
                irEnergy.energy = *value;
            } else {
                // A dynamic energy expression is representable as source text
                // in `expression`; only the static `energy` field is unset.
                // For an energy-modulated Arrhenius rate the expansion composes
                // the expression into a runtime Function rate law; energy
                // patterns with no modulating rule remain representation-only.
                irEnergy.energy = 0.0;
                issue(result, BngLoweringSeverity::Warning, factor.label,
                      "dynamic energy pattern has no static value; represented "
                      "by expression and evaluated at runtime when it modulates a rule");
            }
            BngLoweringResult patternValidation;
            const auto pattern = flattenReactants(
                {factor.pattern}, patternValidation, factor.label, true, &source);
            if (pattern && patternValidation.ok()) {
                irEnergy.pattern = pattern->pattern;
            } else {
                issue(result, BngLoweringSeverity::Error, factor.label,
                      "energy pattern could not be lowered to NFIR");
            }
            result.model.energy_patterns.push_back(std::move(irEnergy));
        }
    }
    // Lower population maps into NFIR. A map is always retained as metadata for
    // representation consumers. For the supported simple shape we additionally
    // synthesize an executable ExpandedRuleIR so NFnext can run the map
    // directly; anything outside that shape remains fail-closed at execution.
    struct ExecutablePopulationMap {
        std::size_t index{0};
        std::string name;
        PatternIR pattern;
        TypeId product_type{0};
        std::optional<CompartmentId> product_compartment;
        bool total_rate{false};
        bool rate_is_static{false};
        double static_rate{0.0};
        std::string rate_expression;
    };
    std::vector<ExecutablePopulationMap> executableMaps;
    if (!source.populationMaps().empty()) {
        result.model.population_maps.reserve(source.populationMaps().size());
        for (const auto& popMap : source.populationMaps()) {
            PopulationMapIR irPopMap;
            irPopMap.population_name = popMap.populationName;
            irPopMap.rate_expression = popMap.sourceRate + (popMap.totalRate ? " TotalRate" : "");
            BngLoweringResult patternValidation;
            const auto pattern = flattenReactants(
                {popMap.pattern}, patternValidation, popMap.populationName, false, &source);
            if (pattern && patternValidation.ok()) {
                irPopMap.pattern = pattern->pattern;
            } else {
                issue(result, BngLoweringSeverity::Error, popMap.populationName,
                      "population map pattern could not be lowered to NFIR");
            }
            std::set<std::size_t> activeRateFunctions;
            const auto expandedRate = expandZeroArgumentRateFunctions(
                source.expandFunctions(popMap.rate), source, activeRateFunctions);
            const auto rateValue = expandedRate
                ? constantExpression(*expandedRate, source) : std::nullopt;
            if (rateValue) {
                irPopMap.rate = *rateValue;
            } else {
                irPopMap.rate = 0.0;
                issue(result, BngLoweringSeverity::Warning, popMap.populationName,
                      "dynamic population map rate has no static value; lowered to a "
                      "runtime observable-dependent rate law when its dependency is supported");
            }

            // Decide whether this map has an exactly representable shape that
            // NFnext can execute. All other shapes stay fail-closed.
            std::string unsupported;
            if (!pattern || !patternValidation.ok()) {
                unsupported = "population map pattern could not be lowered";
            } else if (!expandedRate) {
                unsupported = "population map rate contains an unresolved function";
            } else {
                for (const auto& node : pattern->pattern.nodes) {
                    const auto* molType = source.moleculeType(
                        bng::compile::MoleculeTypeId::fromDenseIndex(
                            static_cast<std::size_t>(node.molecule_type)));
                    if (!molType) {
                        unsupported = "population map reactant references an unknown molecule type";
                        break;
                    }
                    if (molType->population) {
                        // A map reactant must be a particle pattern; bonds to
                        // population nodes are therefore outside this shape.
                        unsupported = "population map reactants must be particle molecules";
                        break;
                    }
                }
            }
            // The product must be a declared population type with no components.
            TypeId productType{0};
            if (unsupported.empty()) {
                bool found = false;
                for (const auto& molType : source.moleculeTypes()) {
                    if (!molType.population || molType.name != popMap.populationName) continue;
                    if (!molType.components.empty()) {
                        unsupported = "population map product must have no components";
                    } else {
                        productType = static_cast<TypeId>(molType.id.value());
                        found = true;
                    }
                    break;
                }
                if (unsupported.empty() && !found)
                    unsupported = "population map product is not a declared population type";
            }
            // The rate is either a finite non-negative constant or an
            // observable-only arithmetic expression evaluated at runtime.
            ExecutablePopulationMap executable;
            if (unsupported.empty()) {
                executable.index = popMap.index;
                executable.name = popMap.populationName;
                executable.pattern = pattern->pattern;
                executable.product_type = productType;
                executable.total_rate = popMap.totalRate;
                if (const auto compartment = popMap.pattern.compartmentId()) {
                    executable.product_compartment =
                        static_cast<CompartmentId>(compartment->value());
                } else {
                    std::optional<CompartmentId> molComp;
                    for (const auto& mol : popMap.pattern.molecules()) {
                        if (!mol.compartmentId.has_value()) continue;
                        const auto cid = static_cast<CompartmentId>(mol.compartmentId->value());
                        if (molComp && *molComp != cid) {
                            unsupported = "population map reactant spans multiple compartments";
                            break;
                        }
                        molComp = cid;
                    }
                    if (unsupported.empty() && molComp) {
                        executable.product_compartment = molComp;
                    }
                }
                if (rateValue) {
                    if (!std::isfinite(*rateValue) || *rateValue < 0.0) {
                        unsupported = "population map rate is not finite and non-negative";
                    } else {
                        executable.rate_is_static = true;
                        executable.static_rate = *rateValue;
                        std::ostringstream rateText;
                        rateText.precision(17);
                        rateText << *rateValue;
                        executable.rate_expression = rateText.str();
                    }
                } else {
                    std::set<std::size_t> observableIds;
                    const auto expression = observableRateExpression(
                        *expandedRate, source, observableIds);
                    if (!expression) {
                        unsupported = "population map rate cannot be evaluated from observables and static parameters";
                    } else {
                        executable.rate_is_static = false;
                        executable.rate_expression = *expression;
                    }
                }
            }
            if (!unsupported.empty()) {
                issue(result, BngLoweringSeverity::Warning, popMap.populationName,
                      "population map is not executable in NFnext (" + unsupported + ")");
            } else {
                executableMaps.push_back(std::move(executable));
            }
            result.model.population_maps.push_back(std::move(irPopMap));
        }
    }
    if (!result.ok()) return result;

    result.model.molecule_types.reserve(source.moleculeTypes().size());
    for (const auto& molecule : source.moleculeTypes()) {
        MoleculeTypeIR type;
        type.id = static_cast<TypeId>(molecule.id.value());
        type.name = molecule.name;
        type.is_population = molecule.population;
        type.sites.reserve(molecule.components.size());
        for (const auto& component : molecule.components)
            type.sites.push_back(SiteSpec{component.name, component.stateNames});
        result.model.molecule_types.push_back(std::move(type));
    }

    RuleId nextRule = 0;
    for (const auto& rule : source.rules()) {
        addDirection(rule, rule.forward(), nextRule++, "", false, source, result);
        if (rule.reverse()) addDirection(rule, *rule.reverse(), nextRule++, "__reverse", true, source, result);
    }

    // Synthesize one executable rule per accepted population map. It behaves
    // like an elementary rule whose reactant is the map pattern and whose only
    // product is the lumped population type: the SSA loop's population-aware
    // action path consumes the matched particles and increments the population
    // count. The map index annotation lets execution fail closed on any map
    // that was not accepted.
    for (const auto& accepted : executableMaps) {
        ExpandedRuleIR mapRule;
        mapRule.id = nextRule++;
        mapRule.name = "population_map_" + std::to_string(accepted.index) + ":" + accepted.name;
        mapRule.pattern = accepted.pattern;
        mapRule.total_rate = accepted.total_rate;
        addPredicates(mapRule.pattern, mapRule.predicates);
        mapRule.rate = accepted.rate_is_static ? accepted.static_rate : 0.0;
        mapRule.rate_law.kind = accepted.rate_is_static
            ? RateLawKind::Elementary : RateLawKind::Function;
        mapRule.rate_law.expression = accepted.rate_expression;

        // Destroy each matched particle reactant and create one lumped product.
        // Created nodes live in a second namespace starting after the matched
        // reactant nodes, matching ExpandedRuleIR action conventions.
        for (std::size_t node = 0; node < mapRule.pattern.nodes.size(); ++node) {
            ActionIR destroy;
            destroy.kind = ActionKind::Destroy;
            destroy.target_node = static_cast<PatternNodeId>(node);
            destroy.molecule_type = mapRule.pattern.nodes[node].molecule_type;
            mapRule.actions.push_back(destroy);
        }
        ActionIR create;
        create.kind = ActionKind::Create;
        create.molecule_type = accepted.product_type;
        create.target_node = static_cast<PatternNodeId>(mapRule.pattern.nodes.size());
        mapRule.actions.push_back(create);
        if (accepted.product_compartment) {
            ActionIR setCompartment;
            setCompartment.kind = ActionKind::SetCompartment;
            setCompartment.target_node = create.target_node;
            setCompartment.molecule_type = create.molecule_type;
            setCompartment.value = static_cast<std::int32_t>(*accepted.product_compartment);
            mapRule.actions.push_back(setCompartment);
        }

        mapRule.reactant_pattern_offsets = {0};
        mapRule.symmetry_divisor = computeWithinPatternSymmetry(
            mapRule.pattern, mapRule.actions, mapRule.reactant_pattern_offsets, {}, source);
        mapRule.annotations["bng.population_map_index"] = std::to_string(accepted.index);
        result.model.expanded_rules.push_back(std::move(mapRule));
    }

    if (!result.ok()) {
        // Never expose a partially lowered executable rule set as valid NFIR.
        result.model.expanded_rules.clear();
        result.model.rule_families.clear();
        result.model.dependencies.feature_to_families.clear();
        return result;
    }

    ModelCompiler compiler;
    compiler.compile(result.model);
    return result;
}

using PopulationLocation = std::pair<TypeId, std::optional<CompartmentId>>;
using PopulationCounts = std::map<PopulationLocation, std::uint64_t>;

struct BngExecutionState {
    std::shared_ptr<const ModelIR> model;
    GenericGraphState graph;
    PopulationCounts populations;
    std::unordered_set<TypeId> compartmentalized_populations;
    double time;
    std::uint64_t seed;
    std::uint64_t stream;
};

BngExecutionResult executeFromBioNetGen(const bng::compile::CompiledModel& source,
                                      const BngExecutionRequest& request) {
    const auto refuse = [](const std::string& reason) {
        throw std::runtime_error("NFnext execution unsupported: " + reason);
    };
    if (request.sample_times.empty()) refuse("sample_times must not be empty");
    if (!std::isfinite(request.start_time) || request.start_time < 0.0)
        refuse("start_time must be finite and nonnegative");
    const auto& continuation = request.continuation;
    if (continuation && continuation->time != request.start_time)
        refuse("continuation start time must equal the previous end time");
    double previous = -1.0;
    for (double time : request.sample_times) {
        if (!std::isfinite(time) || time < 0.0 || time <= previous)
            refuse("sample_times must be finite, nonnegative and strictly increasing");
        if (time < request.start_time) refuse("sample_times must be at or after start_time");
        previous = time;
    }
    for (const auto& comp : source.compartments()) {
        if (!std::isfinite(comp.volume) || comp.volume <= 0.0) {
            refuse("compartments require positive finite volume");
        }
        if (comp.dimension < 1 || comp.dimension > 3) {
            refuse("compartment dimensions must be 1, 2, or 3");
        }
    }
    // Population-map support is decided after lowering, once the synthesized
    // executable map rules (if any) are known; see the check below.
    for (const auto& rule : source.rules()) {
        const auto checkRate = [&](const bng::compile::CompiledRuleDirection& direction) {
            if (!direction.rateLaw) refuse("missing rate law");
            using Kind = bng::compile::RateLawKind;
            switch (direction.rateLaw->kind) {
            case Kind::Expression:
            case Kind::ArrheniusEnergy:
                break;
            default:
                refuse("unsupported NFnext rate law kind");
            }
        };
        checkRate(rule.forward());
        if (rule.reverse()) checkRate(*rule.reverse());
    }
    // Network-free execution has no pending-completion queue. Refuse delayed
    // semantics explicitly rather than executing a delayed rule as immediate.
    for (const auto& rule : source.rules()) {
        if (rule.delayExpression() || rule.resolvedDelayExpression()) {
            refuse("delayed rules require the native DDE method-of-steps solver");
        }
        const auto checkRateDelay = [&](const bng::compile::CompiledRuleDirection& direction) {
            if (direction.rateLaw &&
                resolvedExpressionUsesDelay(direction.rateLaw->resolvedExpression())) {
                refuse("delay() rate expressions require the native DDE method-of-steps solver");
            }
        };
        checkRateDelay(rule.forward());
        if (rule.reverse()) checkRateDelay(*rule.reverse());
    }
    for (const auto& function : source.functions()) {
        if (resolvedExpressionUsesDelay(function.expression)) {
            refuse("delay() function expressions require the native DDE method-of-steps solver");
        }
    }
    auto lowered = lowerFromBioNetGen(source);
    if (!lowered.ok()) {
        for (const auto& issue : lowered.issues)
            if (issue.severity == BngLoweringSeverity::Error) refuse(issue.message);
    }
    // The graph stores a pointer to the model describing its layout.
    // Keep that model alive for the returned state.
    auto modelOwner = request.retain_state
        ? std::make_shared<ModelIR>(std::move(lowered.model))
        : nullptr;
    const auto& model = modelOwner ? *modelOwner : lowered.model;
    // Physical rate units are converted during lowering for supported
    // constant elementary forms; execution refuses only if conversion failed.

    // A population map executes only when lowering synthesized an explicit
    // rule for it. Any map outside the supported simple shape (bonds to
    // population nodes, unresolved or time-dependent rates, undeclared
    // product types, ...) remains a
    // fail-closed refusal rather than an approximation.
    if (!source.populationMaps().empty()) {
        std::unordered_set<std::string> executableMapIndices;
        for (const auto& rule : model.expanded_rules) {
            const auto found = rule.annotations.find("bng.population_map_index");
            if (found != rule.annotations.end()) executableMapIndices.insert(found->second);
        }
        for (const auto& popMap : source.populationMaps()) {
            if (!executableMapIndices.count(std::to_string(popMap.index))) {
                refuse("un-lowered population maps: map '" + popMap.populationName +
                       "' has an unsupported shape or rate for NFnext execution");
            }
        }
    }
    bool has_energy_modulated_rate = false;
    for (const auto& rule : source.rules()) {
        auto check = [&](const bng::compile::CompiledRuleDirection& d) {
            if (d.rateLaw && d.rateLaw->kind == bng::compile::RateLawKind::ArrheniusEnergy &&
                (!source.energyFactors().empty() || !source.barrierFactors().empty()))
                has_energy_modulated_rate = true;
        };
        check(rule.forward());
        if (rule.reverse()) check(*rule.reverse());
    }
    if (has_energy_modulated_rate) {
        bool all_expanded = !model.expanded_rules.empty();
        for (const auto& er : model.expanded_rules) {
            // Dynamic energy factors lower to Function rate laws that the
            // observable-dependent rate executor evaluates at runtime.
            if (er.rate_law.kind != RateLawKind::Elementary &&
                er.rate_law.kind != RateLawKind::Function) { all_expanded = false; break; }
        }
        for (const auto& rule : source.rules()) {
            auto check = [&](const bng::compile::CompiledRuleDirection& d) {
                if (!d.rateLaw) { all_expanded = false; return; }
                if (d.rateLaw->kind == bng::compile::RateLawKind::ArrheniusEnergy) {
                    const bool validStateChange =
                        d.mutations.size() == 1 && d.reactantPatterns.size() == 1 &&
                        d.mutations.front().kind == BngMutationKind::ChangeState;
                    const bool validBinding =
                        d.mutations.size() == 1 && d.reactantPatterns.size() == 2 &&
                        d.reactantPatterns[0].molecules().size() == 1 &&
                        d.reactantPatterns[1].molecules().size() == 1 &&
                        d.mutations.front().kind == BngMutationKind::AddBond;
                    const bool validUnbinding =
                        d.mutations.size() == 1 && d.reactantPatterns.size() == 1 &&
                        d.reactantPatterns[0].molecules().size() == 2 &&
                        d.mutations.front().kind == BngMutationKind::DeleteBond;
                    if ((!validStateChange && !validBinding && !validUnbinding) ||
                        d.rateLaw->resolvedExpression().arguments.size() != 2)
                        all_expanded = false;
                }
            };
            check(rule.forward());
            if (rule.reverse()) check(*rule.reverse());
        }
        if (!all_expanded)
            refuse("energy-modulated Arrhenius rule form is not yet supported in NFnext lowering");
    }
    if (!source.barrierFactors().empty() && !has_energy_modulated_rate)
        refuse("barrier rate modulation not yet implemented in NFnext execution");
    if (request.max_particles > std::numeric_limits<std::uint32_t>::max())
        refuse("particle budget exceeds native index capacity");
    GenericGraphState state = continuation
        ? GenericGraphState(model, continuation->graph)
        : GenericGraphState(model);
    PopulationCounts population_counts = continuation
        ? continuation->populations : PopulationCounts{};
    auto compartmentalized_populations = continuation
        ? continuation->compartmentalized_populations : std::unordered_set<TypeId>{};
    if (state.liveCount() > request.max_particles)
        refuse("particle budget exceeded by the previous stage");
    const auto location = [](const PatternIR::Node& node) -> PopulationLocation {
        return {node.molecule_type, node.compartment};
    };
    const auto incrementPopulation = [&](const PopulationLocation& key, std::uint64_t amount) {
        auto& count = population_counts[key];
        if (amount > std::numeric_limits<std::uint64_t>::max() - count)
            refuse("population count exceeds native capacity");
        count += amount;
    };
    const auto populationCount = [&](const PopulationLocation& key) -> std::uint64_t {
        const auto found = population_counts.find(key);
        return found == population_counts.end() ? 0 : found->second;
    };
    const auto observedPopulation = [&](const PatternIR::Node& node) -> std::uint64_t {
        if (node.compartment) return populationCount(location(node));
        std::uint64_t total = 0;
        for (auto it = population_counts.lower_bound({node.molecule_type, std::nullopt});
             it != population_counts.end() && it->first.first == node.molecule_type; ++it) {
            if (it->second > std::numeric_limits<std::uint64_t>::max() - total)
                refuse("population observable exceeds native count capacity");
            total += it->second;
        }
        return total;
    };
    // Dynamic threshold transitions. When a population map declares a simple
    // particle<->population pair, keep at most ``population_threshold``
    // particles in the graph; the remainder is held in the lumped population.
    // Moving a copy between representations changes no reaction rate and
    // conserves total copies exactly. Shapes with sites, bonds, compartments or
    // filters are refused rather than approximated: silently dropping a bound
    // particle would lose complex state.
    const auto reconcilePopulationThresholds = [&]() {
        const std::uint64_t threshold = request.population_threshold;
        if (threshold == 0) return;
        for (const auto& map : model.population_maps) {
            const auto& pattern = map.pattern;
            bool simple = pattern.nodes.size() == 1 && pattern.bonds.empty() &&
                          pattern.molecularity.empty() && pattern.aliases.empty() &&
                          pattern.connected_to.empty() && pattern.interchangeable.empty();
            if (simple) {
                const auto& node = pattern.nodes.front();
                if (node.compartment || !node.constraints.empty()) simple = false;
                if (node.molecule_type >= model.molecule_types.size()) simple = false;
                if (simple && !model.molecule_types.at(node.molecule_type).sites.empty())
                    simple = false;
            }
            TypeId population_type = 0;
            bool found = false;
            for (const auto& type : model.molecule_types) {
                if (type.is_population && type.name == map.population_name) {
                    population_type = type.id;
                    found = true;
                    if (!type.sites.empty()) simple = false;
                    break;
                }
            }
            if (!simple || !found)
                refuse("population threshold requires a site-free, unbound particle map");
            const TypeId particle_type = pattern.nodes.front().molecule_type;
            std::vector<ParticleId> particles;
            for (const ParticleId id : state.liveParticles())
                if (state.type(id) == particle_type) particles.push_back(id);
            const PopulationLocation key{population_type, std::nullopt};
            if (particles.size() > threshold) {
                const std::uint64_t excess =
                    static_cast<std::uint64_t>(particles.size() - threshold);
                for (std::uint64_t i = 0; i < excess; ++i) state.destroy(particles[i]);
                incrementPopulation(key, excess);
            } else if (particles.size() < threshold) {
                const std::uint64_t available = populationCount(key);
                const std::uint64_t missing =
                    static_cast<std::uint64_t>(threshold - particles.size());
                const std::uint64_t moved = std::min(available, missing);
                if (moved > 0) {
                    population_counts.at(key) -= moved;
                    for (std::uint64_t i = 0; i < moved; ++i) state.create(particle_type, 0);
                }
            }
        }
    };
    reconcilePopulationThresholds();
    bng::units::ConversionContext seedUnitContext;
    if (const auto option = source.metadata().options.find("NumberPerQuantityUnit");
        option != source.metadata().options.end()) {
        try {
            std::size_t consumed = 0;
            const double value = std::stod(option->second, &consumed);
            if (consumed == option->second.size() && std::isfinite(value) && value > 0.0)
                seedUnitContext.numberPerQuantityUnit = value;
        } catch (...) {
        }
    }
    const double numberPerQuantityUnit = seedUnitContext.numberPerQuantityUnit.value_or(1.0);

    struct ConstantSeedSpec {
        bool is_population{false};
        PopulationLocation pop_location{};
        PatternIR pattern;
        CompartmentId default_compartment{0};
        std::size_t target_count{0};
    };
    std::vector<ConstantSeedSpec> constantSeeds;

    for (const auto& seed : source.seeds()) {
        if (continuation && !seed.constant) continue;
        auto amount = constantExpression(seed.amount, source);
        if (!amount || !std::isfinite(*amount) || *amount < 0.0)
            refuse("seeds require bounded static integer particle counts");
        if (seed.declaredUnit.has_value()) {
            const auto& unit = *seed.declaredUnit;
            bng::units::ConversionResult converted;
            if (unit.dimension.length == -3 && unit.dimension.time == 0) {
                std::optional<bng::compile::CompartmentId> compId = seed.compartmentId;
                if (!compId.has_value()) compId = seed.pattern.compartmentId();
                if (!compId.has_value()) {
                    for (const auto& mol : seed.pattern.molecules()) {
                        if (!mol.compartmentId.has_value()) continue;
                        if (compId.has_value() && *compId != *mol.compartmentId)
                            refuse("concentration seed species spans multiple compartments");
                        compId = mol.compartmentId;
                    }
                }
                const auto* comp = compId.has_value() ? source.compartment(*compId) : nullptr;
                if (!comp || comp->dimension != 3 || comp->volumeTimeDependent ||
                    !std::isfinite(comp->volume) || comp->volume <= 0.0 ||
                    !comp->declaredUnit.has_value() ||
                    comp->declaredUnit->dimension.length != 3 ||
                    comp->declaredUnit->dimension.substance != 0 ||
                    comp->declaredUnit->dimension.time != 0) {
                    refuse("concentration seed requires a positive static declared 3D compartment");
                }
                converted = bng::units::concentrationToItemAmount(
                    *amount, unit, comp->volume, *comp->declaredUnit, seedUnitContext);
            } else if (unit.dimension.length == 0 && unit.dimension.time == 0 &&
                       unit.dimension.substance == 1) {
                bng::units::Unit item;
                item.name = "item";
                item.dimension.substance = 1;
                item.baseExponents[bng::units::BaseUnit::Item] = 1;
                converted = bng::units::convertValue(*amount, unit, item, seedUnitContext);
            } else {
                refuse("unit-bearing seed species must have amount or concentration units");
            }
            if (!converted || !converted.factor.has_value() ||
                !std::isfinite(*converted.factor) || *converted.factor < 0.0) {
                refuse("unit-bearing seed conversion failed: " + converted.error);
            }
            amount = std::floor(*converted.factor + 0.5);
        } else if (std::floor(*amount) != *amount) {
            refuse("seeds require bounded static integer particle counts");
        }
        for (const auto& molecule : seed.pattern.molecules()) {
            for (const auto& site : molecule.sites) {
                const auto allowedBond = [](bng::compile::BondConstraintKind kind) {
                    return kind == bng::compile::BondConstraintKind::Unspecified ||
                           kind == bng::compile::BondConstraintKind::Unbound ||
                           kind == bng::compile::BondConstraintKind::Exact;
                };
                if (!allowedBond(site.bondKind)) refuse("seed bond wildcards");
                for (const auto& bond : site.bondConstraints)
                    if (!allowedBond(bond.kind)) refuse("seed bond wildcards");
            }
        }
        BngLoweringResult validation;
        const auto pattern = flattenReactants({seed.pattern}, validation, "seed", false, &source);
        if (!pattern || !validation.ok()) refuse("seeds require valid patterns");

        const auto& pat = pattern->pattern;
        const bool is_pure_population_seed =
            pat.nodes.size() == 1 && pat.bonds.empty() &&
            model.molecule_types.at(pat.nodes.front().molecule_type).is_population &&
            pat.nodes.front().constraints.empty();
        if (is_pure_population_seed) {
            if (*amount >= std::ldexp(1.0, std::numeric_limits<std::uint64_t>::digits))
                refuse("population seed count exceeds native capacity");
            const auto key = location(pat.nodes.front());
            if (!continuation) {
                if (key.second) compartmentalized_populations.insert(key.first);
                incrementPopulation(key, static_cast<std::uint64_t>(*amount));
            }
            if (seed.constant) {
                ConstantSeedSpec spec;
                spec.is_population = true;
                spec.pop_location = key;
                spec.target_count = continuation
                    ? static_cast<std::size_t>(populationCount(key))
                    : static_cast<std::size_t>(*amount);
                constantSeeds.push_back(std::move(spec));
            }
            continue;
        }

        for (std::size_t nodeIdx = 0; nodeIdx < pat.nodes.size(); ++nodeIdx) {
            const auto& node = pat.nodes[nodeIdx];
            const auto& type = model.molecule_types.at(node.molecule_type);
            std::vector<std::optional<std::int32_t>> states(type.sites.size());
            for (const auto& constraint : node.constraints) {
                if (constraint.kind == PatternIR::SiteConstraintKind::State)
                    states.at(constraint.site) = constraint.state;
                else if (constraint.kind != PatternIR::SiteConstraintKind::Free)
                    refuse("seeds require exact states and free sites");
            }
            for (std::size_t site = 0; site < type.sites.size(); ++site)
                if (!type.sites[site].states.empty() && !states[site])
                    refuse("seeds must explicitly initialize every stateful site");
        }

        const CompartmentId seedDefaultComp = seed.compartmentId
            ? static_cast<CompartmentId>(seed.compartmentId->value())
            : (seed.pattern.compartmentId()
                   ? static_cast<CompartmentId>(seed.pattern.compartmentId()->value())
                   : 0);

        std::size_t copy_count = 0;
        if (!continuation) {
            const std::size_t available_particles =
                request.max_particles - state.liveCount();
            if (*amount > static_cast<double>(available_particles))
                refuse("particle budget exceeded by seeds");
            copy_count = static_cast<std::size_t>(*amount);
            if (pat.nodes.empty() ||
                copy_count > available_particles / pat.nodes.size())
                refuse("particle budget exceeded by seeds");

            for (std::size_t count = 0; count < copy_count; ++count) {
                std::vector<ParticleId> particles;
                particles.reserve(pat.nodes.size());
                for (std::size_t nodeIdx = 0; nodeIdx < pat.nodes.size(); ++nodeIdx) {
                    const auto& node = pat.nodes[nodeIdx];
                    const CompartmentId comp = node.compartment.value_or(seedDefaultComp);
                    const auto particle = state.create(node.molecule_type, comp);
                    particles.push_back(particle);
                    for (const auto& constraint : node.constraints) {
                        if (constraint.kind == PatternIR::SiteConstraintKind::State) {
                            state.setSiteState(particle, static_cast<std::uint16_t>(constraint.site), constraint.state);
                        }
                    }
                }
                for (const auto& bond : pat.bonds) {
                    state.bind(particles.at(bond.first), static_cast<std::uint16_t>(bond.first_site),
                               particles.at(bond.second), static_cast<std::uint16_t>(bond.second_site));
                }
            }
        }

        // NFN-05: Track constant ($) particle seed species so their copy number is
        // preserved after every reaction event.
        if (seed.constant) {
            BngLoweringResult constVal;
            const auto constFlat = flattenReactants({seed.pattern}, constVal, "seed", true, &source);
            if (!constFlat || !constVal.ok()) refuse("constant seed pattern invalid");
            PatternIR exactPat = constFlat->pattern;
            exactPat.species_compartments.clear();
            for (std::size_t nodeIdx = 0; nodeIdx < exactPat.nodes.size(); ++nodeIdx) {
                auto& node = exactPat.nodes[nodeIdx];
                if (!model.compartments.empty()) {
                    node.compartment = node.compartment.value_or(seedDefaultComp);
                }
                const auto& type = model.molecule_types.at(node.molecule_type);
                for (std::size_t s = 0; s < type.sites.size(); ++s) {
                    bool isBoundInPat = false;
                    for (const auto& b : exactPat.bonds) {
                        if ((b.first == nodeIdx && b.first_site == s) ||
                            (b.second == nodeIdx && b.second_site == s)) {
                            isBoundInPat = true;
                            break;
                        }
                    }
                    if (isBoundInPat) continue;
                    bool hasFree = false;
                    for (const auto& c : node.constraints) {
                        if (c.site == s && c.kind == PatternIR::SiteConstraintKind::Free) {
                            hasFree = true;
                            break;
                        }
                    }
                    if (!hasFree) node.siteFree(static_cast<std::uint32_t>(s));
                }
            }
            ConstantSeedSpec spec;
            spec.is_population = false;
            spec.pattern = std::move(exactPat);
            spec.default_compartment = seedDefaultComp;
            spec.target_count = copy_count;
            constantSeeds.push_back(std::move(spec));
        }
    }
    struct ObservableTermDef {
        PatternIR pattern;
        std::string relation;
        int quantity = 0;
    };
    struct ObservableDef {
        std::string name;
        bng::compile::ObservableKind kind;
        std::vector<ObservableTermDef> terms;
    };
    std::vector<ObservableDef> observables;
    BngExecutionResult output;
    output.columns.push_back("time");
    for (const auto& observable : source.observables()) {
        if (observable.kind != bng::compile::ObservableKind::Molecules &&
            observable.kind != bng::compile::ObservableKind::Species)
            refuse("only Molecules and Species observables");
        if (observable.terms.empty()) refuse("empty observable terms");
        std::vector<ObservableTermDef> terms;
        for (const auto& term : observable.terms) {
            BngLoweringResult validation;
            const auto pattern = flattenReactants({term.pattern}, validation,
                                                  observable.name, true, &source);
            if (!pattern || !validation.ok())
                refuse("invalid observable pattern");
            terms.push_back({pattern->pattern, term.relation, term.quantity});
        }
        if (std::find(output.columns.begin(), output.columns.end(), observable.name) !=
            output.columns.end()) refuse("duplicate output column names");
        output.columns.push_back(observable.name);
        observables.push_back({observable.name, observable.kind, std::move(terms)});
    }

    std::unordered_map<ObservableId, std::size_t> observableIdToDefIndex;
    FunctionEnvironment functionEnvironment;
    for (std::size_t i = 0; i < source.observables().size(); ++i) {
        const auto obsId = static_cast<ObservableId>(source.observables()[i].id.value());
        observableIdToDefIndex[obsId] = i;
        functionEnvironment.addObservable("observable_" + std::to_string(obsId), 0.0, obsId);
    }
    // NFN-03: Register local observable slot parameters for rules with local functions.
    std::uint32_t maxLocalObsSlot = 0;
    bool hasAnyLocalObs = false;
    for (const auto& rule : model.expanded_rules) {
        for (const auto& binding : rule.local_observable_bindings) {
            hasAnyLocalObs = true;
            if (binding.slot > maxLocalObsSlot) maxLocalObsSlot = binding.slot;
        }
    }
    if (hasAnyLocalObs) {
        for (std::uint32_t slot = 0; slot <= maxLocalObsSlot; ++slot) {
            functionEnvironment.addParameter(
                "local_obs_" + std::to_string(slot), 0.0, static_cast<ParameterId>(slot));
        }
    }

    struct PreparedRuleRate {
        bool isDynamic{false};
        double elementaryRate{0.0};
        std::optional<CompiledFunction> compiledFunction;
    };
    std::vector<PreparedRuleRate> preparedRates;
    preparedRates.reserve(model.expanded_rules.size());
    for (const auto& rule : model.expanded_rules) {
        if (rule.rate_law.kind == RateLawKind::Function) {
            try {
                preparedRates.push_back({
                    true,
                    0.0,
                    FunctionCompiler().compile(rule.rate_law.expression, functionEnvironment)
                });
            } catch (const std::exception& e) {
                refuse("invalid dynamic rate function: " + std::string(e.what()));
            }
        } else {
            preparedRates.push_back({false, rule.rate, std::nullopt});
        }
    }

    std::vector<CompiledTransformation> compiled_transformations;
    compiled_transformations.reserve(model.expanded_rules.size());
    std::vector<std::map<PatternNodeId, CreatedMoleculeId>> ruleCreatedIds(model.expanded_rules.size());
    for (std::size_t ri = 0; ri < model.expanded_rules.size(); ++ri) {
        const auto& rule = model.expanded_rules[ri];
        compiled_transformations.push_back(
            compileTransformation(buildRuleTransformation(rule), model));
        CreatedMoleculeId nextCid = 0;
        for (const auto& action : rule.actions) {
            if (action.kind == ActionKind::Create &&
                !ruleCreatedIds[ri].count(action.target_node)) {
                ruleCreatedIds[ri][action.target_node] = nextCid++;
            }
        }
    }

    GenericMatcher matcher(model);

    // Prepare exact runtime energy patterns when any rule uses runtime Arrhenius evaluation.
    struct PreparedEnergyPattern {
        PatternIR pattern;
        double aut{1.0};
        bool isDynamic{false};
        double staticEnergy{0.0};
        std::optional<CompiledFunction> compiledFunction;
    };
    std::vector<PreparedEnergyPattern> preparedEnergyPatterns;
    const bool anyRuntimeArrhenius = std::any_of(
        model.expanded_rules.begin(), model.expanded_rules.end(),
        [](const ExpandedRuleIR& r) { return r.runtime_arrhenius.enabled; });
    if (anyRuntimeArrhenius) {
        preparedEnergyPatterns.reserve(source.energyFactors().size());
        for (const auto& ep : source.energyFactors()) {
            BngLoweringResult epVal;
            const auto epFlat = flattenReactants({ep.pattern}, epVal, ep.label, true, &source);
            if (!epFlat || !epVal.ok()) refuse("runtime energy pattern could not be lowered");
            PreparedEnergyPattern pep;
            pep.pattern = epFlat->pattern;
            pep.aut = static_cast<double>(std::max<std::size_t>(1, matcher.fullAutomorphismCount(pep.pattern)));
            if (isDynamicEnergyFactor(ep, source)) {
                std::set<std::size_t> activeFunctions;
                const auto expandedEp = expandZeroArgumentRateFunctions(
                    source.expandFunctions(ep.expression), source, activeFunctions);
                if (!expandedEp) refuse("dynamic energy expression could not be resolved");
                std::set<std::size_t> obsIds;
                const auto expr = observableRateExpression(*expandedEp, source, obsIds);
                if (!expr) refuse("dynamic energy expression could not be resolved");
                try {
                    pep.isDynamic = true;
                    pep.compiledFunction = FunctionCompiler().compile(*expr, functionEnvironment);
                } catch (const std::exception& e) {
                    refuse("invalid dynamic energy expression: " + std::string(e.what()));
                }
            } else {
                pep.staticEnergy = energyFactorValue(ep, source);
            }
            preparedEnergyPatterns.push_back(std::move(pep));
        }
    }

    const auto coversWholeComplex = [&](const Embedding& match) {
        const auto& particles = match.particles();
        // The matcher already requires one connected complex. A bond to
        // any particle outside the embedding makes the match incomplete.
        for (const auto particle : particles) {
            const auto siteCount = model.molecule_types.at(state.type(particle)).sites.size();
            for (std::size_t site = 0; site < siteCount; ++site) {
                const auto partner = state.bond(particle, static_cast<std::uint16_t>(site)).particle;
                if (state.alive(partner) &&
                    std::find(particles.begin(), particles.end(), partner) == particles.end()) {
                    return false;
                }
            }
        }
        return !particles.empty();
    };

    // On continuation, initialize particle constant seed targets from current state.
    if (continuation && !constantSeeds.empty()) {
        for (auto& spec : constantSeeds) {
            if (spec.is_population) continue;
            std::unordered_set<std::uint32_t> seenComplexes;
            for (const auto& m : matcher.enumerate(spec.pattern, state)) {
                if (!m.particles().empty() && coversWholeComplex(m)) {
                    seenComplexes.insert(state.complexId(m.particle(0)));
                }
            }
            spec.target_count = seenComplexes.size();
        }
    }

    // NFN-08 / PERF-02: GenericMatcher::enumerate() already returns every ordered
    // (node, duplicate-site) embedding, which equals count * aut(pattern) with no
    // extra automorphism multiplication (eliminating aut^2 and k!*k! double-counting).
    auto evaluateObservable = [&](const ObservableDef& obs) -> double {
        double value = 0.0;
        if (obs.kind == bng::compile::ObservableKind::Molecules) {
            for (const auto& term : obs.terms) {
                if (term.pattern.nodes.size() == 1 && term.pattern.bonds.empty() &&
                    term.pattern.nodes.front().constraints.empty() &&
                    term.pattern.molecularity.empty() && term.pattern.aliases.empty() &&
                    term.pattern.connected_to.empty() && term.pattern.species_compartments.empty() &&
                    model.molecule_types.at(term.pattern.nodes.front().molecule_type).is_population) {
                    const auto count = observedPopulation(term.pattern.nodes.front());
                    if (term.relation.empty()) value += static_cast<double>(count);
                    else if (bng::compile::observablePatternCountMatches(
                                 static_cast<std::size_t>(count), term.relation, term.quantity))
                        value += 1.0;
                    continue;
                }
                const auto count = matcher.enumerate(term.pattern, state).size();
                if (term.relation.empty()) value += static_cast<double>(count);
                else if (bng::compile::observablePatternCountMatches(count, term.relation, term.quantity))
                    value += 1.0;
            }
        } else if (obs.kind == bng::compile::ObservableKind::Species) {
            std::unordered_map<std::uint32_t, std::size_t> complex_counts;
            for (const auto& term : obs.terms) {
                if (term.pattern.nodes.size() == 1 && term.pattern.bonds.empty() &&
                    term.pattern.nodes.front().constraints.empty() &&
                    term.pattern.molecularity.empty() && term.pattern.aliases.empty() &&
                    term.pattern.connected_to.empty() && term.pattern.species_compartments.empty() &&
                    model.molecule_types.at(term.pattern.nodes.front().molecule_type).is_population) {
                    const auto count = observedPopulation(term.pattern.nodes.front());
                    if (bng::compile::observablePatternCountMatches(1, term.relation, term.quantity))
                        value += static_cast<double>(count);
                    continue;
                }
                complex_counts.clear();
                for (const auto& match : matcher.enumerate(term.pattern, state)) {
                    if (!match.particles().empty())
                        ++complex_counts[state.complexId(match.particle(0))];
                }
                for (const auto& [_, c] : complex_counts) {
                    if (bng::compile::observablePatternCountMatches(c, term.relation, term.quantity))
                        value += 1.0;
                }
            }
        }
        return value;
    };

    // NFN-03: Evaluate an observable locally over the connected complex of a matched particle
    // (or restricted to embeddings containing that particle when molecule-scoped).
    auto evaluateObservableLocally = [&](const ObservableDef& obs,
                                         const std::vector<ParticleId>& complexParts,
                                         ParticleId anchor,
                                         bool moleculeScope) -> double {
        double value = 0.0;
        for (const auto& term : obs.terms) {
            const auto localMatches = matcher.enumerateInParticles(term.pattern, state, complexParts);
            std::size_t count = 0;
            if (moleculeScope) {
                for (const auto& lm : localMatches) {
                    if (std::find(lm.particles().begin(), lm.particles().end(), anchor) != lm.particles().end()) {
                        ++count;
                    }
                }
            } else {
                count = localMatches.size();
            }
            if (obs.kind == bng::compile::ObservableKind::Molecules) {
                if (term.relation.empty()) value += static_cast<double>(count);
                else if (bng::compile::observablePatternCountMatches(count, term.relation, term.quantity))
                    value += 1.0;
            } else if (obs.kind == bng::compile::ObservableKind::Species) {
                if (count > 0 && bng::compile::observablePatternCountMatches(count, term.relation, term.quantity))
                    value += 1.0;
            }
        }
        return value;
    };

    const auto seed = continuation && request.seed == 0 ? continuation->seed : request.seed;
    // Resample the waiting time after a stage boundary. Use a new stream
    // even if the previous waiting time was censored before any event fired.
    const auto stream = continuation ? continuation->stream + 1 : 0;
    CounterRng rng(seed, stream);
    auto isSimpleLumpedPopulationReactant = [&](const PatternIR& pattern, std::size_t nodeIndex) {
        const auto& node = pattern.nodes.at(nodeIndex);
        if (!model.molecule_types.at(node.molecule_type).is_population) return false;
        if (!node.constraints.empty()) return false;
        for (const auto& bond : pattern.bonds)
            if (bond.first == nodeIndex || bond.second == nodeIndex) return false;
        for (const auto& pair : pattern.aliases)
            if (pair.first == nodeIndex || pair.second == nodeIndex) return false;
        for (const auto& pair : pattern.connected_to)
            if (pair.first == nodeIndex || pair.second == nodeIndex) return false;
        for (const auto& group : pattern.interchangeable)
            if (std::find(group.begin(), group.end(), nodeIndex) != group.end()) return false;
        // Molecularity constraints are allowed for lumped population reactants (e.g. DifferentComplex to particle reactants).
        return true;
    };

    struct MixedLumpedInfo {
        bool enabled{false};
        std::vector<std::size_t> particleReactantNodes; // original reactant node indices
        PopulationCounts popReactantCounts;
        PatternIR particlePattern;
    };
    std::vector<MixedLumpedInfo> mixedLumped(model.expanded_rules.size());
    for (std::size_t ri = 0; ri < model.expanded_rules.size(); ++ri) {
        const auto& rule = model.expanded_rules[ri];
        bool hasPop = false, hasParticle = false, allPopSimple = true;
        for (std::size_t ni = 0; ni < rule.pattern.nodes.size(); ++ni) {
            if (model.molecule_types.at(rule.pattern.nodes[ni].molecule_type).is_population) {
                hasPop = true;
                if (!isSimpleLumpedPopulationReactant(rule.pattern, ni)) allPopSimple = false;
            } else {
                hasParticle = true;
            }
        }
        if (!hasPop || !hasParticle || !allPopSimple) continue;
        MixedLumpedInfo info;
        info.enabled = true;
        std::map<std::size_t, std::size_t> oldToNew;
        for (std::size_t ni = 0; ni < rule.pattern.nodes.size(); ++ni) {
            if (model.molecule_types.at(rule.pattern.nodes[ni].molecule_type).is_population) {
                info.popReactantCounts[location(rule.pattern.nodes[ni])] += 1;
            } else {
                oldToNew[ni] = info.particleReactantNodes.size();
                info.particleReactantNodes.push_back(ni);
                info.particlePattern.nodes.push_back(rule.pattern.nodes[ni]);
            }
        }
        for (const auto& bond : rule.pattern.bonds) {
            const bool fPop = model.molecule_types.at(rule.pattern.nodes[bond.first].molecule_type).is_population;
            const bool sPop = model.molecule_types.at(rule.pattern.nodes[bond.second].molecule_type).is_population;
            if (fPop || sPop) { info.enabled = false; break; }
            auto b = bond;
            b.first = oldToNew.at(bond.first);
            b.second = oldToNew.at(bond.second);
            info.particlePattern.bonds.push_back(b);
        }
        if (!info.enabled) continue;
        for (const auto& c : rule.pattern.molecularity) {
            const bool lPop = model.molecule_types.at(rule.pattern.nodes[c.left].molecule_type).is_population;
            const bool rPop = model.molecule_types.at(rule.pattern.nodes[c.right].molecule_type).is_population;
            if (lPop || rPop) continue;
            auto cc = c;
            cc.left = static_cast<std::uint16_t>(oldToNew.at(c.left));
            cc.right = static_cast<std::uint16_t>(oldToNew.at(c.right));
            info.particlePattern.molecularity.push_back(cc);
        }
        for (const auto& pair : rule.pattern.connected_to) {
            const bool fPop = model.molecule_types.at(rule.pattern.nodes[pair.first].molecule_type).is_population;
            const bool sPop = model.molecule_types.at(rule.pattern.nodes[pair.second].molecule_type).is_population;
            if (fPop || sPop) { info.enabled = false; break; }
            info.particlePattern.connected_to.push_back({oldToNew.at(pair.first), oldToNew.at(pair.second)});
        }
        if (!info.enabled) continue;
        for (const auto& sc : rule.pattern.species_compartments) {
            auto it = oldToNew.find(sc.first);
            if (it != oldToNew.end()) {
                info.particlePattern.species_compartments.emplace_back(it->second, sc.second);
            }
        }
        for (const auto& group : rule.pattern.interchangeable) {
            bool anyPop = false;
            std::vector<std::size_t> ng;
            for (auto n : group) {
                if (model.molecule_types.at(rule.pattern.nodes[n].molecule_type).is_population) anyPop = true;
                else ng.push_back(oldToNew.at(n));
            }
            if (anyPop) { info.enabled = false; break; }
            if (ng.size() > 1) info.particlePattern.interchangeable.push_back(std::move(ng));
        }
        mixedLumped[ri] = std::move(info);
    }

    // A population reactant without a compartment needs assignment across
    // occupied compartments. Support explicit locations until that matching
    // and product-inheritance semantics are represented in the executor.
    for (const auto& rule : model.expanded_rules) {
        for (const auto& action : rule.actions) {
            if (action.kind == ActionKind::SetCompartment &&
                action.target_node < rule.pattern.nodes.size()) {
                const auto type = rule.pattern.nodes[action.target_node].molecule_type;
                if (model.molecule_types.at(type).is_population)
                    compartmentalized_populations.insert(type);
            }
            if (action.kind != ActionKind::Create ||
                !model.molecule_types.at(action.molecule_type).is_population)
                continue;
            for (const auto& other : rule.actions) {
                if (other.kind == ActionKind::SetCompartment &&
                    other.target_node == action.target_node)
                    compartmentalized_populations.insert(action.molecule_type);
            }
        }
    }
    for (const auto& rule : model.expanded_rules) {
        for (const auto& node : rule.pattern.nodes) {
            if (!node.compartment && compartmentalized_populations.count(node.molecule_type))
                refuse("unqualified reactant for a compartmentalized population");
        }
    }

    // NFN-14a: Population-only rules support MatchOnce too.
    auto populationOnlyReactants = [&](const ExpandedRuleIR& rule) {
        return !rule.pattern.nodes.empty() &&
               std::all_of(rule.pattern.nodes.begin(), rule.pattern.nodes.end(), [&](const auto& node) {
                   return model.molecule_types.at(node.molecule_type).is_population;
               }) && rule.pattern.bonds.empty() && rule.filters.empty();
    };
    auto populationCombinationFactor = [&](const PopulationCounts& required) {
        double comb = 1.0;
        for (const auto& [key, stoich] : required) {
            const std::uint64_t n = populationCount(key);
            if (n < stoich) return 0.0;
            double c = 1.0;
            for (std::uint64_t i = 0; i < stoich; ++i) {
                c *= static_cast<double>(n - i);
                c /= static_cast<double>(i + 1);
            }
            comb *= c;
        }
        return comb;
    };
    auto populationReactantPropensity = [&](const ExpandedRuleIR& rule) {
        PopulationCounts required;
        for (const auto& node : rule.pattern.nodes) ++required[location(node)];
        return populationCombinationFactor(required);
    };

    const auto restoreRetainedPopulations = [&](const ExpandedRuleIR& rule) {
        for (std::size_t i = 0; i < rule.pattern.nodes.size(); ++i) {
            const auto& node = rule.pattern.nodes[i];
            if (!model.molecule_types.at(node.molecule_type).is_population) continue;
            auto destination = location(node);
            bool destroyed = false;
            for (const auto& action : rule.actions) {
                if (action.target_node != i) continue;
                if (action.kind == ActionKind::Destroy || action.kind == ActionKind::DestroyComplex) {
                    destroyed = true;
                    break;
                }
                if (action.kind == ActionKind::SetCompartment)
                    destination.second = static_cast<CompartmentId>(action.value);
            }
            if (!destroyed) incrementPopulation(destination, 1);
        }
    };

    // NFN-05: Preserve constant ($) seed species counts after every reaction event.
    std::vector<ParticleId> scratchMembers;
    const auto enforceConstantSeeds = [&]() {
        if (constantSeeds.empty()) return;
        for (const auto& spec : constantSeeds) {
            if (spec.is_population) {
                population_counts[spec.pop_location] =
                    static_cast<std::uint64_t>(spec.target_count);
                continue;
            }
            std::map<std::uint32_t, ParticleId> matchedRoots;
            for (const auto& m : matcher.enumerate(spec.pattern, state)) {
                if (!m.particles().empty() && coversWholeComplex(m)) {
                    matchedRoots.emplace(state.complexId(m.particle(0)), m.particle(0));
                }
            }
            const std::size_t current = matchedRoots.size();
            if (current < spec.target_count) {
                const std::size_t missing = spec.target_count - current;
                const auto& pat = spec.pattern;
                if (pat.nodes.empty()) continue;
                if (state.liveCount() + missing * pat.nodes.size() > request.max_particles) {
                    refuse("particle budget exhausted");
                }
                for (std::size_t c = 0; c < missing; ++c) {
                    std::vector<ParticleId> created;
                    created.reserve(pat.nodes.size());
                    for (const auto& node : pat.nodes) {
                        const CompartmentId comp = node.compartment.value_or(spec.default_compartment);
                        const auto pid = state.create(node.molecule_type, comp);
                        created.push_back(pid);
                        for (const auto& constraint : node.constraints) {
                            if (constraint.kind == PatternIR::SiteConstraintKind::State) {
                                state.setSiteState(pid, static_cast<std::uint16_t>(constraint.site), constraint.state);
                            }
                        }
                    }
                    for (const auto& bond : pat.bonds) {
                        state.bind(created.at(bond.first), static_cast<std::uint16_t>(bond.first_site),
                                   created.at(bond.second), static_cast<std::uint16_t>(bond.second_site));
                    }
                }
            } else if (current > spec.target_count) {
                std::size_t excess = current - spec.target_count;
                for (const auto& [_, root] : matchedRoots) {
                    if (excess == 0) break;
                    if (!state.alive(root)) continue;
                    state.complexMembers(root, scratchMembers);
                    for (const auto p : scratchMembers) {
                        if (state.alive(p)) state.destroy(p);
                    }
                    --excess;
                }
            }
        }
    };

    // NFN-09b / NFN-09d: Compartment hierarchy & species-compartment helpers.
    const bool has2DCompartment = std::any_of(
        model.compartments.begin(), model.compartments.end(),
        [](const CompartmentIR& c) { return c.dimensions == 2; });

    auto complexSpeciesCompartmentLocal = [&](ParticleId root, std::vector<ParticleId>& buf) -> CompartmentId {
        if (model.compartments.empty()) return 0;
        state.complexMembers(root, buf);
        for (const auto p : buf) {
            const auto cid = state.compartment(p);
            if (cid < model.compartments.size() && model.compartments[cid].dimensions == 2) {
                return cid;
            }
        }
        return state.compartment(root);
    };

    auto compartmentsFormInteractingSetLocal = [&](const std::vector<CompartmentId>& comps) -> bool {
        if (model.compartments.empty() || comps.size() < 2) return true;
        bool allSame = true;
        for (std::size_t i = 1; i < comps.size(); ++i) {
            if (comps[i] != comps[0]) { allSame = false; break; }
        }
        if (allSame) return true;
        // In cBNGL, distinct reactant compartments can interact iff a 2D surface
        // present in the reactant set is adjacent to every other reactant compartment.
        for (const auto surf : comps) {
            if (surf >= model.compartments.size() || model.compartments[surf].dimensions != 2) continue;
            const auto& surfDecl = model.compartments[surf];
            bool allAdjacent = true;
            for (const auto other : comps) {
                if (other == surf) continue;
                if (other >= model.compartments.size()) { allAdjacent = false; break; }
                const bool isOutside = surfDecl.parent.has_value() && *surfDecl.parent == other;
                const bool isInside = model.compartments[other].parent.has_value() &&
                                      *model.compartments[other].parent == surf;
                if (!isOutside && !isInside) {
                    allAdjacent = false;
                    break;
                }
            }
            if (allAdjacent) return true;
        }
        return false;
    };

    auto is3DSeparatedByHierarchy = [&](CompartmentId src, CompartmentId dst) -> bool {
        return has2DCompartment && src != dst &&
               src < model.compartments.size() && dst < model.compartments.size() &&
               model.compartments[src].dimensions == 3 && model.compartments[dst].dimensions == 3;
    };

    auto unqualifiedVolumeFactor = [&](const ExpandedRuleIR& rule,
                                       const Embedding& match,
                                       std::vector<ParticleId>& buf) -> double {
        if (!rule.has_unqualified_compartments || rule.total_rate ||
            model.compartments.empty() || rule.reactant_pattern_offsets.size() < 2) {
            return 1.0;
        }
        std::vector<bng::compile::ReactantCompartment> rcList;
        rcList.reserve(rule.reactant_pattern_offsets.size());
        for (const auto offset : rule.reactant_pattern_offsets) {
            if (offset >= match.particles().size()) continue;
            const auto cid = complexSpeciesCompartmentLocal(match.particle(offset), buf);
            if (cid < model.compartments.size()) {
                const auto& comp = model.compartments[cid];
                if (std::isfinite(comp.volume) && comp.volume > 0.0) {
                    rcList.push_back({comp.dimensions, comp.volume * numberPerQuantityUnit});
                }
            }
        }
        const auto factor = bng::compile::reactantUnitConversionFactor(rcList);
        return factor.value_or(1.0);
    };

    // NFN-02: Verify post-transformation product molecularity ('+' vs '.') locally in O(|complex|).
    auto satisfiesProductMolecularity = [&](const ExpandedRuleIR& rule,
                                            const Embedding& match) -> bool {
        if (rule.product_molecularity.empty()) return true;
        const std::size_t reactantCount = rule.pattern.nodes.size();
        std::vector<ParticleId> subParticles;
        std::unordered_map<std::uint32_t, std::size_t> slotToVertex;
        std::vector<ParticleId> buf;
        for (const auto root : match.particles()) {
            if (slotToVertex.count(root.index)) continue;
            state.complexMembers(root, buf);
            for (const auto p : buf) {
                if (slotToVertex.emplace(p.index, subParticles.size()).second) {
                    subParticles.push_back(p);
                }
            }
        }
        const std::size_t existingCount = subParticles.size();
        std::unordered_map<PatternNodeId, std::size_t> createdToVertex;
        std::size_t totalVertices = existingCount;
        for (const auto& action : rule.actions) {
            if (action.kind == ActionKind::Create && !createdToVertex.count(action.target_node)) {
                createdToVertex[action.target_node] = totalVertices++;
            }
        }

        std::vector<std::uint8_t> dead(totalVertices, 0);
        using DirectedEnd = std::pair<std::uint32_t, std::uint16_t>;
        std::set<std::pair<DirectedEnd, DirectedEnd>> deletedBonds;
        auto normBondKey = [](std::uint32_t p1, std::uint16_t s1,
                              std::uint32_t p2, std::uint16_t s2) {
            DirectedEnd a{p1, s1};
            DirectedEnd b{p2, s2};
            if (b < a) std::swap(a, b);
            return std::make_pair(a, b);
        };
        for (const auto& action : rule.actions) {
            if (action.kind == ActionKind::Destroy && action.target_node < reactantCount) {
                const auto it = slotToVertex.find(match.particle(action.target_node).index);
                if (it != slotToVertex.end()) dead[it->second] = 1;
            } else if (action.kind == ActionKind::DestroyComplex && action.target_node < reactantCount) {
                state.complexMembers(match.particle(action.target_node), buf);
                for (const auto p : buf) {
                    const auto it = slotToVertex.find(p.index);
                    if (it != slotToVertex.end()) dead[it->second] = 1;
                }
            } else if (action.kind == ActionKind::Unbind &&
                       action.target_node < reactantCount && action.partner_node < reactantCount) {
                const auto p1 = match.particle(action.target_node);
                const auto p2 = match.particle(action.partner_node);
                const auto s1 = match.mappedSite(action.target_node, action.site);
                const auto s2 = match.mappedSite(action.partner_node, action.partner_site);
                deletedBonds.insert(normBondKey(p1.index, s1, p2.index, s2));
            }
        }

        std::vector<std::vector<std::size_t>> adj(totalVertices);
        for (std::size_t u = 0; u < existingCount; ++u) {
            if (dead[u]) continue;
            const auto p = subParticles[u];
            const std::size_t siteCount = model.molecule_types.at(state.type(p)).sites.size();
            for (std::size_t si = 0; si < siteCount; ++si) {
                const auto site = static_cast<std::uint16_t>(si);
                if (!state.bound(p, site)) continue;
                const auto partner = state.bond(p, site);
                if (deletedBonds.count(normBondKey(p.index, site, partner.particle.index, partner.site))) {
                    continue;
                }
                const auto it = slotToVertex.find(partner.particle.index);
                if (it == slotToVertex.end() || dead[it->second]) continue;
                adj[u].push_back(it->second);
            }
        }
        auto resolveVertex = [&](PatternNodeId node) -> std::optional<std::size_t> {
            if (node < reactantCount) {
                const auto it = slotToVertex.find(match.particle(node).index);
                if (it == slotToVertex.end() || dead[it->second]) return std::nullopt;
                return it->second;
            }
            const auto it = createdToVertex.find(node);
            if (it == createdToVertex.end()) return std::nullopt;
            return it->second;
        };
        for (const auto& action : rule.actions) {
            if (action.kind != ActionKind::Bind) continue;
            const auto u = resolveVertex(action.target_node);
            const auto v = resolveVertex(action.partner_node);
            if (u && v) {
                adj[*u].push_back(*v);
                adj[*v].push_back(*u);
            }
        }

        std::vector<std::size_t> comp(totalVertices, totalVertices);
        std::size_t nextComp = 0;
        std::vector<std::size_t> q;
        for (std::size_t start = 0; start < totalVertices; ++start) {
            if (dead[start] || comp[start] != totalVertices) continue;
            comp[start] = nextComp;
            q.clear();
            q.push_back(start);
            for (std::size_t head = 0; head < q.size(); ++head) {
                for (const auto nb : adj[q[head]]) {
                    if (!dead[nb] && comp[nb] == totalVertices) {
                        comp[nb] = nextComp;
                        q.push_back(nb);
                    }
                }
            }
            ++nextComp;
        }

        for (const auto& mc : rule.product_molecularity) {
            const auto u = resolveVertex(mc.left);
            const auto v = resolveVertex(mc.right);
            if (!u || !v) return false;
            const bool same = (comp[*u] == comp[*v]);
            if (mc.kind == MolecularityKind::DifferentComplex && same) return false;
            if (mc.kind == MolecularityKind::SameComplex && !same) return false;
        }
        return true;
    };

    // Extract a tiny local GenericGraphState containing only the connected complex(es)
    // participating in `match`, shared by product filters (NFN-06) and runtime Arrhenius (NFN-10).
    auto extractLocalSubState = [&](const Embedding& match,
                                    GenericGraphState& subState,
                                    MatchEmbedding& subEmb,
                                    std::vector<ParticleId>& subParticles) {
        std::vector<ParticleId> origParticles;
        std::unordered_map<std::uint32_t, ParticleId> origToSub;
        std::vector<ParticleId> buf;
        for (const auto root : match.particles()) {
            if (origToSub.count(root.index)) continue;
            state.complexMembers(root, buf);
            for (const auto p : buf) {
                if (origToSub.count(p.index)) continue;
                const auto sp = subState.create(state.type(p), state.compartment(p));
                const std::size_t siteCount = model.molecule_types.at(state.type(p)).sites.size();
                for (std::size_t si = 0; si < siteCount; ++si) {
                    const auto site = static_cast<std::uint16_t>(si);
                    if (!model.molecule_types.at(state.type(p)).sites[si].states.empty()) {
                        subState.setSiteState(sp, site, state.siteState(p, site));
                    }
                }
                origToSub.emplace(p.index, sp);
                origParticles.push_back(p);
                subParticles.push_back(sp);
            }
        }
        for (const auto p : origParticles) {
            const auto sp = origToSub.at(p.index);
            const std::size_t siteCount = model.molecule_types.at(state.type(p)).sites.size();
            for (std::size_t si = 0; si < siteCount; ++si) {
                const auto site = static_cast<std::uint16_t>(si);
                if (!state.bound(p, site)) continue;
                const auto partner = state.bond(p, site);
                if (partner.particle.index < p.index ||
                    (partner.particle.index == p.index && partner.site < site)) {
                    continue;
                }
                const auto it = origToSub.find(partner.particle.index);
                if (it != origToSub.end() && !subState.bound(sp, site) &&
                    !subState.bound(it->second, partner.site)) {
                    subState.bind(sp, site, it->second, partner.site);
                }
            }
        }
        for (std::size_t ni = 0; ni < match.particles().size(); ++ni) {
            subEmb.bindNode(ni, origToSub.at(match.particle(ni).index));
        }
        if (match.hasSiteMaps()) {
            subEmb.setSiteMaps(match.siteMaps());
        }
    };

    // NFN-06: Evaluate include_products / exclude_products on post-transformation product complexes.
    auto passesProductFilters = [&](const ExpandedRuleIR& rule,
                                    std::size_t ruleIdx,
                                    const Embedding& match) -> bool {
        bool hasProductFilter = false;
        for (const auto& f : rule.filters) {
            if (f.products) { hasProductFilter = true; break; }
        }
        if (!hasProductFilter) return true;

        GenericGraphState subState(model);
        MatchEmbedding subEmb;
        std::vector<ParticleId> subParticles;
        extractLocalSubState(match, subState, subEmb, subParticles);

        std::vector<std::pair<CreatedMoleculeId, CompartmentId>> inheritedComps;
        for (const auto& [createdNode, donorNode] : rule.created_compartment_inherit) {
            auto cidIt = ruleCreatedIds[ruleIdx].find(createdNode);
            if (cidIt != ruleCreatedIds[ruleIdx].end() && donorNode < match.particles().size()) {
                inheritedComps.emplace_back(cidIt->second, subState.compartment(subEmb.particle(donorNode)));
            }
        }
        std::vector<CompartmentId> subBeforeComps;
        std::set<ParticleId> subExplicit;
        if (rule.move_connected || has2DCompartment) {
            subBeforeComps.reserve(match.particles().size());
            for (std::size_t ni = 0; ni < match.particles().size(); ++ni) {
                const auto sp = subEmb.particle(ni);
                subBeforeComps.push_back(subState.compartment(sp));
                subExplicit.insert(sp);
            }
        }

        TransformationResult txRes;
        try {
            txRes = applyTransformation(compiled_transformations[ruleIdx], subEmb, subState);
        } catch (...) {
            return false;
        }
        for (const auto& [cid, comp] : inheritedComps) {
            const auto cp = txRes.created(cid);
            if (subState.alive(cp)) subState.setCompartment(cp, comp);
        }
        for (const auto& action : rule.actions) {
            if (action.kind == ActionKind::SetCompartment && action.target_node < match.particles().size()) {
                const auto sp = subEmb.particle(action.target_node);
                if (subState.alive(sp)) subState.setCompartment(sp, static_cast<CompartmentId>(action.value));
            }
        }
        if (rule.move_connected || has2DCompartment) {
            for (std::size_t ni = 0; ni < match.particles().size(); ++ni) {
                const auto sp = subEmb.particle(ni);
                if (!subState.alive(sp)) continue;
                const auto srcComp = subBeforeComps[ni];
                const auto dstComp = subState.compartment(sp);
                if (dstComp == srcComp) continue;
                if (!rule.move_connected && !is3DSeparatedByHierarchy(srcComp, dstComp)) continue;
                std::queue<ParticleId> q;
                std::set<ParticleId> visited;
                q.push(sp);
                visited.insert(sp);
                while (!q.empty()) {
                    const auto curr = q.front();
                    q.pop();
                    const auto& type = model.molecule_types.at(subState.type(curr));
                    for (std::size_t si = 0; si < type.sites.size(); ++si) {
                        const auto site = static_cast<std::uint16_t>(si);
                        if (!subState.bound(curr, site)) continue;
                        const auto partner = subState.bond(curr, site).particle;
                        if (!visited.insert(partner).second) continue;
                        if (!subExplicit.count(partner) && subState.alive(partner) &&
                            subState.compartment(partner) == srcComp) {
                            subState.setCompartment(partner, dstComp);
                            q.push(partner);
                        }
                    }
                }
            }
        }

        std::vector<ParticleId> prodMembers;
        for (const auto& filter : rule.filters) {
            if (!filter.products) continue;
            ParticleId targetPid{};
            bool hasTarget = false;
            if (filter.reactant_node_offset < rule.pattern.nodes.size()) {
                targetPid = subEmb.particle(filter.reactant_node_offset);
                hasTarget = subState.alive(targetPid);
            } else {
                const auto cidIt = ruleCreatedIds[ruleIdx].find(static_cast<PatternNodeId>(filter.reactant_node_offset));
                if (cidIt != ruleCreatedIds[ruleIdx].end()) {
                    try {
                        targetPid = txRes.created(cidIt->second);
                        hasTarget = subState.alive(targetPid);
                    } catch (...) {
                        hasTarget = false;
                    }
                }
            }
            bool anyMatched = false;
            if (hasTarget) {
                subState.complexMembers(targetPid, prodMembers);
                for (const auto& fPat : filter.patterns) {
                    if (matcher.hasMatchInParticles(fPat, subState, prodMembers)) {
                        anyMatched = true;
                        break;
                    }
                }
            }
            if (filter.include && !anyMatched) return false;
            if (!filter.include && anyMatched) return false;
        }
        return true;
    };

    // NFN-10 / ETH-08..11 / ETH-13: Exact per-match Arrhenius rate via G_after - G_before
    // on the local complex substate.
    auto evaluateRuntimeArrheniusRate = [&](const ExpandedRuleIR& rule,
                                            std::size_t ruleIdx,
                                            const Embedding& match,
                                            std::unordered_map<ObservableId, double>& currentObservableValues) -> double {
        GenericGraphState subState(model);
        MatchEmbedding subEmb;
        std::vector<ParticleId> beforeParticles;
        extractLocalSubState(match, subState, subEmb, beforeParticles);

        std::vector<double> epValues(preparedEnergyPatterns.size(), 0.0);
        for (std::size_t epi = 0; epi < preparedEnergyPatterns.size(); ++epi) {
            const auto& pep = preparedEnergyPatterns[epi];
            if (pep.isDynamic) {
                for (const auto depId : pep.compiledFunction->observableDependencies()) {
                    auto obsIt = currentObservableValues.find(depId);
                    if (obsIt == currentObservableValues.end()) {
                        const auto def = observableIdToDefIndex.find(depId);
                        if (def == observableIdToDefIndex.end())
                            refuse("unresolved observable dependency in energy pattern");
                        obsIt = currentObservableValues.emplace(
                            depId, evaluateObservable(observables[def->second])).first;
                    }
                    functionEnvironment.set("observable_" + std::to_string(depId), obsIt->second);
                }
                epValues[epi] = pep.compiledFunction->evaluate(functionEnvironment);
            } else {
                epValues[epi] = pep.staticEnergy;
            }
        }

        double gBefore = 0.0;
        for (std::size_t epi = 0; epi < preparedEnergyPatterns.size(); ++epi) {
            const auto& pep = preparedEnergyPatterns[epi];
            if (epValues[epi] == 0.0) continue;
            const auto cnt = matcher.enumerateInParticles(pep.pattern, subState, beforeParticles).size();
            if (cnt > 0) gBefore += (static_cast<double>(cnt) / pep.aut) * epValues[epi];
        }

        applyTransformation(compiled_transformations[ruleIdx], subEmb, subState);
        const auto afterParticles = subState.liveParticles();
        double gAfter = 0.0;
        for (std::size_t epi = 0; epi < preparedEnergyPatterns.size(); ++epi) {
            const auto& pep = preparedEnergyPatterns[epi];
            if (epValues[epi] == 0.0) continue;
            const auto cnt = matcher.enumerateInParticles(pep.pattern, subState, afterParticles).size();
            if (cnt > 0) gAfter += (static_cast<double>(cnt) / pep.aut) * epValues[epi];
        }

        const auto& info = rule.runtime_arrhenius;
        const double deltaG = gAfter - gBefore;
        const double phiEff = info.reverse ? (1.0 - info.phi) : info.phi;
        const double exponent = info.ea + info.barrier + phiEff * deltaG +
                                (info.reverse ? phiEff * info.work : -phiEff * info.work);
        if (!std::isfinite(exponent)) refuse("runtime Arrhenius rate exponent is nonfinite");
        const double k = std::exp(-exponent);
        if (!std::isfinite(k) || k < 0.0) refuse("runtime Arrhenius rate is invalid");
        return k;
    };

    // Helper: canonical MatchOnce complex-ID key for a reactant embedding (NFN-12).
    auto matchOnceKeyFor = [&](const ExpandedRuleIR& rule,
                               const std::vector<std::size_t>& offsets,
                               const Embedding& match) -> std::vector<std::uint32_t> {
        std::vector<std::uint32_t> key;
        if (offsets.empty()) {
            if (!match.particles().empty()) key.push_back(state.complexId(match.particle(0)));
            return key;
        }
        key.reserve(offsets.size());
        for (const auto off : offsets) {
            if (off < match.particles().size()) key.push_back(state.complexId(match.particle(off)));
        }
        // Sort interchangeable reactant pattern slots so swapped complex pairs deduplicate.
        for (const auto& group : rule.pattern.interchangeable) {
            std::vector<std::size_t> patSlots;
            for (const auto nodeIdx : group) {
                for (std::size_t pi = 0; pi < offsets.size(); ++pi) {
                    if (offsets[pi] == nodeIdx) { patSlots.push_back(pi); break; }
                }
            }
            if (patSlots.size() > 1) {
                std::vector<std::uint32_t> vals;
                vals.reserve(patSlots.size());
                for (const auto s : patSlots) {
                    if (s < key.size()) vals.push_back(key[s]);
                }
                std::sort(vals.begin(), vals.end());
                for (std::size_t k = 0; k < vals.size(); ++k) key[patSlots[k]] = vals[k];
            }
        }
        return key;
    };

    const auto layout = RngLayout::exactSSA();
    double time = request.start_time;
    double next_time = std::numeric_limits<double>::infinity();
    std::size_t selected_rule = 0;
    Embedding selected_match;
    bool selected_population_rule = false;
    bool selected_mixed_lumped_rule = false;
    bool pending = false;
    for (const double sample : request.sample_times) {
        for (;;) {
            if (!pending) reconcilePopulationThresholds();
            if (!pending) {
                std::vector<std::vector<Embedding>> matches;
                std::vector<std::vector<double>> matchWeights(model.expanded_rules.size());
                std::vector<double> rulePropensities(model.expanded_rules.size(), 0.0);
                std::vector<double> currentRates(model.expanded_rules.size(), 0.0);
                std::vector<double> populationFactors(model.expanded_rules.size(), 1.0);
                std::unordered_map<ObservableId, double> currentObservableValues;
                double total = 0.0;
                for (std::size_t index = 0; index < model.expanded_rules.size(); ++index) {
                    const auto& rule = model.expanded_rules[index];
                    const auto& prep = preparedRates[index];
                    const bool hasLocalFuncs = !rule.local_observable_bindings.empty();
                    double rate = prep.elementaryRate;
                    if (prep.isDynamic && !hasLocalFuncs) {
                        for (const auto depId : prep.compiledFunction->observableDependencies()) {
                            auto obsIt = currentObservableValues.find(depId);
                            if (obsIt == currentObservableValues.end()) {
                                const auto definition = observableIdToDefIndex.find(depId);
                                if (definition == observableIdToDefIndex.end())
                                    refuse("unresolved observable dependency");
                                obsIt = currentObservableValues.emplace(
                                    depId, evaluateObservable(observables[definition->second])).first;
                            }
                            functionEnvironment.set("observable_" + std::to_string(depId), obsIt->second);
                        }
                        rate = prep.compiledFunction->evaluate(functionEnvironment);
                        if (!std::isfinite(rate) || rate < 0.0) {
                            refuse("dynamic rate must be finite and non-negative");
                        }
                    }
                    // NFN-13: TotalRate specifies the total macroscopic propensity
                    // independent of compartment volume scaling.
                    if (!rule.total_rate) {
                        rate *= rule.volume_factor;
                    }
                    currentRates[index] = rate;
                    if (populationOnlyReactants(rule)) {
                        matches.emplace_back();
                        const double popFactor = populationReactantPropensity(rule);
                        populationFactors[index] = popFactor;
                        const double prop = rule.total_rate
                            ? (popFactor > 0.0 ? rate : 0.0)
                            : rate * popFactor;
                        rulePropensities[index] = prop;
                        total += prop;
                        continue;
                    }
                    if (mixedLumped[index].enabled) {
                        const auto& info = mixedLumped[index];
                        const double popFactor = populationCombinationFactor(info.popReactantCounts);
                        populationFactors[index] = popFactor;
                        if (popFactor <= 0.0) {
                            matches.emplace_back();
                            rulePropensities[index] = 0.0;
                            continue;
                        }
                        auto rawMatches = matcher.enumerate(info.particlePattern, state);
                        // Apply include/exclude reactant filters scoped to each matched complex (PERF-05).
                        if (!rule.filters.empty() && !rawMatches.empty()) {
                            std::map<std::size_t, std::size_t> oldToNewParticle;
                            for (std::size_t pi = 0; pi < info.particleReactantNodes.size(); ++pi)
                                oldToNewParticle[info.particleReactantNodes[pi]] = pi;
                            std::vector<std::unordered_map<std::uint32_t, bool>> filterCache(rule.filters.size());
                            std::vector<Embedding> passedMatches;
                            passedMatches.reserve(rawMatches.size());
                            for (const auto& match : rawMatches) {
                                bool matchPassed = true;
                                for (std::size_t fi = 0; fi < rule.filters.size(); ++fi) {
                                    const auto& filter = rule.filters[fi];
                                    if (filter.products) continue;
                                    auto itNode = oldToNewParticle.find(filter.reactant_node_offset);
                                    if (itNode == oldToNewParticle.end()) continue;
                                    const auto partId = match.particle(itNode->second);
                                    const auto compId = state.complexId(partId);
                                    auto cit = filterCache[fi].find(compId);
                                    bool ok = true;
                                    if (cit != filterCache[fi].end()) {
                                        ok = cit->second;
                                    } else {
                                        state.complexMembers(partId, scratchMembers);
                                        bool anyMatched = false;
                                        for (const auto& fPat : filter.patterns) {
                                            if (matcher.hasMatchInParticles(fPat, state, scratchMembers)) {
                                                anyMatched = true;
                                                break;
                                            }
                                        }
                                        ok = filter.include ? anyMatched : !anyMatched;
                                        filterCache[fi].emplace(compId, ok);
                                    }
                                    if (!ok) { matchPassed = false; break; }
                                }
                                if (matchPassed) passedMatches.push_back(match);
                            }
                            rawMatches = std::move(passedMatches);
                        }
                        // NFN-12: MatchOnce deduplicates by complex ID tuple (not particle set).
                        if (rule.match_once && !rawMatches.empty()) {
                            std::vector<std::size_t> partOffsets;
                            std::map<std::size_t, std::size_t> oldToNewParticle;
                            for (std::size_t pi = 0; pi < info.particleReactantNodes.size(); ++pi)
                                oldToNewParticle[info.particleReactantNodes[pi]] = pi;
                            for (const auto off : rule.reactant_pattern_offsets) {
                                auto it = oldToNewParticle.find(off);
                                if (it != oldToNewParticle.end()) partOffsets.push_back(it->second);
                            }
                            if (partOffsets.empty()) partOffsets.push_back(0);
                            std::vector<Embedding> uniqueMatches;
                            std::set<std::vector<std::uint32_t>> seenKeys;
                            for (const auto& match : rawMatches) {
                                std::vector<std::uint32_t> key;
                                key.reserve(partOffsets.size());
                                for (const auto off : partOffsets) {
                                    if (off < match.particles().size())
                                        key.push_back(state.complexId(match.particle(off)));
                                }
                                if (seenKeys.insert(key).second) uniqueMatches.push_back(match);
                            }
                            rawMatches = std::move(uniqueMatches);
                        }
                        matches.push_back(std::move(rawMatches));
                        // NFN-14b: TotalRate must NOT be multiplied by popFactor!
                        const double effDiv = rule.match_once ? 1.0 : rule.symmetry_divisor;
                        double prop = 0.0;
                        if (rule.total_rate) {
                            prop = matches.back().empty() ? 0.0 : rate;
                        } else {
                            prop = rate * popFactor * static_cast<double>(matches.back().size()) / effDiv;
                        }
                        rulePropensities[index] = prop;
                        total += prop;
                        continue;
                    }
                    // PERF-01 / RULEHUB-06: O(N) independent counting & exact uniform
                    // sampling for disconnected single-molecule reactants (including
                    // same-type pairs, interchangeable pairs, duplicate sites, and
                    // DifferentComplex molecularity).
                    const bool populationMap = rule.annotations.count("bng.population_map_index") != 0;
                    const bool canUseIndependent =
                        !populationMap && !rule.match_once && rule.filters.empty() &&
                        rule.product_molecularity.empty() && !rule.has_unqualified_compartments &&
                        rule.destroy_complex_patterns.empty() && !hasLocalFuncs &&
                        !rule.runtime_arrhenius.enabled &&
                        (model.compartments.empty() || rule.pattern.nodes.size() <= 1);
                    if (canUseIndependent) {
                        if (const auto independent = matcher.countIndependent(rule.pattern, state)) {
                            std::vector<Embedding> sampled;
                            if (independent->count > 0) {
                                std::uint64_t auxWord = output.event_count * 65536ULL +
                                                        static_cast<std::uint64_t>(index) * 128ULL;
                                auto drawIndex = [&](std::size_t bound) -> std::size_t {
                                    const double u = rng.uniformOpen01(
                                        layout.word(RngPurpose::Auxiliary, auxWord++));
                                    std::size_t pick = static_cast<std::size_t>(
                                        u * static_cast<double>(bound));
                                    if (pick >= bound) pick = bound - 1;
                                    return pick;
                                };
                                const std::size_t nNodes = rule.pattern.nodes.size();
                                std::vector<std::size_t> picks(nNodes, 0);
                                if (nNodes == 2 &&
                                    (independent->different_complex || independent->same_type_pair)) {
                                    const auto& c0 = independent->candidates[0];
                                    const auto& c1 = independent->candidates[1];
                                    auto pairKey = [&](ParticleId p) -> std::uint32_t {
                                        return independent->different_complex
                                            ? state.complexId(p) : p.index;
                                    };
                                    bool picked = false;
                                    for (int attempt = 0; attempt < 32; ++attempt) {
                                        const std::size_t i0 = drawIndex(c0.size());
                                        const std::size_t i1 = drawIndex(c1.size());
                                        if (pairKey(c0[i0]) != pairKey(c1[i1])) {
                                            picks[0] = i0;
                                            picks[1] = i1;
                                            picked = true;
                                            break;
                                        }
                                    }
                                    if (!picked) {
                                        // Exact O(N) bucket-weighted fallback (zero bias even near gelation).
                                        std::unordered_map<std::uint32_t, std::size_t> freq1;
                                        freq1.reserve(c1.size());
                                        for (const auto p : c1) ++freq1[pairKey(p)];
                                        const std::size_t orderedTotal = independent->interchangeable_pair
                                            ? (independent->count * 2) : independent->count;
                                        std::size_t target = drawIndex(orderedTotal);
                                        std::size_t chosen0 = 0;
                                        for (std::size_t i = 0; i < c0.size(); ++i) {
                                            const auto it = freq1.find(pairKey(c0[i]));
                                            const std::size_t validPartners =
                                                c1.size() - (it == freq1.end() ? 0 : it->second);
                                            if (target < validPartners) {
                                                chosen0 = i;
                                                break;
                                            }
                                            target -= validPartners;
                                        }
                                        const auto key0 = pairKey(c0[chosen0]);
                                        std::size_t chosen1 = 0;
                                        for (std::size_t j = 0; j < c1.size(); ++j) {
                                            if (pairKey(c1[j]) == key0) continue;
                                            if (target == 0) {
                                                chosen1 = j;
                                                break;
                                            }
                                            --target;
                                        }
                                        picks[0] = chosen0;
                                        picks[1] = chosen1;
                                    }
                                } else {
                                    for (std::size_t node = 0; node < nNodes; ++node) {
                                        picks[node] = drawIndex(independent->candidates[node].size());
                                    }
                                }
                                std::vector<ParticleId> selected;
                                std::vector<TypeId> types;
                                selected.reserve(nNodes);
                                types.reserve(nNodes);
                                bool anyMaps = false;
                                for (std::size_t node = 0; node < nNodes; ++node) {
                                    const auto particle = independent->candidates[node][picks[node]];
                                    selected.push_back(particle);
                                    types.push_back(state.type(particle));
                                    if (!independent->candidate_site_maps[node].empty()) anyMaps = true;
                                }
                                if (anyMaps) {
                                    std::vector<std::vector<std::uint16_t>> smaps(nNodes);
                                    for (std::size_t node = 0; node < nNodes; ++node) {
                                        if (!independent->candidate_site_maps[node].empty()) {
                                            smaps[node] = independent->candidate_site_maps[node][picks[node]];
                                        }
                                    }
                                    sampled.emplace_back(std::move(selected), std::move(types), std::move(smaps));
                                } else {
                                    sampled.emplace_back(std::move(selected), std::move(types));
                                }
                            }
                            const double prop = rule.total_rate
                                ? (independent->count > 0 ? rate : 0.0)
                                : (rate * static_cast<double>(independent->count) / rule.symmetry_divisor);
                            currentRates[index] = prop;
                            matches.push_back(std::move(sampled));
                            rulePropensities[index] = prop;
                            total += prop;
                            continue;
                        }
                    }

                    auto rawMatches = matcher.enumerate(rule.pattern, state);
                    if (populationMap) {
                        const auto firstPartialMatch = std::remove_if(
                            rawMatches.begin(), rawMatches.end(),
                            [&](const auto& match) { return !coversWholeComplex(match); });
                        rawMatches.erase(firstPartialMatch, rawMatches.end());
                    }
                    // NFN-09b: Enforce cBNGL compartment adjacency across multi-reactant complexes.
                    if (!model.compartments.empty() && rule.reactant_pattern_offsets.size() >= 2 &&
                        !rawMatches.empty()) {
                        std::vector<CompartmentId> reactantComps;
                        reactantComps.reserve(rule.reactant_pattern_offsets.size());
                        const auto endIt = std::remove_if(
                            rawMatches.begin(), rawMatches.end(),
                            [&](const Embedding& match) {
                                reactantComps.clear();
                                for (const auto offset : rule.reactant_pattern_offsets) {
                                    if (offset < match.particles().size()) {
                                        reactantComps.push_back(
                                            complexSpeciesCompartmentLocal(match.particle(offset), scratchMembers));
                                    }
                                }
                                return !compartmentsFormInteractingSetLocal(reactantComps);
                            });
                        rawMatches.erase(endIt, rawMatches.end());
                    }
                    // NFN-02: Filter out matches violating product molecularity ('+' vs '.') BEFORE propensity!
                    if (!rule.product_molecularity.empty() && !rawMatches.empty()) {
                        const auto endIt = std::remove_if(
                            rawMatches.begin(), rawMatches.end(),
                            [&](const Embedding& match) {
                                return !satisfiesProductMolecularity(rule, match);
                            });
                        rawMatches.erase(endIt, rawMatches.end());
                    }
                    // NFN-06 / NFN-07 / PERF-05: Evaluate reactant filters (scoped to matched complex)
                    // AND product filters (evaluated on post-transformation product complexes).
                    if (!rule.filters.empty() && !rawMatches.empty()) {
                        std::vector<std::unordered_map<std::uint32_t, bool>> filterCache(rule.filters.size());
                        bool hasProductFilters = false;
                        for (const auto& f : rule.filters) {
                            if (f.products) { hasProductFilters = true; break; }
                        }
                        std::vector<Embedding> passedMatches;
                        passedMatches.reserve(rawMatches.size());
                        for (const auto& match : rawMatches) {
                            bool matchPassed = true;
                            for (std::size_t fi = 0; fi < rule.filters.size(); ++fi) {
                                const auto& filter = rule.filters[fi];
                                if (filter.products) continue;
                                const auto nodeIdx = filter.reactant_node_offset;
                                if (nodeIdx >= match.particles().size()) continue;
                                const auto partId = match.particle(nodeIdx);
                                const auto compId = state.complexId(partId);
                                auto cit = filterCache[fi].find(compId);
                                bool ok = true;
                                if (cit != filterCache[fi].end()) {
                                    ok = cit->second;
                                } else {
                                    state.complexMembers(partId, scratchMembers);
                                    bool anyMatched = false;
                                    for (const auto& fPat : filter.patterns) {
                                        if (matcher.hasMatchInParticles(fPat, state, scratchMembers)) {
                                            anyMatched = true;
                                            break;
                                        }
                                    }
                                    ok = filter.include ? anyMatched : !anyMatched;
                                    filterCache[fi].emplace(compId, ok);
                                }
                                if (!ok) {
                                    matchPassed = false;
                                    break;
                                }
                            }
                            if (matchPassed && hasProductFilters) {
                                matchPassed = passesProductFilters(rule, index, match);
                            }
                            if (matchPassed) passedMatches.push_back(match);
                        }
                        rawMatches = std::move(passedMatches);
                    }
                    // NFN-04 #5: Whole-species deletion (DestroyComplex) deduplicates matches
                    // per deleted target complex (preserving non-deleted reactant embeddings).
                    if (!rule.destroy_complex_patterns.empty() && !rawMatches.empty()) {
                        std::vector<bool> nodeInDeletedPat(rule.pattern.nodes.size(), false);
                        std::unordered_set<std::size_t> delPatSet(
                            rule.destroy_complex_patterns.begin(), rule.destroy_complex_patterns.end());
                        const auto& offs = rule.reactant_pattern_offsets;
                        for (std::size_t pi = 0; pi < offs.size(); ++pi) {
                            if (!delPatSet.count(pi)) continue;
                            const std::size_t start = offs[pi];
                            const std::size_t end = (pi + 1 < offs.size()) ? offs[pi + 1] : rule.pattern.nodes.size();
                            for (std::size_t u = start; u < end && u < nodeInDeletedPat.size(); ++u) {
                                nodeInDeletedPat[u] = true;
                            }
                        }
                        std::vector<Embedding> uniqueMatches;
                        uniqueMatches.reserve(rawMatches.size());
                        using DelKey = std::pair<std::vector<std::uint32_t>, std::vector<std::uint32_t>>;
                        std::set<DelKey> seenDelKeys;
                        for (const auto& match : rawMatches) {
                            std::vector<std::uint32_t> keptKey;
                            for (std::size_t ni = 0; ni < match.particles().size(); ++ni) {
                                if (ni < nodeInDeletedPat.size() && nodeInDeletedPat[ni]) continue;
                                keptKey.push_back(match.particle(ni).index);
                                if (match.hasSiteMaps() && ni < match.siteMaps().size()) {
                                    keptKey.push_back(static_cast<std::uint32_t>(match.siteMaps()[ni].size()));
                                    for (const auto s : match.siteMaps()[ni]) keptKey.push_back(s);
                                }
                            }
                            std::vector<std::uint32_t> delCompKey;
                            delCompKey.reserve(rule.destroy_complex_patterns.size());
                            for (const auto pi : rule.destroy_complex_patterns) {
                                const std::size_t off = (pi < offs.size()) ? offs[pi] : 0;
                                if (off < match.particles().size()) {
                                    delCompKey.push_back(state.complexId(match.particle(off)));
                                }
                            }
                            if (!rule.pattern.interchangeable.empty() && delCompKey.size() > 1) {
                                std::sort(delCompKey.begin(), delCompKey.end());
                            }
                            if (seenDelKeys.emplace(std::move(keptKey), std::move(delCompKey)).second) {
                                uniqueMatches.push_back(match);
                            }
                        }
                        rawMatches = std::move(uniqueMatches);
                    }
                    // NFN-12: MatchOnce deduplicates by reactant complex-ID tuple (not particle set).
                    if (rule.match_once && !rawMatches.empty()) {
                        std::vector<Embedding> uniqueMatches;
                        uniqueMatches.reserve(rawMatches.size());
                        std::set<std::vector<std::uint32_t>> seenComplexKeys;
                        for (const auto& match : rawMatches) {
                            auto key = matchOnceKeyFor(rule, rule.reactant_pattern_offsets, match);
                            if (seenComplexKeys.insert(std::move(key)).second) {
                                uniqueMatches.push_back(match);
                            }
                        }
                        rawMatches = std::move(uniqueMatches);
                    }

                    const bool hasPerMatchRate =
                        rule.runtime_arrhenius.enabled || hasLocalFuncs ||
                        (rule.has_unqualified_compartments && !rule.total_rate);
                    const double effectiveDiv = rule.match_once ? 1.0 : rule.symmetry_divisor;

                    if (hasPerMatchRate && !rawMatches.empty()) {
                        // Refresh any global observable dependencies once before per-match evaluation.
                        if (hasLocalFuncs && prep.isDynamic) {
                            for (const auto depId : prep.compiledFunction->observableDependencies()) {
                                auto obsIt = currentObservableValues.find(depId);
                                if (obsIt == currentObservableValues.end()) {
                                    const auto def = observableIdToDefIndex.find(depId);
                                    if (def == observableIdToDefIndex.end())
                                        refuse("unresolved observable dependency");
                                    obsIt = currentObservableValues.emplace(
                                        depId, evaluateObservable(observables[def->second])).first;
                                }
                                functionEnvironment.set("observable_" + std::to_string(depId), obsIt->second);
                            }
                        }
                        auto& weights = matchWeights[index];
                        weights.reserve(rawMatches.size());
                        double prop = 0.0;
                        const double matchCountD = static_cast<double>(rawMatches.size());
                        for (const auto& match : rawMatches) {
                            double mRate = rate;
                            if (rule.runtime_arrhenius.enabled) {
                                mRate = evaluateRuntimeArrheniusRate(
                                    rule, index, match, currentObservableValues);
                                if (!rule.total_rate) mRate *= rule.volume_factor;
                            } else if (hasLocalFuncs && prep.isDynamic) {
                                for (const auto& lb : rule.local_observable_bindings) {
                                    if (lb.reactant_node >= match.particles().size() ||
                                        lb.observable_index >= observables.size()) {
                                        refuse("invalid local observable binding");
                                    }
                                    const auto anchor = match.particle(lb.reactant_node);
                                    state.complexMembers(anchor, scratchMembers);
                                    const double localVal = evaluateObservableLocally(
                                        observables[lb.observable_index], scratchMembers, anchor, lb.molecule_scope);
                                    functionEnvironment.set("local_obs_" + std::to_string(lb.slot), localVal);
                                }
                                mRate = prep.compiledFunction->evaluate(functionEnvironment);
                                if (!std::isfinite(mRate) || mRate < 0.0) {
                                    refuse("local function rate must be finite and non-negative");
                                }
                                if (!rule.total_rate) mRate *= rule.volume_factor;
                            }
                            if (rule.has_unqualified_compartments && !rule.total_rate) {
                                mRate *= unqualifiedVolumeFactor(rule, match, scratchMembers);
                            }
                            const double w = rule.total_rate
                                ? (mRate / matchCountD)
                                : (mRate / effectiveDiv);
                            weights.push_back(w);
                            prop += w;
                        }
                        matches.push_back(std::move(rawMatches));
                        rulePropensities[index] = prop;
                        total += prop;
                    } else {
                        matches.push_back(std::move(rawMatches));
                        double prop = 0.0;
                        if (rule.total_rate) {
                            prop = matches.back().empty() ? 0.0 : rate;
                        } else {
                            prop = rate * static_cast<double>(matches.back().size()) / effectiveDiv;
                        }
                        rulePropensities[index] = prop;
                        total += prop;
                    }
                }
                if (!std::isfinite(total)) refuse("nonfinite total propensity");
                next_time = total > 0.0
                    ? time + rng.exponential(layout.word(RngPurpose::WaitingTime, output.event_count), total)
                    : std::numeric_limits<double>::infinity();
                if (total > 0.0) {
                    // PERF-01 / NFN-14b: O(R) reaction selection with O(1) uniform match pick
                    // (eliminating matches.front() bias and O(total matches) linear scan).
                    double choice = rng.uniformOpen01(
                        layout.word(RngPurpose::FamilyChoice, output.event_count)) * total;
                    bool found = false;
                    std::optional<std::size_t> lastPositive;
                    for (std::size_t index = 0; index < model.expanded_rules.size(); ++index) {
                        const double rProp = rulePropensities[index];
                        if (rProp <= 0.0) continue;
                        lastPositive = index;
                        if (choice < rProp) {
                            const auto& rule = model.expanded_rules[index];
                            selected_rule = index;
                            if (populationOnlyReactants(rule)) {
                                selected_population_rule = true;
                                selected_mixed_lumped_rule = false;
                                found = true;
                                break;
                            }
                            selected_population_rule = false;
                            selected_mixed_lumped_rule = mixedLumped[index].enabled;
                            if (!matchWeights[index].empty()) {
                                std::size_t pick = matchWeights[index].size() - 1;
                                for (std::size_t k = 0; k < matchWeights[index].size(); ++k) {
                                    if (choice < matchWeights[index][k]) {
                                        pick = k;
                                        break;
                                    }
                                    choice -= matchWeights[index][k];
                                }
                                selected_match = matches[index][pick];
                            } else {
                                const std::size_t mCount = matches[index].size();
                                if (mCount == 0) refuse("selected rule has no candidate match");
                                std::size_t pick = static_cast<std::size_t>(
                                    (choice / rProp) * static_cast<double>(mCount));
                                if (pick >= mCount) pick = mCount - 1;
                                selected_match = matches[index][pick];
                            }
                            found = true;
                            break;
                        }
                        choice -= rProp;
                    }
                    if (!found && lastPositive.has_value()) {
                        const std::size_t index = *lastPositive;
                        const auto& rule = model.expanded_rules[index];
                        selected_rule = index;
                        selected_population_rule = populationOnlyReactants(rule);
                        selected_mixed_lumped_rule = !selected_population_rule && mixedLumped[index].enabled;
                        if (!selected_population_rule) {
                            if (matches[index].empty()) refuse("selected rule has no candidate match");
                            selected_match = matches[index].back();
                        }
                        found = true;
                    }
                    if (!found) refuse("reaction selection lost floating-point mass");
                }
                pending = true;
            }
            if (next_time > sample) break;
            if (output.event_count >= request.max_events) refuse("event budget exhausted");
            if (!(next_time > time)) refuse("event clock cannot advance");
            time = next_time;

            const auto& rule = model.expanded_rules[selected_rule];
            if (selected_population_rule) {
                PopulationCounts required;
                for (const auto& node : rule.pattern.nodes) ++required[location(node)];
                for (const auto& [key, stoich] : required) {
                    if (populationCount(key) < stoich) refuse("population underflow");
                }
                for (const auto& [key, stoich] : required) {
                    population_counts.at(key) -= stoich;
                }
                std::map<PatternNodeId, CreatedMoleculeId> node_to_created;
                std::map<PatternNodeId, TypeId> created_types;
                std::map<PatternNodeId, std::vector<std::pair<std::uint32_t, std::int32_t>>> created_states;
                std::map<PatternNodeId, CompartmentId> created_compartments;
                CreatedMoleculeId next_created = 0;
                for (const auto& action : rule.actions) {
                    if (action.kind == ActionKind::Create) {
                        if (!node_to_created.count(action.target_node)) {
                            node_to_created[action.target_node] = next_created++;
                            created_types[action.target_node] = action.molecule_type;
                        }
                    } else if (action.kind == ActionKind::SetSiteState && action.target_node >= rule.pattern.nodes.size()) {
                        created_states[action.target_node].push_back({action.site, action.value});
                    } else if (action.kind == ActionKind::SetCompartment && action.target_node >= rule.pattern.nodes.size()) {
                        created_compartments[action.target_node] = static_cast<CompartmentId>(action.value);
                    }
                }
                for (const auto& [createdNode, donorNode] : rule.created_compartment_inherit) {
                    if (!created_compartments.count(createdNode) &&
                        donorNode < rule.pattern.nodes.size() &&
                        rule.pattern.nodes[donorNode].compartment.has_value()) {
                        created_compartments[createdNode] = *rule.pattern.nodes[donorNode].compartment;
                    }
                }
                std::map<CreatedMoleculeId, ParticleId> created_particles;
                for (const auto& [node, cid] : node_to_created) {
                    const TypeId type = created_types[node];
                    if (model.molecule_types.at(type).is_population) {
                        if (created_states.count(node)) refuse("stateful population products are not supported");
                        const auto location = created_compartments.find(node);
                        incrementPopulation(
                            {type, location == created_compartments.end()
                                       ? std::nullopt
                                       : std::make_optional(location->second)},
                            1);
                        continue;
                    }
                    CompartmentId comp = 0;
                    auto cit = created_compartments.find(node);
                    if (cit != created_compartments.end()) comp = cit->second;
                    const auto pid = state.create(type, comp);
                    created_particles[cid] = pid;
                    auto sit = created_states.find(node);
                    if (sit != created_states.end()) {
                        for (const auto& [site, val] : sit->second)
                            state.setSiteState(pid, static_cast<std::uint16_t>(site), val);
                    }
                }
                for (const auto& action : rule.actions) {
                    if (action.kind == ActionKind::Bind) {
                        const bool first_created = action.target_node >= rule.pattern.nodes.size();
                        const bool second_created = action.partner_node >= rule.pattern.nodes.size();
                        if (!(first_created && second_created))
                            refuse("unsupported mixed population-reactant binding in lumped rule");
                        const auto c1 = node_to_created.at(action.target_node);
                        const auto c2 = node_to_created.at(action.partner_node);
                        if (!created_particles.count(c1) || !created_particles.count(c2))
                            refuse("population-particle binding in lumped rule is not supported");
                        state.bind(created_particles.at(c1), static_cast<std::uint16_t>(action.site),
                                   created_particles.at(c2), static_cast<std::uint16_t>(action.partner_site));
                    } else if (action.kind == ActionKind::Destroy || action.kind == ActionKind::DestroyComplex ||
                               action.kind == ActionKind::Create || action.kind == ActionKind::SetSiteState ||
                               action.kind == ActionKind::SetCompartment) {
                    } else {
                        refuse("unsupported action in population-only lumped rule");
                    }
                }
                restoreRetainedPopulations(rule);
                enforceConstantSeeds();
                if (state.liveCount() > request.max_particles) refuse("particle budget exhausted");
                ++output.event_count;
                pending = false;
                continue;
            }
            if (selected_mixed_lumped_rule) {
                const auto& info = mixedLumped[selected_rule];
                for (const auto& [key, stoich] : info.popReactantCounts) {
                    if (populationCount(key) < stoich) refuse("population underflow");
                }
                for (const auto& [key, stoich] : info.popReactantCounts) {
                    population_counts.at(key) -= stoich;
                }

                MatchEmbedding full_embedding;
                std::vector<std::vector<std::uint16_t>> fullSiteMaps;
                if (selected_match.hasSiteMaps()) fullSiteMaps.resize(rule.pattern.nodes.size());
                for (std::size_t pi = 0; pi < info.particleReactantNodes.size() && pi < selected_match.particles().size(); ++pi) {
                    const auto origNode = info.particleReactantNodes[pi];
                    full_embedding.bindNode(origNode, selected_match.particle(pi));
                    if (selected_match.hasSiteMaps() && pi < selected_match.siteMaps().size()) {
                        fullSiteMaps[origNode] = selected_match.siteMaps()[pi];
                    }
                }
                if (!fullSiteMaps.empty()) full_embedding.setSiteMaps(std::move(fullSiteMaps));

                // NFN-14c: Capture beforeCompartments BEFORE SetCompartment runs!
                std::vector<CompartmentId> beforeCompartments;
                std::set<ParticleId> explicitParticles;
                if (rule.move_connected || has2DCompartment) {
                    beforeCompartments.assign(info.particleReactantNodes.size(), 0);
                    for (std::size_t i = 0; i < info.particleReactantNodes.size(); ++i) {
                        try {
                            const auto p = full_embedding.particle(info.particleReactantNodes[i]);
                            explicitParticles.insert(p);
                            if (state.alive(p)) beforeCompartments[i] = state.compartment(p);
                        } catch (...) {}
                    }
                }

                std::map<PatternNodeId, CreatedMoleculeId> node_to_created;
                std::map<PatternNodeId, TypeId> created_types;
                std::map<PatternNodeId, std::vector<std::pair<std::uint32_t, std::int32_t>>> created_states;
                std::map<PatternNodeId, CompartmentId> created_compartments;
                CreatedMoleculeId next_created = 0;
                for (const auto& action : rule.actions) {
                    if (action.kind == ActionKind::Create) {
                        if (!node_to_created.count(action.target_node)) {
                            node_to_created[action.target_node] = next_created++;
                            created_types[action.target_node] = action.molecule_type;
                        }
                    } else if (action.kind == ActionKind::SetSiteState && action.target_node >= rule.pattern.nodes.size()) {
                        created_states[action.target_node].push_back({action.site, action.value});
                    } else if (action.kind == ActionKind::SetCompartment && action.target_node >= rule.pattern.nodes.size()) {
                        created_compartments[action.target_node] = static_cast<CompartmentId>(action.value);
                    }
                }
                auto isPopReactant = [&](PatternNodeId node) {
                    return node < rule.pattern.nodes.size() &&
                           model.molecule_types.at(rule.pattern.nodes[node].molecule_type).is_population;
                };
                for (const auto& [createdNode, donorNode] : rule.created_compartment_inherit) {
                    if (created_compartments.count(createdNode) || donorNode >= rule.pattern.nodes.size()) continue;
                    if (isPopReactant(donorNode)) {
                        if (rule.pattern.nodes[donorNode].compartment.has_value()) {
                            created_compartments[createdNode] = *rule.pattern.nodes[donorNode].compartment;
                        }
                    } else {
                        try {
                            const auto dp = full_embedding.particle(donorNode);
                            if (state.alive(dp)) created_compartments[createdNode] = state.compartment(dp);
                        } catch (...) {}
                    }
                }
                std::map<CreatedMoleculeId, ParticleId> created_particles;
                for (const auto& [node, cid] : node_to_created) {
                    const TypeId type = created_types[node];
                    if (model.molecule_types.at(type).is_population) {
                        if (created_states.count(node)) refuse("stateful population products are not supported");
                        const auto location = created_compartments.find(node);
                        incrementPopulation(
                            {type, location == created_compartments.end()
                                       ? std::nullopt
                                       : std::make_optional(location->second)},
                            1);
                        continue;
                    }
                    CompartmentId comp = 0;
                    auto cit = created_compartments.find(node);
                    if (cit != created_compartments.end()) comp = cit->second;
                    const auto pid = state.create(type, comp);
                    created_particles[cid] = pid;
                    auto sit = created_states.find(node);
                    if (sit != created_states.end()) {
                        for (const auto& [site, val] : sit->second)
                            state.setSiteState(pid, static_cast<std::uint16_t>(site), val);
                    }
                }

                auto resolveEndpoint = [&](PatternNodeId node, std::uint16_t site, ParticleId& pid, std::uint16_t& outSite) -> bool {
                    if (node < rule.pattern.nodes.size()) {
                        if (isPopReactant(node)) return false;
                        try { pid = full_embedding.particle(node); } catch (...) { return false; }
                        outSite = full_embedding.mappedSite(node, site);
                        return state.alive(pid);
                    }
                    auto it = node_to_created.find(node);
                    if (it == node_to_created.end()) return false;
                    auto pit = created_particles.find(it->second);
                    if (pit == created_particles.end()) return false; // population product
                    pid = pit->second;
                    outSite = site;
                    return state.alive(pid);
                };

                for (const auto& action : rule.actions) {
                    switch (action.kind) {
                    case ActionKind::Create:
                    case ActionKind::SetCompartment:
                        break;
                    case ActionKind::SetSiteState: {
                        if (action.target_node < rule.pattern.nodes.size()) {
                            if (isPopReactant(action.target_node)) refuse("state changes on population reactants are not supported");
                            try {
                                const auto pid = full_embedding.particle(action.target_node);
                                const auto mapped = full_embedding.mappedSite(action.target_node, action.site);
                                if (state.alive(pid)) state.setSiteState(pid, mapped, action.value);
                            } catch (...) { refuse("invalid embedding for SetSiteState"); }
                        } else {
                            auto it = node_to_created.find(action.target_node);
                            if (it != node_to_created.end()) {
                                auto pit = created_particles.find(it->second);
                                if (pit != created_particles.end() && state.alive(pit->second))
                                    state.setSiteState(pit->second, action.site, action.value);
                            }
                        }
                        break;
                    }
                    case ActionKind::Unbind: {
                        ParticleId a,b; std::uint16_t sa,sb;
                        if (!resolveEndpoint(action.target_node, action.site, a, sa) ||
                            !resolveEndpoint(action.partner_node, action.partner_site, b, sb)) {
                            if (isPopReactant(action.target_node) || isPopReactant(action.partner_node))
                                refuse("bonds involving lumped population reactants are not supported");
                            refuse("invalid endpoints for Unbind");
                        }
                        if (state.bound(a, sa)) state.unbind(a, sa);
                        break;
                    }
                    case ActionKind::Bind: {
                        ParticleId a,b; std::uint16_t sa,sb;
                        if (!resolveEndpoint(action.target_node, action.site, a, sa) ||
                            !resolveEndpoint(action.partner_node, action.partner_site, b, sb)) {
                            if (isPopReactant(action.target_node) || isPopReactant(action.partner_node))
                                refuse("bonds involving lumped population reactants are not supported");
                            refuse("invalid endpoints for Bind");
                        }
                        state.bind(a, sa, b, sb);
                        break;
                    }
                    case ActionKind::Destroy: {
                        if (isPopReactant(action.target_node)) break;
                        try {
                            const auto pid = full_embedding.particle(action.target_node);
                            if (state.alive(pid)) state.destroy(pid);
                        } catch (...) { refuse("invalid embedding for Destroy"); }
                        break;
                    }
                    case ActionKind::DestroyComplex: {
                        if (isPopReactant(action.target_node)) break; // lumped count consumed above
                        try {
                            const auto root = full_embedding.particle(action.target_node);
                            if (state.alive(root)) {
                                state.complexMembers(root, scratchMembers);
                                for (const auto particle : scratchMembers)
                                    if (state.alive(particle)) state.destroy(particle);
                            }
                        } catch (...) { refuse("invalid embedding for DestroyComplex"); }
                        break;
                    }
                    case ActionKind::MovePosition:
                        refuse("MovePosition not supported");
                    }
                }
                for (const auto& action : rule.actions) {
                    if (action.kind == ActionKind::SetCompartment && action.target_node < rule.pattern.nodes.size()) {
                        if (isPopReactant(action.target_node)) refuse("compartment changes on population reactants are not supported");
                        try {
                            const auto pid = full_embedding.particle(action.target_node);
                            if (state.alive(pid)) state.setCompartment(pid, static_cast<CompartmentId>(action.value));
                        } catch (...) {}
                    }
                }

                if (rule.move_connected || has2DCompartment) {
                    for (std::size_t i = 0; i < info.particleReactantNodes.size(); ++i) {
                        ParticleId p{};
                        try { p = full_embedding.particle(info.particleReactantNodes[i]); } catch (...) { continue; }
                        if (!state.alive(p)) continue;
                        const auto sourceComp = beforeCompartments[i];
                        const auto targetComp = state.compartment(p);
                        if (targetComp == sourceComp) continue;
                        if (!rule.move_connected && !is3DSeparatedByHierarchy(sourceComp, targetComp)) continue;
                        std::queue<ParticleId> q;
                        std::set<ParticleId> visited;
                        q.push(p); visited.insert(p);
                        while (!q.empty()) {
                            const auto curr = q.front(); q.pop();
                            const auto& type = model.molecule_types.at(state.type(curr));
                            for (std::size_t s = 0; s < type.sites.size(); ++s) {
                                const auto site = static_cast<std::uint16_t>(s);
                                if (!state.bound(curr, site)) continue;
                                const auto partner = state.bond(curr, site).particle;
                                if (!visited.insert(partner).second) continue;
                                if (!explicitParticles.count(partner) && state.alive(partner) && state.compartment(partner) == sourceComp) {
                                    state.setCompartment(partner, targetComp);
                                    q.push(partner);
                                }
                            }
                        }
                    }
                }

                restoreRetainedPopulations(rule);
                enforceConstantSeeds();
                if (state.liveCount() > request.max_particles) refuse("particle budget exhausted");
                ++output.event_count;
                pending = false;
                continue;
            }
            // Handle rules with simple lumped population molecule creates/destroys in normal path
            // (e.g. particle->population map rules). applyTransformation operates on particle graph
            // and would create population types as particles; convert to lumped counts instead.
            bool hasSimplePopulationActionEffect = false;
            for (const auto& action : rule.actions) {
                if (action.kind == ActionKind::Create &&
                    model.molecule_types.at(action.molecule_type).is_population) {
                    hasSimplePopulationActionEffect = true;
                    break;
                }
                if ((action.kind == ActionKind::Destroy || action.kind == ActionKind::DestroyComplex) &&
                    action.target_node < rule.pattern.nodes.size() &&
                    model.molecule_types.at(rule.pattern.nodes[action.target_node].molecule_type).is_population) {
                    // simple standalone pop reactant consumed in a rule not classified as pop-only/mixed-lumped
                    hasSimplePopulationActionEffect = true;
                    break;
                }
            }
            if (hasSimplePopulationActionEffect) {
                MatchEmbedding match_embedding;
                for (std::size_t node = 0; node < selected_match.particles().size(); ++node) {
                    match_embedding.bindNode(node, selected_match.particle(node));
                }
                if (selected_match.hasSiteMaps()) {
                    match_embedding.setSiteMaps(selected_match.siteMaps());
                }

                // Manual action interpretation with lumped population handling.
                std::map<PatternNodeId, CreatedMoleculeId> node_to_created;
                std::map<PatternNodeId, TypeId> created_types;
                std::map<PatternNodeId, std::vector<std::pair<std::uint32_t, std::int32_t>>> created_states;
                std::map<PatternNodeId, CompartmentId> created_compartments;
                CreatedMoleculeId next_created = 0;
                for (const auto& action : rule.actions) {
                    if (action.kind == ActionKind::Create) {
                        if (!node_to_created.count(action.target_node)) {
                            node_to_created[action.target_node] = next_created++;
                            created_types[action.target_node] = action.molecule_type;
                        }
                    } else if (action.kind == ActionKind::SetSiteState && action.target_node >= rule.pattern.nodes.size()) {
                        created_states[action.target_node].push_back({action.site, action.value});
                    } else if (action.kind == ActionKind::SetCompartment && action.target_node >= rule.pattern.nodes.size()) {
                        created_compartments[action.target_node] = static_cast<CompartmentId>(action.value);
                    }
                }
                for (const auto& [createdNode, donorNode] : rule.created_compartment_inherit) {
                    if (!created_compartments.count(createdNode) &&
                        donorNode < selected_match.particles().size()) {
                        const auto dp = selected_match.particle(donorNode);
                        if (state.alive(dp)) created_compartments[createdNode] = state.compartment(dp);
                    }
                }
                std::map<CreatedMoleculeId, ParticleId> created_particles;
                for (const auto& [node, cid] : node_to_created) {
                    const TypeId type = created_types[node];
                    if (model.molecule_types.at(type).is_population) {
                        if (created_states.count(node)) refuse("stateful population products are not supported");
                        const auto location = created_compartments.find(node);
                        incrementPopulation(
                            {type, location == created_compartments.end()
                                       ? std::nullopt
                                       : std::make_optional(location->second)},
                            1);
                        continue;
                    }
                    CompartmentId comp = 0;
                    auto cit = created_compartments.find(node);
                    if (cit != created_compartments.end()) comp = cit->second;
                    const auto pid = state.create(type, comp);
                    created_particles[cid] = pid;
                    auto sit = created_states.find(node);
                    if (sit != created_states.end()) {
                        for (const auto& [site, val] : sit->second)
                            state.setSiteState(pid, static_cast<std::uint16_t>(site), val);
                    }
                }

                auto isPopReactantType = [&](PatternNodeId node) {
                    return node < rule.pattern.nodes.size() &&
                           model.molecule_types.at(rule.pattern.nodes[node].molecule_type).is_population;
                };
                auto resolveEndpoint = [&](PatternNodeId node, std::uint16_t site, ParticleId& pid, std::uint16_t& outSite) -> bool {
                    if (node < rule.pattern.nodes.size()) {
                        if (isPopReactantType(node)) return false;
                        try { pid = match_embedding.particle(node); } catch (...) { return false; }
                        outSite = match_embedding.mappedSite(node, site);
                        return state.alive(pid);
                    }
                    auto it = node_to_created.find(node);
                    if (it == node_to_created.end()) return false;
                    auto pit = created_particles.find(it->second);
                    if (pit == created_particles.end()) return false;
                    pid = pit->second;
                    outSite = site;
                    return state.alive(pid);
                };

                for (const auto& action : rule.actions) {
                    switch (action.kind) {
                    case ActionKind::Create:
                    case ActionKind::SetCompartment:
                        break;
                    case ActionKind::SetSiteState: {
                        if (action.target_node < rule.pattern.nodes.size()) {
                            if (isPopReactantType(action.target_node)) refuse("state changes on population reactants are not supported");
                            try {
                                const auto pid = match_embedding.particle(action.target_node);
                                const auto mapped = match_embedding.mappedSite(action.target_node, action.site);
                                if (state.alive(pid)) state.setSiteState(pid, mapped, action.value);
                            } catch (...) { refuse("invalid embedding for SetSiteState"); }
                        } else {
                            auto it = node_to_created.find(action.target_node);
                            if (it != node_to_created.end()) {
                                auto pit = created_particles.find(it->second);
                                if (pit != created_particles.end() && state.alive(pit->second))
                                    state.setSiteState(pit->second, action.site, action.value);
                            }
                        }
                        break;
                    }
                    case ActionKind::Unbind: {
                        ParticleId a,b; std::uint16_t sa,sb;
                        if (!resolveEndpoint(action.target_node, action.site, a, sa) ||
                            !resolveEndpoint(action.partner_node, action.partner_site, b, sb)) {
                            refuse("invalid endpoints for Unbind in lumped-population rule");
                        }
                        if (state.bound(a, sa)) state.unbind(a, sa);
                        break;
                    }
                    case ActionKind::Bind: {
                        ParticleId a,b; std::uint16_t sa,sb;
                        if (!resolveEndpoint(action.target_node, action.site, a, sa) ||
                            !resolveEndpoint(action.partner_node, action.partner_site, b, sb)) {
                            refuse("invalid endpoints for Bind in lumped-population rule");
                        }
                        state.bind(a, sa, b, sb);
                        break;
                    }
                    case ActionKind::Destroy: {
                        if (action.target_node < rule.pattern.nodes.size() &&
                            model.molecule_types.at(rule.pattern.nodes[action.target_node].molecule_type).is_population) {
                            const auto key = location(rule.pattern.nodes[action.target_node]);
                            if (populationCount(key) == 0) refuse("population underflow");
                            --population_counts.at(key);
                            break;
                        }
                        try {
                            const auto pid = match_embedding.particle(action.target_node);
                            if (state.alive(pid)) state.destroy(pid);
                        } catch (...) { refuse("invalid embedding for Destroy"); }
                        break;
                    }
                    case ActionKind::DestroyComplex: {
                        if (action.target_node < rule.pattern.nodes.size() &&
                            model.molecule_types.at(rule.pattern.nodes[action.target_node].molecule_type).is_population) {
                            const auto key = location(rule.pattern.nodes[action.target_node]);
                            if (populationCount(key) == 0) refuse("population underflow");
                            --population_counts.at(key);
                            break;
                        }
                        try {
                            const auto root = match_embedding.particle(action.target_node);
                            if (state.alive(root)) {
                                state.complexMembers(root, scratchMembers);
                                for (const auto particle : scratchMembers)
                                    if (state.alive(particle)) state.destroy(particle);
                            }
                        } catch (...) { refuse("invalid embedding for DestroyComplex"); }
                        break;
                    }
                    case ActionKind::MovePosition:
                        refuse("MovePosition not supported");
                    }
                }
                for (const auto& action : rule.actions) {
                    if (action.kind == ActionKind::SetCompartment && action.target_node < rule.pattern.nodes.size()) {
                        if (isPopReactantType(action.target_node)) refuse("compartment changes on population reactants are not supported");
                        try {
                            const auto pid = match_embedding.particle(action.target_node);
                            if (state.alive(pid)) state.setCompartment(pid, static_cast<CompartmentId>(action.value));
                        } catch (...) {}
                    }
                }
                if (rule.move_connected) refuse("move_connected with lumped population actions not yet supported");

                enforceConstantSeeds();
                if (state.liveCount() > request.max_particles) refuse("particle budget exhausted");
                ++output.event_count;
                pending = false;
                continue;
            }

            std::vector<CompartmentId> beforeCompartments;
            std::set<ParticleId> explicitParticles;
            if (rule.move_connected || has2DCompartment) {
                beforeCompartments.reserve(selected_match.particles().size());
                for (const auto& p : selected_match.particles()) {
                    beforeCompartments.push_back(state.compartment(p));
                    explicitParticles.insert(p);
                }
            }
            // NFN-09a: Capture donor compartments for created molecules BEFORE transformation.
            std::vector<std::pair<CreatedMoleculeId, CompartmentId>> inheritedCompartments;
            if (!rule.created_compartment_inherit.empty()) {
                inheritedCompartments.reserve(rule.created_compartment_inherit.size());
                for (const auto& [createdNode, donorNode] : rule.created_compartment_inherit) {
                    const auto cidIt = ruleCreatedIds[selected_rule].find(createdNode);
                    if (cidIt != ruleCreatedIds[selected_rule].end() &&
                        donorNode < selected_match.particles().size()) {
                        inheritedCompartments.emplace_back(
                            cidIt->second, state.compartment(selected_match.particle(donorNode)));
                    }
                }
            }

            MatchEmbedding match_embedding;
            for (std::size_t node = 0; node < selected_match.particles().size(); ++node) {
                match_embedding.bindNode(node, selected_match.particle(node));
            }
            if (selected_match.hasSiteMaps()) {
                match_embedding.setSiteMaps(selected_match.siteMaps());
            }
            const auto txResult = applyTransformation(
                compiled_transformations[selected_rule], match_embedding, state);

            for (const auto& [cid, comp] : inheritedCompartments) {
                const auto createdPid = txResult.created(cid);
                if (state.alive(createdPid)) state.setCompartment(createdPid, comp);
            }

            for (const auto& action : rule.actions) {
                if (action.kind == ActionKind::SetCompartment) {
                    if (action.target_node < selected_match.particles().size()) {
                        const auto p = selected_match.particle(action.target_node);
                        if (state.alive(p)) {
                            state.setCompartment(p, static_cast<CompartmentId>(action.value));
                        }
                    }
                }
            }

            // NFN-09b: Propagate compartment transport to connected cargo when MoveConnected
            // is requested OR when transporting across a 2D membrane separating two 3D volumes.
            if (rule.move_connected || has2DCompartment) {
                for (std::size_t node = 0; node < selected_match.particles().size(); ++node) {
                    const auto p = selected_match.particle(node);
                    if (!state.alive(p)) continue;
                    const auto sourceComp = beforeCompartments[node];
                    const auto targetComp = state.compartment(p);
                    if (targetComp == sourceComp) continue;
                    if (!rule.move_connected && !is3DSeparatedByHierarchy(sourceComp, targetComp)) continue;
                    std::queue<ParticleId> q;
                    std::set<ParticleId> visited;
                    q.push(p);
                    visited.insert(p);
                    while (!q.empty()) {
                        const auto curr = q.front();
                        q.pop();
                        const auto& type = model.molecule_types.at(state.type(curr));
                        for (std::size_t s = 0; s < type.sites.size(); ++s) {
                            const auto site = static_cast<std::uint16_t>(s);
                            if (state.bound(curr, site)) {
                                const auto partner = state.bond(curr, site).particle;
                                if (visited.insert(partner).second) {
                                    if (!explicitParticles.count(partner)) {
                                        if (state.compartment(partner) == sourceComp) {
                                            state.setCompartment(partner, targetComp);
                                            q.push(partner);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            enforceConstantSeeds();
            if (state.liveCount() > request.max_particles) refuse("particle budget exhausted");
            ++output.event_count;
            pending = false;
        }
        std::vector<double> row{sample};
        for (const auto& obs : observables)
            row.push_back(evaluateObservable(obs));
        output.rows.push_back(std::move(row));
    }
    if (modelOwner) {
        output.final_state = std::make_shared<BngExecutionState>(BngExecutionState{
            std::move(modelOwner), std::move(state), std::move(population_counts),
            std::move(compartmentalized_populations), request.sample_times.back(), seed, stream});
    }
    return output;
}

std::string formatFinalSpecies(const BngExecutionState& state) {
    if (!state.model) return {};
    const auto& model = *state.model;
    const auto& graph = state.graph;

    std::map<std::uint32_t, std::vector<ParticleId>> complexes;
    for (const auto p : graph.liveParticles()) {
        complexes[graph.complexId(p)].push_back(p);
    }

    const auto compartmentName = [&](CompartmentId cid) -> std::string {
        if (cid < model.compartments.size()) return model.compartments[cid].name;
        return {};
    };

    auto siteStateString = [&](ParticleId p, std::size_t si) -> std::string {
        const auto& type = model.molecule_types.at(graph.type(p));
        if (si >= type.sites.size() || type.sites[si].states.empty()) return {};
        const auto st = graph.siteState(p, static_cast<std::uint16_t>(si));
        if (st >= 0 && static_cast<std::size_t>(st) < type.sites[si].states.size()) {
            return type.sites[si].states[static_cast<std::size_t>(st)];
        }
        return {};
    };

    // NFN-15: Canonicalize complex molecule order & duplicate-site order via
    // Weisfeiler-Lehman color refinement + exact tie-breaking so isomorphic
    // species always format identically and merge into one .species line.
    std::map<std::string, std::uint64_t> speciesCounts;
    for (auto& complexEntry : complexes) {
        auto& members = complexEntry.second;
        const std::size_t k = members.size();
        if (k == 0) continue;
        std::unordered_map<std::uint32_t, std::size_t> slotToLocal;
        slotToLocal.reserve(k * 2);
        for (std::size_t i = 0; i < k; ++i) slotToLocal[members[i].index] = i;

        auto formatOrder = [&](const std::vector<std::size_t>& order) -> std::string {
            std::vector<std::size_t> posOf(k, k);
            for (std::size_t pos = 0; pos < k; ++pos) posOf[order[pos]] = pos;

            using EndpointKey = std::pair<std::uint32_t, std::uint16_t>;
            std::map<std::pair<EndpointKey, EndpointKey>, std::size_t> bondIds;
            std::size_t nextBond = 1;
            auto bondIdFor = [&](ParticleId a, std::uint16_t sa, ParticleId b, std::uint16_t sb) {
                EndpointKey k1{a.index, sa};
                EndpointKey k2{b.index, sb};
                if (k2 < k1) std::swap(k1, k2);
                auto [it, inserted] = bondIds.emplace(std::make_pair(k1, k2), nextBond);
                if (inserted) ++nextBond;
                return it->second;
            };

            std::ostringstream complexText;
            for (std::size_t pos = 0; pos < k; ++pos) {
                if (pos != 0) complexText << '.';
                const auto p = members[order[pos]];
                const auto& type = model.molecule_types.at(graph.type(p));
                // Group sites by name preserving declaration order of distinct names,
                // and sort duplicate-named sites canonically.
                std::vector<std::string> nameOrder;
                std::map<std::string, std::vector<std::size_t>> byName;
                for (std::size_t si = 0; si < type.sites.size(); ++si) {
                    const auto& sname = type.sites[si].name;
                    if (!byName.count(sname)) nameOrder.push_back(sname);
                    byName[sname].push_back(si);
                }
                std::vector<std::size_t> siteOrder;
                siteOrder.reserve(type.sites.size());
                for (const auto& sname : nameOrder) {
                    auto& group = byName[sname];
                    if (group.size() > 1) {
                        std::sort(group.begin(), group.end(), [&](std::size_t a, std::size_t b) {
                            const auto sa = siteStateString(p, a);
                            const auto sb = siteStateString(p, b);
                            if (sa != sb) return sa < sb;
                            const bool ba = graph.bound(p, static_cast<std::uint16_t>(a));
                            const bool bb = graph.bound(p, static_cast<std::uint16_t>(b));
                            if (ba != bb) return ba < bb;
                            if (ba && bb) {
                                const auto pa = graph.bond(p, static_cast<std::uint16_t>(a));
                                const auto pb = graph.bond(p, static_cast<std::uint16_t>(b));
                                const auto posA = posOf[slotToLocal.at(pa.particle.index)];
                                const auto posB = posOf[slotToLocal.at(pb.particle.index)];
                                if (posA != posB) return posA < posB;
                                const auto& tpa = model.molecule_types.at(graph.type(pa.particle));
                                const auto& tpb = model.molecule_types.at(graph.type(pb.particle));
                                const std::string psa = pa.site < tpa.sites.size() ? tpa.sites[pa.site].name : "";
                                const std::string psb = pb.site < tpb.sites.size() ? tpb.sites[pb.site].name : "";
                                if (psa != psb) return psa < psb;
                            }
                            return a < b;
                        });
                    }
                    for (const auto si : group) siteOrder.push_back(si);
                }

                complexText << type.name << '(';
                for (std::size_t oi = 0; oi < siteOrder.size(); ++oi) {
                    if (oi != 0) complexText << ',';
                    const std::size_t si = siteOrder[oi];
                    const auto site = static_cast<std::uint16_t>(si);
                    complexText << type.sites[si].name;
                    const auto stStr = siteStateString(p, si);
                    if (!stStr.empty()) complexText << '~' << stStr;
                    if (graph.bound(p, site)) {
                        const auto partner = graph.bond(p, site);
                        complexText << '!' << bondIdFor(p, site, partner.particle, partner.site);
                    }
                }
                complexText << ')';
                if (!model.compartments.empty()) {
                    const auto cname = compartmentName(graph.compartment(p));
                    if (!cname.empty()) complexText << '@' << cname;
                }
            }
            return complexText.str();
        };

        if (k == 1) {
            ++speciesCounts[formatOrder({0})];
            continue;
        }

        // Initial local color per molecule (invariant under ParticleId and duplicate-site order).
        std::vector<std::string> color(k);
        for (std::size_t i = 0; i < k; ++i) {
            const auto p = members[i];
            const auto& type = model.molecule_types.at(graph.type(p));
            std::vector<std::string> siteTokens;
            siteTokens.reserve(type.sites.size());
            for (std::size_t si = 0; si < type.sites.size(); ++si) {
                std::string tok = type.sites[si].name;
                const auto stStr = siteStateString(p, si);
                if (!stStr.empty()) tok += "~" + stStr;
                tok += graph.bound(p, static_cast<std::uint16_t>(si)) ? "!1" : "!0";
                siteTokens.push_back(std::move(tok));
            }
            std::sort(siteTokens.begin(), siteTokens.end());
            std::ostringstream sig;
            sig << type.name;
            if (!model.compartments.empty()) sig << '@' << compartmentName(graph.compartment(p));
            sig << '(';
            for (std::size_t si = 0; si < siteTokens.size(); ++si) {
                if (si != 0) sig << ',';
                sig << siteTokens[si];
            }
            sig << ')';
            color[i] = sig.str();
        }

        std::vector<std::size_t> rank(k, 0);
        auto compressColors = [&]() {
            std::vector<std::string> sortedUnique = color;
            std::sort(sortedUnique.begin(), sortedUnique.end());
            sortedUnique.erase(std::unique(sortedUnique.begin(), sortedUnique.end()), sortedUnique.end());
            for (std::size_t i = 0; i < k; ++i) {
                rank[i] = static_cast<std::size_t>(
                    std::lower_bound(sortedUnique.begin(), sortedUnique.end(), color[i]) -
                    sortedUnique.begin());
            }
        };
        compressColors();
        for (int round = 0; round < 3; ++round) {
            std::vector<std::string> nextColor(k);
            for (std::size_t i = 0; i < k; ++i) {
                const auto p = members[i];
                const auto& type = model.molecule_types.at(graph.type(p));
                std::vector<std::string> nbTokens;
                for (std::size_t si = 0; si < type.sites.size(); ++si) {
                    const auto site = static_cast<std::uint16_t>(si);
                    if (!graph.bound(p, site)) continue;
                    const auto partner = graph.bond(p, site);
                    const auto nb = slotToLocal.at(partner.particle.index);
                    const auto& nbType = model.molecule_types.at(graph.type(partner.particle));
                    std::ostringstream nt;
                    nt << type.sites[si].name << '~' << siteStateString(p, si) << '-'
                       << (partner.site < nbType.sites.size() ? nbType.sites[partner.site].name : "")
                       << ':' << rank[nb];
                    nbTokens.push_back(nt.str());
                }
                std::sort(nbTokens.begin(), nbTokens.end());
                std::ostringstream nc;
                nc << rank[i] << '|';
                for (const auto& t : nbTokens) nc << t << ';';
                nextColor[i] = nc.str();
            }
            color = std::move(nextColor);
            compressColors();
        }

        std::vector<std::size_t> baseOrder(k);
        for (std::size_t i = 0; i < k; ++i) baseOrder[i] = i;
        std::sort(baseOrder.begin(), baseOrder.end(), [&](std::size_t a, std::size_t b) {
            if (rank[a] != rank[b]) return rank[a] < rank[b];
            return a < b;
        });

        // Partition into tied rank groups and count exact within-group permutations.
        std::vector<std::pair<std::size_t, std::size_t>> groups;
        std::size_t permBudget = 1;
        for (std::size_t i = 0; i < k;) {
            std::size_t j = i + 1;
            while (j < k && rank[baseOrder[j]] == rank[baseOrder[i]]) ++j;
            groups.emplace_back(i, j);
            const std::size_t gSize = j - i;
            for (std::size_t f = 2; f <= gSize && permBudget <= 64; ++f) permBudget *= f;
            i = j;
        }

        std::string best;
        if (permBudget <= 64) {
            std::vector<std::size_t> cur = baseOrder;
            std::function<void(std::size_t)> enumGroups = [&](std::size_t gIdx) {
                if (gIdx == groups.size()) {
                    std::string formatted = formatOrder(cur);
                    if (best.empty() || formatted < best) best = std::move(formatted);
                    return;
                }
                const auto [gs, ge] = groups[gIdx];
                if (ge - gs <= 1) {
                    enumGroups(gIdx + 1);
                    return;
                }
                std::sort(cur.begin() + static_cast<std::ptrdiff_t>(gs),
                          cur.begin() + static_cast<std::ptrdiff_t>(ge));
                do {
                    enumGroups(gIdx + 1);
                } while (std::next_permutation(cur.begin() + static_cast<std::ptrdiff_t>(gs),
                                               cur.begin() + static_cast<std::ptrdiff_t>(ge)));
            };
            enumGroups(0);
        } else {
            // Large symmetric polymer: canonical BFS from up to 16 rank-0 roots.
            const auto [g0s, g0e] = groups.front();
            const std::size_t rootLimit = std::min<std::size_t>(g0e - g0s, 16);
            for (std::size_t ri = 0; ri < rootLimit; ++ri) {
                const std::size_t root = baseOrder[g0s + ri];
                std::vector<std::uint8_t> visited(k, 0);
                std::vector<std::size_t> order;
                order.reserve(k);
                visited[root] = 1;
                order.push_back(root);
                for (std::size_t head = 0; head < order.size(); ++head) {
                    const std::size_t u = order[head];
                    const auto p = members[u];
                    const auto& type = model.molecule_types.at(graph.type(p));
                    struct EdgeCand {
                        std::size_t nbRank;
                        std::string mySite;
                        std::string nbSite;
                        std::size_t nb;
                    };
                    std::vector<EdgeCand> cands;
                    for (std::size_t si = 0; si < type.sites.size(); ++si) {
                        const auto site = static_cast<std::uint16_t>(si);
                        if (!graph.bound(p, site)) continue;
                        const auto partner = graph.bond(p, site);
                        const auto nb = slotToLocal.at(partner.particle.index);
                        if (visited[nb]) continue;
                        const auto& nbType = model.molecule_types.at(graph.type(partner.particle));
                        cands.push_back({
                            rank[nb], type.sites[si].name,
                            partner.site < nbType.sites.size() ? nbType.sites[partner.site].name : "",
                            nb
                        });
                    }
                    std::sort(cands.begin(), cands.end(), [](const EdgeCand& a, const EdgeCand& b) {
                        return std::tie(a.nbRank, a.mySite, a.nbSite, a.nb) <
                               std::tie(b.nbRank, b.mySite, b.nbSite, b.nb);
                    });
                    for (const auto& c : cands) {
                        if (!visited[c.nb]) {
                            visited[c.nb] = 1;
                            order.push_back(c.nb);
                        }
                    }
                }
                for (const auto idx : baseOrder) {
                    if (!visited[idx]) {
                        visited[idx] = 1;
                        order.push_back(idx);
                    }
                }
                std::string formatted = formatOrder(order);
                if (best.empty() || formatted < best) best = std::move(formatted);
            }
        }
        ++speciesCounts[best];
    }

    for (const auto& [loc, count] : state.populations) {
        if (count == 0) continue;
        const auto& type = model.molecule_types.at(loc.first);
        std::string label;
        if (loc.second.has_value()) {
            const auto cname = compartmentName(*loc.second);
            if (!cname.empty()) label = "@" + cname + "::";
        }
        label += type.name + "()";
        speciesCounts[label] += count;
    }

    std::ostringstream out;
    for (const auto& [species, count] : speciesCounts) {
        out << species << ' ' << count << '\n';
    }
    return out.str();
}

} // namespace nfnext
