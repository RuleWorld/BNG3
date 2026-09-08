#include "transform.hh"
#include <limits>
#include <stdexcept>
namespace NFcore2 {
namespace {
FeatureId bondFeature(const SimulationState& state, MoleculeTypeId type, std::uint32_t component) {
    const std::vector<FeatureDescriptor>& features = state.model().features();
    for (std::size_t i = 0; i < features.size(); ++i) {
        if (features[i].kind == FEATURE_MOLECULE_BOND &&
            features[i].owner == type.value() && features[i].index == component)
            return FeatureId(static_cast<std::uint32_t>(i));
    }
    return FeatureId();
}

void reportBondDelta(const SimulationState& state, const MoleculeRef& left,
                     std::uint32_t left_slot, const MoleculeRef& right,
                     std::uint32_t right_slot, FeatureId primary,
                     FeatureDelta& delta) {
    FeatureId left_feature = primary.valid() ? primary : bondFeature(state, left.type, left_slot);
    FeatureId right_feature = bondFeature(state, right.type, right_slot);
    if (left_feature.valid()) delta.add(left_feature);
    if (right_feature.valid() && right_feature != left_feature) delta.add(right_feature);
}

void reportMoleculeFeatures(const SimulationState& state, MoleculeTypeId type,
                            FeatureDelta& delta) {
    const std::vector<FeatureDescriptor>& features = state.model().features();
    for (std::size_t i = 0; i < features.size(); ++i) {
        if (features[i].owner != type.value()) continue;
        if (features[i].kind == FEATURE_MOLECULE_STATE ||
            features[i].kind == FEATURE_MOLECULE_BOND ||
            features[i].kind == FEATURE_MOLECULE_EXISTENCE ||
            features[i].kind == FEATURE_MOLECULE_COMPARTMENT)
            delta.add(FeatureId(static_cast<std::uint32_t>(i)));
    }
}
}
void TransformProgram::execute(SimulationState&s,ScaffoldStore&sc,MatchContext&c,FeatureDelta&d)const{for(std::size_t i=0;i<code_.size();++i){const TransformInstruction&x=code_[i];MoleculeRef r=c.moleculeAt(x.target);switch(x.opcode){
case TRANSFORM_SET_STATE_WORD:s.molecules(r.type).setStateWord(r.handle,(std::uint16_t)x.a,x.value);d.add(x.feature.valid()?x.feature:FeatureId(x.b));break;
case TRANSFORM_ADD_STATE_WORD:{
 std::uint64_t old=s.molecules(r.type).stateWord(r.handle,(std::uint16_t)x.a); std::int64_t delta=static_cast<std::int64_t>(x.value);
 if(delta<0){std::uint64_t mag=static_cast<std::uint64_t>(-(delta+1))+1u;if(old<mag)throw std::overflow_error("state underflow");s.molecules(r.type).setStateWord(r.handle,(std::uint16_t)x.a,old-mag);}
 else {std::uint64_t add=static_cast<std::uint64_t>(delta);if(old>std::numeric_limits<std::uint64_t>::max()-add)throw std::overflow_error("state overflow");s.molecules(r.type).setStateWord(r.handle,(std::uint16_t)x.a,old+add);}
 if(x.feature.valid())d.add(x.feature);break;}
case TRANSFORM_SET_SCAFFOLD_STATE:sc.setState(c.scaffold,c.coordinate+x.a,(std::uint8_t)x.value);d.add(x.feature.valid()?x.feature:FeatureId(x.b));break;
case TRANSFORM_MOVE_OCCUPANT:{
 if(x.a>std::numeric_limits<std::uint32_t>::max()-c.coordinate||x.b>std::numeric_limits<std::uint32_t>::max()-c.coordinate)throw std::out_of_range("scaffold offset overflow");
 std::uint32_t from=c.coordinate+x.a,to=c.coordinate+x.b;MoleculeHandle h=sc.occupant(c.scaffold,from);
 if(!h.valid())throw std::logic_error("cannot move empty scaffold occupant");
 if(from!=to&&sc.occupant(c.scaffold,to).valid())throw std::logic_error("cannot overwrite scaffold occupant");
 sc.setOccupant(c.scaffold,from,MoleculeHandle());sc.setOccupant(c.scaffold,to,h);c.coordinate=to;d.add(x.feature.valid()?x.feature:FeatureId((std::uint32_t)x.value));break;}
case TRANSFORM_POPULATION_ADD:s.populations().addTo(PopulationId(x.a),(std::int64_t)x.value);d.add(x.feature.valid()?x.feature:FeatureId(x.b));break;
case TRANSFORM_BIND:{MoleculeRef q=c.moleculeAt(x.other);
 if(!r.valid()||!q.valid())throw std::out_of_range("bind target missing");
 if(s.molecules(r.type).bondRef(r.handle,(std::uint16_t)x.a).valid()||s.molecules(q.type).bondRef(q.handle,(std::uint16_t)x.b).valid())throw std::logic_error("cannot bind occupied site");
 s.molecules(r.type).setBondRef(r.handle,(std::uint16_t)x.a,q);s.molecules(q.type).setBondRef(q.handle,(std::uint16_t)x.b,r);reportBondDelta(s,r,x.a,q,x.b,x.feature,d);break;}
case TRANSFORM_UNBIND:{
 MoleculeRef q=s.molecules(r.type).bondRef(r.handle,(std::uint16_t)x.a);
 if(!q.valid()){if(x.feature.valid())d.add(x.feature);break;}
 if(!s.molecules(q.type).alive(q.handle))throw std::logic_error("unbind partner is stale");
 std::uint32_t partner_slot=x.b;
 if(partner_slot==TRANSFORM_INFER_PARTNER_SLOT){
  partner_slot=TRANSFORM_INFER_PARTNER_SLOT;
  const MoleculeStore& ps=s.molecules(q.type);
  for(std::uint32_t slot=0;slot<ps.bondSlotCount();++slot){
   MoleculeRef back=ps.bondRef(q.handle,(std::uint16_t)slot);
   if(back==r){partner_slot=slot;break;}
  }
  if(partner_slot==TRANSFORM_INFER_PARTNER_SLOT)throw std::logic_error("cannot infer reciprocal bond slot");
 } else {
  if(partner_slot>=s.molecules(q.type).bondSlotCount())throw std::out_of_range("unbind partner slot out of range");
  if(!(s.molecules(q.type).bondRef(q.handle,(std::uint16_t)partner_slot)==r))throw std::logic_error("unbind reciprocal bond mismatch");
 }
 s.molecules(r.type).setBondRef(r.handle,(std::uint16_t)x.a,MoleculeRef());
 s.molecules(q.type).setBondRef(q.handle,(std::uint16_t)partner_slot,MoleculeRef());
 reportBondDelta(s,r,x.a,q,partner_slot,x.feature,d);break;}
case TRANSFORM_CREATE_MOLECULE:{MoleculeTypeId t(x.a);MoleculeHandle h=s.molecules(t).create();c.setMoleculeAt(x.target,MoleculeRef(t,h));if(x.feature.valid())d.add(x.feature);break;}
case TRANSFORM_DELETE_MOLECULE:{if(r.valid()){std::vector<MoleculeRef> neighbors;const MoleculeStore& source=s.molecules(r.type);for(std::uint16_t slot=0;slot<source.bondSlotCount();++slot){MoleculeRef p=source.bondRef(r.handle,slot);if(p.valid()&&s.molecules(p.type).alive(p.handle))neighbors.push_back(p);}s.eraseMolecule(r);reportMoleculeFeatures(s,r.type,d);for(const auto& p:neighbors)reportMoleculeFeatures(s,p.type,d);}if(x.feature.valid())d.add(x.feature);break;}
case TRANSFORM_DELETE_SPECIES:{std::vector<MoleculeRef> removed=s.eraseSpecies(r);for(std::size_t j=0;j<removed.size();++j)reportMoleculeFeatures(s,removed[j].type,d);if(x.feature.valid())d.add(x.feature);break;}
case TRANSFORM_MOVE_MOLECULE:if(!r.valid())throw std::out_of_range("move target missing");s.molecules(r.type).setCompartment(r.handle,x.a);if(x.feature.valid())d.add(x.feature);break;
case TRANSFORM_MOVE_SPECIES:{s.moveSpecies(r,x.a);const std::vector<MoleculeRef> members=s.connectedComponent(r);for(const auto& member:members)reportMoleculeFeatures(s,member.type,d);if(x.feature.valid())d.add(x.feature);break;}
case TRANSFORM_DELETE_MOLECULE_CONDITIONAL:{if(!r.valid()||s.wouldEraseSplitSpecies(r))break;const std::vector<MoleculeRef> members=s.connectedComponent(r);if(s.eraseMolecule(r)){for(const auto& member:members)reportMoleculeFeatures(s,member.type,d);}if(x.feature.valid())d.add(x.feature);break;}
case TRANSFORM_END:return;default:throw std::logic_error("invalid transform opcode");}}}
}
