#include "compile/LegacyAstLowering.hpp"
#include "compile/TotalRate.hpp"
#include "ast/EventSupport.hpp"
#include "OdeIntegrator.hpp"

#include <algorithm>
#include <charconv>
#include <cstddef>
#include <cstring>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <limits>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <unordered_set>
#include <future>
#include <mutex>
#include <string>
#include <thread>
#include "engine/BatchSsa.hpp"
#include "engine/gpu/GpuSsaBackend.hpp"

#include "BNGLexer.h"
#include "BNGParser.h"
#include "antlr4-runtime.h"
#include "ast/Function.hpp"
#include "ast/ReactionRule.hpp"
#include "DelayedSemanticsGuard.hpp"
#include "compile/CompiledRateLaw.hpp"
#include "core/Ullmann.hpp"
#include "io/NetWriter.hpp"
#include "parser/BNGAstVisitor.hpp"
#include "parser/PatternGraphBuilder.hpp"
#include "parser/antlr_compat.hpp"

// SUNDIALS/CVODE includes (v7.x API)
#include "cvode/cvode.h"
#include "ida/ida.h"
#include "nvector/nvector_serial.h"
#include "sundials/sundials_context.h"
#include "sundials/sundials_nonlinearsolver.h"
#include "sundials/sundials_types.h"
#include "sunlinsol/sunlinsol_dense.h"
#include "sunlinsol/sunlinsol_spgmr.h"
#include "sunmatrix/sunmatrix_dense.h"
#include "sunnonlinsol/sunnonlinsol_fixedpoint.h"

