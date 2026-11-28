#include "PsaSimulator.hpp"
#include "DelayedSemanticsGuard.hpp"
#include "ObservableProjection.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <memory>
#include <optional>
#include <random>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

#include "parser/BNGAstVisitor.hpp"
#include "compile/CompiledModel.hpp"
#include "compile/CompiledRateLaw.hpp"
#include "compile/Document.hpp"
#include "compile/TotalRate.hpp"
#include "io/NetWriter.hpp"
#include "io/TfunReader.hpp"
#include "ast/ReactionRule.hpp"

namespace bng::engine {

namespace {

// Delegate to shared compile-owned rate string evaluator
double evaluateRateString(const std::string& rateStr,
                          const std::function<double(const std::string&)>& resolve) {
    return bng::compile::evaluateRateString(rateStr, resolve);
}

bool isParameterOnlyExpression(const ast::Expression& expression,
                               const ast::Model& model,
                               std::set<std::string>& visiting) {
    switch (expression.kind()) {
        case ast::ExpressionKind::Number:
            return true;
        case ast::ExpressionKind::Identifier: {
            const auto& name = expression.name();
            if (!model.getParameters().contains(name) ||
                !visiting.insert(name).second) {
                return false;
            }
            const auto result = isParameterOnlyExpression(
                model.getParameters().get(name).getExpression(), model, visiting);
            visiting.erase(name);
            return result;
        }
        case ast::ExpressionKind::Unary:
        case ast::ExpressionKind::Binary:
            return std::all_of(
                expression.args().begin(), expression.args().end(),
                [&](const auto& child) {
                    return isParameterOnlyExpression(child, model, visiting);
                });
        case ast::ExpressionKind::Function:
        case ast::ExpressionKind::ObservableRef:
        case ast::ExpressionKind::TableFunction:
            return false;
    }
    return false;
}

std::string stripLocalRateTag(std::string rateLaw) {
    const auto local = rateLaw.find("|local:");
    if (local != std::string::npos) {
        rateLaw.erase(local);
    }
    return rateLaw;
}

bool expressionDependsOnTimeImpl(const ast::Expression& expression,
                                 const ast::Model& model) {
    switch (expression.kind()) {
        case ast::ExpressionKind::Number:
            return false;
        case ast::ExpressionKind::Identifier: {
            const auto& name = expression.name();
            if (model.getParameters().contains(name)) {
                return model.getParameters().isTimeDependent(name);
            }
            return name == "time" || name == "t";
        }
        case ast::ExpressionKind::Function: {
            const auto& name = expression.name();
            if ((name == "time" || name == "t") && expression.args().empty()) {
                return true;
            }
            if ((name == "TFUN" || name == "tfun") && expression.args().size() == 1) {
                return true;
            }
            [[fallthrough]];
        }
        case ast::ExpressionKind::Unary:
        case ast::ExpressionKind::Binary:
        case ast::ExpressionKind::ObservableRef:
        case ast::ExpressionKind::TableFunction:
            return std::any_of(
                expression.args().begin(), expression.args().end(),
                [&](const auto& child) {
                    return expressionDependsOnTimeImpl(child, model);
                });
    }
    return false;
}

bool expressionDependsOnTime(const ast::Expression& expression,
                             const ast::Model& model,
                             const ast::ModelFunctionEvaluator& fnEval) {
    try {
        const auto expanded = fnEval.expandFunctions(expression);
        return expressionDependsOnTimeImpl(expanded, model);
    } catch (const std::exception&) {
        return expressionDependsOnTimeImpl(expression, model);
    }
}

bool expressionUsesObservableImpl(const ast::Expression& expression,
                                  const std::unordered_set<std::string>& obsNames) {
    switch (expression.kind()) {
        case ast::ExpressionKind::Number:
            return false;
        case ast::ExpressionKind::Identifier:
        case ast::ExpressionKind::ObservableRef:
            if (obsNames.find(expression.name()) != obsNames.end()) {
                return true;
            }
            return std::any_of(
                expression.args().begin(), expression.args().end(),
                [&](const auto& child) {
                    return expressionUsesObservableImpl(child, obsNames);
                });
        case ast::ExpressionKind::Function:
            if (expression.args().empty() &&
                obsNames.find(expression.name()) != obsNames.end()) {
                return true;
            }
            [[fallthrough]];
        case ast::ExpressionKind::Unary:
        case ast::ExpressionKind::Binary:
        case ast::ExpressionKind::TableFunction:
            return std::any_of(
                expression.args().begin(), expression.args().end(),
                [&](const auto& child) {
                    return expressionUsesObservableImpl(child, obsNames);
                });
    }
    return false;
}

ast::Expression materializeTfunExpression(const ast::Expression& expr) {
    switch (expr.kind()) {
        case ast::ExpressionKind::Number:
        case ast::ExpressionKind::Identifier:
            return expr;
        case ast::ExpressionKind::Unary:
            return ast::Expression::unary(
                expr.name(), materializeTfunExpression(expr.args().front()));
        case ast::ExpressionKind::Binary:
            return ast::Expression::binary(
                expr.name(),
                materializeTfunExpression(expr.args()[0]),
                materializeTfunExpression(expr.args()[1]));
        case ast::ExpressionKind::Function: {
            std::vector<ast::Expression> args;
            args.reserve(expr.args().size());
            for (const auto& arg : expr.args()) {
                args.push_back(materializeTfunExpression(arg));
            }
            return ast::Expression::function(expr.name(), std::move(args));
        }
        case ast::ExpressionKind::ObservableRef: {
            std::vector<ast::Expression> args;
            args.reserve(expr.args().size());
            for (const auto& arg : expr.args()) {
                args.push_back(materializeTfunExpression(arg));
            }
            return ast::Expression::observableRef(expr.name(), std::move(args));
        }
        case ast::ExpressionKind::TableFunction: {
            if (expr.args().size() != 1) {
                throw std::runtime_error("TFUN expression must have one counter expression");
            }
            auto counter = materializeTfunExpression(expr.args().front());
            if (!expr.tableFilePath().empty()) {
                auto table = bng::io::TfunReader::read(expr.tableFilePath());
                return ast::Expression::tableFunction(
                    std::move(table.times),
                    std::move(table.values),
                    std::string(),
                    std::move(counter),
                    expr.tableMethod());
            }
            return ast::Expression::tableFunction(
                expr.tableXValues(),
                expr.tableYValues(),
                std::string(),
                std::move(counter),
                expr.tableMethod());
        }
    }
    return expr;
}

std::vector<ast::Expression> extractTypedRateLawArgs(
    const ast::Rxn& rxn,
    const std::string& rawRateLaw,
    const std::string& keywordLower,
    std::size_t kwLen) {
    auto matchesKeyword = [&](const std::string& fnName) {
        std::string lo = fnName;
        std::transform(lo.begin(), lo.end(), lo.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        return lo == keywordLower;
    };

    if (rxn.getRateExpression().has_value() &&
        rxn.getRateExpression()->kind() == ast::ExpressionKind::Function &&
        matchesKeyword(rxn.getRateExpression()->name())) {
        return rxn.getRateExpression()->args();
    }

    try {
        const auto parsed = parser::parseExpression(rawRateLaw);
        if (parsed.kind() == ast::ExpressionKind::Function &&
            matchesKeyword(parsed.name())) {
            return parsed.args();
        }
    } catch (...) {
    }

    auto parseArgToken = [](const std::string& text) -> ast::Expression {
        try {
            return parser::parseExpression(text);
        } catch (...) {
            char* end = nullptr;
            const double value = std::strtod(text.c_str(), &end);
            if (end != text.c_str() && end != nullptr && *end == '\0') {
                return ast::Expression::number(value);
            }
            return ast::Expression::identifier(text);
        }
    };

    std::vector<ast::Expression> argExprs;
    std::string cleaned = rawRateLaw;
    auto startP = cleaned.find_first_not_of(" \t\r\n");
    if (startP != std::string::npos) cleaned = cleaned.substr(startP);
    else cleaned.clear();
    auto endP = cleaned.find_last_not_of(" \t\r\n");
    if (endP != std::string::npos) cleaned = cleaned.substr(0, endP + 1);

    if (cleaned.size() >= kwLen) {
        cleaned = cleaned.substr(kwLen);
    } else {
        cleaned.clear();
    }

    startP = cleaned.find_first_not_of(" \t\r\n");
    if (startP != std::string::npos) cleaned = cleaned.substr(startP);
    else cleaned.clear();

    if (!cleaned.empty() && cleaned.front() == '(' && cleaned.back() == ')') {
        cleaned = cleaned.substr(1, cleaned.size() - 2);
        int depth = 0;
        std::size_t segStart = 0;
        for (std::size_t ci = 0; ci <= cleaned.size(); ++ci) {
            if (ci < cleaned.size()) {
                if (cleaned[ci] == '(') ++depth;
                else if (cleaned[ci] == ')' && depth > 0) --depth;
            }
            if (ci == cleaned.size() || (cleaned[ci] == ',' && depth == 0)) {
                std::string tok = cleaned.substr(segStart, ci - segStart);
                auto f = tok.find_first_not_of(" \t\r\n");
                if (f != std::string::npos) {
                    tok.erase(0, f);
                    tok.erase(tok.find_last_not_of(" \t\r\n") + 1);
                    argExprs.push_back(parseArgToken(tok));
                }
                segStart = ci + 1;
            }
        }
    } else {
        std::istringstream rlStream(cleaned);
        std::string tok;
        while (rlStream >> tok) {
            argExprs.push_back(parseArgToken(tok));
        }
    }
    return argExprs;
}

std::vector<double> psaOutputTimes(const OdeOptions& opts) {
    if (!std::isfinite(opts.tStart) || !std::isfinite(opts.tEnd)) {
        throw std::runtime_error("t_start and t_end must be finite");
    }
    if (opts.tEnd < opts.tStart) {
        throw std::runtime_error("t_end must be greater than or equal to t_start");
    }
    if (!opts.sampleTimes.empty()) {
        std::vector<double> times = opts.sampleTimes;
        for (std::size_t i = 0; i < times.size(); ++i) {
            if (!std::isfinite(times[i])) {
                throw std::runtime_error("sample_times must contain only finite values");
            }
            if (times[i] < opts.tStart || times[i] > opts.tEnd) {
                throw std::runtime_error("sample_times must lie between t_start and t_end");
            }
            if (i > 0 && times[i] <= times[i - 1]) {
                throw std::runtime_error("sample_times must be strictly increasing");
            }
        }
        return times;
    }
    if (opts.nSteps == 0) {
        throw std::runtime_error("n_steps must be positive");
    }
    const double dt = (opts.tEnd - opts.tStart) / static_cast<double>(opts.nSteps);
    std::vector<double> times;
    times.reserve(opts.nSteps + 1);
    for (std::size_t step = 0; step <= opts.nSteps; ++step) {
        times.push_back(opts.tStart + static_cast<double>(step) * dt);
    }
    return times;
}

} // anonymous namespace


PsaSimulator::PsaSimulator(const ast::Model& model, const GeneratedNetwork& network)
    : model_(model), network_(network), functionEvaluator_(model) {
    requireNoDelayedSemantics(model_, network_, "PSA");
    if (model_.getEventFormatVersion().has_value()) {
        throw std::runtime_error(ast::kUnsupportedEventExecutionMessage);
    }
    compile();
}

void PsaSimulator::PropensityTree::assign(const std::vector<double>& values) {
    tree_.assign(values.size() + 1, 0.0);
    total_ = 0.0;
    for (std::size_t i = 1; i < tree_.size(); ++i) {
        total_ += values[i - 1];
        tree_[i] += values[i - 1];
        const auto parent = i + (i & (~i + 1));
        if (parent < tree_.size()) {
            tree_[parent] += tree_[i];
        }
    }
}

void PsaSimulator::PropensityTree::add(std::size_t index, double delta) {
    total_ += delta;
    for (std::size_t i = index + 1; i < tree_.size(); i += i & (~i + 1)) {
        tree_[i] += delta;
    }
}

std::size_t PsaSimulator::PropensityTree::select(double target) const {
    const std::size_t count = tree_.empty() ? 0 : tree_.size() - 1;
    std::size_t bit = 1;
    while (bit <= count / 2) {
        bit <<= 1;
    }

    std::size_t prefixLength = 0;
    double prefixSum = 0.0;
    while (bit != 0) {
        const auto next = prefixLength + bit;
        if (next <= count && prefixSum + tree_[next] < target) {
            prefixLength = next;
            prefixSum += tree_[next];
        }
        bit >>= 1;
    }
    return prefixLength;
}

void PsaSimulator::compile() {
    nSpecies_ = network_.species.size();
    fixedSpecies_.resize(nSpecies_, false);

    for (std::size_t i = 0; i < nSpecies_; ++i) {
        fixedSpecies_[i] = network_.species.get(i).isConstant();
    }

    auto paramResolver = [&](const std::string& name) -> double {
        return model_.getParameters().evaluate(name);
    };

    std::unordered_set<std::string> obsNames;
    obsNames.reserve(model_.getObservables().size());
    for (const auto& obs : model_.getObservables()) {
        obsNames.insert(obs.getName());
    }

    // Build per-reaction derived rate maps from NetWriter (scoped rates,
    // FunctionProduct, and Energy BNGL Arrhenius rates + barriers + reservoirs).
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
                if (!info.perReactionRates.empty() ||
                    !info.perReactionRateFunctions.empty() ||
                    !info.perReactionRuntimeRateConstants.empty()) {
                    continue;
                }
                std::size_t rxnIdx = 0;
                for (const auto& rxn2 : network_.reactions.all()) {
                    if (rxn2.getOriginRuleName() == ruleName && !rxn2.getReactants().empty()) {
                        const auto specIdx = rxn2.getReactants()[0];
                        const auto it = info.perSpeciesRates.find(specIdx);
                        if (it != info.perSpeciesRates.end()) {
                            perRxnDerivedRates[rxnIdx] = it->second;
                        }
                    }
                    ++rxnIdx;
                }
            }
        }
    }

    struct RuleRateKinds {
        bng::compile::RateLawKind forward = bng::compile::RateLawKind::Expression;
        std::optional<bng::compile::RateLawKind> reverse;
    };
    std::unordered_map<std::string, RuleRateKinds> typedRateKinds;
    for (const auto& rule : model_.getReactionRules()) {
        if (!rule.getRates().empty()) {
            RuleRateKinds kinds;
            kinds.forward = bng::compile::CompiledRateLaw::compile(rule.getRates().front()).kind;
            if (rule.getRates().size() >= 2) {
                kinds.reverse = bng::compile::CompiledRateLaw::compile(rule.getRates()[1]).kind;
            }
            typedRateKinds.emplace(rule.getRuleName(), kinds);
        }
    }
    const auto typedRateKindForOrigin = [&](std::string origin)
        -> std::optional<bng::compile::RateLawKind> {
        if (const auto exact = typedRateKinds.find(origin); exact != typedRateKinds.end()) {
            return exact->second.forward;
        }
        bool isReverse = false;
        if (origin.rfind("_reverse__", 0) == 0) {
            isReverse = true;
            origin = origin.substr(std::string("_reverse__").size());
        } else if (origin.rfind("__reverse__", 0) == 0) {
            isReverse = true;
            origin = origin.substr(std::string("__reverse__").size());
        } else if (!origin.empty() && origin.front() == '_') {
            origin.erase(origin.begin());
        }
        if (origin.size() > std::string("_reverse").size() &&
            origin.rfind("_reverse") == origin.size() - std::string("_reverse").size()) {
            isReverse = true;
            origin.erase(origin.size() - std::string("_reverse").size());
        }
        const auto it = typedRateKinds.find(origin);
        if (it == typedRateKinds.end()) return std::nullopt;
        return isReverse ? it->second.reverse : std::optional<bng::compile::RateLawKind>(it->second.forward);
    };

    compiledRxns_.clear();
    std::size_t rxnIndex = 0;
    for (const auto& rxn : network_.reactions.all()) {
        CompiledReaction crxn;
        crxn.reactantIndices = rxn.getReactants();
        crxn.productIndices = rxn.getProducts();

        const auto& originRuleName = rxn.getOriginRuleName();
        const bool ruleIsTotalRate = bng::compile::isTotalRateReaction(model_, originRuleName);
        crxn.isAbsoluteFlux = bng::compile::isAbsoluteFluxReaction(model_, rxn);
        crxn.isTotalRate = ruleIsTotalRate || crxn.isAbsoluteFlux;

        if (crxn.isAbsoluteFlux) {
            std::optional<ast::Expression> expression = rxn.getRateExpression();
            if (!expression.has_value()) {
                auto rateLaw = stripLocalRateTag(rxn.getRateLaw());
                try {
                    expression = parser::parseExpression(rateLaw);
                } catch (const std::exception&) {
                    throw std::runtime_error(
                        "PSA does not support non-constant absolute-flux rate laws; "
                        "failing closed.");
                }
            }
            std::set<std::string> visiting;
            if (!isParameterOnlyExpression(*expression, model_, visiting)) {
                throw std::runtime_error(
                    "PSA does not support state/time-dependent absolute-flux rate "
                    "laws; failing closed.");
            }
        }

        // Canonical BNG2 semantics: TotalRate omits statFactor only, while
        // compartment unit conversion (1/V) still applies for authored BNGL
        // rules and is omitted only for SBML absolute-flux reactions.
        double prefactor = 1.0;
        if (!crxn.isAbsoluteFlux) {
            const auto unitFactor =
                bng::io::NetWriter::computeUnitConversionFactor(
                    rxn, model_, network_);
            if (unitFactor.has_value()) {
                prefactor *= *unitFactor;
            }
        }
        if (!crxn.isTotalRate) {
            prefactor *= rxn.getFactor();
        }
        crxn.statFactor = prefactor;

        // Fast path: per-reaction derived rates (Arrhenius, scoped rates, FunctionProduct)
        bool resolvedDerived = false;
        if (const auto rtIt = perRxnDerivedRuntimeRateConstants.find(rxnIndex);
            rtIt != perRxnDerivedRuntimeRateConstants.end()) {
            const double baseValue = rtIt->second;
            if (!std::isfinite(baseValue)) {
                throw std::runtime_error("PSA encountered a non-finite derived reaction rate");
            }
            crxn.rateConstant = prefactor * baseValue;
            resolvedDerived = true;
        } else if (const auto fnIt = perRxnDerivedRateFunctions.find(rxnIndex);
                   fnIt != perRxnDerivedRateFunctions.end()) {
            if (expressionDependsOnTime(fnIt->second, model_, functionEvaluator_)) {
                throw std::runtime_error(
                    "PSA does not support explicitly time-dependent rate laws");
            }
            const auto expanded = materializeTfunExpression(
                functionEvaluator_.expandFunctions(fnIt->second));
            if (expressionUsesObservableImpl(expanded, obsNames)) {
                crxn.usesObservables = true;
                crxn.functionalExpr = expanded;
                crxn.rateConstant = std::numeric_limits<double>::quiet_NaN();
            } else {
                const double baseValue = functionEvaluator_.evaluate(expanded, paramResolver);
                if (!std::isfinite(baseValue)) {
                    throw std::runtime_error("PSA encountered a non-finite derived reaction rate");
                }
                crxn.rateConstant = prefactor * baseValue;
            }
            resolvedDerived = true;
        } else if (const auto drIt = perRxnDerivedRates.find(rxnIndex);
                   drIt != perRxnDerivedRates.end()) {
            const double baseValue = drIt->second.second;
            if (!std::isfinite(baseValue)) {
                throw std::runtime_error("PSA encountered a non-finite derived reaction rate");
            }
            crxn.rateConstant = prefactor * baseValue;
            resolvedDerived = true;
        }

        if (resolvedDerived) {
            compiledRxns_.push_back(std::move(crxn));
            ++rxnIndex;
            continue;
        }

        const std::string rawRateLaw = stripLocalRateTag(rxn.getRateLaw());

        // Detect Sat / MM / Hill built-in rate laws (matching OdeIntegrator).
        std::optional<bng::compile::RateLawKind> typedKind;
        if (rxn.getRateExpression().has_value()) {
            typedKind = bng::compile::CompiledRateLaw::compile(*rxn.getRateExpression()).kind;
        } else {
            typedKind = typedRateKindForOrigin(originRuleName);
        }
        PsaRateLawKind detectedKind = PsaRateLawKind::Elementary;
        std::string kwLower;
        std::size_t kwLen = 0;
        if (typedKind.has_value()) {
            switch (*typedKind) {
                case bng::compile::RateLawKind::Saturation:
                    detectedKind = PsaRateLawKind::Saturation;
                    kwLower = "sat";
                    kwLen = 3;
                    break;
                case bng::compile::RateLawKind::MichaelisMenten:
                    detectedKind = PsaRateLawKind::MichaelisMenten;
                    kwLower = "mm";
                    kwLen = 2;
                    break;
                case bng::compile::RateLawKind::Hill:
                    detectedKind = PsaRateLawKind::Hill;
                    kwLower = "hill";
                    kwLen = 4;
                    break;
                default:
                    break;
            }
        } else {
            std::string rlLower = rawRateLaw;
            const auto first = rlLower.find_first_not_of(" \t\r\n");
            if (first != std::string::npos) rlLower = rlLower.substr(first);
            std::transform(rlLower.begin(), rlLower.end(), rlLower.begin(), [](unsigned char c) {
                return static_cast<char>(std::tolower(c));
            });
            auto isWordPrefix = [&](const std::string& kw) {
                if (rlLower.rfind(kw, 0) != 0) return false;
                if (rlLower.size() == kw.size()) return true;
                const char nextC = rlLower[kw.size()];
                return nextC == ' ' || nextC == '\t' || nextC == '\r' || nextC == '\n' || nextC == '(';
            };
            if (isWordPrefix("sat")) {
                detectedKind = PsaRateLawKind::Saturation;
                kwLower = "sat";
                kwLen = 3;
            } else if (isWordPrefix("mm")) {
                detectedKind = PsaRateLawKind::MichaelisMenten;
                kwLower = "mm";
                kwLen = 2;
            } else if (isWordPrefix("hill")) {
                detectedKind = PsaRateLawKind::Hill;
                kwLower = "hill";
                kwLen = 4;
            }
        }

        if (detectedKind != PsaRateLawKind::Elementary) {
            auto argExprs = extractTypedRateLawArgs(rxn, rawRateLaw, kwLower, kwLen);
            const bool isMM = (detectedKind == PsaRateLawKind::MichaelisMenten);
            const bool isHill = (detectedKind == PsaRateLawKind::Hill);
            if (argExprs.empty()) {
                throw std::runtime_error(
                    "PSA encountered a " + kwLower + " rate law with no arguments");
            }
            if ((isMM || isHill) && crxn.reactantIndices.empty()) {
                throw std::runtime_error(
                    "PSA encountered a " + kwLower + " rate law without reactants");
            }
            if (isMM && argExprs.size() == 2 && crxn.reactantIndices.size() >= 2 &&
                crxn.reactantIndices[0] == crxn.reactantIndices[1]) {
                throw std::runtime_error(
                    "MM(kcat,Km) with identical substrate and enzyme reactants is unsupported; "
                    "canonical BioNetGen rejects this rate-law configuration");
            }
            if (isHill && argExprs.size() < 2) {
                throw std::runtime_error("PSA Hill rate law requires at least 2 arguments");
            }
            if (isMM && argExprs.size() < 2) {
                throw std::runtime_error("PSA MM rate law requires at least 2 arguments");
            }

            bool anyUsesObs = false;
            std::vector<ast::Expression> expandedArgs;
            expandedArgs.reserve(argExprs.size());
            for (const auto& argExpr : argExprs) {
                if (expressionDependsOnTime(argExpr, model_, functionEvaluator_)) {
                    throw std::runtime_error(
                        "PSA does not support explicitly time-dependent rate laws");
                }
                auto expanded = materializeTfunExpression(
                    functionEvaluator_.expandFunctions(argExpr));
                if (expressionUsesObservableImpl(expanded, obsNames)) {
                    anyUsesObs = true;
                }
                expandedArgs.push_back(std::move(expanded));
            }

            crxn.rateLawKind = detectedKind;
            crxn.usesObservables = anyUsesObs;
            if (anyUsesObs) {
                crxn.rateLawArgExprs = std::move(expandedArgs);
                crxn.rateConstant = std::numeric_limits<double>::quiet_NaN();
            } else {
                crxn.staticRateLawArgs.reserve(expandedArgs.size());
                for (const auto& expanded : expandedArgs) {
                    const double val = functionEvaluator_.evaluate(expanded, paramResolver);
                    if (!std::isfinite(val)) {
                        throw std::runtime_error(
                            "PSA encountered a non-finite argument in " + kwLower + " rate law");
                    }
                    crxn.staticRateLawArgs.push_back(val);
                }
            }
            compiledRxns_.push_back(std::move(crxn));
            ++rxnIndex;
            continue;
        }

        std::optional<ast::Expression> parsedRate;
        try {
            parsedRate = parser::parseExpression(rawRateLaw);
        } catch (const std::exception&) {
            // Keep the narrow legacy parser for old rate spellings that the
            // shared BNGL expression parser does not accept.
        }
        if (parsedRate.has_value()) {
            if (expressionDependsOnTime(*parsedRate, model_, functionEvaluator_)) {
                throw std::runtime_error(
                    "PSA does not support explicitly time-dependent rate laws");
            }
            const auto expanded = materializeTfunExpression(
                functionEvaluator_.expandFunctions(*parsedRate));
            if (expressionUsesObservableImpl(expanded, obsNames)) {
                crxn.usesObservables = true;
                crxn.functionalExpr = expanded;
                crxn.rateConstant = std::numeric_limits<double>::quiet_NaN();
            } else {
                const double baseValue =
                    functionEvaluator_.evaluate(expanded, paramResolver);
                if (!std::isfinite(baseValue)) {
                    throw std::runtime_error("PSA encountered a non-finite reaction rate constant");
                }
                crxn.rateConstant = prefactor * baseValue;
            }
        } else {
            try {
                crxn.rateConstant = prefactor * evaluateRateString(rawRateLaw, paramResolver);
            } catch (const std::exception&) {
                crxn.rateConstant = 0.0;
            }
        }

        compiledRxns_.push_back(std::move(crxn));
        ++rxnIndex;
    }

    nReactions_ = compiledRxns_.size();
    compileGroups();
    createUpdateLists();
}

