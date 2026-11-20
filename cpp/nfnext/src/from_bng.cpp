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
#include <functional>
#include <limits>
#include <map>
#include <optional>
#include <queue>
#include <set>
#include <sstream>
#include <tuple>
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
        case Binary::Power: return std::pow(*left, *right);
        case Binary::Less: return *left < *right ? 1.0 : 0.0;
        case Binary::LessEqual: return *left <= *right ? 1.0 : 0.0;
        case Binary::Greater: return *left > *right ? 1.0 : 0.0;
        case Binary::GreaterEqual: return *left >= *right ? 1.0 : 0.0;
        case Binary::Equal: return *left == *right ? 1.0 : 0.0;
        case Binary::NotEqual: return *left != *right ? 1.0 : 0.0;
        case Binary::LogicalAnd: return (*left != 0.0 && *right != 0.0) ? 1.0 : 0.0;
        case Binary::LogicalOr: return (*left != 0.0 || *right != 0.0) ? 1.0 : 0.0;
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
    if (const auto value = constantExpression(ep.expression, source)) return *value;
    return 0.0;
}

// A dynamic energy factor has no static value. Its expression must be
// evaluated against runtime state instead of being folded into a constant
// rate; folding it to zero would silently change the model semantics.
bool isDynamicEnergyFactor(const bng::compile::CompiledEnergyFactor& ep,
                           const bng::compile::CompiledModel& source) {
    return !ep.evaluatedValue && !constantExpression(ep.expression, source);
}