namespace bng::engine {

namespace {

bool isResultFunction(const std::string& name) {
    // Internal concentration/rate helper functions are implementation
    // details.  Keep the result payload bounded to user-visible algebraic
    // outputs (including species assignment functions), while still allowing
    // the resolver below to use every zero-argument helper internally.
    return !name.empty() && name.front() != '_' &&
           name.rfind("__assign_rule__", 0) != 0 &&
           name.rfind("__rate_rule_in_", 0) != 0 &&
           name.rfind("__rate_rule_out_", 0) != 0 &&
           name.rfind("__rate_rule__", 0) != 0 &&
           name.rfind("__rate_rule_pos__", 0) != 0 &&
           name.rfind("__rate_rule_neg__", 0) != 0;
}

// Delegate rate string evaluation to shared compile-owned implementation.
double evaluateRateString(const std::string& rateStr,
                          const std::function<double(const std::string&)>& resolve) {
    return bng::compile::evaluateRateString(rateStr, resolve);
}

// Checks if 'target' exists in 'text' bounded by non-word characters
// Word characters are defined as alphanumeric or underscore.
bool hasWordBoundaryMatch(std::string_view text, std::string_view target) {
    if (target.empty() || text.length() < target.length()) {
        return false;
    }

    std::size_t pos = 0;
    const std::size_t targetLength = target.length();
    const std::size_t textLength = text.length();
    while ((pos = text.find(target, pos)) != std::string_view::npos) {
        const bool leftBoundary =
            (pos == 0) || (!std::isalnum(static_cast<unsigned char>(text[pos - 1])) && text[pos - 1] != '_');
        if (leftBoundary) {
            const bool rightBoundary =
                (pos + targetLength == textLength) ||
                (!std::isalnum(static_cast<unsigned char>(text[pos + targetLength])) && text[pos + targetLength] != '_');
            if (rightBoundary) return true;
        }
        pos += 1;
    }
    return false;
}

bool hasWordBoundaryMatchCaseInsensitive(std::string_view text, std::string_view target) {
    if (target.empty() || text.length() < target.length()) {
        return false;
    }

    for (std::size_t i = 0; i <= text.length() - target.length(); ++i) {
        bool match = true;
        for (std::size_t j = 0; j < target.length(); ++j) {
            if (std::tolower(static_cast<unsigned char>(text[i + j])) !=
                std::tolower(static_cast<unsigned char>(target[j]))) {
                match = false;
                break;
            }
        }
        if (!match) {
            continue;
        }

        const bool leftBoundary =
            i == 0 || (!std::isalnum(static_cast<unsigned char>(text[i - 1])) && text[i - 1] != '_');
        const bool rightBoundary =
            i + target.length() == text.length() ||
            (!std::isalnum(static_cast<unsigned char>(text[i + target.length()])) &&
             text[i + target.length()] != '_');
        if (leftBoundary && rightBoundary) {
            return true;
        }
    }
    return false;
}

} // anonymous namespace


OdeIntegrator::OdeIntegrator(const ast::Model& model, const GeneratedNetwork& network)
    : model_(model), network_(network), functionEvaluator_(model) {
    for (const auto& reaction : network_.reactions.all()) {
        if (reaction.getDelayExpression()) {
            const double delay = delayedTime(*reaction.getDelayExpression(), model_);
            if (delay > 0.0) historyDelays_.push_back(delay);
        }
    }
    const auto addExpressionDelays = [&](const ast::Expression& root) {
        std::function<void(const ast::Expression&)> visit;
        visit = [&](const ast::Expression& expression) {
            if (expression.kind() == ast::ExpressionKind::Function &&
                expression.name() == "delay") {
                if (expression.args().size() != 2) {
                    throw std::runtime_error("delay(expr, tau) expects two arguments");
                }
                const auto duration = functionEvaluator_.expandFunctions(
                    expression.args()[1]);
                std::function<bool(const ast::Expression&)> isStaticDuration;
                isStaticDuration = [&](const ast::Expression& term) {
                    if (term.kind() == ast::ExpressionKind::Identifier) {
                        if (term.name() == "time" || term.name() == "t") return false;
                        try {
                            return !model_.getParameters().isTimeDependent(term.name());
                        } catch (...) {
                            return false;
                        }
                    }
                    if (term.kind() == ast::ExpressionKind::ObservableRef ||
                        term.kind() == ast::ExpressionKind::TableFunction) {
                        return false;
                    }
                    if (term.kind() == ast::ExpressionKind::Function &&
                        (term.name() == "time" || term.name() == "t" ||
                         term.name() == "tfun")) {
                        return false;
                    }
                    for (const auto& child : term.args()) {
                        if (!isStaticDuration(child)) return false;
                    }
                    return true;
                };
                if (!isStaticDuration(duration)) {
                    // A duration that depends on time or state is evaluated
                    // at every use (Expression checks it is finite and
                    // nonnegative). It has no fixed breakpoints, so the full
                    // trajectory history is recorded at every solver step.
                    hasDynamicExpressionDelay_ = true;
                    hasPositiveExpressionDelay_ = true;
                    for (const auto& child : expression.args()) visit(child);
                    return;
                }
                const double delay = delayedTime(duration, model_);
                if (!std::isfinite(delay) || delay < 0.0) {
                    throw std::runtime_error(
                        "delay duration must be finite and nonnegative");
                }
                if (delay > 0.0) {
                    historyDelays_.push_back(delay);
                    hasPositiveExpressionDelay_ = true;
                }
            }
            for (const auto& child : expression.args()) visit(child);
        };
        visit(root);
    };
    for (const auto& reaction : network_.reactions.all()) {
        if (reaction.getRateExpression()) {
            const auto expanded = functionEvaluator_.expandFunctions(
                *reaction.getRateExpression());
            addExpressionDelays(expanded);
        } else {
            try {
                const auto parsed = parser::parseExpression(reaction.getRateLaw());
                const auto expanded = functionEvaluator_.expandFunctions(parsed);
                addExpressionDelays(expanded);
            } catch (...) {
                if (containsDelayCall(reaction.getRateLaw())) throw;
            }
        }
    }
    for (const auto& function : model_.getFunctions()) {
        if (function.getArgs().empty()) {
            const auto expanded = functionEvaluator_.expandFunctions(
                function.getExpression());
            addExpressionDelays(expanded);
        }
    }
    ast::validateNativeEventSubset(model_);
    if (model_.getEventFormatVersion()) {
        const compile::CompiledModel compiled(model_);
        if (!compiled.valid()) throw std::runtime_error("bng3_events require a valid compiled semantic model");
        for (const auto& event : compiled.events()) {
            NativeEvent native;
            native.id = event.id;
            native.trigger = compile::lowerResolvedExpressionToAst(event.trigger, compiled);
            addExpressionDelays(
                functionEvaluator_.expandFunctions(native.trigger));
            native.initialValue = event.initialValue;
            native.persistent = event.persistent;
            native.useValuesFromTriggerTime = event.useValuesFromTriggerTime;
            if (event.delay) {
                native.delay = compile::lowerResolvedExpressionToAst(
                    *event.delay, compiled);
            }
            if (event.priority) {
                auto priority = compile::lowerResolvedExpressionToAst(
                    *event.priority, compiled);
                bool dynamic = false;
                std::function<void(const ast::Expression&)> inspectPriority =
                    [&](const ast::Expression& expression) {
                        if (expression.kind() == ast::ExpressionKind::ObservableRef) {
                            dynamic = true;
                        }
                        if (expression.kind() == ast::ExpressionKind::Identifier &&
                            (expression.name() == "time" || expression.name() == "t")) {
                            dynamic = true;
                        }
                        for (const auto& child : expression.args()) {
                            inspectPriority(child);
                        }
                    };
                inspectPriority(priority);
                if (dynamic) {
                    native.dynamicPriority = std::move(priority);
                } else {
                    const double value = priority.evaluate([&](const std::string& name) {
                        return model_.getParameters().evaluate(name, 0.0);
                    }, 0.0);
                    if (!std::isfinite(value)) {
                        throw std::runtime_error(
                            "bng3_events priority must be a finite constant");
                    }
                    native.priority = value;
                }
            }
            for (const auto& assignment : event.assignments) {
                auto value = compile::lowerResolvedExpressionToAst(
                    assignment.value, compiled);
                addExpressionDelays(functionEvaluator_.expandFunctions(value));
                native.assignments.push_back(
                    {assignment.target, std::move(value)});
            }
            nativeEvents_.push_back(std::move(native));
        }
        // The instant at which each event's trigger last rose.  An event
        // that rose at the instant it executes has a trigger that holds
        // conceptually, even where the numerical comparison is an equality.
        triggerRoseAt_.assign(nativeEvents_.size(),
                              -std::numeric_limits<double>::infinity());
        // The events that share one trigger are triggered at the same
        // instant, so they share one root function.  Grouping them keeps the
        // solver's root count small and lets the runtime execute a whole
        // group at once, which is what the specification calls a simultaneous
        // execution.
        for (std::size_t index = 0; index < nativeEvents_.size(); ++index) {
            const auto key = nativeEvents_[index].trigger.toString();
            auto group = std::find_if(nativeEventGroups_.begin(), nativeEventGroups_.end(),
                [&](const NativeEventGroup& candidate) {
                    return candidate.trigger.toString() == key;
                });
            if (group == nativeEventGroups_.end()) {
                nativeEventGroups_.push_back({nativeEvents_[index].trigger, {index}});
            } else {
                group->events.push_back(index);
            }
        }
        for (std::size_t group = 0; group < nativeEventGroups_.size(); ++group) {
            for (const auto* conjunct : triggerConjuncts(nativeEventGroups_[group].trigger)) {
                nativeEventRoots_.emplace_back(group, conjunct);
            }
        }
        for (const auto& event : nativeEvents_) {
            for (const auto& assignment : event.assignments) {
                if (model_.getParameters().contains(assignment.target)) {
                    eventAssignedParameterNames_.insert(assignment.target);
                    eventDependentParameterNames_.insert(assignment.target);
                }
            }
        }
        bool addedParameterDependency = true;
        while (addedParameterDependency) {
            addedParameterDependency = false;
            for (const auto& parameter : model_.getParameters().all()) {
                if (eventDependentParameterNames_.find(parameter.getName()) !=
                    eventDependentParameterNames_.end()) {
                    continue;
                }
                ast::Expression expression = parameter.getExpression();
                try {
                    expression = functionEvaluator_.expandFunctions(expression);
                } catch (...) {
                    // The compiled semantic model reports invalid recursive
                    // functions; keep this dependency pass conservative.
                }
                const auto dependencies = expression.getDependencies();
                if (std::any_of(
                        dependencies.begin(), dependencies.end(),
                        [&](const std::string& dependency) {
                            return eventDependentParameterNames_.find(dependency) !=
                                   eventDependentParameterNames_.end();
                        })) {
                    eventDependentParameterNames_.insert(parameter.getName());
                    addedParameterDependency = true;
                }
            }
        }
    }
    compile();
    markContinuousSpecies();
    pruneDiscreteEventRoots();
    validateEventTargets();
    validateEventRootSurface();
}

void OdeIntegrator::setAlgebraicRules(
    const std::vector<std::pair<std::string, std::string>>& rules) {
    algebraicSpeciesIndices_.clear();
    algebraicResiduals_.clear();
    std::unordered_set<std::size_t> assigned;
    for (const auto& [observableName, residualText] : rules) {
        const auto observable = observableIndex_.find(observableName);
        if (observable == observableIndex_.end()) {
            throw std::runtime_error(
                "DAE algebraic target is not a compiled observable: " + observableName);
        }
        const auto& entries = compiledGroups_.at(observable->second).entries;
        if (entries.size() != 1 || std::abs(entries.front().second - 1.0) > 1e-12 ||
            fixedSpecies_.at(entries.front().first)) {
            throw std::runtime_error(
                "DAE algebraic target must identify one nonconstant species: " +
                observableName);
        }
        if (!assigned.insert(entries.front().first).second) {
            throw std::runtime_error(
                "DAE algebraic rules assign the same species more than once");
        }
        algebraicSpeciesIndices_.push_back(entries.front().first);
        algebraicResiduals_.push_back(parser::parseExpression(residualText));
    }
    if (algebraicSpeciesIndices_.size() > nSpecies_) {
        throw std::runtime_error("DAE has more algebraic rules than state variables");
    }
}

int OdeIntegrator::idaResidual(double time, const double* scaledState,
                               const double* scaledDerivative,
                               double* residual) const {
    try {
        std::vector<double> physicalState(nSpecies_);
        std::vector<double> scaledRhs(nSpecies_);
        cvodeDerivs(time, scaledState, scaledRhs.data());
        std::vector<bool> algebraic(nSpecies_, false);
        for (std::size_t i = 0; i < algebraicSpeciesIndices_.size(); ++i) {
            algebraic[algebraicSpeciesIndices_[i]] = true;
        }
        for (std::size_t i = 0; i < nSpecies_; ++i) {
            physicalState[i] = scaledState[i] * cvodeStateScale_[i];
            residual[i] = algebraic[i]
                ? scaledDerivative[i]
                : scaledDerivative[i] - scaledRhs[i];
        }
        for (std::size_t i = 0; i < algebraicSpeciesIndices_.size(); ++i) {
            residual[algebraicSpeciesIndices_[i]] = evaluateExpressionWithHistory(
                algebraicResiduals_[i], time, physicalState.data());
        }
        return 0;
    } catch (...) {
        return -1;
    }
}

void OdeIntegrator::correctAlgebraicState(std::vector<double>& state,
                                          double time,
                                          double tolerance) const {
    const std::size_t count = algebraicSpeciesIndices_.size();
    if (count == 0) return;
    std::vector<double> residual(count);
    std::vector<double> jacobian(count * count);
    std::vector<double> perturbed = state;
    const auto evaluate = [&](const std::vector<double>& values,
                              std::vector<double>& result) {
        for (std::size_t row = 0; row < count; ++row) {
            result[row] = evaluateExpressionWithHistory(
                algebraicResiduals_[row], time, values.data());
            if (!std::isfinite(result[row])) {
                throw std::runtime_error("algebraic residual is not finite");
            }
        }
    };
    const auto norm = [](const std::vector<double>& values) {
        double value = 0.0;
        for (const double item : values) value = std::max(value, std::abs(item));
        return value;
    };
    const double epsilon = std::cbrt(std::numeric_limits<double>::epsilon());
    for (int iteration = 0; iteration < 30; ++iteration) {
        evaluate(state, residual);
        const double residualNorm = norm(residual);
        if (residualNorm <= tolerance) return;
        for (std::size_t column = 0; column < count; ++column) {
            const auto species = algebraicSpeciesIndices_[column];
            const double h = epsilon * std::max(1.0, std::abs(state[species]));
            perturbed[species] = state[species] + h;
            std::vector<double> plus(count);
            evaluate(perturbed, plus);
            perturbed[species] = state[species] - h;
            std::vector<double> minus(count);
            evaluate(perturbed, minus);
            perturbed[species] = state[species];
            for (std::size_t row = 0; row < count; ++row) {
                jacobian[row * count + column] = (plus[row] - minus[row]) / (2.0 * h);
            }
        }
        std::vector<double> matrix = jacobian;
        std::vector<double> step(count);
        for (std::size_t i = 0; i < count; ++i) step[i] = -residual[i];
        for (std::size_t column = 0; column < count; ++column) {
            std::size_t pivot = column;
            for (std::size_t row = column + 1; row < count; ++row) {
                if (std::abs(matrix[row * count + column]) >
                    std::abs(matrix[pivot * count + column])) pivot = row;
            }
            if (std::abs(matrix[pivot * count + column]) <=
                64.0 * std::numeric_limits<double>::epsilon()) {
                throw std::runtime_error(
                    "algebraic constraint Jacobian is singular or inconsistent");
            }
            for (std::size_t j = column; j < count; ++j) {
                std::swap(matrix[column * count + j], matrix[pivot * count + j]);
            }
            std::swap(step[column], step[pivot]);
            const double diagonal = matrix[column * count + column];
            for (std::size_t j = column; j < count; ++j) {
                matrix[column * count + j] /= diagonal;
            }
            step[column] /= diagonal;
            for (std::size_t row = 0; row < count; ++row) {
                if (row == column) continue;
                const double factor = matrix[row * count + column];
                for (std::size_t j = column; j < count; ++j) {
                    matrix[row * count + j] -= factor * matrix[column * count + j];
                }
                step[row] -= factor * step[column];
            }
        }
        double damping = 1.0;
        bool accepted = false;
        for (int attempt = 0; attempt < 20; ++attempt) {
            for (std::size_t i = 0; i < count; ++i) {
                const auto species = algebraicSpeciesIndices_[i];
                perturbed[species] = state[species] + damping * step[i];
            }
            std::vector<double> candidate(count);
            try {
                evaluate(perturbed, candidate);
                if (norm(candidate) < residualNorm) {
                    state.swap(perturbed);
                    accepted = true;
                    break;
                }
            } catch (const std::exception&) {
            }
            perturbed = state;
            damping *= 0.5;
        }
        if (!accepted) {
            throw std::runtime_error(
                "algebraic constraint is singular or inconsistent; no consistent state was found");
        }
    }
    throw std::runtime_error(
        "algebraic constraint solve did not converge to a consistent state");
}

void OdeIntegrator::compile() {
    nSpecies_ = network_.species.size();
    fixedSpecies_.resize(nSpecies_, false);

    for (std::size_t i = 0; i < nSpecies_; ++i) {
        fixedSpecies_[i] = network_.species.get(i).isConstant();
    }

    // Compile reactions
    auto paramResolver = [&](const std::string& name) -> double {
        return model_.getParameters().evaluate(name);
    };
    const auto rateSymbols = bng::compile::SymbolTable::fromModel(model_);
    const auto hasRuntimeRateDependencies = [&](const ast::Expression& expression) {
        const auto rate = bng::compile::CompiledRateLaw::compile(expression, rateSymbols);
        const auto& dependencies = rate.dependencies();
        if (dependencies.requiresRuntimeEvaluation()) return true;
        const auto& parameters = model_.getParameters().all();
        for (const auto& reference : rate.references()) {
            if (reference.kind == bng::compile::SymbolKind::Parameter &&
                reference.index < parameters.size() &&
                model_.getParameters().isTimeDependent(
                    parameters[reference.index].getName())) {
                return true;
            }
            if (reference.kind == bng::compile::SymbolKind::Parameter &&
                reference.index < parameters.size() &&
                eventDependentParameterNames_.find(
                    parameters[reference.index].getName()) !=
                    eventDependentParameterNames_.end()) {
                return true;
            }
        }
        return false;
    };
    const auto rateTextHasRuntimeDependencies = [&](const std::string& text)
        -> std::optional<bool> {
        try {
            return hasRuntimeRateDependencies(parser::parseExpression(text));
        } catch (...) {
            return std::nullopt;
        }
    };

    // Build per-reaction derived rate parameter map from NetWriter's naming convention.
    // This handles local functions (%x:: scope prefix), energy patterns, and Arrhenius
    // rates where the NetWriter creates per-reaction derived parameters.
    std::unordered_map<std::size_t, std::pair<std::string, double>> perRxnDerivedRates;
    std::unordered_map<std::size_t, ast::Expression> perRxnDerivedRateFunctions;
    std::unordered_map<std::size_t, double> perRxnDerivedRuntimeRateConstants;
    {
        auto derived = bng::io::NetWriter::buildDerivedRateParams(model_, network_);
        for (const auto& [ruleName, info] : derived) {
            if (info.isPerReactionArrhenius || info.isPerReactionLocalFunction || info.isLocalFunction) {
                for (const auto& [rxnIdx, functionPair] : info.perReactionRateFunctions) {
                    perRxnDerivedRateFunctions[rxnIdx] = functionPair.second;
                }
                for (const auto& [rxnIdx, rate] : info.perReactionRuntimeRateConstants) {
                    perRxnDerivedRuntimeRateConstants[rxnIdx] = rate;
                }
                for (const auto& [rxnIdx, paramPair] : info.perReactionRates) {
                    perRxnDerivedRates[rxnIdx] = paramPair;
                }
                // Also build from perSpeciesRates by walking the reaction list
                if (!info.perReactionRates.empty() ||
                    !info.perReactionRateFunctions.empty() ||
                    !info.perReactionRuntimeRateConstants.empty()) continue;
                std::size_t rxnIdx = 0;
                for (const auto& rxn2 : network_.reactions.all()) {
                    if (rxn2.getOriginRuleName() == ruleName) {
                        if (!rxn2.getReactants().empty()) {
                            auto specIdx = rxn2.getReactants()[0];
                            auto it = info.perSpeciesRates.find(specIdx);
                            if (it != info.perSpeciesRates.end()) {
                                perRxnDerivedRates[rxnIdx] = it->second;
                            }
                        }
                    }
                    ++rxnIdx;
                }
            }
        }
    }

    // Precompute lowercase function names once instead of allocating and
    // transforming them for every reaction/function pair.
    std::vector<std::string> lowerFuncNames;
    lowerFuncNames.reserve(model_.getFunctions().size());
    for (const auto& func : model_.getFunctions()) {
        std::string name = func.getName();
        std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        lowerFuncNames.push_back(std::move(name));
    }

    std::unordered_map<std::string, bng::compile::RateLawKind> typedRateKinds;
    for (const auto& rule : model_.getReactionRules()) {
        if (!rule.getRates().empty()) {
            typedRateKinds.emplace(
                rule.getRuleName(),
                bng::compile::CompiledRateLaw::compile(rule.getRates().front()).kind);
        }
    }
    const auto typedRateKindForOrigin = [&](std::string origin)
        -> std::optional<bng::compile::RateLawKind> {
        auto find = [&](const std::string& candidate)
            -> std::optional<bng::compile::RateLawKind> {
            const auto it = typedRateKinds.find(candidate);
            if (it == typedRateKinds.end()) return std::nullopt;
            return it->second;
        };
        if (auto kind = find(origin)) return kind;
        if (origin.rfind("_reverse__", 0) == 0) {
            origin = origin.substr(std::string("_reverse__").size());
        } else if (!origin.empty() && origin.front() == '_') {
            origin.erase(origin.begin());
        }
        if (origin.size() > std::string("_reverse").size() &&
            origin.rfind("_reverse") == origin.size() - std::string("_reverse").size()) {
            origin.erase(origin.size() - std::string("_reverse").size());
        }
        return find(origin);
    };
    const auto totalRateForOrigin = [&](const std::string& origin) {
        // The total-rate decision belongs to the shared capability owner,
        // which also resolves the reverse direction of a rule; a consumer
        // that re-derives it from the rule name alone cannot see that
        // direction.
        return bng::compile::isTotalRateReaction(model_, origin);
    };

    std::string lowerRawRL;
    bool lowerRawRLPopulated = false;
    std::function<bool(const ast::Expression&, std::unordered_set<std::string>&)>
        expressionReadsTime;
    expressionReadsTime = [&](const ast::Expression& expression,
                              std::unordered_set<std::string>& visitedFunctions) {
        switch (expression.kind()) {
        case ast::ExpressionKind::Identifier: {
            const auto& name = expression.name();
            return name == "time" || name == "t" ||
                   (model_.getParameters().contains(name) &&
                    model_.getParameters().isTimeDependent(name));
        }
        case ast::ExpressionKind::Function: {
            const auto& name = expression.name();
            const auto& args = expression.args();
            if (name == "time" || name == "t") {
                return true;
            }
            // TFUN(name) uses the simulation clock. With an explicit counter,
            // only that counter determines time dependence; the table name is
            // metadata and must not be resolved as a model parameter.
            if (name == "TFUN" || name == "tfun") {
                if (args.size() == 1) {
                    return true;
                }
                return !args.empty() && expressionReadsTime(args.front(), visitedFunctions);
            }
            for (const auto& arg : args) {
                if (expressionReadsTime(arg, visitedFunctions)) {
                    return true;
                }
            }
            for (const auto& function : model_.getFunctions()) {
                if (function.getName() == name &&
                    visitedFunctions.insert(name).second &&
                    expressionReadsTime(function.getExpression(), visitedFunctions)) {
                    return true;
                }
            }
            return false;
        }
        case ast::ExpressionKind::TableFunction:
        case ast::ExpressionKind::Unary:
        case ast::ExpressionKind::Binary:
            for (const auto& arg : expression.args()) {
                if (expressionReadsTime(arg, visitedFunctions)) {
                    return true;
                }
            }
            return false;
        case ast::ExpressionKind::ObservableRef: {
            // Imported .net rates are parsed without the typed lowering that
            // rewrites model-function references to Function nodes. Keep
            // walking their arguments and declarations so time dependence is
            // not lost at this representation boundary.
            for (const auto& arg : expression.args()) {
                if (expressionReadsTime(arg, visitedFunctions)) {
                    return true;
                }
            }
            for (const auto& function : model_.getFunctions()) {
                if (function.getName() == expression.name() &&
                    visitedFunctions.insert(expression.name()).second &&
                    expressionReadsTime(function.getExpression(), visitedFunctions)) {
                    return true;
                }
            }
            return false;
        }
        case ast::ExpressionKind::Number:
            return false;
        }
        return false;
    };
    std::size_t rxnIndex = 0;
    for (const auto& rxn : network_.reactions.all()) {
        lowerRawRLPopulated = false;
        CompiledReaction crxn;
        crxn.reactantIndices = rxn.getReactants();
        crxn.productIndices = rxn.getProducts();
        crxn.statFactor = rxn.getFactor();
        crxn.delay = rxn.getDelayExpression()
            ? delayedTime(*rxn.getDelayExpression(), model_) : 0.0;
        crxn.nonConsuming = rxn.isNonConsuming();
        // The rule-level TotalRate decision is kept apart from the
        // per-reaction flag.  A special rate law reuses that flag to mean
        // "this rate is already a complete flux", and that reuse must not
        // hide the rule's TotalRate modifier from the statistical-factor
        // decision made further down.
        const bool ruleIsTotalRate = totalRateForOrigin(rxn.getOriginRuleName());
        crxn.isAbsoluteFlux = bng::compile::isAbsoluteFluxReaction(model_, rxn);
        crxn.isTotalRate = ruleIsTotalRate || crxn.isAbsoluteFlux;

        // TotalRate omits the reaction-center symmetry factor.  Finite-network
        // authored BNGL laws still receive reactant counts below; only the
        // separately marked Atomizer absolute flux omits those factors too.
        const auto& originRuleName = rxn.getOriginRuleName();

        // Fast path: If NetWriter pre-computed a per-reaction derived rate parameter
        // (local functions with %x:: scope prefix or energy patterns), use it directly.
        // The derived value is the raw rate (e.g. exp(-(Ea0 + phi*DG/RT))), so we
        // still need to apply unit conversion (for bimolecular reactions in
        // compartments) and the statistical factor, matching what Perl writes in
        // the .net reactions section.
        {
            auto runtimeConstantIt =
                perRxnDerivedRuntimeRateConstants.find(rxnIndex);
            if (runtimeConstantIt != perRxnDerivedRuntimeRateConstants.end()) {
                double rate = runtimeConstantIt->second;
                if (!crxn.isTotalRate) {
                    const auto unitFactor =
                        bng::io::NetWriter::computeUnitConversionFactor(
                            rxn, model_, network_);
                    if (unitFactor.has_value()) rate *= *unitFactor;
                    if (std::abs(rxn.getFactor() - 1.0) >= 1e-9)
                        rate *= rxn.getFactor();
                }
                crxn.rateConstant = rate;
                crxn.isFunctional = false;
                crxn.isTimeDependent = false;
                compiledRxns_.push_back(crxn);
                ++rxnIndex;
                continue;
            }
            auto functionIt = perRxnDerivedRateFunctions.find(rxnIndex);
            if (functionIt != perRxnDerivedRateFunctions.end()) {
                auto rateExpression = functionIt->second;
                double combinedFactor = 1.0;
                if (!crxn.isTotalRate) {
                    const auto unitFactor = bng::io::NetWriter::computeUnitConversionFactor(
                        rxn, model_, network_);
                    if (unitFactor.has_value()) combinedFactor *= *unitFactor;
                    combinedFactor *= rxn.getFactor();
                }
                if (std::abs(combinedFactor - 1.0) >= 1e-9) {
                    rateExpression = ast::Expression::binary(
                        "*", ast::Expression::number(combinedFactor),
                        std::move(rateExpression));
                }
                crxn.functionalRateExpr = std::move(rateExpression);
                crxn.compiledRateLaw = bng::compile::CompiledRateLaw::compile(
                    *crxn.functionalRateExpr, rateSymbols);
                crxn.rateConstant = 0.0;
                crxn.isFunctional = true;
                std::unordered_set<std::string> visitedFunctions;
                crxn.isTimeDependent = expressionReadsTime(
                    *crxn.functionalRateExpr, visitedFunctions);
                hasFunctionalRates_ = true;
                compiledRxns_.push_back(crxn);
                ++rxnIndex;
                continue;
            }
            auto drIt = perRxnDerivedRates.find(rxnIndex);
            if (drIt != perRxnDerivedRates.end()) {
                double rate = drIt->second.second;  // numeric value
                if (!crxn.isTotalRate) {
                    const auto unitFactor = bng::io::NetWriter::computeUnitConversionFactor(rxn, model_, network_);
                    if (unitFactor.has_value()) rate *= *unitFactor;
                }
                if (!crxn.isTotalRate && std::abs(rxn.getFactor() - 1.0) >= 1e-9) {
                    rate *= rxn.getFactor();
                }
                crxn.rateConstant = rate;
                crxn.isFunctional = false;
                compiledRxns_.push_back(crxn);
                ++rxnIndex;
                continue;
            }
        }

        // Build the complete rate string that NetWriter writes to .net file
        // Format: [unitConvFactor*][statFactor*]derivedParam OR [statFactor*]rawRate
        std::ostringstream rateStrBuilder;
        // This text is parsed back into the executable rate expression. The
        // stream default of six digits changes nonterminating volume factors.
        rateStrBuilder << std::setprecision(std::numeric_limits<double>::max_digits10);
        bool foundDerived = false;

        if (!originRuleName.empty()) {
            // Check if this is an Arrhenius rate with a derived parameter
            const bool isReverse = originRuleName.rfind("_reverse__", 0) == 0;
            std::string ruleBase = isReverse
                ? originRuleName.substr(std::string("_reverse__").size())
                : originRuleName;

            // Remove leading underscore if present
            if (!ruleBase.empty() && ruleBase[0] == '_' && ruleBase != "_reverse") {
                ruleBase = ruleBase.substr(1);
            }

            const std::string derivedParamName = isReverse
                ? ("__reverse__" + ruleBase + "_local1")
                : ("__" + ruleBase + "_local1");

            // Also try alternative naming: {ruleName}Rate_{rxnIndex} (energy pattern format)
            const std::string rxnLabel = rxn.getLabel();
            // Extract reaction index from label (e.g., "R1|..." -> look for "R1Rate_1")
            std::string altDerivedName;
            {
                // Try: ruleBase + "Rate_" + "1" (per-species index, usually 1 for single-species)
                std::string altBase = ruleBase;
                if (altBase.front() == '_') altBase = altBase.substr(1);
                altDerivedName = altBase + "Rate_1";
                // Also try reverse: "R1rRate_1" for reverse rules
                if (isReverse) {
                    altDerivedName = altBase + "rRate_1";
                }
            }

            // Check if any derived parameter exists
            try {
                paramResolver(derivedParamName);
                foundDerived = true;

                // Build rate string with unit conversion and derived param
                // This matches what NetWriter writes: unitFactor*statFactor*derivedParam
                if (!crxn.isTotalRate) {
                    const auto unitFactor = bng::io::NetWriter::computeUnitConversionFactor(rxn, model_, network_);
                    if (unitFactor.has_value()) rateStrBuilder << *unitFactor << "*";
                }
                if (!crxn.isTotalRate && std::abs(rxn.getFactor() - 1.0) >= 1e-9) {
                    rateStrBuilder << rxn.getFactor() << "*";
                }
                rateStrBuilder << derivedParamName;
            } catch (const std::exception& e) {
                // Try alternative name format (energy pattern derived params)
                try {
                    paramResolver(altDerivedName);
                    foundDerived = true;
                    const auto unitFactor2 = crxn.isTotalRate
                        ? std::optional<double>{}
                        : bng::io::NetWriter::computeUnitConversionFactor(rxn, model_, network_);
                    // Reset and rebuild with alternative name
                    rateStrBuilder.str("");
                    rateStrBuilder.clear();
                    if (unitFactor2.has_value()) {
                        rateStrBuilder << *unitFactor2 << "*";
                    }
                                if (!crxn.isTotalRate && std::abs(rxn.getFactor() - 1.0) >= 1e-9) {
                                    rateStrBuilder << rxn.getFactor() << "*";
                                }
                    rateStrBuilder << altDerivedName;
                } catch (const std::exception&) {
                    // Also try the rate string from .net directly (it may already be the param name)
                    // The .net writes "R1Rate_1" but the Rxn has "Arrhenius(phi,Ea_AB)"
                    // Check all model parameters for one matching the reaction's origin rule
                    const auto rateNameSeparator = altDerivedName.rfind('_');
                    // Rule labels such as R1 can occur inside unrelated
                    // parameters (for example proAUR1_degradation_rate).
                    // Keep the legacy fallback anchored to the NetWriter
                    // derived-rate prefix.
                    const std::string derivedRatePrefix =
                        rateNameSeparator == std::string::npos
                            ? std::string{}
                            : altDerivedName.substr(0, rateNameSeparator + 1);
                    for (const auto& param : model_.getParameters().all()) {
                        const auto& pname = param.getName();
                        if (derivedRatePrefix.empty() ||
                            pname.compare(0, derivedRatePrefix.size(), derivedRatePrefix) != 0) {
                            continue;
                        }
                        if (pname.find("Rate") != std::string::npos ||
                            pname.find("rate") != std::string::npos) {
                            try {
                                paramResolver(pname);
                                foundDerived = true;
                                rateStrBuilder.str("");
                                rateStrBuilder.clear();
                                const auto uf = crxn.isTotalRate
                                    ? std::optional<double>{}
                                    : bng::io::NetWriter::computeUnitConversionFactor(rxn, model_, network_);
                                if (uf.has_value()) rateStrBuilder << *uf << "*";
                                if (!crxn.isTotalRate && std::abs(rxn.getFactor() - 1.0) >= 1e-9) rateStrBuilder << rxn.getFactor() << "*";
                                rateStrBuilder << pname;
                                break;
                            } catch (...) {}
                        }
                    }
                    if (!foundDerived) foundDerived = false;
                }
            }
        }

        if (!foundDerived) {
            // No derived parameter — apply volume scaling factor (Bug 3 fix)
            if (!crxn.isTotalRate) {
                const auto unitFactor = bng::io::NetWriter::computeUnitConversionFactor(rxn, model_, network_);
                if (unitFactor.has_value()) rateStrBuilder << *unitFactor << "*";
            }
            if (!crxn.isTotalRate && std::abs(rxn.getFactor() - 1.0) >= 1e-9) {
                rateStrBuilder << rxn.getFactor() << "*";
            }
            rateStrBuilder << rxn.getRateLaw();
        }

        std::string rateStr = rateStrBuilder.str();
        const std::string rawRateLaw = rxn.getRateLaw();

        // --- Bug 1 fix: Detect Sat/MM/Hill rate law types ---
        // Format in .net: "Sat kcat Km" or "MM kcat Km" or "Hill Vmax Kh n"
        bool isSatMMHill = false;
        bool isMM = false;  // True when rate law is MM (Michaelis-Menten), not Sat
        bool isHill = false;  // True only for the Hill law; Sat/MM must never take the Hill path
        std::size_t kwLen = 0;
        if (const auto typedKind = typedRateKindForOrigin(originRuleName)) {
            switch (*typedKind) {
            case bng::compile::RateLawKind::Saturation:
                isSatMMHill = true;
                kwLen = 3;
                break;
            case bng::compile::RateLawKind::MichaelisMenten:
                isSatMMHill = true;
                isMM = true;
                kwLen = 2;
                break;
            case bng::compile::RateLawKind::Hill:
                isSatMMHill = true;
                isHill = true;
                kwLen = 4;
                break;
            default:
                break;
            }
        } else {
            std::string rlLower = rawRateLaw;
            std::transform(rlLower.begin(), rlLower.end(), rlLower.begin(), ::tolower);
            // Trim leading whitespace
            auto start = rlLower.find_first_not_of(" \t\r\n");
            if (start != std::string::npos) rlLower = rlLower.substr(start);

            auto isWordPrefix = [](const std::string& str, const std::string& kw) {
                if (str.rfind(kw, 0) != 0) return false;
                if (str.size() == kw.size()) return true;
                char nextC = str[kw.size()];
                return nextC == ' ' || nextC == '\t' || nextC == '\r' || nextC == '\n' || nextC == '(';
            };

            if (isWordPrefix(rlLower, "sat")) {
                isSatMMHill = true;
                kwLen = 3;
            } else if (isWordPrefix(rlLower, "mm")) {
                isSatMMHill = true;
                isMM = true;
                kwLen = 2;
            } else if (isWordPrefix(rlLower, "hill")) {
                isSatMMHill = true;
                isHill = true;
                kwLen = 4;
            }
        }

        if (isSatMMHill && !crxn.reactantIndices.empty()) {
            // Expand Sat/MM/Hill to functional rate with implicit substrate
            // Sat kcat Km → rate = kcat * [S] / (Km + [S])  (TotalRate, no mass-action multiply)
            // Hill Vmax Kh n → rate = Vmax * [S]^n / (Kh^n + [S]^n)
            crxn.isFunctional = true;
            crxn.isTotalRate = true;  // Don't multiply by reactant conc again
            crxn.isAbsoluteFlux = true;
            hasFunctionalRates_ = true;

            // Parse parameters from the rate law string
            // Handle both "Sat kcat Km" and "Sat(kcat, Km)" formats
            std::vector<std::string> paramNames;
            {
                std::string cleaned = rawRateLaw;

                // Trim leading whitespace
                auto startP = cleaned.find_first_not_of(" \t\r\n");
                if (startP != std::string::npos) cleaned = cleaned.substr(startP);
                else cleaned.clear();

                // Trim trailing whitespace
                auto endP = cleaned.find_last_not_of(" \t\r\n");
                if (endP != std::string::npos) cleaned = cleaned.substr(0, endP + 1);

                // Remove keyword
                cleaned = cleaned.substr(kwLen);

                // Trim leading whitespace again
                startP = cleaned.find_first_not_of(" \t\r\n");
                if (startP != std::string::npos) cleaned = cleaned.substr(startP);
                else cleaned.clear();

                if (!cleaned.empty() && cleaned.front() == '(' && cleaned.back() == ')') {
                    cleaned = cleaned.substr(1, cleaned.size() - 2);
                    std::istringstream css(cleaned);
                    std::string tok;
                    while (std::getline(css, tok, ',')) {
                        auto f = tok.find_first_not_of(" \t\r\n");
                        if (f != std::string::npos) {
                            tok.erase(0, f);
                            tok.erase(tok.find_last_not_of(" \t\r\n") + 1);
                            paramNames.push_back(tok);
                        }
                    }
                } else {
                    std::istringstream rlStream(cleaned);
                    std::string tok;
                    while (rlStream >> tok) {
                        paramNames.push_back(tok);
                    }
                }
            }

            // A rate-law argument is either a numeric literal or a symbol.
            // Building it as a bare identifier made a literal unresolvable at
            // evaluation time, which silently zeroed the whole rate.
            auto rateLawArgument = [](const std::string& text) {
                char* end = nullptr;
                const double value = std::strtod(text.c_str(), &end);
                if (end != text.c_str() && end != nullptr && *end == '\0') {
                    return ast::Expression::number(value);
                }
                return ast::Expression::identifier(text);
            };

            // Store a lambda-like expression that will be evaluated in derivs()
            // We build the expression text for the resolver
            std::size_t substrateIdx = crxn.reactantIndices[0];

            // The reference to the reactant at `position` of the reaction's
            // reactant list.
            //
            // A repeated identical reactant does not contribute the plain
            // population: it contributes the number of *distinct* reactant
            // pairs, `population - offset`, exactly as canonical BioNetGen
            // 2.9.3's discrete branch does (`bng2/Network3/src/network.cpp`,
            // `rxn_rate`: a repeated reactant is multiplied by `X - n`).  The
            // offset travels with the reference, so the deterministic and the
            // stochastic evaluations can read the same expression and still
            // use the convention their own law calls for: the deterministic
            // path resolves the reference to the plain population, the
            // stochastic path to `population - offset`.
            const auto reactantReference = [&crxn](std::size_t position) {
                const std::size_t species = crxn.reactantIndices[position];
                const std::size_t offset =
                    identicalReactantOffset(crxn.reactantIndices, position);
                if (offset == 0) {
                    return ast::Expression::identifier(
                        "__substrate_" + std::to_string(species));
                }
                return ast::Expression::identifier(
                    "__substrate_" + std::to_string(species) + "_off" +
                    std::to_string(offset));
            };

            if (paramNames.size() >= 2) {
                // Sat(kcat, Km): rate = kcat * [S] / (Km + [S]) * [other reactants]
                // MM(kcat, Km):  rate = self-consistent MM with quadratic for free substrate
                //   St=reactant[0], Et=reactant[1], b=St-Et-Km, S=0.5*(b+sqrt(b^2+4*St*Km))
                //   rate = kcat * Et * S / (Km + S)   (total rate, no further mass-action multiply)
                // Hill(Vmax, Kh, n): rate = Vmax * [S]^n / (Kh^n + [S]^n) * [other reactants]
                std::string kcat = paramNames[0];
                std::string Km = paramNames[1];

                ast::Expression baseExpr = ast::Expression::number(0.0); // placeholder

                // The keyword decides the shape of the argument list, NOT the
                // argument count.  `Sat(Vmax, Km, S)` names its substrate in the
                // third position, so routing every three-argument law to the
                // Hill branch silently consumed that substrate as the Hill
                // COEFFICIENT and changed the meaning of the model.  Only the
                // Hill keyword may take the Hill branch.
                if (isHill && paramNames.size() >= 3) {
                    // Hill(Vmax, Kh, n): substrate is first reactant
                    baseExpr = ast::Expression::function("Hill",
                        {ast::Expression::identifier(kcat), ast::Expression::identifier(Km),
                         rateLawArgument(paramNames[2]),
                         ast::Expression::identifier("__substrate_" + std::to_string(substrateIdx))});
                    // Multiply by non-substrate reactant concentrations
                    for (std::size_t ri = 1; ri < crxn.reactantIndices.size(); ++ri) {
                        baseExpr = ast::Expression::binary("*", std::move(baseExpr),
                            reactantReference(ri));
                    }
                } else if (isHill) {
                    // Hill(Vmax, Kh) with no exponent: Hill coefficient of one.
                    baseExpr = ast::Expression::function("Hill",
                        {ast::Expression::identifier(kcat), ast::Expression::identifier(Km),
                         ast::Expression::number(1.0),
                         ast::Expression::identifier("__substrate_" + std::to_string(substrateIdx))});
                    for (std::size_t ri = 1; ri < crxn.reactantIndices.size(); ++ri) {
                        baseExpr = ast::Expression::binary("*", std::move(baseExpr),
                            reactantReference(ri));
                    }
                } else if (isMM && paramNames.size() >= 3) {
                    // MM(Vmax, Km, S) with a named substrate: the simple
                    // saturating law, matching ast::Expression's 3-argument MM.
                    baseExpr = ast::Expression::function("Sat",
                        {ast::Expression::identifier(kcat), ast::Expression::identifier(Km),
                         rateLawArgument(paramNames[2])});
                    for (std::size_t ri = 1; ri < crxn.reactantIndices.size(); ++ri) {
                        baseExpr = ast::Expression::binary("*", std::move(baseExpr),
                            reactantReference(ri));
                    }
                } else if (isMM && crxn.reactantIndices.size() >= 2) {
                    if (crxn.reactantIndices[0] == crxn.reactantIndices[1]) {
                        throw std::runtime_error(
                            "MM(kcat,Km) with identical substrate and enzyme "
                            "reactants is unsupported; canonical BioNetGen "
                            "rejects this rate-law configuration");
                    }
                    // MM(kcat, Km) with 2 reactants: self-consistent Michaelis-Menten
                    // Use 4-arg MM(kcat, Km, St, Et) which applies the quadratic formula
                    std::size_t enzymeIdx = crxn.reactantIndices[1];
                    baseExpr = ast::Expression::function("MM",
                        {ast::Expression::identifier(kcat), ast::Expression::identifier(Km),
                         ast::Expression::identifier("__substrate_" + std::to_string(substrateIdx)),
                         ast::Expression::identifier("__substrate_" + std::to_string(enzymeIdx))});
                    // No further mass-action multiply -- MM already includes enzyme
                } else {
                    // Sat(kcat, Km) or MM with single reactant: simple saturation
                    baseExpr = ast::Expression::function("Sat",
                        {ast::Expression::identifier(kcat), ast::Expression::identifier(Km),
                         ast::Expression::identifier("__substrate_" + std::to_string(substrateIdx))});
                    // Multiply by non-substrate reactant concentrations (e.g., enzyme [E])
                    for (std::size_t ri = 1; ri < crxn.reactantIndices.size(); ++ri) {
                        baseExpr = ast::Expression::binary("*", std::move(baseExpr),
                            reactantReference(ri));
                    }
                }

                // A special rate law is a complete flux: the engine does not
                // multiply it by the reactant concentrations.  It does carry
                // the rule's statistical factor and the compartment-volume
                // conversion, because canonical Perl BNG2 2.9.3 writes both
                // as a prefix on the rate law for every rate law type
                // (RateLaw::toString in RateLaw.pm).  Its own network for
                // ``@cell:A() + @cell:A() -> @cell:D() Sat(kcat,K)`` in a
                // 100-unit volume reads ``0.005*Sat kcat K`` with
                // ``unit_conversion=1/100.0``: 0.5 is the statistical factor
                // of the two identical reactants and 0.01 is the volume
                // conversion.  This engine's own network writer emits the
                // same prefix, so the engine has to apply the same two
                // factors or it disagrees with the network it exported.
                //
                // Authored TotalRate keeps the coefficient as written:
                // canonical BioNetGen forces the statistical factor to one
                // (Rxn.pm) and omits its unit conversion. Finite-network
                // reactant dependence is applied later by reactionFlux().
                double combinedFactor = 1.0;
                if (!ruleIsTotalRate) {
                    const auto uf =
                        bng::io::NetWriter::computeUnitConversionFactor(
                            rxn, model_, network_);
                    if (uf.has_value()) combinedFactor *= *uf;
                }
                if (!ruleIsTotalRate && std::abs(rxn.getFactor() - 1.0) >= 1e-9) {
                    combinedFactor *= rxn.getFactor();
                }
                if (std::abs(combinedFactor - 1.0) >= 1e-9) {
                    baseExpr = ast::Expression::binary("*",
                        ast::Expression::number(combinedFactor), std::move(baseExpr));
                }

                crxn.functionalRateExpr = std::move(baseExpr);
            }
        }

        // Check if this reaction has a functional rate (depends on time or observables)
        bool isFunctional = crxn.isFunctional;  // May already be set by Sat/MM/Hill
        const auto& rateExpr = rxn.getRateExpression();

        const auto ensureLowerRawRL = [&]() {
            if (lowerRawRLPopulated) {
                return;
            }
            lowerRawRL = rawRateLaw;
            std::transform(lowerRawRL.begin(), lowerRawRL.end(), lowerRawRL.begin(), [](unsigned char c) {
                return static_cast<char>(std::tolower(c));
            });
            lowerRawRLPopulated = true;
        };

        bool checkedFunctions = false;
        if (!isFunctional && rateExpr.has_value()) {
            isFunctional = hasRuntimeRateDependencies(*rateExpr);
            if (!isFunctional) {
                // When present, the parsed AST is authoritative for the rate
                // expression; its serialized spelling may also carry local-
                // context metadata. A .net-loaded reaction has no AST, so its
                // serialized rate expression is parsed below as the source.
                const auto sourceDependencies = rateTextHasRuntimeDependencies(rawRateLaw);
                if (sourceDependencies.has_value()) {
                    isFunctional = *sourceDependencies;
                    checkedFunctions = true;
                } else {
                    // Keep a narrow compatibility fallback for legacy rate
                    // strings that the current expression parser cannot read.
                    ensureLowerRawRL();
                    if (lowerRawRL.find("time") != std::string::npos ||
                        hasWordBoundaryMatch(lowerRawRL, "t")) {
                        isFunctional = true;
                    }
                }
            }

            if (isFunctional) {
                crxn.isFunctional = true;
                // Use the original parsed rate expression, but wrap with unit
                // conversion factor and stat factor so that compartment-volume
                // scaling is applied even for functional rates.
                ast::Expression funcExpr = *rateExpr;

                double combinedFactor = 1.0;
                if (!crxn.isTotalRate) {
                    const auto uf = bng::io::NetWriter::computeUnitConversionFactor(rxn, model_, network_);
                    if (uf.has_value()) combinedFactor *= *uf;
                }
                if (!crxn.isTotalRate && std::abs(rxn.getFactor() - 1.0) >= 1e-9) combinedFactor *= rxn.getFactor();
                if (std::abs(combinedFactor - 1.0) >= 1e-9) {
                    funcExpr = ast::Expression::binary("*",
                        ast::Expression::number(combinedFactor), std::move(funcExpr));
                }

                crxn.functionalRateExpr = std::move(funcExpr);
                crxn.rateConstant = 0.0;
                hasFunctionalRates_ = true;
            }
        }

        // Bug 2 fix: Also check for user-defined function references OUTSIDE the rateExpr block
        // This catches cases where rateExpr is nullopt but the rate law string references a function
        if (!crxn.isFunctional && !checkedFunctions) {
            ensureLowerRawRL();
            std::size_t functionIndex = 0;
            for (const auto& func : model_.getFunctions()) {
                if (hasWordBoundaryMatchCaseInsensitive(rawRateLaw, lowerFuncNames[functionIndex]) ||
                    hasWordBoundaryMatch(rawRateLaw, func.getName())) {
                    crxn.isFunctional = true;
                    // Parse the full rate law string into an expression so that
                    // compound expressions like "k * funcName()" are preserved.
                    ast::Expression funcExpr2 = ast::Expression::number(0.0);
                    try {
                        funcExpr2 = parser::parseExpression(rawRateLaw);
                    } catch (...) {
                        // Fallback: use bare identifier if parsing fails
                        funcExpr2 = ast::Expression::identifier(func.getName());
                    }

                    // Apply unit conversion and stat factor
                    double combinedFactor2 = 1.0;
                    if (!crxn.isTotalRate) {
                        const auto uf2 = bng::io::NetWriter::computeUnitConversionFactor(rxn, model_, network_);
                        if (uf2.has_value()) combinedFactor2 *= *uf2;
                    }
                    if (!crxn.isTotalRate && std::abs(rxn.getFactor() - 1.0) >= 1e-9) combinedFactor2 *= rxn.getFactor();
                    if (std::abs(combinedFactor2 - 1.0) >= 1e-9) {
                        funcExpr2 = ast::Expression::binary("*",
                            ast::Expression::number(combinedFactor2), std::move(funcExpr2));
                    }

                    crxn.functionalRateExpr = std::move(funcExpr2);
                    crxn.rateConstant = 0.0;
                    hasFunctionalRates_ = true;
                    break;
                }
                ++functionIndex;
            }
        }

        // Evaluate the rate string (only for non-functional, non-Sat/MM rates).
        // Use the full ANTLR parser so that complex expressions like
        // "k1*kPlus()" or "v_translat()/vol" are handled correctly.
        if (!crxn.isFunctional) {
            bool evaluated = false;

            // Try the ANTLR expression parser first — it handles function
            // calls, power operators, and all arithmetic correctly.
            auto tryParseAndEval = [&](const std::string& str) -> bool {
                try {
                    auto parsed = parser::parseExpression(str);

                    // Dependency kinds come from one typed expression walk;
                    // time-dependent parameter values remain model metadata.
                    const bool needsRuntime = hasRuntimeRateDependencies(parsed);

                    if (needsRuntime) {
                        crxn.isFunctional = true;
                        crxn.functionalRateExpr = std::move(parsed);
                        crxn.rateConstant = 0.0;
                        hasFunctionalRates_ = true;
                    } else {
                        crxn.sourceRateExpr = parsed;
                        crxn.rateConstant = parsed.evaluate(paramResolver);
                    }
                    return true;
                } catch (...) {
                    return false;
                }
            };

            // Prefer the full rateStr (includes unit/stat factor prefixes).
            evaluated = tryParseAndEval(rateStr);

            // If that failed, try the raw rate law without prefixes.
            if (!evaluated) {
                evaluated = tryParseAndEval(rawRateLaw);
            }

            // Last resort: the simple recursive descent evaluator for
            // trivial numeric expressions.
            if (!evaluated) {
                try {
                    try {
                        crxn.sourceRateExpr = parser::parseExpression(rateStr);
                    } catch (...) {
                        crxn.sourceRateExpr = parser::parseExpression(rawRateLaw);
                    }
                    crxn.rateConstant = evaluateRateString(rateStr, paramResolver);
                } catch (const std::exception&) {
                    crxn.isFunctional = true;
                    crxn.rateConstant = 0.0;
                    hasFunctionalRates_ = true;
                }
            }
        }

        if (crxn.functionalRateExpr.has_value()) {
            std::unordered_set<std::string> visitedFunctions;
            crxn.isTimeDependent = expressionReadsTime(
                *crxn.functionalRateExpr, visitedFunctions);
            if (!crxn.compiledRateLaw.has_value()) {
                crxn.compiledRateLaw = bng::compile::CompiledRateLaw::compile(
                    *crxn.functionalRateExpr, rateSymbols);
            }
        } else if (crxn.sourceRateExpr.has_value() && !crxn.compiledRateLaw.has_value()) {
            crxn.compiledRateLaw = bng::compile::CompiledRateLaw::compile(
                *crxn.sourceRateExpr, rateSymbols);
        }
        compiledRxns_.push_back(crxn);
        ++rxnIndex;
    }

    // A rate coefficient that is not a finite number cannot be simulated.
    // The SSA would draw the next reaction from a NaN propensity table and
    // the ODE would integrate NaN derivatives, so both engines have to
    // refuse the model instead of running it.
    //
    // This is the first point at which a constant coefficient enters the
    // engine: a rate law with no runtime dependency -- a model function such
    // as `f() = ln(-1)`, a parameter expression, or a derived rate -- is
    // folded into a number here, whatever the reason that number is not
    // finite.  A coefficient that is non-finite only at some later time
    // belongs to a functional rate and is checked when the engine evaluates
    // it.
    for (std::size_t i = 0; i < compiledRxns_.size(); ++i) {
        const auto& rxn = compiledRxns_[i];
        if (rxn.isFunctional) continue;
        if (!std::isfinite(rxn.rateConstant)) {
            throw std::runtime_error(
                "Model has a non-finite functional rate coefficient for reaction " +
                std::to_string(i + 1));
        }
    }

    // Compile observable groups
    compileGroups();

    // Build performance optimization structures
    // 1. Observable name→index map for O(1) lookup in derivs()
    observableIndex_.clear();
    for (std::size_t i = 0; i < compiledGroups_.size(); ++i) {
        observableIndex_[compiledGroups_[i].name] = i;
    }

    // Result functions are immutable for the lifetime of this integrator.
    resultFunctionIndices_.clear();
    for (std::size_t i = 0; i < model_.getFunctions().size(); ++i) {
        const auto& function = model_.getFunctions()[i];
        if (function.getArgs().empty()) {
            if (isResultFunction(function.getName())) {
                resultFunctionIndices_.push_back(i);
            }
        }
    }

    // 2. Pre-allocate groupValues for reuse in derivs()
    groupValues_.resize(compiledGroups_.size(), 0.0);
    functionalRateCoefficients_.resize(compiledRxns_.size(), 0.0);

    // 3. Keep large constant-reaction networks in compact, contiguous arrays
    // for derivs(). Small networks retain the original indexed representation
    // because their one-time packing cost is not amortized by CVODE callbacks.
    constexpr std::size_t compactReactionThreshold = 512;
    constantRxnIndices_.clear();
    constantReactions_.clear();
    constantReactantIndices_.clear();
    constantProductIndices_.clear();
    useCompactConstantReactions_ = false;
    functionalRxnIndices_.clear();
    delayedRxnIndices_.clear();
    for (std::size_t i = 0; i < compiledRxns_.size(); ++i) {
        const auto& reaction = compiledRxns_[i];
        if (reaction.delay > 0.0) {
            delayedRxnIndices_.push_back(i);
            if (reaction.isFunctional) functionalRxnIndices_.push_back(i);
        } else if (reaction.isFunctional) {
            functionalRxnIndices_.push_back(i);
        } else {
            constantRxnIndices_.push_back(i);
        }
    }

    if (constantRxnIndices_.size() >= compactReactionThreshold) {
        useCompactConstantReactions_ = true;
        constantReactions_.reserve(constantRxnIndices_.size());
        constantReactantIndices_.reserve(constantRxnIndices_.size());
        constantProductIndices_.reserve(constantRxnIndices_.size());
        for (const auto idx : constantRxnIndices_) {
            const auto& rxn = compiledRxns_[idx];
            CompiledConstantReaction compact;
            compact.reactantOffset = constantReactantIndices_.size();
            compact.productOffset = constantProductIndices_.size();
            compact.reactantCount = rxn.reactantIndices.size();
            compact.productCount = rxn.productIndices.size();
            compact.rateConstant = rxn.rateConstant;
            compact.isTotalRate = rxn.isTotalRate;
            compact.isAbsoluteFlux = rxn.isAbsoluteFlux;
            constantReactantIndices_.insert(constantReactantIndices_.end(),
                                            rxn.reactantIndices.begin(), rxn.reactantIndices.end());
            constantProductIndices_.insert(constantProductIndices_.end(),
                                           rxn.productIndices.begin(), rxn.productIndices.end());
            constantReactions_.push_back(compact);
        }
    }
}

void OdeIntegrator::compileGroups() {
    compiledGroups_.clear();

    // Note: const_cast needed because buildPatternGraph may infer molecule types
    auto& mutableModel = const_cast<ast::Model&>(model_);

    struct CachedObservablePattern {
        BNGcore::PatternGraph graph;
        std::string compartment;
    };
    struct ParsedPatternInfo {
        const BNGcore::PatternGraph* graph;
        std::string compartment;
        std::string quantifier;
        int quantifierThreshold;
        bool hasQuantifier;
    };
    std::unordered_map<std::string, CachedObservablePattern> parsedObservableCache;

    for (const auto& observable : model_.getObservables()) {
        CompiledGroup group;
        group.name = observable.getName();

        if (const auto& indexedWeights = observable.getIndexedSpeciesWeights();
            indexedWeights.has_value()) {
            std::unordered_map<std::size_t, std::size_t> entryPositions;
            for (const auto& [speciesIndex, weight] : *indexedWeights) {
                if (speciesIndex >= network_.species.size()) {
                    throw std::runtime_error(
                        "Indexed observable " + observable.getName() +
                        " references species index " + std::to_string(speciesIndex) +
                        " outside the generated network");
                }
                if (!std::isfinite(weight)) {
                    throw std::runtime_error(
                        "Indexed observable " + observable.getName() +
                        " has a non-finite species weight");
                }

                const auto [position, inserted] = entryPositions.emplace(
                    speciesIndex, group.entries.size());
                if (inserted) {
                    group.entries.emplace_back(speciesIndex, weight);
                } else {
                    auto& combinedWeight = group.entries[position->second].second;
                    combinedWeight += weight;
                    if (!std::isfinite(combinedWeight)) {
                        throw std::runtime_error(
                            "Indexed observable " + observable.getName() +
                            " has a non-finite combined species weight");
                    }
                }
            }

            // NET groups name exact generated species indices. Do not treat
            // those rows as graph patterns, and preserve an explicitly empty
            // indexed group as an empty observable.
            compiledGroups_.push_back(std::move(group));
            continue;
        }

        std::vector<ParsedPatternInfo> parsedPatterns;
        parsedPatterns.reserve(observable.getPatterns().size());

        // Parse and cache each pattern once before matching it against all
        // species. Quantifier metadata remains per occurrence.
        for (const auto& patternText : observable.getPatterns()) {
            try {
                std::string cleanPattern = patternText;
                std::string quantifier;
                int quantifierThreshold = 0;
                bool hasQuantifier = false;

                static const std::vector<std::string> ops = {">=", "<=", "==", "!=", ">", "<"};
                for (const auto& op : ops) {
                    const auto pos = cleanPattern.rfind(op);
                    if (pos == std::string::npos || pos == 0) {
                        continue;
                    }

                    std::string after = cleanPattern.substr(pos + op.size());
                    after.erase(0, after.find_first_not_of(" \t"));
                    after.erase(after.find_last_not_of(" \t") + 1);
                    bool isInteger = !after.empty();
                    for (const char c : after) {
                        if (!std::isdigit(static_cast<unsigned char>(c))) {
                            isInteger = false;
                            break;
                        }
                    }
                    if (!isInteger) {
                        continue;
                    }

                    std::string before = cleanPattern.substr(0, pos);
                    before.erase(before.find_last_not_of(" \t") + 1);
                    if (before.empty() ||
                        (before.back() != ')' &&
                         !std::isalnum(static_cast<unsigned char>(before.back())) &&
                         before.back() != '_')) {
                        continue;
                    }

                    quantifier = op;
                    quantifierThreshold = std::stoi(after);
                    hasQuantifier = true;
                    cleanPattern = std::move(before);
                    break;
                }

                auto cacheIt = parsedObservableCache.find(cleanPattern);
                if (cacheIt == parsedObservableCache.end()) {
                    antlr4::ANTLRInputStream input(cleanPattern);
                    BNGLexer lexer(&input);
                    antlr4::CommonTokenStream tokens(&lexer);
                    BNGParser parser(&tokens);
                    auto* species = parser.species_def();
                    if (parser.getNumberOfSyntaxErrors() != 0) {
                        throw std::runtime_error("Could not parse observable pattern: " + patternText);
                    }

                    auto graph = bng::parser::buildPatternGraph(species, mutableModel, false);
                    auto compartment = bng::parser::extractSpeciesCompartment(species);
                    cacheIt = parsedObservableCache.emplace(
                        cleanPattern,
                        CachedObservablePattern {std::move(graph), std::move(compartment)})
                                  .first;
                }

                parsedPatterns.push_back({&cacheIt->second.graph,
                                          cacheIt->second.compartment,
                                          std::move(quantifier),
                                          quantifierThreshold,
                                          hasQuantifier});
            } catch (const std::exception& error) {
                throw std::runtime_error("Failed to compile observable " + observable.getName() +
                                         " pattern '" + patternText + "': " + error.what());
            }
        }

        // Match each pattern against all species
        for (std::size_t speciesIndex = 0; speciesIndex < network_.species.size(); ++speciesIndex) {
            std::size_t weight = 0;

            for (const auto& parsedPattern : parsedPatterns) {
                const auto& pattern = *parsedPattern.graph;

                // Compartment matching strategy:
                // 1. Molecule-level compartment (e.g., SARM()@Cyt) -- handled
                //    by Ullmann matcher's Node::operator== compartment check.
                // 2. Species-level prefix compartment (e.g., @PM:L) -- no
                //    compartment on pattern nodes; filter at species level.
                const auto& patternCompartment = parsedPattern.compartment;
                if (!patternCompartment.empty()) {
                    bool patternHasMoleculeCompartment = false;
                    for (auto it = pattern.begin(); it != pattern.end(); ++it) {
                        if (!(*it)->get_compartment().empty()) {
                            patternHasMoleculeCompartment = true;
                            break;
                        }
                    }
                    if (!patternHasMoleculeCompartment) {
                        const auto& speciesCompartment = network_.species.get(speciesIndex).getCompartment();
                        if (speciesCompartment != patternCompartment) {
                            continue;  // Skip -- species-level compartment mismatch
                        }
                    }
                }

                // Count matches (with node-level state and structure validation)
                const auto& targetGraph = network_.species.get(speciesIndex).getSpeciesGraph().getGraph();
                BNGcore::UllmannSGIso matcher(pattern, targetGraph);
                BNGcore::List<BNGcore::Map> maps;
                matcher.find_maps(maps);

                // Post-filter: verify each map respects node states, compartments,
                // and structural roles (molecule vs component vs bond nodes).
                // The Ullmann SGIso matches by type_name which may conflate molecule
                // types and component types that share the same name (e.g., CDKN1A).
                std::size_t matchCount = 0;
                for (auto mapIt = maps.begin(); mapIt != maps.end(); ++mapIt) {
                    bool valid = true;
                    for (auto pnIt = pattern.begin(); pnIt != pattern.end(); ++pnIt) {
                        auto* target = mapIt->mapf(*pnIt);
                        if (!target) { valid = false; break; }
                        // Check state compatibility
                        if (!((*pnIt)->get_state() == target->get_state())) { valid = false; break; }
                        // Check structural role: molecule nodes must map to molecule nodes
                        bool patternIsMol = ((*pnIt)->in_degree() == 0);
                        bool targetIsMol = (target->in_degree() == 0);
                        if (patternIsMol != targetIsMol) { valid = false; break; }
                        // Check per-molecule compartment
                        if (patternIsMol) {
                            const auto& pc = (*pnIt)->get_compartment();
                            if (!pc.empty() && target->get_compartment() != pc) { valid = false; break; }
                        }
                    }
                    if (valid) ++matchCount;
                }

                // Apply quantifier filter if present.
                //
                // BNG2 honours a stoichiometric comparison only for `Species`
                // observables. Perl2/Observable.pm tests `$patt->Quantifier`
                // solely inside the `Type eq "Species"` branch (lines 278-292);
                // the `Molecules` branch (lines 241-256) accumulates raw match
                // counts and never inspects the quantifier at all. So in BNG2
                // `Molecules Q A()>5` and `Molecules Q A()` are the same
                // observable, and the threshold is inert rather than an error.
                //
                // Applying it to `Molecules` here is what produced the wrong
                // zero: `matchCount` is the number of pattern EMBEDDINGS in the
                // species graph, not a molecule count, so `A()>5` against one
                // species `A()` holding 10 molecules compared 1 > 5 and
                // discarded the contribution. Matching BNG2 means gating the
                // filter on the observable type; the `Species` path below it is
                // unchanged and already agrees with BNG2 term for term.
                if (parsedPattern.hasQuantifier &&
                    observable.getType() == "Species") {
                    bool passes = false;
                    const int matchCountInt = static_cast<int>(matchCount);
                    if (parsedPattern.quantifier == ">") passes = matchCountInt > parsedPattern.quantifierThreshold;
                    else if (parsedPattern.quantifier == "<") passes = matchCountInt < parsedPattern.quantifierThreshold;
                    else if (parsedPattern.quantifier == ">=") passes = matchCountInt >= parsedPattern.quantifierThreshold;
                    else if (parsedPattern.quantifier == "<=") passes = matchCountInt <= parsedPattern.quantifierThreshold;
                    else if (parsedPattern.quantifier == "==") passes = matchCountInt == parsedPattern.quantifierThreshold;
                    else if (parsedPattern.quantifier == "!=") passes = matchCountInt != parsedPattern.quantifierThreshold;
                    matchCount = passes ? matchCount : 0;
                }

                // For "Species" observables, each pattern contributes 0 or 1
                // (presence/absence). The total weight is the number of
                // patterns that match, NOT clamped to 1 across all patterns.
                if (observable.getType() == "Species" && matchCount > 0) {
                    matchCount = 1;
                }
                weight += matchCount;
            }

            if (weight > 0) {
                group.entries.push_back({speciesIndex, static_cast<double>(weight)});
            }
        }

        compiledGroups_.push_back(group);
    }
}

void OdeIntegrator::updateFunctions(
    const std::vector<double>& groupValues,
    double time,
    std::vector<double>& functionValues) const {
    functionValues.clear();

    // Functions are not state variables, but zero-argument functions are
    // observable model outputs in SBML (including algebraic species lowered
    // by the modern Atomizer).  Evaluate them against the same observable
    // snapshot used by the rate-law resolver so exported assignment values
    // are on exactly the integration output grid.
    // The model function list and result indices are immutable for this
    // integrator. The history-aware evaluator resolves observables, parameters,
    // and nested delay() calls from one state/time context.
    const auto& functions = model_.getFunctions();
    const auto functionState = historyStateAt(time);

    for (const auto index : resultFunctionIndices_) {
        const auto& function = functions[index];
        try {
            functionValues.push_back(
                evaluateExpressionWithHistory(
                    function.getExpression(), time, functionState.data()));
        } catch (const std::exception&) {
            // Keep a malformed optional function from invalidating an
            // otherwise executable state trajectory.  The writer/parser
            // diagnostics remain the source of truth for unsupported math.
            functionValues.push_back(0.0);
        }
    }
}

std::vector<double> OdeIntegrator::evaluateRateCoefficients(
    double t, const double* y) const {
    std::vector<double> rates;
    rates.reserve(compiledRxns_.size());
    for (const auto& rxn : compiledRxns_) {
        rates.push_back(rxn.rateConstant);
    }
    if (hasFunctionalRates_) {
        // A local scratch keeps this query free of the shared member the ODE
        // path reuses, so it stays safe to call on an integrator that other
        // threads are using.
        std::vector<double> groupValues;
        evaluateFunctionalRateCoefficients(t, y, rates.data(), groupValues);
    }
    return rates;
}

void OdeIntegrator::evaluateFunctionalRateCoefficients(
    double t, const double* y, double* rates,
    std::vector<double>& groupValues, bool failOnError,
    bool discreteReactantCounts) const {
    updateGroups(y, groupValues);

    // Build resolver with O(1) observable lookup. Keep this shared with the
    // validation value hook so it exercises the same compiled expression
    // evaluation used by derivs().
    std::function<double(const std::string&)> resolver;
    resolver = [&](const std::string& name) -> double {
        if (name == "time") return t;

        // TFUN resolution: __tfun_NAME__ -> interpolate at current time (or custom index value)
        if (name.rfind("__tfun_", 0) == 0 && name.size() > 9 && name.substr(name.size() - 2) == "__") {
            auto atPos = name.find("_AT_");
            if (atPos != std::string::npos) {
                std::string tfunName = name.substr(7, atPos - 7);
                try {
                    double val = std::stod(name.substr(atPos + 4, name.size() - atPos - 6));
                    if (tfunRegistry_.has(tfunName)) {
                        return tfunRegistry_.evaluate(tfunName, val);
                    }
                } catch (...) {}
            }
            std::string tfunName = name.substr(7, name.size() - 9);
            if (tfunRegistry_.has(tfunName)) {
                return tfunRegistry_.evaluate(tfunName, t);
            }
        }

        // Sat/MM/Hill substrate references: __substrate_N -> y[N]
        //
        // A reference that carries a count offset, `__substrate_N_offK`, names
        // a repeated identical reactant: the k-th copy of a reactant cannot
        // react with the copies before it, so it contributes `y[N] - K`
        // distinct pairs rather than `y[N]` reactant choices.  The stochastic
        // paths resolve it that way (canonical BioNetGen's discrete branch);
        // the deterministic path resolves it to the plain population
        // (canonical BioNetGen's continuous branch).
        if (name.rfind("__substrate_", 0) == 0) {
            const std::string rest = name.substr(12);
            const std::size_t marker = rest.find("_off");
            const std::string indexText =
                (marker == std::string::npos) ? rest : rest.substr(0, marker);
            std::size_t idx = 0;
            try {
                idx = static_cast<std::size_t>(std::stoul(indexText));
            } catch (...) {
                return 0.0;
            }
            double value = (idx < nSpecies_) ? y[idx] : 0.0;
            if (marker != std::string::npos && discreteReactantCounts) {
                double offset = 0.0;
                try {
                    offset = std::stod(rest.substr(marker + 4));
                } catch (...) {
                    offset = 0.0;
                }
                value = std::max(0.0, value - offset);
            }
            return value;
        }

        const auto observable = observableIndex_.find(name);
        if (observable != observableIndex_.end()) {
            return groupValues[observable->second];
        }

        // `t` must be passed: a parameter whose expression reads `time` is
        // evaluated at the current derivative time, not memoized at t=0.
        static const std::unordered_map<std::string, double> noEventValues;
        const auto& eventValues = activeSimulationSession_
            ? activeSimulationSession_->eventParameterValues
            : noEventValues;
        try {
            return evaluateParameterWithEventState(name, t, eventValues);
        } catch (...) {
            for (const auto& func : model_.getFunctions()) {
                if (func.getName() == name) {
                    return functionEvaluator_.evaluate(
                        ast::Expression::identifier(name), resolver, t);
                }
            }
            throw;
        }
    };

    for (const auto idx : functionalRxnIndices_) {
        const auto& rxn = compiledRxns_[idx];
        double rate;
        if (rxn.compiledRateLaw.has_value() &&
            rxn.compiledRateLaw->resolvedExpression().fullyResolved() &&
            !rxn.compiledRateLaw->dependsOnDelay() &&
            !hasPositiveExpressionDelay_) {
            try {
                bng::compile::RateEvaluationContext ctx;
                ctx.time = t;
                ctx.resolveIdentifier = resolver;
                ctx.resolveLocal = resolver;
                ctx.resolveParameter = [&](std::size_t, const std::string& name) {
                    return resolver(name);
                };
                ctx.resolveObservable = [&](std::size_t, const std::string& name) {
                    return resolver(name);
                };
                ctx.resolveFunction = [&](const std::string& funcName,
                                          const std::vector<double>& args) -> double {
                    if (args.empty()) {
                        return functionEvaluator_.evaluate(
                            ast::Expression::identifier(funcName), resolver, t);
                    }
                    std::vector<ast::Expression> argExprs;
                    argExprs.reserve(args.size());
                    for (double val : args) {
                        argExprs.push_back(ast::Expression::number(val));
                    }
                    return functionEvaluator_.evaluate(
                        ast::Expression::function(funcName, argExprs), resolver, t);
                };
                ctx.discreteReactantCounts = discreteReactantCounts;
                ctx.resolveReactantCount = [&](std::size_t reactantIdx) {
                    if (reactantIdx < rxn.reactantIndices.size()) {
                        const std::size_t specIdx = rxn.reactantIndices[reactantIdx];
                        return (specIdx < nSpecies_) ? y[specIdx] : 0.0;
                    }
                    return 0.0;
                };
                rate = rxn.compiledRateLaw->evaluate(ctx);
            } catch (const std::exception& error) {
                if (failOnError) {
                    throw std::runtime_error(
                        "SSA failed to evaluate functional rate coefficient for "
                        "reaction " + std::to_string(idx + 1) + ": " + error.what());
                }
                rate = rxn.rateConstant;
            }
        } else if (rxn.functionalRateExpr.has_value()) {
            try {
                rate = evaluateExpressionWithHistory(
                    *rxn.functionalRateExpr, t, y, discreteReactantCounts);
            } catch (const std::exception& error) {
                if (failOnError) {
                    throw std::runtime_error(
                        "SSA failed to evaluate functional rate coefficient for "
                        "reaction " + std::to_string(idx + 1) + ": " + error.what());
                }
                rate = rxn.rateConstant;
            }
        } else if (rxn.sourceRateExpr.has_value()) {
            try {
                rate = evaluateExpressionWithHistory(
                    *rxn.sourceRateExpr, t, y, discreteReactantCounts);
            } catch (const std::exception& error) {
                if (failOnError) {
                    throw std::runtime_error(
                        "SSA failed to evaluate functional rate coefficient for "
                        "reaction " + std::to_string(idx + 1) + ": " + error.what());
                }
                rate = rxn.rateConstant;
            }
        } else {
            if (failOnError) {
                throw std::runtime_error(
                    "SSA has no compiled functional rate expression for reaction " +
                    std::to_string(idx + 1));
            }
            rate = rxn.rateConstant;
        }
        if (failOnError && !std::isfinite(rate)) {
            throw std::runtime_error(
                "SSA produced a non-finite functional rate coefficient for reaction " +
                std::to_string(idx + 1));
        }
        rates[idx] = rate;
    }
}

void OdeIntegrator::derivs(double t, const double* y, double* dydt) const {
    // Zero derivatives
    std::fill(dydt, dydt + nSpecies_, 0.0);

    // Update observables for functional rates (using pre-allocated buffer)
    if (hasFunctionalRates_) {
        evaluateFunctionalRateCoefficients(
            t, y, functionalRateCoefficients_.data(), groupValues_);
    }

    // Process constant-rate reactions first (no expression evaluation needed).
    if (useCompactConstantReactions_) {
        // Their small index arrays are flattened so this hot loop does not
        // chase a vector allocation for every reaction.
        for (const auto& rxn : constantReactions_) {
            double rate = rxn.rateConstant;

            if (!rxn.isAbsoluteFlux && rxn.reactantCount > 0) {
                const auto* reactants = constantReactantIndices_.data() + rxn.reactantOffset;
                for (std::size_t i = 0; i < rxn.reactantCount; ++i) {
                    rate *= y[reactants[i]];
                }
            }

            if (rxn.reactantCount > 0) {
                const auto* reactants = constantReactantIndices_.data() + rxn.reactantOffset;
                for (std::size_t i = 0; i < rxn.reactantCount; ++i) { dydt[reactants[i]] -= rate; }
            }
            if (rxn.productCount > 0) {
                const auto* products = constantProductIndices_.data() + rxn.productOffset;
                for (std::size_t i = 0; i < rxn.productCount; ++i) { dydt[products[i]] += rate; }
            }
        }
    } else {
        for (const auto idx : constantRxnIndices_) {
            const auto& rxn = compiledRxns_[idx];
            double rate = rxn.rateConstant;

            if (!rxn.isAbsoluteFlux) {
                for (const auto ri : rxn.reactantIndices) {
                    rate *= y[ri];
                }
            }

            for (const auto ri : rxn.reactantIndices) { dydt[ri] -= rate; }
            for (const auto pi : rxn.productIndices) { dydt[pi] += rate; }
        }
    }

    // Process functional-rate reactions (require expression evaluation)
    if (hasFunctionalRates_) {
        for (const auto idx : functionalRxnIndices_) {
            const auto& rxn = compiledRxns_[idx];
            if (rxn.delay > 0.0) continue;
            double rate = functionalRateCoefficients_[idx];

            if (!rxn.isAbsoluteFlux) {
                for (const auto ri : rxn.reactantIndices) {
                    rate *= y[ri];
                }
            }

            for (const auto ri : rxn.reactantIndices) { dydt[ri] -= rate; }
            for (const auto pi : rxn.productIndices) { dydt[pi] += rate; }
        }
    }

    for (const auto idx : delayedRxnIndices_) {
        const auto& rxn = compiledRxns_[idx];
        const double currentRate = rxn.isFunctional
            ? functionalRateCoefficients_[idx] : rxn.rateConstant;
        const double initiationFlux = reactionFlux(rxn, currentRate, y);
        if (!rxn.nonConsuming) {
            for (const auto ri : rxn.reactantIndices) dydt[ri] -= initiationFlux;
        }

        std::optional<SimulationSession> fallbackSession;
        const auto* session = activeSimulationSession_;
        if (!session) {
            fallbackSession = network_.snapshotSimulationSession();
            session = &*fallbackSession;
        }
        if (session && t >= session->startTime + rxn.delay) {
            const double delayedTimeValue = t - rxn.delay;
            const auto delayedState = historyStateAt(delayedTimeValue);
            double delayedRate = rxn.rateConstant;
            if (rxn.sourceRateExpr) {
                delayedRate = evaluateExpressionWithHistory(
                    *rxn.sourceRateExpr, delayedTimeValue, delayedState.data());
            } else if (rxn.isFunctional) {
                std::vector<double> rates(compiledRxns_.size(), 0.0);
                std::vector<double> groups;
                evaluateFunctionalRateCoefficients(
                    delayedTimeValue, delayedState.data(), rates.data(), groups);
                delayedRate = rates[idx];
            }
            const double completionFlux =
                reactionFlux(rxn, delayedRate, delayedState.data());
            if (rxn.nonConsuming) {
                for (const auto ri : rxn.reactantIndices) dydt[ri] -= completionFlux;
            }
            for (const auto pi : rxn.productIndices) dydt[pi] += completionFlux;
        }
    }

    // Zero derivatives for fixed (constant) species
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        if (fixedSpecies_[i]) {
            dydt[i] = 0.0;
        }
    }
}

