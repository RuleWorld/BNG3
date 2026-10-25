#pragma once

#include <algorithm>
#include <functional>
#include <unordered_set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "Model.hpp"

namespace bng::ast {

// Evaluates AST expressions with the model's declared user functions. The
// expression parser can represent a user function call as either Function or
// ObservableRef, so the evaluator resolves declared function names explicitly
// and leaves actual observable references to the caller's identifier resolver.
class ModelFunctionEvaluator {
public:
    explicit ModelFunctionEvaluator(const ast::Model& model) : model_(model) {
        const auto& functions = model_.getFunctions();
        for (std::size_t index = 0; index < functions.size(); ++index) {
            functionIndex_.emplace(functions[index].getName(), index);
        }
    }

    double evaluate(
        const ast::Expression& expression,
        const std::function<double(const std::string&)>& resolveIdentifier,
        double time = 0.0,
        const ast::Expression::DelayedEvaluator& evaluateDelayed = {}) const {
        const auto expandedExpression = expandFunctions(expression);
        std::vector<std::size_t> callStack;
        ast::Expression::FunctionResolver resolveFunction;
        const ast::Expression::FunctionPredicate isUserFunction =
            [this](const std::string& name) {
                return functionIndex_.find(name) != functionIndex_.end();
            };

        std::function<double(const std::string&)> resolveSymbol;
        resolveFunction = [&](const std::string& name,
                              const std::vector<double>& arguments) -> double {
            const auto index = functionIndex_.find(name);
            if (index == functionIndex_.end()) {
                if (arguments.empty()) return resolveIdentifier(name);
                throw std::runtime_error("Unknown function '" + name + "'");
            }

            const auto functionIndex = index->second;
            const auto& function = model_.getFunctions()[functionIndex];
            if (arguments.size() != function.getArgs().size()) {
                throw std::runtime_error(
                    "Function '" + name + "' expects " +
                    std::to_string(function.getArgs().size()) + " arguments, got " +
                    std::to_string(arguments.size()));
            }
            if (std::find(callStack.begin(), callStack.end(), functionIndex) !=
                callStack.end()) {
                throw std::runtime_error(
                    "Recursive function dependency at '" + name + "'");
            }

            std::unordered_map<std::string, double> localArguments;
            localArguments.reserve(arguments.size());
            for (std::size_t argument = 0; argument < arguments.size(); ++argument) {
                localArguments.emplace(function.getArgs()[argument],
                                       arguments[argument]);
            }

            const auto resolveLocalIdentifier = [&](const std::string& symbol) {
                const auto local = localArguments.find(symbol);
                if (local != localArguments.end()) return local->second;
                return resolveSymbol(symbol);
            };

            callStack.push_back(functionIndex);
            try {
                const double result = function.getExpression().evaluateWithFunctions(
                    resolveLocalIdentifier, time, resolveFunction, isUserFunction,
                    evaluateDelayed);
                callStack.pop_back();
                return result;
            } catch (...) {
                callStack.pop_back();
                throw;
            }
        };
        resolveSymbol = [&](const std::string& name) -> double {
            const auto index = functionIndex_.find(name);
            if (index != functionIndex_.end()) {
                const auto& function = model_.getFunctions()[index->second];
                if (!function.getArgs().empty()) {
                    throw std::runtime_error(
                        "Function '" + name + "' requires " +
                        std::to_string(function.getArgs().size()) + " arguments");
                }
                return resolveFunction(name, {});
            }
            return resolveIdentifier(name);
        };

        return expandedExpression.evaluateWithFunctions(
            resolveSymbol, time, resolveFunction, isUserFunction, evaluateDelayed);
    }

    // Expose the same hygienic argument substitution used by evaluate() to
    // callers that need to inspect a function body's expression tree (for
    // example, collecting method-of-steps delays).
    ast::Expression expandFunctions(const ast::Expression& expression) const {
        return expandFunctionCalls(expression);
    }

private:
    ast::Expression expandFunctionCalls(const ast::Expression& expression) const {
        std::vector<std::size_t> callStack;
        std::unordered_map<std::string, ast::Expression> locals;
        std::function<ast::Expression(const ast::Expression&)> expand;
        expand = [&](const ast::Expression& current) -> ast::Expression {
            const auto function = functionIndex_.find(current.name());
            if ((current.kind() == ast::ExpressionKind::Function ||
                 current.kind() == ast::ExpressionKind::ObservableRef) &&
                function != functionIndex_.end()) {
                const auto index = function->second;
                const auto& declaration = model_.getFunctions()[index];
                if (std::find(callStack.begin(), callStack.end(), index) !=
                    callStack.end()) {
                    throw std::runtime_error(
                        "Recursive function dependency at '" + current.name() + "'");
                }
                if (current.args().size() != declaration.getArgs().size()) {
                    throw std::runtime_error(
                        "Function '" + current.name() + "' expects " +
                        std::to_string(declaration.getArgs().size()) +
                        " arguments, got " + std::to_string(current.args().size()));
                }
                auto savedLocals = locals;
                for (std::size_t i = 0; i < current.args().size(); ++i) {
                    locals[declaration.getArgs()[i]] = expand(current.args()[i]);
                }
                callStack.push_back(index);
                auto expandedBody = expand(declaration.getExpression());
                callStack.pop_back();
                locals = std::move(savedLocals);
                return expandedBody;
            }
            if (current.kind() == ast::ExpressionKind::Identifier) {
                const auto local = locals.find(current.name());
                if (local != locals.end()) return local->second;
                const auto zeroArgFunction = functionIndex_.find(current.name());
                if (zeroArgFunction != functionIndex_.end() &&
                    model_.getFunctions()[zeroArgFunction->second].getArgs().empty()) {
                    const auto index = zeroArgFunction->second;
                    if (std::find(callStack.begin(), callStack.end(), index) !=
                        callStack.end()) {
                        throw std::runtime_error(
                            "Recursive function dependency at '" + current.name() + "'");
                    }
                    callStack.push_back(index);
                    auto body = expand(model_.getFunctions()[index].getExpression());
                    callStack.pop_back();
                    return body;
                }
                return current;
            }
            const auto& args = current.args();
            switch (current.kind()) {
            case ast::ExpressionKind::Number:
            case ast::ExpressionKind::Identifier:
                return current;
            case ast::ExpressionKind::Unary:
                return ast::Expression::unary(current.name(), expand(args.front()));
            case ast::ExpressionKind::Binary:
                return ast::Expression::binary(
                    current.name(), expand(args[0]), expand(args[1]));
            case ast::ExpressionKind::Function: {
                std::vector<ast::Expression> expanded;
                expanded.reserve(args.size());
                for (const auto& arg : args) expanded.push_back(expand(arg));
                return ast::Expression::function(current.name(), std::move(expanded));
            }
            case ast::ExpressionKind::ObservableRef: {
                std::vector<ast::Expression> expanded;
                expanded.reserve(args.size());
                for (const auto& arg : args) expanded.push_back(expand(arg));
                return ast::Expression::observableRef(current.name(), std::move(expanded));
            }
            case ast::ExpressionKind::TableFunction:
                return ast::Expression::tableFunction(
                    current.tableXValues(), current.tableYValues(),
                    current.tableFilePath(), expand(args.front()),
                    current.tableMethod());
            }
            throw std::runtime_error("Unsupported expression kind while expanding functions");
        };
        return expand(expression);
    }

    const ast::Model& model_;
    std::unordered_map<std::string, std::size_t> functionIndex_;
};

} // namespace bng::ast
