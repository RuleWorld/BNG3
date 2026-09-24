#include "engine/NetworkRulePlan.hpp"

#include "ast/SpeciesGraph.hpp"


#include <algorithm>
#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <tuple>
#include <utility>

#include "compile/LegacyAstLowering.hpp"
#include "core/List.hpp"
#include "core/PatternMatching.hpp"
#include "core/Ullmann.hpp"
#include "engine/LegacyNetworkRuleKernel.hpp"

namespace bng::engine {
namespace {

bool isPatternMoleculeNode(const BNGcore::Node &node) {
  const auto &name = node.get_type().get_type_name();
  return name != BNGcore::BOND_NODE_TYPE.get_type_name() &&
         name != BNGcore::COMPONENT_NODE_TYPE.get_type_name();
}

struct ScopeBinding {
  std::string localName;
  compile::PatternSide side = compile::PatternSide::Reactant;
  std::size_t patternIndex = 0;
    compile::LocalScopeKind kind = compile::LocalScopeKind::Molecule;
    std::optional<std::size_t> moleculeOccurrence;
};

using ScopeEnvironment = std::map<std::string, ScopeBinding>;

std::optional<ScopeBinding> resolveScopeArgument(
    const compile::ResolvedExpression& expression,
    const compile::CompiledRuleDirection& direction,
    const ScopeEnvironment& environment) {
    if (expression.kind != compile::ResolvedExpressionKind::LocalRef) return std::nullopt;
    const auto bound = environment.find(expression.localName);
    if (bound != environment.end()) return bound->second;
    if (const auto* scope = direction.findLocalScope(expression.localName)) {
        return ScopeBinding{scope->name, scope->side, scope->patternIndex, scope->kind, scope->moleculeOccurrence};
    }
    return std::nullopt;
}

bool expressionUsesFunctionProduct(
    const compile::ResolvedExpression &expression,
    const compile::CompiledModel &model,
    std::set<std::size_t> &activeFunctions) {
  using Kind = compile::ResolvedExpressionKind;
  if (expression.kind == Kind::BuiltinCall &&
      expression.builtin == compile::BuiltinFunction::FunctionProduct) {
    return true;
  }
  if (expression.kind == Kind::FunctionRef && expression.symbol.has_value()) {
    const auto functionIndex = expression.symbol->index;
    if (activeFunctions.insert(functionIndex).second) {
      if (const auto *function = model.function(
              compile::FunctionId::fromDenseIndex(functionIndex))) {
        const bool found = expressionUsesFunctionProduct(
            function->expression, model, activeFunctions);
        activeFunctions.erase(functionIndex);
        if (found)
          return true;
      } else {
        activeFunctions.erase(functionIndex);
      }
    }
  }
  for (const auto &argument : expression.arguments) {
    if (expressionUsesFunctionProduct(argument, model, activeFunctions))
      return true;
  }
  return false;
}

struct ScopedObservableKey {
  std::string localScopeName;
  compile::PatternSide side = compile::PatternSide::Reactant;
  std::size_t patternIndex = 0;
    compile::LocalScopeKind scopeKind = compile::LocalScopeKind::Molecule;
    std::optional<std::size_t> moleculeOccurrence;
    std::size_t observableIndex = 0;

