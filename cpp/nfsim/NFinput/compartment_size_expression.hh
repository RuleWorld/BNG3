#pragma once

// Shared bridge from a parsed BioNetGen volume expression to the NFcore
// compartment evaluator.  The three NFsim loaders (AST, compiled, XML) all
// install the same evaluator so a general compartment-size expression refreshes
// identically no matter which entry point built the System.

#include <limits>
#include <map>
#include <string>

#include "ast/Expression.hpp"
#include "NFcore/compartment.hh"

namespace NFinput {

// Resolve identifiers from the System parameter map; an unknown name yields
// NaN so System::updateCompartmentSizesFromParameters() leaves the last finite
// size in place instead of silently snapshotting a stale or zero volume.
inline NFcore::Compartment::SizeExpression makeCompartmentSizeExpression(
    const bng::ast::Expression& expression) {
    return [expression](const std::map<std::string, double>& parameters) {
        return expression.evaluate([&parameters](const std::string& name) {
            const auto found = parameters.find(name);
            if (found == parameters.end()) {
                return std::numeric_limits<double>::quiet_NaN();
            }
            return found->second;
        });
    };
}

} // namespace NFinput
