#pragma once

#include <cmath>
#include <cctype>
#include <stdexcept>
#include <string>

#include "ast/Model.hpp"
#include "NetworkGenerator.hpp"

namespace bng::engine {

inline double delayedTime(const ast::Expression& expression, const ast::Model& model) {
    const double value = expression.evaluate([&](const std::string& name) {
        return model.getParameters().evaluate(name);
    });
    if (!std::isfinite(value) || value < 0.0) {
        throw std::runtime_error("Delayed reaction time must be finite and nonnegative");
    }
    return value;
}

inline bool containsDelayCall(const std::string& source) {
    for (std::size_t i = 0; i + 5 < source.size(); ++i) {
        if (std::tolower(static_cast<unsigned char>(source[i])) != 'd' ||
            std::tolower(static_cast<unsigned char>(source[i + 1])) != 'e' ||
            std::tolower(static_cast<unsigned char>(source[i + 2])) != 'l' ||
            std::tolower(static_cast<unsigned char>(source[i + 3])) != 'a' ||
            std::tolower(static_cast<unsigned char>(source[i + 4])) != 'y') continue;
        const bool leftBoundary = i == 0 ||
            !(std::isalnum(static_cast<unsigned char>(source[i - 1])) || source[i - 1] == '_');
        std::size_t next = i + 5;
        while (next < source.size() && std::isspace(static_cast<unsigned char>(source[next]))) ++next;
        if (leftBoundary && next < source.size() && source[next] == '(') return true;
    }
    return false;
}

inline void requireValidDelay(const ast::Expression& expression,
                              const ast::Model& model,
                              const std::string& backend) {
    const double value = delayedTime(expression, model);
    if (value > 0.0) {
        throw std::runtime_error("Delayed reactions are not supported by " + backend);
    }
}

inline bool expressionUsesDelay(const ast::Expression& expression) {
    if (expression.kind() == ast::ExpressionKind::Function &&
        expression.name() == "delay") return true;
    for (const auto& child : expression.args()) {
        if (expressionUsesDelay(child)) return true;
    }
    return false;
}

inline void requireNoDelayedRuleSemantics(const ast::Model& model,
                                          const std::string& backend);

inline void requireNoDelayedSemantics(const ast::Model& model,
                                      const GeneratedNetwork& network,
                                      const std::string& backend) {
    requireNoDelayedRuleSemantics(model, backend);
    for (const auto& reaction : network.reactions.all()) {
        if (reaction.getDelayExpression()) requireValidDelay(*reaction.getDelayExpression(), model, backend);
        if (reaction.getRateExpression() &&
            expressionUsesDelay(*reaction.getRateExpression())) {
            throw std::runtime_error("delay(x, tau) expressions are not supported by " + backend);
        }
        if (!reaction.getRateExpression() && containsDelayCall(reaction.getRateLaw())) {
            throw std::runtime_error("delay(x, tau) expressions are not supported by " + backend);
        }
    }
    for (const auto& function : model.getFunctions()) {
        if (expressionUsesDelay(function.getExpression())) {
            throw std::runtime_error("delay(x, tau) expressions are not supported by " + backend);
        }
    }
}

inline void requireNoExpressionDelaySemantics(
    const ast::Model& model, const GeneratedNetwork& network,
    const std::string& backend) {
    for (const auto& reaction : network.reactions.all()) {
        if (reaction.getRateExpression() &&
            expressionUsesDelay(*reaction.getRateExpression())) {
            throw std::runtime_error(
                "delay(x, tau) expressions are not supported by " + backend);
        }
        if (!reaction.getRateExpression() &&
            containsDelayCall(reaction.getRateLaw())) {
            throw std::runtime_error(
                "delay(x, tau) expressions are not supported by " + backend);
        }
    }
    for (const auto& function : model.getFunctions()) {
        if (expressionUsesDelay(function.getExpression())) {
            throw std::runtime_error(
                "delay(x, tau) expressions are not supported by " + backend);
        }
    }
}

inline void requireNoDelayedRuleSemantics(const ast::Model& model,
                                          const std::string& backend) {
    for (const auto& rule : model.getReactionRules()) {
        if (rule.getDelayExpression()) requireValidDelay(*rule.getDelayExpression(), model, backend);
        for (const auto& rate : rule.getRates()) {
            if (expressionUsesDelay(rate)) {
                throw std::runtime_error("delay(x, tau) expressions are not supported by " + backend);
            }
        }
    }
    for (const auto& function : model.getFunctions()) {
        if (expressionUsesDelay(function.getExpression())) {
            throw std::runtime_error("delay(x, tau) expressions are not supported by " + backend);
        }
    }
}

}  // namespace bng::engine
