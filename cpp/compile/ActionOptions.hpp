#pragma once

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <limits>
#include <map>
#include <optional>
#include <string>

#include "ast/Model.hpp"
#include "compile/SimulationMethod.hpp"

namespace bng::compile {

// ---------------------------------------------------------------------------
// Source text helpers
//
// These are the only spellings of the action language's values.  They live in
// one place so every action option is read with the same rules.
// ---------------------------------------------------------------------------

inline std::string trim(std::string value) {
    auto first = std::find_if_not(value.begin(), value.end(), [](unsigned char c) {
        return std::isspace(c) != 0;
    });
    auto last = std::find_if_not(value.rbegin(), value.rend(), [](unsigned char c) {
        return std::isspace(c) != 0;
    }).base();
    if (first >= last) {
        return {};
    }
    return std::string(first, last);
}

inline std::string stripQuotes(const std::string& text) {
    if (text.size() >= 2 &&
        ((text.front() == '"' && text.back() == '"') ||
         (text.front() == '\'' && text.back() == '\''))) {
        return text.substr(1, text.size() - 2);
    }
    return text;
}

inline std::string lowercase(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

// ---------------------------------------------------------------------------
// Typed option access
// ---------------------------------------------------------------------------

// The numeric value of an action option.  The value may be a literal or an
// expression over the model's parameters.  A rejected value quotes the source
// spelling.
double parseScalarValue(const std::string& text, ast::Model& model);

// The strict flag convention: "1", "true", "yes" and "on" are true, "0",
// "false", "no" and "off" are false and any other spelling is rejected.
bool parseBoolean(const std::string& text, bool defaultValue = false);

// A non-negative integer value.
std::size_t parseNonNegativeCount(const std::string& text,
                                  ast::Model& model,
                                  const std::string& name);

// The step count of a simulation option.  The value must be a non-negative
// integer and may use the Safe-Perl numeric expression forms.
std::size_t parseSimulationStepCount(const std::string& text, ast::Model& model);

// A typed view over one action's arguments.
//
// Every action option is read through this class, so the default, the
// validation and the source spelling of an option are decided in one place.
// A diagnostic quotes the spelling as written in the source.
class ActionOptions {
public:
    ActionOptions(const ast::Action& action, ast::Model& model)
        : action_(action), model_(model) {}

    bool has(const std::string& key) const {
        return action_.arguments.find(key) != action_.arguments.end();
    }

    // True when the option carries a value.  An option that is absent and an
    // option whose text is empty are the same thing: the option was not
    // given.
    bool hasValue(const std::string& key) const {
        const auto found = action_.arguments.find(key);
        if (found == action_.arguments.end()) {
            return false;
        }
        return !stripQuotes(trim(found->second)).empty();
    }

    // The argument text exactly as written in the source.  It is the text a
    // diagnostic quotes when an option is rejected.
    std::string sourceSpelling(const std::string& key) const {
        const auto found = action_.arguments.find(key);
        if (found == action_.arguments.end()) {
            return {};
        }
        return found->second;
    }

    // The flag convention of the BNGL action language: "1" and "true" are
    // true and every other spelling is false.
    bool flag(const std::string& key, bool fallback) const {
        if (!hasValue(key)) {
            return fallback;
        }
        const auto value = lowercase(stripQuotes(sourceSpelling(key)));
        return value == "1" || value == "true";
    }

    // The flag convention of the exporter actions: "1", "on" and "true" are
    // true and every other spelling is false.
    bool flagOn(const std::string& key, bool fallback) const {
        if (!hasValue(key)) {
            return fallback;
        }
        const auto value = lowercase(stripQuotes(sourceSpelling(key)));
        return value == "1" || value == "on" || value == "true";
    }

    // The default-on flag convention: only "0", "false" and "off" are false.
    bool flagUnlessOff(const std::string& key, bool fallback) const {
        if (!hasValue(key)) {
            return fallback;
        }
        const auto value = lowercase(stripQuotes(sourceSpelling(key)));
        return !(value == "0" || value == "false" || value == "off");
    }

    // The strict flag convention: "1", "true", "yes" and "on" are true, "0",
    // "false", "no" and "off" are false and any other spelling is rejected.
    bool strictFlag(const std::string& key, bool fallback) const {
        if (!hasValue(key)) {
            return fallback;
        }
        return parseBoolean(sourceSpelling(key), fallback);
    }
    // A numeric option.  The value may be a literal or an expression over the
    // model's parameters.
    double number(const std::string& key, double fallback) const {
        const auto value = optionalNumber(key);
        return value.has_value() ? *value : fallback;
    }

    std::optional<double> optionalNumber(const std::string& key) const {
        if (!hasValue(key)) {
            return std::nullopt;
        }
        return parseScalarValue(sourceSpelling(key), model_);
    }

    // A count option.  The value must be a non-negative integer.
    std::size_t count(const std::string& key, std::size_t fallback) const {
        const auto value = optionalCount(key);
        return value.has_value() ? *value : fallback;
    }

    std::optional<std::size_t> optionalCount(const std::string& key) const {
        if (!hasValue(key)) {
            return std::nullopt;
        }
        return parseSimulationStepCount(sourceSpelling(key), model_);
    }

    // An internal event count, such as an output cadence or a step budget.
    // The value must be a non-negative integer and the diagnostic names the
    // option.
    std::optional<std::size_t> optionalEventCount(const std::string& key) const {
        if (!hasValue(key)) {
            return std::nullopt;
        }
        return parseNonNegativeCount(sourceSpelling(key), model_, key);
    }

    // A textual option.  The value keeps its quotes only when they are part
    // of the spelling.
    std::string text(const std::string& key, const std::string& fallback) const {
        const auto found = action_.arguments.find(key);
        if (found == action_.arguments.end()) {
            return fallback;
        }
        return found->second;
    }

    // The method-dependent options this action requests.  The set is read
    // once so every surface decides the same way whether an option is
    // acceptable for the selected method.
    SimulationOptionSupport requestedSimulationOptions() const {
        SimulationOptionSupport requested;
        if (const auto value = optionalNumber("max_step")) {
            requested.maxStep = *value > 0.0;
        }
        requested.steadyState = flag("steady_state", false);
        requested.sparse = flag("sparse", false);
        requested.stopIf = hasValue("stop_if");
        requested.sampleTimes = hasValue("sample_times");
        if (const auto value = optionalEventCount("output_step_interval")) {
            requested.outputStepInterval = *value > 0;
        }
        if (const auto value = optionalEventCount("max_sim_steps")) {
            requested.maxSimSteps = *value > 0;
        }
        if (const auto value = optionalNumber("check_product_scale")) {
            requested.checkProductScale = *value > 0.0;
        }
        return requested;
    }

private:
    const ast::Action& action_;
    ast::Model& model_;
};

// Apply the shared time-grid options to a target that carries the same
// fields.  An option that is absent keeps the target's own default, so each
// consumer keeps its own documented defaults while the reading of a provided
// option is decided once.
template <class Target>
void applyTimeGridOptions(const ActionOptions& options, Target& target) {
    if (const auto value = options.optionalNumber("t_start")) {
        target.tStart = *value;
    }
    if (const auto value = options.optionalNumber("t_end")) {
        target.tEnd = *value;
    }
    if (const auto value = options.optionalCount("n_steps")) {
        target.nSteps = *value;
    }
    if (const auto value = options.optionalNumber("atol")) {
        target.atol = *value;
    }
    if (const auto value = options.optionalNumber("rtol")) {
        target.rtol = *value;
    }
}

} // namespace bng::compile