void PsaSimulator::compileGroups() {
    compiledGroups_.clear();

    std::unique_ptr<compile::CompiledModel> compiledModel;
    std::unique_ptr<ObservableProjection> projection;
    const auto ensureProjection = [&]() {
        if (!projection) {
            compiledModel = std::make_unique<compile::CompiledModel>(model_);
            projection = std::make_unique<ObservableProjection>(*compiledModel);
        }
    };

    const auto& observables = model_.getObservables();
    compiledGroups_.reserve(observables.size());
    for (std::size_t observableIndex = 0; observableIndex < observables.size(); ++observableIndex) {
        const auto& observable = observables[observableIndex];
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

            compiledGroups_.push_back(std::move(group));
            continue;
        }

        ensureProjection();
        for (std::size_t speciesIndex = 0; speciesIndex < network_.species.size(); ++speciesIndex) {
            const auto& speciesObj = network_.species.get(speciesIndex);
            const int weight = projection->weight(
                observableIndex,
                speciesObj.getSpeciesGraph().getGraph(),
                speciesObj.getCompartment());
            if (weight > 0) {
                group.entries.emplace_back(speciesIndex, static_cast<double>(weight));
            }
        }

        compiledGroups_.push_back(std::move(group));
    }
}

void PsaSimulator::createUpdateLists() {
    // Build dependency lists: for each reaction, determine which reactions
    // need propensity updates when it fires.
    // This mirrors create_update_lists() from network.cpp.

    // Step 1: Build species-to-reaction maps.
    // asReactant[species] = reactions that have this species as a reactant.
    // asProduct[species]  = reactions that have this species as a product
    //   (needed for PSA scaling of zeroth-order reactions and pScaleChecker).
    std::vector<std::set<std::size_t>> asReactant(nSpecies_);
    std::vector<std::set<std::size_t>> asProduct(nSpecies_);
    std::vector<std::size_t> functionalRxns;
    for (std::size_t r = 0; r < nReactions_; ++r) {
        for (const auto idx : compiledRxns_[r].reactantIndices) {
            asReactant[idx].insert(r);
        }
        for (const auto idx : compiledRxns_[r].productIndices) {
            asProduct[idx].insert(r);
        }
        if (compiledRxns_[r].usesObservables) {
            functionalRxns.push_back(r);
        }
    }

    // Step 2: For each reaction, find all species it touches (reactants + products),
    // then collect all reactions that depend on those species (plus any
    // observable-dependent functional reactions).
    rxnUpdateRxn_.resize(nReactions_);
    for (std::size_t r = 0; r < nReactions_; ++r) {
        std::set<std::size_t> depRxns;

        // All species affected by firing reaction r
        for (const auto idx : compiledRxns_[r].reactantIndices) {
            for (const auto depR : asReactant[idx]) {
                depRxns.insert(depR);
            }
            for (const auto depR : asProduct[idx]) {
                depRxns.insert(depR);
            }
        }
        for (const auto idx : compiledRxns_[r].productIndices) {
            for (const auto depR : asReactant[idx]) {
                depRxns.insert(depR);
            }
            for (const auto depR : asProduct[idx]) {
                depRxns.insert(depR);
            }
        }
        for (const auto funcR : functionalRxns) {
            depRxns.insert(funcR);
        }

        rxnUpdateRxn_[r].assign(depRxns.begin(), depRxns.end());
    }
}

