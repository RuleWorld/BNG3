#include "scaffold.hh"
namespace NFcore2 {
ScaffoldId ScaffoldStore::create(std::uint32_t n, std::uint8_t d, ScaffoldStorageKind kind) {
    Scaffold s; s.length=n; s.default_state=d; s.storage=kind;
    if(kind==SCAFFOLD_DENSE){s.dense_state.assign(n,d);s.dense_occupant.resize(n);}
    scaffolds_.push_back(s); return ScaffoldId(static_cast<std::uint32_t>(scaffolds_.size()-1));
}
std::uint8_t ScaffoldStore::state(ScaffoldId id, std::uint32_t p) const { const Scaffold& s=scaffolds_.at(id.value()); if(p>=s.length) throw std::out_of_range("scaffold position"); if(s.storage==SCAFFOLD_DENSE)return s.dense_state[p]; std::unordered_map<std::uint32_t,std::uint8_t>::const_iterator it=s.state_exceptions.find(p); return it==s.state_exceptions.end()?s.default_state:it->second; }
void ScaffoldStore::setState(ScaffoldId id,std::uint32_t p,std::uint8_t v){ Scaffold& s=scaffolds_.at(id.value()); if(p>=s.length) throw std::out_of_range("scaffold position"); if(s.storage==SCAFFOLD_DENSE){s.dense_state[p]=v;return;} if(v==s.default_state)s.state_exceptions.erase(p);else s.state_exceptions[p]=v; }
MoleculeHandle ScaffoldStore::occupant(ScaffoldId id,std::uint32_t p) const { const Scaffold& s=scaffolds_.at(id.value()); if(p>=s.length) throw std::out_of_range("scaffold position"); if(s.storage==SCAFFOLD_DENSE)return s.dense_occupant[p]; std::unordered_map<std::uint32_t,MoleculeHandle>::const_iterator it=s.sparse_occupant.find(p); return it==s.sparse_occupant.end()?MoleculeHandle():it->second; }
void ScaffoldStore::setOccupant(ScaffoldId id,std::uint32_t p,MoleculeHandle h){ Scaffold& s=scaffolds_.at(id.value()); if(p>=s.length) throw std::out_of_range("scaffold position"); if(s.storage==SCAFFOLD_DENSE){s.dense_occupant[p]=h;return;} if(h.valid())s.sparse_occupant[p]=h;else s.sparse_occupant.erase(p); }
std::uint32_t ScaffoldStore::length(ScaffoldId id) const { return scaffolds_.at(id.value()).length; }
std::size_t ScaffoldStore::materializedStateCount(ScaffoldId id) const { const Scaffold& s=scaffolds_.at(id.value()); return s.storage==SCAFFOLD_DENSE?s.dense_state.size():s.state_exceptions.size(); }
std::size_t ScaffoldStore::occupiedCount(ScaffoldId id) const { const Scaffold& s=scaffolds_.at(id.value()); if(s.storage==SCAFFOLD_SPARSE)return s.sparse_occupant.size(); std::size_t n=0;for(std::size_t i=0;i<s.dense_occupant.size();++i)if(s.dense_occupant[i].valid())++n;return n; }
}