double OdeIntegrator::reactionFlux(const CompiledReaction& reaction,
                                  double rateCoefficient,
                                  const double* state) const {
    double flux = rateCoefficient;
    if (!reaction.isAbsoluteFlux) {
        for (const auto reactant : reaction.reactantIndices) {
            flux *= state[reactant];
        }
    }
    return flux;
}

std::vector<double> OdeIntegrator::historyStateAt(double time) const {
    std::optional<SimulationSession> fallbackSession;
    const auto* session = activeSimulationSession_;
    if (!session) {
        fallbackSession = network_.snapshotSimulationSession();
        session = &*fallbackSession;
    }
    if (!session || session->history.empty()) {
        std::vector<double> initial(nSpecies_);
        for (std::size_t i = 0; i < nSpecies_; ++i) {
            initial[i] = network_.species.get(i).getAmount();
        }
        return initial;
    }
    const auto& history = session->history;
    if (time <= history.front().time) return history.front().state;
    if (time >= history.back().time) return history.back().state;

    auto right = std::upper_bound(
        history.begin(), history.end(), time,
        [](double query, const SimulationSession::HistoryPoint& point) {
            return query < point.time;
        });
    if (right == history.begin()) return right->state;
    const auto left = std::prev(right);
    if (std::abs(time - left->time) <= 1e-14) return left->state;
    if (right == history.end()) return left->state;
    const double width = right->time - left->time;
    if (!(width > 0.0)) return right->state;
    const double x = (time - left->time) / width;
    const double x2 = x * x;
    const double x3 = x2 * x;
    const double h00 = 2 * x3 - 3 * x2 + 1;
    const double h10 = x3 - 2 * x2 + x;
    const double h01 = -2 * x3 + 3 * x2;
    const double h11 = x3 - x2;
    std::vector<double> result(nSpecies_);
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        result[i] = h00 * left->state[i] + h10 * width * left->derivative[i] +
                    h01 * right->state[i] + h11 * width * right->derivative[i];
    }
    return result;
}

std::unordered_map<std::string, double> OdeIntegrator::historyParametersAt(
    double time) const {
    std::optional<SimulationSession> fallbackSession;
    const auto* session = activeSimulationSession_;
    if (!session) {
        fallbackSession = network_.snapshotSimulationSession();
        session = &*fallbackSession;
    }
    if (!session || session->history.empty()) return {};
    const auto& history = session->history;
    if (time <= history.front().time) return history.front().parameters;
    if (time > history.back().time + 1e-14) {
        std::unordered_map<std::string, double> current;
        static const std::unordered_map<std::string, double> noEventValues;
        const auto& eventValues = activeSimulationSession_
            ? activeSimulationSession_->eventParameterValues
            : noEventValues;
        for (const auto& parameter : model_.getParameters().all()) {
            try {
                current[parameter.getName()] =
                    evaluateParameterWithEventState(
                        parameter.getName(), time, eventValues);
            } catch (...) {}
        }
        return current;
    }
    auto right = std::upper_bound(
        history.begin(), history.end(), time,
        [](double query, const SimulationSession::HistoryPoint& point) {
            return query < point.time;
        });
    if (right == history.end()) return history.back().parameters;
    if (right == history.begin()) return right->parameters;
    const auto left = std::prev(right);
    if (std::abs(time - left->time) <= 1e-14 ||
        !(right->time > left->time)) return left->parameters;
    const double fraction = (time - left->time) / (right->time - left->time);
    auto values = left->parameters;
    for (const auto& [name, rightValue] : right->parameters) {
        const auto found = left->parameters.find(name);
        if (found != left->parameters.end()) {
            values[name] = found->second + fraction * (rightValue - found->second);
        } else {
            values[name] = rightValue;
        }
    }
    return values;
}

double OdeIntegrator::evaluateExpressionWithHistory(
    const ast::Expression& expression, double time, const double* state,
    bool discreteReactantCounts) const {
    std::function<double(const ast::Expression&, double, const double*,
                         const std::unordered_map<std::string, double>&, bool)> evaluateAt;
    evaluateAt = [&](const ast::Expression& current, double currentTime,
                     const double* currentState,
                     const std::unordered_map<std::string, double>& parameters,
                     bool useCurrentEventValues) {
        std::vector<double> groupValues;
        updateGroups(currentState, groupValues);
        const auto resolver = [&](const std::string& name) -> double {
            if (name == "time" || name == "t") return currentTime;
            if (name.rfind("__substrate_", 0) == 0) {
                const std::string rest = name.substr(12);
                const auto marker = rest.find("_off");
                const auto indexText = marker == std::string::npos
                    ? rest : rest.substr(0, marker);
                try {
                    const auto index = static_cast<std::size_t>(std::stoul(indexText));
                    if (index < nSpecies_) {
                        double value = currentState[index];
                        if (marker != std::string::npos && discreteReactantCounts) {
                            const double offset = std::stod(rest.substr(marker + 4));
                            value = std::max(0.0, value - offset);
                        }
                        return value;
                    }
                } catch (...) {}
                return 0.0;
            }
            if (name.rfind("__tfun_", 0) == 0 && name.size() > 9 &&
                name.substr(name.size() - 2) == "__") {
                const auto atPos = name.find("_AT_");
                if (atPos != std::string::npos) {
                    const auto tfunName = name.substr(7, atPos - 7);
                    try {
                        const double value = std::stod(
                            name.substr(atPos + 4, name.size() - atPos - 6));
                        if (tfunRegistry_.has(tfunName)) {
                            return tfunRegistry_.evaluate(tfunName, value);
                        }
                    } catch (...) {}
                }
                const auto tfunName = name.substr(7, name.size() - 9);
                if (tfunRegistry_.has(tfunName)) {
                    return tfunRegistry_.evaluate(tfunName, currentTime);
                }
            }
            const auto observable = observableIndex_.find(name);
            if (observable != observableIndex_.end() &&
                observable->second < groupValues.size()) {
                return groupValues[observable->second];
            }
            static const std::unordered_map<std::string, double> noEventValues;
            const auto& eventValues = activeSimulationSession_
                ? activeSimulationSession_->eventParameterValues
                : noEventValues;
            if (useCurrentEventValues && !eventValues.empty() &&
                eventDependentParameterNames_.find(name) !=
                    eventDependentParameterNames_.end()) {
                return evaluateParameterWithEventState(
                    name, currentTime, eventValues);
            }
            const auto historicalParameter = parameters.find(name);
            if (historicalParameter != parameters.end()) {
                return historicalParameter->second;
            }
            return evaluateParameterWithEventState(
                name, currentTime,
                useCurrentEventValues ? eventValues : noEventValues);
        };
        const ast::Expression::DelayedEvaluator delayed =
            [&](const ast::Expression& delayedExpression, double delayedTime) {
                const auto delayedState = historyStateAt(delayedTime);
                const auto delayedParameters = historyParametersAt(delayedTime);
                return evaluateAt(delayedExpression, delayedTime,
                                  delayedState.data(), delayedParameters, false);
            };
        return functionEvaluator_.evaluate(current, resolver, currentTime, delayed);
    };
    return evaluateAt(expression, time, state, historyParametersAt(time), true);
}

void OdeIntegrator::recordHistoryPoint(double time,
                                       const std::vector<double>& state) {
    auto* session = activeSimulationSession_;
    if (!session) return;
    std::vector<double> derivative(nSpecies_, 0.0);
    derivs(time, state.data(), derivative.data());
    SimulationSession::HistoryPoint point;
    point.time = time;
    point.state = state;
    point.derivative = std::move(derivative);
    for (const auto& parameter : model_.getParameters().all()) {
        try {
            point.parameters[parameter.getName()] =
                evaluateParameterWithEventState(
                    parameter.getName(), time, session->eventParameterValues);
        } catch (...) {}
    }
    if (!session->history.empty() &&
        std::abs(session->history.back().time - time) <= 1e-14) {
        session->history.back() = std::move(point);
    } else {
        session->history.push_back(std::move(point));
    }
}

void OdeIntegrator::recordHistoryJump(double time,
                                      const std::vector<double>& state) {
    auto* session = activeSimulationSession_;
    if (!session) return;
    std::vector<double> derivative(nSpecies_, 0.0);
    derivs(time, state.data(), derivative.data());
    SimulationSession::HistoryPoint point;
    point.time = time;
    point.state = state;
    point.derivative = std::move(derivative);
    for (const auto& parameter : model_.getParameters().all()) {
        try {
            point.parameters[parameter.getName()] =
                evaluateParameterWithEventState(
                    parameter.getName(), time, session->eventParameterValues);
        } catch (...) {}
    }
    if (!session->history.empty() &&
        std::abs(session->history.back().time - time) <= 1e-14) {
        session->history.push_back(std::move(point));
    } else {
        session->history.push_back(std::move(point));
    }
    if (session->discontinuities.empty() ||
        std::abs(session->discontinuities.back() - time) > 1e-14) {
        session->discontinuities.push_back(time);
    }
}

