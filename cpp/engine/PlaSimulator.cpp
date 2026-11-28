#include "PlaSimulator.hpp"
#include "DelayedSemanticsGuard.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <limits>
#include <map>
#include <numeric>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

#include "parser/antlr_compat.hpp"
#include "antlr4-runtime.h"
#include "BNGLexer.h"
#include "BNGParser.h"
#include "ast/ModelFunctionEvaluator.hpp"
#include "parser/BNGAstVisitor.hpp"
#include "parser/PatternGraphBuilder.hpp"
#include "core/Ullmann.hpp"
#include "compile/CompiledRateLaw.hpp"
#include "compile/TotalRate.hpp"
#include "io/NetWriter.hpp"

namespace bng::engine {

namespace {

double evaluateRateString(const std::string& rateStr,
                          const std::function<double(const std::string&)>& resolve) {
    return bng::compile::evaluateRateString(rateStr, resolve);
}

std::string stripPlaLocalTag(std::string rateLaw) {
    const auto localPos = rateLaw.find("|local:");
    if (localPos != std::string::npos) {
        rateLaw.erase(localPos);
    }
    return rateLaw;
}

bool isUnsupportedPlaTypedRateLaw(const std::string& rawRateLaw) {
    std::string lower = rawRateLaw;
    const auto first = lower.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return false;
    lower = lower.substr(first);
    std::transform(lower.begin(), lower.end(), lower.begin(),
                   [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    auto hasWordPrefix = [&](const std::string& kw) {
        if (lower.rfind(kw, 0) != 0) return false;
        if (lower.size() == kw.size()) return true;
        const char nextC = lower[kw.size()];
        return nextC == ' ' || nextC == '\t' || nextC == '\r' || nextC == '\n' || nextC == '(';
    };
    return hasWordPrefix("sat") || hasWordPrefix("mm") || hasWordPrefix("hill");
}

bool plaExprDependsOnTimeImpl(const ast::Expression& expression,
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
        case ast::ExpressionKind::Function:
            if (expression.name() == "time" && expression.args().empty()) {
                return true;
            }
            [[fallthrough]];
        case ast::ExpressionKind::Unary:
        case ast::ExpressionKind::Binary:
        case ast::ExpressionKind::ObservableRef:
        case ast::ExpressionKind::TableFunction:
            return std::any_of(
                expression.args().begin(), expression.args().end(),
                [&](const auto& child) {
                    return plaExprDependsOnTimeImpl(child, model);
                });
    }
    return false;
}

bool plaExprDependsOnTime(const ast::Expression& expression,
                          const ast::Model& model,
                          const ast::ModelFunctionEvaluator& fnEval) {
    try {
        return plaExprDependsOnTimeImpl(fnEval.expandFunctions(expression), model);
    } catch (const std::exception&) {
        return plaExprDependsOnTimeImpl(expression, model);
    }
}

bool plaExprUsesObservableImpl(const ast::Expression& expression,
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
                    return plaExprUsesObservableImpl(child, obsNames);
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
                    return plaExprUsesObservableImpl(child, obsNames);
                });
    }
    return false;
}

bool plaExprUsesObservable(const ast::Expression& expression,
                           const ast::ModelFunctionEvaluator& fnEval,
                           const std::unordered_set<std::string>& obsNames) {
    if (obsNames.empty()) return false;
    try {
        return plaExprUsesObservableImpl(fnEval.expandFunctions(expression), obsNames);
    } catch (const std::exception&) {
        return plaExprUsesObservableImpl(expression, obsNames);
    }
}

