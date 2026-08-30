#include "ExpressionEval.hpp"

#include "Expression.hpp"

#include <stdexcept>

namespace bng::eval {

double evaluate(const bng::ast::Expression& expr, const Context& ctx) {
    if (!ctx.lookup) {
        throw std::invalid_argument("Expression evaluation requires a symbol resolver");
    }
    return expr.evaluate(ctx.lookup, ctx.time);
}

double evaluate(const bng::ast::Expression& expr,
                double time,
                const std::unordered_map<std::string, double>& symbols) {
    return evaluate(expr, Context {
        time,
        [&symbols](const std::string& name) -> double {
            const auto it = symbols.find(name);
            if (it == symbols.end()) {
                throw std::runtime_error("Unknown expression symbol '" + name + "'");
            }
            return it->second;
        }
    });
}

} // namespace bng::eval
