#include "nfsim_native_reader.hh"
#include "../NFcore/NFcore.hh"
#include "../NFcore/compartment.hh"
#include "../NFcore/templateMolecule.hh"
#include "../NFreactions/transformations/transformationSet.hh"
#include "../NFreactions/transformations/transformation.hh"
#include "nfsim_transform_decoder.hh"
#include "../NFreactions/transformations/moleculeCreator.hh"
#include <algorithm>
#include <limits>
#include <stdexcept>
#include <map>
#include <queue>
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
    std::vector<NativeGraphPatternSnapshot> graphPatterns;
    collectGraphPatterns(i, graphPatterns);
    for (int p = 0; p < r->getNumOfReactants(); ++p) {
        auto* mt = r->getMoleculeTypeOfReactantTemplate(p);
        if (!mt) throw std::logic_error("NFsim reactant without molecule type");
        h.reactant_types.push_back(static_cast<std::uint32_t>(mt->getTypeID()));
        auto* root = r->getReactantTemplate(p);
        TemplateMolecule::RootLocalConstraints constraints;
        if (!root || (!root->collectRootLocalConstraints(constraints) && graphPatterns.empty())) h.uses_connected_to = true;
        for (const auto& bond : constraints.bonds) {
            if (std::find(roots.begin(), roots.end(), bond.partner) == roots.end() && graphPatterns.empty())
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
void NativeNFsimSystemReader::collectGraphPatterns(std::size_t i,std::vector<NativeGraphPatternSnapshot>& out) const {
    ReactionClass* r=system_.getReaction(static_cast<int>(i));
    std::vector<TemplateMolecule*> roots;
    for (int p=0;p<r->getNumOfReactants();++p) roots.push_back(r->getReactantTemplate(p));
    std::map<TemplateMolecule*,std::size_t> indices;
    std::queue<TemplateMolecule*> pending;
    NativeGraphPatternSnapshot graph;
    auto appendNode = [&](TemplateMolecule* molecule, std::uint16_t reactant) {
        if (!molecule || !molecule->getMoleculeType()) { out.clear(); return false; }
        TemplateMolecule::RootLocalConstraints constraints;
        if (!molecule->collectRootLocalConstraints(constraints)) { out.clear(); return false; }
        // Root-local constraints are emitted separately as dependency
        // predicates. Internal graph nodes need their own exact state
        // constraint here; silently dropping child constraints would widen
        // the graph match.
        if (reactant == std::numeric_limits<std::uint16_t>::max() &&
            (!constraints.exclusions.empty() || !constraints.connected_to.empty() ||
             constraints.states.size() > 1)) {
            out.clear(); return false;
        }
        NativeGraphNodeSnapshot node;
        node.molecule_type=static_cast<std::uint32_t>(molecule->getMoleculeType()->getTypeID());
        node.reactant=reactant;
        if (!constraints.compartment.empty())
            node.compartment=nativeCompartmentId(constraints.compartment);
        for (const auto component : constraints.empty)
            node.free_components.push_back(static_cast<std::uint32_t>(component));
        for (const auto component : constraints.occupied)
            node.bound_components.push_back(static_cast<std::uint32_t>(component));
        if (reactant == std::numeric_limits<std::uint16_t>::max() && !constraints.states.empty()) {
            if (constraints.states.front().first < 0 || constraints.states.front().second < 0) {
                out.clear(); return false;
            }
            node.state_component=static_cast<std::uint32_t>(constraints.states.front().first);
            node.state=constraints.states.front().second;
        }
        indices[molecule]=graph.nodes.size();
        graph.nodes.push_back(node);
        pending.push(molecule);
        return true;
    };
    for (std::size_t p=0;p<roots.size();++p) {
        TemplateMolecule* root=roots[p];
        if (!root || root->getN_symComps()!=0) { out.clear(); return; }
        if (indices.find(root)==indices.end()) {
            if (!appendNode(root, static_cast<std::uint16_t>(p))) return;
        }
    }
    while (!pending.empty()) {
        TemplateMolecule* current=pending.front(); pending.pop();
        const std::size_t currentIndex=indices[current];
        for (int b=0;b<current->getBondConstraintCount();++b) {
            TemplateMolecule* partner=current->getBondPartner(b);
            const int partnerComponent=current->getBondPartnerComponent(b);
            const int component=current->getBondComponent(b);
            if (!partner || component<0 || partnerComponent<0 || partner->getN_symComps()!=0) { out.clear(); return; }
            auto found=indices.find(partner);
            if (found==indices.end()) {
                if (!appendNode(partner, std::numeric_limits<std::uint16_t>::max())) return;
                found=indices.find(partner);
            }
            const std::size_t partnerIndex=found->second;
            if (currentIndex < partnerIndex) {
                NativeGraphEdgeSnapshot edge; edge.first_node=currentIndex; edge.first_component=static_cast<std::uint32_t>(component); edge.second_node=partnerIndex; edge.second_component=static_cast<std::uint32_t>(partnerComponent); graph.edges.push_back(edge);
            }
        }
    }
    if (graph.edges.empty() || graph.nodes.size() <= roots.size()) { return; }
    out.push_back(graph);
}

void NativeNFsimSystemReader::collectCompartments(std::vector<NativeCompartmentSnapshot>& out) const {
    out.clear();
    const auto& compartments=system_.getCompartments();
    for (const auto& entry : compartments) {
        Compartment* c=entry.second;
        NativeCompartmentSnapshot snapshot; snapshot.id=nativeCompartmentId(c->getId()); snapshot.dimensions=c->getSpatialDimensions(); snapshot.size=c->getSize();
        snapshot.parent=c->getParent() ? nativeCompartmentId(c->getParent()->getId()) : std::numeric_limits<std::uint32_t>::max();
        out.push_back(snapshot);
    }
}
void NativeNFsimSystemReader::collectDependencies(std::size_t i,std::vector<NativeDependencySnapshot>& out) const{
    ReactionClass* r=system_.getReaction(static_cast<int>(i));
    std::vector<TemplateMolecule*> roots;
    for (int p = 0; p < r->getNumOfReactants(); ++p) roots.push_back(r->getReactantTemplate(p));
    std::vector<NativeGraphPatternSnapshot> graphPatterns;
    collectGraphPatterns(i, graphPatterns);
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
                // The captured graph carries this internal relation. Adding
                // an unresolved topology marker would force fallback again.
                if (graphPatterns.empty()) append(NATIVE_TOPOLOGY, bond.component, -1);
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
    ReactionClass* r=system_.getReaction(static_cast<int>(i));
    TransformationSet* ts=r->getTransformationSet();
    if(!ts)return;
    std::vector<std::vector<NFsimPublicTransformView> > views(
        static_cast<std::size_t>(std::max(1,r->getNumOfReactants())));
    for(int p=0;p<r->getNumOfReactants();++p){
        for(int x=0;x<ts->getNumOfTransformations(p);++x){
            Transformation* t=ts->getTransformation(p,x);
            NFsimPublicTransformView v;
            v.kind=t->getType();
            v.reactant=static_cast<std::uint16_t>(p);
            int ci=-1;
            switch(t->getType()){
                case TransformationFactory::STATE_CHANGE:
                case TransformationFactory::BINDING:
                case TransformationFactory::UNBINDING:
                case TransformationFactory::EMPTY:
                case TransformationFactory::INCREMENT_STATE:
                case TransformationFactory::DECREMENT_STATE:
                    ci=t->getComponentIndex(); break;
                default: break;
            }
            v.component=ci<0?0u:static_cast<std::uint32_t>(ci);
            if(t->getType()==TransformationFactory::STATE_CHANGE){
                StateChangeTransform* q=dynamic_cast<StateChangeTransform*>(t);
                if(!q)throw std::logic_error("state transform type mismatch");
                v.final_state=q->getFinalStateValue();
            }else if(t->getType()==TransformationFactory::BINDING){
                BindingTransform* q=dynamic_cast<BindingTransform*>(t);
                if(!q)throw std::logic_error("binding transform type mismatch");
                v.other_reactant=q->getOtherReactantIndex();
                v.other_mapping_index=q->getOtherMappingIndex();
            }else if(t->getType()==TransformationFactory::EMPTY && ci>=0){
                v.second_binding_half=true;
            }else if(t->getType()==TransformationFactory::REMOVE){
                v.removal_type=t->getRemovalType();
            }else if(t->getType()==TransformationFactory::ADD){
                AddMoleculeTransform* q=dynamic_cast<AddMoleculeTransform*>(t);
                if(q){
                    if(q->isPopulationType()){
                        v.kind=TransformationFactory::INCREMENT_POPULATION;
                        v.population_delta=1;
                    }else if(q->getMoleculeType()){
                        v.added_molecule_type=static_cast<std::uint32_t>(
                            q->getMoleculeType()->getTypeID());
                    }
                }
            }else if(t->getType()==TransformationFactory::DECREMENT_POPULATION){
                v.population_delta=1;
            }else if(t->getType()==TransformationFactory::MOVE){
                MoveTransformation* q=dynamic_cast<MoveTransformation*>(t);
                if(q){
                    v.destination_compartment=nativeCompartmentId(q->getNewCompartmentId());
                    v.move_connected=q->isMoveConnected();
                }
            }
            views[static_cast<std::size_t>(p)].push_back(v);
        }
    }
    for (int x = 0; x < ts->getNumOfAddMoleculeTransforms(); ++x) {
        AddMoleculeTransform* add = ts->getAddMoleculeTransform(static_cast<unsigned int>(x));
        if (!add || !add->getMoleculeType())
            throw std::logic_error("NFsim add-molecule transform has no molecule type");
        NFsimPublicTransformView v;
        v.kind = add->isPopulationType() ? TransformationFactory::INCREMENT_POPULATION
                                          : TransformationFactory::ADD;
        v.reactant = 0;
        v.added_molecule_type = static_cast<std::uint32_t>(add->getMoleculeType()->getTypeID());
        if (add->isPopulationType()) v.population_delta = 1;
        views[0].push_back(v);
    }
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