namespace {

/* Scaling factor of a reaction for the partial scaling algorithm (PSA):
 * floor(Nmin/poplevel), where Nmin is the smallest population among the
 * reaction's reactants (and its products, if pScaleChecker is set), and 1 if
 * any of those populations is below 2*poplevel (Lin, Feng & Hlavacek, J Chem
 * Phys 150:244101, 2019, Eq. 9). A reaction with no reactants, such as 0 -> A,
 * is scaled by its products whether or not pScaleChecker is set; one with no
 * reactants and no products is not scaled. Matches bionetgen #358.
 *
 * In addition, for every reactant r with stoichiometric multiplicity m_r,
 * enforce m_r * s <= state[r] (i.e. s <= floor(state[r] / m_r)). This
 * guarantees both exact mass conservation (firing never drives a reactant
 * negative even when poplevel <= m_r or poplevel < 1) and that the scaled
 * combinatorial factor (state[r] / s - (m_r - 1)) stays strictly positive
 * whenever state[r] >= m_r (never freezing homotypic reactions). */
double psaScaling(const std::vector<std::size_t>& reactants,
                  const std::vector<std::size_t>& products,
                  const std::vector<double>& state,
                  double poplevel,
                  bool pScaleChecker) {
    const double upperBound = 2.0 * poplevel;
    double tempPop = -1.0;
    double maxAllowedScaling = std::numeric_limits<double>::infinity();

    for (const auto ri : reactants) {
        const double x = state[ri];
        if (x < upperBound) return 1.0;
        if (tempPop < 0.0 || x < tempPop) tempPop = x;
        const auto mult = static_cast<double>(
            std::count(reactants.begin(), reactants.end(), ri));
        if (mult >= 1.0) {
            const double cap = std::floor(x / mult);
            if (cap < 1.0) return 1.0;
            if (cap < maxAllowedScaling) maxAllowedScaling = cap;
        }
    }
    if (pScaleChecker || reactants.empty()) {
        for (const auto pi : products) {
            const double x = state[pi];
            if (x < upperBound) return 1.0;
            if (tempPop < 0.0 || x < tempPop) tempPop = x;
        }
    }
    if (tempPop < 0.0) return 1.0;
    double scaling = std::floor(tempPop / poplevel);
    if (scaling > maxAllowedScaling) {
        scaling = maxAllowedScaling;
    }
    return scaling < 1.0 ? 1.0 : scaling;
}

double computeScaledElementaryPropensity(double baseRate,
                                         const std::vector<std::size_t>& reactants,
                                         const std::vector<std::size_t>& products,
                                         const std::vector<double>& state,
                                         double poplevel,
                                         bool pScaleChecker,
                                         double& scaling) {
    const std::size_t nReactants = reactants.size();
    double rate = baseRate;

    if (poplevel <= 0.0) {
        scaling = 1.0;
        for (std::size_t i = 0; i < nReactants; ++i) {
            const double n = static_cast<double>(
                std::count(reactants.begin(),
                           reactants.begin() + static_cast<std::ptrdiff_t>(i),
                           reactants[i]));
            rate *= std::max(0.0, state[reactants[i]] - n);
        }
        return rate < 0.0 ? 0.0 : rate;
    }

    scaling = psaScaling(reactants, products, state, poplevel, pScaleChecker);

    double scalingExp = 0.0;
    for (std::size_t i = 0; i < nReactants; ++i) {
        scalingExp += 1.0;
        const double n = static_cast<double>(
            std::count(reactants.begin(),
                       reactants.begin() + static_cast<std::ptrdiff_t>(i),
                       reactants[i]));
        rate *= std::max(0.0, state[reactants[i]] / scaling - n);
    }
    rate *= std::pow(scaling, scalingExp - 1.0);
    return rate < 0.0 ? 0.0 : rate;
}

double computeScaledTypedPropensity(
    double statFactor,
    const std::vector<std::size_t>& reactants,
    const std::vector<std::size_t>& products,
    const std::vector<bool>& fixedSpecies,
    const std::vector<double>& state,
    const std::vector<double>& args,
    int rateLawKindInt,
    double poplevel,
    bool pScaleChecker,
    double& scaling) {
    scaling = (poplevel <= 0.0)
        ? 1.0
        : psaScaling(reactants, products, state, poplevel, pScaleChecker);

    const std::size_t nReactants = reactants.size();
    auto repeatedOffset = [&](std::size_t idxPos) -> double {
        return static_cast<double>(
            std::count(reactants.begin(),
                       reactants.begin() + static_cast<std::ptrdiff_t>(idxPos),
                       reactants[idxPos]));
    };

    double unscaled = 0.0;
    if (rateLawKindInt == 1) {
        // Saturation: Sat(k) or Sat(k, K1, ..., KN)
        if (args.size() == 1) {
            for (std::size_t i = 0; i < nReactants; ++i) {
                if (reactants[i] < fixedSpecies.size() && fixedSpecies[reactants[i]]) continue;
                const double required = repeatedOffset(i) + 1.0;
                if (state[reactants[i]] < required) return 0.0;
            }
            unscaled = statFactor * args[0];
        } else {
            const std::size_t nDenom = std::min(args.size() - 1, nReactants);
            double rate = statFactor * args[0];
            for (std::size_t i = 0; i < nDenom; ++i) {
                const double x = state[reactants[i]];
                const double n = repeatedOffset(i);
                const double eff = std::max(0.0, x - scaling * n);
                const double denom = args[i + 1] + x;
                if (denom == 0.0 || eff <= 0.0) return 0.0;
                rate *= eff / denom;
            }
            for (std::size_t i = nDenom; i < nReactants; ++i) {
                const double x = state[reactants[i]];
                const double n = repeatedOffset(i);
                rate *= std::max(0.0, x - scaling * n);
            }
            unscaled = rate;
        }
    } else if (rateLawKindInt == 2) {
        // Michaelis-Menten: MM(kcat, Km) or MM(Vmax, Km, S)
        if (args.size() >= 3) {
            const double vmax = args[0];
            const double km = args[1];
            const double sVal = args[2];
            const double denom = km + sVal;
            if (denom == 0.0 || sVal <= 0.0) return 0.0;
            double rate = statFactor * vmax * sVal / denom;
            for (std::size_t i = 1; i < nReactants; ++i) {
                const double n = repeatedOffset(i);
                rate *= std::max(0.0, state[reactants[i]] - scaling * n);
            }
            unscaled = rate;
        } else if (nReactants >= 2) {
            const double kcat = args[0];
            const double km = args[1];
            const double st = state[reactants[0]];
            const double et = state[reactants[1]];
            if (st <= 0.0 || et <= 0.0) return 0.0;
            const double b = st - km - et;
            const double disc = b * b + 4.0 * st * km;
            if (disc < 0.0) return 0.0;
            const double q = std::sqrt(disc);
            const double sFree = (b >= 0.0)
                ? (0.5 * (b + q))
                : ((q - b) > 0.0 ? (2.0 * st * km / (q - b)) : 0.0);
            const double denom = km + sFree;
            if (denom <= 0.0) return 0.0;
            double rate = statFactor * kcat * et * sFree / denom;
            for (std::size_t i = 2; i < nReactants; ++i) {
                const double n = repeatedOffset(i);
                rate *= std::max(0.0, state[reactants[i]] - scaling * n);
            }
            unscaled = rate;
        } else if (nReactants == 1) {
            const double kcat = args[0];
            const double km = args[1];
            const double st = state[reactants[0]];
            const double denom = km + st;
            if (denom <= 0.0 || st <= 0.0) return 0.0;
            unscaled = statFactor * kcat * st / denom;
        }
    } else if (rateLawKindInt == 3) {
        // Hill: Hill(Vmax, Kh, n)
        if (nReactants == 0) return 0.0;
        const double vmax = args[0];
        const double kh = args[1];
        const double nExp = (args.size() >= 3) ? args[2] : 1.0;
        const double sVal = state[reactants[0]];
        if (sVal <= 0.0) return 0.0;
        const double sn = std::pow(sVal, nExp);
        const double kn = std::pow(kh, nExp);
        const double denom = kn + sn;
        if (!std::isfinite(denom) || denom <= 0.0) return 0.0;
        double rate = statFactor * vmax * sn / denom;
        for (std::size_t i = 1; i < nReactants; ++i) {
            const double n = repeatedOffset(i);
            rate *= std::max(0.0, state[reactants[i]] - scaling * n);
        }
        unscaled = rate;
    }

    const double scaled = unscaled / scaling;
    return (std::isfinite(scaled) && scaled > 0.0) ? scaled : 0.0;
}

} // anonymous namespace