void OdeIntegrator::cvodeDerivs(double t, const double* y, double* dydt) const {
    if (cvodeStateScale_.size() != nSpecies_) {
        derivs(t, y, dydt);
        return;
    }

    cvodePhysicalState_.resize(nSpecies_);
    cvodePhysicalDerivatives_.resize(nSpecies_);
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        cvodePhysicalState_[i] = y[i] * cvodeStateScale_[i];
    }
    derivs(t, cvodePhysicalState_.data(), cvodePhysicalDerivatives_.data());
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        dydt[i] = cvodePhysicalDerivatives_[i] / cvodeStateScale_[i];
    }
}

void OdeIntegrator::updateGroups(const double* y, std::vector<double>& groupValues) const {
    groupValues.resize(compiledGroups_.size(), 0.0);
    for (std::size_t i = 0; i < compiledGroups_.size(); ++i) {
        double value = 0.0;
        for (const auto& [speciesIdx, weight] : compiledGroups_[i].entries) {
            value += weight * y[speciesIdx];
        }
        groupValues[i] = value;
    }
}

std::vector<double> OdeIntegrator::outputTimes(const OdeOptions& options) const {
    if (!std::isfinite(options.tStart) || !std::isfinite(options.tEnd)) {
        throw std::runtime_error("t_start and t_end must be finite");
    }
    if (options.tEnd < options.tStart) {
        throw std::runtime_error("t_end must be greater than or equal to t_start");
    }

    if (!options.sampleTimes.empty()) {
        std::vector<double> times = options.sampleTimes;
        for (std::size_t i = 0; i < times.size(); ++i) {
            if (!std::isfinite(times[i])) {
                throw std::runtime_error("sample_times must contain only finite values");
            }
            if (times[i] < options.tStart || times[i] > options.tEnd) {
                throw std::runtime_error(
                    "sample_times must lie between t_start and t_end");
            }
            if (i > 0 && times[i] <= times[i - 1]) {
                throw std::runtime_error(
                    "sample_times must be strictly increasing");
            }
        }
        return times;
    }

    if (options.nSteps == 0) {
        throw std::runtime_error("n_steps must be positive");
    }

    const double dt = (options.tEnd - options.tStart) /
                      static_cast<double>(options.nSteps);
    std::vector<double> times;
    times.reserve(options.nSteps + 1);
    for (std::size_t step = 0; step <= options.nSteps; ++step) {
        times.push_back(options.tStart + step * dt);
    }
    return times;
}

std::optional<ast::Expression> OdeIntegrator::parseStopIf(
    const OdeOptions& options) const {
    if (options.stopIf.empty()) {
        return std::nullopt;
    }
    try {
        return parser::parseExpression(options.stopIf);
    } catch (const std::exception& error) {
        throw std::runtime_error(
            "Failed to parse stop_if expression: " + std::string(error.what()));
    }
}

bool OdeIntegrator::stopConditionMet(const ast::Expression& condition,
                                     double time,
                                     const std::vector<double>& state) const {
    std::vector<double> groupValues;
    updateGroups(state.data(), groupValues);

    const auto resolver = [&](const std::string& name) -> double {
        if (name == "time") {
            return time;
        }
        const auto observable = observableIndex_.find(name);
        if (observable != observableIndex_.end()) {
            return groupValues[observable->second];
        }
        static const std::unordered_map<std::string, double> noEventValues;
        const auto& eventValues = activeSimulationSession_
            ? activeSimulationSession_->eventParameterValues
            : noEventValues;
        return evaluateParameterWithEventState(name, time, eventValues);
    };

    try {
        return condition.evaluate(resolver, time) != 0.0;
    } catch (const std::exception& error) {
        throw std::runtime_error(
            "Failed to evaluate stop_if expression '" +
            condition.toString() + "': " + error.what());
    }
}

bool OdeIntegrator::steadyStateReached(const OdeOptions& options,
                                       double time,
                                       const std::vector<double>& state) const {
    if (!options.steadyState) {
        return false;
    }
    if (nSpecies_ == 0) {
        return true;
    }

    std::vector<double> derivatives(nSpecies_);
    derivs(time, state.data(), derivatives.data());
    double sumSq = 0.0;
    for (const double derivative : derivatives) {
        sumSq += derivative * derivative;
    }
    const double dx = std::sqrt(sumSq) / static_cast<double>(nSpecies_);
    return dx < options.steadyStateTol;
}

void OdeIntegrator::markContinuousSpecies() {
    continuousSpecies_.assign(network_.species.size(), false);
    for (const auto& reaction : network_.reactions.all()) {
        std::unordered_map<std::size_t, long> net;
        for (const auto species : reaction.getReactants()) --net[species];
        for (const auto species : reaction.getProducts()) ++net[species];
        for (const auto& [species, change] : net) {
            if (change != 0 && species < continuousSpecies_.size()) {
                continuousSpecies_[species] = true;
            }
        }
    }
}

bool OdeIntegrator::isDiscreteConjunct(const ast::Expression& conjunct) const {
    // A conjunct is discrete when it reads at least one species observable,
    // every species it reads is one that no reaction changes, and it reads
    // neither time, a delayed value nor a time-dependent parameter.  Its
    // value then changes only when an event assigns, so the trigger is
    // re-tested after each event execution (retestTriggers) instead of being
    // located by a root function: floor(ticks / 16) >= 1 with ticks counted
    // by an event is piecewise constant and has no continuous root.
    const auto expanded = functionEvaluator_.expandFunctions(conjunct);
    bool readsObservable = false;
    bool discrete = true;
    std::function<void(const ast::Expression&)> visit = [&](const ast::Expression& node) {
        if (!discrete) return;
        if (node.kind() == ast::ExpressionKind::Function && node.name() == "delay") {
            discrete = false;
            return;
        }
        if (node.kind() == ast::ExpressionKind::Identifier ||
            node.kind() == ast::ExpressionKind::ObservableRef) {
            const auto& name = node.name();
            if (name == "time" || name == "t") {
                discrete = false;
                return;
            }
            const auto observable = observableIndex_.find(name);
            if (observable != observableIndex_.end()) {
                readsObservable = true;
                for (const auto& entry : compiledGroups_[observable->second].entries) {
                    if (entry.first < continuousSpecies_.size() &&
                        continuousSpecies_[entry.first]) {
                        discrete = false;
                        return;
                    }
                }
                return;
            }
            try {
                if (model_.getParameters().isTimeDependent(name)) discrete = false;
            } catch (const std::exception&) {
                // An identifier that is neither an observable nor a known
                // parameter leaves the classification to the caller's checks.
                discrete = false;
            }
            return;
        }
        for (const auto& child : node.args()) visit(child);
    };
    visit(expanded);
    return discrete && readsObservable;
}

void OdeIntegrator::pruneDiscreteEventRoots() {
    discreteEventConjuncts_.clear();
    std::vector<std::pair<std::size_t, const ast::Expression*>> continuousRoots;
    continuousRoots.reserve(nativeEventRoots_.size());
    for (const auto& root : nativeEventRoots_) {
        if (isDiscreteConjunct(*root.second)) {
            discreteEventConjuncts_.insert(root.second);
        } else {
            continuousRoots.push_back(root);
        }
    }
    // A discrete conjunct is piecewise constant: as a root function it is
    // either identically zero or never changes sign between the solver's
    // steps.  Its rising edge can only be an event execution or the start,
    // where the triggers are tested directly.
    nativeEventRoots_ = std::move(continuousRoots);
}

void OdeIntegrator::validateEventRootSurface() {
    if (nativeEvents_.empty()) return;
    const auto dynamic = [&](const ast::Expression& value) {
        return ((value.kind() == ast::ExpressionKind::Identifier ||
                 value.kind() == ast::ExpressionKind::ObservableRef) &&
                (value.name() == "time" || observableIndex_.count(value.name()))) ||
               (value.kind() == ast::ExpressionKind::Function &&
                value.name() == "delay" && value.args().size() == 2);
    };
    for (const auto& event : nativeEvents_) {
        const auto expandedTrigger = functionEvaluator_.expandFunctions(event.trigger);
        const auto originalConjuncts = triggerConjuncts(event.trigger);
        const auto expandedConjuncts = triggerConjuncts(expandedTrigger);
        for (std::size_t index = 0; index < expandedConjuncts.size(); ++index) {
            const auto* conjunct = expandedConjuncts[index];
            const auto& arguments = conjunct->args();
            if (dynamic(arguments[0]) || dynamic(arguments[1])) continue;
            // A conjunct of any arithmetic form over species that only events
            // change is admitted: it is re-tested at every event execution.
            if (index < originalConjuncts.size() &&
                isDiscreteConjunct(*originalConjuncts[index])) {
                continue;
            }
            throw std::runtime_error(
                "bng3_events trigger requires one time or species observable "
                "against a static threshold, or a comparison of species that only "
                "events change");
        }
    }
    // The runtime's contract is uniform: the trigger's rising edge is the
    // first sign change of the root function, and the root function is
    // positive exactly where the trigger holds.  A strict inequality is true
    // on one side of its root, so the sign change is exactly the rising
    // edge; a non-strict inequality is also true at a tangential contact
    // that leaves no sign change, which the crossing detection cannot see.
    // Both forms therefore carry the same documented limitation, and neither
    // needs a monotonicity proof on the state.
}

double OdeIntegrator::evaluateParameterWithEventState(
    const std::string& name, double time,
    const std::unordered_map<std::string, double>& eventValues) const {
    const auto assigned = eventValues.find(name);
    if (assigned != eventValues.end()) return assigned->second;
    if (eventDependentParameterNames_.find(name) ==
        eventDependentParameterNames_.end()) {
        return model_.getParameters().evaluate(name, time);
    }

    std::unordered_set<std::string> visiting;
    std::function<double(const std::string&)> resolve =
        [&](const std::string& parameterName) -> double {
            const auto value = eventValues.find(parameterName);
            if (value != eventValues.end()) return value->second;
            if (eventDependentParameterNames_.find(parameterName) ==
                eventDependentParameterNames_.end()) {
                return model_.getParameters().evaluate(parameterName, time);
            }
            if (!model_.getParameters().contains(parameterName)) {
                return model_.getParameters().evaluate(parameterName, time);
            }
            if (!visiting.insert(parameterName).second) {
                throw std::runtime_error(
                    "Circular parameter dependency detected at '" +
                    parameterName + "'");
            }
            const auto resolvedValue = functionEvaluator_.evaluate(
                model_.getParameters().get(parameterName).getExpression(),
                resolve, time);
            visiting.erase(parameterName);
            return resolvedValue;
        };
    return resolve(name);
}

void OdeIntegrator::validateEventTargets() {
    if (nativeEvents_.empty()) return;
    for (auto& event : nativeEvents_) {
        for (const auto& assignment : event.assignments) {
            const auto found = observableIndex_.find(assignment.target);
            if (found == observableIndex_.end()) {
                if (!model_.getParameters().contains(assignment.target) ||
                    model_.getParameters().isTimeDependent(assignment.target)) {
                    throw std::runtime_error(
                        "bng3_events assignment target must be a species observable or static parameter");
                }
                const auto duplicate = std::find_if(
                    event.targets.begin(), event.targets.end(),
                    [&](const NativeEventTarget& target) {
                        return target.kind == NativeEventTarget::Kind::Parameter &&
                               target.parameterName == assignment.target;
                    });
                if (duplicate != event.targets.end()) {
                    throw std::runtime_error(
                        "bng3_events assignments alias the same parameter");
                }
                event.targets.push_back({
                    NativeEventTarget::Kind::Parameter, 0, assignment.target});
                continue;
            }
            const auto& entries = compiledGroups_[found->second].entries;
            if (entries.size() != 1 || entries.front().second != 1.0 ||
                fixedSpecies_[entries.front().first]) {
                throw std::runtime_error("bng3_events assignment target must identify one nonconstant species with weight one");
            }
            const auto target = entries.front().first;
            const auto duplicate = std::find_if(
                event.targets.begin(), event.targets.end(),
                [&](const NativeEventTarget& existing) {
                    return existing.kind == NativeEventTarget::Kind::Species &&
                           existing.speciesIndex == target;
                });
            if (duplicate != event.targets.end()) {
                throw std::runtime_error("bng3_events assignments alias the same species");
            }
            event.targets.push_back({NativeEventTarget::Kind::Species, target, {}});
        }
    }
}

double OdeIntegrator::eventValue(const ast::Expression& expression,
                                 double time, const double* state) const {
    return evaluateExpressionWithHistory(expression, time, state);
}

namespace {

double drawSbmlDistribution(const std::string& name,
                           const std::vector<double>& args,
                           std::mt19937_64& rng) {
    const auto requireCount = [&](std::initializer_list<std::size_t> allowed) {
        if (std::find(allowed.begin(), allowed.end(), args.size()) == allowed.end()) {
            throw std::runtime_error("SBML distrib function '" + name +
                                     "' has an invalid argument count");
        }
    };
    const auto requireFinite = [&](std::size_t index) {
        if (!std::isfinite(args[index])) {
            throw std::runtime_error("SBML distrib function '" + name +
                                     "' requires finite parameters");
        }
    };
    const auto sampleBounded = [&](const std::function<double()>& sample,
                                   double minimum, double maximum,
                                   bool discrete) {
        if (!(minimum <= maximum) ||
            (!discrete && !(minimum < maximum)) ||
            (discrete && std::ceil(minimum) > std::floor(maximum))) {
            throw std::runtime_error("SBML distrib function '" + name +
                                     "' has invalid truncation bounds");
        }
        for (std::size_t attempt = 0; attempt < 1000000; ++attempt) {
            const double value = sample();
            if (value >= minimum && (discrete ? value <= maximum : value < maximum)) {
                return value;
            }
        }
        throw std::runtime_error("SBML distrib function '" + name +
                                 "' could not draw within its truncation bounds");
    };
    const auto bounds = [&](std::size_t index) {
        return std::pair<double, double>{
            args.size() > index ? args[index] : -std::numeric_limits<double>::infinity(),
            args.size() > index + 1 ? args[index + 1]
                                    : std::numeric_limits<double>::infinity()};
    };
    const auto unit = [&]() {
        std::uniform_real_distribution<double> distribution(0.0, 1.0);
        double value = distribution(rng);
        while (value == 0.0) value = distribution(rng);
        return value;
    };

    if (name == "distrib_normal") {
        requireCount({2, 4});
        requireFinite(0);
        requireFinite(1);
        if (!(args[1] > 0.0)) {
            throw std::runtime_error("SBML normal stdev must be positive");
        }
        const auto [minimum, maximum] = bounds(2);
        std::normal_distribution<double> distribution(args[0], args[1]);
        return sampleBounded([&]() { return distribution(rng); }, minimum,
                             maximum, false);
    }
    if (name == "distrib_uniform") {
        requireCount({2});
        requireFinite(0);
        requireFinite(1);
        if (!(args[0] < args[1])) {
            throw std::runtime_error("SBML uniform minimum must be less than maximum");
        }
        std::uniform_real_distribution<double> distribution(args[0], args[1]);
        return distribution(rng);
    }
    if (name == "distrib_bernoulli") {
        requireCount({1});
        requireFinite(0);
        if (args[0] < 0.0 || args[0] > 1.0) {
            throw std::runtime_error("SBML Bernoulli probability must be in [0, 1]");
        }
        std::bernoulli_distribution distribution(args[0]);
        return distribution(rng) ? 1.0 : 0.0;
    }
    if (name == "distrib_binomial") {
        requireCount({2, 4});
        requireFinite(0);
        requireFinite(1);
        if (args[0] < 0.0 || std::floor(args[0]) != args[0] ||
            args[0] > static_cast<double>(std::numeric_limits<int>::max()) ||
            args[1] < 0.0 || args[1] > 1.0) {
            throw std::runtime_error("SBML binomial parameters are invalid");
        }
        const auto [minimum, maximum] = bounds(2);
        std::binomial_distribution<int> distribution(
            static_cast<int>(args[0]), args[1]);
        return sampleBounded([&]() { return distribution(rng); }, minimum,
                             maximum, true);
    }
    if (name == "distrib_cauchy") {
        requireCount({1, 2, 4});
        const double location = args.size() == 1 ? 0.0 : args[0];
        const double scale = args.size() == 1 ? args[0] : args[1];
        if (!std::isfinite(location) || !std::isfinite(scale) || !(scale > 0.0)) {
            throw std::runtime_error("SBML Cauchy parameters are invalid");
        }
        const auto [minimum, maximum] = bounds(2);
        std::cauchy_distribution<double> distribution(location, scale);
        return sampleBounded([&]() { return distribution(rng); }, minimum,
                             maximum, false);
    }
    if (name == "distrib_chisquare") {
        requireCount({1, 3});
        requireFinite(0);
        if (!(args[0] > 0.0)) {
            throw std::runtime_error("SBML chi-square degrees of freedom must be positive");
        }
        const auto [minimum, maximum] = bounds(1);
        std::chi_squared_distribution<double> distribution(args[0]);
        return sampleBounded([&]() { return distribution(rng); }, minimum,
                             maximum, false);
    }
    if (name == "distrib_exponential") {
        requireCount({1, 3});
        requireFinite(0);
        if (!(args[0] > 0.0)) {
            throw std::runtime_error("SBML exponential rate must be positive");
        }
        const auto [minimum, maximum] = bounds(1);
        std::exponential_distribution<double> distribution(args[0]);
        return sampleBounded([&]() { return distribution(rng); }, minimum,
                             maximum, false);
    }
    if (name == "distrib_gamma") {
        requireCount({2, 4});
        requireFinite(0);
        requireFinite(1);
        if (!(args[0] > 0.0) || !(args[1] > 0.0)) {
            throw std::runtime_error("SBML gamma shape and scale must be positive");
        }
        const auto [minimum, maximum] = bounds(2);
        std::gamma_distribution<double> distribution(args[0], args[1]);
        return sampleBounded([&]() { return distribution(rng); }, minimum,
                             maximum, false);
    }
    if (name == "distrib_laplace") {
        requireCount({1, 2, 4});
        const double location = args.size() == 1 ? 0.0 : args[0];
        const double scale = args.size() == 1 ? args[0] : args[1];
        if (!std::isfinite(location) || !std::isfinite(scale) || !(scale > 0.0)) {
            throw std::runtime_error("SBML Laplace parameters are invalid");
        }
        const auto [minimum, maximum] = bounds(2);
        const auto sample = [&]() {
            const double u = unit();
            return u < 0.5 ? location + scale * std::log(2.0 * u)
                           : location - scale * std::log(2.0 * (1.0 - u));
        };
        return sampleBounded(sample, minimum, maximum, false);
    }
    if (name == "distrib_lognormal") {
        requireCount({2, 4});
        requireFinite(0);
        requireFinite(1);
        if (!(args[1] > 0.0)) {
            throw std::runtime_error("SBML lognormal stdev must be positive");
        }
        const auto [minimum, maximum] = bounds(2);
        std::lognormal_distribution<double> distribution(args[0], args[1]);
        return sampleBounded([&]() { return distribution(rng); }, minimum,
                             maximum, false);
    }
    if (name == "distrib_poisson") {
        requireCount({1, 3});
        requireFinite(0);
        if (args[0] < 0.0) {
            throw std::runtime_error("SBML Poisson rate must be nonnegative");
        }
        const auto [minimum, maximum] = bounds(1);
        std::poisson_distribution<unsigned long long> distribution(args[0]);
        return sampleBounded(
            [&]() { return static_cast<double>(distribution(rng)); }, minimum,
            maximum, true);
    }
    if (name == "distrib_rayleigh") {
        requireCount({1, 3});
        requireFinite(0);
        if (!(args[0] > 0.0)) {
            throw std::runtime_error("SBML Rayleigh scale must be positive");
        }
        const auto [minimum, maximum] = bounds(1);
        const auto sample = [&]() { return args[0] * std::sqrt(-2.0 * std::log(1.0 - unit())); };
        return sampleBounded(sample, minimum, maximum, false);
    }
    throw std::runtime_error("Unsupported SBML distrib function '" + name + "'");
}

}  // namespace

double OdeIntegrator::eventAssignmentValue(const ast::Expression& expression,
                                            double time,
                                            const double* state) const {
    auto expanded = functionEvaluator_.expandFunctions(expression);
    std::function<bool(const ast::Expression&)> hasDraw;
    hasDraw = [&](const ast::Expression& current) {
        if (current.kind() == ast::ExpressionKind::Function &&
            current.name().rfind("distrib_", 0) == 0) {
            return true;
        }
        return std::any_of(current.args().begin(), current.args().end(), hasDraw);
    };
    if (hasDraw(expanded) &&
        (activeSimulationSession_ == nullptr ||
         !activeSimulationSession_->rngInitialized)) {
        throw std::runtime_error(
            "SBML distrib draws require a seeded simulation session");
    }
    std::function<ast::Expression(const ast::Expression&)> sampleDraws;
    sampleDraws = [&](const ast::Expression& current) -> ast::Expression {
        const auto& args = current.args();
        if (current.kind() == ast::ExpressionKind::Function &&
            current.name() == "if" && args.size() == 3) {
            // An event samples only the selected branch. Traversing both
            // branches would consume unused distribution draws and change
            // subsequent event values even when the condition selects a constant.
            const auto condition = sampleDraws(args[0]);
            return sampleDraws(args[eventValue(condition, time, state) != 0.0 ? 1 : 2]);
        }
        if (current.kind() == ast::ExpressionKind::Function &&
            current.name().rfind("distrib_", 0) == 0) {
            std::vector<double> parameters;
            parameters.reserve(args.size());
            for (const auto& argument : args) {
                const auto sampledArgument = sampleDraws(argument);
                parameters.push_back(eventValue(sampledArgument, time, state));
            }
            return ast::Expression::number(drawSbmlDistribution(
                current.name(), parameters, activeSimulationSession_->rng));
        }
        switch (current.kind()) {
        case ast::ExpressionKind::Number:
        case ast::ExpressionKind::Identifier:
            return current;
        case ast::ExpressionKind::Unary:
            return ast::Expression::unary(current.name(), sampleDraws(args.front()));
        case ast::ExpressionKind::Binary:
            return ast::Expression::binary(current.name(), sampleDraws(args[0]),
                                           sampleDraws(args[1]));
        case ast::ExpressionKind::Function:
        case ast::ExpressionKind::ObservableRef: {
            std::vector<ast::Expression> sampled;
            sampled.reserve(args.size());
            for (const auto& argument : args) sampled.push_back(sampleDraws(argument));
            return current.kind() == ast::ExpressionKind::Function
                ? ast::Expression::function(current.name(), std::move(sampled))
                : ast::Expression::observableRef(current.name(), std::move(sampled));
        }
        case ast::ExpressionKind::TableFunction:
            return ast::Expression::tableFunction(
                current.tableXValues(), current.tableYValues(),
                current.tableFilePath(), sampleDraws(args.front()),
                current.tableMethod());
        }
        throw std::runtime_error("Unsupported SBML event assignment expression");
    };
    const auto sampled = sampleDraws(expanded);
    const double value = eventValue(sampled, time, state);
    return value;
}

std::vector<double> OdeIntegrator::eventValues(const NativeEvent& event, double time,
                                                const double* state) const {
    std::vector<double> values;
    for (const auto& assignment : event.assignments) {
        values.push_back(eventAssignmentValue(assignment.value, time, state));
    }
    return values;
}

void OdeIntegrator::assignEventValues(const NativeEvent& event, std::vector<double>& state,
                                      const std::vector<double>& values) {
    if (values.size() != event.targets.size()) {
        throw std::runtime_error("bng3_events assignment values do not match targets");
    }
    for (std::size_t i = 0; i < values.size(); ++i) {
        const auto& target = event.targets[i];
        if (target.kind == NativeEventTarget::Kind::Species) {
            state[target.speciesIndex] = values[i];
            continue;
        }
        if (!activeSimulationSession_) {
            throw std::runtime_error(
                "bng3_events parameter assignments require a simulation session");
        }
        activeSimulationSession_->eventParameterValues[target.parameterName] =
            values[i];
    }
}

bool OdeIntegrator::triggerHolds(const ast::Expression& trigger, double time,
                                  const double* state) const {
    return eventValue(trigger, time, state) != 0.0;
}

double OdeIntegrator::eventSideDerivative(const ast::Expression& expression,
                                           double time,
                                           const double* state,
                                           const std::vector<double>& derivatives) const {
    switch (expression.kind()) {
    case ast::ExpressionKind::Number:
        return 0.0;
    case ast::ExpressionKind::Identifier:
    case ast::ExpressionKind::ObservableRef: {
        if (expression.name() == "time" || expression.name() == "t") return 1.0;
        const auto observable = observableIndex_.find(expression.name());
        if (observable == observableIndex_.end()) return 0.0;
        double total = 0.0;
        for (const auto& entry : compiledGroups_[observable->second].entries) {
            if (entry.first < derivatives.size()) {
                total += entry.second * derivatives[entry.first];
            }
        }
        return total;
    }
    case ast::ExpressionKind::Unary:
        if (expression.name() == "-") {
            return -eventSideDerivative(expression.args().front(), time, state,
                                        derivatives);
        }
        return eventSideDerivative(expression.args().front(), time, state,
                                   derivatives);
    case ast::ExpressionKind::Binary: {
        const auto& lhs = expression.args()[0];
        const auto& rhs = expression.args()[1];
        const double left = eventSideDerivative(lhs, time, state, derivatives);
        const double right = eventSideDerivative(rhs, time, state, derivatives);
        if (expression.name() == "+") return left + right;
        if (expression.name() == "-") return left - right;
        if (expression.name() == "*") {
            return left * eventValue(rhs, time, state) +
                   eventValue(lhs, time, state) * right;
        }
        return 0.0;
    }
    case ast::ExpressionKind::Function:
        if (expression.name() == "abs" && expression.args().size() == 1) {
            const auto& argument = expression.args().front();
            const double value = eventValue(argument, time, state);
            if (value == 0.0) return 0.0;
            return std::copysign(1.0, value) *
                   eventSideDerivative(argument, time, state, derivatives);
        }
        return 0.0;
    case ast::ExpressionKind::TableFunction:
        return 0.0;
    }
    return 0.0;
}

double OdeIntegrator::eventRootDerivative(const ast::Expression& trigger,
                                           double time,
                                           const double* state,
                                           const std::vector<double>& derivatives) const {
    const auto& arguments = trigger.args();
    const double difference =
        eventSideDerivative(arguments[0], time, state, derivatives) -
        eventSideDerivative(arguments[1], time, state, derivatives);
    // The root function is positive exactly where the trigger holds.
    return trigger.name()[0] == '<' ? -difference : difference;
}

std::vector<const ast::Expression*> OdeIntegrator::triggerConjuncts(
    const ast::Expression& trigger) {
    std::vector<const ast::Expression*> conjuncts;
    if (trigger.kind() == ast::ExpressionKind::Binary && trigger.name() == "&&") {
        for (const auto& child : trigger.args()) {
            for (const auto* conjunct : triggerConjuncts(child)) {
                conjuncts.push_back(conjunct);
            }
        }
        return conjuncts;
    }
    conjuncts.push_back(&trigger);
    return conjuncts;
}

bool OdeIntegrator::isStrictTrigger(const ast::Expression& trigger) {
    for (const auto* conjunct : triggerConjuncts(trigger)) {
        if (conjunct->name() != "<" && conjunct->name() != ">") return false;
    }
    return true;
}

double OdeIntegrator::eventRootValue(const ast::Expression& trigger, double time,
                                      const double* state) const {
    const auto conjuncts = triggerConjuncts(trigger);
    if (conjuncts.size() == 1) {
        const auto& arguments = conjuncts.front()->args();
        if (conjuncts.front()->name() == "==") {
            return eventValue(arguments[0], time, state) ==
                           eventValue(arguments[1], time, state)
                       ? 1.0
                       : -1.0;
        }
        const double difference =
            eventValue(arguments[0], time, state) -
            eventValue(arguments[1], time, state);
        return conjuncts.front()->name()[0] == '<' ? -difference : difference;
    }
    // A conjunction holds only where every conjunct holds, so its root
    // function is the smallest of the conjunct root functions.
    double smallest = std::numeric_limits<double>::infinity();
    for (const auto* conjunct : conjuncts) {
        smallest = std::min(smallest, eventRootValue(*conjunct, time, state));
    }
    return smallest;
}

OdeIntegrator::TriggerSurface OdeIntegrator::triggerSurface(
    const ast::Expression& trigger, double time, const double* state,
    const std::vector<double>& derivatives) const {
    TriggerSurface surface;
    const auto conjuncts = triggerConjuncts(trigger);
    double smallest = std::numeric_limits<double>::infinity();
    const ast::Expression* active = nullptr;
    for (const auto* conjunct : conjuncts) {
        const double value = eventRootValue(*conjunct, time, state);
        if (value < smallest) {
            smallest = value;
            active = conjunct;
        }
    }
    surface.difference = smallest;
    if (active != nullptr) {
        surface.derivative = eventRootDerivative(*active, time, state, derivatives);
    }
    return surface;
}

void OdeIntegrator::queueTriggeredGroup(std::size_t groupIndex, double time,
                                        const std::vector<double>& state) {
    for (const auto index : nativeEventGroups_[groupIndex].events) {
        const auto& event = nativeEvents_[index];
        PendingEvent pending;
        pending.event = index;
        pending.executionTime = time + eventDelay(event, time, state.data());
        if (event.useValuesFromTriggerTime) {
            pending.values = eventValues(event, time, state.data());
        }
        triggerRoseAt_[index] = time;
        pendingEvents_.push_back(std::move(pending));
    }
}

