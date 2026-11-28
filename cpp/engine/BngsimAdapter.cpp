#include "BngsimAdapter.hpp"
#include "DelayedSemanticsGuard.hpp"
#include "FiniteBackend.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <limits>
#include <map>
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
#include "compile/energy/DrivenEnergy.hpp"
#include "io/NetWriter.hpp"
#include "parser/antlr_compat.hpp"
#include "antlr4-runtime.h"
#include "BNGLexer.h"
#include "BNGParser.h"
#include "core/List.hpp"
#include "core/PatternMatching.hpp"
#include "core/Ullmann.hpp"
#include "parser/BNGAstVisitor.hpp"
#include "parser/PatternGraphBuilder.hpp"

namespace bng::engine {

namespace {

enum class BngsimRateKind {
    Parameter,
    Function,
    SyntheticExpression,
    ArrheniusConstant,
    Sat,
    Hill,
    MichaelisMentenNative,
    MichaelisMentenFunctional,
    AbsoluteFlux,
};

struct BngsimRateReference {
    BngsimRateKind kind = BngsimRateKind::Parameter;
    std::string name;
    std::optional<ast::Expression> expression;
    double numericRate = 0.0;
    std::vector<ast::Expression> lawArgs;
    std::string mmKcatParam;
    std::string mmKmParam;
    bool applyStatFactorToAbsoluteFlux = false;
    bool isContinuousDifferentialChannel = false;
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
    std::vector<std::string>& blockers,
    bool allowLogicalAndCompare = false) {
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
        if (expression.name() == "+" || expression.name() == "-") {
            collectInlineRateExpressionBlockers(
                model, expression.args().front(), sourcePath, context, blockers, false);
            return;
        }
        if (allowLogicalAndCompare && expression.name() == "!") {
            collectInlineRateExpressionBlockers(
                model, expression.args().front(), sourcePath, context, blockers, true);
            return;
        }
        blockers.push_back(
            "BNGsim adapter rejected " + context + ": unsupported unary operator '" + expression.name() + "' in rate expression");
        return;
    case ast::ExpressionKind::Binary: {
        if (expression.args().size() != 2) {
            blockers.push_back("BNGsim adapter rejected malformed binary expression");
            return;
        }
        const auto& op = expression.name();
        if (op == "+" || op == "-" || op == "*" || op == "/" || op == "^" || op == "**") {
            collectInlineRateExpressionBlockers(
                model, expression.args()[0], sourcePath, context, blockers, false);
            collectInlineRateExpressionBlockers(
                model, expression.args()[1], sourcePath, context, blockers, false);
            return;
        }
        if (allowLogicalAndCompare && (op == "&&" || op == "||")) {
            collectInlineRateExpressionBlockers(
                model, expression.args()[0], sourcePath, context, blockers, true);
            collectInlineRateExpressionBlockers(
                model, expression.args()[1], sourcePath, context, blockers, true);
            return;
        }
        if (allowLogicalAndCompare &&
            (op == "<" || op == "<=" || op == ">" || op == ">=" ||
             op == "==" || op == "!=")) {
            collectInlineRateExpressionBlockers(
                model, expression.args()[0], sourcePath, context, blockers, false);
            collectInlineRateExpressionBlockers(
                model, expression.args()[1], sourcePath, context, blockers, false);
            return;
        }
        blockers.push_back(
            "BNGsim adapter rejected " + context + ": unsupported binary operator '" + op + "' in rate expression");
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
        if (arity == 0 &&
            (lower == "time" || lower == "t" ||
             modelHasZeroArgFunction(model, name) ||
             modelHasObservable(model, name))) {
            return;
        }
        if (arity == 3 && lower == "if") {
            collectInlineRateExpressionBlockers(
                model, expression.args()[0], sourcePath, context, blockers, true);
            collectInlineRateExpressionBlockers(
                model, expression.args()[1], sourcePath, context, blockers, false);
            collectInlineRateExpressionBlockers(
                model, expression.args()[2], sourcePath, context, blockers, false);
            return;
        }
        static const std::unordered_set<std::string> kUnaryBuiltins = {
            "abs", "acos", "asin", "atan", "ceil", "cos", "cosh", "exp",
            "floor", "ln", "log", "log10", "log2", "rint", "sign", "sin",
            "sinh", "sqrt", "tan", "tanh"
        };
        const bool supportedBuiltin =
            (arity == 1 && kUnaryBuiltins.count(lower) > 0) ||
            (arity == 2 && (lower == "min" || lower == "max")) ||
            (arity == 3 && lower == "mratio");
        if (!supportedBuiltin) {
            blockers.push_back(
                "BNGsim adapter rejected " + context + ": unsupported function '" + name + "' in rate expression");
            return;
        }
        for (const auto& argument : expression.args()) {
            collectInlineRateExpressionBlockers(
                model, argument, sourcePath, context, blockers, false);
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

bool bngsimMapIsExactAutomorphism(const BNGcore::PatternGraph& pattern,
                                  const BNGcore::Map& map) {
    std::unordered_set<const BNGcore::Node*> mappedNodes;
    for (auto node = pattern.begin(); node != pattern.end(); ++node) {
        const auto* mapped = map.mapf(*node);
        if (mapped == nullptr ||
            !((*node)->get_type() == mapped->get_type()) ||
            (*node)->get_state().get_BNG2_string() !=
                mapped->get_state().get_BNG2_string() ||
            (*node)->get_compartment() != mapped->get_compartment() ||
            (*node)->in_degree() != mapped->in_degree() ||
            (*node)->out_degree() != mapped->out_degree() ||
            !mappedNodes.insert(mapped).second) {
            return false;
        }
        std::unordered_map<const BNGcore::Node*, std::size_t> expectedEdges;
        for (auto edge = (*node)->edges_out_begin();
             edge != (*node)->edges_out_end(); ++edge) {
            const auto* mappedTarget = map.mapf(*edge);
            if (mappedTarget == nullptr) return false;
            ++expectedEdges[mappedTarget];
        }
        std::unordered_map<const BNGcore::Node*, std::size_t> actualEdges;
        for (auto edge = mapped->edges_out_begin();
             edge != mapped->edges_out_end(); ++edge) {
            ++actualEdges[*edge];
        }
        if (expectedEdges != actualEdges) return false;
    }
    return mappedNodes.size() == pattern.size();
}

std::size_t bngsimCountExactPatternAutomorphisms(const BNGcore::PatternGraph& pattern) {
    if (pattern.empty()) return 0;
    BNGcore::UllmannSGIso matcher(pattern, pattern);
    BNGcore::List<BNGcore::Map> maps;
    matcher.find_maps(maps);
    std::size_t count = 0;
    for (auto it = maps.begin(); it != maps.end(); ++it) {
        if (bngsimMapIsExactAutomorphism(pattern, *it)) ++count;
    }
    return count;
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

    const auto& options = model.getOptions();
    const auto readCountUnique = [&options](const std::string& key) -> bool {
        const auto found = options.find(key);
        if (found == options.end() || found->second == "CountAll") return false;
        if (found->second == "CountUnique") return true;
        throw std::runtime_error("unsupported " + key + " value '" + found->second +
                                 "' (expected 'CountUnique' or 'CountAll')");
    };
    const bool moleculesCountUnique = readCountUnique("MoleculesObservables");
    const bool speciesCountUnique = readCountUnique("SpeciesObservables");

    struct CompiledBngsimPattern {
        BNGcore::PatternGraph pattern;
        std::string compartment;
        bool hasMoleculeCompartment = false;
        std::string quantifier;
        int quantifierThreshold = 0;
        bool hasQuantifier = false;
        std::size_t automorphisms = 1;
    };

    std::vector<CompiledBngsimPattern> compiledPatterns;
    compiledPatterns.reserve(observable.getPatterns().size());
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
        bool hasMoleculeCompartment = false;
        for (auto it = pattern.begin(); it != pattern.end(); ++it) {
            if (!(*it)->get_compartment().empty()) {
                hasMoleculeCompartment = true;
                break;
            }
        }
        std::size_t automorphisms = 1;
        if (observable.getType() == "Molecules" && moleculesCountUnique) {
            automorphisms = bngsimCountExactPatternAutomorphisms(pattern);
            if (automorphisms == 0) {
                throw std::runtime_error(
                    "observable '" + observable.getName() +
                    "': pattern has no self-embedding, so its automorphism "
                    "count cannot be established for CountUnique");
            }
        }
        compiledPatterns.push_back(CompiledBngsimPattern{
            std::move(pattern), patternCompartment, hasMoleculeCompartment,
            std::move(quantifier), quantifierThreshold, hasQuantifier,
            automorphisms});
    }

    std::vector<std::pair<int, double>> entries;
    for (std::size_t speciesIndex = 0; speciesIndex < network.species.size(); ++speciesIndex) {
        std::size_t weight = 0;
        const auto& targetSpecies = network.species.get(speciesIndex);
        const auto& targetGraph = targetSpecies.getSpeciesGraph().getGraph();

        for (const auto& cp : compiledPatterns) {
            bool compartmentMatches = true;
            if (!cp.compartment.empty() && !cp.hasMoleculeCompartment &&
                targetSpecies.getCompartment() != cp.compartment) {
                compartmentMatches = false;
            }

            const std::size_t matchCount = compartmentMatches
                ? bng::core::countPatternMatches(cp.pattern, targetGraph)
                : 0;

            if (observable.getType() == "Species") {
                bool matches = false;
                if (cp.hasQuantifier) {
                    const int count = static_cast<int>(matchCount);
                    if (cp.quantifier == ">") matches = count > cp.quantifierThreshold;
                    else if (cp.quantifier == "<") matches = count < cp.quantifierThreshold;
                    else if (cp.quantifier == ">=") matches = count >= cp.quantifierThreshold;
                    else if (cp.quantifier == "<=") matches = count <= cp.quantifierThreshold;
                    else if (cp.quantifier == "==") matches = count == cp.quantifierThreshold;
                    else if (cp.quantifier == "!=") matches = count != cp.quantifierThreshold;
                } else {
                    matches = matchCount > 0;
                }
                if (matches) {
                    ++weight;
                }
                if (speciesCountUnique && (cp.hasQuantifier || matches)) {
                    break;
                }
            } else {
                if (moleculesCountUnique) {
                    if (matchCount % cp.automorphisms != 0) {
                        throw std::runtime_error(
                            "observable '" + observable.getName() + "': match count " +
                            std::to_string(matchCount) + " is not divisible by the pattern's "
                            "automorphism count " + std::to_string(cp.automorphisms) +
                            "; CountUnique cannot produce an exact value");
                    }
                    weight += matchCount / cp.automorphisms;
                } else {
                    weight += matchCount;
                }
            }
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
    const std::filesystem::path& sourcePath,
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
                model, expression.args().front(), sourcePath, context, false, blockers);
            return;
        }
        if (allowLogicalAndCompare && op == "!") {
            collectEventExpressionBlockers(
                model, expression.args().front(), sourcePath, context, true, blockers);
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
                model, expression.args()[0], sourcePath, context, false, blockers);
            collectEventExpressionBlockers(
                model, expression.args()[1], sourcePath, context, false, blockers);
            return;
        }
        if (allowLogicalAndCompare && (op == "&&" || op == "||")) {
            collectEventExpressionBlockers(
                model, expression.args()[0], sourcePath, context, true, blockers);
            collectEventExpressionBlockers(
                model, expression.args()[1], sourcePath, context, true, blockers);
            return;
        }
        if (allowLogicalAndCompare &&
            (op == "<" || op == "<=" || op == ">" || op == ">=" ||
             op == "==" || op == "!=")) {
            collectEventExpressionBlockers(
                model, expression.args()[0], sourcePath, context, false, blockers);
            collectEventExpressionBlockers(
                model, expression.args()[1], sourcePath, context, false, blockers);
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
            collectEventExpressionBlockers(model, expression.args()[0], sourcePath, context, true, blockers);
            collectEventExpressionBlockers(model, expression.args()[1], sourcePath, context, false, blockers);
            collectEventExpressionBlockers(model, expression.args()[2], sourcePath, context, false, blockers);
            return;
        }
        static const std::unordered_set<std::string> kUnaryBuiltins = {
            "abs", "acos", "asin", "atan", "ceil", "cos", "cosh", "exp",
            "floor", "ln", "log", "log10", "log2", "rint", "sign", "sin",
            "sinh", "sqrt", "tan", "tanh"
        };
        const bool supportedBuiltin =
            (arity == 1 && kUnaryBuiltins.count(lower) > 0) ||
            (arity == 2 && (lower == "min" || lower == "max")) ||
            (arity == 3 && lower == "mratio");
        if (!supportedBuiltin) {
            blockers.push_back(
                "BNGsim adapter rejected " + context +
                ": unsupported function '" + name + "' in event expression");
            return;
        }
        for (const auto& argument : expression.args()) {
            collectEventExpressionBlockers(model, argument, sourcePath, context, false, blockers);
        }
        return;
    }
    case ast::ExpressionKind::TableFunction:
        collectExpressionBlockers(model, expression, sourcePath, blockers);
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
    std::vector<std::string> derivedParameterOrder;
    std::unordered_set<std::string> derivedParameters;
    std::unordered_map<std::string, ast::Expression> derivedParameterExpressions;
};

CompiledBngsimEventPlan analyzeBngsimEvents(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const std::unordered_map<std::string, std::vector<std::pair<int, double>>>& compiledObservables,
    const std::filesystem::path& sourcePath,
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
            model, compiled.expandedTrigger, sourcePath, ctx + " trigger", true, blockers);