double PsaSimulator::rxnRateScaled(std::size_t rxnIdx,
                                     const std::vector<double>& state,
                                     double poplevel, bool pScaleChecker,
                                     double& scaling) const {
    const auto& rxn = compiledRxns_[rxnIdx];
    const auto& reactants = rxn.reactantIndices;
    const auto& products = rxn.productIndices;
    const std::size_t nReactants = reactants.size();

    if (rxn.rateLawKind != PsaRateLawKind::Elementary) {
        return computeScaledTypedPropensity(
            rxn.statFactor, reactants, products, fixedSpecies_, state,
            rxn.staticRateLawArgs, static_cast<int>(rxn.rateLawKind),
            poplevel, pScaleChecker, scaling);
    }

    // Absolute SBML fluxes already include reactant dependence. Authored
    // TotalRate rules still use finite-network reactant counts, with their
    // symmetry factor set to one during compilation.
    if (rxn.isAbsoluteFlux) {
        scaling = 1.0;
        for (std::size_t i = 0; i < nReactants; ++i) {
            if (reactants[i] < fixedSpecies_.size() && fixedSpecies_[reactants[i]]) continue;
            const auto required = static_cast<double>(
                std::count(reactants.begin(),
                           reactants.begin() + static_cast<std::ptrdiff_t>(i),
                           reactants[i]) + 1);
            if (state[reactants[i]] < required) return 0.0;
        }
        return rxn.rateConstant < 0.0 ? 0.0 : rxn.rateConstant;
    }

    return computeScaledElementaryPropensity(
        rxn.rateConstant, reactants, products, state, poplevel, pScaleChecker, scaling);
}

