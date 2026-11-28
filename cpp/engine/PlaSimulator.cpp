#include "PlaSimulator.hpp"
#include "DelayedSemanticsGuard.hpp"
#include "ObservableProjection.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <limits>
#include <map>
#include <memory>
#include <numeric>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

#include "ast/ModelFunctionEvaluator.hpp"
#include "parser/BNGAstVisitor.hpp"
#include "compile/CompiledModel.hpp"
#include "compile/CompiledRateLaw.hpp"
#include "compile/TotalRate.hpp"
#include "io/NetWriter.hpp"
#include "io/TfunReader.hpp"

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

ast::Expression materializePlaTfunExpression(const ast::Expression& expr) {
    switch (expr.kind()) {
        case ast::ExpressionKind::Number:
        case ast::ExpressionKind::Identifier:
            return expr;
        case ast::ExpressionKind::Unary:
            return ast::Expression::unary(
                expr.name(), materializePlaTfunExpression(expr.args().front()));
        case ast::ExpressionKind::Binary:
            return ast::Expression::binary(
                expr.name(),
                materializePlaTfunExpression(expr.args()[0]),
                materializePlaTfunExpression(expr.args()[1]));
        case ast::ExpressionKind::Function: {
            std::vector<ast::Expression> args;
            args.reserve(expr.args().size());
            for (const auto& arg : expr.args()) {
                args.push_back(materializePlaTfunExpression(arg));
            }
            return ast::Expression::function(expr.name(), std::move(args));
        }
        case ast::ExpressionKind::ObservableRef: {
            std::vector<ast::Expression> args;
            args.reserve(expr.args().size());
            for (const auto& arg : expr.args()) {
                args.push_back(materializePlaTfunExpression(arg));
            }
            return ast::Expression::observableRef(expr.name(), std::move(args));
        }
        case ast::ExpressionKind::TableFunction: {
            if (expr.args().size() != 1) {
                throw std::runtime_error("TFUN expression must have one counter expression");
            }
            auto counter = materializePlaTfunExpression(expr.args().front());
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

std::vector<RxnClass> classifyReactionsForTau(const std::vector<double>& a,
                                              double tau,
                                              const PlaConfig& config) {
    std::vector<RxnClass> classes(a.size(), RxnClass::ExactStochastic);
    for (std::size_t r = 0; r < a.size(); ++r) {
        const double expectedFirings = a[r] * tau;
        if (!std::isfinite(expectedFirings) || expectedFirings <= 0.0) {
            classes[r] = RxnClass::ExactStochastic;
        } else if (std::sqrt(expectedFirings) > config.gg1) {
            classes[r] = RxnClass::Deterministic;
        } else if (expectedFirings > config.gg1) {
            classes[r] = RxnClass::Langevin;
        } else if (expectedFirings > config.apx1) {
            classes[r] = RxnClass::Poisson;
        } else {
            classes[r] = RxnClass::ExactStochastic;
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
    speciesG_.assign(nSpecies_, 1.0);

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

    // Build per-reaction derived rate maps from NetWriter (Arrhenius, scoped
    // rates, FunctionProduct, barrier patterns, driven reservoirs).
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

    compiledRxns_.clear();
    std::size_t rxnIndex = 0;
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

        // Fast path: per-reaction derived rates (Arrhenius, scoped rates, FunctionProduct)
        bool resolvedDerived = false;
        if (const auto rtIt = perRxnDerivedRuntimeRateConstants.find(rxnIndex);
            rtIt != perRxnDerivedRuntimeRateConstants.end()) {
            if (!std::isfinite(rtIt->second)) {
                throw std::runtime_error(
                    "PLA encountered a non-finite derived reaction rate constant");
            }
            crxn.rateConstant = rtIt->second;
            resolvedDerived = true;
        } else if (const auto fnIt = perRxnDerivedRateFunctions.find(rxnIndex);
                   fnIt != perRxnDerivedRateFunctions.end()) {
            if (plaExprDependsOnTime(fnIt->second, model_, fnEval)) {
                throw std::runtime_error(
                    "PLA does not support explicitly time-dependent rate laws");
            }
            const auto expanded = materializePlaTfunExpression(
                fnEval.expandFunctions(fnIt->second));
            if (plaExprUsesObservableImpl(expanded, obsNames)) {
                crxn.usesObservables = true;
                crxn.functionalExpr = expanded;
                crxn.rateConstant = std::numeric_limits<double>::quiet_NaN();
            } else {
                const double val = fnEval.evaluate(expanded, resolver);
                if (!std::isfinite(val)) {
                    throw std::runtime_error(
                        "PLA encountered a non-finite derived reaction rate constant");
                }
                crxn.rateConstant = val;
            }
            resolvedDerived = true;
        } else if (const auto drIt = perRxnDerivedRates.find(rxnIndex);
                   drIt != perRxnDerivedRates.end()) {
            if (!std::isfinite(drIt->second.second)) {
                throw std::runtime_error(
                    "PLA encountered a non-finite derived reaction rate constant");
            }
            crxn.rateConstant = drIt->second.second;
            resolvedDerived = true;
        }

        if (!resolvedDerived) {
            const std::string baseRateStr = stripPlaLocalTag(rxn.getRateLaw());
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
                const auto expanded = materializePlaTfunExpression(
                    fnEval.expandFunctions(*parsedRate));
                if (plaExprUsesObservableImpl(expanded, obsNames)) {
                    crxn.usesObservables = true;
                    crxn.functionalExpr = expanded;
                    crxn.rateConstant = std::numeric_limits<double>::quiet_NaN();
                } else {
                    const double val = fnEval.evaluate(expanded, resolver);
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
        }

        // Compute stoichiometry
        std::map<std::size_t, int> stoichMap;
        for (auto idx : crxn.reactantIndices) stoichMap[idx] -= 1;
        for (auto idx : crxn.productIndices) stoichMap[idx] += 1;
        for (auto& [idx, coeff] : stoichMap) {
            if (coeff != 0) crxn.stoich.push_back({idx, coeff});
        }

        // Update Cao et al. (2006) highest-order reaction factor g_i per reactant species
        const std::size_t totalReactants = crxn.reactantIndices.size();
        for (std::size_t ri = 0; ri < totalReactants; ++ri) {
            const std::size_t specIdx = crxn.reactantIndices[ri];
            if (specIdx >= nSpecies_) continue;
            const std::size_t mult = static_cast<std::size_t>(
                std::count(crxn.reactantIndices.begin(), crxn.reactantIndices.end(), specIdx));
            double gVal = 1.0;
            if (totalReactants == 1) {
                gVal = 1.0;
            } else if (totalReactants == 2) {
                gVal = (mult == 2) ? 3.0 : 2.0;
            } else if (totalReactants == 3) {
                gVal = (mult == 3) ? 5.5 : ((mult == 2) ? 4.5 : 3.0);
            } else if (totalReactants > 3) {
                gVal = static_cast<double>(totalReactants) +
                       0.5 * static_cast<double>(mult > 0 ? mult - 1 : 0);
            }
            if (gVal > speciesG_[specIdx]) {
                speciesG_[specIdx] = gVal;
            }
        }

        compiledRxns_.push_back(std::move(crxn));
        ++rxnIndex;
    }
}

void PlaSimulator::compileGroups() {
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
    // over reaction stoichiometry entries with species highest-order g_i factors.
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

        const double g = (s < speciesG_.size() && speciesG_[s] > 0.0) ? speciesG_[s] : 1.0;
        const double bound = std::max(eps * std::max(state[s], 0.0) / g, 1.0);
        const double bound_mu = (absMu > 0.0)
            ? (bound / absMu)
            : std::numeric_limits<double>::infinity();
        const double bound_sigma = (sigma2[s] > 0.0)
            ? ((bound * bound) / sigma2[s])
            : std::numeric_limits<double>::infinity();

        const double tau_s = std::min(bound_mu, bound_sigma);
        tauMin = std::min(tauMin, tau_s);
    }

    // Only fall back to 1/a0 when no species has non-zero drift or variance
    // (e.g. catalyst-only reactions); do NOT clamp small tau up to 1/a0, so
    // exact-stochastic regimes take true Gillespie SSA steps.
    if (!std::isfinite(tauMin)) {
        tauMin = 1.0 / a0;
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
    std::normal_distribution<double> normal01(0.0, 1.0);
    for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
        if (a[r] <= 0.0 || classes[r] == RxnClass::ExactStochastic) continue;

        const double mean = a[r] * tau;
        if (!std::isfinite(mean)) {
            throw std::runtime_error("PLA produced non-finite expected reaction firings");
        }
        if (mean <= 0.0) continue;

        double firings = 0.0;

        switch (classes[r]) {
            case RxnClass::ExactStochastic:
                break;
            case RxnClass::Poisson: {
                if (mean < 1e9) {
                    std::poisson_distribution<std::int64_t> poisson(mean);
                    firings = static_cast<double>(poisson(rng));
                } else {
                    const double draw = std::round(mean + std::sqrt(mean) * normal01(rng));
                    firings = (std::isfinite(draw) && draw > 0.0) ? draw : 0.0;
                }
                break;
            }
            case RxnClass::Langevin: {
                const double draw = std::round(mean + std::sqrt(mean) * normal01(rng));
                firings = (std::isfinite(draw) && draw > 0.0) ? draw : 0.0;
                break;
            }
            case RxnClass::Deterministic: {
                if (mean < 1.0) {
                    std::poisson_distribution<std::int64_t> poisson(mean);
                    firings = static_cast<double>(poisson(rng));
                } else {
                    firings = std::round(mean);
                }
                break;
            }
        }

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

bool PlaSimulator::checkSpeciesEps(const std::vector<double>& savedState,
                                   const std::vector<double>& newState,
                                   double eps, double wFactor) const {
    constexpr double kTol = 1e-9;
    for (std::size_t s = 0; s < nSpecies_; ++s) {
        if (fixedSpecies_[s]) continue;
        const double dX = std::abs(newState[s] - savedState[s]);
        const double g = (s < speciesG_.size() && speciesG_[s] > 0.0) ? speciesG_[s] : 1.0;
        const double bound = wFactor * eps * std::max(savedState[s], 0.0) / g;
        if (dX > bound && dX > (1.0 + kTol)) {
            return false;
        }
    }
    return true;
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
    if (!std::isfinite(config.eps) || config.eps <= 0.0 || config.eps > 1.0) {
        throw std::runtime_error("PLA eps must be finite and in (0, 1]");
    }
    if (!std::isfinite(config.fixedTau) || config.fixedTau < 0.0) {
        throw std::runtime_error("PLA tau must be finite and non-negative");
    }
    if (config.checkType == PlaConfig::CheckType::Fixed && config.fixedTau <= 0.0) {
        throw std::runtime_error("PLA fixed check mode requires a positive tau");
    }
    if (!std::isfinite(config.p) || config.p <= 0.0 || config.p >= 1.0) {
        throw std::runtime_error("PLA p must be finite and in (0, 1)");
    }
    if (!std::isfinite(config.q) || config.q < 1.0) {
        throw std::runtime_error("PLA q must be finite and >= 1");
    }
    if (!std::isfinite(config.w) || config.w <= 0.0 || config.w >= 1.0) {
        throw std::runtime_error("PLA w must be finite and in (0, 1)");
    }
    if (!std::isfinite(config.apx1) || config.apx1 < 0.0 ||
        !std::isfinite(config.gg1) || config.gg1 < 0.0) {
        throw std::runtime_error("PLA apx1 and gg1 must be finite and non-negative");
    }

    const std::vector<double> targetTimes = plaOutputTimes(opts);
    const double tStart = opts.tStart;
    const double tEnd = opts.tEnd;
    const double minTauFloor = 1e-15 * std::max(1.0, std::abs(tEnd - tStart));
    const double maxPostTau = std::max(std::abs(tEnd - tStart), 1.0);
    const bool useEpsPostcheck =
        config.checkType == PlaConfig::CheckType::PreEps ||
        config.checkType == PlaConfig::CheckType::PostEps;
    const bool usePostAdaptiveTau =
        config.fixedTau <= 0.0 &&
        (config.checkType == PlaConfig::CheckType::PostNeg ||
         config.checkType == PlaConfig::CheckType::PostEps);

    ast::ModelFunctionEvaluator fnEval(model_);

    // Parse optional stop_if condition
    std::optional<ast::Expression> stopIfExpr;
    if (!opts.stopIf.empty()) {
        try {
            stopIfExpr = materializePlaTfunExpression(
                fnEval.expandFunctions(parser::parseExpression(opts.stopIf)));
        } catch (const std::exception& error) {
            throw std::runtime_error(
                "Failed to parse stop_if expression: " + std::string(error.what()));
        }
    }

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

    double evalTime = tStart;
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

    auto stopConditionMet = [&](double checkTime, const std::vector<double>& currentState) -> bool {
        if (!stopIfExpr.has_value()) return false;
        updateObservables(currentState, currentObs);
        evalTime = checkTime;
        try {
            return fnEval.evaluate(*stopIfExpr, dynResolver, checkTime) != 0.0;
        } catch (const std::exception& error) {
            throw std::runtime_error(
                "Failed to evaluate stop_if expression '" +
                opts.stopIf + "': " + error.what());
        }
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
            if (!rxn.usesObservables || !rxn.functionalExpr.has_value()) {
                aOut[r] = computePropensity(rxn, currentState);
                continue;
            }
            const double baseVal = fnEval.evaluate(*rxn.functionalExpr, dynResolver);
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
    std::uniform_real_distribution<double> u01(0.0, 1.0);
    std::normal_distribution<double> normal01(0.0, 1.0);

    auto drawOpenUnit = [&]() -> double {
        double u = u01(rng);
        while (u <= 0.0 || u >= 1.0) {
            u = u01(rng);
        }
        return u;
    };

    auto applySingleReaction = [&](std::vector<double>& st, std::size_t rxnIdx) {
        if (rxnIdx >= compiledRxns_.size()) return;
        for (const auto& [idx, coeff] : compiledRxns_[rxnIdx].stoich) {
            if (!fixedSpecies_[idx]) {
                st[idx] += static_cast<double>(coeff);
            }
        }
    };

    auto canApplySingleReaction = [&](const std::vector<double>& st, std::size_t rxnIdx) -> bool {
        if (rxnIdx >= compiledRxns_.size()) return false;
        for (const auto& [idx, coeff] : compiledRxns_[rxnIdx].stoich) {
            if (!fixedSpecies_[idx] && st[idx] + static_cast<double>(coeff) < -1e-9) {
                return false;
            }
        }
        return true;
    };

    auto applyFirings = [&](const std::vector<double>& baseState,
                            const std::vector<double>& firings,
                            std::vector<double>& outState) {
        outState = baseState;
        for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
            const double k = firings[r];
            if (k <= 0.0) continue;
            for (const auto& [idx, coeff] : compiledRxns_[r].stoich) {
                if (!fixedSpecies_[idx]) {
                    outState[idx] += static_cast<double>(coeff) * k;
                }
            }
        }
    };

    auto stepExactSsa = [&](std::vector<double>& st,
                            const std::vector<double>& propensities,
                            double a0,
                            double maxDt,
                            double& dtOut) -> bool {
        const double ssaTau = -std::log(drawOpenUnit()) / a0;
        if (ssaTau > maxDt) {
            dtOut = maxDt;
            return false;
        }
        const double target = u01(rng) * a0;
        double cum = 0.0;
        std::size_t chosen = compiledRxns_.size();
        std::size_t lastPositive = compiledRxns_.size();
        for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
            if (propensities[r] > 0.0) {
                lastPositive = r;
            }
            cum += propensities[r];
            if (cum >= target && propensities[r] > 0.0) {
                chosen = r;
                break;
            }
        }
        if (chosen == compiledRxns_.size()) {
            chosen = lastPositive;
        }
        applySingleReaction(st, chosen);
        clampNegatives(st);
        dtOut = ssaTau;
        return true;
    };

    OdeResult result;
    result.timePoints.reserve(targetTimes.size());
    result.concentrations.reserve(targetTimes.size());
    result.observables.reserve(targetTimes.size());

    std::vector<double> obsValues;
    std::vector<double> a;
    std::vector<double> savedState;
    std::vector<double> firings(compiledRxns_.size(), 0.0);
    std::vector<bool> alreadyES(compiledRxns_.size(), false);

    double t = tStart;
    bool systemInactive = false;
    bool hitStopCondition = false;
    double postTau = 0.0;
    bool hasPostTau = false;

    if (stopIfExpr.has_value() && stopConditionMet(t, state)) {
        result.timePoints.push_back(t);
        result.concentrations.push_back(state);
        updateObservables(state, obsValues);
        result.observables.push_back(obsValues);
        return result;
    }

    for (std::size_t outIdx = 0; outIdx < targetTimes.size(); ++outIdx) {
        const double nextOutputTime = targetTimes[outIdx];

        while (!systemInactive && !hitStopCondition && t < nextOutputTime) {
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

            const double maxTau = nextOutputTime - t;
            double trialTau = 0.0;
            if (config.fixedTau > 0.0) {
                trialTau = config.fixedTau;
            } else if (usePostAdaptiveTau && hasPostTau) {
                trialTau = postTau;
            } else {
                trialTau = computeTau(state, a, config);
            }
            if (!std::isfinite(trialTau) || trialTau <= 0.0) {
                systemInactive = true;
                t = tEnd;
                break;
            }

            const bool wasCappedByOutput = (trialTau > maxTau);
            double tau = wasCappedByOutput ? maxTau : trialTau;

            auto classes = classifyReactionsForTau(a, tau, config);
            bool allES = true;
            for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
                if (a[r] > 0.0 && classes[r] != RxnClass::ExactStochastic) {
                    allES = false;
                    break;
                }
            }

            if (allES) {
                double dtTaken = 0.0;
                const bool fired = stepExactSsa(state, a, a0, maxTau, dtTaken);
                if (!fired) {
                    t = nextOutputTime;
                    break;
                }
                t += dtTaken;
                hasPostTau = false;
                if (stopIfExpr.has_value() && stopConditionMet(t, state)) {
                    hitStopCondition = true;
                    break;
                }
                continue;
            }

            // Harris & Clancy (2006) iterative ES waiting-time competition
            std::fill(alreadyES.begin(), alreadyES.end(), false);
            std::size_t esRxn = compiledRxns_.size();
            double tauES = std::numeric_limits<double>::infinity();
            bool fireES = false;
            bool esConsistent = false;
            while (!esConsistent) {
                esConsistent = true;
                allES = true;
                for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
                    if (a[r] <= 0.0) continue;
                    if (classes[r] == RxnClass::ExactStochastic) {
                        if (!alreadyES[r]) {
                            alreadyES[r] = true;
                            const double tauESr = -std::log(drawOpenUnit()) / a[r];
                            if (tauESr < tauES) {
                                tauES = tauESr;
                                esRxn = r;
                            }
                        }
                    } else {
                        allES = false;
                    }
                }
                if (tauES < tau || allES) {
                    tau = tauES;
                    fireES = true;
                    if (!allES) {
                        esConsistent = false;
                        auto newClasses = classifyReactionsForTau(a, tau, config);
                        for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
                            classes[r] = alreadyES[r] ? RxnClass::ExactStochastic : newClasses[r];
                        }
                    }
                }
            }

            if (allES) {
                if (tau <= maxTau && esRxn < compiledRxns_.size()) {
                    applySingleReaction(state, esRxn);
                    clampNegatives(state);
                    t += tau;
                    hasPostTau = false;
                    if (stopIfExpr.has_value() && stopConditionMet(t, state)) {
                        hitStopCondition = true;
                        break;
                    }
                    continue;
                }
                t = nextOutputTime;
                break;
            }

            // Fire all non-ES reactions over tau and record per-reaction counts
            savedState = state;
            std::fill(firings.begin(), firings.end(), 0.0);
            for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
                if (a[r] <= 0.0 || classes[r] == RxnClass::ExactStochastic) continue;
                const double mean = a[r] * tau;
                if (!std::isfinite(mean)) {
                    throw std::runtime_error("PLA produced non-finite expected reaction firings");
                }
                if (mean <= 0.0) continue;
                switch (classes[r]) {
                    case RxnClass::ExactStochastic:
                        break;
                    case RxnClass::Poisson: {
                        if (mean < 1e9) {
                            std::poisson_distribution<std::int64_t> poisson(mean);
                            firings[r] = static_cast<double>(poisson(rng));
                        } else {
                            const double draw = std::round(mean + std::sqrt(mean) * normal01(rng));
                            firings[r] = (std::isfinite(draw) && draw > 0.0) ? draw : 0.0;
                        }
                        break;
                    }
                    case RxnClass::Langevin: {
                        const double draw = std::round(mean + std::sqrt(mean) * normal01(rng));
                        firings[r] = (std::isfinite(draw) && draw > 0.0) ? draw : 0.0;
                        break;
                    }
                    case RxnClass::Deterministic: {
                        if (mean < 1.0) {
                            std::poisson_distribution<std::int64_t> poisson(mean);
                            firings[r] = static_cast<double>(poisson(rng));
                        } else {
                            firings[r] = std::round(mean);
                        }
                        break;
                    }
                }
            }

            applyFirings(savedState, firings, state);
            auto postleapPasses = [&](const std::vector<double>& candidate) -> bool {
                if (checkNegativePopulations(candidate)) return false;
                if (useEpsPostcheck && !checkSpeciesEps(savedState, candidate, config.eps, 1.0)) {
                    return false;
                }
                return true;
            };

            bool accepted = postleapPasses(state);
            bool wasRejected = !accepted;
            if (!accepted) {
                fireES = false;
                constexpr int kMaxRollbackAttempts = 64;
                const double pShrink = config.p;
                for (int attempt = 0; attempt < kMaxRollbackAttempts; ++attempt) {
                    const double oldTau = tau;
                    tau *= pShrink;
                    if (tau <= minTauFloor) {
                        break;
                    }
                    for (std::size_t r = 0; r < compiledRxns_.size(); ++r) {
                        if (a[r] <= 0.0 || classes[r] == RxnClass::ExactStochastic) continue;
                        const double kOld = firings[r];
                        if (classes[r] == RxnClass::Poisson) {
                            if (kOld <= 0.0) {
                                firings[r] = 0.0;
                            } else if (kOld < 1e9) {
                                std::binomial_distribution<std::int64_t> binom(
                                    static_cast<std::int64_t>(kOld), pShrink);
                                firings[r] = static_cast<double>(binom(rng));
                            } else {
                                const double stdBridge = std::sqrt(kOld * pShrink * (1.0 - pShrink));
                                const double draw = std::round(pShrink * kOld + stdBridge * normal01(rng));
                                firings[r] = (std::isfinite(draw) && draw > 0.0) ? draw : 0.0;
                            }
                        } else if (classes[r] == RxnClass::Langevin) {
                            const double stdBridge = std::sqrt(
                                std::max(0.0, a[r] * oldTau * pShrink * (1.0 - pShrink)));
                            const double draw = std::round(pShrink * kOld + stdBridge * normal01(rng));
                            firings[r] = (std::isfinite(draw) && draw > 0.0) ? draw : 0.0;
                        } else if (classes[r] == RxnClass::Deterministic) {
                            const double newMean = a[r] * tau;
                            firings[r] = (newMean >= 1.0) ? std::round(newMean) : 0.0;
                        }
                    }
                    applyFirings(savedState, firings, state);
                    if (postleapPasses(state)) {
                        accepted = true;
                        break;
                    }
                }
            }

            if (!accepted) {
                // Exact single-step Gillespie SSA fallback
                state = savedState;
                double dtTaken = 0.0;
                const bool fired = stepExactSsa(state, a, a0, maxTau, dtTaken);
                if (!fired) {
                    t = nextOutputTime;
                    break;
                }
                t += dtTaken;
                hasPostTau = false;
                if (stopIfExpr.has_value() && stopConditionMet(t, state)) {
                    hitStopCondition = true;
                    break;
                }
                continue;
            }

            if (fireES && esRxn < compiledRxns_.size() && canApplySingleReaction(state, esRxn)) {
                applySingleReaction(state, esRxn);
            }

            if (usePostAdaptiveTau && ((!wasCappedByOutput && !fireES) || wasRejected)) {
                if (config.checkType == PlaConfig::CheckType::PostNeg) {
                    postTau = std::min(std::max(tau * config.q, minTauFloor), maxPostTau);
                } else {
                    if (checkSpeciesEps(savedState, state, config.eps, config.w)) {
                        postTau = std::min(std::max(tau * config.q, minTauFloor), maxPostTau);
                    } else {
                        const double pp = 0.5 * (1.0 + config.p);
                        postTau = std::max(tau * pp, minTauFloor);
                    }
                }
                hasPostTau = true;
            }

            clampNegatives(state);
            t += tau;
            if (stopIfExpr.has_value() && stopConditionMet(t, state)) {
                hitStopCondition = true;
                break;
            }
        }

        const double recordTime = hitStopCondition ? t : nextOutputTime;
        result.timePoints.push_back(recordTime);
        result.concentrations.push_back(state);
        updateObservables(state, obsValues);
        result.observables.push_back(obsValues);

        if (!hitStopCondition && stopIfExpr.has_value() &&
            stopConditionMet(recordTime, state)) {
            hitStopCondition = true;
        }
        if (hitStopCondition) {
            break;
        }
    }

    return result;
}

} // namespace bng::engine
