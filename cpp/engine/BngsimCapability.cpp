#include "BngsimCapability.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "parser/antlr_compat.hpp"
#include "antlr4-runtime.h"
#include "BNGLexer.h"
#include "BNGParser.h"
#include "core/Ullmann.hpp"
#include "parser/PatternGraphBuilder.hpp"

namespace bng::engine {

namespace {

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
    const ast::Expression& expression,
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
        collectExpressionBlockers(expression.args().front(), blockers);
        return;
    case ast::ExpressionKind::Binary:
        if (expression.args().size() != 2) {
            blockers.push_back("BNGsim adapter rejected malformed binary expression");
            return;
        }
        collectExpressionBlockers(expression.args()[0], blockers);
        collectExpressionBlockers(expression.args()[1], blockers);
        return;
    case ast::ExpressionKind::Function:
    case ast::ExpressionKind::ObservableRef:
        for (const auto& argument : expression.args()) {
            collectExpressionBlockers(argument, blockers);
        }
        return;
    case ast::ExpressionKind::TableFunction:
        if (expression.args().size() != 1) {
            blockers.push_back("BNGsim adapter rejected malformed TFUN expression");
            return;
        }
        try {
            (void)bngsimTableCounterName(expression.args().front());
        } catch (const std::exception& error) {
            blockers.push_back(error.what());
            return;
        }
        if (!expression.tableFilePath().empty()) {
            try {
                if (!std::filesystem::path(expression.tableFilePath()).is_absolute()) {
                    blockers.push_back(
                        "BNGsim adapter rejected TFUN: relative table path requires source-directory provenance");
                }
            } catch (const std::exception&) {
                blockers.push_back(
                    "BNGsim adapter rejected TFUN: relative table path requires source-directory provenance");
            }
        }
        return;
    }
    blockers.push_back("BNGsim adapter rejected unknown expression kind");
}

} // namespace

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

std::string bngsimTableCounterName(const ast::Expression& counter) {
    if (counter.kind() == ast::ExpressionKind::Identifier ||
        counter.kind() == ast::ExpressionKind::ObservableRef) {
        if (counter.name().empty()) {
            throw std::runtime_error("BNGsim adapter rejected TFUN: empty counter name");
        }
        return counter.name() == "t" ? "time" : counter.name();
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
    std::size_t index) {
    const auto& rateLaw = reaction.getRateLaw();
    const auto normalized = normalizeRateLaw(rateLaw);
    if (model.getParameters().contains(normalized)) {
        return {BngsimRateKind::Parameter, normalized};
    }
    for (const auto& function : model.getFunctions()) {
        if (function.getName() == normalized) {
            return {BngsimRateKind::Function, normalized};
        }
    }
    throw std::runtime_error(
        "BNGsim adapter rejected " + bngsimReactionContext(index, reaction) +
        ": rate law '" + rateLaw + "' is not a direct parameter or function reference");
}

BngsimLoweringCheck checkBngsimLowering(
    const ast::Model& model,
    const GeneratedNetwork& network) {
    BngsimLoweringCheck check;
    auto& mutableModel = const_cast<ast::Model&>(model);
    auto reject = [&](const std::string& blocker) {
        check.blockers.push_back(blocker);
    };

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
        collectExpressionBlockers(function.getExpression(), check.blockers);
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
            (void)resolveBngsimRateReference(model, reaction, index);
        } catch (const std::exception& error) {
            reject(error.what());
            break;
        }
    }

    check.supported = check.blockers.empty();
    return check;
}

} // namespace bng::engine
