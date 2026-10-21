#pragma once

#include <string>
#include <vector>
#include <map>

#include "core/BNGcore.hpp"
#include "Compartment.hpp"

namespace bng::ast {

class SpeciesGraph {
public:
    SpeciesGraph() = default;
    explicit SpeciesGraph(BNGcore::PatternGraph graph, std::string compartment = {});

    const BNGcore::PatternGraph& getGraph() const;
    BNGcore::PatternGraph& getGraph();
    // Structural canonical label; per-molecule and outer compartments are
    // deliberately excluded, so this is not a complete species identity.
    std::string canonicalLabel() const;
    std::string fingerprint() const;
    // Compare exact graph identity (node types, exact states, connectivity,
    // and per-molecule compartments). Wildcard state matching is deliberately
    // excluded. The outer species-level compartment is compared by its owner.
    // Native NFsim keeps a different encoding, differential-tested against
    // this relation; the two canonical-label strings are not interchangeable.
    bool graphIsomorphicTo(const BNGcore::PatternGraph& other) const;
    std::string toString() const;
    std::string toStringForDedup() const;
    const std::string& getCompartment() const;
    void setCompartment(std::string compartment);
    bool isCompartmentPrefix() const { return compartmentIsPrefix_; }
    void setCompartmentIsPrefix(bool v) { compartmentIsPrefix_ = v; }

    // Graph Operations (Tasks 5 & 6)
    bool isConnected() const;
    size_t numComponents() const;
    std::vector<SpeciesGraph> splitConnectedComponents() const;
    std::map<std::string, size_t> stoichiometry() const;
    std::string inferCompartment(const std::vector<Compartment>& hierarchy) const;

private:
    BNGcore::PatternGraph graph_;
    std::string compartment_;
    bool compartmentIsPrefix_ = false;
};

} // namespace bng::ast
