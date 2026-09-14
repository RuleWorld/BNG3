#pragma once

#include <filesystem>
#include <map>
#include <string>

namespace bng::compile { class CompiledModel; struct ResolvedExpression; }
namespace NFcore {
class CompositeFunction;
class GlobalFunction;
class LocalFunction;
class System;
}

namespace NFinput {

// Backend-facing declaration builders. These consume only the immutable
// BioNetGen compile contract and deliberately know nothing about parser/AST
// ownership. More NFsim sections can migrate behind this seam independently.
bool addOptionsFromCompiled(const bng::compile::CompiledModel& model,
                            NFcore::System* system, bool verbose);
bool addParametersFromCompiled(const bng::compile::CompiledModel& model,
                               NFcore::System* system,
                               std::map<std::string, double>& parameters,
                               bool verbose);
bool addCompartmentsFromCompiled(const bng::compile::CompiledModel& model,
                                 NFcore::System* system, bool verbose);
bool addMoleculeTypesFromCompiled(const bng::compile::CompiledModel& model,
                                  NFcore::System* system,
                                  std::map<std::string, int>& allowedStates,
                                  bool verbose);

bool addObservablesFromCompiled(const bng::compile::CompiledModel& model,
                                NFcore::System* system,
                                bool verbose,
                                int& suggestedTraversalLimit);

bool addSpeciesFromCompiledWithOverrides(
    const bng::compile::CompiledModel& model,
    NFcore::System* system,
    bool verbose,
    const std::map<std::string, double>& seedAmountOverrides);

bool addSpeciesFromCompiled(const bng::compile::CompiledModel& model,
                            NFcore::System* system, bool verbose);

bool addEnergyPatternsFromCompiled(const bng::compile::CompiledModel& model,
                                   NFcore::System* system, bool verbose);

bool addReactionRulesFromCompiled(
    const bng::compile::CompiledModel& model,
    NFcore::System* system,
    bool blockSameComplexBinding,
    bool verbose,
    int& suggestedTraversalLimit,
    const std::filesystem::path& sourcePath = {});

bool addFunctionsFromCompiled(const bng::compile::CompiledModel& model,
                              NFcore::System* system, bool verbose,
                              const std::filesystem::path& sourcePath = {});

// Shared by the compiled function and reaction-rate builders.  Keep TFUN
// execution metadata in the semantic expression tree; callers provide the
// already-created NFsim function object that owns the live counter.
bool configureTableFunctionFromCompiled(
    const bng::compile::CompiledModel& model,
    const bng::compile::ResolvedExpression& table,
    const std::filesystem::path& sourcePath,
    NFcore::System* system,
    NFcore::GlobalFunction* global,
    NFcore::CompositeFunction* composite,
    NFcore::LocalFunction* local,
    std::string& diagnostic);

} // namespace NFinput