std::string resolvePlaBaseRateString(
    const ast::Rxn& rxn,
    const std::function<double(const std::string&)>& paramResolver) {
    const auto& originRuleName = rxn.getOriginRuleName();
    if (!originRuleName.empty()) {
        const bool isReverse = originRuleName.rfind("_reverse__", 0) == 0;
        std::string ruleBase = isReverse
            ? originRuleName.substr(std::string("_reverse__").size())
            : originRuleName;
        if (!ruleBase.empty() && ruleBase[0] == '_' && ruleBase != "_reverse") {
            ruleBase = ruleBase.substr(1);
        }
        const std::string derivedParamName = isReverse
            ? ("__reverse__" + ruleBase + "_local1")
            : ("__" + ruleBase + "_local1");
        try {
            (void)paramResolver(derivedParamName);
            return derivedParamName;
        } catch (const std::exception&) {
        }
    }
    return stripPlaLocalTag(rxn.getRateLaw());
}

std::vector<RxnClass> classifyReactionsForTau(const std::vector<double>& a,
                                              double tau,
                                              const PlaConfig& config) {
    std::vector<RxnClass> classes(a.size(), RxnClass::ExactStochastic);
    for (std::size_t r = 0; r < a.size(); ++r) {
        const double expectedFirings = a[r] * tau;
        if (!std::isfinite(expectedFirings) || expectedFirings <= 0.0) {
            classes[r] = RxnClass::ExactStochastic;
        } else if (expectedFirings < config.apx1) {
            classes[r] = RxnClass::ExactStochastic;
        } else if (expectedFirings < config.gg1) {
            classes[r] = RxnClass::Poisson;
        } else {
            classes[r] = RxnClass::Deterministic;
        }
    }
    return classes;
}

