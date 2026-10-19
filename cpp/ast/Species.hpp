#pragma once

#include <string>

#include "SpeciesGraph.hpp"

namespace bng::ast {

class Species {
public:
    Species(SpeciesGraph graph, double amount = 0.0, bool constant = false, std::string compartment = {});

    const SpeciesGraph& getSpeciesGraph() const;
    SpeciesGraph& getSpeciesGraph();
    double getAmount() const;
    void setAmount(double amount);
    bool isConstant() const;
    const std::string& getCompartment() const;
    void setCompartment(std::string compartment);
    // BNG2-canonical species identity: the species compartment prefix, the
    // constant marker and the graph spelling, exactly as the .net writer
    // emits it.  A species-level compartment is part of the identity, so two
    // species that differ only by compartment are distinguishable.
    std::string canonicalName() const;
    std::size_t getIndex() const;
    void setIndex(std::size_t index);
    bool rulesApplied() const;
    void setRulesApplied(bool value);

private:
    SpeciesGraph graph_;
    double amount_;
    bool constant_;
    std::string compartment_;
    std::size_t index_ = 0;
    bool rulesApplied_ = false;
};

} // namespace bng::ast
