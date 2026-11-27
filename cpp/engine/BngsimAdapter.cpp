#include "BngsimAdapter.hpp"
#include "DelayedSemanticsGuard.hpp"
#include "FiniteBackend.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <limits>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

#ifdef BNG3_HAS_BNGSIM_ADAPTER
#include <bngsim/model_builder.hpp>
#endif

#include "ast/Model.hpp"
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

BngsimRateReference resolveBngsimRateReference(
    const ast::Model& model,
    const ast::Rxn& reaction,
    std::size_t index,
    const BngsimLoweringOptions& options) {
    const auto context = bngsimReactionContext(index, reaction);
    if (reaction.isTotalRate()) {
        throw std::runtime_error(
            "BNGsim adapter rejected " + context +
            ": TotalRate reactions require a total-rate bridge");
    }
    if (reaction.isAbsoluteFlux()) {
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

    if (model.getEventFormatVersion().has_value()) {
        reject("BNGsim adapter rejected model: native events are unsupported");
    }
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
    if (!model.getCompartments().empty()) {
        reject("BNGsim adapter rejected model: compartments require a volume-aware bridge");
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

    for (const auto& observable : model.getObservables()) {
        try {
            (void)compileBngsimObservableEntries(mutableModel, network, observable);
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
    std::size_t reactionIndex) {
    std::string candidate = "__bng3_rate_" + std::to_string(reactionIndex);
    while (usedNames.count(candidate) > 0 ||
           model.getParameters().contains(candidate) ||
           modelHasObservable(model, candidate) ||
           modelHasZeroArgFunction(model, candidate)) {
        candidate.push_back('_');
    }
    usedNames.insert(candidate);
    return candidate;
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

    bngsim::ModelBuilder builder;

    for (const auto& parameter : model.getParameters().all()) {
        const double value = model.getParameters().evaluate(parameter.getName());
        builder.add_parameter(parameter.getName(), value);
    }

    for (const auto& species : network.species.all()) {
        builder.add_species(
            species.getSpeciesGraph().toString(),
            species.getAmount(),
            species.isConstant());
    }

    if (!model.getObservables().empty()) {
        auto& mutableModel = const_cast<ast::Model&>(model);
        for (const auto& observable : model.getObservables()) {
            builder.add_observable(
                observable.getName(),
                compileBngsimObservableEntries(mutableModel, network, observable));
        }
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

    for (std::size_t index = 0; index < network.reactions.size(); ++index) {
        const auto& reaction = network.reactions.all()[index];
        const auto context = bngsimReactionContext(index, reaction);
        const auto reactants = checkedBngsimIndices(
            reaction.getReactants(), network.species.size(), context);
        const auto products = checkedBngsimIndices(
            reaction.getProducts(), network.species.size(), context);
        const auto rate = resolveBngsimRateReference(model, reaction, index, options);

        bngsim::RateLawType type;
        std::string rateName = rate.name;
        if (rate.kind == BngsimRateKind::Parameter) {
            type = bngsim::RateLawType::Elementary;
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
            reaction.getFactor(),
            true);
    }

    return std::make_unique<bngsim::NetworkModel>(builder.build());
}


#endif // BNG3_HAS_BNGSIM_ADAPTER

} // namespace bng::engine