void OdeIntegrator::retestTriggers(double time, std::vector<double>& state,
                                   const std::vector<bool>& heldBefore) {
    // SBML L3V2 Core Sec. 4.12.7 ("Detailed semantics of events"): every
    // trigger is re-tested after an execution, so an event whose trigger the
    // assignment made true joins the same execution point.
    for (std::size_t index = 0; index < nativeEvents_.size(); ++index) {
        if (heldBefore[index]) continue;
        if (!triggerHolds(nativeEvents_[index].trigger, time, state.data())) continue;
        const auto& event = nativeEvents_[index];
        PendingEvent pending;
        pending.event = index;
        pending.executionTime = time + eventDelay(event, time, state.data());
        if (event.useValuesFromTriggerTime) {
            pending.values = eventValues(event, time, state.data());
        }
        triggerRoseAt_[index] = time;
        pendingEvents_.push_back(std::move(pending));
    }
}

double OdeIntegrator::eventDelay(const NativeEvent& event, double time,
                                 const double* state) const {
    const double delay = event.delay ? eventValue(*event.delay, time, state) : 0.0;
    if (!std::isfinite(delay) || delay < 0.0) {
        throw std::runtime_error(
            "bng3_events delay must be a finite nonnegative value at trigger time");
    }
    return delay;
}

bool OdeIntegrator::applyDueEvents(double time, std::vector<double>& state) {
    bool applied = false;
    while (true) {
        // The queued events are executed in the order the specification
        // defines: the events with the earliest execution instant first, and
        // the events executed at the same instant in the order of their
        // priority, the highest priority first (SBML L3V2 Core Sec. 4.12.3).
        double earliest = std::numeric_limits<double>::infinity();
        for (const auto& pending : pendingEvents_) {
            if (pending.executionTime <= time + 1e-12) {
                earliest = std::min(earliest, pending.executionTime);
            }
        }
        if (!std::isfinite(earliest)) break;
        auto selected = pendingEvents_.end();
        double selectedPriority = -std::numeric_limits<double>::infinity();
        std::vector<std::vector<PendingEvent>::iterator> equalPriority;
        for (auto candidate = pendingEvents_.begin();
             candidate != pendingEvents_.end(); ++candidate) {
            if (candidate->executionTime > earliest + 1e-12) continue;
            const auto& event = nativeEvents_[candidate->event];
            const double priority = event.dynamicPriority
                ? eventValue(*event.dynamicPriority, candidate->executionTime,
                             state.data())
                : event.priority;
            if (!std::isfinite(priority)) {
                throw std::runtime_error("bng3_events expression is nonfinite");
            }
            if (selected == pendingEvents_.end() || priority > selectedPriority) {
                selected = candidate;
                selectedPriority = priority;
                equalPriority.clear();
                equalPriority.push_back(candidate);
            } else if (priority == selectedPriority) {
                equalPriority.push_back(candidate);
            }
        }
        if (equalPriority.size() > 1) {
            if (activeSimulationSession_ == nullptr ||
                !activeSimulationSession_->rngInitialized) {
                throw std::runtime_error(
                    "random native event ordering requires a seeded simulation session");
            }
            std::uniform_int_distribution<std::size_t> choose(
                0, equalPriority.size() - 1);
            selected = equalPriority[choose(activeSimulationSession_->rng)];
        }
        const PendingEvent pending = *selected;
        pendingEvents_.erase(selected);
        const auto& event = nativeEvents_[pending.event];
        // The event executes at its own instant, which is the instant its
        // delay put it at.
        const double instant = pending.executionTime;
        if (!event.persistent &&
            !triggerHolds(event.trigger, instant, state.data())) {
            // SBML L3V2 Core Sec. 4.12.2: a trigger that is not persistent is
            // re-evaluated before the execution, and the event is not executed
            // at all when the trigger has become false again.
            continue;
        }
        // The values are computed at the trigger time or at the execution
        // time, as the event's useValuesFromTriggerTime says.
        const std::vector<double> values =
            event.useValuesFromTriggerTime
                ? pending.values
                : eventValues(event, instant, state.data());
        // The trigger values before the assignment tell a rising edge from a
        // trigger that was already true.  The trigger of an event that rose
        // at this very instant holds conceptually, even where the numerical
        // comparison is an equality: the event has just been triggered, so
        // its own assignment cannot make it rise again.
        std::vector<bool> heldBefore;
        heldBefore.reserve(nativeEvents_.size());
        for (std::size_t index = 0; index < nativeEvents_.size(); ++index) {
            const bool justRose =
                std::abs(triggerRoseAt_[index] - instant) <= 1e-12;
            heldBefore.push_back(
                justRose || triggerHolds(nativeEvents_[index].trigger, instant, state.data()));
        }
        assignEventValues(event, state, values);
        applied = true;
        retestTriggers(instant, state, heldBefore);
    }
    return applied;
}

void OdeIntegrator::cvodeEventRoots(double time, const double* scaledState,
                                    double* roots) const {
    std::vector<double> state(nSpecies_);
    for (std::size_t i = 0; i < nSpecies_; ++i) state[i] = scaledState[i] * cvodeStateScale_[i];
    for (std::size_t root = 0; root < nativeEventRoots_.size(); ++root) {
        roots[root] = eventRootValue(*nativeEventRoots_[root].second, time, state.data());
    }
}

double OdeIntegrator::cvodeEventRoot(double time, const double* scaledState) const {
    if (nativeEventGroups_.empty()) return 0.0;
    std::vector<double> state(nSpecies_);
    for (std::size_t i = 0; i < nSpecies_; ++i) state[i] = scaledState[i] * cvodeStateScale_[i];
    return eventRootValue(nativeEventGroups_.front().trigger, time, state.data());
}

OdeResult OdeIntegrator::integrate(const OdeOptions& options) {
    if (options.isolatedTrajectory) {
        if (options.method != "ssa") {
            throw std::runtime_error(
                "isolatedTrajectory is reserved for independent SSA samples");
        }
        if (options.continueSimulation) {
            throw std::runtime_error(
                "continue_simulation is not supported for isolated trajectories");
        }
        if (hasPositiveExpressionDelay_) {
            throw std::runtime_error(
                "delay(expr, tau) is not supported by batch SSA");
        }
        SimulationSession trajectory;
        trajectory.initialized = true;
        trajectory.startTime = options.tStart;
        trajectory.currentTime = options.tStart;
        trajectory.reactionDelays.reserve(compiledRxns_.size());
        for (const auto& reaction : compiledRxns_) {
            trajectory.reactionDelays.push_back(reaction.delay);
        }
        trajectory.state.resize(nSpecies_);
        trajectory.initialState.resize(nSpecies_);
        for (std::size_t i = 0; i < nSpecies_; ++i) {
            trajectory.state[i] = network_.species.get(i).getAmount();
            trajectory.initialState[i] = trajectory.state[i];
        }
        activeSimulationSession_ = &trajectory;
        try {
            auto result = integrateCore(options);
            activeSimulationSession_ = nullptr;
            return result;
        } catch (...) {
            activeSimulationSession_ = nullptr;
            throw;
        }
    }
    if (options.batchSize > 0) {
        if (options.continueSimulation) {
            throw std::runtime_error(
                "continue_simulation is not supported for batch SSA");
        }
        if (hasPositiveExpressionDelay_) {
            throw std::runtime_error(
                "delay(expr, tau) is not supported by batch SSA");
        }
        return integrateCore(options);
    }

    SimulationSession working = network_.snapshotSimulationSession();
    if (options.method == "ssa" && hasPositiveExpressionDelay_) {
        throw std::runtime_error(
            "delay(expr, tau) has no direct SSA semantics");
    }
    bool hasNetworkIntervention = false;
    bool hasParameterIntervention = false;
    std::vector<double> stateBeforeIntervention;
    std::vector<double> stateAfterIntervention;
    if (options.continueSimulation) {
        if (!working.initialized ||
            std::abs(working.currentTime - options.tStart) > 1e-10) {
            throw std::runtime_error(
                "continue_simulation requires a prior successful run ending at t_start");
        }
        if (working.reactionDelays.size() != compiledRxns_.size()) {
            throw std::runtime_error(
                "continue_simulation cannot change the compiled reaction set");
        }
        for (std::size_t i = 0; i < compiledRxns_.size(); ++i) {
            if (working.reactionDelays[i] != compiledRxns_[i].delay) {
                throw std::runtime_error(
                    "continue_simulation requires reaction delays to remain constant");
            }
        }
        if (!working.history.empty()) {
            const auto& previousParameters = working.history.back().parameters;
            for (const auto& parameter : model_.getParameters().all()) {
                try {
                    const double current = evaluateParameterWithEventState(
                        parameter.getName(), options.tStart,
                        working.eventParameterValues);
                    const auto previous = previousParameters.find(parameter.getName());
                    if (previous != previousParameters.end() &&
                        std::abs(previous->second - current) > 1e-12) {
                        hasParameterIntervention = true;
                        break;
                    }
                } catch (...) {}
            }
        }
        std::vector<double> networkState(nSpecies_);
        bool networkDiffers = false;
        bool networkIsOriginal = working.initialState.size() == nSpecies_;
        bool networkWasExplicitlyChanged = false;
        for (std::size_t i = 0; i < nSpecies_; ++i) {
            networkState[i] = network_.species.get(i).getAmount();
            networkDiffers = networkDiffers ||
                std::abs(networkState[i] - working.state[i]) > 1e-12;
            networkIsOriginal = networkIsOriginal &&
                std::abs(networkState[i] - working.initialState[i]) <= 1e-12;
            networkWasExplicitlyChanged = networkWasExplicitlyChanged ||
                (working.networkAmountVersions.size() == nSpecies_ &&
                 network_.species.get(i).getAmountVersion() !=
                     working.networkAmountVersions[i]);
        }
        if (networkDiffers &&
            (networkWasExplicitlyChanged || !networkIsOriginal)) {
            hasNetworkIntervention = true;
            stateBeforeIntervention = working.state;
            stateAfterIntervention = networkState;
            working.state = networkState;
        }
    } else {
        std::vector<double> freshState;
        if (options.freshFromInitialState && working.initialized &&
            working.initialState.size() == nSpecies_) {
            freshState = working.initialState;
        } else {
            freshState.resize(nSpecies_);
            for (std::size_t i = 0; i < nSpecies_; ++i) {
                freshState[i] = network_.species.get(i).getAmount();
            }
        }
        working.reset();
        working.initialized = true;
        working.startTime = options.tStart;
        working.currentTime = options.tStart;
        working.reactionDelays.reserve(compiledRxns_.size());
        for (const auto& reaction : compiledRxns_) {
            working.reactionDelays.push_back(reaction.delay);
        }
        working.state.resize(nSpecies_);
        working.initialState.resize(nSpecies_);
        working.networkAmountVersions.resize(nSpecies_);
        for (std::size_t i = 0; i < nSpecies_; ++i) {
            working.state[i] = freshState[i];
            working.initialState[i] = working.state[i];
            working.networkAmountVersions[i] =
                network_.species.get(i).getAmountVersion();
        }
    }
    activeSimulationSession_ = &working;
    try {
        if (!working.rngInitialized) {
            const std::mt19937_64::result_type seedValue =
                options.seed > 0
                    ? static_cast<std::mt19937_64::result_type>(options.seed)
                    : static_cast<std::mt19937_64::result_type>(
                          std::random_device{}());
            working.rng.seed(seedValue);
            working.rngInitialized = true;
        }
        if (hasNetworkIntervention) {
            recordHistoryJump(options.tStart, stateBeforeIntervention);
            recordHistoryJump(options.tStart, stateAfterIntervention);
        }
        if (hasParameterIntervention) {
            recordHistoryJump(options.tStart, working.state);
        }
        if (options.method != "cvode" && options.method != "ssa") {
            if (hasPositiveExpressionDelay_) {
                throw std::runtime_error(
                    "delay(expr, tau) requires the CVODE ODE method");
            }
            for (const auto& reaction : compiledRxns_) {
                if (reaction.delay > 0.0) {
                    throw std::runtime_error(
                        "Delayed reactions require the CVODE ODE method");
                }
            }
        }
        auto result = integrateCore(options);
        if (!result.concentrations.empty()) {
            working.state = result.concentrations.back();
            working.currentTime = result.timePoints.back();
        }
        working.pendingNativeEvents.clear();
        for (const auto& pending : pendingEvents_) {
            working.pendingNativeEvents.push_back({
                pending.event, pending.executionTime, pending.values});
        }
        working.eventTriggerRoseAt = triggerRoseAt_;
        working.networkAmountVersions.resize(nSpecies_);
        for (std::size_t i = 0; i < nSpecies_; ++i) {
            working.networkAmountVersions[i] =
                network_.species.get(i).getAmountVersion();
        }
        working.initialized = true;
        network_.replaceSimulationSession(std::move(working));
        activeSimulationSession_ = nullptr;
        return result;
    } catch (...) {
        activeSimulationSession_ = nullptr;
        throw;
    }
}

OdeResult OdeIntegrator::integrateCore(const OdeOptions& options) {
    if (!nativeEvents_.empty() && options.method != "cvode" &&
        options.method != "ssa") {
        throw std::runtime_error(
            "bng3_events require CVODE or SSA event detection");
    }
    if (options.method != "ssa" &&
        (options.maxSimSteps > 0 || options.outputStepInterval > 0)) {
        throw std::runtime_error(
            "max_sim_steps and output_step_interval are supported only for SSA");
    }
    if (options.method == "ssa" && options.batchSize > 0 &&
        !options.stopIf.empty()) {
        throw std::runtime_error("batch SSA does not support stop_if");
    }
    if (options.method == "ssa" && options.batchSize > 0 &&
        !nativeEvents_.empty()) {
        throw std::runtime_error("batch SSA does not support native events");
    }
    if (nSpecies_ == 0 &&
        (options.method == "euler" || options.method == "rk4" ||
         options.method == "cvode" || options.method == "ssa")) {
        // SBML permits models with parameters and no dynamic state. CVODE
        // cannot allocate a zero-length state vector, but these models still
        // have a well-defined output grid and may expose time/parameter-only
        // functions. Evaluate those outputs without entering a numerical
        // solver.
        auto times = outputTimes(options);
        const auto stopIfExpr = parseStopIf(options);
        const std::vector<double> emptyState;
        if (stopIfExpr.has_value() &&
            stopConditionMet(*stopIfExpr, options.tStart, emptyState) &&
            times.front() != options.tStart) {
            times.insert(times.begin(), options.tStart);
        }
        OdeResult result;
        result.timePoints.reserve(times.size());
        result.concentrations.reserve(times.size());
        result.observables.reserve(times.size());
        result.functions.reserve(times.size());
        for (std::size_t step = 0; step < times.size(); ++step) {
            const double time = times[step];
            result.timePoints.push_back(time);
            result.concentrations.emplace_back();
            result.observables.emplace_back();
            result.functions.emplace_back();
            updateGroups(emptyState.data(), result.observables.back());
            updateFunctions(result.observables.back(), time,
                            result.functions.back());
            if (step > 0 && options.steadyState &&
                steadyStateReached(options, time, emptyState)) {
                break;
            }
            if (stopIfExpr.has_value() &&
                stopConditionMet(*stopIfExpr, time, emptyState)) {
                break;
            }
        }
        return result;
    }
    if (options.method == "euler") {
        return integrateEuler(options);
    } else if (options.method == "rk4") {
        return integrateRK4(options);
    } else if (options.method == "cvode") {
        if (!algebraicResiduals_.empty()) {
            if (options.enforceNonnegative) {
                throw std::runtime_error(
                    "DAE integration does not combine with CVODE nonnegative constraints");
            }
            return integrateIda(options);
        }
        if (options.enforceNonnegative) {
            return integrateCvode(options);
        }
        const auto integrateWithExistingRetries = [&]() -> OdeResult {
            try {
                // SBML state variables are not inherently nonnegative.
                // Preserve that source semantics on the first attempt; use
                // constraints only as a solver-stability fallback when CVODE
                // cannot complete otherwise valid nonnegative populations.
                return integrateCvode(options);
            } catch (const std::runtime_error& error) {
                if (std::string(error.what()).find("CVODE") == std::string::npos) {
                    throw;
                }
                OdeOptions retry = options;
                retry.enforceNonnegative = true;
                try {
                    return integrateCvode(retry);
                } catch (const std::runtime_error& constrainedError) {
                    // A few imported SBML models have an extremely small
                    // characteristic timescale (often from a tiny declared
                    // compartment). With no user max_step, CVODE can spend
                    // its internal-step budget chasing that scale. Retry once
                    // with a bounded step only after the existing ordinary
                    // and constrained CVODE paths fail.
                    if (options.maxStep > 0.0 ||
                        std::string(constrainedError.what()).find("CVODE") ==
                            std::string::npos) {
                        throw;
                    }
                    OdeOptions stepped = options;
                    const double span = std::abs(options.tEnd - options.tStart);
                    stepped.maxStep = std::max(span / 2000.0, 1e-6);
                    return integrateCvode(stepped);
                }
            }
        };

        try {
            return integrateWithExistingRetries();
        } catch (const std::runtime_error& error) {
            const std::string message = error.what();
            if (message != "CVODE failed with flag " +
                               std::to_string(CV_CONV_FAILURE)) {
                throw;
            }
            try {
                // Only a terminal BDF convergence failure gets one complete
                // Adams restart. Start with the caller's original model state,
                // tolerances, output grid, and unconstrained semantics.
                return integrateCvode(options, true);
            } catch (const std::exception& fallbackError) {
                throw std::runtime_error(
                    message + "; Adams fixed-point fallback failed: " +
                    fallbackError.what());
            }
        }
    } else if (options.method == "ssa") {
        if (options.batchSize > 0) {
            return integrateBatchSSA(options);
        }
        bool allRateRuleStateChannels = !compiledRxns_.empty();
        {
            auto rxnIt = network_.reactions.all().begin();
            for (const auto& reaction : compiledRxns_) {
                if (!reaction.isAbsoluteFlux) { allRateRuleStateChannels = false; break; }
                std::string originName;
                if (rxnIt != network_.reactions.all().end()) {
                    originName = rxnIt->getOriginRuleName();
                    ++rxnIt;
                }
                if (originName.rfind("__rate_rule", 0) != 0) {
                    allRateRuleStateChannels = false;
                    break;
                }
            }
        }
        if (!nativeEvents_.empty() && allRateRuleStateChannels) {
            // A model with no stochastic reaction channels can still have
            // continuous SBML rate-rule states that drive discrete events.
            // Preserve those trajectories with the deterministic solver and
            // let the event assignments consume the seeded session RNG.
            return integrateCvode(options);
        }
        return integrateSSA(options);
    } else {
        throw std::runtime_error("Unknown ODE method: " + options.method);
    }
}

OdeResult OdeIntegrator::integrateEuler(const OdeOptions& opts) {
    auto times = outputTimes(opts);
    const auto stopIfExpr = parseStopIf(opts);
    std::vector<double> y(nSpecies_);

    // Initialize from species amounts
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        y[i] = network_.species.get(i).getAmount();
    }
    if (stopIfExpr.has_value() && stopConditionMet(*stopIfExpr, opts.tStart, y) &&
        times.front() != opts.tStart) {
        times.insert(times.begin(), opts.tStart);
    }

    OdeResult result;
    result.timePoints.reserve(times.size());
    result.concentrations.reserve(times.size());

    double currentTime = opts.tStart;
    for (std::size_t step = 0; step < times.size(); ++step) {
        const double targetTime = times[step];
        const double dt = targetTime - currentTime;
        if (dt > 0.0) {
            std::vector<double> dydt(nSpecies_);
            derivs(currentTime, y.data(), dydt.data());
            for (std::size_t i = 0; i < nSpecies_; ++i) {
                y[i] += dt * dydt[i];
                if (y[i] < 0.0) y[i] = 0.0;
            }
            currentTime = targetTime;
        }

        result.timePoints.push_back(targetTime);
        result.concentrations.push_back(y);

        if (step > 0 && steadyStateReached(opts, targetTime, y)) {
            break;
        }
        if (stopIfExpr.has_value() &&
            stopConditionMet(*stopIfExpr, targetTime, y)) {
            break;
        }
    }

    // Compute observables for each time point
    result.observables.resize(result.timePoints.size());
    result.functions.resize(result.timePoints.size());
    for (std::size_t step = 0; step < result.timePoints.size(); ++step) {
        updateGroups(result.concentrations[step].data(), result.observables[step]);
        updateFunctions(result.observables[step], result.timePoints[step], result.functions[step]);
    }

    return result;
}

OdeResult OdeIntegrator::integrateRK4(const OdeOptions& opts) {
    // Use internal sub-stepping for stability
    // For stiff systems, we need many more steps than the output points
    const std::size_t internalStepsPerOutput = 1000;  // Subdivide each output interval
    auto times = outputTimes(opts);
    const auto stopIfExpr = parseStopIf(opts);

    std::vector<double> y(nSpecies_);

    // Initialize from species amounts
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        y[i] = network_.species.get(i).getAmount();
    }
    if (stopIfExpr.has_value() && stopConditionMet(*stopIfExpr, opts.tStart, y) &&
        times.front() != opts.tStart) {
        times.insert(times.begin(), opts.tStart);
    }

    OdeResult result;
    result.timePoints.reserve(times.size());
    result.concentrations.reserve(times.size());

    std::vector<double> k1(nSpecies_), k2(nSpecies_), k3(nSpecies_), k4(nSpecies_);
    std::vector<double> yTemp(nSpecies_);

    double t = opts.tStart;
    for (std::size_t outputStep = 0; outputStep < times.size(); ++outputStep) {
        const double targetT = times[outputStep];
        const double outputDt = targetT - t;
        if (outputDt > 0.0) {
            const double dt = outputDt / static_cast<double>(internalStepsPerOutput);
            // Take internal steps to reach the next output point.
            for (std::size_t internalStep = 0; internalStep < internalStepsPerOutput; ++internalStep) {
                // k1 = f(t, y)
                derivs(t, y.data(), k1.data());

                // k2 = f(t + dt/2, y + dt*k1/2)
                for (std::size_t i = 0; i < nSpecies_; ++i) {
                    yTemp[i] = y[i] + 0.5 * dt * k1[i];
                    if (yTemp[i] < 0.0) yTemp[i] = 0.0;
                }
                derivs(t + 0.5 * dt, yTemp.data(), k2.data());

                // k3 = f(t + dt/2, y + dt*k2/2)
                for (std::size_t i = 0; i < nSpecies_; ++i) {
                    yTemp[i] = y[i] + 0.5 * dt * k2[i];
                    if (yTemp[i] < 0.0) yTemp[i] = 0.0;
                }
                derivs(t + 0.5 * dt, yTemp.data(), k3.data());

                // k4 = f(t + dt, y + dt*k3)
                for (std::size_t i = 0; i < nSpecies_; ++i) {
                    yTemp[i] = y[i] + dt * k3[i];
                    if (yTemp[i] < 0.0) yTemp[i] = 0.0;
                }
                derivs(t + dt, yTemp.data(), k4.data());

                // y_next = y + dt/6 * (k1 + 2*k2 + 2*k3 + k4)
                for (std::size_t i = 0; i < nSpecies_; ++i) {
                    y[i] += (dt / 6.0) * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]);
                    if (y[i] < 0.0) y[i] = 0.0;  // Clamp negative concentrations
                    if (!std::isfinite(y[i])) {
                        y[i] = 0.0;
                    }
                }

                t += dt;
            }
            t = targetT;
        }

        result.timePoints.push_back(targetT);
        result.concentrations.push_back(y);

        if (outputStep > 0 && steadyStateReached(opts, targetT, y)) {
            break;
        }
        if (stopIfExpr.has_value() &&
            stopConditionMet(*stopIfExpr, targetT, y)) {
            break;
        }
    }

    // Compute observables for each time point
    result.observables.resize(result.timePoints.size());
    result.functions.resize(result.timePoints.size());
    for (std::size_t step = 0; step < result.timePoints.size(); ++step) {
        updateGroups(result.concentrations[step].data(), result.observables[step]);
        updateFunctions(result.observables[step], result.timePoints[step], result.functions[step]);
    }

    return result;
}

namespace {

// Emits one .cdat/.gdat numeric field.
//
// The writer's established byte format is
//     out << " " << std::setw(18) << value
// with `std::scientific` and `std::setprecision(12)` latched on the stream, i.e.
// the 18-column right-justified form of "%.12e". This helper produces those
// same bytes without the per-value ostream sentry, num_put facet lookup and
// num_put locale grouping that dominate this loop.
//
// std::to_chars(chars_format::scientific, 12) was verified to emit identical
// digits to operator<< over 8,998,531 doubles (including 0.0, -0.0, 5e-324,
// -5e-324, DBL_MIN, DBL_MAX and raw 64-bit patterns) on this toolchain; see
// the bench/format_probe evidence quoted in the PR. The emitted bytes are
// identical, so the .cdat/.gdat files are unchanged byte-for-byte.
//
// `leadingSpace` reproduces the literal " " the caller inserted before every
// field except the first on a row. `dst` must have room for kMaxFieldBytes;
// the return value is the first byte after the field.
constexpr std::size_t kMaxFieldBytes = 24;

// Portable path for toolchains whose standard library does not yet provide
// floating-point std::to_chars (for example Apple deployment targets older
// than 13.3, where __cpp_lib_to_chars is undefined). It goes back through the
// stream, which is the definition of correct for this format: a literal space,
// then the value right-justified into 18 columns as "%.12e". Slower than the
// to_chars path, but it emits the same bytes, so the .cdat/.gdat files are
// identical on every supported target.
char* appendScientificFieldPortable(char* dst, double value, bool leadingSpace) {
    std::ostringstream s;
    s << std::setprecision(12) << std::scientific << std::setw(18) << value;
    const std::string text = s.str();
    std::size_t offset = 0;
    if (leadingSpace) {
        dst[offset++] = ' ';
    }
    std::memcpy(dst + offset, text.data(), text.size());
    return dst + offset + text.size();
}

// Select the direct byte-building path only where the standard library
// actually provides floating-point std::to_chars.
//
// Note __cpp_lib_to_chars is NOT a usable signal here: this libc++ does not
// define it at all, even where the facility works, so testing it selects the
// portable path everywhere and costs an ostringstream per emitted field.
// libc++'s own availability macro is the signal that carries information.
#if defined(_LIBCPP_AVAILABILITY_HAS_TO_CHARS_FLOATING_POINT)
#if _LIBCPP_AVAILABILITY_HAS_TO_CHARS_FLOATING_POINT
#define BNG3_HAS_FP_TO_CHARS 1
#endif
#elif defined(__cpp_lib_to_chars) && __cpp_lib_to_chars >= 201611L
#define BNG3_HAS_FP_TO_CHARS 1
#endif
#if defined(BNG3_HAS_FP_TO_CHARS)

// Floating-point std::to_chars is available: build the bytes directly.
//
// Non-finite values go through the stream instead. std::to_chars formats NaN
// as "-nan(ind)" or "nan(snan)" depending on the payload, while the stream
// emits plain "nan"; those are different bytes, and the stream is what this
// writer has always emitted. Measured over 6,019,750 values, the two agreed on
// every finite value and on infinity, and disagreed only on NaN. A diverged
// simulation is exactly when NaN reaches this loop, so the faithful path has
// to win there.
char* appendScientificField(char* dst, double value, bool leadingSpace) {
    if (!std::isfinite(value)) {
        return appendScientificFieldPortable(dst, value, leadingSpace);
    }
    constexpr std::size_t kWidth = 18;
    char buf[64];
    char* cursor = buf;
    if (leadingSpace) {
        *cursor++ = ' ';
    }
    char* const fieldStart = cursor;
    const auto result = std::to_chars(fieldStart, buf + sizeof(buf), value,
                                      std::chars_format::scientific, 12);
    if (result.ec != std::errc{}) {
        // Cannot happen with a 64-byte buffer and this format (the longest
        // field is 20 characters), but the length below feeds a memmove, so
        // do not trust an errored result.
        return appendScientificFieldPortable(dst, value, leadingSpace);
    }
    const std::size_t length = static_cast<std::size_t>(result.ptr - fieldStart);
    // "%18.12e" right-justifies into 18 columns. The digit string is shorter
    // than that for an ordinary value (17 characters, e.g. "1.000000000000e+00")
    // and LONGER for a three-digit exponent or a wider one with a sign
    // (19 characters, or 20 for -DBL_MAX). Only the short case is padded; the
    // long case is emitted in full, exactly as the stream would.
    const std::size_t pad = (length < kWidth) ? (kWidth - length) : 0;
    if (pad != 0) {
        std::memmove(fieldStart + pad, fieldStart, length);
        std::memset(fieldStart, ' ', pad);
    }
    const std::size_t total = static_cast<std::size_t>(cursor - buf) + pad + length;
    std::memcpy(dst, buf, total);
    return dst + total;
}

#else

char* appendScientificField(char* dst, double value, bool leadingSpace) {
    return appendScientificFieldPortable(dst, value, leadingSpace);
}

#endif

// Accumulates formatted rows and hands the ofstream one write per ~1 MiB
// instead of one insertion per row. Measured on a 40001-row x 9-field write,
// the per-row insertion costs a stream sentry, a filebuf copy and a
// buffer-full test, which together are about a third of what is left of the
// loop once the digit conversion is done. The bytes that reach the file are
// the same bytes, in the same order.
class RowBuffer {
public:
    // `totalBytes` estimates the whole file: the buffer is capped at ~1 MiB so
    // a large file is written in a handful of chunks, and sized down for a
    // small one so a two-row .gdat does not allocate a megabyte.
    RowBuffer(std::ofstream& out, std::size_t totalBytes) : out_(out) {
        buf_.resize(std::min(totalBytes, kFlushAt));
    }

    // Start of writable space for the next row, flushing if fewer than
    // `bytes` remain.
    char* reserve(std::size_t bytes) {
        if (buf_.size() - used_ < bytes) {
            flush();
            if (buf_.size() < bytes) {
                buf_.resize(bytes);
            }
        }
        return buf_.data() + used_;
    }

    void commit(const char* end) { used_ = static_cast<std::size_t>(end - buf_.data()); }

    void flush() {
        if (used_ != 0) {
            out_.write(buf_.data(), static_cast<std::streamsize>(used_));
            used_ = 0;
        }
    }

private:
    static constexpr std::size_t kFlushAt = 1u << 20;