bool PsaSimulator::updateConcentrationsPsa(std::size_t irxn,
                                             std::vector<double>& state,
                                             const std::vector<double>& scaling) const {
    // Faithful port of update_concentrations_psa() from network.cpp.
    // Concentration changes by +/- s[irxn] instead of +/- 1.
    const int threshOcc = 10;
    bool forceUpdate = false;
    const auto& rxn = compiledRxns_[irxn];
    const double s = scaling[irxn];

    // Loop over reactants: decrease by s
    for (const auto ri : rxn.reactantIndices) {
        if (!fixedSpecies_[ri]) {
            state[ri] -= s;
            if (state[ri] < 0.0) {
                state[ri] = 0.0;  // Guard against floating-point rounding only
            }
            if (state[ri] < threshOcc) {
                forceUpdate = true;
            }
        }
    }

    // Loop over products: increase by s
    for (const auto pi : rxn.productIndices) {
        if (!fixedSpecies_[pi]) {
            state[pi] += s;
            if (state[pi] <= threshOcc) {
                forceUpdate = true;
            }
        }
    }

    return forceUpdate;
}

void PsaSimulator::updateRxnRatesPsa(std::size_t irxn,
                                       std::vector<double>& propensities,
                                       std::vector<double>& scaling,
                                       double& aTot,
                                       const std::vector<double>& state,
                                       double poplevel,
                                       bool pScaleChecker,
                                       PropensityTree& propensityTree) const {
    // Faithful port of update_rxn_rates_psa() from network.cpp.
    // Recompute propensities only for reactions in the dependency list of irxn.

    for (const auto jrxn : rxnUpdateRxn_[irxn]) {
        double anew = rxnRateScaled(jrxn, state, poplevel, pScaleChecker, scaling[jrxn]);
        aTot += anew - propensities[jrxn];
        propensityTree.add(jrxn, anew - propensities[jrxn]);
        propensities[jrxn] = anew;
    }

    // Error check: recalculate if a_tot goes non-positive (floating point drift)
    if (aTot <= 0.0 && nReactions_ > 0) {
        aTot = 0.0;
        for (std::size_t i = 0; i < nReactions_; ++i) {
            aTot += propensities[i];
        }
        propensityTree.assign(propensities);
        if (aTot < 0.0) {
            aTot = 0.0;
        }
    }
}

