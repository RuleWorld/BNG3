#include "matcher.hh"
#include <limits>
namespace NFcore2 {
bool MatcherProgram::evaluate(const SimulationState&s,const ScaffoldStore&sc,const MatchContext&c)const{
 for(std::size_t i=0;i<code_.size();++i){const MatchInstruction&x=code_[i];MoleculeRef r=c.moleculeAt(x.target);switch(x.opcode){
 case MATCH_TYPE_EXISTS: if(!r.valid()||!s.molecules(r.type).alive(r.handle))return false;break;
 case MATCH_STATE_MASK: if(!r.valid()||((s.molecules(r.type).stateWord(r.handle,(std::uint16_t)x.a)&x.mask)!=x.value))return false;break;
 case MATCH_STATE_NOT_EQUAL: if(!r.valid()||s.molecules(r.type).stateWord(r.handle,(std::uint16_t)x.a)==x.value)return false;break;
 case MATCH_BOND_PRESENT: if(!r.valid()||!s.molecules(r.type).bondRef(r.handle,(std::uint16_t)x.a).valid())return false;break;
 case MATCH_BOND_FREE: if(!r.valid())return false; if(s.molecules(r.type).bondRef(r.handle,(std::uint16_t)x.a).valid())return false;break;
 case MATCH_BOND_TO:{if(!r.valid())return false;MoleculeRef q=c.moleculeAt(x.b);if(!q.valid()||!(s.molecules(r.type).bondRef(r.handle,(std::uint16_t)x.a)==q))return false;if(x.check_partner_component){if(x.value>std::numeric_limits<std::uint16_t>::max())throw std::out_of_range("partner bond slot overflow");const MoleculeStore& ps=s.molecules(q.type);if(x.value>=ps.bondSlotCount()||!(ps.bondRef(q.handle,(std::uint16_t)x.value)==r))return false;}break;}
 case MATCH_POPULATION_AT_LEAST: if(s.populations().value(PopulationId(x.a))<(std::int64_t)x.value)return false;break;
 case MATCH_SCAFFOLD_STATE: if(x.a>std::numeric_limits<std::uint32_t>::max()-c.coordinate)throw std::out_of_range("scaffold offset overflow"); if(sc.state(c.scaffold,c.coordinate+x.a)!=(std::uint8_t)x.value)return false;break;
 case MATCH_SCAFFOLD_FREE: if(x.a>std::numeric_limits<std::uint32_t>::max()-c.coordinate)throw std::out_of_range("scaffold offset overflow"); if(sc.occupant(c.scaffold,c.coordinate+x.a).valid())return false;break;
 case MATCH_END:return true; default: throw std::logic_error("invalid matcher opcode"); }}return true;}
}