std::vector<double> plaOutputTimes(const OdeOptions& opts) {
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

// ===== PlaConfig =====

PlaConfig PlaConfig::parse(const std::string& configStr) {
    PlaConfig config;

    // Split by '|'
    std::vector<std::string> parts;
    std::string current;
    for (char c : configStr) {
        if (c == '|') {
            parts.push_back(current);
            current.clear();
        } else {
            current += c;
        }
    }
    if (!current.empty()) parts.push_back(current);

    // Part 1: Method
    if (!parts.empty()) {
        const auto& m = parts[0];
        if (m == "fEuler" || m == "feuler") config.method = Method::fEuler;
        else if (m == "midpt" || m == "midpoint") config.method = Method::Midpoint;
        else if (m == "rk4" || m == "RK4") config.method = Method::RK4;
        else config.method = Method::fEuler;
    }

    // Part 2: Check type + basis
    if (parts.size() > 1) {
        const auto& check = parts[1];
        if (check.find("pre-neg") != std::string::npos) config.checkType = CheckType::PreNeg;
        else if (check.find("pre-eps") != std::string::npos) config.checkType = CheckType::PreEps;
        else if (check.find("post-neg") != std::string::npos) config.checkType = CheckType::PostNeg;
        else if (check.find("post-eps") != std::string::npos) config.checkType = CheckType::PostEps;
        else if (check.find("fixed") != std::string::npos) config.checkType = CheckType::Fixed;

        if (check.find(":rb") != std::string::npos) config.basis = Basis::ReactionBased;
        else config.basis = Basis::SpeciesBased;
    }

    // Part 3: Parameters
    if (parts.size() > 2) {
        // Split by ','
        std::istringstream paramStream(parts[2]);
        std::string param;
        while (std::getline(paramStream, param, ',')) {
            auto eqPos = param.find('=');
            if (eqPos == std::string::npos) continue;
            std::string key = param.substr(0, eqPos);
            std::string val = param.substr(eqPos + 1);
            try {
                if (key == "eps") config.eps = std::stod(val);
                else if (key == "p") config.p = std::stod(val);
                else if (key == "q") config.q = std::stod(val);
                else if (key == "w") config.w = std::stod(val);
                else if (key == "tau") config.fixedTau = std::stod(val);
                else if (key == "apx1") config.apx1 = std::stod(val);
                else if (key == "gg1") config.gg1 = std::stod(val);
            } catch (...) {}
        }
    }

    return config;
}

// ===== PlaSimulator =====

PlaSimulator::PlaSimulator(const ast::Model& model, const GeneratedNetwork& network)
    : model_(model), network_(network) {
    requireNoDelayedSemantics(model_, network_, "PLA");
    if (model_.getEventFormatVersion().has_value()) {
        throw std::runtime_error(ast::kUnsupportedEventExecutionMessage);
    }
    compile();
    compileGroups();
}

void PlaSimulator::compile() {
    nSpecies_ = network_.species.size();
    fixedSpecies_.resize(nSpecies_, false);

    for (std::size_t i = 0; i < nSpecies_; ++i) {
        fixedSpecies_[i] = network_.species.get(i).isConstant();
    }

    const auto resolver = [&](const std::string& name) -> double {
        return model_.getParameters().evaluate(name);
    };

    ast::ModelFunctionEvaluator fnEval(model_);
    std::unordered_set<std::string> obsNames;
    obsNames.reserve(model_.getObservables().size());
    for (const auto& obs : model_.getObservables()) {
        obsNames.insert(obs.getName());
    }

    compiledRxns_.clear();
    for (const auto& rxn : network_.reactions.all()) {
        if (bng::compile::isTotalRateReaction(model_, rxn.getOriginRuleName()) ||
            bng::compile::isAbsoluteFluxReaction(model_, rxn)) {
            throw std::runtime_error(
                "PLA does not support TotalRate or absolute-flux reactions; "
                "failing closed.");
        }
        CompiledReaction crxn;
        crxn.reactantIndices = rxn.getReactants();
        crxn.productIndices = rxn.getProducts();

        // Apply compartment volume unit_conversion scaling (matching OdeIntegrator / BNG2)
        double unitScale = 1.0;
        const auto unitFactor =
            bng::io::NetWriter::computeUnitConversionFactor(rxn, model_, network_);
        if (unitFactor.has_value()) {
            unitScale = *unitFactor;
        }
        crxn.statFactor = rxn.getFactor() * unitScale;

        const std::string baseRateStr = resolvePlaBaseRateString(rxn, resolver);
        if (isUnsupportedPlaTypedRateLaw(baseRateStr)) {
            throw std::runtime_error(
                "PLA does not support Sat/MM/Hill rate laws; failing closed.");
        }

        std::optional<ast::Expression> parsedRate;
        try {
            parsedRate = parser::parseExpression(baseRateStr);
        } catch (const std::exception&) {
        }

        if (parsedRate.has_value()) {
            if (plaExprDependsOnTime(*parsedRate, model_, fnEval)) {
                throw std::runtime_error(
                    "PLA does not support explicitly time-dependent rate laws");
            }
            if (plaExprUsesObservable(*parsedRate, fnEval, obsNames)) {
                // Sentinel: dynamically evaluated from current observables in simulate().
                crxn.rateConstant = std::numeric_limits<double>::quiet_NaN();
            } else {
                const double val = fnEval.evaluate(*parsedRate, resolver);
                if (!std::isfinite(val)) {
                    throw std::runtime_error(
                        "PLA encountered a non-finite reaction rate constant");
                }
                crxn.rateConstant = val;
            }
        } else {
            const double val = evaluateRateString(baseRateStr, resolver);
            if (!std::isfinite(val)) {
                throw std::runtime_error(
                    "PLA encountered a non-finite reaction rate constant");
            }
            crxn.rateConstant = val;
        }

        // Compute stoichiometry
        std::map<std::size_t, int> stoichMap;
        for (auto idx : crxn.reactantIndices) stoichMap[idx] -= 1;
        for (auto idx : crxn.productIndices) stoichMap[idx] += 1;
        for (auto& [idx, coeff] : stoichMap) {
            if (coeff != 0) crxn.stoich.push_back({idx, coeff});
        }

        compiledRxns_.push_back(std::move(crxn));
    }
}

void PlaSimulator::compileGroups() {
    compiledGroups_.clear();
    auto& mutableModel = const_cast<ast::Model&>(model_);

    struct CachedObservablePattern {
        BNGcore::PatternGraph graph;
        std::string compartment;
    };
    struct ParsedPatternInfo {
        const BNGcore::PatternGraph* graph = nullptr;
        std::string compartment;
        std::string quantifier;
        int quantifierThreshold = 0;
        bool hasQuantifier = false;
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
            compiledGroups_.push_back(std::move(group));
            continue;
        }

        // Parse and cache each observable pattern ONCE outside the species loop
        // with treatUnspecifiedBondAsWildcard = false (matching OdeIntegrator).
        std::vector<ParsedPatternInfo> parsedPatterns;
        parsedPatterns.reserve(observable.getPatterns().size());
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
                    const auto firstNonWs = after.find_first_not_of(" \t");
                    if (firstNonWs == std::string::npos) continue;
                    after.erase(0, firstNonWs);
                    after.erase(after.find_last_not_of(" \t") + 1);
                    bool isInteger = !after.empty();
                    for (const char c : after) {
                        if (!std::isdigit(static_cast<unsigned char>(c))) {
                            isInteger = false;
                            break;
                        }
                    }
                    if (!isInteger) continue;

                    std::string before = cleanPattern.substr(0, pos);
                    const auto lastNonWs = before.find_last_not_of(" \t");
                    if (lastNonWs == std::string::npos) continue;
                    before.erase(lastNonWs + 1);
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
                        continue;
                    }
                    auto graph = bng::parser::buildPatternGraph(species, mutableModel, false);
                    auto compartment = bng::parser::extractSpeciesCompartment(species);
                    cacheIt = parsedObservableCache.emplace(
                        cleanPattern,
                        CachedObservablePattern{std::move(graph), std::move(compartment)}).first;
                }
                parsedPatterns.push_back({&cacheIt->second.graph,
                                          cacheIt->second.compartment,
                                          std::move(quantifier),
                                          quantifierThreshold,
                                          hasQuantifier});
            } catch (...) {}
        }

        for (std::size_t speciesIndex = 0; speciesIndex < network_.species.size(); ++speciesIndex) {
            std::size_t weight = 0;
            const auto& speciesObj = network_.species.get(speciesIndex);
            const auto& targetGraph = speciesObj.getSpeciesGraph().getGraph();
            const auto& speciesCompartment = speciesObj.getCompartment();

            for (const auto& parsedPattern : parsedPatterns) {
                const auto& pattern = *parsedPattern.graph;
                const auto& patternCompartment = parsedPattern.compartment;
                bool compartmentMatches = true;
                if (!patternCompartment.empty()) {
                    bool patternHasMoleculeCompartment = false;
                    for (auto it = pattern.begin(); it != pattern.end(); ++it) {
                        if (!(*it)->get_compartment().empty()) {
                            patternHasMoleculeCompartment = true;
                            break;
                        }
                    }
                    if (!patternHasMoleculeCompartment &&
                        speciesCompartment != patternCompartment) {
                        compartmentMatches = false;
                    }
                }

                std::size_t matchCount = 0;
                if (compartmentMatches) {
                    BNGcore::UllmannSGIso matcher(pattern, targetGraph);
                    BNGcore::List<BNGcore::Map> maps;
                    matcher.find_maps(maps);
                    for (auto mapIt = maps.begin(); mapIt != maps.end(); ++mapIt) {
                        bool valid = true;
                        for (auto pnIt = pattern.begin(); pnIt != pattern.end(); ++pnIt) {
                            auto* target = mapIt->mapf(*pnIt);
                            if (!target) { valid = false; break; }
                            if (!((*pnIt)->get_state() == target->get_state())) {
                                valid = false;
                                break;
                            }
                            const bool patternIsMol = ((*pnIt)->in_degree() == 0);
                            const bool targetIsMol = (target->in_degree() == 0);
                            if (patternIsMol != targetIsMol) { valid = false; break; }
                            if (patternIsMol) {
                                const auto& pc = (*pnIt)->get_compartment();
                                if (!pc.empty() && target->get_compartment() != pc) {
                                    valid = false;
                                    break;
                                }
                            }
                        }
                        if (valid) ++matchCount;
                    }
                }

                if (parsedPattern.hasQuantifier && observable.getType() == "Species") {
                    bool passes = false;
                    const int matchCountInt = static_cast<int>(matchCount);
                    if (parsedPattern.quantifier == ">") passes = matchCountInt > parsedPattern.quantifierThreshold;
                    else if (parsedPattern.quantifier == "<") passes = matchCountInt < parsedPattern.quantifierThreshold;
                    else if (parsedPattern.quantifier == ">=") passes = matchCountInt >= parsedPattern.quantifierThreshold;
                    else if (parsedPattern.quantifier == "<=") passes = matchCountInt <= parsedPattern.quantifierThreshold;
                    else if (parsedPattern.quantifier == "==") passes = matchCountInt == parsedPattern.quantifierThreshold;
                    else if (parsedPattern.quantifier == "!=") passes = matchCountInt != parsedPattern.quantifierThreshold;
                    matchCount = passes ? 1 : 0;
                } else if (observable.getType() == "Species" && matchCount > 0) {
                    matchCount = 1;
                }
                weight += matchCount;
            }
            if (weight > 0) group.entries.push_back({speciesIndex, static_cast<double>(weight)});
        }
        compiledGroups_.push_back(std::move(group));
    }
}

