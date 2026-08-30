#pragma once

#include <functional>
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
    double evaluateLocal(const std::function<double(const std::string&)>& resolveIdentifier,
                         const std::unordered_map<std::string, double>& localContext,
                         double t = 0.0) const;
    bool checkLocalDependency(const std::set<std::string>& localNames) const;
    std::set<std::string> getDependencies() const;
    std::string toString() const;

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
    ExpressionKind kind_;
    double numberValue_;
    std::string text_;
    std::vector<Expression> children_;
    std::vector<double> tableXValues_;
    std::vector<double> tableYValues_;
    std::string tableFilePath_;
    std::string tableMethod_;
};

} // namespace bng::ast