std::optional<std::string> observableRateExpression(
    const bng::compile::ResolvedExpression& expression,
    const bng::compile::CompiledModel& model,
    std::set<std::size_t>& observableIds) {
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
            observable->kind != bng::compile::ObservableKind::Molecules)
            return std::nullopt;
        observableIds.insert(index);
        return "observable_" + std::to_string(index);
    }
    case Kind::Unary: {
        if (!expression.unaryOp || expression.arguments.size() != 1 ||
            (*expression.unaryOp != Unary::Plus &&
             *expression.unaryOp != Unary::Negate))
            return std::nullopt;
        const auto child = observableRateExpression(
            expression.arguments.front(), model, observableIds);
        if (!child) return std::nullopt;
        return *expression.unaryOp == Unary::Negate
            ? "(-" + *child + ")" : "(" + *child + ")";
    }
    case Kind::Binary: {
        if (!expression.binaryOp || expression.arguments.size() != 2)
            return std::nullopt;
        const char* operation = nullptr;
        switch (*expression.binaryOp) {
        case Binary::Add: operation = "+"; break;
        case Binary::Subtract: operation = "-"; break;
        case Binary::Multiply: operation = "*"; break;
        case Binary::Divide: operation = "/"; break;
        case Binary::Power: operation = "^"; break;
        default: return std::nullopt;
        }
        const auto left = observableRateExpression(
            expression.arguments[0], model, observableIds);
        const auto right = observableRateExpression(
            expression.arguments[1], model, observableIds);
        if (!left || !right) return std::nullopt;
        return "(" + *left + operation + *right + ")";
    }
    case Kind::BuiltinCall: {
        if (!expression.builtin) return std::nullopt;
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
            const auto child = observableRateExpression(argument, model, observableIds);
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

struct FlattenedPattern {
    PatternIR pattern;
    std::vector<std::size_t> patternOffsets;
};

bool appendPattern(const BngPattern& source, PatternIR& destination,
                   BngLoweringResult& result, const std::string& entity,
                   std::size_t& firstNode,
                   bool unspecifiedBondIsUnbound = false) {
    if (!source.isResolved()) {
        issue(result, BngLoweringSeverity::Error, entity,
              "pattern is not fully symbol-resolved");
        return false;
    }
    std::optional<CompartmentId> patternCompId;
    if (source.compartmentId().has_value()) {
        patternCompId = static_cast<CompartmentId>(source.compartmentId()->value());
    }
    firstNode = destination.nodes.size();
    std::map<std::size_t, std::vector<std::pair<std::size_t, std::uint32_t>>> exactBonds;
    for (const auto& molecule : source.molecules()) {
        if (!molecule.moleculeTypeId) {
            issue(result, BngLoweringSeverity::Error, entity, "pattern molecule has no typed molecule ID");
            return false;
        }
        const auto node = destination.addNode(static_cast<TypeId>(molecule.moleculeTypeId->value()));
        std::optional<CompartmentId> molCompId = molecule.compartmentId.has_value()
            ? std::optional<CompartmentId>(static_cast<CompartmentId>(molecule.compartmentId->value()))
            : patternCompId;
        destination.node(node).compartment = molCompId;
        for (const auto& site : molecule.sites) {
            if (!site.componentType) {
                issue(result, BngLoweringSeverity::Error, entity, "pattern site has no typed component ID");
                return false;
            }
            const auto siteIndex = static_cast<std::uint32_t>(site.componentType->index);
            const auto& state = site.stateConstraintResolved;
            if (state.kind == bng::compile::StateConstraintKind::Exact) {
                if (!state.exact) {
                    issue(result, BngLoweringSeverity::Error, entity, "exact state constraint has no state ID");
                    return false;
                }
                destination.node(node).siteState(siteIndex, static_cast<std::int32_t>(state.exact->index));
            } else if (state.kind == bng::compile::StateConstraintKind::Set) {
                std::vector<std::int32_t> states;
                for (const auto& value : state.states) states.push_back(static_cast<std::int32_t>(value.index));
                if (states.empty()) {
                    issue(result, BngLoweringSeverity::Error, entity, "empty state-set constraint");
                    return false;
                }
                destination.node(node).siteStateSet(siteIndex, std::move(states));
            }

            const auto bonds = site.bondConstraints.empty()
                ? std::vector<bng::compile::PatternBondDescriptor>{
                      {site.bondConstraint, site.bondKind, site.bondGroup}}
                : site.bondConstraints;
            for (const auto& bond : bonds) {
                switch (bond.kind) {
                case bng::compile::BondConstraintKind::Unspecified:
                    // BNG2 treats a listed site with no bond notation as
                    // unbound (the observable A(b) counts only free A), and
                    // PatternLowering defaults Unspecified to UNBOUND. Scope
                    // that correction to observables here so other lowered
                    // pattern kinds keep their established constraints.
                    if (unspecifiedBondIsUnbound)
                        destination.node(node).siteFree(siteIndex);
                    break;
                case bng::compile::BondConstraintKind::Any:
                    break;
                case bng::compile::BondConstraintKind::Unbound:
                    destination.node(node).siteFree(siteIndex);
                    break;
                case bng::compile::BondConstraintKind::Bound:
                    destination.node(node).siteBound(siteIndex);
                    break;
                case bng::compile::BondConstraintKind::Exact:
                    exactBonds[bond.group.value].push_back({node, siteIndex});
                    break;
                }
            }
        }
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
    const std::string& entity, bool unspecifiedBondIsUnbound = false) {
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
                           unspecifiedBondIsUnbound))
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
    const DirectionNodeMap& nodes,
    std::vector<ActionIR>& actions,
    BngLoweringResult& result,
    const std::string& entity) {
    for (const auto& key : nodes.createdProducts) {
        if (key.first >= direction.productPatterns.size() ||
            key.second >= direction.productPatterns[key.first].molecules().size()) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "created molecule occurrence is outside the product pattern");
            return false;
        }
        const auto& molecule = direction.productPatterns[key.first].molecules()[key.second];
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

        const auto compId = molecule.compartmentId ? molecule.compartmentId : direction.productPatterns[key.first].compartmentId();
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
                const FlattenedPattern& pattern,
                bool reverseDirection,
                std::vector<ActionIR>& actions,
                BngLoweringResult& result, const std::string& entity) {
    if (!direction.transformationsComplete) {
        issue(result, BngLoweringSeverity::Error, entity,
              "compiled rule transformation program is incomplete");
        return false;
    }

    const auto nodes = buildDirectionNodeMap(
        rule, direction, pattern, reverseDirection, result, entity);
    if (!nodes) return false;
    if (!appendCreateActions(direction, *nodes, actions, result, entity)) return false;

    const bool deleteMolecules = hasDeleteMoleculesModifier(rule);
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
            actions.push_back(std::move(action));
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
        const auto prodComp = prodMol.compartmentId ? prodMol.compartmentId : prodPattern.compartmentId();
        const auto reactComp = reactMol.compartmentId ? reactMol.compartmentId : reactPattern.compartmentId();
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
        key.push_back(static_cast<int>(node(action.partner_node)));
        key.push_back(static_cast<int>(action.partner_site));
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
    const auto flattened = flattenReactants(direction.reactantPatterns, result, entity);
    if (!flattened) return;

    // Lower filters into NFIR FilterIR. Filters constrain rule applicability
    // by requiring or excluding species matching specific patterns in the
    // reactant or product set. The filter patterns are lowered to PatternIR.
    std::vector<FilterIR> loweredFilters;
    if (!direction.filters.empty()) {
        loweredFilters.reserve(direction.filters.size());
        for (const auto& filter : direction.filters) {
            FilterIR irFilter;
            irFilter.include = filter.include;
            irFilter.products = filter.products;
            irFilter.pattern_index = filter.patternIndex;
            irFilter.reactant_node_offset = (filter.patternIndex < flattened->patternOffsets.size())
                ? flattened->patternOffsets[filter.patternIndex]
                : 0;
            irFilter.patterns.reserve(filter.patterns.size());
            for (const auto& pattern : filter.patterns) {
                BngLoweringResult filterValidation;
                const auto loweredPattern = flattenReactants({pattern}, filterValidation, entity);
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
    if (!addActions(rule, direction, *flattened, reverseDirection,
                    loweredActions, result, entity)) return;

    // Whole-species deletions have no identity-sensitive action. Other rules
    // qualify when exchanging the duplicate reactants leaves the action
    // program unchanged (e.g. a symmetric A+A -> A.A binding, but not
    // A+A -> A(p)+A(u)). The whole pattern is compared first, so distinct
    // state or bond constraints never share a symmetry group. BNG2 applies
    // the same 1/n! combinatorial factor to identical reactants.
    const bool wholeDeletionSymmetry =
        !hasDeleteMoleculesModifier(rule) &&
        direction.wholeSpeciesDeletions.size() == direction.reactantPatterns.size();
    if (!hasDeleteMoleculesModifier(rule) && direction.filters.empty() &&
        direction.localScopes.empty()) {
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
            if (!wholeDeletionSymmetry) {
                bool allExchangesSymmetric = true;
                for (std::size_t dupIdx = 1; dupIdx < duplicates.size(); ++dupIdx) {
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
                if (!allExchangesSymmetric) continue;
            }
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
    if (energyModulatedArrhenius && !expandableEnergyStateChange) {
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
            *expandedRate, source, observableIds);
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
                        volumeFactor = comp->volume;
                    }
                }
            }
        } else if (direction.reactantPatterns.size() >= 2) {
            std::vector<bng::compile::ReactantCompartment> rcList;
            for (const auto& rPat : direction.reactantPatterns) {
                auto rCompId = rPat.compartmentId();
                if (!rCompId && !rPat.molecules().empty()) rCompId = rPat.molecules().front().compartmentId;
                if (rCompId) {
                    const auto* comp = source.compartment(*rCompId);
                    if (comp && std::isfinite(comp->volume) && comp->volume > 0.0) {
                        rcList.push_back({comp->dimension, comp->volume});
                    }
                }
            }
            const auto factor = bng::compile::reactantUnitConversionFactor(rcList);
            if (factor) {
                volumeFactor = *factor;
            }
        }
    }
    lowered.volume_factor = volumeFactor;

    if (direction.rateLaw && direction.rateLaw->unit.has_value()) {
        if (!constant || lowered.rate_law.kind != RateLawKind::Elementary) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "physical unit rate conversion requires a constant elementary rate in NFnext");
            return;
        }
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
            if (!direction.productPatterns.empty()) {
                const auto& prod = direction.productPatterns.front();
                pCompId = prod.compartmentId();
                if (!pCompId && !prod.molecules().empty()) pCompId = prod.molecules().front().compartmentId;
            }
            if (!pCompId) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "physical zero-order rate requires one declared product compartment");
                return;
            }
            const auto* decl = source.compartment(*pCompId);
            if (!decl || decl->volumeTimeDependent || !decl->declaredUnit.has_value() ||
                !std::isfinite(decl->volume) || decl->volume <= 0.0) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "physical zero-order rate requires a static declared product volume unit");
                return;
            }
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
            const auto conversion = bng::units::stochasticRateFactor(*direction.rateLaw->unit, 1, context);
            if (!conversion || !conversion.factor.has_value() || !std::isfinite(*conversion.factor) ||
                *conversion.factor < 0.0) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "physical unimolecular rate unit cannot be converted to a count rate");
                return;
            }
            lowered.rate = *constant * *conversion.factor;
            // geometric volume factor (usually 1) retained
        } else if (molecularity == 2) {
            const auto& rPat = direction.reactantPatterns.front();
            auto rCompId = rPat.compartmentId();
            if (!rCompId && !rPat.molecules().empty()) rCompId = rPat.molecules().front().compartmentId;
            const auto* decl = rCompId ? source.compartment(*rCompId) : nullptr;
            if (!decl || !decl->declaredUnit.has_value()) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "physical bimolecular rate requires one declared reactant volume unit");
                return;
            }
            // The physical rate k [M^-1 s^-1] must become a count-rate
            // coefficient k / (N_A * V). stochasticRateFactor with a unit
            // compartment volume supplies the mole/item bridge and the
            // declared-volume basis (1 / (N_A * 1 volume unit)); the geometric
            // reactant compartment factor computed above supplies 1 / V.
            // Both are required: dropping either leaves the propensity wrong.
            context.compartmentVolume = 1.0;
            context.volumeUnit = decl->declaredUnit;
            const auto conversion = bng::units::stochasticRateFactor(
                *direction.rateLaw->unit, 2, context);
            if (!conversion || !conversion.factor.has_value() ||
                !std::isfinite(*conversion.factor) || *conversion.factor < 0.0) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "physical bimolecular rate unit cannot be converted to a count rate");
                return;
            }
            lowered.rate = *constant * (*conversion.factor);
        } else {
            issue(result, BngLoweringSeverity::Error, entity,
                  "physical rate conversion for molecularity > 2 is not yet supported in NFnext");
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
        const auto molName = source.moleculeType(*reactantMol.moleculeTypeId)->name;

        struct Cond {
            std::string compName;
            std::uint32_t site{0};
            std::vector<int> gated;
        };
        std::map<std::string, Cond> condMap;
        std::vector<int> always;
        std::vector<int> conditional;

        struct CenterContribution {
            bool has_center{false};
            int coefficient{0};
        };
        // The signed energy delta is this coefficient times the pattern's
        // energy value. Keeping the coefficient separate lets a dynamic
        // expression be composed at runtime instead of folded to zero.
        auto signedCenterContribution = [&](std::size_t patternIndex) -> CenterContribution {
            const auto& ep = source.energyFactors()[patternIndex];
            CenterContribution result;
            for (const auto& mol : ep.pattern.molecules()) {
                if (!mol.moleculeTypeId || mol.moleculeTypeId->value() != molTypeId) continue;
                for (const auto& site : mol.sites) {
                    if (!site.componentType || site.componentType->index != centerSiteTypeId) continue;
                    if (site.stateConstraintResolved.kind != bng::compile::StateConstraintKind::Exact ||
                        !site.stateConstraintResolved.exact) continue;
                    result.has_center = true;
                    const auto st = site.stateConstraintResolved.exact->index;
                    if (st == toStateId) ++result.coefficient;
                    else if (st == fromStateId) --result.coefficient;
                }
            }
            return result;
        };
        auto appendDynamicEnergyTerm = [&](int coefficient,
                                           const bng::compile::CompiledEnergyFactor& ep,
                                           std::vector<std::string>& terms) -> bool {
            if (coefficient == 0) return true;
            std::set<std::size_t> observableIds;
            const auto expression = observableRateExpression(ep.expression, source, observableIds);
            if (!expression) return false;
            std::ostringstream term;
            term << '(' << coefficient << "*(" << *expression << "))";
            terms.push_back(term.str());
            return true;
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

            bool hasExtra = false;
            int weighted = 0;
            for (const auto& mol : ep.pattern.molecules()) {
                if (mol.moleculeTypeId && mol.moleculeTypeId->value() == molTypeId) ++weighted;
                if (!mol.moleculeTypeId || mol.moleculeTypeId->value() != molTypeId) {
                    hasExtra = true;
                    continue;
                }
                for (const auto& site : mol.sites) {
                    if (site.componentType && site.componentType->index == centerSiteTypeId) continue;
                    const bool isBound = site.bondKind == bng::compile::BondConstraintKind::Exact ||
                        std::any_of(site.bondConstraints.begin(), site.bondConstraints.end(),
                            [](const auto& b){ return b.kind == bng::compile::BondConstraintKind::Exact; });
                    const bool hasState = site.stateConstraintResolved.kind == bng::compile::StateConstraintKind::Exact;
                    if (isBound || hasState) { hasExtra = true; break; }
                }
                if (hasExtra) break;
            }
            if (weighted != 1) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "energy-modulated state change requires one weighted reactant molecule per energy pattern");
                return;
            }
            if (!signedCenterContribution(pi).has_center) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "energy-modulated state change requires a reaction-center state constraint in relevant energy patterns");
                return;
            }

            if (hasExtra) {
                conditional.push_back(static_cast<int>(pi));
                for (const auto& mol : ep.pattern.molecules()) {
                    if (!mol.moleculeTypeId || mol.moleculeTypeId->value() != molTypeId) continue;
                    for (const auto& site : mol.sites) {
                        if (site.componentType && site.componentType->index == centerSiteTypeId) continue;
                        const bool isBound = site.bondKind == bng::compile::BondConstraintKind::Exact ||
                            std::any_of(site.bondConstraints.begin(), site.bondConstraints.end(),
                                [](const auto& b){ return b.kind == bng::compile::BondConstraintKind::Exact; });
                        if (!isBound) continue;
                        if (!site.componentType) continue;
                        const auto cname = source.component(*site.componentType)->name;
                        auto& cc = condMap[cname];
                        cc.compName = cname;
                        cc.site = static_cast<std::uint32_t>(site.componentType->index);
                        cc.gated.push_back(static_cast<int>(pi));
                    }
                }
            } else {
                always.push_back(static_cast<int>(pi));
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

        std::vector<Cond> conditions;
        conditions.reserve(condMap.size());
        for (auto& kv : condMap) {
            std::sort(kv.second.gated.begin(), kv.second.gated.end());
            kv.second.gated.erase(std::unique(kv.second.gated.begin(), kv.second.gated.end()), kv.second.gated.end());
            conditions.push_back(std::move(kv.second));
        }
        std::sort(conditions.begin(), conditions.end(), [](const auto& a, const auto& b){ return a.compName < b.compName; });
        if (conditions.size() >= 20) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "energy-modulated state change expansion too large for NFnext");
            return;
        }

        const std::size_t targetNode = mutation.source.moleculeIndex;
        const int combos = 1 << static_cast<int>(conditions.size());
        for (int combo = 0; combo < combos; ++combo) {
            ExpandedRuleIR variant = lowered;
            variant.id = static_cast<RuleId>(id * 1024u + static_cast<RuleId>(combo));
            variant.name = entity + (reverseDirection ? "_rev_v" : "_v") + std::to_string(combo);
            variant.rate_law.kind = RateLawKind::Elementary;
            std::set<int> active(always.begin(), always.end());
            if (targetNode >= variant.pattern.nodes.size()) continue;
            for (std::size_t ci = 0; ci < conditions.size(); ++ci) {
                const bool met = (combo >> ci) & 1;
                if (met) {
                    variant.pattern.nodes[targetNode].siteBound(conditions[ci].site);
                    for (int pi : conditions[ci].gated) active.insert(pi);
                } else {
                    variant.pattern.nodes[targetNode].siteFree(conditions[ci].site);
                }
            }
            double deltaG = baseEnergy;
            std::vector<std::string> dynamicTerms = baseDynamicTerms;
            for (int pi : active) {
                if (std::find(always.begin(), always.end(), pi) != always.end()) continue;
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
            // deltaG is computed for this direction's state change. For the
            // reverse expansion, deltaG_dir = -deltaG_forward and the NFcore
            // Arrhenius form with forward work W gives
            // k_rev = exp(-(Ea+B + (phi-1)*(deltaG_forward-W)))
            //       = exp(-(Ea+B + (1-phi)*deltaG_dir + (1-phi)*W)).
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
                // Dynamic energy factors are evaluated from current observables
                // by the same Function rate machinery used for dynamic rates.
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

    // 2. Perform state updates, unbinding, and binding
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
        case ActionKind::Bind: {
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
            break;
        }
        case ActionKind::Destroy:
        case ActionKind::DestroyComplex:
            destructions.push_back(action);
            break;
        case ActionKind::MovePosition:
            throw std::runtime_error("NFnext MovePosition action not supported in standard BNG");
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
            const auto pattern = flattenReactants({factor.pattern}, patternValidation, factor.label);
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
            irPopMap.rate_expression = popMap.sourceRate;
            BngLoweringResult patternValidation;
            const auto pattern = flattenReactants({popMap.pattern}, patternValidation, popMap.populationName);
            if (pattern && patternValidation.ok()) {
                irPopMap.pattern = pattern->pattern;
            } else {
                issue(result, BngLoweringSeverity::Error, popMap.populationName,
                      "population map pattern could not be lowered to NFIR");
            }
            const auto rateValue = constantExpression(popMap.rate, source);
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
                        popMap.rate, source, observableIds);
                    if (!expression) {
                        unsupported = "population map rate depends on state that is not a Molecules observable";
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

BngExecutionResult executeFromBioNetGen(const bng::compile::CompiledModel& source,
                                      const BngExecutionRequest& request) {
    const auto refuse = [](const std::string& reason) {
        throw std::runtime_error("NFnext execution unsupported: " + reason);
    };
    if (request.sample_times.empty()) refuse("sample_times must not be empty");
    double previous = -1.0;
    for (double time : request.sample_times) {
        if (!std::isfinite(time) || time < 0.0 || time <= previous)
            refuse("sample_times must be finite, nonnegative and strictly increasing");
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
    const auto& model = lowered.model;
    // Physical rate units are converted during lowering for supported
    // constant elementary forms; execution refuses only if conversion failed.

    // A population map executes only when lowering synthesized an explicit
    // rule for it. Any map outside the supported simple shape (bonds to
    // population nodes, unresolvable or non-Molecules-observable or
    // time-dependent rates, undeclared product types, ...) remains a
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
                    if (d.mutations.size() != 1 || d.reactantPatterns.size() != 1 ||
                        d.mutations.front().kind != BngMutationKind::ChangeState ||
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
    GenericGraphState state(model);
    using PopulationLocation = std::pair<TypeId, std::optional<CompartmentId>>;
    using PopulationCounts = std::map<PopulationLocation, std::uint64_t>;
    PopulationCounts population_counts;
    std::unordered_set<TypeId> compartmentalized_populations;
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
    for (const auto& seed : source.seeds()) {
        const auto amount = constantExpression(seed.amount, source);
        // A constant seed species only marks the species as immutable for
        // setConcentration-style actions; it still initializes particles
        // exactly like an ordinary seed. BNG3 models such as localfunc use a
        // zero-count constant seed for a degradation sink.
        if (seed.declaredUnit ||
            !amount || !std::isfinite(*amount) || *amount < 0.0 ||
            std::floor(*amount) != *amount)
            refuse("seeds require bounded static integer particle counts");
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
        const auto pattern = flattenReactants({seed.pattern}, validation, "seed");
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
            if (key.second) compartmentalized_populations.insert(key.first);
            incrementPopulation(key, static_cast<std::uint64_t>(*amount));
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

        const std::size_t available_particles =
            request.max_particles - state.liveCount();
        if (*amount > static_cast<double>(available_particles))
            refuse("particle budget exceeded by seeds");
        const std::size_t copy_count = static_cast<std::size_t>(*amount);
        if (pat.nodes.empty() ||
            copy_count > available_particles / pat.nodes.size())
            refuse("particle budget exceeded by seeds");

        for (std::size_t count = 0; count < copy_count; ++count) {
            std::vector<ParticleId> particles;
            particles.reserve(pat.nodes.size());
            for (std::size_t nodeIdx = 0; nodeIdx < pat.nodes.size(); ++nodeIdx) {
                const auto& node = pat.nodes[nodeIdx];
                const CompartmentId comp = node.compartment.value_or(
                    seed.compartmentId ? static_cast<CompartmentId>(seed.compartmentId->value()) : 0);
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
                                                  observable.name, true);
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
    for (const auto& rule : model.expanded_rules) {
        compiled_transformations.push_back(
            compileTransformation(buildRuleTransformation(rule), model));
    }

    GenericMatcher matcher(model);

    auto evaluateObservable = [&](const ObservableDef& obs) -> double {
        double value = 0.0;
        if (obs.kind == bng::compile::ObservableKind::Molecules) {
            for (const auto& term : obs.terms) {
                if (term.pattern.nodes.size() == 1 && term.pattern.bonds.empty() &&
                    term.pattern.nodes.front().constraints.empty() &&
                    term.pattern.molecularity.empty() && term.pattern.aliases.empty() &&
                    term.pattern.connected_to.empty() &&
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
                    term.pattern.connected_to.empty() &&
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

    CounterRng rng(request.seed, 0);
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
        if (rule.match_once) continue; // keep conservative for now
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

    auto populationOnlyReactants = [&](const ExpandedRuleIR& rule) {
        return !rule.pattern.nodes.empty() &&
               std::all_of(rule.pattern.nodes.begin(), rule.pattern.nodes.end(), [&](const auto& node) {
                   return model.molecule_types.at(node.molecule_type).is_population;
               }) && rule.pattern.bonds.empty() && rule.filters.empty() && !rule.match_once && !rule.total_rate;
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

    const auto layout = RngLayout::exactSSA();
    double time = 0.0;
    double next_time = std::numeric_limits<double>::infinity();
    std::size_t selected_rule = 0;
    Embedding selected_match;
    bool selected_population_rule = false;
    bool selected_mixed_lumped_rule = false;
    bool pending = false;
    for (const double sample : request.sample_times) {
        for (;;) {
            if (!pending) {
                std::vector<std::vector<Embedding>> matches;
                std::vector<double> rulePropensities(model.expanded_rules.size(), 0.0);
                std::vector<double> currentRates(model.expanded_rules.size(), 0.0);
                std::vector<double> populationFactors(model.expanded_rules.size(), 1.0);
                std::unordered_map<ObservableId, double> currentObservableValues;
                double total = 0.0;
                for (std::size_t index = 0; index < model.expanded_rules.size(); ++index) {
                    const auto& rule = model.expanded_rules[index];
                    const auto& prep = preparedRates[index];
                    double rate = prep.elementaryRate;
                    if (prep.isDynamic) {
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
                    rate *= rule.volume_factor;
                    currentRates[index] = rate;
                    if (populationOnlyReactants(rule)) {
                        matches.emplace_back();
                        const double popFactor = populationReactantPropensity(rule);
                        populationFactors[index] = popFactor;
                        const double prop = rate * popFactor;
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
                        // Apply include/exclude reactant filters relative to particle reactant nodes.
                        if (!rule.filters.empty()) {
                            std::map<std::size_t, std::size_t> oldToNewParticle;
                            for (std::size_t pi = 0; pi < info.particleReactantNodes.size(); ++pi)
                                oldToNewParticle[info.particleReactantNodes[pi]] = pi;
                            std::vector<Embedding> passedMatches;
                            for (const auto& match : rawMatches) {
                                bool matchPassed = true;
                                for (const auto& filter : rule.filters) {
                                    if (filter.products) continue;
                                    // Map filter's reactant node offset back to original node index
                                    // by finding which particle reactant node corresponds.
                                    std::size_t origNode = filter.reactant_node_offset;
                                    // If offset is not a direct particle node index in info, try identity.
                                    auto itNode = oldToNewParticle.find(origNode);
                                    if (itNode == oldToNewParticle.end()) continue;
                                    const auto partId = match.particle(itNode->second);
                                    const auto compId = state.complexId(partId);
                                    bool anyMatched = false;
                                    for (const auto& fPat : filter.patterns) {
                                        const auto fMatches = matcher.enumerate(fPat, state);
                                        for (const auto& fm : fMatches) {
                                            if (!fm.particles().empty() && state.complexId(fm.particle(0)) == compId) {
                                                anyMatched = true;
                                                break;
                                            }
                                        }
                                        if (anyMatched) break;
                                    }
                                    if (filter.include && !anyMatched) { matchPassed = false; break; }
                                    if (!filter.include && anyMatched) { matchPassed = false; break; }
                                }
                                if (matchPassed) passedMatches.push_back(match);
                            }
                            rawMatches = std::move(passedMatches);
                        }
                        if (rule.match_once) {
                            std::vector<Embedding> uniqueMatches;
                            std::set<std::vector<std::uint32_t>> seenParticleSets;
                            for (const auto& match : rawMatches) {
                                std::vector<std::uint32_t> key;
                                key.reserve(match.particles().size());
                                for (const auto& p : match.particles()) key.push_back(p.index);
                                std::sort(key.begin(), key.end());
                                if (seenParticleSets.insert(key).second) uniqueMatches.push_back(match);
                            }
                            rawMatches = std::move(uniqueMatches);
                        }
                        matches.push_back(std::move(rawMatches));
                        double prop = 0.0;
                        if (rule.total_rate) {
                            prop = matches.back().empty() ? 0.0 : rate * popFactor;
                        } else {
                            prop = rate * popFactor * static_cast<double>(matches.back().size());
                        }
                        rulePropensities[index] = prop;
                        total += prop;
                        continue;
                    }
                    auto rawMatches = matcher.enumerate(rule.pattern, state);
                    if (!rule.filters.empty()) {
                        std::vector<Embedding> passedMatches;
                        for (const auto& match : rawMatches) {
                            bool matchPassed = true;
                            for (const auto& filter : rule.filters) {
                                if (filter.products) continue;
                                const auto nodeIdx = filter.reactant_node_offset;
                                if (nodeIdx >= match.particles().size()) continue;
                                const auto partId = match.particle(nodeIdx);
                                const auto compId = state.complexId(partId);
                                bool anyMatched = false;
                                for (const auto& fPat : filter.patterns) {
                                    const auto fMatches = matcher.enumerate(fPat, state);
                                    for (const auto& fm : fMatches) {
                                        if (!fm.particles().empty() && state.complexId(fm.particle(0)) == compId) {
                                            anyMatched = true;
                                            break;
                                        }
                                    }
                                    if (anyMatched) break;
                                }
                                if (filter.include && !anyMatched) {
                                    matchPassed = false;
                                    break;
                                }
                                if (!filter.include && anyMatched) {
                                    matchPassed = false;
                                    break;
                                }
                            }
                            if (matchPassed) passedMatches.push_back(match);
                        }
                        rawMatches = std::move(passedMatches);
                    }
                    if (rule.match_once) {
                        std::vector<Embedding> uniqueMatches;
                        std::set<std::vector<std::uint32_t>> seenParticleSets;
                        for (const auto& match : rawMatches) {
                            std::vector<std::uint32_t> key;
                            key.reserve(match.particles().size());
                            for (const auto& p : match.particles()) key.push_back(p.index);
                            std::sort(key.begin(), key.end());
                            if (seenParticleSets.insert(key).second) {
                                uniqueMatches.push_back(match);
                            }
                        }
                        rawMatches = std::move(uniqueMatches);
                    }
                    matches.push_back(std::move(rawMatches));
                    double prop = 0.0;
                    if (rule.total_rate) {
                        prop = matches.back().empty() ? 0.0 : rate;
                    } else {
                        prop = rate * matches.back().size();
                    }
                    rulePropensities[index] = prop;
                    total += prop;
                }
                if (!std::isfinite(total)) refuse("nonfinite total propensity");
                next_time = total > 0.0
                    ? time + rng.exponential(layout.word(RngPurpose::WaitingTime, output.event_count), total)
                    : std::numeric_limits<double>::infinity();
                if (total > 0.0) {
                    double choice = rng.uniformOpen01(
                        layout.word(RngPurpose::FamilyChoice, output.event_count)) * total;
                    bool found = false;
                    for (std::size_t index = 0; index < model.expanded_rules.size() && !found; ++index) {
                        const auto& rule = model.expanded_rules[index];
                        if (populationOnlyReactants(rule)) {
                            choice -= rulePropensities[index];
                            if (choice < 0.0) {
                                selected_rule = index;
                                selected_population_rule = true;
                                selected_mixed_lumped_rule = false;
                                found = true;
                                break;
                            }
                            continue;
                        }
                        if (mixedLumped[index].enabled) {
                            if (rule.total_rate) {
                                choice -= rulePropensities[index];
                                if (choice < 0.0) {
                                    selected_rule = index;
                                    selected_population_rule = false;
                                    selected_mixed_lumped_rule = true;
                                    selected_match = matches[index].empty() ? Embedding{} : matches[index].front();
                                    found = true;
                                    break;
                                }
                                continue;
                            }
                            const double matchWeight = currentRates[index] * populationFactors[index];
                            for (const auto& match : matches[index]) {
                                choice -= matchWeight;
                                if (choice < 0.0) {
                                    selected_rule = index;
                                    selected_match = match;
                                    selected_population_rule = false;
                                    selected_mixed_lumped_rule = true;
                                    found = true;
                                    break;
                                }
                            }
                            if (found) break;
                            continue;
                        }
                        const double matchWeight = rule.total_rate
                            ? (matches[index].empty() ? 0.0 : currentRates[index] / matches[index].size())
                            : currentRates[index];
                        for (const auto& match : matches[index]) {
                            choice -= matchWeight;
                            if (choice < 0.0) {
                                selected_rule = index;
                                selected_match = match;
                                selected_population_rule = false;
                                selected_mixed_lumped_rule = false;
                                found = true;
                                break;
                            }
                        }
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
                for (std::size_t pi = 0; pi < info.particleReactantNodes.size() && pi < selected_match.particles().size(); ++pi) {
                    full_embedding.bindNode(info.particleReactantNodes[pi], selected_match.particle(pi));
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

                auto isPopReactant = [&](PatternNodeId node) {
                    return node < rule.pattern.nodes.size() &&
                           model.molecule_types.at(rule.pattern.nodes[node].molecule_type).is_population;
                };
                auto resolveEndpoint = [&](PatternNodeId node, std::uint16_t site, ParticleId& pid, std::uint16_t& outSite) -> bool {
                    if (node < rule.pattern.nodes.size()) {
                        if (isPopReactant(node)) return false;
                        try { pid = full_embedding.particle(node); } catch (...) { return false; }
                        outSite = site;
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
                                if (state.alive(pid)) state.setSiteState(pid, action.site, action.value);
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
                                std::vector<ParticleId> members;
                                for (const auto particle : state.liveParticles())
                                    if (state.sameComplex(root, particle)) members.push_back(particle);
                                for (const auto particle : members) if (state.alive(particle)) state.destroy(particle);
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

                if (rule.move_connected) {
                    std::vector<CompartmentId> beforeCompartments(info.particleReactantNodes.size(), 0);
                    std::set<ParticleId> explicitParticles;
                    for (std::size_t i = 0; i < info.particleReactantNodes.size(); ++i) {
                        try {
                            const auto p = full_embedding.particle(info.particleReactantNodes[i]);
                            explicitParticles.insert(p);
                            if (state.alive(p)) beforeCompartments[i] = state.compartment(p);
                        } catch (...) {}
                    }
                    for (std::size_t i = 0; i < info.particleReactantNodes.size(); ++i) {
                        ParticleId p{};
                        try { p = full_embedding.particle(info.particleReactantNodes[i]); } catch (...) { continue; }
                        if (!state.alive(p)) continue;
                        const auto sourceComp = beforeCompartments[i];
                        const auto targetComp = state.compartment(p);
                        if (targetComp == sourceComp) continue;
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

                MatchEmbedding match_embedding;
                for (std::size_t node = 0; node < selected_match.particles().size(); ++node) {
                    match_embedding.bindNode(node, selected_match.particle(node));
                }

                auto isPopReactantType = [&](PatternNodeId node) {
                    return node < rule.pattern.nodes.size() &&
                           model.molecule_types.at(rule.pattern.nodes[node].molecule_type).is_population;
                };
                auto resolveEndpoint = [&](PatternNodeId node, std::uint16_t site, ParticleId& pid, std::uint16_t& outSite) -> bool {
                    if (node < rule.pattern.nodes.size()) {
                        if (isPopReactantType(node)) return false;
                        try { pid = match_embedding.particle(node); } catch (...) { return false; }
                        outSite = site;
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
                                if (state.alive(pid)) state.setSiteState(pid, action.site, action.value);
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
                                std::vector<ParticleId> members;
                                for (const auto particle : state.liveParticles())
                                    if (state.sameComplex(root, particle)) members.push_back(particle);
                                for (const auto particle : members) if (state.alive(particle)) state.destroy(particle);
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
                // move_connected for this path not yet handled; refuse if requested
                if (rule.move_connected) refuse("move_connected with lumped population actions not yet supported");

                if (state.liveCount() > request.max_particles) refuse("particle budget exhausted");
                ++output.event_count;
                pending = false;
                continue;
            }

            std::vector<CompartmentId> beforeCompartments;
            std::set<ParticleId> explicitParticles;
            if (rule.move_connected) {
                beforeCompartments.reserve(selected_match.particles().size());
                for (const auto& p : selected_match.particles()) {
                    beforeCompartments.push_back(state.compartment(p));
                    explicitParticles.insert(p);
                }
            }

            MatchEmbedding match_embedding;
            for (std::size_t node = 0; node < selected_match.particles().size(); ++node) {
                match_embedding.bindNode(node, selected_match.particle(node));
            }
            applyTransformation(compiled_transformations[selected_rule], match_embedding, state);

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

            if (rule.move_connected) {
                for (std::size_t node = 0; node < selected_match.particles().size(); ++node) {
                    const auto p = selected_match.particle(node);
                    if (!state.alive(p)) continue;
                    const auto sourceComp = beforeCompartments[node];
                    const auto targetComp = state.compartment(p);
                    if (targetComp != sourceComp) {
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
            }

            if (state.liveCount() > request.max_particles) refuse("particle budget exhausted");
            ++output.event_count;
            pending = false;
        }
        std::vector<double> row{sample};
        for (const auto& obs : observables)
            row.push_back(evaluateObservable(obs));
        output.rows.push_back(std::move(row));
    }
    return output;
}

} // namespace nfnext
