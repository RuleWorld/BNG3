#include "ParameterList.hpp"

#include <stdexcept>
#include <unordered_set>
#include <utility>

namespace bng::ast {

void ParameterList::add(Parameter parameter) {
    // Names can be referenced transitively, including forward references. A
    // declaration change invalidates both cached values and time dependence.
    // Defer the linear reset so adding a block of declarations stays linear.
    cachesDirty_ = true;
    const auto& name = parameter.getName();
    const auto existing = indexByName_.find(name);
    if (existing != indexByName_.end()) {
        parameters_[existing->second] = std::move(parameter);
        if (existing->second < valuesStale_.size()) {
            valuesStale_[existing->second] = true;
        }
        return;
    }

    indexByName_[name] = parameters_.size();
    parameters_.push_back(std::move(parameter));
    timeDependent_.push_back(kUnknown);
    valuesStale_.push_back(true);
}

void ParameterList::refreshCaches() const {
    if (!cachesDirty_) return;
    // Retain the memoized values: they are the last values evaluated against a
    // settled model and direct getValue() consumers depend on them. Marking them
    // stale is enough for evaluate() to recompute, and avoids zeroing live
    // values that export writers read without re-evaluating.
    valuesStale_.assign(parameters_.size(), true);
    timeDependent_.assign(parameters_.size(), kUnknown);
    cachesDirty_ = false;
}

bool ParameterList::hasFreshValue(std::size_t index) const {
    return index < valuesStale_.size() && !valuesStale_[index] &&
           index < parameters_.size() && parameters_[index].hasValue();
}

namespace {

// True when the expression reads the simulation clock. `time` and `t` are
// both bound to the `t` argument by Expression::evaluate, and a zero-arg
// `time()`/`t()` call is handled as the same binding, so both spellings and
// both the identifier and function node kinds must be recognized here.
bool referencesTime(const Expression& expression) {
    if ((expression.kind() == ExpressionKind::Identifier ||
         expression.kind() == ExpressionKind::Function) &&
        (expression.name() == "time" || expression.name() == "t")) {
        return true;
    }
    for (const auto& child : expression.args()) {
        if (referencesTime(child)) {
            return true;
        }
    }
    return false;
}

} // namespace
bool ParameterList::isTimeDependent(const std::string& name) const {
    const auto it = indexByName_.find(name);
    return it != indexByName_.end() && isTimeDependent(it->second);
}

bool ParameterList::expressionIsTimeDependent(const Expression& expression) const {
    std::unordered_set<std::string> visiting;
    const auto mayDependOnTime = [&](const auto& self, const Expression& candidate) -> bool {
        if (referencesTime(candidate)) return true;

        switch (candidate.kind()) {
        case ExpressionKind::Number:
            return false;
        case ExpressionKind::Identifier: {
            const auto iter = indexByName_.find(candidate.name());
            if (iter == indexByName_.end()) return true;
            if (isTimeDependent(iter->second)) return true;
            if (!visiting.insert(candidate.name()).second) return true;
            const bool dependent = self(self, parameters_[iter->second].getExpression());
            visiting.erase(candidate.name());
            return dependent;
        }
        case ExpressionKind::Function:
        case ExpressionKind::ObservableRef:
        case ExpressionKind::TableFunction:
            // A non-clock call can still resolve to a user function or table
            // lookup with runtime state. The volume bridge has no proof for
            // those semantics, so leave them outside its static subset.
            return true;
        case ExpressionKind::Unary:
        case ExpressionKind::Binary:
            for (const auto& child : candidate.args()) {
                if (self(self, child)) return true;
            }
            return false;
        }
        return true;
    };
    return mayDependOnTime(mayDependOnTime, expression);
}


bool ParameterList::isTimeDependent(std::size_t index) const {
    refreshCaches();
    if (index >= timeDependent_.size()) {
        return false;
    }
    if (timeDependent_[index] == kUnknown) {
        std::vector<bool> visiting(parameters_.size(), false);
        computeTimeDependent(index, visiting);
    }
    return timeDependent_[index] == kTimeDependent;
}

bool ParameterList::computeTimeDependent(std::size_t index, std::vector<bool>& visiting) const {
    if (timeDependent_[index] != kUnknown) {
        return timeDependent_[index] == kTimeDependent;
    }
    // A dependency cycle makes the parameter's value undefined; the existing
    // evaluator reports that when it recurses, so treat it as time-dependent
    // here rather than caching a value that cycle-detection will reject.
    if (visiting[index]) {
        timeDependent_[index] = kTimeDependent;
        return true;
    }
    visiting[index] = true;

    const auto& expression = parameters_[index].getExpression();
    bool dependent = referencesTime(expression);
    if (!dependent) {
        for (const auto& dependency : expression.getDependencies()) {
            const auto iter = indexByName_.find(dependency);
            if (iter != indexByName_.end() && computeTimeDependent(iter->second, visiting)) {
                dependent = true;
                break;
            }
        }
    }

    visiting[index] = false;
    timeDependent_[index] = dependent ? kTimeDependent : kTimeIndependent;
    return dependent;
}

bool ParameterList::contains(const std::string& name) const {
    return indexByName_.find(name) != indexByName_.end();
}

const Parameter& ParameterList::get(const std::string& name) const {
    const auto iter = indexByName_.find(name);
    if (iter == indexByName_.end()) {
        throw std::runtime_error("Unknown parameter '" + name + "'");
    }
    return parameters_[iter->second];
}

const std::vector<Parameter>& ParameterList::all() const {
    return parameters_;
}

std::vector<Parameter>& ParameterList::all() {
    return parameters_;
}

std::size_t ParameterList::size() const {
    return parameters_.size();
}

void ParameterList::evaluateAll(double t) {
    for (auto& parameter : parameters_) {
        parameter.clearValue();
    }
    std::unordered_map<std::string, bool> visiting;
    for (std::size_t i = 0; i < parameters_.size(); ++i) {
        evaluateIndex(i, visiting, t);
    }
}

double ParameterList::evaluate(const std::string& name, double t) const {
    const auto iter = indexByName_.find(name);
    if (iter == indexByName_.end()) {
        throw std::runtime_error("Unknown parameter '" + name + "'");
    }

    // A time-dependent parameter is never memoized: its value is a function
    // of `t`, so returning a value cached at an earlier time would freeze it
    // for the rest of the run.  Time-independent parameters still short-circuit
    // on the memo, which is what keeps the rate-evaluation hot path cheap.
    if (!isTimeDependent(iter->second) && hasFreshValue(iter->second)) {
        return parameters_[iter->second].getValue();
    }

    std::unordered_map<std::string, bool> visiting;
    return evaluateIndex(iter->second, visiting, t);
}

double ParameterList::evaluateIndex(std::size_t index, std::unordered_map<std::string, bool>& visiting, double t) const {
    auto& parameter = parameters_[index];
    const bool cacheable = !isTimeDependent(index);
    if (cacheable && hasFreshValue(index)) {
        return parameter.getValue();
    }

    const auto& name = parameter.getName();
    if (visiting[name]) {
        throw std::runtime_error("Circular parameter dependency detected at '" + name + "'");
    }

    visiting[name] = true;
    const double value = parameter.getExpression().evaluate(
        [&](const std::string& dependency) {
            const auto iter = indexByName_.find(dependency);
            if (iter == indexByName_.end()) {
                throw std::runtime_error(
                    "Unknown parameter dependency '" + dependency + "' referenced by '" + name + "'");
            }
            return evaluateIndex(iter->second, visiting, t);
        },
        t);
    visiting[name] = false;
    if (cacheable) {
        parameter.setValue(value);
        if (index < valuesStale_.size()) valuesStale_[index] = false;
    }
    return value;
}

} // namespace bng::ast
