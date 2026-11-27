#include "BngsimAdapter.hpp"
#include "DelayedSemanticsGuard.hpp"
#include "FiniteBackend.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <limits>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#ifdef BNG3_HAS_BNGSIM_ADAPTER
#include <bngsim/model_builder.hpp>
#endif

#include "ast/EventSupport.hpp"
#include "ast/Model.hpp"
#include "ast/ModelFunctionEvaluator.hpp"
#include "compile/TotalRate.hpp"
#include "io/NetWriter.hpp"
#include "parser/antlr_compat.hpp"
#include "antlr4-runtime.h"
#include "BNGLexer.h"
#include "BNGParser.h"
#include "core/Ullmann.hpp"
#include "parser/BNGAstVisitor.hpp"
#include "parser/PatternGraphBuilder.hpp"

namespace bng::engine {

namespace {

enum class BngsimRateKind {
    Parameter,
    Function,
    SyntheticExpression,
};

struct BngsimRateReference {
    BngsimRateKind kind;
    std::string name;
    std::optional<ast::Expression> expression;
};

std::string toLowerCopy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

bool modelHasObservable(const ast::Model& model, const std::string& name) {
    for (const auto& observable : model.getObservables()) {
        if (observable.getName() == name) {
            return true;
        }
    }
    return false;
}

bool modelHasZeroArgFunction(const ast::Model& model, const std::string& name) {
    for (const auto& function : model.getFunctions()) {
        if (function.getName() == name && function.getArgs().empty()) {
            return true;
        }
    }
    return false;
}

void validateBngsimTableMethod(const std::string& method) {
    const std::string lower = toLowerCopy(method);
    if (lower.empty() || lower == "linear" || lower == "step") {
        return;
    }
    throw std::runtime_error(
        "BNGsim adapter rejected TFUN: unsupported interpolation method '" + method + "'");
}

std::string resolveBngsimTablePath(
    const std::string& rawPath,
    const std::filesystem::path& sourcePath) {
    if (rawPath.empty()) {
        return {};
    }
    try {
        const std::filesystem::path tablePath(rawPath);
        if (tablePath.is_absolute()) {
            return tablePath.lexically_normal().string();
        }
        if (sourcePath.empty()) {
            throw std::runtime_error(
                "BNGsim adapter rejected TFUN: relative table path requires source-directory provenance");
        }
        std::error_code ec;
        std::filesystem::path baseDir;
        if (std::filesystem::is_directory(sourcePath, ec)) {
            baseDir = sourcePath;
        } else {
            baseDir = sourcePath.parent_path();
        }
        if (baseDir.empty()) {
            baseDir = std::filesystem::current_path(ec);
        }
        const auto resolved = std::filesystem::absolute(baseDir / tablePath, ec).lexically_normal();
        if (ec || resolved.empty()) {
            throw std::runtime_error(
                "BNGsim adapter rejected TFUN: relative table path requires source-directory provenance");
        }
        return resolved.string();
    } catch (const std::runtime_error&) {
        throw;
    } catch (const std::exception&) {
        throw std::runtime_error(
            "BNGsim adapter rejected TFUN: relative table path requires source-directory provenance");
    }
}

std::string bngsimTableCounterName(
    const ast::Model& model,
    const ast::Expression& counter);

std::string normalizeRateLaw(std::string value) {
    const auto first = value.find_first_not_of(" \t");
    if (first != std::string::npos) value.erase(0, first);
    else value.clear();
    if (!value.empty()) {
        const auto last = value.find_last_not_of(" \t");
        value.erase(last + 1);
    }
    if (value.size() >= 2 && value.substr(value.size() - 2) == "()") {
        value.erase(value.size() - 2);
        if (!value.empty()) {
            const auto last = value.find_last_not_of(" \t");
            if (last != std::string::npos) value.erase(last + 1);
            const auto leading = value.find_first_not_of(" \t");
            if (leading != std::string::npos) value.erase(0, leading);
        }
    }
    return value;
}

void collectExpressionBlockers(
    const ast::Model& model,
    const ast::Expression& expression,
    const std::filesystem::path& sourcePath,
    std::vector<std::string>& blockers) {
    switch (expression.kind()) {
    case ast::ExpressionKind::Number:
    case ast::ExpressionKind::Identifier:
        return;
    case ast::ExpressionKind::Unary:
        if (expression.args().size() != 1) {
            blockers.push_back("BNGsim adapter rejected malformed unary expression");
            return;
        }
        collectExpressionBlockers(model, expression.args().front(), sourcePath, blockers);
        return;
    case ast::ExpressionKind::Binary:
        if (expression.args().size() != 2) {
            blockers.push_back("BNGsim adapter rejected malformed binary expression");
            return;
        }
        collectExpressionBlockers(model, expression.args()[0], sourcePath, blockers);
        collectExpressionBlockers(model, expression.args()[1], sourcePath, blockers);
        return;
    case ast::ExpressionKind::Function:
    case ast::ExpressionKind::ObservableRef:
        for (const auto& argument : expression.args()) {
            collectExpressionBlockers(model, argument, sourcePath, blockers);
        }
        return;
    case ast::ExpressionKind::TableFunction:
        if (expression.args().size() != 1) {
            blockers.push_back("BNGsim adapter rejected malformed TFUN expression");
            return;
        }
        try {
            validateBngsimTableMethod(expression.tableMethod());
            (void)bngsimTableCounterName(model, expression.args().front());
            if (!expression.tableFilePath().empty()) {
                (void)resolveBngsimTablePath(expression.tableFilePath(), sourcePath);
            }
        } catch (const std::exception& error) {
            blockers.push_back(error.what());
        }
        return;
    }
    blockers.push_back("BNGsim adapter rejected unknown expression kind");
}

void collectInlineRateExpressionBlockers(
    const ast::Model& model,
    const ast::Expression& expression,
    const std::filesystem::path& sourcePath,
    const std::string& context,
    std::vector<std::string>& blockers) {
    switch (expression.kind()) {
    case ast::ExpressionKind::Number:
        if (!std::isfinite(expression.numberValue())) {
            blockers.push_back(
                "BNGsim adapter rejected " + context + ": rate expression contains non-finite literal");
        }
        return;
    case ast::ExpressionKind::Identifier: {
        const auto& name = expression.name();
        if (name == "time" || name == "t" ||
            model.getParameters().contains(name) ||
            modelHasObservable(model, name) ||
            modelHasZeroArgFunction(model, name)) {
            return;
        }
        blockers.push_back(
            "BNGsim adapter rejected " + context + ": rate expression references unsupported identifier '" + name + "'");
        return;
    }
    case ast::ExpressionKind::Unary:
        if (expression.args().size() != 1) {
            blockers.push_back("BNGsim adapter rejected malformed unary expression");
            return;
        }
        if (expression.name() != "+" && expression.name() != "-") {
            blockers.push_back(
                "BNGsim adapter rejected " + context + ": unsupported unary operator '" + expression.name() + "' in rate expression");
            return;
        }
        collectInlineRateExpressionBlockers(
            model, expression.args().front(), sourcePath, context, blockers);
        return;
    case ast::ExpressionKind::Binary:
        if (expression.args().size() != 2) {
            blockers.push_back("BNGsim adapter rejected malformed binary expression");
            return;
        }
        if (expression.name() != "+" && expression.name() != "-" &&
            expression.name() != "*" && expression.name() != "/" &&
            expression.name() != "^") {
            blockers.push_back(
                "BNGsim adapter rejected " + context + ": unsupported binary operator '" + expression.name() + "' in rate expression");
            return;
        }
        collectInlineRateExpressionBlockers(
            model, expression.args()[0], sourcePath, context, blockers);
        collectInlineRateExpressionBlockers(
            model, expression.args()[1], sourcePath, context, blockers);
        return;
    case ast::ExpressionKind::Function:
    case ast::ExpressionKind::ObservableRef: {
        const std::string& name = expression.name();
        const std::string lower = toLowerCopy(name);
        const std::size_t arity = expression.args().size();
        if (arity == 0 &&
            (lower == "time" || lower == "t" ||
             modelHasZeroArgFunction(model, name) ||
             modelHasObservable(model, name))) {
            return;
        }
        static const std::unordered_set<std::string> kUnaryBuiltins = {
            "abs", "acos", "asin", "atan", "ceil", "cos", "cosh", "exp",
            "floor", "ln", "log", "log10", "log2", "sin", "sinh", "sqrt",
            "tan", "tanh"
        };
        const bool supportedBuiltin =
            (arity == 1 && kUnaryBuiltins.count(lower) > 0) ||
            (arity == 2 && (lower == "min" || lower == "max")) ||
            (arity == 3 && lower == "if");
        if (!supportedBuiltin) {
            blockers.push_back(
                "BNGsim adapter rejected " + context + ": unsupported function '" + name + "' in rate expression");
            return;
        }
        for (const auto& argument : expression.args()) {
            collectInlineRateExpressionBlockers(model, argument, sourcePath, context, blockers);
        }
        return;
    }
    case ast::ExpressionKind::TableFunction:
        collectExpressionBlockers(model, expression, sourcePath, blockers);
        return;
    }
    blockers.push_back("BNGsim adapter rejected unknown expression kind");
}

std::string bngsimReactionContext(std::size_t index, const ast::Rxn& reaction) {
    return "reaction " + std::to_string(index) +
           (reaction.getLabel().empty() ? std::string{} : " ('" + reaction.getLabel() + "')");
}

std::vector<int> checkedBngsimIndices(
    const std::vector<std::size_t>& indices,
    std::size_t speciesCount,
    const std::string& context) {
    std::vector<int> result;
    result.reserve(indices.size());
    for (const auto index : indices) {
        if (index >= speciesCount) {
            throw std::runtime_error(
                "BNGsim adapter rejected " + context + ": species index out of range");
        }
        if (index > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
            throw std::runtime_error(
                "BNGsim adapter rejected " + context + ": species index exceeds BNGsim int range");
        }
        result.push_back(static_cast<int>(index));
    }
    return result;
}

std::vector<std::pair<int, double>> compileBngsimObservableEntries(
    ast::Model& model,
    const GeneratedNetwork& network,
    const ast::Observable& observable) {
    if (observable.getType() != "Molecules" && observable.getType() != "Species") {
        throw std::runtime_error(
            "BNGsim adapter rejected observable '" + observable.getName() +
            "': unsupported observable type '" + observable.getType() + "'");
    }

    std::vector<std::pair<int, double>> entries;
    for (std::size_t speciesIndex = 0; speciesIndex < network.species.size(); ++speciesIndex) {
        std::size_t weight = 0;

        for (const auto& patternText : observable.getPatterns()) {
            std::string cleanPattern = patternText;
            std::string quantifier;
            int quantifierThreshold = 0;
            bool hasQuantifier = false;

            static const std::vector<std::string> operators = {">=", "<=", "==", "!=", ">", "<"};
            for (const auto& op : operators) {
                const auto position = cleanPattern.rfind(op);
                if (position == std::string::npos || position == 0) continue;

                std::string after = cleanPattern.substr(position + op.size());
                const auto first = after.find_first_not_of(" \t");
                if (first == std::string::npos) continue;
                after.erase(0, first);
                const auto last = after.find_last_not_of(" \t");
                after.erase(last + 1);

                bool isInteger = !after.empty();
                for (const char c : after) {
                    if (!std::isdigit(static_cast<unsigned char>(c))) {
                        isInteger = false;
                        break;
                    }
                }
                if (!isInteger) continue;

                std::string before = cleanPattern.substr(0, position);
                const auto beforeLast = before.find_last_not_of(" \t");
                if (beforeLast == std::string::npos) continue;
                before.erase(beforeLast + 1);
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

            antlr4::ANTLRInputStream input(cleanPattern);
            BNGLexer lexer(&input);
            antlr4::CommonTokenStream tokens(&lexer);
            BNGParser parser(&tokens);
            auto* species = parser.species_def();
            if (parser.getNumberOfSyntaxErrors() != 0) {
                throw std::runtime_error(
                    "BNGsim adapter rejected observable '" + observable.getName() +
                    "': could not parse pattern '" + patternText + "'");
            }

            auto pattern = bng::parser::buildPatternGraph(species, model, false);
            const auto patternCompartment = bng::parser::extractSpeciesCompartment(species);
            if (!patternCompartment.empty()) {
                bool hasMoleculeCompartment = false;
                for (auto it = pattern.begin(); it != pattern.end(); ++it) {
                    if (!(*it)->get_compartment().empty()) {
                        hasMoleculeCompartment = true;
                        break;
                    }
                }
                if (!hasMoleculeCompartment &&
                    network.species.get(speciesIndex).getCompartment() != patternCompartment) {
                    continue;
                }
            }

            const auto& targetGraph = network.species.get(speciesIndex).getSpeciesGraph().getGraph();
            BNGcore::UllmannSGIso matcher(pattern, targetGraph);
            BNGcore::List<BNGcore::Map> maps;
            matcher.find_maps(maps);

            std::size_t matchCount = 0;
            for (auto mapIt = maps.begin(); mapIt != maps.end(); ++mapIt) {
                bool valid = true;
                for (auto patternIt = pattern.begin(); patternIt != pattern.end(); ++patternIt) {
                    auto* target = mapIt->mapf(*patternIt);
                    if (!target || !((*patternIt)->get_state() == target->get_state())) {
                        valid = false;
                        break;
                    }
                    const bool patternIsMolecule = ((*patternIt)->in_degree() == 0);
                    const bool targetIsMolecule = (target->in_degree() == 0);
                    if (patternIsMolecule != targetIsMolecule) {
                        valid = false;
                        break;
                    }
                    if (patternIsMolecule && !(*patternIt)->get_compartment().empty() &&
                        target->get_compartment() != (*patternIt)->get_compartment()) {
                        valid = false;
                        break;
                    }
                }
                if (valid) ++matchCount;
            }

            if (hasQuantifier) {
                bool passes = false;
                const int count = static_cast<int>(matchCount);
                if (quantifier == ">") passes = count > quantifierThreshold;
                else if (quantifier == "<") passes = count < quantifierThreshold;
                else if (quantifier == ">=") passes = count >= quantifierThreshold;
                else if (quantifier == "<=") passes = count <= quantifierThreshold;
                else if (quantifier == "==") passes = count == quantifierThreshold;
                else if (quantifier == "!=") passes = count != quantifierThreshold;
                matchCount = passes ? matchCount : 0;
            }

            if (observable.getType() == "Species" && matchCount > 0) matchCount = 1;
            weight += matchCount;
        }

        if (weight > 0) {
            if (speciesIndex > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
                throw std::runtime_error(
                    "BNGsim adapter rejected observable: species index exceeds int range");
            }
            entries.emplace_back(static_cast<int>(speciesIndex), static_cast<double>(weight));
        }
    }
    return entries;
}

std::string bngsimTableCounterName(
    const ast::Model& model,
    const ast::Expression& counter) {
    if (counter.kind() == ast::ExpressionKind::Identifier ||
        counter.kind() == ast::ExpressionKind::ObservableRef) {
        if (counter.name().empty()) {
            throw std::runtime_error("BNGsim adapter rejected TFUN: empty counter name");
        }
        if (counter.name() == "t" || counter.name() == "time") {
            return "time";
        }
        if (model.getParameters().contains(counter.name()) ||
            modelHasObservable(model, counter.name())) {
            return counter.name();
        }
        throw std::runtime_error(
            "BNGsim adapter rejected TFUN: counter must be time or a named parameter/observable");
    }
    if (counter.kind() == ast::ExpressionKind::Function &&
        (counter.name() == "time" || counter.name() == "t") &&
        counter.args().empty()) {
        return "time";
    }
    throw std::runtime_error(
        "BNGsim adapter rejected TFUN: counter must be time or a named parameter/observable");
}

bool expressionDependsOnAny(
    const ast::Model& model,
    const ast::Expression& expression,
    const std::unordered_set<std::string>& targets,
    std::unordered_set<std::string>& visitedParams) {
    if (targets.empty()) return false;
    for (const auto& dep : expression.getDependencies()) {
        if (targets.count(dep) > 0) return true;
        if (model.getParameters().contains(dep) && visitedParams.insert(dep).second) {
            if (expressionDependsOnAny(
                    model,
                    model.getParameters().get(dep).getExpression(),
                    targets,
                    visitedParams)) {
                return true;
            }
        }
    }
    return false;
}

bool expressionReferencesDynamicOrPromoted(
    const ast::Model& model,
    const ast::Expression& expression,
    const std::unordered_set<std::string>& promotedParams) {
    switch (expression.kind()) {
    case ast::ExpressionKind::Number:
        return false;
    case ast::ExpressionKind::Identifier: {
        const auto& name = expression.name();
        if (name == "time" || name == "t" ||
            modelHasObservable(model, name) ||
            promotedParams.count(name) > 0) {
            return true;
        }
        if (model.getParameters().contains(name)) {
            std::unordered_set<std::string> visited;
            if (expressionDependsOnAny(
                    model,
                    model.getParameters().get(name).getExpression(),
                    promotedParams,
                    visited)) {
                return true;
            }
            return model.getParameters().isTimeDependent(name);
        }
        return false;
    }
    case ast::ExpressionKind::ObservableRef:
        return true;
    case ast::ExpressionKind::TableFunction:
        return true;
    case ast::ExpressionKind::Function:
        if (expression.args().empty() &&
            (expression.name() == "time" || expression.name() == "t")) {
            return true;
        }
        for (const auto& arg : expression.args()) {
            if (expressionReferencesDynamicOrPromoted(model, arg, promotedParams)) {
                return true;
            }
        }
        return false;
    case ast::ExpressionKind::Unary:
    case ast::ExpressionKind::Binary:
        for (const auto& arg : expression.args()) {
            if (expressionReferencesDynamicOrPromoted(model, arg, promotedParams)) {
                return true;
            }
        }
        return false;
    }
    return true;
}

void collectEventExpressionBlockers(
    const ast::Model& model,
    const ast::Expression& expression,
    const std::string& context,
    bool allowLogicalAndCompare,
    std::vector<std::string>& blockers) {
    switch (expression.kind()) {
    case ast::ExpressionKind::Number:
        if (!std::isfinite(expression.numberValue())) {
            blockers.push_back(
                "BNGsim adapter rejected " + context + ": expression contains non-finite literal");
        }
        return;
    case ast::ExpressionKind::Identifier: {
        const auto& name = expression.name();
        if (name == "time" || name == "t" ||
            model.getParameters().contains(name) ||
            modelHasObservable(model, name)) {
            return;
        }
        blockers.push_back(
            "BNGsim adapter rejected " + context +
            ": unsupported identifier '" + name + "' in event expression");
        return;
    }
    case ast::ExpressionKind::Unary: {
        if (expression.args().size() != 1) {
            blockers.push_back(
                "BNGsim adapter rejected " + context + ": malformed unary expression");
            return;
        }
        const auto& op = expression.name();
        if (op == "+" || op == "-") {
            collectEventExpressionBlockers(
                model, expression.args().front(), context, false, blockers);
            return;
        }
        if (allowLogicalAndCompare && op == "!") {
            collectEventExpressionBlockers(
                model, expression.args().front(), context, true, blockers);
            return;
        }
        blockers.push_back(
            "BNGsim adapter rejected " + context +
            ": unsupported unary operator '" + op + "' in event expression");
        return;
    }
    case ast::ExpressionKind::Binary: {
        if (expression.args().size() != 2) {
            blockers.push_back(
                "BNGsim adapter rejected " + context + ": malformed binary expression");
            return;
        }
        const auto& op = expression.name();
        if (op == "+" || op == "-" || op == "*" || op == "/" || op == "^" || op == "**") {
            collectEventExpressionBlockers(
                model, expression.args()[0], context, false, blockers);
            collectEventExpressionBlockers(
                model, expression.args()[1], context, false, blockers);
            return;
        }
        if (allowLogicalAndCompare && (op == "&&" || op == "||")) {
            collectEventExpressionBlockers(
                model, expression.args()[0], context, true, blockers);
            collectEventExpressionBlockers(
                model, expression.args()[1], context, true, blockers);
            return;
        }
        if (allowLogicalAndCompare &&
            (op == "<" || op == "<=" || op == ">" || op == ">=" ||
             op == "==" || op == "!=")) {
            collectEventExpressionBlockers(
                model, expression.args()[0], context, false, blockers);
            collectEventExpressionBlockers(
                model, expression.args()[1], context, false, blockers);
            return;
        }
        blockers.push_back(
            "BNGsim adapter rejected " + context +
            ": unsupported binary operator '" + op + "' in event expression");
        return;
    }
    case ast::ExpressionKind::Function:
    case ast::ExpressionKind::ObservableRef: {
        const std::string& name = expression.name();
        const std::string lower = toLowerCopy(name);
        const std::size_t arity = expression.args().size();
        if (lower == "delay") {
            blockers.push_back(
                "BNGsim adapter rejected " + context +
                ": delay() expressions require the native DDE method-of-steps solver");
            return;
        }
        if (lower.rfind("distrib_", 0) == 0) {
            blockers.push_back(
                "BNGsim adapter rejected " + context +
                ": SBML distrib function '" + name + "' is unsupported by BNGsim");
            return;
        }
        if (arity == 0 && (lower == "time" || lower == "t" || modelHasObservable(model, name))) {
            return;
        }
        if (arity == 3 && lower == "if") {
            collectEventExpressionBlockers(model, expression.args()[0], context, true, blockers);
            collectEventExpressionBlockers(model, expression.args()[1], context, false, blockers);
            collectEventExpressionBlockers(model, expression.args()[2], context, false, blockers);
            return;
        }
        static const std::unordered_set<std::string> kUnaryBuiltins = {
            "abs", "acos", "asin", "atan", "ceil", "cos", "cosh", "exp",
            "floor", "ln", "log", "log10", "log2", "sin", "sinh", "sqrt",
            "tan", "tanh"
        };
        const bool supportedBuiltin =
            (arity == 1 && kUnaryBuiltins.count(lower) > 0) ||
            (arity == 2 && (lower == "min" || lower == "max"));
        if (!supportedBuiltin) {
            blockers.push_back(
                "BNGsim adapter rejected " + context +
                ": unsupported function '" + name + "' in event expression");
            return;
        }
        for (const auto& argument : expression.args()) {
            collectEventExpressionBlockers(model, argument, context, false, blockers);
        }
        return;
    }
    case ast::ExpressionKind::TableFunction:
        blockers.push_back(
            "BNGsim adapter rejected " + context +
            ": TFUN inside event expressions is unsupported");
        return;
    }
    blockers.push_back("BNGsim adapter rejected " + context + ": unknown expression kind");
}

struct CompiledBngsimEventAssignment {
    bool isSpecies = true;
    int speciesIndex = -1;
    std::string parameterName;
    ast::Expression expandedValue;
};

struct CompiledBngsimEvent {
    std::string id;
    ast::Expression expandedTrigger;
    bool initialValue = false;
    bool persistent = true;
    bool useValuesFromTriggerTime = true;
    std::optional<ast::Expression> expandedDelay;
    std::optional<ast::Expression> expandedPriority;
    std::vector<CompiledBngsimEventAssignment> assignments;
};

struct CompiledBngsimEventPlan {
    std::vector<CompiledBngsimEvent> events;
    std::vector<std::string> promotedParameterOrder;
    std::unordered_set<std::string> promotedParameters;
};

CompiledBngsimEventPlan analyzeBngsimEvents(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const std::unordered_map<std::string, std::vector<std::pair<int, double>>>& compiledObservables,
    std::vector<std::string>& blockers) {
    CompiledBngsimEventPlan plan;
    if (!model.getEventFormatVersion().has_value()) {
        return plan;
    }

    try {
        ast::validateNativeEventSubset(model);
    } catch (const std::exception& error) {
        blockers.push_back(
            std::string("BNGsim adapter rejected event: ") + error.what());
        return plan;
    }

    std::unordered_set<std::string> speciesNames;
    speciesNames.reserve(network.species.size() * 2);
    for (const auto& sp : network.species.all()) {
        speciesNames.insert(sp.getSpeciesGraph().toString());
        speciesNames.insert(sp.getSpeciesGraph().toStringForDedup());
    }

    const ast::ModelFunctionEvaluator evaluator(model);
    for (std::size_t idx = 0; idx < model.getEvents().size(); ++idx) {
        const auto& ev = model.getEvents()[idx];
        const std::string eventId =
            ev.id.empty() ? ("event_" + std::to_string(idx)) : ev.id;
        const std::string ctx = "event '" + eventId + "'";

        CompiledBngsimEvent compiled;
        compiled.id = eventId;
        compiled.initialValue = ev.initialValue;
        compiled.persistent = ev.persistent;
        compiled.useValuesFromTriggerTime = ev.useValuesFromTriggerTime;
        compiled.expandedTrigger = evaluator.expandFunctions(ev.trigger);

        collectEventExpressionBlockers(
            model, compiled.expandedTrigger, ctx + " trigger", true, blockers);

        if (ev.delay.has_value()) {
            compiled.expandedDelay = evaluator.expandFunctions(*ev.delay);
            collectEventExpressionBlockers(
                model, *compiled.expandedDelay, ctx + " delay", false, blockers);
        }
        if (ev.priority.has_value()) {
            compiled.expandedPriority = evaluator.expandFunctions(*ev.priority);
            collectEventExpressionBlockers(
                model, *compiled.expandedPriority, ctx + " priority", false, blockers);
        }

        std::unordered_set<std::string> seenTargets;
        std::unordered_set<int> seenSpeciesTargets;
        for (const auto& assignment : ev.assignments) {
            if (!seenTargets.insert(assignment.target).second) {
                blockers.push_back(
                    "BNGsim adapter rejected " + ctx +
                    ": duplicate assignment target '" + assignment.target + "'");
                continue;
            }
            CompiledBngsimEventAssignment compiledAssign;
            compiledAssign.expandedValue = evaluator.expandFunctions(assignment.value);
            collectEventExpressionBlockers(
                model,
                compiledAssign.expandedValue,
                ctx + " assignment '" + assignment.target + "'",
                false,
                blockers);

            const auto obsIt = compiledObservables.find(assignment.target);
            if (obsIt != compiledObservables.end()) {
                const auto& entries = obsIt->second;
                if (entries.size() != 1 || entries.front().second != 1.0 ||
                    network.species.get(static_cast<std::size_t>(entries.front().first)).isConstant()) {
                    blockers.push_back(
                        "BNGsim adapter rejected " + ctx +
                        ": assignment target '" + assignment.target +
                        "' must identify one nonconstant species with weight one");
                    continue;
                }
                const int spIdx = entries.front().first;
                if (!seenSpeciesTargets.insert(spIdx).second) {
                    blockers.push_back(
                        "BNGsim adapter rejected " + ctx +
                        ": assignments alias the same species");
                    continue;
                }
                compiledAssign.isSpecies = true;
                compiledAssign.speciesIndex = spIdx;
            } else if (model.getParameters().contains(assignment.target)) {
                if (model.getParameters().isTimeDependent(assignment.target)) {
                    blockers.push_back(
                        "BNGsim adapter rejected " + ctx +
                        ": assignment target parameter '" + assignment.target + "' must be static");
                    continue;
                }
                if (modelHasZeroArgFunction(model, assignment.target) ||
                    speciesNames.count(assignment.target) > 0) {
                    blockers.push_back(
                        "BNGsim adapter rejected " + ctx +
                        ": event-assigned parameter '" + assignment.target +
                        "' collides with a species or function name");
                    continue;
                }
                compiledAssign.isSpecies = false;
                compiledAssign.parameterName = assignment.target;
                if (plan.promotedParameters.insert(assignment.target).second) {
                    plan.promotedParameterOrder.push_back(assignment.target);
                }
            } else {
                blockers.push_back(
                    "BNGsim adapter rejected " + ctx +
                    ": assignment target '" + assignment.target +
                    "' must be a species observable or static parameter");
                continue;
            }

            compiled.assignments.push_back(std::move(compiledAssign));
        }
        if (compiled.assignments.empty() && ev.assignments.empty()) {
            blockers.push_back(
                "BNGsim adapter rejected " + ctx + ": event requires at least one assignment");
        }
        plan.events.push_back(std::move(compiled));
    }

    // Reject derived parameters that depend on an event-assigned parameter,
    // because BNGsim evaluates parameter-expression chains only at build/set_param.
    if (!plan.promotedParameters.empty()) {
        for (const auto& parameter : model.getParameters().all()) {
            if (plan.promotedParameters.count(parameter.getName()) > 0) continue;
            std::unordered_set<std::string> visited;
            if (expressionDependsOnAny(
                    model, parameter.getExpression(), plan.promotedParameters, visited)) {
                blockers.push_back(
                    "BNGsim adapter rejected event: derived parameter '" +
                    parameter.getName() +
                    "' depends on an event-assigned parameter");
            }
        }
    }

    // Validate static delays are finite and non-negative.
    for (const auto& ev : plan.events) {
        if (!ev.expandedDelay.has_value()) continue;
        if (!expressionReferencesDynamicOrPromoted(model, *ev.expandedDelay, plan.promotedParameters)) {
            try {
                const double d = ev.expandedDelay->evaluate([&](const std::string& name) {
                    return model.getParameters().evaluate(name);
                });
                if (!std::isfinite(d) || d < 0.0) {
                    blockers.push_back(
                        "BNGsim adapter rejected event '" + ev.id +
                        "': delay must be finite and non-negative");
                }
            } catch (const std::exception& error) {
                blockers.push_back(
                    "BNGsim adapter rejected event '" + ev.id +
                    "' delay: " + error.what());
            }
        }
    }

    return plan;
}

BngsimRateReference resolveBngsimRateReference(
    const ast::Model& model,
    const ast::Rxn& reaction,
    std::size_t index,
    const BngsimLoweringOptions& options) {
    const auto context = bngsimReactionContext(index, reaction);
    if (compile::isAbsoluteFluxReaction(model, reaction)) {
        throw std::runtime_error(
            "BNGsim adapter rejected " + context +
            ": absolute-flux reactions are unsupported");
    }
    const auto& rateLaw = reaction.getRateLaw();
    const auto normalized = normalizeRateLaw(rateLaw);
    if (model.getParameters().contains(normalized)) {
        return {BngsimRateKind::Parameter, normalized, std::nullopt};
    }
    for (const auto& function : model.getFunctions()) {
        if (function.getName() == normalized) {
            return {BngsimRateKind::Function, normalized, std::nullopt};
        }
    }
    if (!options.allowRateExpressionWrapping) {
        throw std::runtime_error(
            "BNGsim adapter rejected " + context +
            ": rate law '" + rateLaw + "' is not a direct parameter or function reference");
    }

    ast::Expression rateExpression;
    if (reaction.getRateExpression().has_value()) {
        rateExpression = *reaction.getRateExpression();
    } else {
        try {
            rateExpression = parser::parseExpression(rateLaw);
        } catch (const std::exception&) {
            throw std::runtime_error(
                "BNGsim adapter rejected " + context +
                ": rate law '" + rateLaw + "' could not be parsed as a BNGsim functional expression");
        }
    }

    std::vector<std::string> exprBlockers;
    collectInlineRateExpressionBlockers(
        model, rateExpression, options.sourcePath, context, exprBlockers);
    if (!exprBlockers.empty()) {
        throw std::runtime_error(exprBlockers.front());
    }
    return {BngsimRateKind::SyntheticExpression, {}, std::move(rateExpression)};
}

double computeEffectiveBngsimStatFactor(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const ast::Rxn& reaction,
    const std::string& context) {
    const bool isTotalRate =
        reaction.isTotalRate() ||
        compile::isTotalRateReaction(model, reaction.getOriginRuleName());
    if (isTotalRate) {
        // BNG2 / BNG3 authored TotalRate omits both the reaction-center
        // symmetry factor and the compartment unit conversion factor while
        // still multiplying by reactant counts (apply_species_factor = true).
        return 1.0;
    }
    double factor = reaction.getFactor();
    const auto unitFactor = io::NetWriter::computeUnitConversionFactor(reaction, model, network);
    if (unitFactor.has_value()) {
        if (!std::isfinite(*unitFactor) || *unitFactor <= 0.0) {
            throw std::runtime_error(
                "BNGsim adapter rejected " + context +
                ": compartment unit conversion factor must be finite and positive");
        }
        factor *= *unitFactor;
    }
    if (!std::isfinite(factor)) {
        throw std::runtime_error(
            "BNGsim adapter rejected " + context +
            ": effective statistical/volume factor is not finite");
    }
    return factor;
}

} // namespace

BngsimLoweringCheck checkBngsimLowering(
    const ast::Model& model,
    const GeneratedNetwork& network) {
    return checkBngsimLowering(model, network, BngsimLoweringOptions{});
}

BngsimLoweringCheck checkBngsimLowering(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const BngsimLoweringOptions& options) {
    BngsimLoweringCheck check;
    auto& mutableModel = const_cast<ast::Model&>(model);
    auto reject = [&](const std::string& blocker) {
        check.blockers.push_back(blocker);
    };

    bool hasDelayBlocker = false;
    for (const auto& rule : model.getReactionRules()) {
        if (rule.getDelayExpression()) {
            reject(
                "BNGsim adapter rejected model: delayed reactions require the "
                "native DDE method-of-steps solver");
            hasDelayBlocker = true;
            break;
        }
    }
    if (!hasDelayBlocker) {
        for (const auto& rxn : network.reactions.all()) {
            if (rxn.getDelayExpression()) {
                reject(
                    "BNGsim adapter rejected model: delayed reactions require the "
                    "native DDE method-of-steps solver");
                hasDelayBlocker = true;
                break;
            }
        }
    }
    bool hasDelayExprBlocker = false;
    for (const auto& rule : model.getReactionRules()) {
        for (const auto& rate : rule.getRates()) {
            if (expressionUsesDelay(rate)) {
                reject(
                    "BNGsim adapter rejected model: delay() expressions require the "
                    "native DDE method-of-steps solver");
                hasDelayExprBlocker = true;
                break;
            }
        }
        if (hasDelayExprBlocker) break;
    }
    if (!hasDelayExprBlocker) {
        for (const auto& fn : model.getFunctions()) {
            if (expressionUsesDelay(fn.getExpression())) {
                reject(
                    "BNGsim adapter rejected model: delay() expressions require the "
                    "native DDE method-of-steps solver");
                hasDelayExprBlocker = true;
                break;
            }
        }
    }
    if (!hasDelayExprBlocker) {
        for (const auto& rxn : network.reactions.all()) {
            if ((rxn.getRateExpression() &&
                 expressionUsesDelay(*rxn.getRateExpression())) ||
                (!rxn.getRateExpression() && containsDelayCall(rxn.getRateLaw()))) {
                reject(
                    "BNGsim adapter rejected model: delay() expressions require the "
                    "native DDE method-of-steps solver");
                break;
            }
        }
    }
    if (!model.getEnergyPatterns().empty()) {
        reject("BNGsim adapter rejected model: energy patterns require an eBNGL rate bridge");
    }
    if (!model.getBarrierPatterns().empty()) {
        reject("BNGsim adapter rejected model: barrier patterns require an eBNGL rate bridge");
    }
    for (const auto& rule : model.getReactionRules()) {
        if (rule.hasDrivingWork()) {
            reject(
                "BNGsim adapter rejected model: driven_by() reservoir work requires "
                "an eBNGL rate bridge");
            break;
        }
    }
    if (!model.getPopulationMaps().empty()) {
        reject("BNGsim adapter rejected model: population maps are not a generated-network feature");
    }
    if (!model.getSimulationProtocol().empty()) {
        reject("BNGsim adapter rejected model: simulation protocol requires a protocol bridge");
    }
    for (const auto& action : model.getActions()) {
        if (action.name != "generate_network") {
            reject(
                "BNGsim adapter rejected model action '" + action.name +
                "': action execution requires a protocol bridge");
            break;
        }
    }

    for (const auto& parameter : model.getParameters().all()) {
        try {
            if (!std::isfinite(model.getParameters().evaluate(parameter.getName()))) {
                reject(
                    "BNGsim adapter rejected parameter '" + parameter.getName() +
                    "': value is not finite");
            }
        } catch (const std::exception& error) {
            reject(
                "BNGsim adapter rejected parameter '" + parameter.getName() +
                "': " + error.what());
        }
    }

    std::unordered_map<std::string, std::vector<std::pair<int, double>>> compiledObservables;
    for (const auto& observable : model.getObservables()) {
        try {
            compiledObservables.emplace(
                observable.getName(),
                compileBngsimObservableEntries(mutableModel, network, observable));
        } catch (const std::exception& error) {
            reject(error.what());
            break;
        } catch (...) {
            reject(
                "BNGsim adapter rejected observable '" + observable.getName() +
                "': could not build observable pattern");
            break;
        }
    }

    const auto eventPlan = analyzeBngsimEvents(
        model, network, compiledObservables, check.blockers);

    for (const auto& compartment : model.getCompartments()) {
        if (compartment.isVolumeTimeDependent()) {
            reject(
                "BNGsim adapter rejected compartment '" + compartment.getName() +
                "': dynamic/time-dependent compartment volumes are unsupported");
            continue;
        }
        if (compartment.getDimension() != 2 && compartment.getDimension() != 3) {
            reject(
                "BNGsim adapter rejected compartment '" + compartment.getName() +
                "': only 2D surface and 3D volume compartments are supported");
            continue;
        }
        if (!std::isfinite(compartment.getVolume()) || compartment.getVolume() <= 0.0) {
            reject(
                "BNGsim adapter rejected compartment '" + compartment.getName() +
                "': compartment volume must be finite and positive");
            continue;
        }
        if (compartment.getVolumeExpression().has_value() &&
            !eventPlan.promotedParameters.empty()) {
            std::unordered_set<std::string> visited;
            if (expressionDependsOnAny(
                    model,
                    *compartment.getVolumeExpression(),
                    eventPlan.promotedParameters,
                    visited)) {
                reject(
                    "BNGsim adapter rejected compartment '" + compartment.getName() +
                    "': event-modified compartment volumes are unsupported");
            }
        }
    }

    for (const auto& function : model.getFunctions()) {
        if (!function.getArgs().empty()) {
            reject(
                "BNGsim adapter rejected function '" + function.getName() +
                "': function arguments require a local-function bridge");
            continue;
        }
        collectExpressionBlockers(
            model, function.getExpression(), options.sourcePath, check.blockers);
    }

    for (std::size_t index = 0; index < network.reactions.size(); ++index) {
        const auto& reaction = network.reactions.all()[index];
        const auto context = bngsimReactionContext(index, reaction);
        try {
            (void)checkedBngsimIndices(reaction.getReactants(), network.species.size(), context);
            (void)checkedBngsimIndices(reaction.getProducts(), network.species.size(), context);
        } catch (const std::exception& error) {
            reject(error.what());
            break;
        }
        try {
            (void)resolveBngsimRateReference(model, reaction, index, options);
            (void)computeEffectiveBngsimStatFactor(model, network, reaction, context);
        } catch (const std::exception& error) {
            reject(error.what());
            break;
        }
    }

    check.supported = check.blockers.empty();
    return check;
}


#ifdef BNG3_HAS_BNGSIM_ADAPTER


namespace {

std::string makeUniqueSyntheticFunctionName(
    const ast::Model& model,
    std::unordered_set<std::string>& usedNames,
    const std::string& base) {
    std::string candidate = base;
    while (usedNames.count(candidate) > 0 ||
           model.getParameters().contains(candidate) ||
           modelHasObservable(model, candidate) ||
           modelHasZeroArgFunction(model, candidate)) {
        candidate.push_back('_');
    }
    usedNames.insert(candidate);
    return candidate;
}

std::string makeUniqueSyntheticFunctionName(
    const ast::Model& model,
    std::unordered_set<std::string>& usedNames,
    std::size_t reactionIndex) {
    return makeUniqueSyntheticFunctionName(
        model, usedNames, "__bng3_rate_" + std::to_string(reactionIndex));
}

std::string formatDoubleExact(double value) {
    std::ostringstream oss;
    oss << std::setprecision(std::numeric_limits<double>::max_digits10) << value;
    return oss.str();
}

std::string eventExpressionForBngsim(
    const ast::Model& model,
    const ast::Expression& expression) {
    switch (expression.kind()) {
    case ast::ExpressionKind::Number:
        return formatDoubleExact(expression.numberValue());
    case ast::ExpressionKind::Identifier:
        if ((expression.name() == "time" || expression.name() == "t") &&
            !model.getParameters().contains(expression.name()) &&
            !modelHasObservable(model, expression.name())) {
            return "time()";
        }
        return expression.name();
    case ast::ExpressionKind::Unary: {
        const auto& op = expression.name();
        const auto arg = eventExpressionForBngsim(model, expression.args().front());
        if (op == "!") {
            return "(not(" + arg + "))";
        }
        return "(" + op + arg + ")";
    }
    case ast::ExpressionKind::Binary: {
        std::string op = expression.name();
        if (op == "**") op = "^";
        else if (op == "&&") op = "and";
        else if (op == "||") op = "or";
        return "(" + eventExpressionForBngsim(model, expression.args()[0]) +
               " " + op + " " +
               eventExpressionForBngsim(model, expression.args()[1]) + ")";
    }
    case ast::ExpressionKind::Function:
    case ast::ExpressionKind::ObservableRef: {
        const auto& name = expression.name();
        const auto lower = toLowerCopy(name);
        if (expression.args().empty() &&
            (lower == "time" || lower == "t") &&
            !modelHasObservable(model, name)) {
            return "time()";
        }
        if (expression.args().empty() && modelHasObservable(model, name)) {
            return name;
        }
        std::ostringstream result;
        result << lower << "(";
        for (std::size_t index = 0; index < expression.args().size(); ++index) {
            if (index != 0) result << ", ";
            result << eventExpressionForBngsim(model, expression.args()[index]);
        }
        result << ")";
        return result.str();
    }
    case ast::ExpressionKind::TableFunction:
        break;
    }
    throw std::logic_error("Invalid event expression reached BNGsim conversion after capability check");
}

std::string expressionForBngsim(const ast::Model& model,
                                const ast::Expression& expression,
                                const std::string& owner,
                                const std::filesystem::path& sourcePath,
                                bngsim::ModelBuilder& builder,
                                std::size_t& tableIndex) {
    switch (expression.kind()) {
    case ast::ExpressionKind::Number:
        return expression.toString();
    case ast::ExpressionKind::Identifier:
        if (expression.name() == "t" &&
            !model.getParameters().contains("t") &&
            !modelHasObservable(model, "t") &&
            !modelHasZeroArgFunction(model, "t")) {
            return "time";
        }
        return expression.toString();
    case ast::ExpressionKind::Unary:
        return "(" + expression.name() +
               expressionForBngsim(model, expression.args().front(), owner, sourcePath, builder, tableIndex) + ")";
    case ast::ExpressionKind::Binary:
        return "(" + expressionForBngsim(model, expression.args()[0], owner, sourcePath, builder, tableIndex) +
               " " + expression.name() + " " +
               expressionForBngsim(model, expression.args()[1], owner, sourcePath, builder, tableIndex) + ")";
    case ast::ExpressionKind::Function:
    case ast::ExpressionKind::ObservableRef: {
        if (expression.args().empty() &&
            (expression.name() == "time" || expression.name() == "t") &&
            !modelHasZeroArgFunction(model, expression.name()) &&
            !modelHasObservable(model, expression.name())) {
            return "time";
        }
        if (expression.args().empty() && modelHasObservable(model, expression.name())) {
            return expression.name();
        }
        std::ostringstream result;
        result << expression.name() << "(";
        for (std::size_t index = 0; index < expression.args().size(); ++index) {
            if (index != 0) result << ", ";
            result << expressionForBngsim(model, expression.args()[index], owner, sourcePath, builder, tableIndex);
        }
        result << ")";
        return result.str();
    }
    case ast::ExpressionKind::TableFunction: {
        const std::string counter = bngsimTableCounterName(model, expression.args().front());
        const std::string syntheticName =
            owner + "__tfun" + std::to_string(tableIndex++);
        if (!expression.tableFilePath().empty()) {
            const std::string resolvedPath =
                resolveBngsimTablePath(expression.tableFilePath(), sourcePath);
            builder.add_table_function_spec(
                syntheticName,
                resolvedPath,
                counter,
                expression.tableMethod());
        } else {
            builder.add_inline_table_function_spec(
                syntheticName,
                expression.tableXValues(),
                expression.tableYValues(),
                counter,
                expression.tableMethod());
        }
        return "tfun_" + syntheticName + "()";
    }
    }
    throw std::logic_error("Invalid expression reached BNGsim conversion after capability check");
}

} // namespace

std::unique_ptr<bngsim::NetworkModel> buildBngsimNetwork(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const BngsimLoweringOptions& options) {
    requireNoDelayedSemantics(model, network, "the BNGsim adapter");
    const auto check = checkBngsimLowering(model, network, options);
    if (!check.supported) {
        throw std::runtime_error(check.blockers.empty()
                                     ? "BNGsim adapter rejected model: unsupported lowering"
                                     : check.blockers.front());
    }

    auto& mutableModel = const_cast<ast::Model&>(model);
    std::unordered_map<std::string, std::vector<std::pair<int, double>>> compiledObservables;
    for (const auto& observable : model.getObservables()) {
        compiledObservables.emplace(
            observable.getName(),
            compileBngsimObservableEntries(mutableModel, network, observable));
    }

    std::vector<std::string> eventBlockers;
    const auto eventPlan = analyzeBngsimEvents(
        model, network, compiledObservables, eventBlockers);
    if (!eventBlockers.empty()) {
        throw std::runtime_error(eventBlockers.front());
    }

    bngsim::ModelBuilder builder;

    for (const auto& parameter : model.getParameters().all()) {
        if (eventPlan.promotedParameters.count(parameter.getName()) > 0) {
            continue;
        }
        const double value = model.getParameters().evaluate(parameter.getName());
        builder.add_parameter(parameter.getName(), value);
    }

    const bool hasCompartments = !model.getCompartments().empty();
    for (const auto& species : network.species.all()) {
        const std::string speciesName = hasCompartments
            ? species.getSpeciesGraph().toStringForDedup()
            : species.getSpeciesGraph().toString();
        builder.add_species(
            speciesName,
            species.getAmount(),
            species.isConstant());
    }

    if (!model.getObservables().empty()) {
        for (const auto& observable : model.getObservables()) {
            builder.add_observable(
                observable.getName(),
                compiledObservables.at(observable.getName()));
        }
    }

    // Promote event-assigned static parameters to unreported continuous species
    // with matching helper observables appended after real model observables.
    std::unordered_map<std::string, int> promotedParamSpeciesIndex;
    for (const auto& paramName : eventPlan.promotedParameterOrder) {
        const double initVal = model.getParameters().evaluate(paramName);
        const int spIdx = builder.add_species(
            paramName, initVal, /*fixed=*/false, /*volume_factor=*/1.0,
            /*amount_valued=*/false, /*reported=*/false);
        builder.set_species_continuous(spIdx);
        builder.add_observable(paramName, {{spIdx, 1.0}});
        promotedParamSpeciesIndex.emplace(paramName, spIdx);
    }

    std::unordered_set<std::string> usedFunctionNames;
    for (const auto& function : model.getFunctions()) {
        usedFunctionNames.insert(function.getName());
        std::size_t tableIndex = 0;
        builder.add_function(
            function.getName(),
            expressionForBngsim(
                model, function.getExpression(), function.getName(),
                options.sourcePath, builder, tableIndex));
    }

    std::unordered_map<std::string, std::string> promotedParamRateFunctions;
    for (std::size_t index = 0; index < network.reactions.size(); ++index) {
        const auto& reaction = network.reactions.all()[index];
        const auto context = bngsimReactionContext(index, reaction);
        const auto reactants = checkedBngsimIndices(
            reaction.getReactants(), network.species.size(), context);
        const auto products = checkedBngsimIndices(
            reaction.getProducts(), network.species.size(), context);
        const auto rate = resolveBngsimRateReference(model, reaction, index, options);
        const double effectiveStatFactor =
            computeEffectiveBngsimStatFactor(model, network, reaction, context);

        bngsim::RateLawType type;
        std::string rateName = rate.name;
        if (rate.kind == BngsimRateKind::Parameter) {
            if (promotedParamSpeciesIndex.count(rate.name) > 0) {
                type = bngsim::RateLawType::Functional;
                auto fnIt = promotedParamRateFunctions.find(rate.name);
                if (fnIt == promotedParamRateFunctions.end()) {
                    const auto synthName = makeUniqueSyntheticFunctionName(
                        model, usedFunctionNames, "__bng3_eparam_" + rate.name);
                    builder.add_function(synthName, rate.name);
                    fnIt = promotedParamRateFunctions.emplace(rate.name, synthName).first;
                }
                rateName = fnIt->second;
            } else {
                type = bngsim::RateLawType::Elementary;
            }
        } else if (rate.kind == BngsimRateKind::Function) {
            type = bngsim::RateLawType::Functional;
        } else {
            type = bngsim::RateLawType::Functional;
            rateName = makeUniqueSyntheticFunctionName(model, usedFunctionNames, index);
            std::size_t tableIndex = 0;
            builder.add_function(
                rateName,
                expressionForBngsim(
                    model, *rate.expression, rateName,
                    options.sourcePath, builder, tableIndex));
        }

        builder.add_reaction(
            reactants,
            products,
            type,
            rateName,
            effectiveStatFactor,
            true);
    }

    for (const auto& ev : eventPlan.events) {
        const std::string triggerExpr =
            eventExpressionForBngsim(model, ev.expandedTrigger);

        double constDelay = 0.0;
        std::string delayExpr;
        if (ev.expandedDelay.has_value()) {
            if (expressionReferencesDynamicOrPromoted(
                    model, *ev.expandedDelay, eventPlan.promotedParameters)) {
                delayExpr = eventExpressionForBngsim(model, *ev.expandedDelay);
            } else {
                constDelay = ev.expandedDelay->evaluate([&](const std::string& name) {
                    return model.getParameters().evaluate(name);
                });
            }
        }

        int constPriority = 0;
        std::string priorityExpr;
        if (ev.expandedPriority.has_value()) {
            if (expressionReferencesDynamicOrPromoted(
                    model, *ev.expandedPriority, eventPlan.promotedParameters)) {
                priorityExpr = eventExpressionForBngsim(model, *ev.expandedPriority);
            } else {
                const double val = ev.expandedPriority->evaluate([&](const std::string& name) {
                    return model.getParameters().evaluate(name);
                });
                const double rounded = std::round(val);
                if (std::isfinite(val) &&
                    std::abs(val - rounded) == 0.0 &&
                    rounded >= static_cast<double>(std::numeric_limits<int>::min()) &&
                    rounded <= static_cast<double>(std::numeric_limits<int>::max())) {
                    constPriority = static_cast<int>(rounded);
                } else {
                    priorityExpr = eventExpressionForBngsim(model, *ev.expandedPriority);
                }
            }
        }

        std::vector<std::pair<int, std::string>> assignments;
        assignments.reserve(ev.assignments.size());
        for (const auto& assign : ev.assignments) {
            const int targetSpeciesIdx = assign.isSpecies
                ? assign.speciesIndex
                : promotedParamSpeciesIndex.at(assign.parameterName);
            assignments.emplace_back(
                targetSpeciesIdx,
                eventExpressionForBngsim(model, assign.expandedValue));
        }

        builder.add_event(
            ev.id,
            triggerExpr,
            assignments,
            constDelay,
            constPriority,
            ev.persistent,
            ev.initialValue,
            ev.useValuesFromTriggerTime,
            delayExpr,
            priorityExpr);
    }

    return std::make_unique<bngsim::NetworkModel>(builder.build());
}


#endif // BNG3_HAS_BNGSIM_ADAPTER

} // namespace bng::engine
