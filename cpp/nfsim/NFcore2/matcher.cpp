#include "matcher.hh"
#include <algorithm>
#include <limits>
#include <functional>
namespace NFcore2 {
namespace {
bool graphMatch(const SimulationState& s, const GraphPattern& graph, const MatchContext& c) {
 if (graph.nodes.empty()) return false;
 for (const auto& node : graph.nodes)
  if (node.molecule_type >= s.model().moleculeTypes().size()) return false;
 for (const auto& edge : graph.edges) {
  if (edge.first_node >= graph.nodes.size() || edge.second_node >= graph.nodes.size() ||
      edge.first_node == edge.second_node ||
      edge.first_component > std::numeric_limits<std::uint16_t>::max() ||
      edge.second_component > std::numeric_limits<std::uint16_t>::max()) return false;
 }
 for (const auto& connected : graph.connected_to) {
  if (connected.first_node >= graph.nodes.size() ||
      connected.second_node >= graph.nodes.size() ||
      connected.first_node == connected.second_node) return false;
 }
 for (const auto& node : graph.nodes) {
  if (node.min_bound_components < -1 || node.max_bound_components < -1 ||
      (node.min_bound_components >= 0 && node.max_bound_components >= 0 &&
       node.min_bound_components > node.max_bound_components)) return false;
 }
 std::vector<MoleculeRef> mapping(graph.nodes.size());
 std::vector<bool> used(graph.nodes.size(), false);
 for (std::size_t i=0;i<graph.nodes.size();++i) {
  const GraphNodePattern& n=graph.nodes[i];
  if (n.anchor_reactant==std::numeric_limits<std::uint16_t>::max()) continue;
  MoleculeRef ref=c.moleculeAt(n.anchor_reactant);
  if (!ref.valid() || ref.type.value()!=n.molecule_type || !s.molecules(ref.type).alive(ref.handle)) return false;
  for (std::size_t j=0;j<i;++j) if (mapping[j]==ref) return false;
  mapping[i]=ref; used[i]=true;
 }
 auto symmetricOk = [&](std::size_t i, MoleculeRef ref, bool requirePartners) {
  const GraphNodePattern& n = graph.nodes[i];
  if (n.symmetric_constraints.empty()) return true;
  const MoleculeStore& store = s.molecules(ref.type);
  std::vector<bool> assigned(store.bondSlotCount(), false);
  std::function<bool(std::size_t)> choose = [&](std::size_t which) {
   if (which == n.symmetric_constraints.size()) return true;
   const SymmetricConstraintPattern& constraint = n.symmetric_constraints[which];
   for (const auto component : constraint.components) {
    if (component > std::numeric_limits<std::uint16_t>::max() ||
        component >= store.bondSlotCount() || assigned[component]) continue;
    if (constraint.state_value >= 0 &&
        store.stateWord(ref.handle, static_cast<std::uint16_t>(component)) !=
            static_cast<std::uint64_t>(constraint.state_value)) continue;
    const MoleculeRef bond = store.bondRef(ref.handle, static_cast<std::uint16_t>(component));
    if (constraint.bond_state == 0 && bond.valid()) continue;
    if (constraint.bond_state == 1 && !bond.valid()) continue;
    if (constraint.partner_node != std::numeric_limits<std::uint32_t>::max()) {
     if (constraint.partner_node >= mapping.size()) return false;
     const MoleculeRef partner = mapping[constraint.partner_node];
     if (!partner.valid()) {
      if (requirePartners) continue;
     } else {
      if (!bond.valid() || !(bond == partner) || constraint.partner_components.empty()) continue;
      const MoleculeStore& partnerStore = s.molecules(partner.type);
      bool reciprocal = false;
      for (const auto partnerComponent : constraint.partner_components) {
       if (partnerComponent > std::numeric_limits<std::uint16_t>::max() ||
           partnerComponent >= partnerStore.bondSlotCount()) return false;
       if (partnerStore.bondRef(partner.handle, static_cast<std::uint16_t>(partnerComponent)) == ref) {
        reciprocal = true; break;
       }
      }
      if (!reciprocal) continue;
     }
    }
    assigned[component] = true;
    if (choose(which + 1)) return true;
    assigned[component] = false;
   }
   return false;
  };
  return choose(0);
 };
 auto nodeOk = [&](std::size_t i, MoleculeRef ref) {
  const GraphNodePattern& n=graph.nodes[i];
  if (!ref.valid() || ref.type.value()!=n.molecule_type || !s.molecules(ref.type).alive(ref.handle)) return false;
  if (n.compartment != std::numeric_limits<std::uint32_t>::max() &&
      s.molecules(ref.type).compartment(ref.handle) != n.compartment) return false;
  if (n.min_bound_components >= 0 || n.max_bound_components >= 0) {
   int occupied = 0;
   const MoleculeStore& boundedStore = s.molecules(ref.type);
   for (std::uint16_t slot = 0; slot < boundedStore.bondSlotCount(); ++slot)
    if (boundedStore.bondRef(ref.handle, slot).valid()) ++occupied;
   if (n.min_bound_components >= 0 && occupied < n.min_bound_components) return false;
   if (n.max_bound_components >= 0 && occupied > n.max_bound_components) return false;
  }
  for (const auto component : n.free_components) {
   if (component > std::numeric_limits<std::uint16_t>::max() ||
       component >= s.molecules(ref.type).bondSlotCount() ||
       s.molecules(ref.type).bondRef(ref.handle, static_cast<std::uint16_t>(component)).valid()) return false;
  }
  for (const auto component : n.bound_components) {
   if (component > std::numeric_limits<std::uint16_t>::max() ||
       component >= s.molecules(ref.type).bondSlotCount() ||
       !s.molecules(ref.type).bondRef(ref.handle, static_cast<std::uint16_t>(component)).valid()) return false;
  }
  if (n.state_component!=std::numeric_limits<std::uint32_t>::max() && n.state_value >= 0 &&
      n.state_component <= std::numeric_limits<std::uint16_t>::max() &&
      s.molecules(ref.type).stateWord(ref.handle, static_cast<std::uint16_t>(n.state_component)) != static_cast<std::uint64_t>(n.state_value)) return false;
  if (n.state_component != std::numeric_limits<std::uint32_t>::max() &&
      n.state_component > std::numeric_limits<std::uint16_t>::max()) return false;
  for (const auto& state : n.state_constraints) {
   if (state.first > std::numeric_limits<std::uint16_t>::max() ||
       state.first >= s.model().moleculeTypes()[ref.type.value()].state_words)
    return false;
   if (state.second < 0 ||
       s.molecules(ref.type).stateWord(ref.handle,
                                       static_cast<std::uint16_t>(state.first)) !=
           static_cast<std::uint64_t>(state.second)) return false;
  }
  for (const auto& excluded : n.excluded_states) {
   if (excluded.first > std::numeric_limits<std::uint16_t>::max() ||
       excluded.first >= s.model().moleculeTypes()[ref.type.value()].state_words ||
       excluded.second < 0)
    return false;
   if (s.molecules(ref.type).stateWord(ref.handle,
                                       static_cast<std::uint16_t>(excluded.first)) ==
           static_cast<std::uint64_t>(excluded.second)) return false;
  }
  if (!symmetricOk(i, ref, false)) return false;
  for (const auto& e: graph.edges) {
   std::size_t other=std::numeric_limits<std::size_t>::max(); std::uint32_t slot=0;
   if (e.first_node==i) { other=e.second_node; slot=e.first_component; }
   else if (e.second_node==i) { other=e.first_node; slot=e.second_component; }
   if (other!=std::numeric_limits<std::size_t>::max() && mapping[other].valid()) {
    const bool equal = s.molecules(ref.type).bondRef(
        ref.handle, static_cast<std::uint16_t>(slot)) == mapping[other];
    if ((!e.negate && !equal) || (e.negate && equal)) return false;
   }
  }
  for (const auto& connected : graph.connected_to) {
   std::size_t other = std::numeric_limits<std::size_t>::max();
   if (connected.first_node == i) other = connected.second_node;
   else if (connected.second_node == i) other = connected.first_node;
   if (other == std::numeric_limits<std::size_t>::max() || !mapping[other].valid()) continue;
   const std::vector<MoleculeRef> component = s.connectedComponent(ref);
   const bool connectedTo = std::find(component.begin(), component.end(), mapping[other]) != component.end();
   if ((!connected.negate && !connectedTo) || (connected.negate && connectedTo)) return false;
  }
  return true;
 };
 std::function<bool(std::size_t)> search = [&](std::size_t next) {
  while (next<graph.nodes.size() && used[next]) ++next;
  if (next==graph.nodes.size()) {
   for (std::size_t i=0; i<graph.nodes.size(); ++i)
    if (!nodeOk(i, mapping[i]) || !symmetricOk(i, mapping[i], true)) return false;
   return true;
  }
  const auto handles=s.molecules(MoleculeTypeId(graph.nodes[next].molecule_type)).liveHandles();
  for (const auto& h: handles) {
   MoleculeRef ref(MoleculeTypeId(graph.nodes[next].molecule_type),h);
   bool duplicate=false; for (std::size_t j=0;j<mapping.size();++j) if (mapping[j]==ref) {duplicate=true;break;}
   if (duplicate || !nodeOk(next,ref)) continue;
   mapping[next]=ref; used[next]=true;
   if (search(next+1)) return true;
   used[next]=false; mapping[next]=MoleculeRef();
  }
  return false;
 };
 for (std::size_t i=0;i<graph.nodes.size();++i) if (used[i] && !nodeOk(i,mapping[i])) return false;
 return search(0);
}
}
bool MatcherProgram::evaluate(const SimulationState&s,const ScaffoldStore&sc,const MatchContext&c)const{
 for(std::size_t i=0;i<code_.size();++i){const MatchInstruction&x=code_[i];MoleculeRef r=c.moleculeAt(x.target);switch(x.opcode){
 case MATCH_TYPE_EXISTS: if(!r.valid()||!s.molecules(r.type).alive(r.handle))return false; if(x.a!=MoleculeTypeId::invalid_value()&&r.type.value()!=x.a)return false;break;
 case MATCH_STATE_MASK: if(!r.valid()||((s.molecules(r.type).stateWord(r.handle,(std::uint16_t)x.a)&x.mask)!=x.value))return false;break;
 case MATCH_STATE_NOT_EQUAL: if(!r.valid()||s.molecules(r.type).stateWord(r.handle,(std::uint16_t)x.a)==x.value)return false;break;
 case MATCH_BOND_PRESENT: if(!r.valid()||!s.molecules(r.type).bondRef(r.handle,(std::uint16_t)x.a).valid())return false;break;
 case MATCH_BOND_FREE: if(!r.valid())return false; if(s.molecules(r.type).bondRef(r.handle,(std::uint16_t)x.a).valid())return false;break;
 case MATCH_BOND_TO:{if(!r.valid())return false;MoleculeRef q=c.moleculeAt(x.b);if(!q.valid()||!(s.molecules(r.type).bondRef(r.handle,(std::uint16_t)x.a)==q))return false;if(x.check_partner_component){if(x.value>std::numeric_limits<std::uint16_t>::max())throw std::out_of_range("partner bond slot overflow");const MoleculeStore& ps=s.molecules(q.type);if(x.value>=ps.bondSlotCount()||!(ps.bondRef(q.handle,(std::uint16_t)x.value)==r))return false;}break;}
 case MATCH_POPULATION_AT_LEAST: if(s.populations().value(PopulationId(x.a))<(std::int64_t)x.value)return false;break;
 case MATCH_COMPARTMENT: if(!r.valid()||s.molecules(r.type).compartment(r.handle)!=x.value)return false;break;
 case MATCH_COMPARTMENT_INSIDE: if(!r.valid()||!s.model().compartmentInside(s.molecules(r.type).compartment(r.handle), static_cast<std::uint32_t>(x.value)))return false;break;
 case MATCH_CONNECTED_TO:{
  if(!r.valid()) return x.negate;
  MoleculeRef wanted=c.moleculeAt(x.b);
  if(!wanted.valid()) return x.negate;
  std::vector<MoleculeRef> pending(1,r), seen(1,r);
  bool found=false;
  for(std::size_t qi=0;qi<pending.size()&&!found;++qi){
   const MoleculeRef current=pending[qi];
   if(current==wanted){found=true;break;}
   const MoleculeStore& store=s.molecules(current.type);
   for(std::uint16_t slot=0;slot<store.bondSlotCount();++slot){
    MoleculeRef next=store.bondRef(current.handle,slot);
    if(!next.valid()||!s.molecules(next.type).alive(next.handle)) continue;
    bool known=false; for(std::size_t si=0;si<seen.size();++si)
     if(seen[si]==next){known=true;break;}
    if(!known){seen.push_back(next);pending.push_back(next);}
   }
  }
  if((!x.negate && !found)||(x.negate && found)) return false;
  break;
 }
 case MATCH_GRAPH: if(x.a>=graphs_.size() || !graphMatch(s,graphs_[x.a],c))return false;break;
 case MATCH_SCAFFOLD_STATE: if(x.a>std::numeric_limits<std::uint32_t>::max()-c.coordinate)throw std::out_of_range("scaffold offset overflow"); if(sc.state(c.scaffold,c.coordinate+x.a)!=(std::uint8_t)x.value)return false;break;
 case MATCH_SCAFFOLD_FREE: if(x.a>std::numeric_limits<std::uint32_t>::max()-c.coordinate)throw std::out_of_range("scaffold offset overflow"); if(sc.occupant(c.scaffold,c.coordinate+x.a).valid())return false;break;
 case MATCH_END:return true; default: throw std::logic_error("invalid matcher opcode"); }}return true;}
}
