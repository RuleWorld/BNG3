#include "BngsimAdapter.hpp"

#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>

#include <bngsim/model_builder.hpp>

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

} // namespace

std::unique_ptr<bngsim::NetworkModel> buildBngsimNetwork(
    const ast::Model& model,
    const GeneratedNetwork& network) {
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

    // BNGsim observables are weighted generated-species sums. Exact generated
    // species-name matching is safe; wildcard/pattern matching needs a future
    // semantic observer bridge and therefore fails closed.
    if (!model.getObservables().empty()) {
        std::unordered_map<std::string, int> speciesByName;
        for (std::size_t index = 0; index < network.species.size(); ++index) {
            speciesByName.emplace(network.species.get(index).getSpeciesGraph().toString(),
                                  static_cast<int>(index));
        }
        for (const auto& observable : model.getObservables()) {
            std::vector<std::pair<int, double>> entries;
            for (const auto& pattern : observable.getPatterns()) {
                const auto found = speciesByName.find(pattern);
                if (found == speciesByName.end()) {
                    throw std::runtime_error(
                        "BNGsim adapter rejected observable '" + observable.getName() +
                        "': pattern matching requires semantic observer bridge ('" + pattern + "')");
                }
                entries.emplace_back(found->second, 1.0);
            }
            builder.add_observable(observable.getName(), entries);
        }
    }

    for (const auto& function : model.getFunctions()) {
        builder.add_function(function.getName(), function.getExpression().toString());
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
