#include "nfsim_native_reader.hh"
#include "../NFcore/NFcore.hh"
#include "../NFcore/templateMolecule.hh"
#include "../NFreactions/transformations/transformationSet.hh"
#include "../NFreactions/transformations/transformation.hh"
#include "nfsim_transform_decoder.hh"
#include "../NFreactions/transformations/moleculeCreator.hh"
#include <algorithm>
#include <limits>
#include <stdexcept>
namespace NFcore2 {
using namespace NFcore;
NativeNFsimSystemReader::NativeNFsimSystemReader(System& s):system_(s){}
std::size_t NativeNFsimSystemReader::moleculeTypeCount() const{return static_cast<std::size_t>(system_.getNumOfMoleculeTypes());}
NativeMoleculeTypeSnapshot NativeNFsimSystemReader::moleculeType(std::size_t i) const{
    MoleculeType* mt=system_.getMoleculeType(static_cast<int>(i));NativeMoleculeTypeSnapshot o;o.name=mt->getName();o.component_count=static_cast<std::uint32_t>(mt->getNumOfComponents());o.population=mt->isPopulationType();return o;
}
std::size_t NativeNFsimSystemReader::reactionCount() const{return system_.getAllReactions().size();}
NativeReactionHeader NativeNFsimSystemReader::reactionHeader(std::size_t i) const{
    ReactionClass* r=system_.getReaction(static_cast<int>(i));NativeReactionHeader h;h.name=r->getName();h.base_rate=r->getBaseRate();h.coordinate=static_cast<std::uint32_t>(i);h.parameter_index=static_cast<std::uint32_t>(i);
    h.uses_local_function = r->getRxnType() != ReactionClass::BASIC_RXN;
    // A zero-reactant rule is a synthesis/population rule.  It does not
    // imply an unresolved internal graph query.
    h.uses_connected_to = false;
    std::vector<TemplateMolecule*> roots;
    for (int p = 0; p < r->getNumOfReactants(); ++p) roots.push_back(r->getReactantTemplate(p));
    for (int p = 0; p < r->getNumOfReactants(); ++p) {
        auto* mt = r->getMoleculeTypeOfReactantTemplate(p);
        if (!mt) throw std::logic_error("NFsim reactant without molecule type");
        h.reactant_types.push_back(static_cast<std::uint32_t>(mt->getTypeID()));
        auto* root = r->getReactantTemplate(p);
        TemplateMolecule::RootLocalConstraints constraints;
        if (!root || !root->collectRootLocalConstraints(constraints)) h.uses_connected_to = true;
        for (const auto& bond : constraints.bonds) {
            if (std::find(roots.begin(), roots.end(), bond.partner) == roots.end())
                h.uses_connected_to = true;
        }
        for (TemplateMolecule* connected : constraints.connected_to) {
            if (std::find(roots.begin(), roots.end(), connected) == roots.end())
                h.uses_connected_to = true;
        }
    }
    TransformationSet* ts=r->getTransformationSet();if(ts)for(int p=0;p<r->getNumOfReactants();++p)for(int x=0;x<ts->getNumOfTransformations(p);++x)if(ts->getTransformation(p,x)->getType()==TransformationFactory::LOCAL_FUNCTION_REFERENCE)h.uses_local_function=true;
    return h;
}
void NativeNFsimSystemReader::collectDependencies(std::size_t i,std::vector<NativeDependencySnapshot>& out) const{
    ReactionClass* r=system_.getReaction(static_cast<int>(i));
    std::vector<TemplateMolecule*> roots;
    for (int p = 0; p < r->getNumOfReactants(); ++p) roots.push_back(r->getReactantTemplate(p));
    for (int p = 0; p < r->getNumOfReactants(); ++p) {
        auto* root = r->getReactantTemplate(p);
        TemplateMolecule::RootLocalConstraints constraints;
        if (!root || !root->collectRootLocalConstraints(constraints)) continue;
        auto append = [&](NativeDependencyKind kind, int component, int state) {
            NativeDependencySnapshot value;
            value.kind = kind; value.reactant = static_cast<std::uint16_t>(p);
            value.component = static_cast<std::uint32_t>(component); value.state = state;
            out.push_back(value);
        };
        for (auto c : constraints.empty) append(NATIVE_BOND_FREE, c, -1);
        for (auto c : constraints.occupied) append(NATIVE_BOND_BOUND, c, -1);
        for (auto c : constraints.states) append(NATIVE_STATE_REQUIRED, c.first, c.second);
        for (auto c : constraints.exclusions) append(NATIVE_STATE_EXCLUDED, c.first, c.second);
        for (const auto& bond : constraints.bonds) {
            auto partner = std::find(roots.begin(), roots.end(), bond.partner);
            if (partner == roots.end()) {
                append(NATIVE_TOPOLOGY, bond.component, -1);
                continue;
            }
            NativeDependencySnapshot value;
            value.kind = NATIVE_BOND_TO;
            value.reactant = static_cast<std::uint16_t>(p);
            value.component = static_cast<std::uint32_t>(bond.component);
            value.partner_reactant = static_cast<std::uint16_t>(partner - roots.begin());
            value.partner_component = static_cast<std::uint32_t>(bond.partner_component);
            out.push_back(value);
        }
        if (!constraints.compartment.empty()) {
            NativeDependencySnapshot value;
            value.kind = NATIVE_COMPARTMENT_REQUIRED;
            value.reactant = static_cast<std::uint16_t>(p);
            value.compartment = nativeCompartmentId(constraints.compartment);
            out.push_back(value);
        }
        for (TemplateMolecule* connected : constraints.connected_to) {
            auto partner = std::find(roots.begin(), roots.end(), connected);
            if (partner == roots.end()) {
                NativeDependencySnapshot unsupported;
                unsupported.kind = NATIVE_TOPOLOGY;
                unsupported.reactant = static_cast<std::uint16_t>(p);
                unsupported.partner_reactant = std::numeric_limits<std::uint16_t>::max();
                out.push_back(unsupported);
                continue;
            }
            NativeDependencySnapshot value;
            value.kind = NATIVE_TOPOLOGY;
            value.reactant = static_cast<std::uint16_t>(p);
            value.partner_reactant = static_cast<std::uint16_t>(partner - roots.begin());
            value.partner_component = NATIVE_INFER_PARTNER_COMPONENT;
            out.push_back(value);
        }
    }
}
void NativeNFsimSystemReader::collectTransforms(std::size_t i,std::vector<NativeTransformSnapshot>& out) const{
    ReactionClass* r=system_.getReaction(static_cast<int>(i));TransformationSet* ts=r->getTransformationSet();if(!ts)return;std::vector<std::vector<NFsimPublicTransformView> > views(static_cast<std::size_t>(r->getNumOfReactants()));
    for(int p=0;p<r->getNumOfReactants();++p){for(int x=0;x<ts->getNumOfTransformations(p);++x){Transformation* t=ts->getTransformation(p,x);NFsimPublicTransformView v;v.kind=t->getType();v.reactant=static_cast<std::uint16_t>(p);int ci=-1;switch(t->getType()){case TransformationFactory::STATE_CHANGE:case TransformationFactory::BINDING:case TransformationFactory::UNBINDING:case TransformationFactory::EMPTY:case TransformationFactory::INCREMENT_STATE:case TransformationFactory::DECREMENT_STATE:ci=t->getComponentIndex();break;default:break;}v.component=ci<0?0u:static_cast<std::uint32_t>(ci);if(t->getType()==TransformationFactory::STATE_CHANGE){StateChangeTransform* q=dynamic_cast<StateChangeTransform*>(t);if(!q)throw std::logic_error("state transform type mismatch");v.final_state=q->getFinalStateValue();}else if(t->getType()==TransformationFactory::BINDING){BindingTransform* q=dynamic_cast<BindingTransform*>(t);if(!q)throw std::logic_error("binding transform type mismatch");v.other_reactant=q->getOtherReactantIndex();v.other_mapping_index=q->getOtherMappingIndex();}else if(t->getType()==TransformationFactory::EMPTY && ci>=0){v.second_binding_half=true;}else if(t->getType()==TransformationFactory::REMOVE){v.removal_type=t->getRemovalType();}else if(t->getType()==TransformationFactory::ADD){AddMoleculeTransform* q=dynamic_cast<AddMoleculeTransform*>(t);if(q){if(q->isPopulationType()){v.kind=TransformationFactory::INCREMENT_POPULATION;v.population_delta=1;}else if(q->getMoleculeType()){v.added_molecule_type=static_cast<std::uint32_t>(q->getMoleculeType()->getTypeID());}}}else if(t->getType()==TransformationFactory::DECREMENT_POPULATION){v.population_delta=1;}else if(t->getType()==TransformationFactory::MOVE){MoveTransformation* q=dynamic_cast<MoveTransformation*>(t);if(q)v.destination_compartment=nativeCompartmentId(q->getNewCompartmentId());}views[static_cast<std::size_t>(p)].push_back(v);}}
    out=NFsimTransformDecoder::decode(views);
}
NativeModelSnapshot snapshotLegacyNFsim(System& system){NativeNFsimSystemReader reader(system);return readNFsimSystem(reader);}
LegacyLoweringResult lowerLegacyNFsim(System& system){
    const NativeModelSnapshot snapshot=snapshotLegacyNFsim(system);
    const LegacyModelIR legacy=NFsimSnapshotAdapter::toLegacy(snapshot);
    LegacyLoweringResult result=LegacyLowerer::lower(legacy);
    result.executable.validate();
    return result;
}
}