    std::ofstream& out_;
    std::vector<char> buf_;
    std::size_t used_ = 0;
};

// Upper bound on the bytes a text output file of `rows` rows will need, using
// the widest field the emitter can produce. Only used to size RowBuffer.
std::size_t textFileBytes(std::size_t fieldsPerRow, std::size_t rows) {
    return kMaxFieldBytes * (fieldsPerRow + 2) * rows;
}

std::string cdatSpeciesColumnName(const ast::Species& species) {
    // SpeciesGraph::toString() is a display serialization of the graph alone:
    // it omits both the outer compartment and the constant-species marker.
    // CDAT needs a stable identity for each network column, including the
    // compartment-aware graph spelling used by species deduplication.
    std::string name = species.getSpeciesGraph().toStringForDedup();
    if (species.isConstant()) {
        const auto compartmentEnd = !name.empty() && name.front() == '@'
            ? name.find("::")
            : std::string::npos;
        const auto markerPosition = compartmentEnd == std::string::npos
            ? 0
            : compartmentEnd + 2;
        name.insert(markerPosition, "$");
    }
    return name;
}

} // namespace

void OdeIntegrator::writeOutputFiles(const std::string& prefix, const OdeResult& result, bool printCDAT, bool printFunctions, bool append) const {
    // When appending (continue=1), skip the first output row since it
    // duplicates the last row of the previous phase — matches Perl/run_network
    // behavior with the -c flag.
    const std::size_t startStep = append ? 1 : 0;

    // Write .cdat (concentrations) - only if printCDAT is true
    if (printCDAT) {
        std::ofstream cdat(prefix + ".cdat", append ? std::ios::app : std::ios::trunc);
        if (!cdat) {
            throw std::runtime_error("Failed to open " + prefix + ".cdat for writing");
        }

        // Header line - only write if not appending
        if (!append) {
            cdat << "#";
            cdat << std::setw(17) << "time";
            for (std::size_t i = 0; i < network_.species.size(); ++i) {
                cdat << " " << std::setw(18)
                     << cdatSpeciesColumnName(network_.species.get(i));
            }
            cdat << "\n";
        }

        // Rows are formatted into a reused buffer and the buffer is written
        // once per ~1 MiB, so the loop pays neither an ostream insertion
        // (sentry + num_put facet lookup + num_put locale grouping) nor a
        // stream write per numeric field.
        RowBuffer rows(cdat,
                       textFileBytes(result.concentrations.empty()
                                         ? 0
                                         : result.concentrations.front().size(),
                                     result.timePoints.size() - startStep));
        for (std::size_t step = startStep; step < result.timePoints.size(); ++step) {
            const std::vector<double>& conc = result.concentrations[step];
            char* const row = rows.reserve(kMaxFieldBytes * (conc.size() + 2));
            char* cursor = appendScientificField(row, result.timePoints[step],
                                                /*leadingSpace=*/false);
            for (const auto& c : conc) {
                cursor = appendScientificField(cursor, c, /*leadingSpace=*/true);
            }
            *cursor++ = '\n';
            rows.commit(cursor);
        }
        rows.flush();
    }

    // Write .gdat (observables)
    std::ofstream gdat(prefix + ".gdat", append ? std::ios::app : std::ios::trunc);
    if (!gdat) {
        throw std::runtime_error("Failed to open " + prefix + ".gdat for writing");
    }

    // Collect function names and expressions for print_functions output
    std::vector<std::string> funcNames;
    std::vector<ast::Expression> funcExprs;
    if (printFunctions) {
        for (const auto& fn : model_.getFunctions()) {
            funcNames.push_back(fn.getName());
            funcExprs.push_back(fn.getExpression());
        }
    }

    // Header line - only write if not appending
    if (!append) {
        gdat << "#";
        gdat << std::setw(17) << "time";
        for (const auto& group : compiledGroups_) {
            gdat << " " << std::setw(18) << group.name;
        }
        for (const auto& fname : funcNames) {
            gdat << " " << std::setw(18) << fname;
        }
        gdat << "\n";
    }

    // Rows are built in a reused buffer and written once per ~1 MiB; see the
    // .cdat loop above for why.
    RowBuffer rows(gdat,
                   textFileBytes((result.observables.empty()
                                      ? 0
                                      : result.observables.front().size()) +
                                     funcExprs.size(),
                                 result.timePoints.size() - startStep));
    for (std::size_t step = startStep; step < result.timePoints.size(); ++step) {
        const std::vector<double>& obs = result.observables[step];
        char* const row = rows.reserve(kMaxFieldBytes * (obs.size() + funcExprs.size() + 2));
        char* cursor = appendScientificField(row, result.timePoints[step],
                                            /*leadingSpace=*/false);
        for (const auto& o : obs) {
            cursor = appendScientificField(cursor, o, /*leadingSpace=*/true);
        }
        // Evaluate and print function values
        if (printFunctions && !funcExprs.empty()) {
            // Build observable value map for this time step
            std::unordered_map<std::string, double> obsMap;
            for (std::size_t gi = 0; gi < compiledGroups_.size() && gi < result.observables[step].size(); ++gi) {
                obsMap[compiledGroups_[gi].name] = result.observables[step][gi];
            }
            // Also resolve model-defined functions recursively.  A function
            // output may reference another zero-argument function (for
            // example f_diff() = f_correct() - f_builtin()), so treating
            // every identifier as a parameter loses the model-function
            // namespace and raises "Unknown parameter".
            std::function<double(const std::string&)> resolver;
            resolver = [&](const std::string& name) -> double {
                auto obsIt = obsMap.find(name);
                if (obsIt != obsMap.end()) return obsIt->second;
                for (const auto& function : model_.getFunctions()) {
                    if (function.getName() == name && function.getArgs().empty()) {
                        return function.getExpression().evaluate(
                            resolver, result.timePoints[step]);
                    }
                }
                // As in derivs(): the parameter may depend on time.
                return model_.getParameters().evaluate(
                    name, result.timePoints[step]);
            };
            for (auto& fexpr : funcExprs) {
                double val = fexpr.evaluate(resolver, result.timePoints[step]);
                cursor = appendScientificField(cursor, val, /*leadingSpace=*/true);
            }
        }
        *cursor++ = '\n';
        rows.commit(cursor);
    }
    rows.flush();
}

void OdeIntegrator::writeBinaryOutputFiles(const std::string& prefix, const OdeResult& result, bool printCDAT) const {
    if (printCDAT) {
        std::ofstream cdat(prefix + ".cdat", std::ios::binary | std::ios::trunc);
        if (!cdat) {
            throw std::runtime_error("Failed to open " + prefix + ".cdat for binary writing");
        }
        // Accumulated and written once per ~1 MiB; see RowBuffer above.
        RowBuffer rows(cdat,
                       sizeof(float) * result.timePoints.size() *
                           (result.concentrations.empty()
                                ? 1
                                : result.concentrations.front().size() + 1));
        for (std::size_t step = 0; step < result.timePoints.size(); ++step) {
            const std::vector<double>& conc = result.concentrations[step];
            char* const row = rows.reserve(sizeof(float) * (conc.size() + 1));
            char* cursor = row;
            float t = static_cast<float>(result.timePoints[step]);
            std::memcpy(cursor, &t, sizeof(float));
            cursor += sizeof(float);
            for (const auto& c : conc) {
                float val = static_cast<float>(c);
                std::memcpy(cursor, &val, sizeof(float));
                cursor += sizeof(float);
            }
            rows.commit(cursor);
        }
        rows.flush();
    }

    std::ofstream gdat(prefix + ".gdat", std::ios::binary | std::ios::trunc);
    if (!gdat) {
        throw std::runtime_error("Failed to open " + prefix + ".gdat for binary writing");
    }
    RowBuffer rows(gdat,
                   sizeof(float) * result.timePoints.size() *
                       (result.observables.empty() ? 1 : result.observables.front().size() + 1));
    for (std::size_t step = 0; step < result.timePoints.size(); ++step) {
        const std::vector<double>& obs = result.observables[step];
        char* const row = rows.reserve(sizeof(float) * (obs.size() + 1));
        char* cursor = row;
        float t = static_cast<float>(result.timePoints[step]);
        std::memcpy(cursor, &t, sizeof(float));
        cursor += sizeof(float);
        for (const auto& o : obs) {
            float val = static_cast<float>(o);
            std::memcpy(cursor, &val, sizeof(float));
            cursor += sizeof(float);
        }
        rows.commit(cursor);
    }
    rows.flush();
}

// ---------------------------------------------------------------------------
// Batch SSA: run N independent trajectories, aggregate mean + std dev.
// Routes to a GPU backend when one is compiled in, has a device, and the batch
// is large enough to pay for the launch; otherwise falls back to the CPU pool.
// ---------------------------------------------------------------------------
OdeResult OdeIntegrator::integrateBatchSSA(const OdeOptions& opts) {
    const bool hasDelayedReactions = std::any_of(
        compiledRxns_.begin(), compiledRxns_.end(),
        [](const CompiledReaction& reaction) { return reaction.delay > 0.0; });
    if (opts.batchGpuPreferred && !hasDelayedReactions) {
        const GpuBackendKind requested = gpuBackendFromName(opts.batchGpuBackend);
        const GpuBackendKind selected =
            (requested == GpuBackendKind::Auto) ? defaultGpuBackend() : requested;

        if (selected != GpuBackendKind::None) {
            if (!gpuBatchSsaWorthwhile(compiledRxns_.size(), opts.batchSize)) {
                std::cerr << "[bng_cpp] batch_ssa: " << gpuBackendName(selected)
                          << " backend skipped, batch of " << opts.batchSize
                          << " over " << compiledRxns_.size()
                          << " reactions is below the launch-overhead threshold.\n";
            } else {
                try {
                    const auto flat =
                        FlattenedReactionNetwork::fromModelAndNetwork(model_, network_);
                    auto backend = makeGpuSsaBackend(selected, flat);
                    if (backend) {
                        BatchSsaOptions batchOpts;
                        batchOpts.batchSize = opts.batchSize;
                        batchOpts.tStart    = opts.tStart;
                        batchOpts.tEnd      = opts.tEnd;
                        batchOpts.nSteps    = static_cast<int>(opts.nSteps);
                        batchOpts.baseSeed  = opts.seed;
                        batchOpts.maxSimSteps = opts.maxSimSteps;
                        auto metrics = backend->simulate(flat, batchOpts);

                        // Convert BatchSsaMetrics -> OdeResult (mean trajectory + std devs)
                        OdeResult result;
                        result.batchSize       = opts.batchSize;
                        result.timePoints      = metrics.timePointsDouble;
                        result.concentrations  = metrics.meanSpecies;
                        result.observables     = metrics.meanObservables;
                        result.batchStdDevs    = metrics.stdSpecies;
                        result.batchObsStdDevs = metrics.stdObservables;
                        result.eventCount      = static_cast<std::size_t>(metrics.totalEvents);

                        // OdeResult::concentrations / batchStdDevs are
                        // [timeIndex][speciesIndex], and every consumer walks
                        // them in lockstep with timePoints: writeOutputFiles
                        // indexes concentrations[step] for step up to
                        // timePoints.size(), save_progress does the same, and
                        // the Python binding shapes them as an (n_steps,
                        // n_species) array.  A backend that records only the
                        // per-trajectory final species -- which is what
                        // detail::fillDoubleFields does, collapsing
                        // finalSpecies into a single row -- cannot satisfy
                        // that shape, and handing it back would both mis-shape
                        // the result and read out of bounds in the .cdat
                        // writer.  Reject it so the catch below routes to the
                        // CPU thread pool, which produces the full grid.
                        if (result.concentrations.size() != result.timePoints.size() ||
                            result.batchStdDevs.size() != result.timePoints.size()) {
                            throw std::runtime_error(
                                "backend cannot produce a full species time course: "
                                "got " + std::to_string(result.concentrations.size()) +
                                " species row(s) for " +
                                std::to_string(result.timePoints.size()) +
                                " output time point(s)");
                        }

                        return result;
                    }
                } catch (const std::exception& ex) {
                    std::cerr << "[bng_cpp] batch_ssa: GPU path unavailable (" << ex.what()
                              << "), falling back to CPU thread pool.\n";
                }
            }
        }
    }

    // CPU thread-pool fallback.
    // Each thread runs integrateSSA independently; results are aggregated.
    const std::size_t B = opts.batchSize;
    const std::size_t nWorkers = std::min(B,
        static_cast<std::size_t>(std::max(1u, std::thread::hardware_concurrency())));

    // Pre-compute output time grid from a single reference run's time points.
    OdeOptions singleOpts = opts;
    singleOpts.batchSize = 0;
    singleOpts.isolatedTrajectory = true;
    singleOpts.seed = (opts.seed == 0) ? 1u : opts.seed;
    const auto refTimes = outputTimes(singleOpts);
    const std::size_t T = refTimes.size();
    const std::size_t S = nSpecies_;
    const std::size_t G = compiledGroups_.size();

    // Accumulators (mean, M2 for Welford online variance)
    std::vector<std::vector<double>> sumSpec(T, std::vector<double>(S, 0.0));
    std::vector<std::vector<double>> sumSqSpec(T, std::vector<double>(S, 0.0));
    std::vector<std::vector<double>> sumObs(T, std::vector<double>(G, 0.0));
    std::vector<std::vector<double>> sumSqObs(T, std::vector<double>(G, 0.0));
    std::size_t totalEvents = 0;
    std::mutex mu;

    // Chunk trajectories across workers.
    std::vector<std::future<void>> futures;
    futures.reserve(nWorkers);
    const std::size_t chunk = (B + nWorkers - 1) / nWorkers;
    for (std::size_t w = 0; w < nWorkers; ++w) {
        const std::size_t lo = w * chunk;
        const std::size_t hi = std::min(lo + chunk, B);
        if (lo >= hi) break;
        futures.push_back(std::async(std::launch::async, [&, lo, hi]() {
            // Local accumulators avoid lock contention inside the hot loop.
            std::vector<std::vector<double>> locSumSpec(T, std::vector<double>(S, 0.0));
            std::vector<std::vector<double>> locSumSqSpec(T, std::vector<double>(S, 0.0));
            std::vector<std::vector<double>> locSumObs(T, std::vector<double>(G, 0.0));
            std::vector<std::vector<double>> locSumSqObs(T, std::vector<double>(G, 0.0));
            std::size_t locEvents = 0;

            OdeIntegrator localInt(model_, network_);
            OdeOptions trajOpts = opts;
            trajOpts.batchSize = 0;
            trajOpts.isolatedTrajectory = true;
            for (std::size_t traj = lo; traj < hi; ++traj) {
                // Each trajectory gets its own decorrelated seed. See
                // batchTrajectorySeed in engine/BatchSsa.hpp for why this is a
                // hash of (base, traj) rather than base + traj, and why it must
                // match the GPU backends' derivation exactly.
                const unsigned int base = (opts.seed == 0) ? 1u : opts.seed;
                trajOpts.seed = batchTrajectoryEngineSeed(base, traj);
                OdeResult r = localInt.integrate(trajOpts);
                locEvents += r.eventCount;
                for (std::size_t t = 0; t < std::min(T, r.timePoints.size()); ++t) {
                    for (std::size_t s = 0; s < std::min(S, r.concentrations[t].size()); ++s) {
                        locSumSpec[t][s]   += r.concentrations[t][s];
                        locSumSqSpec[t][s] += r.concentrations[t][s] * r.concentrations[t][s];
                    }
                    for (std::size_t g = 0; g < std::min(G, r.observables[t].size()); ++g) {
                        locSumObs[t][g]   += r.observables[t][g];
                        locSumSqObs[t][g] += r.observables[t][g] * r.observables[t][g];
                    }
                }
            }
            std::lock_guard<std::mutex> lk(mu);
            totalEvents += locEvents;
            for (std::size_t t = 0; t < T; ++t) {
                for (std::size_t s = 0; s < S; ++s) {
                    sumSpec[t][s]   += locSumSpec[t][s];
                    sumSqSpec[t][s] += locSumSqSpec[t][s];
                }
                for (std::size_t g = 0; g < G; ++g) {
                    sumObs[t][g]   += locSumObs[t][g];
                    sumSqObs[t][g] += locSumSqObs[t][g];
                }
            }
        }));
    }
    for (auto& f : futures) f.get();

    // Build mean + std-dev result.
    OdeResult result;
    result.batchSize  = B;
    result.eventCount = totalEvents;
    result.timePoints = refTimes;
    result.concentrations.resize(T, std::vector<double>(S));
    result.batchStdDevs.resize(T, std::vector<double>(S));
    result.observables.resize(T, std::vector<double>(G));
    result.batchObsStdDevs.resize(T, std::vector<double>(G));
    const double invB = 1.0 / static_cast<double>(B);
    for (std::size_t t = 0; t < T; ++t) {
        for (std::size_t s = 0; s < S; ++s) {
            const double mean = sumSpec[t][s] * invB;
            result.concentrations[t][s] = mean;
            const double var = sumSqSpec[t][s] * invB - mean * mean;
            result.batchStdDevs[t][s] = std::sqrt(std::max(0.0, var));
        }
        for (std::size_t g = 0; g < G; ++g) {
            const double mean = sumObs[t][g] * invB;
            result.observables[t][g] = mean;
            const double var = sumSqObs[t][g] * invB - mean * mean;
            result.batchObsStdDevs[t][g] = std::sqrt(std::max(0.0, var));
        }
    }
    return result;
}

void OdeIntegrator::writeBatchStdDevsFile(const std::string& prefix, const OdeResult& result) const {
    if (result.batchSize == 0 || result.batchObsStdDevs.empty()) return;
    std::ofstream bdat(prefix + ".bdat", std::ios::trunc);
    if (!bdat) {
        throw std::runtime_error("Failed to open " + prefix + ".bdat for writing");
    }
    // Header: same columns as .gdat but values are std devs.
    bdat << "# Batch SSA std dev  batch_size=" << result.batchSize << "\n";
    bdat << "#";
    bdat << std::setw(17) << "time";
    for (const auto& group : compiledGroups_) {
        bdat << " " << std::setw(18) << group.name;
    }
    bdat << "\n";
    // Same field format as the .gdat loop above, emitted the same way.
    RowBuffer rows(bdat,
                   textFileBytes(result.batchObsStdDevs.front().size(),
                                 result.timePoints.size()));
    for (std::size_t step = 0; step < result.timePoints.size(); ++step) {
        const std::vector<double>& sd = result.batchObsStdDevs[step];
        char* const row = rows.reserve(kMaxFieldBytes * (sd.size() + 2));
        char* cursor = appendScientificField(row, result.timePoints[step],
                                            /*leadingSpace=*/false);
        for (const auto& s : sd) {
            cursor = appendScientificField(cursor, s, /*leadingSpace=*/true);
        }
        *cursor++ = '\n';
        rows.commit(cursor);
    }
    rows.flush();
}


// Static C-style callback for CVODE (v7: sunrealtype instead of realtype)
static int cvodeCallbackWrapper(sunrealtype t, N_Vector y, N_Vector ydot, void* user_data) {
    auto* self = static_cast<OdeIntegrator*>(user_data);
    self->cvodeDerivs(static_cast<double>(t), NV_DATA_S(y), NV_DATA_S(ydot));
    return 0;
}

static int idaResidualWrapper(sunrealtype t, N_Vector y, N_Vector ydot,
                              N_Vector residual, void* user_data) {
    return static_cast<OdeIntegrator*>(user_data)->idaResidual(
        static_cast<double>(t), NV_DATA_S(y), NV_DATA_S(ydot),
        NV_DATA_S(residual));
}

static int idaEventRootWrapper(sunrealtype time, N_Vector state, N_Vector,
                               sunrealtype* roots, void* userData) {
    try {
        static_cast<OdeIntegrator*>(userData)->cvodeEventRoots(
            static_cast<double>(time), NV_DATA_S(state), roots);
        return 0;
    } catch (...) {
        return -1;
    }
}

static int cvodeEventRootWrapper(sunrealtype time, N_Vector state,
                                 sunrealtype* roots, void* userData) {
    try {
        static_cast<OdeIntegrator*>(userData)->cvodeEventRoots(
            static_cast<double>(time), NV_DATA_S(state), roots);
        return 0;
    } catch (...) { return -1; }
}

namespace {

// Owns the SUNDIALS resources of one CVODE integration.
//
// CVODE, its state vector, the linear solver, the matrix and the SUNDIALS
// context are raw handles with manual cleanup.  When an exception unwinds
// the integration -- for example the right-hand side of a lazy ``stop_if``
// expression -- none of the explicit cleanup blocks run and every handle
// leaks.  Releasing them from one owner keeps the release order identical
// to the manual sequence and makes it impossible for an exception to skip
// it.
struct CvodeSession {
    SUNContext sunctx = nullptr;
    N_Vector y = nullptr;
    void* cvode_mem = nullptr;
    SUNNonlinearSolver nonlinearSolver = nullptr;
    SUNMatrix A = nullptr;
    SUNLinearSolver LS = nullptr;

    CvodeSession() = default;
    CvodeSession(const CvodeSession&) = delete;
    CvodeSession& operator=(const CvodeSession&) = delete;

    ~CvodeSession() {
        if (LS) { SUNLinSolFree(LS); LS = nullptr; }
        if (A) { SUNMatDestroy(A); A = nullptr; }
        if (cvode_mem) { CVodeFree(&cvode_mem); }
        if (nonlinearSolver) {
            SUNNonlinSolFree(nonlinearSolver);
            nonlinearSolver = nullptr;
        }
        if (y) { N_VDestroy(y); y = nullptr; }
        if (sunctx) { SUNContext_Free(&sunctx); }
    }
};

struct IdaSession {
    SUNContext sunctx = nullptr;
    N_Vector y = nullptr;
    N_Vector ydot = nullptr;
    N_Vector id = nullptr;
    N_Vector absTol = nullptr;
    void* ida_mem = nullptr;
    SUNMatrix A = nullptr;
    SUNLinearSolver LS = nullptr;

    IdaSession() = default;
    IdaSession(const IdaSession&) = delete;
    IdaSession& operator=(const IdaSession&) = delete;
    ~IdaSession() {
        if (LS) SUNLinSolFree(LS);
        if (A) SUNMatDestroy(A);
        if (ida_mem) IDAFree(&ida_mem);
        if (absTol) N_VDestroy(absTol);
        if (id) N_VDestroy(id);
        if (ydot) N_VDestroy(ydot);
        if (y) N_VDestroy(y);
        if (sunctx) SUNContext_Free(&sunctx);
    }
};

}  // namespace

