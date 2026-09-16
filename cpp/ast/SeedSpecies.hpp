#pragma once

#include <string>
#include <optional>

#include "core/BNGcore.hpp"
#include "Expression.hpp"
#include "units/Unit.hpp"

namespace bng::ast {

class SeedSpecies {
public:
    SeedSpecies(
        std::string pattern,
        Expression amount,
        bool constant = false,
        std::string compartment = {},
        BNGcore::PatternGraph graph = BNGcore::PatternGraph());

    const std::string& getPattern() const;
    const Expression& getAmount() const;
    bool isConstant() const;
    const std::string& getCompartment() const;
    const BNGcore::PatternGraph& getGraph() const;
    std::string getCanonicalLabel() const;
    bool hasUnit() const;
    const std::optional<units::Unit>& getUnit() const;
    const std::string& getUnitName() const;
    void setUnit(units::Unit unit, std::string name);

private:
    std::string pattern_;
    Expression amount_;
    bool constant_;
    std::string compartment_;
    BNGcore::PatternGraph graph_;
    std::optional<units::Unit> unit_;
    std::string unitName_;
};

} // namespace bng::ast