        if (ev.delay.has_value()) {
            compiled.expandedDelay = evaluator.expandFunctions(*ev.delay);
            collectEventExpressionBlockers(
                model, *compiled.expandedDelay, sourcePath, ctx + " delay", false, blockers);
        }
        if (ev.priority.has_value()) {
            compiled.expandedPriority = evaluator.expandFunctions(*ev.priority);
            collectEventExpressionBlockers(
                model, *compiled.expandedPriority, sourcePath, ctx + " priority", false, blockers);
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
                sourcePath,
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

    // Identify derived parameters that depend (directly or transitively) on any
    // event-assigned parameter and topologically order them so BNGsim evaluates
    // them dynamically as functions in dependency order.
    if (!plan.promotedParameters.empty()) {
        std::unordered_set<std::string> allDynamicParams = plan.promotedParameters;
        std::unordered_map<std::string, ast::Expression> expandedParamExprs;
        bool added = true;
        while (added) {
            added = false;
            for (const auto& parameter : model.getParameters().all()) {
                const auto& pname = parameter.getName();
                if (allDynamicParams.count(pname) > 0) continue;
                ast::Expression expr = parameter.getExpression();
                try {
                    expr = evaluator.expandFunctions(expr);
                } catch (...) {
                    // Keep original expression if expansion fails; validated below.
                }
                const auto deps = expr.getDependencies();
                const bool dependsOnDynamic = std::any_of(
                    deps.begin(), deps.end(),
                    [&](const std::string& dep) { return allDynamicParams.count(dep) > 0; });
                if (dependsOnDynamic) {
                    allDynamicParams.insert(pname);
                    plan.derivedParameters.insert(pname);
                    expandedParamExprs.emplace(pname, std::move(expr));
                    added = true;
                }
            }
        }

        // Topological sort of derivedParameters so dependencies precede dependents.
        std::unordered_map<std::string, int> visitState; // 0=unvisited, 1=visiting, 2=done
        bool foundCycle = false;
        std::function<void(const std::string&)> topoVisit = [&](const std::string& name) {
            const int st = visitState[name];
            if (st == 2 || foundCycle) return;
            if (st == 1) {
                foundCycle = true;
                return;
            }
            visitState[name] = 1;
            const auto exprIt = expandedParamExprs.find(name);
            if (exprIt != expandedParamExprs.end()) {
                for (const auto& dep : exprIt->second.getDependencies()) {
                    if (plan.derivedParameters.count(dep) > 0) {
                        topoVisit(dep);
                    }
                }
            }
            visitState[name] = 2;
            plan.derivedParameterOrder.push_back(name);
        };
        for (const auto& parameter : model.getParameters().all()) {
            const auto& pname = parameter.getName();
            if (plan.derivedParameters.count(pname) > 0) {
                topoVisit(pname);
            }
        }
        if (foundCycle) {
            blockers.push_back(
                "BNGsim adapter rejected event: cyclic derived parameter dependency");
        } else {
            for (const auto& pname : plan.derivedParameterOrder) {
                if (modelHasZeroArgFunction(model, pname) ||
                    modelHasObservable(model, pname) ||
                    speciesNames.count(pname) > 0) {
                    blockers.push_back(
                        "BNGsim adapter rejected event: derived parameter '" + pname +
                        "' collides with an observable, species, or function name");
                    continue;
                }
                const auto& expr = expandedParamExprs.at(pname);
                collectInlineRateExpressionBlockers(
                    model, expr, sourcePath, "derived parameter '" + pname + "'", blockers, false);
                plan.derivedParameterExpressions.emplace(pname, expr);
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

std::string trimWhitespace(std::string value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return {};
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

struct ParsedSpecialRateLaw {
    std::string keyword; // lowercase: "sat", "mm", "hill", "arrhenius"
    std::vector<ast::Expression> args;
};

std::optional<ParsedSpecialRateLaw> parseSpecialRateLaw(
    const ast::Rxn& reaction,
    std::string& parseError) {
    static const std::unordered_set<std::string> kKeywords = {
        "sat", "mm", "hill", "arrhenius"
    };

    if (reaction.getRateExpression().has_value()) {
        const auto& expr = *reaction.getRateExpression();
        if (expr.kind() == ast::ExpressionKind::Function) {
            const auto lower = toLowerCopy(expr.name());
            if (kKeywords.count(lower) > 0) {
                return ParsedSpecialRateLaw{lower, expr.args()};
            }
        }
    }

    const std::string trimmed = trimWhitespace(reaction.getRateLaw());
    if (trimmed.empty()) return std::nullopt;
    const std::string lower = toLowerCopy(trimmed);

    std::string matchedKw;
    for (const auto& kw : kKeywords) {
        if (lower.rfind(kw, 0) != 0) continue;
        if (lower.size() == kw.size()) continue; // bare identifier handled as param/func
        const char nextC = lower[kw.size()];
        if (nextC == '(' || nextC == ' ' || nextC == '\t') {
            matchedKw = kw;
            break;
        }
    }
    if (matchedKw.empty()) return std::nullopt;

    const std::string rest = trimWhitespace(trimmed.substr(matchedKw.size()));
    if (rest.empty()) return std::nullopt;

    if (rest.front() == '(') {
        try {
            const auto parsed = parser::parseExpression(trimmed);
            if (parsed.kind() == ast::ExpressionKind::Function &&
                toLowerCopy(parsed.name()) == matchedKw) {
                return ParsedSpecialRateLaw{matchedKw, parsed.args()};
            }
        } catch (const std::exception& err) {
            parseError = err.what();
            return std::nullopt;
        }
        parseError = "malformed parenthesized rate law '" + trimmed + "'";
        return std::nullopt;
    }

    // Space-separated .net form: e.g. "Sat kcat Km", "MM kcat Km", "Hill Vmax Kh n"
    std::vector<ast::Expression> args;
    std::istringstream iss(rest);
    std::string tok;
    while (iss >> tok) {
        try {
            args.push_back(parser::parseExpression(tok));
        } catch (const std::exception& err) {
            parseError = err.what();
            return std::nullopt;
        }
    }
    if (args.empty()) return std::nullopt;
    return ParsedSpecialRateLaw{matchedKw, std::move(args)};
}

bool isContinuousDifferentialOrigin(const ast::Model& model, const ast::Rxn& reaction) {
    const auto& origin = reaction.getOriginRuleName();
    if (origin.rfind("__rate_rule", 0) == 0) return true;
    const auto resolved = compile::resolveOriginRule(origin).name;
    if (resolved.rfind("__rate_rule", 0) == 0) return true;
    for (const auto& rule : model.getReactionRules()) {
        if (rule.getRuleName() == origin || rule.getRuleName() == resolved) {
            if (rule.getLabel().rfind("__rate_rule", 0) == 0 ||
                rule.getRuleName().rfind("__rate_rule", 0) == 0) {
                return true;
            }
        }
    }
    return false;
}

std::unordered_map<std::size_t, double> analyzeBngsimEnergyAndArrhenius(
    const ast::Model& model,
    const GeneratedNetwork& network,
    const CompiledBngsimEventPlan& eventPlan,
    std::vector<std::string>& blockers) {
    std::unordered_map<std::size_t, double> perReactionArrheniusRates;

    bool hasDrivingWork = false;
    for (const auto& rule : model.getReactionRules()) {
        if (rule.hasDrivingWork()) {
            hasDrivingWork = true;
            break;
        }
    }
    bool hasArrheniusReaction = false;
    for (std::size_t idx = 0; idx < network.reactions.size(); ++idx) {
        const auto& rxn = network.reactions.all()[idx];
        std::string parseError;
        const auto parsed = parseSpecialRateLaw(rxn, parseError);
        if (parsed.has_value() && parsed->keyword == "arrhenius") {
            hasArrheniusReaction = true;
            break;
        }
    }

    const bool usesGeneralEnergy = !model.getBarrierPatterns().empty() || hasDrivingWork;
    const bool usesEnergyFeatures =
        !model.getEnergyPatterns().empty() || usesGeneralEnergy || hasArrheniusReaction;
    if (!usesEnergyFeatures) {
        return perReactionArrheniusRates;
    }

    if (usesGeneralEnergy && !compile::energy::generalEnergyEnabled()) {
        blockers.push_back(
            "BNGsim adapter rejected model: barrier patterns and driven_by() reservoir work "
            "require BNG_NFSIM_GENERAL_ENERGY=1");
        return perReactionArrheniusRates;
    }

    const auto checkStaticFinite = [&](const ast::Expression& expr, const std::string& label) -> bool {
        if (expressionReferencesDynamicOrPromoted(model, expr, eventPlan.promotedParameters)) {
            blockers.push_back(
                "BNGsim adapter rejected model: " + label + " must be statically evaluable");
            return false;
        }
        try {
            const double val = expr.evaluate([&](const std::string& name) {
                return model.getParameters().evaluate(name);
            });
            if (!std::isfinite(val)) {
                blockers.push_back(
                    "BNGsim adapter rejected model: " + label + " evaluates to a non-finite value");
                return false;
            }
        } catch (const std::exception& err) {
            blockers.push_back(
                "BNGsim adapter rejected model: " + label +
                " must be statically evaluable (" + err.what() + ")");
            return false;
        }
        return true;
    };

    const std::size_t blockersBefore = blockers.size();
    for (const auto& ep : model.getEnergyPatterns()) {
        (void)checkStaticFinite(ep.getExpression(), "energy pattern expression");
    }
    for (const auto& bp : model.getBarrierPatterns()) {
        if (!bp.hasExpression()) {
            blockers.push_back(
                "BNGsim adapter rejected model: barrier pattern has no transition-state energy expression");
            continue;
        }
        (void)checkStaticFinite(bp.expression(), "barrier pattern expression");
    }
    for (const auto& rule : model.getReactionRules()) {
        if (rule.hasDrivingWork()) {
            (void)checkStaticFinite(
                rule.drivingWorkExpression(), "driven_by() reservoir work expression");
        }
    }
    for (std::size_t idx = 0; idx < network.reactions.size(); ++idx) {
        const auto& rxn = network.reactions.all()[idx];
        std::string parseError;
        const auto parsed = parseSpecialRateLaw(rxn, parseError);
        if (!parsed.has_value() || parsed->keyword != "arrhenius") continue;
        const auto context = bngsimReactionContext(idx, rxn);
        if (parsed->args.size() != 2) {
            blockers.push_back(
                "BNGsim adapter rejected " + context +
                ": Arrhenius rate law requires exactly 2 arguments (phi, Ea)");
            continue;
        }
        (void)checkStaticFinite(parsed->args[0], context + " Arrhenius phi argument");
        (void)checkStaticFinite(parsed->args[1], context + " Arrhenius Ea argument");
    }
    if (blockers.size() != blockersBefore) {
        return perReactionArrheniusRates;
    }

    try {
        const auto derived = io::NetWriter::buildDerivedRateParams(model, network);
        for (const auto& [ruleName, info] : derived) {
            if (!info.isPerReactionArrhenius) continue;
            for (const auto& [rxnIdx, paramPair] : info.perReactionRates) {
                if (!std::isfinite(paramPair.second) || paramPair.second < 0.0) {
                    blockers.push_back(
                        "BNGsim adapter rejected reaction " + std::to_string(rxnIdx) +
                        ": computed Arrhenius energy rate is not finite and non-negative");
                    continue;
                }
                perReactionArrheniusRates[rxnIdx] = paramPair.second;
            }
        }
    } catch (const std::exception& err) {
        blockers.push_back(
            std::string("BNGsim adapter rejected model: eBNGL energy compilation failed: ") +
            err.what());
        return {};
    }

    for (std::size_t idx = 0; idx < network.reactions.size(); ++idx) {
        const auto& rxn = network.reactions.all()[idx];
        std::string parseError;
        const auto parsed = parseSpecialRateLaw(rxn, parseError);
        if (parsed.has_value() && parsed->keyword == "arrhenius" &&
            perReactionArrheniusRates.count(idx) == 0) {
            blockers.push_back(
                "BNGsim adapter rejected " + bngsimReactionContext(idx, rxn) +
                ": Arrhenius rate could not be lowered to a finite network constant");
        }
    }

    return perReactionArrheniusRates;
}

BngsimRateReference resolveBngsimRateReference(
    const ast::Model& model,
    const ast::Rxn& reaction,
    std::size_t index,
    const BngsimLoweringOptions& options,
    const CompiledBngsimEventPlan& eventPlan,
    const std::unordered_map<std::size_t, double>& perReactionArrheniusRates) {
    const auto context = bngsimReactionContext(index, reaction);

    const auto arrhIt = perReactionArrheniusRates.find(index);
    if (arrhIt != perReactionArrheniusRates.end()) {
        if (compile::isAbsoluteFluxReaction(model, reaction)) {
            throw std::runtime_error(
                "BNGsim adapter rejected " + context +
                ": Arrhenius rate law cannot be combined with absolute-flux semantics");
        }
        BngsimRateReference ref;
        ref.kind = BngsimRateKind::ArrheniusConstant;
        ref.numericRate = arrhIt->second;
        return ref;
    }

    const auto& rateLaw = reaction.getRateLaw();
    const auto normalized = normalizeRateLaw(rateLaw);

    if (compile::isAbsoluteFluxReaction(model, reaction)) {
        if (options.executionMode == BngsimExecutionMode::Psa) {
            throw std::runtime_error(
                "BNGsim adapter rejected " + context +
                ": absolute-flux reactions are unsupported in BNGsim PSA");
        }
        ast::Expression rateExpression;
        if (model.getParameters().contains(normalized)) {
            rateExpression = ast::Expression::identifier(normalized);
        } else if (modelHasZeroArgFunction(model, normalized)) {
            rateExpression = ast::Expression::function(normalized, {});
        } else if (reaction.getRateExpression().has_value()) {
            rateExpression = *reaction.getRateExpression();
        } else {
            try {
                rateExpression = parser::parseExpression(rateLaw);
            } catch (const std::exception&) {
                throw std::runtime_error(
                    "BNGsim adapter rejected " + context +
                    ": absolute-flux rate law '" + rateLaw +
                    "' could not be parsed as a BNGsim functional expression");
            }
        }
        std::vector<std::string> exprBlockers;
        collectInlineRateExpressionBlockers(
            model, rateExpression, options.sourcePath, context, exprBlockers, false);
        if (!exprBlockers.empty()) {
            throw std::runtime_error(exprBlockers.front());
        }
        BngsimRateReference ref;
        ref.kind = BngsimRateKind::AbsoluteFlux;
        ref.expression = std::move(rateExpression);
        ref.applyStatFactorToAbsoluteFlux = false;
        ref.isContinuousDifferentialChannel =
            isContinuousDifferentialOrigin(model, reaction) &&
            reaction.getReactants().empty() &&
            reaction.getProducts().size() == 1;
        return ref;
    }

    if (model.getParameters().contains(normalized)) {
        BngsimRateReference ref;
        ref.kind = BngsimRateKind::Parameter;
        ref.name = normalized;
        return ref;
    }
    for (const auto& function : model.getFunctions()) {
        if (function.getName() == normalized) {
            BngsimRateReference ref;
            ref.kind = BngsimRateKind::Function;
            ref.name = normalized;
            return ref;
        }
    }

    std::string specialParseError;
    if (auto special = parseSpecialRateLaw(reaction, specialParseError)) {
        if (special->keyword == "arrhenius") {
            throw std::runtime_error(
                "BNGsim adapter rejected " + context +
                ": Arrhenius rate could not be lowered to a finite network constant");
        }
        if (reaction.getReactants().empty()) {
            throw std::runtime_error(
                "BNGsim adapter rejected " + context + ": '" + special->keyword +
                "' rate law requires at least one reactant");
        }
        std::vector<std::string> argBlockers;
        for (const auto& arg : special->args) {
            collectInlineRateExpressionBlockers(
                model, arg, options.sourcePath, context, argBlockers, false);
        }
        if (!argBlockers.empty()) {
            throw std::runtime_error(argBlockers.front());
        }

        if (special->keyword == "sat") {
            if (special->args.size() != 2) {
                throw std::runtime_error(
                    "BNGsim adapter rejected " + context +
                    ": Sat rate law requires exactly 2 arguments (kcat, Km)");
            }
            BngsimRateReference ref;
            ref.kind = BngsimRateKind::Sat;
            ref.lawArgs = std::move(special->args);
            return ref;
        }
        if (special->keyword == "hill") {
            if (special->args.size() != 2 && special->args.size() != 3) {
                throw std::runtime_error(
                    "BNGsim adapter rejected " + context +
                    ": Hill rate law requires 2 or 3 arguments (Vmax, Kh[, n])");
            }
            if (special->args.size() == 2) {
                special->args.push_back(ast::Expression::number(1.0));
            }
            if (!expressionReferencesDynamicOrPromoted(
                    model, special->args[2], eventPlan.promotedParameters)) {
                double hillN = 0.0;
                try {
                    hillN = special->args[2].evaluate([&](const std::string& name) {
                        return model.getParameters().evaluate(name);
                    });
                } catch (const std::exception& err) {
                    throw std::runtime_error(
                        "BNGsim adapter rejected " + context +
                        ": could not evaluate Hill exponent (" + err.what() + ")");
                }
                if (!std::isfinite(hillN) || hillN <= 0.0) {
                    throw std::runtime_error(
                        "BNGsim adapter rejected " + context +
                        ": Hill exponent must be finite and positive");
                }
            }
            BngsimRateReference ref;
            ref.kind = BngsimRateKind::Hill;
            ref.lawArgs = std::move(special->args);
            return ref;
        }
        if (special->keyword == "mm") {
            if (special->args.size() == 2) {
                if (reaction.getReactants().size() == 1) {
                    BngsimRateReference ref;
                    ref.kind = BngsimRateKind::Sat;
                    ref.lawArgs = std::move(special->args);
                    return ref;
                }
                if (reaction.getReactants().size() == 2) {
                    if (reaction.getReactants()[0] == reaction.getReactants()[1]) {
                        throw std::runtime_error(
                            "BNGsim adapter rejected " + context +
                            ": MM(kcat,Km) with identical substrate and enzyme reactants is unsupported");
                    }
                    const auto isPlainStaticParam = [&](const ast::Expression& e, std::string& outName) {
                        if (e.kind() != ast::ExpressionKind::Identifier) return false;
                        const auto& n = e.name();
                        if (!model.getParameters().contains(n)) return false;
                        if (eventPlan.promotedParameters.count(n) > 0 ||
                            eventPlan.derivedParameters.count(n) > 0) {
                            return false;
                        }
                        if (model.getParameters().isTimeDependent(n)) return false;
                        outName = n;
                        return true;
                    };
                    std::string kcatName;
                    std::string kmName;
                    if (isPlainStaticParam(special->args[0], kcatName) &&
                        isPlainStaticParam(special->args[1], kmName)) {
                        BngsimRateReference ref;
                        ref.kind = BngsimRateKind::MichaelisMentenNative;
                        ref.mmKcatParam = std::move(kcatName);
                        ref.mmKmParam = std::move(kmName);
                        return ref;
                    }
                    BngsimRateReference ref;
                    ref.kind = BngsimRateKind::MichaelisMentenFunctional;
                    ref.lawArgs = std::move(special->args);
                    return ref;
                }
                throw std::runtime_error(
                    "BNGsim adapter rejected " + context +
                    ": MM(kcat, Km) requires 1 or 2 reactants");
            }
            if (special->args.size() == 3) {
                if (reaction.getReactants().size() != 1) {
                    throw std::runtime_error(
                        "BNGsim adapter rejected " + context +
                        ": 3-argument MM(Vmax, Km, S) with multiple reactants is unsupported");
                }
                if (options.executionMode == BngsimExecutionMode::Psa) {
                    throw std::runtime_error(
                        "BNGsim adapter rejected " + context +
                        ": 3-argument MM(Vmax, Km, S) is unsupported in BNGsim PSA");
                }
                // Vmax * S / (Km + S) with statistical/volume factor
                auto num = ast::Expression::binary("*", special->args[0], special->args[2]);
                auto den = ast::Expression::binary("+", special->args[1], special->args[2]);
                BngsimRateReference ref;
                ref.kind = BngsimRateKind::AbsoluteFlux;
                ref.expression = ast::Expression::binary("/", std::move(num), std::move(den));
                ref.applyStatFactorToAbsoluteFlux = true;
                return ref;
            }
            throw std::runtime_error(
                "BNGsim adapter rejected " + context +
                ": MM rate law requires 2 or 3 arguments");
        }
    } else if (!specialParseError.empty()) {
        throw std::runtime_error(
            "BNGsim adapter rejected " + context +
            ": could not parse rate law '" + rateLaw + "' (" + specialParseError + ")");
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
        model, rateExpression, options.sourcePath, context, exprBlockers, false);
    if (!exprBlockers.empty()) {
        throw std::runtime_error(exprBlockers.front());
    }
    BngsimRateReference ref;
    ref.kind = BngsimRateKind::SyntheticExpression;
    ref.expression = std::move(rateExpression);
    return ref;
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
        model, network, compiledObservables, options.sourcePath, check.blockers);

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

    const auto perReactionArrheniusRates = analyzeBngsimEnergyAndArrhenius(
        model, network, eventPlan, check.blockers);

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
            (void)resolveBngsimRateReference(
                model, reaction, index, options, eventPlan, perReactionArrheniusRates);
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
    const ast::Expression& expression,
    const CompiledBngsimEventPlan& eventPlan,
    const std::string& owner,
    const std::filesystem::path& sourcePath,
    bngsim::ModelBuilder& builder,
    std::size_t& tableIndex,
    std::unordered_set<std::string>& expandingDerived) {
    switch (expression.kind()) {
    case ast::ExpressionKind::Number:
        return formatDoubleExact(expression.numberValue());
    case ast::ExpressionKind::Identifier: {
        const auto& name = expression.name();
        if ((name == "time" || name == "t") &&
            !model.getParameters().contains(name) &&
            !modelHasObservable(model, name)) {
            return "time()";
        }
        const auto derivedIt = eventPlan.derivedParameterExpressions.find(name);
        if (derivedIt != eventPlan.derivedParameterExpressions.end() &&
            expandingDerived.insert(name).second) {
            const std::string expanded = "(" + eventExpressionForBngsim(
                model, derivedIt->second, eventPlan, owner, sourcePath,
                builder, tableIndex, expandingDerived) + ")";
            expandingDerived.erase(name);
            return expanded;
        }
        return name;
    }
    case ast::ExpressionKind::Unary: {
        const auto& op = expression.name();
        const auto arg = eventExpressionForBngsim(
            model, expression.args().front(), eventPlan, owner, sourcePath,
            builder, tableIndex, expandingDerived);
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
        return "(" + eventExpressionForBngsim(
                   model, expression.args()[0], eventPlan, owner, sourcePath,
                   builder, tableIndex, expandingDerived) +
               " " + op + " " +
               eventExpressionForBngsim(
                   model, expression.args()[1], eventPlan, owner, sourcePath,
                   builder, tableIndex, expandingDerived) + ")";
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
            result << eventExpressionForBngsim(
                model, expression.args()[index], eventPlan, owner, sourcePath,
                builder, tableIndex, expandingDerived);
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
            if (counter == "time") {
                for (double knot : expression.tableXValues()) {
                    if (std::isfinite(knot)) {
                        builder.add_discontinuity_trigger("time() >= " + formatDoubleExact(knot));
                    }
                }
            }
        }
        return "tfun_" + syntheticName + "()";
    }
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
        return formatDoubleExact(expression.numberValue());
    case ast::ExpressionKind::Identifier:
        if (expression.name() == "t" &&
            !model.getParameters().contains("t") &&
            !modelHasObservable(model, "t") &&
            !modelHasZeroArgFunction(model, "t")) {
            return "time";
        }
        return expression.toString();
    case ast::ExpressionKind::Unary: {
        const auto& op = expression.name();
        const auto arg = expressionForBngsim(
            model, expression.args().front(), owner, sourcePath, builder, tableIndex);
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
        return "(" + expressionForBngsim(model, expression.args()[0], owner, sourcePath, builder, tableIndex) +
               " " + op + " " +
               expressionForBngsim(model, expression.args()[1], owner, sourcePath, builder, tableIndex) + ")";
    }
    case ast::ExpressionKind::Function:
    case ast::ExpressionKind::ObservableRef: {
        const auto& name = expression.name();
        const auto lower = toLowerCopy(name);
        if (expression.args().empty() &&
            (lower == "time" || lower == "t") &&
            !modelHasZeroArgFunction(model, name) &&
            !modelHasObservable(model, name)) {
            return "time";
        }
        if (expression.args().empty() && modelHasObservable(model, name)) {
            return name;
        }
        std::ostringstream result;
        if (expression.args().empty() && modelHasZeroArgFunction(model, name)) {
            result << name << "()";
            return result.str();
        }
        result << lower << "(";
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
        model, network, compiledObservables, options.sourcePath, eventBlockers);
    if (!eventBlockers.empty()) {
        throw std::runtime_error(eventBlockers.front());
    }

    std::vector<std::string> energyBlockers;
    const auto perReactionArrheniusRates = analyzeBngsimEnergyAndArrhenius(
        model, network, eventPlan, energyBlockers);
    if (!energyBlockers.empty()) {
        throw std::runtime_error(energyBlockers.front());
    }

    bngsim::ModelBuilder builder;

    std::unordered_set<std::string> usedSyntheticNames;
    for (const auto& parameter : model.getParameters().all()) {
        const auto& pname = parameter.getName();
        usedSyntheticNames.insert(pname);
        if (eventPlan.promotedParameters.count(pname) > 0 ||
            eventPlan.derivedParameters.count(pname) > 0) {
            continue;
        }
        const double value = model.getParameters().evaluate(pname);
        builder.add_parameter(pname, value);
    }

    // Add synthetic per-reaction Arrhenius rate parameters up front so every
    // parameter is registered before species, functions, and reactions.
    std::unordered_map<std::size_t, std::string> arrheniusParamNames;
    for (std::size_t index = 0; index < network.reactions.size(); ++index) {
        const auto arrhIt = perReactionArrheniusRates.find(index);
        if (arrhIt == perReactionArrheniusRates.end()) continue;
        const std::string paramName = makeUniqueSyntheticFunctionName(
            model, usedSyntheticNames, "__bng3_arrh_" + std::to_string(index));
        builder.add_parameter(paramName, arrhIt->second);
        arrheniusParamNames.emplace(index, paramName);
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
            usedSyntheticNames.insert(observable.getName());
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

    // Register derived event-dependent parameters as BNGsim functions in
    // topological dependency order BEFORE user functions so downstream
    // functions and reactions observe updated values immediately.
    for (const auto& paramName : eventPlan.derivedParameterOrder) {
        std::size_t tableIndex = 0;
        const auto& expr = eventPlan.derivedParameterExpressions.at(paramName);
        builder.add_function(
            paramName,
            expressionForBngsim(
                model, expr, paramName, options.sourcePath, builder, tableIndex));
    }

    for (const auto& function : model.getFunctions()) {
        usedSyntheticNames.insert(function.getName());
        std::size_t tableIndex = 0;
        builder.add_function(
            function.getName(),
            expressionForBngsim(
                model, function.getExpression(), function.getName(),
                options.sourcePath, builder, tableIndex));
    }

    // On-demand single-species helper observables (appended after declared
    // observables so convertBngsimResult projects them out transparently).
    std::unordered_map<int, std::string> singleSpeciesObservables;
    const auto ensureSpeciesObservable = [&](int spIdx) -> std::string {
        auto it = singleSpeciesObservables.find(spIdx);
        if (it != singleSpeciesObservables.end()) return it->second;
        const std::string obsName = makeUniqueSyntheticFunctionName(
            model, usedSyntheticNames, "__bng3_sp_" + std::to_string(spIdx));
        builder.add_observable(obsName, {{spIdx, 1.0}});
        singleSpeciesObservables.emplace(spIdx, obsName);
        return obsName;
    };

    std::unordered_map<std::string, std::string> promotedParamRateFunctions;
    for (std::size_t index = 0; index < network.reactions.size(); ++index) {
        const auto& reaction = network.reactions.all()[index];
        const auto context = bngsimReactionContext(index, reaction);
        const auto reactants = checkedBngsimIndices(
            reaction.getReactants(), network.species.size(), context);
        const auto products = checkedBngsimIndices(
            reaction.getProducts(), network.species.size(), context);
        const auto rate = resolveBngsimRateReference(
            model, reaction, index, options, eventPlan, perReactionArrheniusRates);
        const double effectiveStatFactor =
            computeEffectiveBngsimStatFactor(model, network, reaction, context);

        bngsim::RateLawType type = bngsim::RateLawType::Elementary;
        std::string rateName = rate.name;
        double statFactorToPass = effectiveStatFactor;
        bool applySpeciesFactor = true;
        bool isContinuousOdeChannel = false;

        switch (rate.kind) {
        case BngsimRateKind::ArrheniusConstant: {
            type = bngsim::RateLawType::Elementary;
            rateName = arrheniusParamNames.at(index);
            break;
        }
        case BngsimRateKind::Parameter: {
            if (promotedParamSpeciesIndex.count(rate.name) > 0) {
                type = bngsim::RateLawType::Functional;
                auto fnIt = promotedParamRateFunctions.find(rate.name);
                if (fnIt == promotedParamRateFunctions.end()) {
                    const auto synthName = makeUniqueSyntheticFunctionName(
                        model, usedSyntheticNames, "__bng3_eparam_" + rate.name);
                    builder.add_function(synthName, rate.name);
                    fnIt = promotedParamRateFunctions.emplace(rate.name, synthName).first;
                }
                rateName = fnIt->second;
            } else if (eventPlan.derivedParameters.count(rate.name) > 0) {
                type = bngsim::RateLawType::Functional;
                rateName = rate.name;
            } else {
                type = bngsim::RateLawType::Elementary;
            }
            break;
        }
        case BngsimRateKind::Function: {
            type = bngsim::RateLawType::Functional;
            break;
        }
        case BngsimRateKind::SyntheticExpression: {
            type = bngsim::RateLawType::Functional;
            rateName = makeUniqueSyntheticFunctionName(model, usedSyntheticNames, index);
            std::size_t tableIndex = 0;
            builder.add_function(
                rateName,
                expressionForBngsim(
                    model, *rate.expression, rateName,
                    options.sourcePath, builder, tableIndex));
            break;
        }
        case BngsimRateKind::Sat: {
            type = bngsim::RateLawType::Functional;
            rateName = makeUniqueSyntheticFunctionName(
                model, usedSyntheticNames, "__bng3_sat_" + std::to_string(index));
            const std::string sObs = ensureSpeciesObservable(reactants[0]);
            std::size_t tableIndex = 0;
            const std::string kcatStr = expressionForBngsim(
                model, rate.lawArgs[0], rateName + "_kcat",
                options.sourcePath, builder, tableIndex);
            const std::string kmStr = expressionForBngsim(
                model, rate.lawArgs[1], rateName + "_km",
                options.sourcePath, builder, tableIndex);
            // BNGsim multiplies by all reactant counts (and discrete falling
            // factorial in SSA) when apply_species_factor = true.
            builder.add_function(
                rateName,
                "((" + kcatStr + ") / ((" + kmStr + ") + " + sObs + "))");
            applySpeciesFactor = true;
            break;
        }
        case BngsimRateKind::Hill: {
            type = bngsim::RateLawType::Functional;
            rateName = makeUniqueSyntheticFunctionName(
                model, usedSyntheticNames, "__bng3_hill_" + std::to_string(index));
            const std::string sObs = ensureSpeciesObservable(reactants[0]);
            std::size_t tableIndex = 0;
            const std::string vmaxStr = expressionForBngsim(
                model, rate.lawArgs[0], rateName + "_vmax",
                options.sourcePath, builder, tableIndex);
            const std::string khStr = expressionForBngsim(
                model, rate.lawArgs[1], rateName + "_kh",
                options.sourcePath, builder, tableIndex);
            const std::string nStr = expressionForBngsim(
                model, rate.lawArgs[2], rateName + "_n",
                options.sourcePath, builder, tableIndex);
            const std::string body =
                "((" + vmaxStr + ") * (" + sObs + " ^ ((" + nStr + ") - 1)) / (((" +
                khStr + ") ^ (" + nStr + ")) + (" + sObs + " ^ (" + nStr + "))))";
            builder.add_function(
                rateName,
                "if((" + sObs + " > 0) or ((" + nStr + ") >= 1), " + body + ", 0)");
            applySpeciesFactor = true;
            break;
        }
        case BngsimRateKind::MichaelisMentenNative: {
            type = bngsim::RateLawType::MichaelisMenten;
            rateName = rate.mmKcatParam + "," + rate.mmKmParam;
            applySpeciesFactor = true;
            break;
        }
        case BngsimRateKind::MichaelisMentenFunctional: {
            type = bngsim::RateLawType::Functional;
            const std::string stObs = ensureSpeciesObservable(reactants[0]);
            const std::string etObs = ensureSpeciesObservable(reactants[1]);
            std::size_t tableIndex = 0;
            const std::string base = "__bng3_mm_" + std::to_string(index);
            const std::string kcatStr = expressionForBngsim(
                model, rate.lawArgs[0], base + "_kcat",
                options.sourcePath, builder, tableIndex);
            const std::string kmStr = expressionForBngsim(
                model, rate.lawArgs[1], base + "_km",
                options.sourcePath, builder, tableIndex);
            const std::string bFn = makeUniqueSyntheticFunctionName(
                model, usedSyntheticNames, base + "_b");
            const std::string qFn = makeUniqueSyntheticFunctionName(
                model, usedSyntheticNames, base + "_q");
            const std::string sfFn = makeUniqueSyntheticFunctionName(
                model, usedSyntheticNames, base + "_sf");
            rateName = makeUniqueSyntheticFunctionName(
                model, usedSyntheticNames, base + "_rate");
            builder.add_function(
                bFn, "(" + stObs + " - (" + kmStr + ") - " + etObs + ")");
            builder.add_function(
                qFn, "sqrt((" + bFn + " * " + bFn + ") + (4 * " + stObs + " * (" + kmStr + ")))");
            builder.add_function(
                sfFn,
                "if(" + bFn + " >= 0, 0.5 * (" + bFn + " + " + qFn +
                "), if((" + qFn + " - " + bFn + ") > 0, (2 * " + stObs + " * (" + kmStr +
                ")) / (" + qFn + " - " + bFn + "), 0))");
            builder.add_function(
                rateName,
                "if(((" + kmStr + ") + " + sfFn + ") > 0, ((" + kcatStr + ") * " +
                etObs + " * " + sfFn + ") / ((" + kmStr + ") + " + sfFn + "), 0)");
            applySpeciesFactor = false;
            break;
        }
        case BngsimRateKind::AbsoluteFlux: {
            type = bngsim::RateLawType::Functional;
            rateName = makeUniqueSyntheticFunctionName(
                model, usedSyntheticNames, "__bng3_absflux_" + std::to_string(index));
            std::size_t tableIndex = 0;
            const std::string rawExpr = expressionForBngsim(
                model, *rate.expression, rateName,
                options.sourcePath, builder, tableIndex);
            statFactorToPass = rate.applyStatFactorToAbsoluteFlux ? effectiveStatFactor : 1.0;
            applySpeciesFactor = false;
            if (options.executionMode == BngsimExecutionMode::Ssa) {
                if (rate.isContinuousDifferentialChannel &&
                    reactants.empty() && products.size() == 1) {
                    builder.set_species_continuous(products[0]);
                    builder.add_function(rateName, rawExpr);
                    isContinuousOdeChannel = true;
                } else {
                    // Guard stochastic availability on non-constant reactants and
                    // clamp negative fluxes to zero to match native BNG3 SSA.
                    std::map<int, int> requiredCounts;
                    for (int rIdx : reactants) {
                        if (!network.species.get(static_cast<std::size_t>(rIdx)).isConstant()) {
                            requiredCounts[rIdx] += 1;
                        }
                    }
                    const std::string nonNeg = "max(0, (" + rawExpr + "))";
                    if (requiredCounts.empty()) {
                        builder.add_function(rateName, nonNeg);
                    } else {
                        std::ostringstream cond;
                        bool first = true;
                        for (const auto& [spIdx, req] : requiredCounts) {
                            if (!first) cond << " and ";
                            first = false;
                            cond << "(" << ensureSpeciesObservable(spIdx) << " >= " << req << ")";
                        }
                        builder.add_function(
                            rateName,
                            "if((" + cond.str() + "), " + nonNeg + ", 0)");
                    }
                }
            } else {
                builder.add_function(rateName, rawExpr);
            }
            break;
        }
        }

        builder.add_reaction(
            reactants,
            products,
            type,
            rateName,
            statFactorToPass,
            applySpeciesFactor,
            /*ssa_volume_factor=*/1.0,
            /*per_species_volume_scaling=*/false,
            /*is_rate_rule_ode=*/isContinuousOdeChannel);
    }

    for (std::size_t evIdx = 0; evIdx < eventPlan.events.size(); ++evIdx) {
        const auto& ev = eventPlan.events[evIdx];
        const std::string evOwner = "__bng3_ev_" + std::to_string(evIdx);
        std::size_t evTableIndex = 0;
        std::unordered_set<std::string> expanding;

        const std::string triggerExpr = eventExpressionForBngsim(
            model, ev.expandedTrigger, eventPlan, evOwner + "_trig",
            options.sourcePath, builder, evTableIndex, expanding);

        double constDelay = 0.0;
        std::string delayExpr;
        if (ev.expandedDelay.has_value()) {
            if (expressionReferencesDynamicOrPromoted(
                    model, *ev.expandedDelay, eventPlan.promotedParameters)) {
                expanding.clear();
                delayExpr = eventExpressionForBngsim(
                    model, *ev.expandedDelay, eventPlan, evOwner + "_delay",
                    options.sourcePath, builder, evTableIndex, expanding);
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
                expanding.clear();
                priorityExpr = eventExpressionForBngsim(
                    model, *ev.expandedPriority, eventPlan, evOwner + "_prio",
                    options.sourcePath, builder, evTableIndex, expanding);
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
                    expanding.clear();
                    priorityExpr = eventExpressionForBngsim(
                        model, *ev.expandedPriority, eventPlan, evOwner + "_prio",
                        options.sourcePath, builder, evTableIndex, expanding);
                }
            }
        }

        std::vector<std::pair<int, std::string>> assignments;
        assignments.reserve(ev.assignments.size());
        for (std::size_t aIdx = 0; aIdx < ev.assignments.size(); ++aIdx) {
            const auto& assign = ev.assignments[aIdx];
            const int targetSpeciesIdx = assign.isSpecies
                ? assign.speciesIndex
                : promotedParamSpeciesIndex.at(assign.parameterName);
            expanding.clear();
            assignments.emplace_back(
                targetSpeciesIdx,
                eventExpressionForBngsim(
                    model, assign.expandedValue, eventPlan,
                    evOwner + "_a" + std::to_string(aIdx),
                    options.sourcePath, builder, evTableIndex, expanding));
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
