#pragma once
#include "simulation_state.hh"
#include "scaffold.hh"
#include <cstdint>
#include <vector>
namespace NFcore2 {
enum MatchOpcode { MATCH_TYPE_EXISTS, MATCH_STATE_MASK, MATCH_STATE_NOT_EQUAL, MATCH_BOND_PRESENT, MATCH_BOND_FREE, MATCH_BOND_TO, MATCH_POPULATION_AT_LEAST, MATCH_SCAFFOLD_STATE, MATCH_SCAFFOLD_FREE, MATCH_END };
struct MatchInstruction { std::uint16_t opcode; std::uint16_t target; std::uint32_t a,b; std::uint64_t mask,value; MatchInstruction(std::uint16_t op=MATCH_END):opcode(op),target(0),a(0),b(0),mask(0),value(0){} };
struct MatchContext {
    MoleculeTypeId type; MoleculeHandle molecule; ScaffoldId scaffold; std::uint32_t coordinate; std::vector<MoleculeRef> reactants;
    MoleculeRef moleculeAt(std::size_t i) const { if(i<reactants.size()) return reactants[i]; if(i==0) return MoleculeRef(type,molecule); return MoleculeRef(); }
    void setMoleculeAt(std::size_t i, MoleculeRef r){ if(reactants.size()<=i)reactants.resize(i+1);reactants[i]=r;if(i==0){type=r.type;molecule=r.handle;} }
};
class MatcherProgram { public: void add(const MatchInstruction&i){code_.push_back(i);} bool evaluate(const SimulationState&,const ScaffoldStore&,const MatchContext&) const; const std::vector<MatchInstruction>& code() const { return code_; } private: std::vector<MatchInstruction> code_; };
class MatcherRegistry { public: MatcherId add(const MatcherProgram&p){programs_.push_back(p);return MatcherId((std::uint32_t)programs_.size()-1);} const MatcherProgram& at(MatcherId i)const{return programs_.at(i.value());} std::size_t size()const{return programs_.size();} const std::vector<MatcherProgram>& programs() const { return programs_; } private:std::vector<MatcherProgram>programs_;};
}
