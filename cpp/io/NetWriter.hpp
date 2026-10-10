#pragma once

#include <filesystem>
#include <string>
#include <unordered_map>

#include "ast/Model.hpp"
#include "ast/Expression.hpp"
#include "engine/NetworkGenerator.hpp"

namespace bng::io {

struct DerivedRateInfo {
    std::string paramName;
    std::string expression;
    ast::Expression exprTree;
    bool reverseDirection = false;
    bool asFunction = false;  // true if should be written as function (references observables)
    bool isLocalFunction =
      false; // true if this is a per-species local function rate
  bool isPerReactionLocalFunction = false;  // true if this is a per-species local function rate
    bool isPerReactionArrhenius = false;  // true for energy-pattern per-reaction rates
    // Per-species rate parameters for local function rules:
    // maps reactant species index -> (param name, numeric value)
    std::unordered_map<std::size_t, std::pair<std::string, double>> perSpeciesRates;
    // Per-reaction rate parameters for Arrhenius energy-pattern rules:
    // maps reaction index -> (parameter name, numeric value)
    std::unordered_map<std::size_t, std::pair<std::string, double>> perReactionRates;
    // Time-dependent scoped rates remain no-argument functions evaluated by
    // the simulation clock instead of being folded to per-reaction numbers.
    std::unordered_map<std::size_t,
                       std::pair<std::string, ast::Expression>>
        perReactionRateFunctions;
    // Runtime-only constants for scoped-rate functions whose clock-bearing
    // branches are unreachable after substituting per-reaction scope counts.
    // The symbolic functions above remain unchanged for .net serialization.
    std::unordered_map<std::size_t, double> perReactionRuntimeRateConstants;
};

struct NetWriterOptions {
    bool evaluateExpressions = true;
};

class NetWriter {
public:
    static void write(const std::filesystem::path& outputPath, ast::Model& model, const engine::GeneratedNetwork& network);
    static void write(const std::filesystem::path& outputPath, ast::Model& model, const engine::GeneratedNetwork& network, const NetWriterOptions& opts);
    static std::unordered_map<std::string, DerivedRateInfo> buildDerivedRateParams(
        const ast::Model& model,
        const engine::GeneratedNetwork& network);
    static std::optional<double> computeUnitConversionFactor(
        const ast::Rxn& reaction,
        const ast::Model& model,
        const engine::GeneratedNetwork& network);
};

} // namespace bng::io
