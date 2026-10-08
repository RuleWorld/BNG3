#include "BngsimAdapter.hpp"

#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

#include <bngsim/model_builder.hpp>

#include "BngsimCapability.hpp"

namespace bng::engine {

namespace {

std::string expressionForBngsim(const ast::Expression& expression,
                                const std::string& owner,
                                bngsim::ModelBuilder& builder,
                                std::size_t& tableIndex) {
    switch (expression.kind()) {
    case ast::ExpressionKind::Number:
    case ast::ExpressionKind::Identifier:
        return expression.toString();
    case ast::ExpressionKind::Unary:
        return "(" + expression.name() +
               expressionForBngsim(expression.args().front(), owner, builder, tableIndex) + ")";
    case ast::ExpressionKind::Binary:
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
        const std::string counter = bngsimTableCounterName(expression.args().front());
        const std::string syntheticName =
            owner + "__tfun" + std::to_string(tableIndex++);
        if (!expression.tableFilePath().empty()) {
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
    throw std::logic_error("Invalid expression reached BNGsim conversion after capability check");
}

} // namespace

std::unique_ptr<bngsim::NetworkModel> buildBngsimNetwork(
    const ast::Model& model,
    const GeneratedNetwork& network) {
    const auto check = checkBngsimLowering(model, network);
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

    for (const auto& function : model.getFunctions()) {
        std::size_t tableIndex = 0;
        builder.add_function(
            function.getName(),
            expressionForBngsim(function.getExpression(), function.getName(), builder, tableIndex));
    }

    for (std::size_t index = 0; index < network.reactions.size(); ++index) {
        const auto& reaction = network.reactions.all()[index];
        const auto context = bngsimReactionContext(index, reaction);
        const auto reactants = checkedBngsimIndices(
            reaction.getReactants(), network.species.size(), context);
        const auto products = checkedBngsimIndices(
            reaction.getProducts(), network.species.size(), context);
        const auto rate = resolveBngsimRateReference(model, reaction, index);

        bngsim::RateLawType type;
        if (rate.kind == BngsimRateKind::Parameter) {
            type = bngsim::RateLawType::Elementary;
        } else {
            type = bngsim::RateLawType::Functional;
        }

        builder.add_reaction(
            reactants,
            products,
            type,
            rate.name,
            reaction.getFactor(),
            true);
    }

    return std::make_unique<bngsim::NetworkModel>(builder.build());
}

} // namespace bng::engine
