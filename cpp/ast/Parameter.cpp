#include "Parameter.hpp"

#include <utility>

namespace bng::ast {

Parameter::Parameter(std::string name, Expression expression)
    : name_(std::move(name)), expression_(std::move(expression)), value_(0.0), hasValue_(false) {}

const std::string& Parameter::getName() const {
    return name_;
}

const Expression& Parameter::getExpression() const {
    return expression_;
}

double Parameter::getValue() const {
    return value_;
}

bool Parameter::hasValue() const {
    return hasValue_;
}

void Parameter::setValue(double value) {
    value_ = value;
    hasValue_ = true;
}

void Parameter::clearValue() {
    value_ = 0.0;
    hasValue_ = false;
}

bool Parameter::hasUnit() const {
    return unit_.has_value();
}

const std::optional<units::Unit>& Parameter::getUnit() const {
    return unit_;
}

const std::string& Parameter::getUnitName() const {
    return unitName_;
}

void Parameter::setUnit(units::Unit unit, std::string name) {
    unit_ = std::move(unit);
    unitName_ = std::move(name);
}

} // namespace bng::ast
