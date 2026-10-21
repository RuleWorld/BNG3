#pragma once

#include <functional>
#include <optional>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

namespace bng::ast {

enum class ExpressionKind {
    Number,
    Identifier,
    Unary,
    Binary,
    Function,
    ObservableRef,
    TableFunction,
};

class Expression {
public:
    using FunctionResolver = std::function<double(
        const std::string&, const std::vector<double>&)>;
    using FunctionPredicate = std::function<bool(const std::string&)>;
    Expression();

    static Expression number(double value);
    static Expression identifier(std::string name);
    static Expression unary(std::string op, Expression operand);
    static Expression binary(std::string op, Expression lhs, Expression rhs);
    static Expression function(std::string name, std::vector<Expression> args);
    static Expression observableRef(std::string name, std::vector<Expression> args);
    static Expression tableFunction(std::vector<double> xValues,
                                     std::vector<double> yValues,
                                     std::string filePath,
                                     Expression counter,
                                     std::string method = "linear");

    double evaluate(const std::function<double(const std::string&)>& resolveIdentifier, double t = 0.0) const;
    double evaluateWithFunctions(
        const std::function<double(const std::string&)>& resolveIdentifier,
        double t, const FunctionResolver& resolveFunction) const;
    double evaluateWithFunctions(
        const std::function<double(const std::string&)>& resolveIdentifier,
        double t, const FunctionResolver& resolveFunction,
        const FunctionPredicate& isUserFunction) const;
    double evaluateLocal(const std::function<double(const std::string&)>& resolveIdentifier,
                         const std::unordered_map<std::string, double>& localContext,
                         double t = 0.0) const;
    bool checkLocalDependency(const std::set<std::string>& localNames) const;
    std::set<std::string> getDependencies() const;
    std::string toString() const;

    /// Render the expression as BNGL source.
    ///
    /// Identical to ``toString()`` except that a function call is written
    /// with the spelling the BNGL grammar accepts. The parser lower-cases
    /// function names, and the grammar's rate-law keywords are spelled
    /// 'Sat', 'MM', 'Hill', 'Arrhenius' and 'FunctionProduct', so the
    /// lower-cased spelling is read back as an ordinary identifier and the
    /// model cannot be executed again.
    std::string toBnglString() const;

    ExpressionKind kind() const { return kind_; }
    const std::string& name() const { return text_; }
    const std::vector<Expression>& args() const { return children_; }
    double numberValue() const { return numberValue_; }
    const std::vector<double>& tableXValues() const { return tableXValues_; }
    const std::vector<double>& tableYValues() const { return tableYValues_; }
    const std::string& tableFilePath() const { return tableFilePath_; }
    const std::string& tableMethod() const { return tableMethod_; }
    std::string tableFileKey() const;

private:
    std::string renderExpression(bool canonicalFunctionNames) const;

    ExpressionKind kind_;
    double numberValue_;
    std::string text_;
    std::vector<Expression> children_;
    std::vector<double> tableXValues_;
    std::vector<double> tableYValues_;
    std::string tableFilePath_;
    std::string tableMethod_;
};

class Function;

// Fold expression subtrees that are provably constant while retaining symbol
// references. The resolver may expand a user-defined call; recursive calls
// are left symbolic rather than expanded indefinitely.
using FunctionExpander = std::function<std::optional<Expression>(
    const std::string&, const std::vector<Expression>&)>;

Expression partialEvaluate(const Expression& expression,
                           const FunctionExpander& expandFunction = {});

// Model-aware overload. User-defined calls are expanded only when simplifying
// their bodies enables a fold; otherwise the call identity is preserved.
Expression partialEvaluate(const Expression& expression,
                           const std::vector<Function>& functions);

} // namespace bng::ast
