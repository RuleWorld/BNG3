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
    std::string canonicalLabel() const;
    std::string fingerprint() const;
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
