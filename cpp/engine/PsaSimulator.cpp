#include "PsaSimulator.hpp"
#include "DelayedSemanticsGuard.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <iostream>
#include <limits>
#include <optional>
#include <random>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

#include "parser/antlr_compat.hpp"
#include "antlr4-runtime.h"
#include "BNGLexer.h"
#include "BNGParser.h"
#include "parser/BNGAstVisitor.hpp"
#include "parser/PatternGraphBuilder.hpp"
#include "core/Ullmann.hpp"
#include "compile/CompiledRateLaw.hpp"
#include "io/NetWriter.hpp"
#include "ast/ReactionRule.hpp"
#include "compile/TotalRate.hpp"

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

bool expressionUsesObservable(const ast::Expression& expression,
                              const ast::ModelFunctionEvaluator& fnEval,
                              const std::unordered_set<std::string>& obsNames) {
    if (obsNames.empty()) return false;
    try {
        const auto expanded = fnEval.expandFunctions(expression);
        return expressionUsesObservableImpl(expanded, obsNames);
    } catch (const std::exception&) {
        return expressionUsesObservableImpl(expression, obsNames);
    }
}

std::string resolveBaseRateString(
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
    return stripLocalRateTag(rxn.getRateLaw());
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

    for (const auto& rxn : network_.reactions.all()) {
        CompiledReaction crxn;
        crxn.reactantIndices = rxn.getReactants();
        crxn.productIndices = rxn.getProducts();

        const auto& originRuleName = rxn.getOriginRuleName();
        crxn.isAbsoluteFlux = bng::compile::isAbsoluteFluxReaction(model_, rxn);
        crxn.isTotalRate = bng::compile::isTotalRateReaction(model_, originRuleName) ||
                           crxn.isAbsoluteFlux;

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

        // Compute scalar prefactor (unit_conversion * stat_factor) once in double
        // precision so it is never squared or corrupted by string precedence.
        double prefactor = 1.0;
        if (!crxn.isTotalRate) {
            const auto unitFactor =
                bng::io::NetWriter::computeUnitConversionFactor(
                    rxn, model_, network_);
            if (unitFactor.has_value()) {
                prefactor *= *unitFactor;
            }
            prefactor *= rxn.getFactor();
        }
        // statFactor stores the full prefactor (unit_conversion * rxn.getFactor(),
        // or 1.0 for TotalRate/absolute-flux) for dynamic functional-rate evaluation.
        crxn.statFactor = prefactor;

        const std::string baseRateStr = resolveBaseRateString(rxn, paramResolver);
        std::optional<ast::Expression> parsedRate;
        try {
            parsedRate = parser::parseExpression(baseRateStr);
        } catch (const std::exception&) {
            // Keep the narrow legacy parser for old rate spellings that the
            // shared BNGL expression parser does not accept.
        }
        if (parsedRate.has_value()) {
            if (expressionDependsOnTime(*parsedRate, model_, functionEvaluator_)) {
                throw std::runtime_error(
                    "PSA does not support explicitly time-dependent rate laws");
            }
            if (expressionUsesObservable(*parsedRate, functionEvaluator_, obsNames)) {
                // Sentinel: dynamically evaluated from current observables in simulate().
                crxn.rateConstant = std::numeric_limits<double>::quiet_NaN();
            } else {
                const double baseValue =
                    functionEvaluator_.evaluate(*parsedRate, paramResolver);
                crxn.rateConstant = prefactor * baseValue;
            }
        } else {
            try {
                crxn.rateConstant = prefactor * evaluateRateString(baseRateStr, paramResolver);
            } catch (const std::exception&) {
                crxn.rateConstant = 0.0;
            }
        }

        compiledRxns_.push_back(crxn);
    }

    nReactions_ = compiledRxns_.size();
    compileGroups();
    createUpdateLists();
}

void PsaSimulator::compileGroups() {
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
            } catch (...) {
                // Skip patterns that fail to parse
            }
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
        if (std::isnan(compiledRxns_[r].rateConstant)) {
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

} // anonymous namespace

