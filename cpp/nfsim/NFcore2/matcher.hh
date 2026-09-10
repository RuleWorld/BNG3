#pragma once
#include "simulation_state.hh"
#include "scaffold.hh"
#include <cstdint>
#include <limits>
#include <utility>
#include <vector>
namespace NFcore2 {
struct SymmetricConstraintPattern {
    // Concrete equivalent component indices that may satisfy this occurrence.
    std::vector<std::uint32_t> components;
    int state_value;
    int bond_state; // -1 any, 0 free, 1 occupied
    std::uint32_t partner_node;
    std::vector<std::uint32_t> partner_components;
    bool partner_symmetric;
    SymmetricConstraintPattern() : state_value(-1), bond_state(-1),
        partner_node(std::numeric_limits<std::uint32_t>::max()), partner_symmetric(false) {}
};
struct GraphNodePattern {
    std::uint32_t molecule_type;
    std::uint16_t anchor_reactant;
    std::uint32_t state_component;
    std::uint32_t compartment;
    std::vector<std::uint32_t> free_components;
    std::vector<std::uint32_t> bound_components;
    std::vector<std::pair<std::uint32_t, int> > state_constraints;
    std::vector<std::pair<std::uint32_t, int> > excluded_states;
    std::vector<SymmetricConstraintPattern> symmetric_constraints;
    // Optional molecularity bounds.  -1 means unconstrained; these bounds
    // let graph expressions retain arbitrary free/bound-site predicates
    // instead of collapsing them to one representative component.
    int min_bound_components;
    int max_bound_components;
    int state_value;
    GraphNodePattern() : molecule_type(0), anchor_reactant(std::numeric_limits<std::uint16_t>::max()),
        state_component(std::numeric_limits<std::uint32_t>::max()),
        compartment(std::numeric_limits<std::uint32_t>::max()),
        min_bound_components(-1), max_bound_components(-1), state_value(-1) {}
};
struct GraphEdgePattern {
    std::uint32_t first_node, first_component, second_node, second_component;
    bool negate;
    GraphEdgePattern() : first_node(0), first_component(0), second_node(0), second_component(0), negate(false) {}
};
struct GraphConnectivityPattern {
    std::uint32_t first_node, second_node;
    bool negate;
    GraphConnectivityPattern(std::uint32_t first = 0, std::uint32_t second = 0)
        : first_node(first), second_node(second), negate(false) {}
};
struct GraphPattern {
    std::vector<GraphNodePattern> nodes;
    std::vector<GraphEdgePattern> edges;
    std::vector<GraphConnectivityPattern> connected_to;
};
enum MatchOpcode { MATCH_TYPE_EXISTS, MATCH_STATE_MASK, MATCH_STATE_NOT_EQUAL, MATCH_BOND_PRESENT, MATCH_BOND_FREE, MATCH_BOND_TO, MATCH_POPULATION_AT_LEAST, MATCH_COMPARTMENT, MATCH_COMPARTMENT_INSIDE, MATCH_CONNECTED_TO, MATCH_GRAPH, MATCH_SCAFFOLD_STATE, MATCH_SCAFFOLD_FREE, MATCH_END };
struct MatchInstruction { std::uint16_t opcode; std::uint16_t target; std::uint32_t a,b; std::uint64_t mask,value; bool check_partner_component; bool negate; MatchInstruction(std::uint16_t op=MATCH_END):opcode(op),target(0),a(op==MATCH_TYPE_EXISTS?MoleculeTypeId::invalid_value():0),b(0),mask(0),value(0),check_partner_component(false),negate(false){} };
struct MatchContext {
    MoleculeTypeId type; MoleculeHandle molecule; ScaffoldId scaffold; std::uint32_t coordinate; std::vector<MoleculeRef> reactants; std::vector<std::uint64_t> reactant_counts;
    MoleculeRef moleculeAt(std::size_t i) const { if(i<reactants.size()) return reactants[i]; if(i==0) return MoleculeRef(type,molecule); return MoleculeRef(); }
    void setMoleculeAt(std::size_t i, MoleculeRef r){ if(reactants.size()<=i)reactants.resize(i+1);reactants[i]=r;if(i==0){type=r.type;molecule=r.handle;} }
    void setReactantCount(std::size_t i, std::uint64_t count){ if(reactant_counts.size()<=i) reactant_counts.resize(i+1,0); reactant_counts[i]=count; }
};
class MatcherProgram { public: void add(const MatchInstruction&i){code_.push_back(i);} std::uint32_t addGraphPattern(const GraphPattern& p){graphs_.push_back(p);return static_cast<std::uint32_t>(graphs_.size()-1);} bool evaluate(const SimulationState&,const ScaffoldStore&,const MatchContext&) const; const std::vector<MatchInstruction>& code() const { return code_; } const std::vector<GraphPattern>& graphPatterns() const { return graphs_; } private: std::vector<MatchInstruction> code_; std::vector<GraphPattern> graphs_; };
class MatcherRegistry { public: MatcherId add(const MatcherProgram&p){programs_.push_back(p);return MatcherId((std::uint32_t)programs_.size()-1);} const MatcherProgram& at(MatcherId i)const{return programs_.at(i.value());} std::size_t size()const{return programs_.size();} const std::vector<MatcherProgram>& programs() const { return programs_; } private:std::vector<MatcherProgram>programs_;};
}
