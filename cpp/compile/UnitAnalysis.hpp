#pragma once

#include <map>
#include <optional>
#include <string>
#include <vector>

#include "Capabilities.hpp"
#include "units/Unit.hpp"

namespace bng::ast { class Model; }

namespace bng::compile {

enum class UnitMode {
    Off,
    Permissive,
    Strict,
};

UnitMode unitMode(const ast::Model& model);

struct UnitAnalysisResult {
    UnitMode mode = UnitMode::Off;
    bool enabled = false;
    std::map<std::string, units::Unit> inferredParameters;
    std::map<std::string, units::Unit> inferredExpressions;
    std::vector<Diagnostic> diagnostics;
};

UnitAnalysisResult analyzeUnits(const ast::Model& model);

} // namespace bng::compile