double PsaSimulator::rxnRateScaled(std::size_t rxnIdx,
                                     const std::vector<double>& state,
                                     double poplevel, bool pScaleChecker,
                                     double& scaling) const {
    // Faithful port of rxn_rate_scaled() from network.cpp (ELEMENTARY case).
    const auto& rxn = compiledRxns_[rxnIdx];
    const auto& reactants = rxn.reactantIndices;
    const auto& products = rxn.productIndices;
    const std::size_t nReactants = reactants.size();

    // Absolute SBML fluxes already include reactant dependence.  Authored
    // TotalRate rules still use finite-network reactant counts, with their
    // symmetry factor set to one during compilation.
    // A constant reactant is never consumed, so it does not limit an absolute
    // flux (see OdeIntegrator::computePropensity).
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

    // rxn.rateConstant already includes unit_conversion * statFactor (computed
    // once in compile()); do NOT multiply by rxn.statFactor a second time.
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
    // from network.cpp, with exact periodic Fenwick/aTot rebuild (Hlavacek #123)
    // and observable-dependent functional rate evaluation.

    const std::vector<double> targetTimes = psaOutputTimes(opts);

    // Seed RNG
    std::mt19937_64 rng;
    if (opts.seed > 0) {
        rng.seed(opts.seed);
    } else {
        std::random_device rd;
        rng.seed(rd());
    }
    std::uniform_real_distribution<double> uniform(0.0, 1.0);

    // Build dynamic functional-rate expressions only when needed
    bool hasFunctional = false;
    for (const auto& crxn : compiledRxns_) {
        if (std::isnan(crxn.rateConstant)) {
            hasFunctional = true;
            break;
        }
    }

    std::vector<std::optional<ast::Expression>> functionalExprs;
    std::unordered_map<std::string, std::size_t> obsNameToIndex;
    std::vector<double> currentObs(compiledGroups_.size(), 0.0);
    if (hasFunctional) {
        obsNameToIndex.reserve(compiledGroups_.size());
        for (std::size_t g = 0; g < compiledGroups_.size(); ++g) {
            obsNameToIndex.emplace(compiledGroups_[g].name, g);
        }
        auto paramResolver = [&](const std::string& name) -> double {
            return model_.getParameters().evaluate(name);
        };
        functionalExprs.resize(nReactions_);
        const auto& rawRxns = network_.reactions.all();
        for (std::size_t r = 0; r < nReactions_; ++r) {
            if (!std::isnan(compiledRxns_[r].rateConstant)) continue;
            const std::string baseRateStr = resolveBaseRateString(rawRxns[r], paramResolver);
            functionalExprs[r] = functionEvaluator_.expandFunctions(
                parser::parseExpression(baseRateStr));
        }
    }

    const auto dynResolver = [&](const std::string& name) -> double {
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
    if (hasFunctional) {
        updateObservables(c, currentObs);
    }

    auto evalPropensity = [&](std::size_t rxnIdx, double& rxnScaling) -> double {
        if (!hasFunctional || !functionalExprs[rxnIdx].has_value()) {
            return rxnRateScaled(rxnIdx, c, poplevel, pScaleChecker, rxnScaling);
        }
        const auto& rxn = compiledRxns_[rxnIdx];
        const double baseVal = functionEvaluator_.evaluate(*functionalExprs[rxnIdx], dynResolver);
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

            // Update observables before refreshing functional rates
            if (hasFunctional) {
                updateObservables(c, currentObs);
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

        if (hitMaxSteps || hitStopCondition) {
            break;
        }
    }

    // Fill remaining output points if we stopped early
    while (result.timePoints.size() < targetTimes.size()) {
        result.timePoints.push_back(result.timePoints.back());
        result.concentrations.push_back(c);
    }

    // Compute observables for each time point
    result.observables.resize(result.timePoints.size());
    for (std::size_t step = 0; step < result.timePoints.size(); ++step) {
        updateObservables(result.concentrations[step], result.observables[step]);
    }

    return result;
}

} // namespace bng::engine