double PlaSimulator::computePropensity(const CompiledReaction& rxn, const std::vector<double>& state) const {
    // Discrete reactant combinatorics: count ALL preceding occurrences of
    // reactantIndices[i] (not only adjacent elements, handling A + B + A -> C).
    double prop = rxn.statFactor * rxn.rateConstant;

    for (std::size_t i = 0; i < rxn.reactantIndices.size(); ++i) {
        const std::size_t idx = rxn.reactantIndices[i];
        if (idx >= state.size()) {
            return 0.0;
        }
        const double offset = static_cast<double>(
            std::count(rxn.reactantIndices.begin(),
                       rxn.reactantIndices.begin() + static_cast<std::ptrdiff_t>(i),
                       idx));
        prop *= std::max(0.0, state[idx] - offset);
    }

    return std::max(0.0, prop);
}

void PlaSimulator::computeAllPropensities(const std::vector<double>& state, std::vector<double>& a) const {
    a.resize(compiledRxns_.size());
    for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
        a[r] = computePropensity(compiledRxns_[r], state);
    }
}

double PlaSimulator::computeTotalPropensity(const std::vector<double>& a) const {
    return std::accumulate(a.begin(), a.end(), 0.0);
}

double PlaSimulator::computeTau(const std::vector<double>& state, const std::vector<double>& a,
                                 const PlaConfig& config) const {
    if (config.fixedTau > 0.0) return config.fixedTau;

    double a0 = computeTotalPropensity(a);
    if (a0 <= 0.0) return std::numeric_limits<double>::infinity();

    // Adaptive tau calculation (Cao et al. 2006) in O(R + S) via scatter-accumulation
    // over reaction stoichiometry entries (eliminating the O(S * R) nested scan).
    std::vector<double> mu(nSpecies_, 0.0);
    std::vector<double> sigma2(nSpecies_, 0.0);

    for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
        const double ar = a[r];
        if (ar <= 0.0) continue;
        for (const auto& [idx, coeff] : compiledRxns_[r].stoich) {
            if (idx < nSpecies_ && !fixedSpecies_[idx]) {
                const double c = static_cast<double>(coeff);
                mu[idx] += c * ar;
                sigma2[idx] += c * c * ar;
            }
        }
    }

    double tauMin = std::numeric_limits<double>::infinity();
    const double eps = config.eps;

    // Do NOT skip species with state[s] <= 0.0: zero-order synthesis (0 -> A)
    // and buffered sources ($A -> B) produce into initially empty species.
    for (std::size_t s = 0; s < nSpecies_; ++s) {
        if (fixedSpecies_[s]) continue;
        const double absMu = std::abs(mu[s]);
        if (absMu < 1e-30 && sigma2[s] < 1e-30) continue;

        const double bound = std::max(eps * std::max(state[s], 0.0), 1.0);
        const double bound_mu = (absMu > 0.0)
            ? (bound / absMu)
            : std::numeric_limits<double>::infinity();
        const double bound_sigma = (sigma2[s] > 0.0)
            ? ((bound * bound) / sigma2[s])
            : std::numeric_limits<double>::infinity();

        const double tau_s = std::min(bound_mu, bound_sigma);
        tauMin = std::min(tauMin, tau_s);
    }

    // Don't let tau be too small or remain infinite when reactions are active
    const double exactTau = 1.0 / a0;
    if (!std::isfinite(tauMin) || tauMin < config.apx1 * exactTau) {
        tauMin = exactTau;
    }

    return tauMin;
}

