#pragma once

#include <cstddef>
#include <string>
#include <vector>

#include "CompiledRule.hpp"
#include "SymbolTable.hpp"
#include "ast/Model.hpp"

namespace bng::compile {

struct CompiledEnergyFactor {
    EnergyPatternId id;
    std::size_t index = 0;
    std::string label;
    std::string sourcePattern;
    std::string structuralFingerprint;
    std::string energyExpression;
    Pattern pattern;
};

struct CompiledFunction {
    FunctionId id;
    std::string name;
    std::vector<std::string> arguments;
    ResolvedExpression expression;
};

struct CompiledObservable {
    ObservableId id;
    std::size_t index = 0;
    std::string name;
    std::string type;
    std::vector<std::string> sourcePatterns;
    std::vector<Pattern> patterns;
};

struct CompiledSeed {
    SeedSpeciesId id;
    std::size_t index = 0;
    std::string sourcePattern;
    std::string amountExpression;
    bool constant = false;
    std::string compartment;
    std::string structuralFingerprint;
    Pattern pattern;
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
    const std::vector<CompiledFunction>& functions() const { return functions_; }
    const std::vector<CompiledObservable>& observables() const {
        return observables_;
    }
    const std::vector<CompiledSeed>& seeds() const { return seeds_; }
    std::size_t energyPatternCount() const { return energyFactors_.size(); }
    const FeatureSet& features() const { return features_; }
    const SymbolTable& symbols() const { return symbols_; }
    const std::vector<Diagnostic>& diagnostics() const { return diagnostics_; }

private:
    FeatureSet features_;
    SymbolTable symbols_;
    std::vector<Diagnostic> diagnostics_;
    std::vector<CompiledRule> rules_;
    std::vector<CompiledFunction> functions_;
    std::vector<CompiledEnergyFactor> energyFactors_;
    std::vector<CompiledObservable> observables_;
    std::vector<CompiledSeed> seeds_;
};

} // namespace bng::compile
