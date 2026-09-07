#pragma once

#include <cstddef>
#include <string>
#include <vector>

#include "CompiledRule.hpp"
#include "ast/Model.hpp"

namespace bng::compile {

struct CompiledEnergyFactor {
    std::size_t index = 0;
    std::string label;
    std::string sourcePattern;
    std::string structuralFingerprint;
    std::string energyExpression;
};

// Immutable execution-facing metadata compiled from ast::Model. This initial
// layer deliberately contains no mutable simulation state, so one instance can
// be shared across trajectories and execution backends.
class CompiledModel {
public:
    explicit CompiledModel(const ast::Model& model);

    const std::vector<CompiledRule>& rules() const { return rules_; }
    const std::vector<CompiledEnergyFactor>& energyFactors() const {
        return energyFactors_;
    }
    std::size_t energyPatternCount() const { return energyFactors_.size(); }

private:
    std::vector<CompiledRule> rules_;
    std::vector<CompiledEnergyFactor> energyFactors_;
};

} // namespace bng::compile
