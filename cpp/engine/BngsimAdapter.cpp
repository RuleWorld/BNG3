#include "BngsimAdapter.hpp"

#include <cctype>
#include <cmath>
#include <filesystem>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

#include <bngsim/model_builder.hpp>

#include "parser/antlr_compat.hpp"
#include "antlr4-runtime.h"
#include "BNGLexer.h"
#include "BNGParser.h"
#include "core/Ullmann.hpp"
#include "parser/BNGAstVisitor.hpp"
#include "parser/PatternGraphBuilder.hpp"

namespace bng::engine {

namespace {

std::string reactionContext(std::size_t index, const ast::Rxn& reaction) {
    return "reaction " + std::to_string(index) +
           (reaction.getLabel().empty() ? std::string{} : " ('" + reaction.getLabel() + "')");
}

std::vector<int> checkedIndices(const std::vector<std::size_t>& indices,
                                std::size_t nSpecies,
                                const std::string& context) {
    std::vector<int> result;
    result.reserve(indices.size());
    for (const auto index : indices) {
        if (index >= nSpecies) {
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

std::vector<std::pair<int, double>> compileObservableEntries(
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

std::string tableCounterName(const ast::Expression& counter) {
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

std::string expressionForBngsim(const ast::Expression& expression,
                                const std::string& owner,
                                bngsim::ModelBuilder& builder,
                                std::size_t& tableIndex) {
    switch (expression.kind()) {
    case ast::ExpressionKind::Number:
    case ast::ExpressionKind::Identifier:
        return expression.toString();
    case ast::ExpressionKind::Unary:
        if (expression.args().size() != 1) {
            throw std::runtime_error("BNGsim adapter rejected malformed unary expression");
        }
        return "(" + expression.name() +
               expressionForBngsim(expression.args().front(), owner, builder, tableIndex) + ")";
    case ast::ExpressionKind::Binary:
        if (expression.args().size() != 2) {
            throw std::runtime_error("BNGsim adapter rejected malformed binary expression");
        }
        return "(" + expressionForBngsim(expression.args()[0], owner, builder, tableIndex) +
               " " + expression.name() + " " +
               expressionForBngsim(expression.args()[1], owner, builder, tableIndex) + ")";
    case ast::ExpressionKind::Function:
    case ast::ExpressionKind::ObservableRef: {
        std::ostringstream result;
        result << expression.name() << "(";
        for (std::size_t index = 0; index < expression.args().size(); ++index) {
            if (index != 0) result << ", ";
            result << expressionForBngsim(expression.args()[index], owner, builder, tableIndex);
        }
        result << ")";
        return result.str();
    }
    case ast::ExpressionKind::TableFunction: {
        if (expression.args().size() != 1) {
            throw std::runtime_error("BNGsim adapter rejected malformed TFUN expression");
        }
        const std::string counter = tableCounterName(expression.args().front());
        const std::string syntheticName =
            owner + "__tfun" + std::to_string(tableIndex++);
        if (!expression.tableFilePath().empty()) {
            if (!std::filesystem::path(expression.tableFilePath()).is_absolute()) {
                throw std::runtime_error(
                    "BNGsim adapter rejected TFUN: relative table path requires source-directory provenance");
            }
            builder.add_table_function_spec(
                syntheticName,
                expression.tableFilePath(),
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
    throw std::runtime_error("BNGsim adapter rejected unknown expression kind");
}

} // namespace

std::unique_ptr<bngsim::NetworkModel> buildBngsimNetwork(
    const ast::Model& model,
    const GeneratedNetwork& network) {
    // ModelBuilder currently has no BNGL compartment, energy-pattern, or
    // protocol surface. Reject these constructs before any partial model is
    // built; silently dropping them would produce a numerically valid but
    // scientifically different network.
    if (!model.getCompartments().empty()) {
        throw std::runtime_error(
            "BNGsim adapter rejected model: compartments require a volume-aware bridge");
    }
    if (!model.getEnergyPatterns().empty()) {
        throw std::runtime_error(
            "BNGsim adapter rejected model: energy patterns require an eBNGL rate bridge");
    }
    if (!model.getPopulationMaps().empty()) {
        throw std::runtime_error(
            "BNGsim adapter rejected model: population maps are not a generated-network feature");
    }
    if (!model.getSimulationProtocol().empty()) {
        throw std::runtime_error(
            "BNGsim adapter rejected model: simulation protocol requires a protocol bridge");
    }
    for (const auto& action : model.getActions()) {
        if (action.name != "generate_network") {
            throw std::runtime_error(
                "BNGsim adapter rejected model action '" + action.name +
                "': action execution requires a protocol bridge");
        }
    }

    bngsim::ModelBuilder builder;

    for (const auto& parameter : model.getParameters().all()) {
        const double value = model.getParameters().evaluate(parameter.getName());
        if (!std::isfinite(value)) {
            throw std::runtime_error(
                "BNGsim adapter rejected parameter '" + parameter.getName() +
                "': value is not finite");
        }
        builder.add_parameter(parameter.getName(), value);
    }

    for (const auto& species : network.species.all()) {
        builder.add_species(
            species.getSpeciesGraph().toString(),
            species.getAmount(),
            species.isConstant());
    }

    if (!model.getObservables().empty()) {
        for (const auto& observable : model.getObservables()) {
            auto& mutableModel = const_cast<ast::Model&>(model);
            builder.add_observable(
                observable.getName(),
                compileObservableEntries(mutableModel, network, observable));
        }
    }

    for (const auto& function : model.getFunctions()) {
        if (!function.getArgs().empty()) {
            throw std::runtime_error(
                "BNGsim adapter rejected function '" + function.getName() +
                "': function arguments require a local-function bridge");
        }
        std::size_t tableIndex = 0;
        builder.add_function(
            function.getName(),
            expressionForBngsim(function.getExpression(), function.getName(), builder, tableIndex));
    }

    for (std::size_t index = 0; index < network.reactions.size(); ++index) {
        const auto& reaction = network.reactions.all()[index];
        const std::string context = reactionContext(index, reaction);
        const auto reactants = checkedIndices(
            reaction.getReactants(), network.species.size(), context);
        const auto products = checkedIndices(
            reaction.getProducts(), network.species.size(), context);
        const auto& rateLaw = reaction.getRateLaw();

        bngsim::RateLawType type;
        if (model.getParameters().contains(rateLaw)) {
            type = bngsim::RateLawType::Elementary;
        } else {
            bool isFunction = false;
            for (const auto& function : model.getFunctions()) {
                if (function.getName() == rateLaw) {
                    isFunction = true;
                    break;
                }
            }
            if (!isFunction) {
                throw std::runtime_error(
                    "BNGsim adapter rejected " + context + ": rate law '" + rateLaw +
                    "' is not a direct parameter or function reference");
            }
            type = bngsim::RateLawType::Functional;
        }

        builder.add_reaction(
            reactants,
            products,
            type,
            rateLaw,
            reaction.getFactor(),
            true);
    }

    return std::make_unique<bngsim::NetworkModel>(builder.build());
}

} // namespace bng::engine
