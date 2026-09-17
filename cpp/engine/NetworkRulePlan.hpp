#pragma once

#include <cstddef>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include "compile/CompiledModel.hpp"
#include "compile/PatternLowering.hpp"

namespace bng::ast { class SpeciesGraph; class SpeciesList; class RxnList; }

namespace bng::engine {

// Backend-specific lowering of one resolved BioNetGen rule direction into the
// mature native network-expansion engine. The semantic input is CompiledRule;
// ast::ReactionRule is retained only as a private execution implementation.
class NetworkRulePlan {
public:
    NetworkRulePlan(const compile::CompiledRule& rule,
                    const compile::CompiledRuleDirection& direction,
                    const compile::CompiledModel& model,
                    compile::BNGcoreLoweringContext& loweringContext,
                    bool reverseDirection = false);
    ~NetworkRulePlan();
    NetworkRulePlan(NetworkRulePlan&&) noexcept;
    NetworkRulePlan& operator=(NetworkRulePlan&&) noexcept;
    NetworkRulePlan(const NetworkRulePlan&) = delete;
    NetworkRulePlan& operator=(const NetworkRulePlan&) = delete;

    const std::string& name() const noexcept;
    void clearPatternMatchCache();

    std::size_t expand(
        ast::SpeciesList& species,
        ast::RxnList& reactions,
        std::size_t currentIteration,
        const std::function<bool(const ast::SpeciesGraph&)>& productFilter,
        std::size_t speciesBoundary);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

std::vector<NetworkRulePlan> lowerNetworkRules(
    const compile::CompiledModel& model,
    compile::BNGcoreLoweringContext& loweringContext);

} // namespace bng::engine
