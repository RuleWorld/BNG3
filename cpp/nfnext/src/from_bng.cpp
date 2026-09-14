#include "nfnext/from_bng.hpp"

#include "compile/CompiledModel.hpp"
#include "nfnext/compiler.hpp"

#include <cmath>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <tuple>
#include <utility>

namespace nfnext {
namespace {

using BngPattern = bng::compile::Pattern;
using BngPatternSide = bng::compile::PatternSide;
using BngMutationKind = bng::compile::MutationKind;

void issue(BngLoweringResult& result, BngLoweringSeverity severity,
           std::string entity, std::string message) {
    result.issues.push_back({severity, std::move(entity), std::move(message)});
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
            if (parameter && parameter->constantValue) return parameter->constantValue;
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
        return std::nullopt;
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
                   std::size_t& firstNode) {
    if (!source.isResolved()) {
        issue(result, BngLoweringSeverity::Error, entity,
              "pattern is not fully symbol-resolved");
        return false;
    }
    if (!source.compartment().empty()) {
        issue(result, BngLoweringSeverity::Error, entity,
              "compartment-scoped patterns are not representable in NFIR v5");
        return false;
    }
    firstNode = destination.nodes.size();
    std::map<std::size_t, std::vector<std::pair<std::size_t, std::uint32_t>>> exactBonds;
    for (const auto& molecule : source.molecules()) {
        if (!molecule.compartment.empty()) {
            issue(result, BngLoweringSeverity::Error, entity,
                  "molecule-local compartments are not representable in NFIR v5");
            return false;
        }
        if (!molecule.moleculeTypeId) {
            issue(result, BngLoweringSeverity::Error, entity, "pattern molecule has no typed molecule ID");
            return false;
        }
        const auto node = destination.addNode(static_cast<TypeId>(molecule.moleculeTypeId->value()));
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
    return true;
}

std::optional<FlattenedPattern> flattenReactants(
    const std::vector<BngPattern>& patterns, BngLoweringResult& result,
    const std::string& entity) {
    FlattenedPattern flattened;
    flattened.patternOffsets.reserve(patterns.size());
    std::vector<std::size_t> representatives;
    for (const auto& pattern : patterns) {
        std::size_t first = 0;
        flattened.patternOffsets.push_back(flattened.pattern.nodes.size());
        if (!appendPattern(pattern, flattened.pattern, result, entity, first)) return std::nullopt;
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

    if (pureDegradation && !deleteMolecules) {
        // Standard BNGL degradation removes the matched reactant species/complex,
        // including context not explicitly present in the pattern. One action per
        // '+' reactant pattern is sufficient because each pattern is a distinct
        // reactant complex in NFIR.
        for (std::size_t patternIndex = 0; patternIndex < direction.reactantPatterns.size(); ++patternIndex) {
            if (direction.reactantPatterns[patternIndex].molecules().empty()) continue;
            const bng::compile::PatternMoleculeRef ref{
                BngPatternSide::Reactant, patternIndex, 0};
            const auto node = nodeFor(ref, reactants);
            if (!node) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "degradation rule could not identify a reactant complex representative");
                return false;
            }
            const auto& molecule = direction.reactantPatterns[patternIndex].molecules().front();
            if (!molecule.moleculeTypeId) {
                issue(result, BngLoweringSeverity::Error, entity,
                      "degradation reactant molecule is not typed");
                return false;
            }
            ActionIR destroy;
            destroy.kind = ActionKind::DestroyComplex;
            destroy.target_node = *node;
            destroy.molecule_type = static_cast<TypeId>(molecule.moleculeTypeId->value());
            actions.push_back(std::move(destroy));
        }
        return true;
    }

    // A simultaneous unmatched deletion + creation is the legacy molecule-
    // replacement case. BioNetGen's mature network engine suppresses orphaned
    // context for that case, while NFIR v5 only has explicit molecule/complex
    // destruction. Refuse to guess until that cleanup contract is represented.
    bool hasUnmappedReactant = false;
    for (std::size_t patternIndex = 0; patternIndex < direction.reactantPatterns.size(); ++patternIndex) {
        const auto& pattern = direction.reactantPatterns[patternIndex];
        for (std::size_t moleculeIndex = 0; moleculeIndex < pattern.molecules().size(); ++moleculeIndex) {
            const bng::compile::PatternMoleculeRef ref{
                BngPatternSide::Reactant, patternIndex, moleculeIndex};
            const auto node = nodeFor(ref, reactants);
            if (node && nodes.mappedReactants.count(*node) == 0) hasUnmappedReactant = true;
        }
    }
    if (!deleteMolecules && hasUnmappedReactant && !nodes.createdProducts.empty()) {
        issue(result, BngLoweringSeverity::Error, entity,
              "simultaneous molecule replacement requires orphan-context semantics "
              "not yet representable in NFIR v5");
        return false;
    }

    // DeleteMolecules and partial rule rewrites remove only explicit unmatched
    // molecule occurrences, preserving any unmatched surrounding context.
    for (std::size_t patternIndex = 0; patternIndex < direction.reactantPatterns.size(); ++patternIndex) {
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

    for (const auto& mutation : direction.mutations) {
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

    if (!appendCreatedProductBonds(direction, *nodes, actions, result, entity)) return false;
    return appendDeletionActions(rule, direction, pattern, *nodes, actions, result, entity);
}

void addDirection(const bng::compile::CompiledRule& rule,
                  const bng::compile::CompiledRuleDirection& direction,
                  RuleId id, const std::string& suffix, bool reverseDirection,
                  const bng::compile::CompiledModel& source,
                  BngLoweringResult& result) {
    const std::string entity = rule.name() + suffix;
    if (!direction.filters.empty()) {
        issue(result, BngLoweringSeverity::Error, entity,
              "include/exclude rule filters are not representable in NFIR v5");
        return;
    }
    for (const auto& modifier : rule.modifiers()) {
        if (modifier.kind == bng::compile::ModifierKind::DeleteMolecules) continue;
        issue(result, BngLoweringSeverity::Error, entity,
              "rule modifier '" + modifier.source +
              "' is not representable in NFIR v5");
        return;
    }
    const auto flattened = flattenReactants(direction.reactantPatterns, result, entity);
    if (!flattened) return;
    if (!direction.rateLaw) {
        issue(result, BngLoweringSeverity::Error, entity, "rule direction has no rate law");
        return;
    }

    ExpandedRuleIR lowered;
    lowered.id = id;
    lowered.name = entity;
    lowered.pattern = flattened->pattern;
    addPredicates(lowered.pattern, lowered.predicates);
    if (!addActions(rule, direction, *flattened, reverseDirection,
                    lowered.actions, result, entity)) return;

    const auto constant = constantExpression(direction.rateLaw->resolvedExpression(), source);
    if (!constant || !std::isfinite(*constant) || *constant < 0.0) {
        issue(result, BngLoweringSeverity::Error, entity,
              "dynamic BioNetGen rate expressions are not representable in NFIR v5; "
              "NFIR does not yet carry the parameter/function/observable expression graph");
        return;
    }
    lowered.rate = *constant;
    lowered.rate_law.kind = RateLawKind::Elementary;
    // This spelling is diagnostic only for elementary rates. Runtime execution
    // uses the resolved numeric rate above, so NFnext never reparses BNGL here.
    std::ostringstream rateText;
    rateText.precision(17);
    rateText << *constant;
    lowered.rate_law.expression = rateText.str();
    lowered.annotations.emplace("bng.rule_label", rule.label());
    result.model.expanded_rules.push_back(std::move(lowered));
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
    if (!source.compartments().empty())
        issue(result, BngLoweringSeverity::Warning, source.metadata().name,
              "NFIR v5 retains molecule topology/rules but does not yet carry compartment declarations");
    if (!source.populationMaps().empty())
        issue(result, BngLoweringSeverity::Error, source.metadata().name,
              "population maps are not representable in NFIR v5");
    if (!source.energyFactors().empty())
        issue(result, BngLoweringSeverity::Error, source.metadata().name,
              "energy patterns are not representable in NFIR v5 rate semantics");
    if (!result.ok()) return result;

    result.model.molecule_types.reserve(source.moleculeTypes().size());
    for (const auto& molecule : source.moleculeTypes()) {
        MoleculeTypeIR type;
        type.id = static_cast<TypeId>(molecule.id.value());
        type.name = molecule.name;
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

} // namespace nfnext