std::size_t PsaSimulator::selectNextRxn(const PropensityTree& propensityTree,
                                       std::mt19937_64& rng) const {
    const double total = propensityTree.total();
    if (total <= 0.0) {
        return nReactions_;
    }

    std::uniform_real_distribution<double> dist(0.0, 1.0);
    double fraction = dist(rng);
    while (fraction == 0.0 || fraction == 1.0) {
        fraction = dist(rng);
    }
    return propensityTree.select(fraction * total);
}

void PsaSimulator::updateObservables(const std::vector<double>& state,
                                      std::vector<double>& obsValues) const {
    obsValues.resize(compiledGroups_.size());
    for (std::size_t g = 0; g < compiledGroups_.size(); ++g) {
        double val = 0.0;
        for (const auto& [idx, weight] : compiledGroups_[g].entries) {
            val += weight * state[idx];
        }
        obsValues[g] = val;
    }
}

OdeResult PsaSimulator::simulate(const OdeOptions& opts, double poplevel,
                                  bool pScaleChecker) {
    // Faithful port of init_adaptive_scaling_network() + adaptive_scaling_network()
    // from network.cpp, with exact periodic Fenwick/aTot rebuild (Hlavacek #123),
    // Sat/MM/Hill scaling, stop_if support, and observable-dependent functional rates.

    if (const auto decision = bng::compile::poplevelDecisionError(poplevel)) {
        throw std::runtime_error(*decision);
    }

    const std::vector<double> targetTimes = psaOutputTimes(opts);

    // Parse optional stop_if condition
    std::optional<ast::Expression> stopIfExpr;
    if (!opts.stopIf.empty()) {
        try {
            stopIfExpr = materializeTfunExpression(
                functionEvaluator_.expandFunctions(parser::parseExpression(opts.stopIf)));
        } catch (const std::exception& error) {
            throw std::runtime_error(
                "Failed to parse stop_if expression: " + std::string(error.what()));
        }
    }

    // Seed RNG
    std::mt19937_64 rng;
    if (opts.seed > 0) {
        rng.seed(opts.seed);
    } else {
        std::random_device rd;
        rng.seed(rd());
    }
    std::uniform_real_distribution<double> uniform(0.0, 1.0);

    bool hasFunctional = false;
    for (const auto& crxn : compiledRxns_) {
        if (crxn.usesObservables) {
            hasFunctional = true;
            break;
        }
    }

    std::unordered_map<std::string, std::size_t> obsNameToIndex;
    std::vector<double> currentObs(compiledGroups_.size(), 0.0);
    if (hasFunctional || stopIfExpr.has_value()) {
        obsNameToIndex.reserve(compiledGroups_.size());
        for (std::size_t g = 0; g < compiledGroups_.size(); ++g) {
            obsNameToIndex.emplace(compiledGroups_[g].name, g);
        }
    }

    double evalTime = opts.tStart;
    const auto dynResolver = [&](const std::string& name) -> double {
        if (name == "time" || name == "t") {
            return evalTime;
        }
        const auto obsIt = obsNameToIndex.find(name);
        if (obsIt != obsNameToIndex.end()) {
            return currentObs[obsIt->second];
        }
        return model_.getParameters().evaluate(name);
    };

    // Initialize concentration array and round to nearest integer
    std::vector<double> c(nSpecies_);
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        c[i] = std::round(network_.species.get(i).getAmount());
    }
    if (hasFunctional || stopIfExpr.has_value()) {
        updateObservables(c, currentObs);
    }

    auto stopConditionMet = [&](double checkTime, bool refreshObs) -> bool {
        if (!stopIfExpr.has_value()) return false;
        if (refreshObs) {
            updateObservables(c, currentObs);
        }
        evalTime = checkTime;
        try {
            return functionEvaluator_.evaluate(*stopIfExpr, dynResolver, checkTime) != 0.0;
        } catch (const std::exception& error) {
            throw std::runtime_error(
                "Failed to evaluate stop_if expression '" +
                opts.stopIf + "': " + error.what());
        }
    };

    auto evalPropensity = [&](std::size_t rxnIdx, double& rxnScaling) -> double {
        const auto& rxn = compiledRxns_[rxnIdx];
        if (!rxn.usesObservables) {
            return rxnRateScaled(rxnIdx, c, poplevel, pScaleChecker, rxnScaling);
        }
        if (rxn.rateLawKind != PsaRateLawKind::Elementary) {
            std::vector<double> evalArgs;
            evalArgs.reserve(rxn.rateLawArgExprs.size());
            for (const auto& argExpr : rxn.rateLawArgExprs) {
                const double v = functionEvaluator_.evaluate(argExpr, dynResolver);
                if (!std::isfinite(v)) {
                    throw std::runtime_error(
                        "PSA produced a non-finite functional rate argument for reaction " +
                        std::to_string(rxnIdx + 1));
                }
                evalArgs.push_back(v);
            }
            return computeScaledTypedPropensity(
                rxn.statFactor, rxn.reactantIndices, rxn.productIndices,
                fixedSpecies_, c, evalArgs, static_cast<int>(rxn.rateLawKind),
                poplevel, pScaleChecker, rxnScaling);
        }
        const double baseVal = functionEvaluator_.evaluate(*rxn.functionalExpr, dynResolver);
        if (!std::isfinite(baseVal)) {
            throw std::runtime_error(
                "PSA produced a non-finite functional rate coefficient for reaction " +
                std::to_string(rxnIdx + 1));
        }
        const double effRate = rxn.statFactor * baseVal;
        return computeScaledElementaryPropensity(
            effRate, rxn.reactantIndices, rxn.productIndices,
            c, poplevel, pScaleChecker, rxnScaling);
    };

    // Initialize scaling factor and propensity arrays
    std::vector<double> s(nReactions_, 1.0);
    std::vector<double> a(nReactions_, 0.0);
    double aTot = 0.0;
    for (std::size_t i = 0; i < nReactions_; ++i) {
        a[i] = evalPropensity(i, s[i]);
        aTot += a[i];
    }
    PropensityTree propensityTree;
    propensityTree.assign(a);

    double peakATot = aTot;
    std::size_t stepsSinceRebuild = 0;
    constexpr std::size_t kRebuildInterval = 1024;
    auto rebuildPropensityTotals = [&]() {
        double exactTotal = 0.0;
        for (std::size_t i = 0; i < nReactions_; ++i) {
            if (!std::isfinite(a[i]) || a[i] < 0.0) a[i] = 0.0;
            exactTotal += a[i];
        }
        aTot = exactTotal;
        propensityTree.assign(a);
        peakATot = aTot;
        stepsSinceRebuild = 0;
    };

    // === PREPARE OUTPUT ===

    OdeResult result;
    result.timePoints.reserve(targetTimes.size());
    result.concentrations.reserve(targetTimes.size());

    double t = opts.tStart;

    // Determine max simulation steps
    const double maxStep = (opts.maxSimStepsSpecified || opts.maxSimSteps > 0)
        ? static_cast<double>(opts.maxSimSteps)
        : std::numeric_limits<double>::max();

    double nSteps = 0.0;
    bool hitMaxSteps = false;
    bool hitStopCondition = false;

    if (stopIfExpr.has_value() && stopConditionMet(t, false)) {
        result.timePoints.push_back(t);
        result.concentrations.push_back(c);
        result.observables.resize(1);
        updateObservables(c, result.observables[0]);
        return result;
    }

    // === MAIN SIMULATION LOOP (adaptive_scaling_network) ===
    for (std::size_t step = 0; step < targetTimes.size(); ++step) {
        const double outputTime = targetTimes[step];
        double tRemain = outputTime - t;

        while (tRemain > 0.0) {
            // Check maxStep limit
            if (nSteps >= maxStep) {
                hitMaxSteps = true;
                break;
            }

            if (aTot <= 0.0) {
                if (stepsSinceRebuild > 0) {
                    rebuildPropensityTotals();
                }
                if (aTot <= 0.0) {
                    break;
                }
            }

            // Determine time to next reaction
            double rnd = uniform(rng);
            while (rnd == 0.0 || rnd == 1.0) {
                rnd = uniform(rng);
            }
            double tau = -std::log(rnd) / aTot;

            tRemain -= tau;

            // Don't fire the next reaction if it occurs past the current
            // integration endpoint
            if (tRemain < 0.0) break;

            // Select next reaction to fire
            std::size_t irxn = selectNextRxn(propensityTree, rng);
            if (irxn >= nReactions_ || a[irxn] <= 0.0) {
                // Guard against floating-point drift in Fenwick prefix sums
                rebuildPropensityTotals();
                if (aTot <= 0.0) break;
                irxn = selectNextRxn(propensityTree, rng);
                if (irxn >= nReactions_ || a[irxn] <= 0.0) {
                    // Fallback: linear scan for the last positive propensity
                    irxn = nReactions_;
                    for (std::size_t r = nReactions_; r-- > 0;) {
                        if (a[r] > 0.0) {
                            irxn = r;
                            break;
                        }
                    }
                    if (irxn == nReactions_) break;
                }
            }

            // Fire reaction by updating concentrations (PSA version)
            (void)updateConcentrationsPsa(irxn, c, s);
            nSteps += 1.0;

            // Update observables before refreshing functional rates / stop_if
            if (hasFunctional || stopIfExpr.has_value()) {
                updateObservables(c, currentObs);
            }

            if (stopIfExpr.has_value() && stopConditionMet(outputTime - tRemain, false)) {
                hitStopCondition = true;
                break;
            }

            // Update affected reaction rates
            if (!hasFunctional) {
                updateRxnRatesPsa(
                    irxn, a, s, aTot, c, poplevel, pScaleChecker,
                    propensityTree);
            } else {
                for (const auto jrxn : rxnUpdateRxn_[irxn]) {
                    const double anew = evalPropensity(jrxn, s[jrxn]);
                    const double delta = anew - a[jrxn];
                    aTot += delta;
                    propensityTree.add(jrxn, delta);
                    a[jrxn] = anew;
                }
            }

            ++stepsSinceRebuild;
            if (aTot > peakATot) {
                peakATot = aTot;
            }
            // Periodically rebuild exact Fenwick tree & aTot so floating-point
            // cancellation never permanently starves slow channels (Hlavacek #123).
            if (stepsSinceRebuild >= kRebuildInterval ||
                (peakATot > 0.0 && aTot < peakATot * 1e-2) ||
                (aTot <= 0.0 && nReactions_ > 0)) {
                rebuildPropensityTotals();
            }
        }

        if (hitMaxSteps || hitStopCondition) {
            t = outputTime - std::max(0.0, tRemain);
        } else {
            t = outputTime;
        }

        // Record state at this output time
        result.timePoints.push_back(
            hitMaxSteps || hitStopCondition ? t : outputTime);
        result.concentrations.push_back(c);

        if (!hitStopCondition && stopIfExpr.has_value() &&
            stopConditionMet(t, !hasFunctional)) {
            hitStopCondition = true;
        }

        if (hitMaxSteps || hitStopCondition) {
            break;
        }
    }

    // Fill remaining output points if we hit maxStep (stop_if ends at the stop point)
    if (!hitStopCondition) {
        while (result.timePoints.size() < targetTimes.size()) {
            result.timePoints.push_back(result.timePoints.back());
            result.concentrations.push_back(c);
        }
    }

    // Compute observables for each time point
    result.observables.resize(result.timePoints.size());
    for (std::size_t step = 0; step < result.timePoints.size(); ++step) {
        updateObservables(result.concentrations[step], result.observables[step]);
    }

    return result;
}

} // namespace bng::engine
