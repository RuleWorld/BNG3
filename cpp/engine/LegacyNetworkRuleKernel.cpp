#include "engine/LegacyNetworkRuleKernel.hpp"

#include "ast/ReactionRule.hpp"
#include "ast/RxnList.hpp"
#include "ast/SpeciesList.hpp"
#include "compile/CompiledModel.hpp"
#include "compile/CompiledRule.hpp"
#include "compile/LegacyAstLowering.hpp"
#include "compile/PatternLowering.hpp"

#include <algorithm>
#include <utility>

namespace bng::engine {
namespace {

bool isFilterModifier(compile::ModifierKind kind) {
    using K = compile::ModifierKind;
    return kind == K::IncludeReactants || kind == K::ExcludeReactants ||
           kind == K::IncludeProducts || kind == K::ExcludeProducts;
}

std::vector<std::string> executionModifiers(const compile::CompiledRule& rule) {
    std::vector<std::string> result;
    for (const auto& modifier : rule.modifiers()) {
        // The compiled DeleteMolecules kind is supplied through ExecutionHooks
        // below; keeping it out of the lowered text makes that runtime decision
        // independent of modifier spelling. The compatibility constructor may
        // still derive its mismatch hint from this list, but the typed deletion
        // hook controls orphan retention during compiled execution.
        if (!isFilterModifier(modifier.kind) &&
            modifier.kind != compile::ModifierKind::DeleteMolecules) {
            result.push_back(modifier.source);
        }
    }
    return result;
}

bool deletesMolecules(const compile::CompiledRule& rule) {
    return std::any_of(rule.modifiers().begin(), rule.modifiers().end(),
        [](const auto& modifier) {
            return modifier.kind == compile::ModifierKind::DeleteMolecules;
        });
}

bool hasSpeciesScope(const compile::CompiledRuleDirection& direction) {
    return std::any_of(direction.localScopes.begin(), direction.localScopes.end(),
        [](const auto& scope) { return scope.kind == compile::LocalScopeKind::Species; });
}

} // namespace

struct LegacyNetworkRuleKernel::Impl {
    std::string name;
    ast::ReactionRule rule;
    std::unique_ptr<ast::ReactionRule::ExecutionState> state;
    compile::CompiledRuleExecutionHooks publicHooks;
    ast::ReactionRule::ExecutionHooks astHooks;

    Impl(const compile::CompiledRule& compiledRule,
         const compile::CompiledRuleDirection& direction,
         const compile::CompiledModel& model,
         compile::BNGcoreLoweringContext& context,
         bool reverseDirection)
        : name(reverseDirection ? std::string("_reverse__") + compiledRule.name()
                                : compiledRule.name()),
          rule(
              name,
              reverseDirection
                  ? (compiledRule.label().empty() ? std::string("_reverse")
                                                  : std::string("_reverse__") + compiledRule.label())
                  : compiledRule.label(),
              {}, {},
              direction.rateLaw.has_value()
                  ? std::vector<ast::Expression>{compile::lowerResolvedExpressionToAst(
                        model.expandFunctions(
                            direction.rateLaw->resolvedExpression()),
                        model)}
                  : std::vector<ast::Expression>{},
              executionModifiers(compiledRule),
              false,
              compile::lowerPatternsToSpeciesGraphs(direction.reactantPatterns, context),
              compile::lowerPatternsToSpeciesGraphs(direction.productPatterns, context)),
          state(rule.createExecutionState()) {
        rule.setHasScopePrefix(hasSpeciesScope(direction));
        astHooks.deleteMolecules = deletesMolecules(compiledRule);
        astHooks.wholeSpeciesDeletions = direction.wholeSpeciesDeletions;
    }

    void refreshHooks() {
        astHooks.localRateFingerprint = publicHooks.localRateFingerprint;
        astHooks.productScopeMatchSignature =
        publicHooks.productScopeMatchSignature;
        astHooks.rejectZeroRate = publicHooks.rejectZeroRate;
        // The compile-owned filter callbacks speak the backend neutral graph
        // vocabulary. The AST expansion speaks the legacy species vocabulary.
        // Only install the adapter when the contract actually declares the
        // filter: an unset contract keeps the expansion's own default.
        if (publicHooks.reactantFilter) {
            const auto filter = publicHooks.reactantFilter;
            astHooks.reactantFilter =
                [filter](std::size_t patternIndex, const ast::SpeciesGraph& species) {
                    return filter(patternIndex, species.getGraph());
                };
        }
        if (publicHooks.productFilter) {
            const auto filter = publicHooks.productFilter;
            astHooks.productFilter =
                [filter](const std::vector<ast::SpeciesGraph>& products) {
                    std::vector<const BNGcore::PatternGraph*> graphs;
                    graphs.reserve(products.size());
                    for (const auto& product : products)
                        graphs.push_back(&product.getGraph());
                    return filter(graphs);
                };
        }
        if (publicHooks.productLocalRateFingerprint) {
            const auto fingerprint = publicHooks.productLocalRateFingerprint;
            astHooks.productLocalRateFingerprint =
                [fingerprint](const std::vector<ast::SpeciesGraph>& products,
                              const std::vector<std::size_t>& productPatternIndices) {
                    std::vector<const BNGcore::PatternGraph*> graphs;
                    graphs.reserve(products.size());
                    for (const auto& product : products)
                        graphs.push_back(&product.getGraph());
                    return fingerprint(graphs, productPatternIndices);
                };
        }
  }
};

LegacyNetworkRuleKernel::LegacyNetworkRuleKernel(
    const compile::CompiledRule& rule,
    const compile::CompiledRuleDirection& direction,
    const compile::CompiledModel& model,
    compile::BNGcoreLoweringContext& loweringContext,
    bool reverseDirection)
    : impl_(std::make_unique<Impl>(rule, direction, model, loweringContext, reverseDirection)) {}

LegacyNetworkRuleKernel::~LegacyNetworkRuleKernel() = default;
LegacyNetworkRuleKernel::LegacyNetworkRuleKernel(LegacyNetworkRuleKernel&&) noexcept = default;
LegacyNetworkRuleKernel& LegacyNetworkRuleKernel::operator=(LegacyNetworkRuleKernel&&) noexcept = default;

const std::string& LegacyNetworkRuleKernel::name() const noexcept { return impl_->name; }

void LegacyNetworkRuleKernel::setHooks(compile::CompiledRuleExecutionHooks hooks) {
    impl_->publicHooks = std::move(hooks);
    impl_->refreshHooks();
}

void LegacyNetworkRuleKernel::clearPatternMatchCache() {
    impl_->rule.clearPatternMatchCache(*impl_->state);
}

std::size_t LegacyNetworkRuleKernel::expand(
    ast::SpeciesList& species,
    ast::RxnList& reactions,
    std::size_t currentIteration,
    const std::function<bool(const BNGcore::PatternGraph&)>& productFilter,
    std::size_t speciesBoundary) {
    std::function<bool(const ast::SpeciesGraph&)> astProductFilter;
    if (productFilter) {
        astProductFilter =
            [productFilter](const ast::SpeciesGraph& graph) {
                return productFilter(graph.getGraph());
            };
    }
    return impl_->rule.expandRule(
        species, reactions, currentIteration, *impl_->state, astProductFilter,
        speciesBoundary, nullptr, &impl_->astHooks);
}

} // namespace bng::engine
