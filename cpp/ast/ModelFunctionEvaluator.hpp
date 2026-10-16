#pragma once

#include <algorithm>
#include <functional>
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
        double time = 0.0) const {
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
                    resolveLocalIdentifier, time, resolveFunction, isUserFunction);
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

        return expression.evaluateWithFunctions(
            resolveSymbol, time, resolveFunction, isUserFunction);
    }

private:
    const ast::Model& model_;
    std::unordered_map<std::string, std::size_t> functionIndex_;
};

} // namespace bng::ast