std::vector<RxnClass> PlaSimulator::classifyReactions(const std::vector<double>& a,
                                                       const PlaConfig& config) const {
    return classifyReactionsForTau(a, 1.0, config);
}

void PlaSimulator::fireReactionsEuler(std::vector<double>& state, const std::vector<double>& a,
                                       const std::vector<RxnClass>& classes, double tau,
                                       std::mt19937& rng) const {
    for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
        if (a[r] <= 0.0) continue;

        const double mean = a[r] * tau;
        if (!std::isfinite(mean)) {
            throw std::runtime_error("PLA produced non-finite expected reaction firings");
        }
        if (mean <= 0.0) continue;

        double firings = 0.0;

        switch (classes[r]) {
            case RxnClass::ExactStochastic:
            case RxnClass::Poisson: {
                if (mean < 20.0) {
                    std::poisson_distribution<std::int64_t> poisson(mean);
                    firings = static_cast<double>(poisson(rng));
                } else {
                    std::normal_distribution<double> normal(mean, std::sqrt(mean));
                    const double draw = std::round(normal(rng));
                    firings = (std::isfinite(draw) && draw > 0.0) ? draw : 0.0;
                }
                break;
            }
            case RxnClass::Langevin: {
                const double noise = std::sqrt(mean);
                std::normal_distribution<double> normal(0.0, 1.0);
                const double draw = std::round(mean + noise * normal(rng));
                firings = (std::isfinite(draw) && draw > 0.0) ? draw : 0.0;
                break;
            }
            case RxnClass::Deterministic: {
                if (mean < 1.0) {
                    // Guard against rounding small expected firings to 0 even if gg1 < 1.
                    std::poisson_distribution<std::int64_t> poisson(mean);
                    firings = static_cast<double>(poisson(rng));
                } else {
                    firings = std::round(mean);
                }
                break;
            }
        }

        // Apply stoichiometry changes in double precision (no 32-bit int overflow UB).
        if (firings > 0.0) {
            for (const auto& [idx, coeff] : compiledRxns_[r].stoich) {
                if (!fixedSpecies_[idx]) {
                    state[idx] += static_cast<double>(coeff) * firings;
                }
            }
        }
    }
}