    friend bool operator<(const ScopedObservableKey& lhs,
                          const ScopedObservableKey& rhs) noexcept {
        return std::tie(lhs.localScopeName, lhs.side, lhs.patternIndex, lhs.scopeKind, lhs.moleculeOccurrence, lhs.observableIndex) <
               std::tie(rhs.localScopeName, rhs.side, rhs.patternIndex, rhs.scopeKind, rhs.moleculeOccurrence, rhs.observableIndex);
    }
};

void collectScopedObservableDependencies(
    const compile::ResolvedExpression& expression,
    const compile::CompiledModel& model,
    const compile::CompiledRuleDirection& direction,
    const ScopeEnvironment& environment,
    std::set<ScopedObservableKey>& observables,
    std::set<std::size_t>& activeFunctions) {
    using Kind = compile::ResolvedExpressionKind;

    if (expression.kind == Kind::ObservableRef && expression.symbol.has_value()) {
        // A local observable is semantically scoped by its argument, e.g.
        // AB_motif(x). A zero-argument observable remains global and therefore
        // must not affect the per-embedding local-rate fingerprint.
        if (expression.arguments.size() == 1) {
            if (const auto scope = resolveScopeArgument(
                    expression.arguments.front(), direction, environment)) {
                observables.insert(ScopedObservableKey{
            scope->localName, scope->side, scope->patternIndex, scope->kind, scope->moleculeOccurrence,
                    expression.symbol->index});
            }
        }
    }

    if (expression.kind == Kind::FunctionRef && expression.symbol.has_value()) {
        const auto functionIndex = expression.symbol->index;
        if (activeFunctions.insert(functionIndex).second) {
            if (const auto* function = model.function(
                    compile::FunctionId::fromDenseIndex(functionIndex))) {
                ScopeEnvironment childEnvironment = environment;
                const auto count = std::min(function->arguments.size(),
                                            expression.arguments.size());
                for (std::size_t index = 0; index < count; ++index) {
                    if (const auto scope = resolveScopeArgument(
                            expression.arguments[index], direction, environment)) {
                        childEnvironment[function->arguments[index]] = *scope;
                    }
                }
                collectScopedObservableDependencies(
                    function->expression, model, direction, childEnvironment,
                    observables, activeFunctions);
            }
            activeFunctions.erase(functionIndex);
        }
    }

    // Function-call actual arguments can themselves contain observable/function
    // expressions, so traverse them even after following the declaration body.
    for (const auto& argument : expression.arguments) {
        collectScopedObservableDependencies(
            argument, model, direction, environment, observables, activeFunctions);
    }
}

struct RuntimeFilter {
    bool include = false;
    bool products = false;
    std::size_t patternIndex = 0;
    std::vector<ast::SpeciesGraph> patterns;
};

struct RuntimeObservable {
    std::string name;
    std::string localScopeName;
  compile::PatternSide side = compile::PatternSide::Reactant;
  std::size_t patternIndex = 0;
    compile::LocalScopeKind scopeKind = compile::LocalScopeKind::Molecule;
    std::optional<std::size_t> moleculeOccurrence;
    std::optional<std::size_t> inputPatternIndex;
  std::optional<std::size_t> inputMoleculeOccurrence;
  std::vector<ast::SpeciesGraph> patterns;
  std::optional<ast::SpeciesGraph> scopePattern;
};

std::vector<RuntimeFilter> lowerFilters(
    const compile::CompiledRuleDirection& direction,
    compile::BNGcoreLoweringContext& context) {
    std::vector<RuntimeFilter> result;
    result.reserve(direction.filters.size());
    for (const auto& filter : direction.filters) {
        RuntimeFilter runtime;
        runtime.include = filter.include;
        runtime.products = filter.products;
        runtime.patternIndex = filter.patternIndex;
        runtime.patterns.reserve(filter.patterns.size());
        for (const auto& pattern : filter.patterns) {
            runtime.patterns.push_back(
                compile::lowerPatternToSpeciesGraph(pattern, context));
        }
        result.push_back(std::move(runtime));
    }
    return result;
}

std::vector<RuntimeObservable> lowerLocalObservableDependencies(
    const compile::CompiledRule &compiledRule,
    const compile::CompiledRuleDirection& direction,
    const compile::CompiledModel& model,
    compile::BNGcoreLoweringContext& context, bool reverseDirection) {
    std::vector<RuntimeObservable> result;
    if (direction.localScopes.empty() || !direction.rateLaw.has_value()) return result;

    std::set<ScopedObservableKey> observableKeys;
    std::set<std::size_t> activeFunctions;
    collectScopedObservableDependencies(
        direction.rateLaw->resolvedExpression(), model, direction, {},
        observableKeys, activeFunctions);

    for (const auto& key : observableKeys) {
        const auto* observable = model.observable(
            compile::ObservableId::fromDenseIndex(key.observableIndex));
        if (observable == nullptr) continue;

        RuntimeObservable runtime;
        runtime.name = observable->name;
        runtime.localScopeName = key.localScopeName;
    runtime.side = key.side;
    runtime.patternIndex = key.patternIndex;
        runtime.scopeKind = key.scopeKind;
        runtime.moleculeOccurrence = key.moleculeOccurrence;
    if (key.side == compile::PatternSide::Product &&
        key.moleculeOccurrence.has_value()) {
      for (const auto &[product, reactant] : compiledRule.moleculeMappings()) {
        if (!reverseDirection &&
            product.side == compile::PatternSide::Product &&
            product.patternIndex == key.patternIndex &&
            product.moleculeIndex == *key.moleculeOccurrence &&
            reactant.side == compile::PatternSide::Reactant) {
          runtime.inputPatternIndex = reactant.patternIndex;
          runtime.inputMoleculeOccurrence = reactant.moleculeIndex;
          break;
        }
        if (reverseDirection &&
            reactant.side == compile::PatternSide::Reactant &&
            reactant.patternIndex == key.patternIndex &&
            reactant.moleculeIndex == *key.moleculeOccurrence &&
            product.side == compile::PatternSide::Product) {
          runtime.inputPatternIndex = product.patternIndex;
          runtime.inputMoleculeOccurrence = product.moleculeIndex;
          break;
        }
      }
    }
    if (key.side == compile::PatternSide::Product &&
        key.patternIndex < direction.productPatterns.size()) {
      runtime.scopePattern = compile::lowerPatternToSpeciesGraph(
          direction.productPatterns[key.patternIndex], context);
    }
    runtime.patterns.reserve(observable->terms.size());
        for (const auto& term : observable->terms) {
            // Local functions evaluate ordinary pattern counts. Stoichiometric
            // comparison terms (R==2, R>=3, ...) require separate boolean/count
            // semantics and must not silently collapse to raw embedding counts.
            if (!term.relation.empty()) {
                throw std::runtime_error(
                    "network local function observable '" + observable->name +
                    "' uses stoichiometric relation '" + term.relation +
                    "', which is not yet representable by the compiled network "
                    "local-rate fingerprint");
            }
            runtime.patterns.push_back(
                compile::lowerPatternToSpeciesGraph(term.pattern, context));
        }
        result.push_back(std::move(runtime));
    }
    std::sort(result.begin(), result.end(), [](const auto& lhs, const auto& rhs) {
        return std::tie(lhs.side, lhs.patternIndex, lhs.localScopeName, lhs.name) <
               std::tie(rhs.side, rhs.patternIndex, rhs.localScopeName, rhs.name);
    });
    return result;
}

bool passesFilterPatterns(const RuntimeFilter& filter, const ast::SpeciesGraph& species) {
    // BioNetGen include_* semantics are disjunctive across the supplied
    // patterns (at least one must match); exclude_* rejects when any supplied
    // pattern matches. This mirrors the legacy Perl implementation.
    const bool anyMatch = std::any_of(
        filter.patterns.begin(), filter.patterns.end(),
        [&](const auto& pattern) {
            return core::patternMatchesSpecies(pattern, species);
        });
    return filter.include ? anyMatch : !anyMatch;
}

} // namespace

struct NetworkRulePlan::Impl {
    std::unique_ptr<LegacyNetworkRuleKernel> kernel;
    std::vector<RuntimeFilter> filters;
    std::vector<RuntimeObservable> localObservables;
    LegacyNetworkRuleHooks hooks;
  bool functionProductRate = false;

