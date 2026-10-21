#pragma once

#include <cstddef>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include "compile/CompiledRuleExecution.hpp"

namespace BNGcore { class Node; class PatternGraph; }
namespace bng::ast {
class SpeciesList;
class RxnList;
}
namespace bng::compile {
class CompiledModel;
class CompiledRule;
struct CompiledRuleDirection;
class BNGcoreLoweringContext;
}

namespace bng::engine {

// Deliberately isolated compatibility boundary around the mature
// ast::ReactionRule expansion kernel. NetworkRulePlan and other compiled-facing
// engine code should not include ast/ReactionRule.hpp directly.
//
// The execution decisions themselves are compile-owned: they arrive as
// compile::CompiledRuleExecutionHooks, so the kernel never has to recover
// them from a reconstructed AST rule.
class LegacyNetworkRuleKernel {
public:
    LegacyNetworkRuleKernel(const compile::CompiledRule& rule,
                            const compile::CompiledRuleDirection& direction,
                            const compile::CompiledModel& model,
                            compile::BNGcoreLoweringContext& loweringContext,
                            bool reverseDirection = false);
    ~LegacyNetworkRuleKernel();
    LegacyNetworkRuleKernel(LegacyNetworkRuleKernel&&) noexcept;
    LegacyNetworkRuleKernel& operator=(LegacyNetworkRuleKernel&&) noexcept;
    LegacyNetworkRuleKernel(const LegacyNetworkRuleKernel&) = delete;
    LegacyNetworkRuleKernel& operator=(const LegacyNetworkRuleKernel&) = delete;

    const std::string& name() const noexcept;
    void setHooks(compile::CompiledRuleExecutionHooks hooks);
    void clearPatternMatchCache();
    std::size_t expand(ast::SpeciesList& species,
                       ast::RxnList& reactions,
                       std::size_t currentIteration,
                       const std::function<bool(const BNGcore::PatternGraph&)>& productFilter,
                       std::size_t speciesBoundary);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace bng::engine
