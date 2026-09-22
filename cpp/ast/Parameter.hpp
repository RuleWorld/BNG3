#pragma once

#include <string>
#include <optional>

#include "Expression.hpp"
#include "units/Unit.hpp"

namespace bng::ast {

class Parameter {
public:
    Parameter(std::string name, Expression expression);

    const std::string& getName() const;
    const Expression& getExpression() const;
    double getValue() const;
    bool hasValue() const;
    void setValue(double value);
    void clearValue();
    bool hasUnit() const;
    const std::optional<units::Unit>& getUnit() const;
    const std::string& getUnitName() const;
    void setUnit(units::Unit unit, std::string name);

private:
    std::string name_;
    Expression expression_;
    double value_;
    bool hasValue_;
    std::optional<units::Unit> unit_;
    std::string unitName_;
};

} // namespace bng::ast