OdeResult OdeIntegrator::integrateCvode(const OdeOptions& opts,
                                         bool useAdamsFallback) {
    auto times = outputTimes(opts);
    const auto stopIfExpr = parseStopIf(opts);
    pendingEvents_.clear();
    std::optional<SimulationSession> fallbackSession;
    auto* eventSession = activeSimulationSession_;
    if (!eventSession) {
        fallbackSession = network_.snapshotSimulationSession();
        eventSession = &*fallbackSession;
    }
    if (eventSession && !eventSession->rngInitialized) {
        const auto seed = opts.seed > 0
            ? static_cast<std::mt19937_64::result_type>(opts.seed)
            : static_cast<std::mt19937_64::result_type>(std::random_device{}());
        eventSession->rng.seed(seed);
        eventSession->rngInitialized = true;
    }
    if (opts.continueSimulation && eventSession) {
        for (const auto& pending : eventSession->pendingNativeEvents) {
            pendingEvents_.push_back({pending.event, pending.executionTime,
                                      pending.values});
        }
        triggerRoseAt_ = eventSession->eventTriggerRoseAt;
    }
    if (!opts.continueSimulation ||
        triggerRoseAt_.size() != nativeEvents_.size()) {
        triggerRoseAt_.assign(nativeEvents_.size(),
                              -std::numeric_limits<double>::infinity());
    }

    std::vector<double> initialState(nSpecies_);
    std::vector<double> initialDerivatives(nSpecies_);
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        initialState[i] = activeSimulationSession_ &&
                activeSimulationSession_->state.size() == nSpecies_
            ? activeSimulationSession_->state[i]
            : network_.species.get(i).getAmount();
    }
    if (stopIfExpr.has_value() &&
        stopConditionMet(*stopIfExpr, opts.tStart, initialState) &&
        times.front() != opts.tStart) {
        times.insert(times.begin(), opts.tStart);
    }
    if (!nativeEvents_.empty()) {
        // The root function value of every group at the start of the run.
        // A group whose value changed its sign since then crossed its trigger
        // in the meantime.
        lastRootValues_.clear();
        for (const auto& group : nativeEventGroups_) {
            lastRootValues_.push_back(
                eventRootValue(group.trigger, opts.tStart, initialState.data()));
        }
        for (std::size_t index = 0;
             !opts.continueSimulation && index < nativeEvents_.size(); ++index) {
            const auto& event = nativeEvents_[index];
            const auto& trigger = event.trigger;
            // CVODE does not report a root that starts exactly at zero.  For
            // a strict trigger whose root surface is rising at tStart, queue
            // its right-limit event at tStart so the first integration step
            // starts from the post-trigger state.  The SBML trigger itself is
            // still false at equality; this represents the crossing that
            // occurs immediately after tStart at the solver's time precision.
            if (isStrictTrigger(trigger) &&
                eventRootValue(trigger, opts.tStart, initialState.data()) == 0.0) {
                std::vector<double> initialRates(nSpecies_);
                derivs(opts.tStart, initialState.data(), initialRates.data());
                const auto surface = triggerSurface(
                    trigger, opts.tStart, initialState.data(), initialRates);
                if (surface.derivative > 0.0) {
                    PendingEvent pending;
                    pending.event = index;
                    pending.executionTime = opts.tStart +
                        eventDelay(event, opts.tStart, initialState.data());
                    if (event.useValuesFromTriggerTime) {
                        pending.values = eventValues(
                            event, opts.tStart, initialState.data());
                    }
                    triggerRoseAt_[index] = opts.tStart;
                    pendingEvents_.push_back(std::move(pending));
                } else if (surface.derivative == 0.0) {
                    throw std::runtime_error(
                        std::string(ast::kUnsupportedEventExecutionMessage) +
                        ": strict trigger direction is unresolved at the initial time");
                }
            }
            if (!event.initialValue &&
                triggerHolds(trigger, opts.tStart, initialState.data())) {
                // The trigger holds at the start of the simulation and the
                // trigger's initial value is false, so the event triggers
                // immediately (SBML L3V2 Core Sec. 4.12.2).
                PendingEvent pending;
                pending.event = index;
                pending.executionTime =
                    opts.tStart + eventDelay(event, opts.tStart, initialState.data());
                if (event.useValuesFromTriggerTime) {
                    pending.values = eventValues(event, opts.tStart, initialState.data());
                }
                triggerRoseAt_[index] = opts.tStart;
                pendingEvents_.push_back(std::move(pending));
            }
        }
        // The events that trigger at the start of the simulation are executed
        // before the solver takes its first step.
        if (applyDueEvents(opts.tStart, initialState)) {
            recordHistoryJump(opts.tStart, initialState);
        }
    }

    // The SUNDIALS handles used below are raw pointers with manual
    // cleanup.  ``CvodeSession`` owns them, so an exception that unwinds
    // this function releases them instead of leaking them.  The aliases
    // keep the rest of the function unchanged.
    CvodeSession session;
    SUNContext& sunctx = session.sunctx;
    N_Vector& y = session.y;
    void*& cvode_mem = session.cvode_mem;
    SUNNonlinearSolver& nonlinearSolver = session.nonlinearSolver;
    SUNMatrix& A = session.A;
    SUNLinearSolver& LS = session.LS;

    // SUNDIALS v7: Create context (required for all SUNDIALS objects)
    int flag = SUNContext_Create(SUN_COMM_NULL, &sunctx);
    if (flag != 0) {
        throw std::runtime_error("SUNContext_Create failed");
    }

    // Initialize state vector (v7: takes sunctx)
    y = N_VNew_Serial(static_cast<sunindextype>(nSpecies_), sunctx);
    if (y == nullptr) {
        throw std::runtime_error("Failed to allocate CVODE state vector");
    }

    // Converted SBML models can legitimately combine sub-molecular amounts
    // with molecule-number rate constants.  Integrating those raw values
    // makes CVODE's initial Newton step ill-conditioned even when the source
    // model and the generated network are finite.  Use a per-state scale
    // based on the initial amount and one characteristic time of motion.
    derivs(opts.tStart, initialState.data(), initialDerivatives.data());
    const double timeScale = std::max(std::abs(opts.tEnd - opts.tStart), 1.0);
    cvodeStateScale_.resize(nSpecies_);
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        double scale = std::abs(initialState[i]);
        if (std::isfinite(initialDerivatives[i])) {
            scale = std::max(scale, std::abs(initialDerivatives[i]) * timeScale);
        }
        if (!std::isfinite(scale) || scale < 1e-30) scale = 1.0;
        cvodeStateScale_[i] = scale;
        NV_Ith_S(y, i) = initialState[i] / scale;
    }

    // The default solver remains BDF/Newton. After a repeated BDF corrector
    // convergence failure, one fresh attempt uses Adams with fixed-point
    // iteration, which avoids finite-difference Jacobians at singular
    // fractional-power states without changing the model or error weights.
    const int linearMultistepMethod = useAdamsFallback ? CV_ADAMS : CV_BDF;
    cvode_mem = CVodeCreate(linearMultistepMethod, sunctx);
    if (cvode_mem == nullptr) {
        throw std::runtime_error("Failed to create CVODE solver");
    }

    // Initialize CVODE at the requested start time (critical for continue=1 phases)
    flag = CVodeInit(cvode_mem, cvodeCallbackWrapper, opts.tStart, y);
    if (flag != CV_SUCCESS) {
        throw std::runtime_error("CVodeInit failed with flag " + std::to_string(flag));
    }
    if (useAdamsFallback) {
        nonlinearSolver = SUNNonlinSol_FixedPoint(y, 0, sunctx);
        if (nonlinearSolver == nullptr) {
            throw std::runtime_error("Failed to create CVODE fixed-point solver");
        }
        flag = CVodeSetNonlinearSolver(cvode_mem, nonlinearSolver);
        if (flag != CV_SUCCESS) {
            throw std::runtime_error("CVodeSetNonlinearSolver (fixed-point) failed");
        }
    }
    // Keep the standard BDF order ceiling. The component-scaled state
    // addresses disparate SBML scales while the normal order ceiling
    // preserves parity with libRoadRunner CVODE.
    if (!useAdamsFallback) {
        CVodeSetMaxOrd(cvode_mem, 5);
    }

    // The state is scaled below, so use component-wise absolute tolerances
    // that map the requested physical ``atol`` back into scaled coordinates.
    // A scalar tolerance here would be far too strict for sub-molecular SBML
    // amounts and far too loose for molecule-number states.
    N_Vector scaledAbsTol = N_VNew_Serial(static_cast<sunindextype>(nSpecies_), sunctx);
    if (scaledAbsTol == nullptr) {
        throw std::runtime_error("Failed to allocate CVODE absolute tolerances");
    }
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        NV_Ith_S(scaledAbsTol, i) = opts.atol / cvodeStateScale_[i];
    }
    flag = CVodeSVtolerances(cvode_mem, opts.rtol, scaledAbsTol);
    N_VDestroy(scaledAbsTol);
    if (flag != CV_SUCCESS) {
        throw std::runtime_error("CVodeSStolerances failed");
    }

    if (opts.enforceNonnegative) {
        // Constraints are an opt-in solver fallback.  Never apply them to
        // rate-rule states or initially negative values: those are explicit
        // signs that the source model is not a population-constrained system.
        bool canConstrainStates = true;
        for (std::size_t i = 0; i < nSpecies_; ++i) {
            const auto name = network_.species.get(i).getSpeciesGraph().toString();
            const bool isRateRuleState = name.find("__rate_rule_state__") != std::string::npos;
            if (isRateRuleState || initialState[i] < 0.0) {
                canConstrainStates = false;
                break;
            }
        }
        if (canConstrainStates) {
            N_Vector constraints = N_VNew_Serial(static_cast<sunindextype>(nSpecies_), sunctx);
            if (constraints == nullptr) {
                throw std::runtime_error("Failed to allocate CVODE constraints");
            }
            for (std::size_t i = 0; i < nSpecies_; ++i) {
                NV_Ith_S(constraints, i) = 1.0;
            }
            flag = CVodeSetConstraints(cvode_mem, constraints);
            N_VDestroy(constraints);
            if (flag != CV_SUCCESS) {
                throw std::runtime_error("CVodeSetConstraints failed");
            }
        }
    }

    // Set user data
    CVodeSetUserData(cvode_mem, this);
    if (!nativeEventGroups_.empty()) {
        // One root per trigger group.  The root function is positive exactly
        // where the trigger holds, so an increasing crossing is the trigger's
        // rising edge.
        const auto roots = static_cast<int>(nativeEventRoots_.size());
        if (CVodeRootInit(cvode_mem, roots, cvodeEventRootWrapper) != CV_SUCCESS) {
            throw std::runtime_error("bng3_events CVodeRootInit failed");
        }
        std::vector<int> directions(static_cast<std::size_t>(roots), 1);
        CVodeSetRootDirection(cvode_mem, directions.data());
    }

    // Set max number of steps (BNG2 default: 2000, auto-increases if needed)
    CVodeSetMaxNumSteps(cvode_mem, 2000);
    if (opts.maxStep > 0.0) {
        flag = CVodeSetMaxStep(cvode_mem, opts.maxStep);
        if (flag != CV_SUCCESS) {
            throw std::runtime_error("CVodeSetMaxStep failed");
        }
    }

    double minimumDelay = std::numeric_limits<double>::infinity();
    for (const double delay : historyDelays_) {
        minimumDelay = std::min(minimumDelay, delay);
    }
    if (std::isfinite(minimumDelay)) {
        const double stepLimit = opts.maxStep > 0.0
            ? std::min(opts.maxStep, minimumDelay) : minimumDelay;
        if (CVodeSetMaxStep(cvode_mem, stepLimit) != CV_SUCCESS) {
            throw std::runtime_error("CVodeSetMaxStep for delayed history failed");
        }
    }

    // Note: Perl's run_network does NOT enable stability limit detection.
    // Disabled for exact parity with Perl CVODE stepping behavior.
    // CVodeSetStabLimDet(cvode_mem, 1);

    // Linear solver setup (v7 API: SUNMatrix + SUNLinearSolver + CVodeSetLinearSolver)
    // Choose solver based on network size and sparse option
    // Dense for small networks, GMRES for large/sparse networks
    if (!useAdamsFallback) {
        if (!opts.sparse && nSpecies_ < 500) {
            // Dense direct solver
            A = SUNDenseMatrix(static_cast<sunindextype>(nSpecies_),
                               static_cast<sunindextype>(nSpecies_), sunctx);
            if (A == nullptr) {
                throw std::runtime_error("SUNDenseMatrix failed");
            }
            LS = SUNLinSol_Dense(y, A, sunctx);
            if (LS == nullptr) {
                throw std::runtime_error("SUNLinSol_Dense failed");
            }
            flag = CVodeSetLinearSolver(cvode_mem, LS, A);
            if (flag != CV_SUCCESS) {
                throw std::runtime_error("CVodeSetLinearSolver (dense) failed");
            }
        } else {
            // GMRES iterative solver (better for large sparse systems)
            LS = SUNLinSol_SPGMR(y, SUN_PREC_NONE, 0, sunctx);
            if (LS == nullptr) {
                throw std::runtime_error("SUNLinSol_SPGMR failed");
            }
            flag = CVodeSetLinearSolver(cvode_mem, LS, nullptr);
            if (flag != CV_SUCCESS) {
                throw std::runtime_error("CVodeSetLinearSolver (GMRES) failed");
            }
        }
    }

    // Integration loop
    OdeResult result;
    result.timePoints.reserve(times.size());
    result.concentrations.reserve(times.size());

    double t = opts.tStart;
    {
        std::vector<double> state(nSpecies_);
        for (std::size_t i = 0; i < nSpecies_; ++i) {
            state[i] = NV_Ith_S(y, i) * cvodeStateScale_[i];
        }
        recordHistoryPoint(t, state);
    }

    for (std::size_t step = 0; step < times.size(); ++step) {
        const double tOut = times[step];

        if (tOut > t) {
            long int maxSteps = 2000;
            while (true) {
                // A queued event executes at its own instant, so the solver
                // stops there before the output grid continues.
                double target = tOut;
                for (const auto& pending : pendingEvents_) {
                    if (pending.executionTime < target) target = pending.executionTime;
                }
                for (const double delay : historyDelays_) {
                    const double historyStart = activeSimulationSession_
                        ? activeSimulationSession_->startTime : opts.tStart;
                    const double elapsed = std::max(0.0, t - historyStart);
                    const double interval = std::floor(elapsed / delay) + 1.0;
                    const double breakpoint = historyStart + interval * delay;
                    if (breakpoint > t + 1e-13 && breakpoint < target) {
                        target = breakpoint;
                    }
                    if (activeSimulationSession_) {
                        for (const double discontinuity :
                             activeSimulationSession_->discontinuities) {
                            if (discontinuity > t + 1e-13) continue;
                            const double lagged =
                                std::floor((t - discontinuity) / delay) + 1.0;
                            const double propagated = discontinuity + lagged * delay;
                            if (propagated > t + 1e-13 && propagated < target) {
                                target = propagated;
                            }
                        }
                    }
                }
                if (target < t) target = t;
                if (target <= t) {
                    // Nothing lies between the current instant and the output
                    // time: only a queued event that is due now remains.
                    std::vector<double> dueState(nSpecies_);
                    for (std::size_t i = 0; i < nSpecies_; ++i) {
                        dueState[i] = NV_Ith_S(y, i) * cvodeStateScale_[i];
                    }
                    if (!applyDueEvents(t, dueState)) break;
                    for (std::size_t i = 0; i < nSpecies_; ++i) {
                        NV_Ith_S(y, i) = dueState[i] / cvodeStateScale_[i];
                    }
                    if (CVodeReInit(cvode_mem, t, y) != CV_SUCCESS) {
                        // The session releases the SUNDIALS handles.
                        throw std::runtime_error("bng3_events CVodeReInit failed");
                    }
                    continue;
                }
                if (target < tOut - 1e-12 || recordsHistory()) {
                    // CV_NORMAL may step past a returned output/root time.
                    // If target is already inside that step, CVode interpolates
                    // to it; a stop behind the internal time is invalid.
                    sunrealtype internalTime;
                    if (CVodeGetCurrentTime(cvode_mem, &internalTime) != CV_SUCCESS) {
                        throw std::runtime_error("CVodeGetCurrentTime failed");
                    }
                    if (target > internalTime &&
                        CVodeSetStopTime(cvode_mem, target) != CV_SUCCESS) {
                        throw std::runtime_error("CVodeSetStopTime failed");
                    }
                }
                // Method-of-steps needs every accepted solver state in the
                // history. Keep CV_NORMAL for ordinary simulations so this
                // feature does not change their established CVODE path.
                flag = CVode(cvode_mem, target, y, &t,
                             recordsHistory() ? CV_ONE_STEP : CV_NORMAL);

                if (flag == CV_ROOT_RETURN) {
                    // CVodeGetRootInfo writes one entry per registered root
                    // function, not a single root index. Keep the buffer sized
                    // to the conjunct roots passed to CVodeRootInit above.
                    std::vector<int> rootsFound(nativeEventRoots_.size());
                    if (CVodeGetRootInfo(cvode_mem, rootsFound.data()) != CV_SUCCESS) {
                        throw std::runtime_error("bng3_events CVodeGetRootInfo failed");
                    }
                    const auto root = std::find_if(
                        rootsFound.begin(), rootsFound.end(),
                        [](int rootDirection) { return rootDirection > 0; });
                    if (root != rootsFound.end()) {
                        std::vector<double> state(nSpecies_);
                        for (std::size_t i = 0; i < nSpecies_; ++i) state[i] = NV_Ith_S(y, i) * cvodeStateScale_[i];
                        recordHistoryPoint(t, state);
                        // The session owns the SUNDIALS handles: an
                        // exception here unwinds the integration and the
                        // session releases the linear solver, the matrix,
                        // the solver memory, the vector and the context
                        // exactly once.
                        const auto rootIndex = static_cast<std::size_t>(
                            root - rootsFound.begin());
                        const auto group = nativeEventRoots_[rootIndex].first;
                        // A conjunction rises only when every surface holds.
                        // At this root, the selected surface is exactly zero;
                        // its positive direction makes it conceptually true.
                        std::vector<double> derivatives(nSpecies_);
                        derivs(t, state.data(), derivatives.data());
                        bool conjunctionHolds = true;
                        const auto* risingConjunct = nativeEventRoots_[rootIndex].second;
                        for (const auto* conjunct : triggerConjuncts(
                                 nativeEventGroups_[group].trigger)) {
                            // CVODE reported this conjunct's root with an
                            // increasing direction, so it is rising here even
                            // where its slope has no analytic form (a user
                            // function or delay() side has no derivative in
                            // eventSideDerivative).
                            if (conjunct == risingConjunct) continue;
                            if (discreteEventConjuncts_.count(conjunct)) {
                                // Piecewise constant: it holds or it does not;
                                // a zero slope says nothing about tangency.
                                if (!triggerHolds(*conjunct, t, state.data())) {
                                    conjunctionHolds = false;
                                    break;
                                }
                                continue;
                            }
                            const double value = eventRootValue(*conjunct, t, state.data());
                            const double tolerance = 1e-9 * (1.0 + std::abs(value));
                            if (value < -tolerance ||
                                (std::abs(value) <= tolerance &&
                                 eventRootDerivative(*conjunct, t, state.data(),
                                                     derivatives) <= 0.0)) {
                                conjunctionHolds = false;
                                break;
                            }
                        }
                        if (conjunctionHolds) queueTriggeredGroup(group, t, state);
                        // Another group may have crossed in the same step:
                        // the solver reports one crossing per step, so the
                        // other groups are compared against the value their
                        // root function had at the last instant the events
                        // were processed.
                        for (std::size_t other = 0; other < nativeEventGroups_.size(); ++other) {
                            if (other == group) continue;
                            const double value = eventRootValue(
                                nativeEventGroups_[other].trigger, t, state.data());
                            const double previous = lastRootValues_[other];
                            const double tolerance =
                                1e-9 * (1.0 + std::abs(previous));
                            bool crossed = false;
                            if (value > tolerance) {
                                crossed = previous <= 0.0;
                            } else if (value < -tolerance) {
                                crossed = false;
                            } else {
                                // The group is at its root, where the sign of
                                // the root function is the interpolation
                                // error.  Its rate of change decides the
                                // direction of the crossing.
                                std::vector<double> derivatives(nSpecies_);
                                derivs(t, state.data(), derivatives.data());
                                crossed = eventRootDerivative(
                                    nativeEventGroups_[other].trigger, t, state.data(),
                                    derivatives) > 0.0;
                            }
                            if (crossed) queueTriggeredGroup(other, t, state);
                        }
                        for (std::size_t other = 0; other < nativeEventGroups_.size(); ++other) {
                            lastRootValues_[other] = eventRootValue(
                                nativeEventGroups_[other].trigger, t, state.data());
                        }
                        // The trigger just became true, so the events that
                        // execute at this instant run now.  A delayed event
                        // waits in the queue until its delay has elapsed.
                        if (applyDueEvents(t, state)) {
                            for (std::size_t i = 0; i < nSpecies_; ++i) NV_Ith_S(y, i) = state[i] / cvodeStateScale_[i];
                            recordHistoryJump(t, state);
                            if (CVodeReInit(cvode_mem, t, y) != CV_SUCCESS) {
                                throw std::runtime_error("bng3_events CVodeReInit failed");
                            }
                        }
                    }
                    if (t >= tOut) break;
                    continue;
                }
                if (flag == CV_SUCCESS || flag == CV_TSTOP_RETURN) {
                    // Execute the queued events whose delay has elapsed before
                    // the trajectory continues.
                    std::vector<double> dueState(nSpecies_);
                    for (std::size_t i = 0; i < nSpecies_; ++i) {
                        dueState[i] = NV_Ith_S(y, i) * cvodeStateScale_[i];
                    }
                    recordHistoryPoint(t, dueState);
                    if (applyDueEvents(t, dueState)) {
                        for (std::size_t i = 0; i < nSpecies_; ++i) {
                            NV_Ith_S(y, i) = dueState[i] / cvodeStateScale_[i];
                        }
                        recordHistoryJump(t, dueState);
                        if (CVodeReInit(cvode_mem, t, y) != CV_SUCCESS) {
                            // The session releases the SUNDIALS handles.
                            throw std::runtime_error("bng3_events CVodeReInit failed");
                        }
                        continue;
                    }
                    if (t < target - 1e-12) continue;
                    if (target < tOut - 1e-12) {
                        // A method-of-steps kink (including a sum-generated
                        // breakpoint) becomes a source discontinuity for each
                        // other delay in the model.
                        if (activeSimulationSession_ && recordsHistory()) {
                            auto& discontinuities =
                                activeSimulationSession_->discontinuities;
                            if (discontinuities.empty() ||
                                std::abs(discontinuities.back() - t) > 1e-12) {
                                discontinuities.push_back(t);
                            }
                        }
                        continue;
                    }
                    break;
                } else if (flag == CV_TOO_MUCH_WORK) {
                    // Auto-increase max steps (matches BNG2 behavior)
                    // Keep the retry bounded.  A singular or ill-conditioned
                    // model must become a diagnostic, not an unbounded loop
                    // that makes a per-model validation job time out.
                    constexpr long int maxInternalSteps = 10000;
                    if (maxSteps >= maxInternalSteps) {
                        throw std::runtime_error(
                            "CVODE failed with flag " + std::to_string(flag) +
                            " after reaching the internal step budget");
                    }
                    maxSteps *= 2;
                    if (maxSteps > maxInternalSteps) maxSteps = maxInternalSteps;
                    CVodeSetMaxNumSteps(cvode_mem, maxSteps);
                    continue;
                } else {
                    throw std::runtime_error("CVODE failed with flag " + std::to_string(flag));
                }
            }
            t = tOut;
        }

        // Save current state
        result.timePoints.push_back(tOut);
        std::vector<double> conc(nSpecies_);
        for (std::size_t i = 0; i < nSpecies_; ++i) {
            conc[i] = NV_Ith_S(y, i) * cvodeStateScale_[i];
        }
        result.concentrations.push_back(conc);

        // Check product concentration scale (warn if exceeded)
        if (opts.checkProductScale > 0.0 && step > 0) {
            for (std::size_t i = 0; i < nSpecies_; ++i) {
                if (conc[i] > opts.checkProductScale) {
                    std::cerr << "[bng_cpp] WARNING: species " << (i + 1)
                              << " concentration (" << conc[i]
                              << ") exceeds check_product_scale threshold ("
                              << opts.checkProductScale << ") at t=" << tOut << "\n";
                    break;
                }
            }
        }

        if (step > 0 && steadyStateReached(opts, tOut, conc)) {
            break;
        }
        if (stopIfExpr.has_value()) {
            // CVODE integrates a scaled vector. At the initial point, use the
            // original model state for stop_if so a scale/unscale round trip
            // cannot change a threshold comparison by one ULP.
            const auto& stopState = tOut == opts.tStart ? initialState : conc;
            if (stopConditionMet(*stopIfExpr, tOut, stopState)) {
                break;
            }
        }
    }

    // Compute observables for each time point
    result.observables.resize(result.timePoints.size());
    result.functions.resize(result.timePoints.size());
    for (std::size_t step = 0; step < result.timePoints.size(); ++step) {
        updateGroups(result.concentrations[step].data(), result.observables[step]);
        updateFunctions(result.observables[step], result.timePoints[step], result.functions[step]);
    }

    // Optional solver profile for bench/ode_large_bench.py: one stderr line
    // with CVODE's own counters (steps, RHS evals, Jacobian evals, linear
    // work). Off unless BNG3_CVODE_STATS is set; the default path only pays
    // one getenv per integration.
    if (std::getenv("BNG3_CVODE_STATS") != nullptr) {
        long int nsteps = 0, nfevals = 0, njevals = 0, nsetups = 0;
        long int netfails = 0, nni = 0, nnf = 0, nliters = 0, nlnfails = 0;
        long int nfeDQ = 0;
        CVodeGetNumSteps(cvode_mem, &nsteps);
        CVodeGetNumRhsEvals(cvode_mem, &nfevals);
        if (!useAdamsFallback) {
            CVodeGetNumJacEvals(cvode_mem, &njevals);
            CVodeGetNumLinSolvSetups(cvode_mem, &nsetups);
            CVodeGetNumLinIters(cvode_mem, &nliters);
            CVodeGetNumLinConvFails(cvode_mem, &nlnfails);
        }
        nfeDQ = 0;  // Not available in SUNDIALS 7.6.0
        CVodeGetNumErrTestFails(cvode_mem, &netfails);
        CVodeGetNumNonlinSolvIters(cvode_mem, &nni);
        CVodeGetNumNonlinSolvConvFails(cvode_mem, &nnf);
        std::cerr << "BNG3_CVODE_STATS {\"lmm\": \""
                  << (useAdamsFallback ? "Adams" : "BDF")
                  << "\", \"steps\": " << nsteps
                  << ", \"rhs_evals\": " << nfevals
                  << ", \"jac_evals\": " << njevals
                  << ", \"jac_rhs_evals\": " << nfeDQ
                  << ", \"lin_setups\": " << nsetups
                  << ", \"err_test_fails\": " << netfails
                  << ", \"nonlin_iters\": " << nni
                  << ", \"nonlin_conv_fails\": " << nnf
                  << ", \"lin_iters\": " << nliters
                  << ", \"lin_conv_fails\": " << nlnfails
                  << ", \"n_species\": " << nSpecies_ << "}\n";
    }

    // Cleanup (v7: also free linear solver, matrix, and context) happens
    // when ``session`` goes out of scope, after the result is returned.
    return result;
}

OdeResult OdeIntegrator::integrateIda(const OdeOptions& opts) {
    if (hasPositiveExpressionDelay_ || !historyDelays_.empty()) {
        throw std::runtime_error(
            "DAE integration with delayed expressions is not supported");
    }
    auto times = outputTimes(opts);
    const auto stopIfExpr = parseStopIf(opts);
    pendingEvents_.clear();
    if (opts.continueSimulation && activeSimulationSession_) {
        for (const auto& pending : activeSimulationSession_->pendingNativeEvents) {
            pendingEvents_.push_back({pending.event, pending.executionTime,
                                      pending.values});
        }
        triggerRoseAt_ = activeSimulationSession_->eventTriggerRoseAt;
    }
    if (!opts.continueSimulation || triggerRoseAt_.size() != nativeEvents_.size()) {
        triggerRoseAt_.assign(nativeEvents_.size(),
                              -std::numeric_limits<double>::infinity());
    }

    std::vector<double> initialState(nSpecies_);
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        initialState[i] = activeSimulationSession_ &&
                activeSimulationSession_->state.size() == nSpecies_
            ? activeSimulationSession_->state[i]
            : network_.species.get(i).getAmount();
    }
    correctAlgebraicState(initialState, opts.tStart,
        std::max(opts.atol, 32.0 * std::numeric_limits<double>::epsilon()));
    lastRootValues_.clear();
    for (const auto& group : nativeEventGroups_) {
        lastRootValues_.push_back(
            eventRootValue(group.trigger, opts.tStart, initialState.data()));
    }
    for (std::size_t index = 0;
         !opts.continueSimulation && index < nativeEvents_.size(); ++index) {
        const auto& event = nativeEvents_[index];
        if (isStrictTrigger(event.trigger)) {
            const double rootValue = eventRootValue(
                event.trigger, opts.tStart, initialState.data());
            if (std::abs(rootValue) <= 1e-14) {
                // IDA retains the existing near-root refusal unless the
                // strict surface is exactly zero and its right-limit is
                // established by a positive derivative.
                std::vector<double> initialRates(nSpecies_);
                derivs(opts.tStart, initialState.data(), initialRates.data());
                const auto surface = triggerSurface(
                    event.trigger, opts.tStart, initialState.data(), initialRates);
                if (surface.difference == 0.0 && surface.derivative > 0.0) {
                    PendingEvent pending;
                    pending.event = index;
                    pending.executionTime = opts.tStart +
                        eventDelay(event, opts.tStart, initialState.data());
                    if (event.useValuesFromTriggerTime) {
                        pending.values = eventValues(
                            event, opts.tStart, initialState.data());
                    }
                    triggerRoseAt_[index] = opts.tStart;
                    pendingEvents_.push_back(std::move(pending));
                } else if (surface.difference == 0.0 &&
                           surface.derivative == 0.0) {
                    throw std::runtime_error(
                        std::string(ast::kUnsupportedEventExecutionMessage) +
                        ": strict trigger direction is unresolved at the initial time");
                } else if (surface.difference != 0.0) {
                    throw std::runtime_error(
                        std::string(ast::kUnsupportedEventExecutionMessage) +
                        ": strict trigger equals its threshold at the initial time");
                }
            }
        }
        if (!event.initialValue &&
            triggerHolds(event.trigger, opts.tStart, initialState.data())) {
            PendingEvent pending;
            pending.event = index;
            pending.executionTime =
                opts.tStart + eventDelay(event, opts.tStart, initialState.data());
            if (event.useValuesFromTriggerTime) {
                pending.values = eventValues(event, opts.tStart, initialState.data());
            }
            triggerRoseAt_[index] = opts.tStart;
            pendingEvents_.push_back(std::move(pending));
        }
    }
    if (!opts.continueSimulation && applyDueEvents(opts.tStart, initialState)) {
        correctAlgebraicState(initialState, opts.tStart,
            std::max(opts.atol, 32.0 * std::numeric_limits<double>::epsilon()));
        for (std::size_t group = 0; group < nativeEventGroups_.size(); ++group) {
            lastRootValues_[group] = eventRootValue(
                nativeEventGroups_[group].trigger, opts.tStart, initialState.data());
        }
    }
    std::vector<double> initialRhs(nSpecies_);
    derivs(opts.tStart, initialState.data(), initialRhs.data());
    const double timeScale = std::max(std::abs(opts.tEnd - opts.tStart), 1.0);
    cvodeStateScale_.resize(nSpecies_);

    IdaSession session;
    if (SUNContext_Create(SUN_COMM_NULL, &session.sunctx) != 0) {
        throw std::runtime_error("IDA DAE solver could not create SUNDIALS context");
    }
    const auto count = static_cast<sunindextype>(nSpecies_);
    session.y = N_VNew_Serial(count, session.sunctx);
    session.ydot = N_VNew_Serial(count, session.sunctx);
    session.id = N_VNew_Serial(count, session.sunctx);
    session.absTol = N_VNew_Serial(count, session.sunctx);
    if (!session.y || !session.ydot || !session.id || !session.absTol) {
        throw std::runtime_error("IDA DAE solver could not allocate state vectors");
    }
    std::vector<bool> isAlgebraic(nSpecies_, false);
    for (const auto index : algebraicSpeciesIndices_) isAlgebraic[index] = true;
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        double scale = std::abs(initialState[i]);
        if (std::isfinite(initialRhs[i])) {
            scale = std::max(scale, std::abs(initialRhs[i]) * timeScale);
        }
        if (!std::isfinite(scale) || scale < 1e-30) scale = 1.0;
        cvodeStateScale_[i] = scale;
        NV_Ith_S(session.y, i) = initialState[i] / scale;
        NV_Ith_S(session.ydot, i) = initialRhs[i] / scale;
        NV_Ith_S(session.id, i) = isAlgebraic[i] ? 0.0 : 1.0;
        NV_Ith_S(session.absTol, i) = opts.atol / scale;
    }

    session.ida_mem = IDACreate(session.sunctx);
    if (!session.ida_mem || IDAInit(session.ida_mem, idaResidualWrapper,
                                    opts.tStart, session.y, session.ydot) != IDA_SUCCESS) {
        throw std::runtime_error("IDA DAE solver initialization failed");
    }
    IDASetUserData(session.ida_mem, this);
    if (IDASVtolerances(session.ida_mem, opts.rtol, session.absTol) != IDA_SUCCESS ||
        IDASetId(session.ida_mem, session.id) != IDA_SUCCESS ||
        IDASetMaxNumSteps(session.ida_mem, 10000) != IDA_SUCCESS) {
        throw std::runtime_error("IDA DAE solver configuration failed");
    }
    if (opts.maxStep > 0.0 &&
        IDASetMaxStep(session.ida_mem, opts.maxStep) != IDA_SUCCESS) {
        throw std::runtime_error("IDA DAE solver maximum step setup failed");
    }
    if (!opts.sparse && nSpecies_ < 500) {
        session.A = SUNDenseMatrix(count, count, session.sunctx);
        session.LS = session.A
            ? SUNLinSol_Dense(session.y, session.A, session.sunctx)
            : nullptr;
    } else {
        session.LS = SUNLinSol_SPGMR(session.y, SUN_PREC_NONE, 0, session.sunctx);
    }
    if (!session.LS ||
        IDASetLinearSolver(session.ida_mem, session.LS, session.A) != IDA_SUCCESS) {
        throw std::runtime_error("IDA DAE solver linear system setup failed");
    }
    if (!nativeEventRoots_.empty()) {
        const int rootCount = static_cast<int>(nativeEventRoots_.size());
        std::vector<int> rootDirections(static_cast<std::size_t>(rootCount), 1);
        if (IDARootInit(session.ida_mem, rootCount, idaEventRootWrapper) != IDA_SUCCESS ||
            IDASetRootDirection(session.ida_mem, rootDirections.data()) != IDA_SUCCESS) {
            throw std::runtime_error("DAE event root initialization failed");
        }
    }
    double icTarget = opts.tStart + std::max(timeScale * 1e-3, 1e-8);
    if (IDACalcIC(session.ida_mem, IDA_YA_YDP_INIT, icTarget) != IDA_SUCCESS ||
        IDAGetConsistentIC(session.ida_mem, session.y, session.ydot) != IDA_SUCCESS) {
        throw std::runtime_error(
            "DAE consistent initial conditions failed; algebraic constraint may be singular or inconsistent");
    }

    OdeResult result;
    result.timePoints.reserve(times.size());
    result.concentrations.reserve(times.size());
    double time = opts.tStart;
    for (std::size_t step = 0; step < times.size(); ++step) {
        const double outputTime = times[step];
        if (outputTime > time) {
            while (time < outputTime - 1e-12) {
                double target = outputTime;
                for (const auto& pending : pendingEvents_) {
                    target = std::min(target, pending.executionTime);
                }
                if (target <= time + 1e-12) {
                    std::vector<double> dueState(nSpecies_);
                    for (std::size_t i = 0; i < nSpecies_; ++i) {
                        dueState[i] = NV_Ith_S(session.y, i) * cvodeStateScale_[i];
                    }
                    if (!applyDueEvents(time, dueState)) break;
                    correctAlgebraicState(dueState, time,
                        std::max(opts.atol,
                            32.0 * std::numeric_limits<double>::epsilon()));
                    for (std::size_t i = 0; i < nSpecies_; ++i) {
                        NV_Ith_S(session.y, i) = dueState[i] / cvodeStateScale_[i];
                    }
                    if (IDAReInit(session.ida_mem, time, session.y,
                                  session.ydot) != IDA_SUCCESS ||
                        IDASetId(session.ida_mem, session.id) != IDA_SUCCESS) {
                        throw std::runtime_error("DAE event reinitialization failed");
                    }
                    const double icTarget = time + std::max(timeScale * 1e-3, 1e-8);
                    if (IDACalcIC(session.ida_mem, IDA_YA_YDP_INIT, icTarget) !=
                            IDA_SUCCESS ||
                        IDAGetConsistentIC(session.ida_mem, session.y,
                                           session.ydot) != IDA_SUCCESS) {
                        throw std::runtime_error(
                            "DAE event reset left inconsistent algebraic state");
                    }
                    recordHistoryJump(time, dueState);
                    continue;
                }
                if (IDASetStopTime(session.ida_mem, target) != IDA_SUCCESS) {
                    throw std::runtime_error("IDA DAE stop time setup failed");
                }
                const int flag = IDASolve(session.ida_mem, target, &time,
                                          session.y, session.ydot, IDA_NORMAL);
                if (flag == IDA_ROOT_RETURN) {
                    std::vector<int> rootsFound(nativeEventRoots_.size());
                    if (IDAGetRootInfo(session.ida_mem, rootsFound.data()) != IDA_SUCCESS) {
                        throw std::runtime_error("DAE event root information failed");
                    }
                    std::vector<double> state(nSpecies_);
                    for (std::size_t i = 0; i < nSpecies_; ++i) {
                        state[i] = NV_Ith_S(session.y, i) * cvodeStateScale_[i];
                    }
                    recordHistoryPoint(time, state);
                    std::set<std::size_t> risingGroups;
                    std::vector<double> derivatives(nSpecies_);
                    derivs(time, state.data(), derivatives.data());
                    for (std::size_t root = 0; root < rootsFound.size(); ++root) {
                        if (rootsFound[root] <= 0) continue;
                        const auto [group, risingConjunct] = nativeEventRoots_[root];
                        bool conjunctionHolds = true;
                        for (const auto* conjunct : triggerConjuncts(
                                 nativeEventGroups_[group].trigger)) {
                            if (conjunct == risingConjunct) continue;
                            if (discreteEventConjuncts_.count(conjunct)) {
                                if (!triggerHolds(*conjunct, time, state.data())) {
                                    conjunctionHolds = false;
                                    break;
                                }
                                continue;
                            }
                            const double value = eventRootValue(
                                *conjunct, time, state.data());
                            const double tolerance = 1e-9 * (1.0 + std::abs(value));
                            if (value < -tolerance ||
                                (std::abs(value) <= tolerance &&
                                 eventRootDerivative(*conjunct, time, state.data(),
                                                     derivatives) <= 0.0)) {
                                conjunctionHolds = false;
                                break;
                            }
                        }
                        if (conjunctionHolds) {
                            risingGroups.insert(group);
                            queueTriggeredGroup(group, time, state);
                        }
                    }
                    for (std::size_t group = 0;
                         group < nativeEventGroups_.size(); ++group) {
                        if (risingGroups.count(group)) continue;
                        const double value = eventRootValue(
                            nativeEventGroups_[group].trigger, time, state.data());
                        const double previous = lastRootValues_[group];
                        const double tolerance = 1e-9 * (1.0 + std::abs(previous));
                        bool crossed = value > tolerance && previous <= 0.0;
                        if (std::abs(value) <= tolerance) {
                            crossed = eventRootDerivative(
                                nativeEventGroups_[group].trigger, time, state.data(),
                                derivatives) > 0.0;
                        }
                        if (crossed) queueTriggeredGroup(group, time, state);
                    }
                    for (std::size_t group = 0;
                         group < nativeEventGroups_.size(); ++group) {
                        lastRootValues_[group] = eventRootValue(
                            nativeEventGroups_[group].trigger, time, state.data());
                    }
                    if (applyDueEvents(time, state)) {
                        correctAlgebraicState(state, time,
                            std::max(opts.atol,
                                32.0 * std::numeric_limits<double>::epsilon()));
                        for (std::size_t i = 0; i < nSpecies_; ++i) {
                            NV_Ith_S(session.y, i) = state[i] / cvodeStateScale_[i];
                        }
                        recordHistoryJump(time, state);
                        if (IDAReInit(session.ida_mem, time, session.y,
                                      session.ydot) != IDA_SUCCESS ||
                            IDASetId(session.ida_mem, session.id) != IDA_SUCCESS) {
                            throw std::runtime_error("DAE event reinitialization failed");
                        }
                        const double icTarget = time +
                            std::max(timeScale * 1e-3, 1e-8);
                        const int icFlag = IDACalcIC(
                            session.ida_mem, IDA_YA_YDP_INIT, icTarget);
                        const int getIcFlag = icFlag == IDA_SUCCESS
                            ? IDAGetConsistentIC(session.ida_mem, session.y,
                                                 session.ydot)
                            : IDA_SUCCESS;
                        if (icFlag != IDA_SUCCESS || getIcFlag != IDA_SUCCESS) {
                            std::ostringstream detail;
                            detail << "DAE event reset left inconsistent algebraic state"
                                   << " (IDA flags " << icFlag << ", " << getIcFlag
                                   << ", time " << time << ", state";
                            for (std::size_t i = 0; i < state.size(); ++i) {
                                detail << " " << state[i];
                            }
                            detail << ")";
                            throw std::runtime_error(detail.str());
                        }
                    }
                    continue;
                }
                if (flag != IDA_SUCCESS && flag != IDA_TSTOP_RETURN) {
                    throw std::runtime_error("IDA DAE integration failed with flag " +
                                             std::to_string(flag));
                }
                std::vector<double> dueState(nSpecies_);
                for (std::size_t i = 0; i < nSpecies_; ++i) {
                    dueState[i] = NV_Ith_S(session.y, i) * cvodeStateScale_[i];
                }
                if (applyDueEvents(time, dueState)) {
                    correctAlgebraicState(dueState, time,
                        std::max(opts.atol,
                            32.0 * std::numeric_limits<double>::epsilon()));
                    for (std::size_t i = 0; i < nSpecies_; ++i) {
                        NV_Ith_S(session.y, i) = dueState[i] / cvodeStateScale_[i];
                    }
                    if (IDAReInit(session.ida_mem, time, session.y,
                                  session.ydot) != IDA_SUCCESS ||
                        IDASetId(session.ida_mem, session.id) != IDA_SUCCESS) {
                        throw std::runtime_error("DAE event reinitialization failed");
                    }
                    const double icTarget = time + std::max(timeScale * 1e-3, 1e-8);
                    if (IDACalcIC(session.ida_mem, IDA_YA_YDP_INIT, icTarget) !=
                            IDA_SUCCESS ||
                        IDAGetConsistentIC(session.ida_mem, session.y,
                                           session.ydot) != IDA_SUCCESS) {
                        throw std::runtime_error(
                            "DAE event reset left inconsistent algebraic state");
                    }
                    continue;
                }
            }
        }
        result.timePoints.push_back(outputTime);
        std::vector<double> state(nSpecies_);
        for (std::size_t i = 0; i < nSpecies_; ++i) {
            state[i] = NV_Ith_S(session.y, i) * cvodeStateScale_[i];
        }
        result.concentrations.push_back(state);
        if (stopIfExpr && stopConditionMet(*stopIfExpr, outputTime, state)) break;
        if (step > 0 && steadyStateReached(opts, outputTime, state)) break;
    }
    result.observables.resize(result.timePoints.size());
    result.functions.resize(result.timePoints.size());
    for (std::size_t step = 0; step < result.timePoints.size(); ++step) {
        updateGroups(result.concentrations[step].data(), result.observables[step]);
        updateFunctions(result.observables[step], result.timePoints[step], result.functions[step]);
    }
    return result;
}