  Impl(const compile::CompiledRule& compiledRule,
         const compile::CompiledRuleDirection& direction,
         const compile::CompiledModel& model,
         compile::BNGcoreLoweringContext& context,
         bool reverseDirection)
        : kernel(std::make_unique<LegacyNetworkRuleKernel>(
              compiledRule, direction, model, context, reverseDirection)),
          filters(lowerFilters(direction, context)),
          localObservables(lowerLocalObservableDependencies(
            compiledRule, direction, model, context, reverseDirection)),
        functionProductRate([&]() {
          if (!direction.rateLaw.has_value())
            return false;
          std::set<std::size_t> activeFunctions;
          return expressionUsesFunctionProduct(
              direction.rateLaw->resolvedExpression(), model, activeFunctions);
        }()) {
        if (!filters.empty()) {
            hooks.reactantFilter = [this](std::size_t patternIndex,
                                          const ast::SpeciesGraph& species) {
                for (const auto& filter : filters) {
                    if (filter.products || filter.patternIndex != patternIndex) continue;
                    if (!passesFilterPatterns(filter, species)) return false;
                }
                return true;
            };
            hooks.productFilter = [this](const std::vector<ast::SpeciesGraph>& products) {
                for (const auto& filter : filters) {
                    if (!filter.products) continue;
                    if (filter.patternIndex >= products.size()) return false;
                    if (!passesFilterPatterns(filter, products[filter.patternIndex])) return false;
                }
                return true;
            };
        }

        if (!localObservables.empty()) {
            hooks.localRateFingerprint = [this](
                std::size_t patternIndex,
                std::size_t moleculeIndex,
                const BNGcore::Node* scopedMolecule,
                const BNGcore::PatternGraph& speciesGraph) {
                std::ostringstream out;
                for (const auto& observable : localObservables) {
                    if (observable.side != compile::PatternSide::Reactant)
                continue;
              if (observable.patternIndex != patternIndex) continue;
                    if (observable.scopeKind == compile::LocalScopeKind::Molecule &&
                        observable.moleculeOccurrence.has_value() &&
                        *observable.moleculeOccurrence != moleculeIndex) continue;
                    std::size_t count = 0;
                    for (const auto& pattern : observable.patterns) {
                        if (observable.scopeKind == compile::LocalScopeKind::Species) {
                            count += core::countPatternMatches(pattern, speciesGraph);
                        } else {
                            count += core::countPatternMatchesForScopedMolecule(
                                pattern, speciesGraph, scopedMolecule);
                        }
                    }
              if (functionProductRate) {
                out << observable.localScopeName << "::" << observable.name
                    << '=' << count << ';';
              } else {
                out << observable.name << '=' << count << ';';
              }
            }
            return out.str();
          };

      const bool hasProductLocalObservables =
          std::any_of(localObservables.begin(), localObservables.end(),
                      [](const auto &observable) {
                        return observable.side == compile::PatternSide::Product;
                      });
      if (hasProductLocalObservables) {
        hooks.productScopeMatchSignature =
            [this](std::size_t patternIndex, std::size_t moleculeIndex,
                   const BNGcore::Node *scopedMolecule,
                   const BNGcore::PatternGraph &) {
              std::ostringstream out;
              for (const auto &observable : localObservables) {
                if (observable.side != compile::PatternSide::Product ||
                    !observable.inputPatternIndex.has_value() ||
                    !observable.inputMoleculeOccurrence.has_value()) {
                  continue;
                }
                if (*observable.inputPatternIndex != patternIndex ||
                    *observable.inputMoleculeOccurrence != moleculeIndex) {
                  continue;
                }
                out << observable.localScopeName << '@'
                    << reinterpret_cast<std::uintptr_t>(scopedMolecule) << ';';
              }
              return out.str();
            };

        hooks.productLocalRateFingerprint =
            [this](const std::vector<ast::SpeciesGraph> &products,
                   const std::vector<std::size_t> &productPatternIndices) {
              std::ostringstream out;
              for (const auto &observable : localObservables) {
                if (observable.side != compile::PatternSide::Product)
                  continue;
                if (observable.scopeKind == compile::LocalScopeKind::Molecule &&
                    (!observable.scopePattern ||
                     !observable.moleculeOccurrence.has_value())) {
                  throw std::runtime_error("product local function scope '" +
                                           observable.localScopeName +
                                           "' has no compiled molecule anchor");
                }

                const BNGcore::Node *scopePatternMolecule = nullptr;
                if (observable.scopePattern &&
                    observable.moleculeOccurrence.has_value()) {
                  std::size_t moleculeIndex = 0;
                  for (auto node = observable.scopePattern->getGraph().begin();
                       node != observable.scopePattern->getGraph().end();
                       ++node) {
                    if (!isPatternMoleculeNode(**node))
                      continue;
                    if (moleculeIndex++ == *observable.moleculeOccurrence) {
                      scopePatternMolecule = *node;
                      break;
                    }
                  }
                  if (scopePatternMolecule == nullptr) {
                    throw std::runtime_error(
                        "product local function scope '" +
                        observable.localScopeName +
                        "' refers to a missing product molecule");
                  }
                }

                bool foundScopeProduct = false;
                std::size_t count = 0;
                for (std::size_t productIndex = 0;
                     productIndex < products.size() &&
                     productIndex < productPatternIndices.size();
                     ++productIndex) {
                  if (productPatternIndices[productIndex] !=
                      observable.patternIndex) {
                    continue;
                  }
                  foundScopeProduct = true;
                  const auto &productGraph = products[productIndex].getGraph();
                  if (observable.scopeKind ==
                      compile::LocalScopeKind::Species) {
                    for (const auto &pattern : observable.patterns) {
                      count += core::countPatternMatches(pattern, productGraph);
                    }
                    continue;
                  }

                  BNGcore::UllmannSGIso matcher(
                      observable.scopePattern->getGraph(), productGraph);
                  BNGcore::List<BNGcore::Map> maps;
                  matcher.find_maps(maps);
                  if (maps.begin() == maps.end())
                    continue;
                  auto *scopedMolecule = maps.begin()->mapf(
                      const_cast<BNGcore::Node *>(scopePatternMolecule));
                  if (scopedMolecule == nullptr)
                    continue;
                  for (const auto &pattern : observable.patterns) {
                    count += core::countPatternMatchesForScopedMolecule(
                        pattern, productGraph, scopedMolecule);
                  }
                }
                if (!foundScopeProduct) {
                  throw std::runtime_error(
                      "product local function scope '" +
                      observable.localScopeName +
                      "' has no generated product species");
                }
                out << observable.localScopeName << "::" << observable.name << '=' << count << ';';
                }
                return out.str();
            };
      }
    }
        kernel->setHooks(hooks);
    }
};

NetworkRulePlan::NetworkRulePlan(
    const compile::CompiledRule& rule,
    const compile::CompiledRuleDirection& direction,
    const compile::CompiledModel& model,
    compile::BNGcoreLoweringContext& loweringContext,
    bool reverseDirection)
    : impl_(std::make_unique<Impl>(
          rule, direction, model, loweringContext, reverseDirection)) {}

NetworkRulePlan::~NetworkRulePlan() = default;
NetworkRulePlan::NetworkRulePlan(NetworkRulePlan&&) noexcept = default;
NetworkRulePlan& NetworkRulePlan::operator=(NetworkRulePlan&&) noexcept = default;

const std::string& NetworkRulePlan::name() const noexcept { return impl_->kernel->name(); }

void NetworkRulePlan::clearPatternMatchCache() {
    impl_->kernel->clearPatternMatchCache();
}

std::size_t NetworkRulePlan::expand(
    ast::SpeciesList& species,
    ast::RxnList& reactions,
    std::size_t currentIteration,
    const std::function<bool(const ast::SpeciesGraph&)>& productFilter,
    std::size_t speciesBoundary) {
    return impl_->kernel->expand(
        species, reactions, currentIteration, productFilter, speciesBoundary);
}

std::vector<NetworkRulePlan> lowerNetworkRules(
    const compile::CompiledModel& model,
    compile::BNGcoreLoweringContext& loweringContext) {
    std::vector<NetworkRulePlan> result;
    for (const auto& rule : model.rules()) {
        // The compatibility execution object derives its internal edit caches
        // from the already-resolved reactant/product graphs. Therefore a
        // conservative/incomplete compiler mutation summary does not require
        // falling back to the original AST rule.
        result.emplace_back(rule, rule.forward(), model, loweringContext, false);
        if (rule.reverse().has_value())
            result.emplace_back(rule, *rule.reverse(), model, loweringContext, true);
    }
    return result;
}

} // namespace bng::engine