bool PlaSimulator::checkNegativePopulations(const std::vector<double>& state) const {
    for (std::size_t s = 0; s < nSpecies_; ++s) {
        if (!fixedSpecies_[s] && state[s] < -1e-9) return true;
    }
    return false;
}

void PlaSimulator::clampNegatives(std::vector<double>& state) const {
    for (std::size_t s = 0; s < nSpecies_; ++s) {
        if (state[s] < 0.0) state[s] = 0.0;
    }
}

void PlaSimulator::updateObservables(const std::vector<double>& state,
                                      std::vector<double>& obsValues) const {
    obsValues.resize(compiledGroups_.size(), 0.0);
    for (std::size_t g = 0; g < compiledGroups_.size(); ++g) {
        double val = 0.0;
        for (const auto& [idx, weight] : compiledGroups_[g].entries) {
            val += weight * state[idx];
        }
        obsValues[g] = val;
    }
}

OdeResult PlaSimulator::simulate(const OdeOptions& opts, const PlaConfig& config) {
    if (config.method != PlaConfig::Method::fEuler) {
        throw std::runtime_error(
            "PLA currently supports only fEuler integration method (midpt and rk4 are not implemented); failing closed.");
    }
    if (config.basis != PlaConfig::Basis::SpeciesBased) {
        throw std::runtime_error(
            "PLA currently supports only species-based (:sb) leaping (reaction-based :rb is not implemented); failing closed.");
    }

    const std::vector<double> targetTimes = plaOutputTimes(opts);
    const double tStart = opts.tStart;
    const double tEnd = opts.tEnd;
    const double minTauFloor = 1e-15 * std::max(1.0, std::abs(tEnd - tStart));
    const double shrink = (config.w > 0.0 && config.w < 1.0) ? config.w : 0.5;

    // Prepare dynamic functional-rate evaluator if any reaction references observables
    bool hasFunctional = false;
    for (const auto& crxn : compiledRxns_) {
        if (std::isnan(crxn.rateConstant)) {
            hasFunctional = true;
            break;
        }
    }

    ast::ModelFunctionEvaluator fnEval(model_);
    std::vector<std::optional<ast::Expression>> functionalExprs;
    std::unordered_map<std::string, std::size_t> obsNameToIndex;
    std::vector<double> currentObs(compiledGroups_.size(), 0.0);
    if (hasFunctional) {
        obsNameToIndex.reserve(compiledGroups_.size());
        for (std::size_t g = 0; g < compiledGroups_.size(); ++g) {
            obsNameToIndex.emplace(compiledGroups_[g].name, g);
        }
        const auto paramResolver = [&](const std::string& name) -> double {
            return model_.getParameters().evaluate(name);
        };
        functionalExprs.resize(compiledRxns_.size());
        const auto& rawRxns = network_.reactions.all();
        for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
            if (!std::isnan(compiledRxns_[r].rateConstant)) continue;
            const std::string baseRateStr = resolvePlaBaseRateString(rawRxns[r], paramResolver);
            functionalExprs[r] = fnEval.expandFunctions(parser::parseExpression(baseRateStr));
        }
    }

    const auto dynResolver = [&](const std::string& name) -> double {
        const auto obsIt = obsNameToIndex.find(name);
        if (obsIt != obsNameToIndex.end()) {
            return currentObs[obsIt->second];
        }
        return model_.getParameters().evaluate(name);
    };

    auto computeStepPropensities = [&](const std::vector<double>& currentState,
                                       std::vector<double>& aOut) {
        if (!hasFunctional) {
            computeAllPropensities(currentState, aOut);
            return;
        }
        updateObservables(currentState, currentObs);
        aOut.resize(compiledRxns_.size());
        for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
            const auto& rxn = compiledRxns_[r];
            if (!functionalExprs[r].has_value()) {
                aOut[r] = computePropensity(rxn, currentState);
                continue;
            }
            const double baseVal = fnEval.evaluate(*functionalExprs[r], dynResolver);
            if (!std::isfinite(baseVal)) {
                throw std::runtime_error(
                    "PLA produced a non-finite functional rate coefficient for reaction " +
                    std::to_string(r + 1));
            }
            double prop = rxn.statFactor * baseVal;
            for (std::size_t i = 0; i < rxn.reactantIndices.size(); ++i) {
                const std::size_t idx = rxn.reactantIndices[i];
                if (idx >= currentState.size()) {
                    prop = 0.0;
                    break;
                }
                const double offset = static_cast<double>(
                    std::count(rxn.reactantIndices.begin(),
                               rxn.reactantIndices.begin() + static_cast<std::ptrdiff_t>(i),
                               idx));
                prop *= std::max(0.0, currentState[idx] - offset);
            }
            aOut[r] = std::max(0.0, prop);
        }
    };

    // Initialize state
    std::vector<double> state(nSpecies_);
    for (std::size_t i = 0; i < nSpecies_; ++i) {
        state[i] = network_.species.get(i).getAmount();
    }

    // Random number generator
    std::mt19937 rng(opts.seed > 0 ? opts.seed : std::random_device{}());

    OdeResult result;
    result.timePoints.reserve(targetTimes.size());
    result.concentrations.reserve(targetTimes.size());
    result.observables.reserve(targetTimes.size());

    std::vector<double> obsValues;
    std::vector<double> a;
    std::vector<double> savedState;

    double t = tStart;
    bool systemInactive = false;

    for (std::size_t outIdx = 0; outIdx < targetTimes.size(); ++outIdx) {
        const double nextOutputTime = targetTimes[outIdx];

        while (!systemInactive && t < nextOutputTime) {
            computeStepPropensities(state, a);

            const double a0 = computeTotalPropensity(a);
            if (!std::isfinite(a0)) {
                throw std::runtime_error("PLA produced non-finite total propensity");
            }
            if (a0 <= 0.0) {
                systemInactive = true;
                t = tEnd;
                break;
            }

            // Compute initial trial tau outside the rollback retry loop so that
            // tau *= shrink is preserved across retries instead of overwritten.
            double tau = computeTau(state, a, config);
            if (!std::isfinite(tau) || tau <= 0.0) {
                systemInactive = true;
                t = tEnd;
                break;
            }

            if (t + tau > nextOutputTime) {
                tau = nextOutputTime - t;
            }

            savedState = state;
            bool accepted = false;
            constexpr int kMaxRollbackAttempts = 64;
            for (int attempt = 0; attempt < kMaxRollbackAttempts; ++attempt) {
                state = savedState;
                const auto classes = classifyReactionsForTau(a, tau, config);
                fireReactionsEuler(state, a, classes, tau, rng);

                if (!checkNegativePopulations(state)) {
                    accepted = true;
                    break;
                }
                tau *= shrink;
                if (tau <= minTauFloor) {
                    break;
                }
            }

            if (!accepted) {
                // Exact single-step Gillespie SSA fallback: strictly preserves
                // non-negativity and mass conservation when leaping overshoots.
                state = savedState;
                std::uniform_real_distribution<double> u01(0.0, 1.0);
                double r1 = u01(rng);
                while (r1 <= 0.0 || r1 >= 1.0) {
                    r1 = u01(rng);
                }
                const double ssaTau = -std::log(r1) / a0;
                if (t + ssaTau > nextOutputTime) {
                    t = nextOutputTime;
                    break;
                }
                const double target = u01(rng) * a0;
                double cum = 0.0;
                std::size_t chosen = compiledRxns_.size();
                std::size_t lastPositive = compiledRxns_.size();
                for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
                    if (a[r] > 0.0) {
                        lastPositive = r;
                    }
                    cum += a[r];
                    if (cum >= target && a[r] > 0.0) {
                        chosen = r;
                        break;
                    }
                }
                if (chosen == compiledRxns_.size()) {
                    chosen = lastPositive;
                }
                if (chosen < compiledRxns_.size()) {
                    for (const auto& [idx, coeff] : compiledRxns_[chosen].stoich) {
                        if (!fixedSpecies_[idx]) {
                            state[idx] += static_cast<double>(coeff);
                        }
                    }
                }
                clampNegatives(state);
                t += ssaTau;
                continue;
            }

            clampNegatives(state);
            t += tau;
        }

        // Always emit every scheduled output point (including when a0 == 0).
        result.timePoints.push_back(nextOutputTime);
        result.concentrations.push_back(state);
        updateObservables(state, obsValues);
        result.observables.push_back(obsValues);
    }

    return result;
}

} // namespace bng::engine
