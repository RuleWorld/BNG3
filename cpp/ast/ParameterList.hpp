#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "Parameter.hpp"

namespace bng::ast {

class ParameterList {
public:
    void add(Parameter parameter);
    bool contains(const std::string& name) const;
    const Parameter& get(const std::string& name) const;
    const std::vector<Parameter>& all() const;
    std::vector<Parameter>& all();
    std::size_t size() const;

    void evaluateAll(double t = 0.0);
    double evaluate(const std::string& name, double t = 0.0) const;
    // True when the named parameter's value changes with time. Callers use this
    // to decide whether a rate that merely *references* the parameter still has
    // to be evaluated per timestep. Unknown names are not time dependent.
    bool isTimeDependent(const std::string& name) const;

private:
    double evaluateIndex(std::size_t index, std::unordered_map<std::string, bool>& visiting, double t) const;

    // A parameter is memoized only when its value cannot change with time.
    // `time`/`t` is the sole varying input Expression::evaluate accepts, so
    // a parameter whose expression references it -- directly or through
    // another parameter -- must be recomputed on every call.
    bool isTimeDependent(std::size_t index) const;
    bool computeTimeDependent(std::size_t index, std::vector<bool>& visiting) const;

    // kUnknown until classified; see isTimeDependent.
    static constexpr std::int8_t kUnknown = 0;
    static constexpr std::int8_t kTimeIndependent = 1;
    static constexpr std::int8_t kTimeDependent = 2;
    mutable std::vector<std::int8_t> timeDependent_;

    mutable std::vector<Parameter> parameters_;
    std::unordered_map<std::string, std::size_t> indexByName_;
};

} // namespace bng::ast