double OdeIntegrator::computePropensity(const CompiledReaction& rxn,
                                        const std::vector<double>& y,
                                        double rateCoefficient) const {
    // The stochastic propensity uses the discrete reactant count: a rule with
    // two identical reactants has `n * (n - 1)` ways to react, not `n * n`,
    // because the same molecule cannot react with itself.  This is canonical
    // BioNetGen's convention: the `discrete` branch of
    // `bng2/Network3/src/network.cpp`'s `rxn_rate` multiplies a repeated
    // reactant by `X - n`, and NFsim reaches the same count by rejecting the
    // degenerate self-pair as a null event.
    //
    // The stat_factor is already baked into rateConstant.
    double propensity = rateCoefficient;

    // Atomizer absolute fluxes already contain reactant dependence. Authored
    // BNGL TotalRate laws follow BNG2's finite-network convention: omit the
    // symmetry factor but still multiply by the reactant counts.
    //
    // The availability check stops an absolute flux from consuming molecules
    // that are not there. A constant ($ or SBML boundaryCondition) reactant is
    // never consumed, so it is not checked: an SBML zero-order source such as
    // `$Source() -> X()` with Source at 0 fires at its full rate, matching the
    // deterministic reading.
    if (rxn.isAbsoluteFlux) {
        for (std::size_t i = 0; i < rxn.reactantIndices.size(); ++i) {
            const auto index = rxn.reactantIndices[i];
            if (index < fixedSpecies_.size() && fixedSpecies_[index]) continue;
            const auto required = static_cast<double>(
                std::count(rxn.reactantIndices.begin(),
                           rxn.reactantIndices.begin() + i, index) + 1);
            if (index >= y.size() || y[index] < required) return 0.0;
        }
        return propensity;
    }

    // Group identical reactants and apply the discrete formula.  BNG2 assumes
    // reactant indices are sorted, so identical species are adjacent.
    for (size_t i = 0; i < rxn.reactantIndices.size(); ++i) {
        std::size_t idx = rxn.reactantIndices[i];
        const double n_offset =
            static_cast<double>(identicalReactantOffset(rxn.reactantIndices, i));

        // Discrete formula: multiply by (population - offset)
        double population = y[idx];
        propensity *= std::max(0.0, population - n_offset);
    }

    return propensity;
}

namespace {

// Per-thread scratch for integrateSSA.
//
// The batch pool drives one trajectory per call against a single shared
// integrator, so the state vector, the propensity table, its prefix sums and
// the species->reaction dependency graph are rebuilt once per trajectory --
// a million times over a pool run -- while depending only on the compiled
// network.  Holding them here makes that rebuild a resize instead of a
// fresh allocation.  Every field is written in full before it is read, and
// integrateSSA never recurses, so nothing leaks between trajectories or
// between threads.
struct SsaScratch {
    std::vector<double> state;
    std::vector<double> propensities;
    std::vector<double> prefixSums;
    std::vector<std::size_t> depOffset;
    std::vector<std::size_t> depReactions;
    // Observable scratch for state-dependent rate laws.  It lives here, not on
    // the OdeIntegrator, because the batched CPU pool shares one integrator
    // across its worker threads: a member scratch would be written by every
    // worker at once, and a rate expression that reads an observable would
    // then resolve against another trajectory's state.
    std::vector<double> groupValues;
};

} // namespace

OdeResult OdeIntegrator::integrateSSA(const OdeOptions& opts) {
    const auto readsClock = [&](const auto& self, const ast::Expression& expression) -> bool {
        if ((expression.kind() == ast::ExpressionKind::Identifier ||
             expression.kind() == ast::ExpressionKind::Function) &&
            (expression.name() == "time" || expression.name() == "t" ||
             model_.getParameters().isTimeDependent(expression.name()))) {
            return true;
        }
        return std::any_of(expression.args().begin(), expression.args().end(),
                           [&](const auto& child) { return self(self, child); });
    };
    for (const auto& event : nativeEvents_) {
        if (readsClock(readsClock, functionEvaluator_.expandFunctions(event.trigger))) {
            throw std::runtime_error(
                "SSA does not support time-dependent native event triggers");
        }
    }
    // Direct Gillespie algorithm (matches BNG2 implementation)
    for (const auto& rxn : compiledRxns_) {
        if (rxn.isTimeDependent) {
            throw std::runtime_error(
                "SSA does not support explicitly time-dependent rate laws");
        }
    }
    auto times = outputTimes(opts);
    const auto stopIfExpr = parseStopIf(opts);
    const bool explicitTimes = !opts.sampleTimes.empty();
    pendingEvents_.clear();
    auto* eventSession = activeSimulationSession_;
    if (opts.continueSimulation && eventSession) {
        for (const auto& pending : eventSession->pendingNativeEvents) {
            pendingEvents_.push_back({pending.event, pending.executionTime,
                                      pending.values});
        }
        triggerRoseAt_ = eventSession->eventTriggerRoseAt;
    }
    if (!opts.continueSimulation || triggerRoseAt_.size() != nativeEvents_.size()) {
        triggerRoseAt_.assign(nativeEvents_.size(),
                              -std::numeric_limits<double>::infinity());
    }
    // Constructing with the value seeds the engine once.  Declaring the engine
    // and then calling seed() runs the 312-word state initialisation twice per
    // trajectory and throws the first result away; a pool run pays that on
    // every trajectory for a state the very next line overwrites.  The seeded
    // state is the same either way, so the draw sequence is unchanged.
    const std::mt19937_64::result_type seedValue =
        opts.seed > 0
            ? static_cast<std::mt19937_64::result_type>(opts.seed)
            : static_cast<std::mt19937_64::result_type>(std::random_device{}());
    auto* session = activeSimulationSession_;
    std::mt19937_64 localRng(seedValue);
    if (session && !session->rngInitialized) {
        session->rng.seed(seedValue);
        session->rngInitialized = true;
    }
    auto& rng = session ? session->rng : localRng;
    std::uniform_real_distribution<double> uniform(0.0, 1.0);

    // Initialize state (round to nearest integer)
    static thread_local SsaScratch scratch;
    auto& y = scratch.state;
    y.resize(nSpecies_);
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        const double state = session && session->state.size() == nSpecies_
            ? session->state[i] : network_.species.get(i).getAmount();
        y[i] = std::round(state);
    }
    if (!opts.continueSimulation) {
        for (std::size_t index = 0; index < nativeEvents_.size(); ++index) {
            const auto& event = nativeEvents_[index];
            if (!event.initialValue &&
                triggerHolds(event.trigger, opts.tStart, y.data())) {
                PendingEvent pending;
                pending.event = index;
                pending.executionTime = opts.tStart + eventDelay(event, opts.tStart, y.data());
                if (event.useValuesFromTriggerTime) {
                    pending.values = eventValues(event, opts.tStart, y.data());
                }
                triggerRoseAt_[index] = opts.tStart;
                pendingEvents_.push_back(std::move(pending));
            }
        }
        applyDueEvents(opts.tStart, y);
    }
    const bool stopAtInitial =
        stopIfExpr.has_value() && stopConditionMet(*stopIfExpr, opts.tStart, y);
    if (stopAtInitial && times.front() != opts.tStart) {
        times.insert(times.begin(), opts.tStart);
    }

    OdeResult result;
    result.timePoints.reserve(times.size() + 1);
    result.concentrations.reserve(times.size() + 1);

    double t = opts.tStart;
    std::size_t nextOutputTime = 0;
    std::size_t ssaStepCount = 0;  // track internal SSA steps for output_step_interval
    bool stoppedEarly = false;

    const auto appendScheduledBefore = [&](double until) {
        while (nextOutputTime < times.size() &&
               times[nextOutputTime] < until - 1e-12) {
            result.timePoints.push_back(times[nextOutputTime]);
            result.concentrations.push_back(y);
            ++nextOutputTime;
        }
    };

    const auto appendScheduledThrough = [&](double until) {
        while (nextOutputTime < times.size() &&
               times[nextOutputTime] <= until + 1e-12) {
            result.timePoints.push_back(times[nextOutputTime]);
            result.concentrations.push_back(y);
            ++nextOutputTime;
        }
    };

    const auto appendEventState = [&]() {
        if (result.timePoints.empty() ||
            std::abs(result.timePoints.back() - t) > 1e-12) {
            result.timePoints.push_back(t);
            result.concentrations.push_back(y);
        } else {
            // An event may land exactly on an explicit output time.  The
            // sample at that instant represents the post-event state.
            result.concentrations.back() = y;
        }
    };

    // Propensity table and the prefix sums the selector searches.  Both live
    // in per-thread scratch: a batch pool drives one trajectory per call
    // against a single shared integrator, so these are rebuilt once per
    // trajectory -- a million times over a pool run -- while depending only
    // on the compiled network.  Each is written in full before it is read.
    const std::size_t nRxns = compiledRxns_.size();
    auto& propensities = scratch.propensities;
    auto& prefixSums = scratch.prefixSums;
    propensities.resize(nRxns);
    prefixSums.resize(nRxns);
    // Functional-rate coefficients are re-evaluated from the current state,
    // so they stay local to this trajectory; only the value tables are reused.
    std::vector<double> rateCoefficients;
    if (hasFunctionalRates_) {
        rateCoefficients.resize(nRxns);
        for (std::size_t r = 0; r < nRxns; ++r) {
            rateCoefficients[r] = compiledRxns_[r].rateConstant;
        }
    }
    const auto rateCoefficientFor = [&](std::size_t r) {
        return compiledRxns_[r].isFunctional
                   ? rateCoefficients[r]
                   : compiledRxns_[r].rateConstant;
    };
    double totalPropensity = 0.0;

    // Reaction selection needs the first cumulative propensity that reaches
    // the target.  Storing each running total while summing costs exactly the
    // additions the total-propensity accumulation already performs, in the
    // same order, so totalPropensity keeps its original bits.  If every rate
    // constant is non-negative the prefix is non-decreasing and the first
    // crossing can be found by binary search; a negative or non-finite rate
    // constant falls back to a linear scan over the same prefix values, which
    // reproduces the original cumulative scan exactly for any sign pattern.
    bool monotonePrefix = true;

    auto recomputeAll = [&]() {
        if (hasFunctionalRates_) {
            evaluateFunctionalRateCoefficients(
                t, y.data(), rateCoefficients.data(), scratch.groupValues, true,
                /*discreteReactantCounts=*/true);
        }
        totalPropensity = 0.0;
        monotonePrefix = true;
        for (std::size_t r = 0; r < nRxns; ++r) {
            const double rateCoef = rateCoefficientFor(r);
            if (!(rateCoef >= 0.0)) {
                monotonePrefix = false;
            }
            propensities[r] = computePropensity(
                compiledRxns_[r], y, rateCoef);
            totalPropensity += propensities[r];
            prefixSums[r] = totalPropensity;
        }
    };

    recomputeAll();

    // Species -> reactions whose propensity reads that species.  A propensity
    // consults only reactantIndices (see computePropensity), so firing a
    // reaction can only change propensities of reactions sharing a species
    // with its reactants or products.  Every other stored propensity is
    // already exact, and is what recomputeAll would re-derive.
    //
    // The graph earns its two setup passes only when the reactions it skips
    // outnumber the reactions it refreshes.  On a small network most of the
    // table is affected anyway, while the O(nRxns) prefix rebuild that follows
    // every event is paid either way, so recomputeAll is cheaper both to set
    // up and to run.  The threshold is the point past which skipping the
    // unaffected reactions dominates: each one saved is a propensity
    // evaluation the per-event pass no longer does, against a graph that
    // costs two traversals of the whole reaction table per trajectory.
    constexpr std::size_t dependencyGraphThreshold = 64;
    const bool useDependencyGraph = nRxns > dependencyGraphThreshold;

    auto& depOffset = scratch.depOffset;
    auto& depReactions = scratch.depReactions;
    if (useDependencyGraph) {
        depOffset.assign(nSpecies_ + 1, 0);
        for (const auto& rxn : compiledRxns_) {
            for (const auto idx : rxn.reactantIndices) {
                // Reactant indices are network species indices, so they are in
                // [0, nSpecies_) — the same invariant the pre-existing ODE and
                // SSA code relies on when it reads y[idx].  depOffset is sized
                // nSpecies_ + 1 precisely so idx + 1 stays in range; assert the
                // invariant where the index first crosses this new write.
                // Beyond the assertion, this bound was audited empirically over
                // the repository's generated networks (perfOracle's audit, 2026-
                // 09-30): 2,711 generated .net files, 792,960 reaction lines,
                // max 1-based reactant index == nSpecies and zero references
                // outside [1, nSpecies] in every file, so idx+1 never exceeds
                // depOffset[nSpecies_].
                assert(idx < nSpecies_);
                ++depOffset[idx + 1];
            }
        }
        for (std::size_t i = 0; i < nSpecies_; ++i) {
            depOffset[i + 1] += depOffset[i];
        }
        depReactions.resize(depOffset[nSpecies_]);
        std::vector<std::size_t> cursor(depOffset.begin(),
                                        depOffset.end() - 1);
        for (std::size_t r = 0; r < nRxns; ++r) {
            for (const auto idx : compiledRxns_[r].reactantIndices) {
                depReactions[cursor[idx]++] = r;
            }
        }
    }

    auto refreshAffected = [&](std::size_t firedIndex) {
        const auto& fired = compiledRxns_[firedIndex];
        if (hasFunctionalRates_) {
            // An observable-backed function may read any species in the
            // model, so refresh every functional coefficient after a state
            // change. Constant-rate reactions retain dependency-indexed work.
            evaluateFunctionalRateCoefficients(
                t, y.data(), rateCoefficients.data(), scratch.groupValues, true,
                /*discreteReactantCounts=*/true);
            for (const auto r : functionalRxnIndices_) {
                propensities[r] = computePropensity(
                    compiledRxns_[r], y, rateCoefficients[r]);
            }
        }
        auto refreshSpecies = [&](std::size_t speciesIndex) {
            for (std::size_t p = depOffset[speciesIndex];
                 p < depOffset[speciesIndex + 1]; ++p) {
                const std::size_t r = depReactions[p];
                if (!compiledRxns_[r].isFunctional) {
                    propensities[r] = computePropensity(
                        compiledRxns_[r], y, rateCoefficientFor(r));
                }
            }
        };
        for (const auto idx : fired.reactantIndices) {
            refreshSpecies(idx);
        }
        for (const auto idx : fired.productIndices) {
            refreshSpecies(idx);
        }
        totalPropensity = 0.0;
        monotonePrefix = true;
        for (std::size_t r = 0; r < nRxns; ++r) {
            if (!(rateCoefficientFor(r) >= 0.0)) {
                monotonePrefix = false;
            }
            totalPropensity += propensities[r];
            prefixSums[r] = totalPropensity;
        }
    };

    // Record initial state
    if (opts.outputStepInterval == 0 || explicitTimes) {
        appendScheduledThrough(t);
    } else {
        result.timePoints.push_back(t);
        result.concentrations.push_back(y);
    }

    // Initial-state checks use the rounded molecule-count state and run before
    // any RNG draws. The initial row was scheduled above when explicit times
    // omitted t_start.
    stoppedEarly = stopAtInitial;

    // Main SSA loop
    while (t < opts.tEnd && !stoppedEarly) {
        // Record scheduled output points as events advance the trajectory.
        if (opts.outputStepInterval == 0 || explicitTimes) {
            appendScheduledThrough(t);
        }

        // Check if we've passed the end time
        if (opts.maxSimSteps > 0 && ssaStepCount >= opts.maxSimSteps) {
            stoppedEarly = true;
            break;
        }
        if (t >= opts.tEnd) {
            break;
        }
        double nextCompletion = std::numeric_limits<double>::infinity();
        if (session) {
            for (const auto& pending : session->pendingCompletions) {
                nextCompletion = std::min(nextCompletion, pending.time);
            }
        }
        for (const auto& pending : pendingEvents_) {
            nextCompletion = std::min(nextCompletion, pending.executionTime);
        }
        double nextReaction = std::numeric_limits<double>::infinity();
        if (totalPropensity > 0.0) {
            if (session) {
                if (!session->ssaHazardInitialized) {
                    double r1 = uniform(rng);
                    while (r1 == 0.0 || r1 == 1.0) r1 = uniform(rng);
                    session->ssaRemainingHazard = -std::log(r1);
                    session->ssaHazardInitialized = true;
                }
                nextReaction = t + session->ssaRemainingHazard / totalPropensity;
            } else {
                double r1 = uniform(rng);
                while (r1 == 0.0 || r1 == 1.0) r1 = uniform(rng);
                nextReaction = t - std::log(r1) / totalPropensity;
            }
        }

        if (nextCompletion <= nextReaction && nextCompletion <= opts.tEnd) {
            if (session && totalPropensity > 0.0) {
                session->ssaRemainingHazard = std::max(
                    0.0, session->ssaRemainingHazard -
                             totalPropensity * (nextCompletion - t));
            }
            if (opts.outputStepInterval == 0 || explicitTimes) {
                appendScheduledBefore(nextCompletion);
            }
            t = nextCompletion;
            std::vector<bool> heldBefore;
            if (!nativeEvents_.empty()) {
                heldBefore.reserve(nativeEvents_.size());
                for (const auto& event : nativeEvents_) {
                    heldBefore.push_back(
                        triggerHolds(event.trigger, t, y.data()));
                }
            }
            bool reactionCompletionApplied = false;
            std::vector<std::size_t> completed;
            if (session) {
                for (std::size_t i = 0;
                     i < session->pendingCompletions.size(); ++i) {
                    if (std::abs(session->pendingCompletions[i].time - t) <= 1e-12) {
                        completed.push_back(i);
                    }
                }
            }
            std::sort(completed.rbegin(), completed.rend());
            for (const auto index : completed) {
                const auto pending = session->pendingCompletions[index];
                const auto& reaction = compiledRxns_[pending.reaction];
                reactionCompletionApplied = true;
                if (reaction.nonConsuming) {
                    for (const auto idx : reaction.reactantIndices) {
                        if (!fixedSpecies_[idx]) y[idx] -= 1.0;
                    }
                }
                for (const auto idx : reaction.productIndices) {
                    if (!fixedSpecies_[idx]) y[idx] += 1.0;
                }
                session->pendingCompletions.erase(
                    session->pendingCompletions.begin() +
                    static_cast<std::ptrdiff_t>(index));
            }
            if (reactionCompletionApplied && !nativeEvents_.empty()) {
                retestTriggers(t, y, heldBefore);
            }
            const bool eventApplied = applyDueEvents(t, y);
            if (reactionCompletionApplied || eventApplied) {
                recomputeAll();
            }
            if (opts.outputStepInterval == 0 || explicitTimes) {
                appendScheduledThrough(t);
            } else if ((ssaStepCount % opts.outputStepInterval) == 0) {
                result.timePoints.push_back(t);
                result.concentrations.push_back(y);
            }
            if (stopIfExpr.has_value() && stopConditionMet(*stopIfExpr, t, y)) {
                stoppedEarly = true;
            }
            continue;
        }

        if (nextReaction > opts.tEnd) {
            if (session && totalPropensity > 0.0) {
                session->ssaRemainingHazard = std::max(
                    0.0, session->ssaRemainingHazard -
                             totalPropensity * (opts.tEnd - t));
            }
            t = opts.tEnd;
            break;
        }

        const double eventTime = nextReaction;
        if (opts.outputStepInterval == 0 || explicitTimes) {
            // Scheduled samples before the event see the pre-event state.
            appendScheduledBefore(eventTime);
        }
        t = eventTime;
        if (session) {
            session->ssaHazardInitialized = false;
            session->ssaRemainingHazard = 0.0;
        }

        // Select next reaction
        double r2 = uniform(rng);
        double target = r2 * totalPropensity;
        std::size_t selectedRxn = compiledRxns_.size();

        if (monotonePrefix) {
            // First index whose prefix sum reaches the target (binary search
            // over a non-decreasing sequence: same first crossing the
            // cumulative scan finds, including equal-value plateaus).
            std::size_t lo = 0;
            std::size_t hi = compiledRxns_.size();
            while (lo < hi) {
                const std::size_t mid = lo + (hi - lo) / 2;
                if (prefixSums[mid] >= target) {
                    hi = mid;
                } else {
                    lo = mid + 1;
                }
            }
            selectedRxn = lo;
        } else {
            for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
                if (prefixSums[r] >= target) {
                    selectedRxn = r;
                    break;
                }
            }
        }

        if (selectedRxn >= compiledRxns_.size()) {
            // Shouldn't happen unless roundoff error
            stoppedEarly = true;
            break;
        }

        // Fire the selected reaction
        //
        // A constant species carries the model's "this amount does not change"
        // marker (BNGL's ``$`` seed species; SBML's ``boundaryCondition``).
        // The deterministic reading honours it by zeroing the species'
        // derivative, and the partitioned simulators honour it by skipping the
        // species in their state update, so the direct method has to skip it
        // too: otherwise the same converted model means two different things
        // depending on which engine simulates it.  The propensity is
        // untouched - a constant species still contributes its amount to the
        // rate law it appears in - only the state update skips it.
        std::vector<bool> heldBefore;
        if (!nativeEvents_.empty()) {
            heldBefore.reserve(nativeEvents_.size());
            for (const auto& event : nativeEvents_) {
                heldBefore.push_back(triggerHolds(event.trigger, t, y.data()));
            }
        }
        const auto& rxn = compiledRxns_[selectedRxn];
        if (rxn.delay > 0.0) {
            if (!rxn.nonConsuming) {
                for (const auto idx : rxn.reactantIndices) {
                    if (fixedSpecies_[idx]) continue;
                    y[idx] -= 1.0;
                    if (y[idx] < 0.0) y[idx] = 0.0;
                }
            }
            session->pendingCompletions.push_back({
                t + rxn.delay, selectedRxn, session->nextCompletionOrder++});
        } else {
            for (const auto idx : rxn.reactantIndices) {
                if (fixedSpecies_[idx]) continue;
                y[idx] -= 1.0;
                if (y[idx] < 0.0) y[idx] = 0.0;
            }
            for (const auto idx : rxn.productIndices) {
                if (fixedSpecies_[idx]) continue;
                y[idx] += 1.0;
            }
        }

        if (!nativeEvents_.empty()) {
            retestTriggers(t, y, heldBefore);
        }
        const bool eventApplied = applyDueEvents(t, y);

        // Recompute propensities.  On a network with a dependency graph only
        // reactions that read a species whose amount this event changed can
        // differ from the previous step, and the total is rebuilt over all
        // reactions in the original order; on a small network the whole table
        // is re-derived instead.  Both are bit-identical to each other.
        if (eventApplied) {
            // Event assignments can write species unrelated to the reaction
            // that triggered them, so refresh the complete propensity table.
            recomputeAll();
        } else if (useDependencyGraph) {
            refreshAffected(selectedRxn);
        } else {
            recomputeAll();
        }

        if (opts.outputStepInterval == 0 || explicitTimes) {
            // Include an explicit sample that coincides with the event using
            // the post-event state.
            appendScheduledThrough(t);
        }

        // output_step_interval: record output every N internal SSA steps
        ++ssaStepCount;
        if (opts.outputStepInterval > 0 && !explicitTimes &&
            (ssaStepCount % opts.outputStepInterval) == 0) {
            result.timePoints.push_back(t);
            result.concentrations.push_back(y);
        }

        if (stopIfExpr.has_value() &&
            stopConditionMet(*stopIfExpr, t, y)) {
            stoppedEarly = true;
            break;
        }
    }

    if (opts.outputStepInterval > 0 && !explicitTimes) {
        // Record final state at the actual stopping time.
        appendEventState();
    } else {
        if (!stoppedEarly) {
            t = opts.tEnd;
        }
        appendScheduledThrough(t);
        if (stoppedEarly) {
            appendEventState();
        }
    }

    // Compute observables for each time point
    result.observables.resize(result.timePoints.size());
    for (std::size_t step = 0; step < result.timePoints.size(); ++step) {
        updateGroups(result.concentrations[step].data(), result.observables[step]);
    }
    result.eventCount = ssaStepCount;

    return result;
}

} // namespace bng::engine
