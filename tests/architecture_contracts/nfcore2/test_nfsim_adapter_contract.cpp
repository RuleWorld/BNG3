#include "test_harness.hh"
#include "nfsim_adapter_contract.hh"
#include "engine.hh"
#include <limits>
using namespace NFcore2;

namespace {
NativeMoleculeTypeSnapshot mol(const char* n,unsigned comps,bool pop=false){NativeMoleculeTypeSnapshot x;x.name=n;x.component_count=comps;x.population=pop;return x;}
NativeDependencySnapshot dep(NativeDependencyKind k,unsigned reactant,unsigned comp,int state=-1){NativeDependencySnapshot d;d.kind=k;d.reactant=reactant;d.component=comp;d.state=state;return d;}
NativeTransformSnapshot tr(NativeTransformKind k,unsigned reactant,unsigned comp=0){NativeTransformSnapshot t;t.kind=k;t.reactant=reactant;t.component=comp;return t;}
NativeReactionSnapshot rxn(){NativeReactionSnapshot r;r.name="r";r.base_rate=2.0;return r;}
}

TEST(NFsimAdapter_EmptySnapshotLowersEmptyModel){
    NativeModelSnapshot n; LegacyModelIR m=NFsimSnapshotAdapter::toLegacy(n);
    EXPECT_TRUE(m.rules.empty()); EXPECT_TRUE(m.molecule_types.empty());
}

TEST(NFsimAdapter_MoleculeTypeBecomesCompactDescriptor){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",5));
    LegacyModelIR m=NFsimSnapshotAdapter::toLegacy(n);
    EXPECT_EQ(m.molecule_types.size(),1u); EXPECT_EQ(m.molecule_types[0].name,std::string("R"));
    EXPECT_EQ(m.molecule_types[0].state_words,5u); EXPECT_EQ(m.molecule_types[0].bond_slots,5u);
}

TEST(NFsimAdapter_PopulationTypeDoesNotAllocateParticleSlots){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("ATP",1,true));
    LegacyModelIR m=NFsimSnapshotAdapter::toLegacy(n);
    EXPECT_EQ(m.molecule_types[0].state_words,0u); EXPECT_EQ(m.molecule_types[0].bond_slots,0u);
}

TEST(NFsimAdapter_BuildsStateAndBondFeaturesPerParticleComponent){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",3));
    LegacyModelIR m=NFsimSnapshotAdapter::toLegacy(n);
    EXPECT_EQ(m.features.size(),8u);
    EXPECT_EQ(m.features[0].kind,FEATURE_MOLECULE_STATE); EXPECT_EQ(m.features[0].owner,0u); EXPECT_EQ(m.features[0].index,0u);
    EXPECT_EQ(m.features[3].kind,FEATURE_MOLECULE_BOND); EXPECT_EQ(m.features[3].index,0u);
}

TEST(NFsimAdapter_PopulationTypeBuildsPopulationFeature){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("ATP",1,true));
    LegacyModelIR m=NFsimSnapshotAdapter::toLegacy(n);
    EXPECT_EQ(m.features.size(),1u); EXPECT_EQ(m.features[0].kind,FEATURE_POPULATION); EXPECT_EQ(m.features[0].owner,0u);
}

TEST(NFsimAdapter_StateRequiredBecomesExactStatePredicate){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",2));NativeReactionSnapshot r=rxn();r.dependencies.push_back(dep(NATIVE_STATE_REQUIRED,0,1,4));n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(x.predicates.size(),1u); EXPECT_EQ(x.predicates[0].kind,LEGACY_PRED_STATE_MASK); EXPECT_EQ(x.predicates[0].target,0u);
    EXPECT_EQ(x.predicates[0].a,1u); EXPECT_EQ(x.predicates[0].mask,~std::uint64_t(0)); EXPECT_EQ(x.predicates[0].value,4u);
}

TEST(NFsimAdapter_StateExcludedBecomesNotEqualPredicate){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",2));NativeReactionSnapshot r=rxn();r.dependencies.push_back(dep(NATIVE_STATE_EXCLUDED,0,1,7));n.rules.push_back(r);
    EXPECT_EQ(NFsimSnapshotAdapter::toLegacy(n).rules[0].predicates[0].kind,LEGACY_PRED_STATE_NOT_EQUAL);
}

TEST(NFsimAdapter_BondFreeAndBoundBecomeLocalPredicates){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",2));NativeReactionSnapshot r=rxn();r.dependencies.push_back(dep(NATIVE_BOND_FREE,0,0));r.dependencies.push_back(dep(NATIVE_BOND_BOUND,0,1));n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(x.predicates[0].kind,LEGACY_PRED_BOND_FREE); EXPECT_EQ(x.predicates[1].kind,LEGACY_PRED_BOND_PRESENT);
}

TEST(NFsimAdapter_DirectBondToPreservesPartnerReactantAndComponent){
    NativeModelSnapshot n;
    n.molecule_types.push_back(mol("A",2));
    n.molecule_types.push_back(mol("B",3));
    NativeReactionSnapshot r=rxn();
    r.reactant_types.push_back(0); r.reactant_types.push_back(1);
    NativeDependencySnapshot d=dep(NATIVE_BOND_TO,0,1);
    d.partner_reactant=1; d.partner_component=2;
    r.dependencies.push_back(d); n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(x.predicates.size(),3u);
    EXPECT_EQ(x.predicates[0].kind,LEGACY_PRED_TYPE_EXISTS);
    EXPECT_EQ(x.predicates[1].kind,LEGACY_PRED_TYPE_EXISTS);
    EXPECT_EQ(x.predicates[0].a,0u);
    EXPECT_EQ(x.predicates[1].a,1u);
    EXPECT_EQ(x.predicates[2].kind,LEGACY_PRED_BOND_TO);
    EXPECT_EQ(x.predicates[2].target,0u);
    EXPECT_EQ(x.predicates[2].a,1u);
    EXPECT_EQ(x.predicates[2].b,1u);
    EXPECT_EQ(x.predicates[2].value,2u);
    EXPECT_TRUE(x.predicates[2].has_partner_component);
    EXPECT_FALSE(x.uses_connected_to);
}

TEST(NFsimAdapter_DirectBondToInvalidatesBothBondFeatures){
    NativeModelSnapshot n;
    n.molecule_types.push_back(mol("A",2));
    n.molecule_types.push_back(mol("B",3));
    NativeReactionSnapshot r=rxn();
    r.reactant_types.push_back(0); r.reactant_types.push_back(1);
    NativeDependencySnapshot d=dep(NATIVE_BOND_TO,0,1);
    d.partner_reactant=1; d.partner_component=2;
    r.dependencies.push_back(d); n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    EXPECT_EQ(lowered.supported_rule_count,1u);
    const DependencyIndex& index=lowered.executable.metadata().dependencies();
    std::pair<const MatcherId*,const MatcherId*> source=index.dependents(FeatureId(3));
    std::pair<const MatcherId*,const MatcherId*> partner=index.dependents(FeatureId(9));
    EXPECT_TRUE(source.first!=source.second);
    EXPECT_TRUE(partner.first!=partner.second);
    EXPECT_EQ(*source.first,*partner.first);
}

TEST(NFsimAdapter_StateDependencyKeysMoleculeTypeOwner){
    NativeModelSnapshot n;
    n.molecule_types.push_back(mol("A",1));
    n.molecule_types.push_back(mol("B",2));
    NativeReactionSnapshot left=rxn();
    left.reactant_types.push_back(0);
    left.dependencies.push_back(dep(NATIVE_STATE_REQUIRED,0,0,1));
    NativeReactionSnapshot right=rxn();
    right.name="right";
    right.reactant_types.push_back(1);
    right.dependencies.push_back(dep(NATIVE_STATE_REQUIRED,0,0,1));
    n.rules.push_back(left);
    n.rules.push_back(right);

    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    const DependencyIndex& index=lowered.executable.metadata().dependencies();
    std::pair<const MatcherId*,const MatcherId*> leftDependents=index.dependents(FeatureId(0));
    std::pair<const MatcherId*,const MatcherId*> rightDependents=index.dependents(FeatureId(2));
    EXPECT_TRUE(leftDependents.first!=leftDependents.second);
    EXPECT_TRUE(rightDependents.first!=rightDependents.second);
    EXPECT_EQ(rightDependents.second-rightDependents.first,1);
    EXPECT_EQ(leftDependents.second-leftDependents.first,1);
    EXPECT_NE(*leftDependents.first,*rightDependents.first);
}

TEST(NFsimAdapter_InternalTopologyIsConservativeFallback){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",2));NativeReactionSnapshot r=rxn();r.dependencies.push_back(dep(NATIVE_TOPOLOGY,0,0));n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_TRUE(x.uses_connected_to); EXPECT_EQ(x.predicates.size(),0u);
}

TEST(NFsimAdapter_PartnerStateIsConservativeFallbackUntilInternalVariablesExist){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",2));NativeReactionSnapshot r=rxn();r.dependencies.push_back(dep(NATIVE_PARTNER_STATE_REQUIRED,0,0,1));n.rules.push_back(r);
    EXPECT_TRUE(NFsimSnapshotAdapter::toLegacy(n).rules[0].uses_connected_to);
}

TEST(NFsimAdapter_StateChangeTransformGetsExactFeature){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",3));NativeReactionSnapshot r=rxn();NativeTransformSnapshot t=tr(NATIVE_STATE_CHANGE,0,2);t.new_value=5;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(x.transforms[0].kind,LEGACY_TRANSFORM_SET_STATE_WORD); EXPECT_EQ(x.transforms[0].target,0u); EXPECT_EQ(x.transforms[0].a,2u); EXPECT_EQ(x.transforms[0].value,5);
    EXPECT_TRUE(x.transforms[0].changed_feature.valid());
}

TEST(NFsimAdapter_BindingTransformUsesBothReactantEndpoints){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("A",2));n.molecule_types.push_back(mol("B",3));NativeReactionSnapshot r=rxn();NativeTransformSnapshot t=tr(NATIVE_BINDING,0,1);t.other_reactant=1;t.other_component=2;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(x.transforms[0].kind,LEGACY_TRANSFORM_BIND);EXPECT_EQ(x.transforms[0].target,0u);EXPECT_EQ(x.transforms[0].other,1u);EXPECT_EQ(x.transforms[0].a,1u);EXPECT_EQ(x.transforms[0].b,2u);
    EXPECT_TRUE(x.topology_change_is_local);
}

TEST(NFsimAdapter_UnbindingTransformUsesKnownPartnerComponent){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("A",2));NativeReactionSnapshot r=rxn();NativeTransformSnapshot t=tr(NATIVE_UNBINDING,0,1);t.other_component=0;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(x.transforms[0].kind,LEGACY_TRANSFORM_UNBIND);EXPECT_EQ(x.transforms[0].a,1u);EXPECT_EQ(x.transforms[0].b,0u);EXPECT_TRUE(x.topology_change_is_local);
}

TEST(NFsimAdapter_DeleteSingleMoleculeIsLocalDelete){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.reactant_types.push_back(0);NativeTransformSnapshot t=tr(NATIVE_REMOVE,0);t.removal_type=NATIVE_DELETE_MOLECULE_ONLY;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];EXPECT_EQ(x.transforms[0].kind,LEGACY_TRANSFORM_DELETE_MOLECULE);EXPECT_TRUE(x.topology_change_is_local);
}

TEST(NFsimAdapter_DeleteWholeSpeciesLowersToSpeciesDelete){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.reactant_types.push_back(0);NativeTransformSnapshot t=tr(NATIVE_REMOVE,0);t.removal_type=NATIVE_DELETE_COMPLETE_SPECIES;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];EXPECT_TRUE(x.changes_topology);EXPECT_TRUE(x.topology_change_is_local);EXPECT_EQ(x.transforms[0].kind,LEGACY_TRANSFORM_DELETE_SPECIES);
}

TEST(NFsimAdapter_DeleteWholeSpeciesRemovesConnectedComponent){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("A",2));n.molecule_types.push_back(mol("B",1));
    NativeReactionSnapshot r=rxn();r.reactant_types.push_back(0);NativeTransformSnapshot t=tr(NATIVE_REMOVE,0);t.removal_type=NATIVE_DELETE_COMPLETE_SPECIES;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));Engine engine(lowered.executable);
    MoleculeHandle a=engine.state().molecules(MoleculeTypeId(0)).create(),b=engine.state().molecules(MoleculeTypeId(1)).create();
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(1),b));engine.state().molecules(MoleculeTypeId(1)).setBondRef(b,0,MoleculeRef(MoleculeTypeId(0),a));
    MatchContext context;context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));FeatureDelta delta;
    EXPECT_TRUE(engine.fire(lowered.rules[0].family,lowered.rules[0].member,context,delta));
    EXPECT_FALSE(engine.state().molecules(MoleculeTypeId(0)).alive(a));EXPECT_FALSE(engine.state().molecules(MoleculeTypeId(1)).alive(b));
}

TEST(NFsimAdapter_WholeSpeciesDeletionRequiresReactant){
    NativeModelSnapshot n;
    n.molecule_types.push_back(mol("R",1));
    NativeReactionSnapshot r=rxn();
    NativeTransformSnapshot t=tr(NATIVE_REMOVE,0);
    t.removal_type=NATIVE_DELETE_COMPLETE_SPECIES;
    r.transforms.push_back(t);
    n.rules.push_back(r);
    EXPECT_THROW(NFsimSnapshotAdapter::toLegacy(n),std::invalid_argument);
}

TEST(NFsimAdapter_IncrementAndDecrementStateLowerToCheckedAdd){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot a=rxn();a.transforms.push_back(tr(NATIVE_INCREMENT_STATE,0,0));NativeReactionSnapshot b=rxn();b.transforms.push_back(tr(NATIVE_DECREMENT_STATE,0,0));n.rules.push_back(a);n.rules.push_back(b);
    LegacyModelIR m=NFsimSnapshotAdapter::toLegacy(n);EXPECT_EQ(m.rules[0].transforms[0].kind,LEGACY_TRANSFORM_ADD_STATE_WORD);EXPECT_EQ(m.rules[0].transforms[0].value,1);EXPECT_EQ(m.rules[1].transforms[0].kind,LEGACY_TRANSFORM_ADD_STATE_WORD);EXPECT_EQ(m.rules[1].transforms[0].value,-1);
}

TEST(NFsimAdapter_LocalFunctionReferenceMarksRuleFallback){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.transforms.push_back(tr(NATIVE_LOCAL_FUNCTION_REFERENCE,0));n.rules.push_back(r);
    EXPECT_TRUE(NFsimSnapshotAdapter::toLegacy(n).rules[0].uses_local_function);
}

TEST(NFsimAdapter_MoveCompartmentLowersDirectly){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.transforms.push_back(tr(NATIVE_MOVE,0));n.rules.push_back(r);
    EXPECT_EQ(NFsimSnapshotAdapter::toLegacy(n).rules[0].transforms[0].kind,LEGACY_TRANSFORM_MOVE_MOLECULE);
}

TEST(NFsimAdapter_MoveConnectedLowersToSpeciesMove){
    NativeModelSnapshot n;
    n.molecule_types.push_back(mol("R",1));
    NativeReactionSnapshot r=rxn();
    r.reactant_types.push_back(0);
    NativeTransformSnapshot move=tr(NATIVE_MOVE,0);
    move.move_connected=true;
    r.transforms.push_back(move);
    n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    EXPECT_EQ(lowered.supported_rule_count,1u);
    EXPECT_EQ(lowered.fallback_rule_count,0u);
    EXPECT_TRUE(lowered.rules[0].supported());
}

TEST(NFsimAdapter_PopulationTransformsLowerToSignedPopulationDelta){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("ATP",0,true));
    NativeReactionSnapshot r=rxn();
    NativeTransformSnapshot add=tr(NATIVE_INCREMENT_POPULATION,0);add.population_delta=3;
    NativeTransformSnapshot sub=tr(NATIVE_DECREMENT_POPULATION,0);sub.population_delta=2;
    r.transforms.push_back(add);r.transforms.push_back(sub);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(x.transforms.size(),2u);
    EXPECT_EQ(x.transforms[0].kind,LEGACY_TRANSFORM_POPULATION_ADD);
    EXPECT_EQ(x.transforms[0].value,3ll);
    EXPECT_EQ(x.transforms[1].kind,LEGACY_TRANSFORM_POPULATION_ADD);
    EXPECT_EQ(x.transforms[1].value,-2ll);
    EXPECT_TRUE(x.transforms[0].changed_feature.valid());
}

TEST(NFsimAdapter_PopulationRuleExecutesAgainstPopulationStore){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("ATP",0,true));
    NativeReactionSnapshot r=rxn();NativeTransformSnapshot t=tr(NATIVE_INCREMENT_POPULATION,0);t.population_delta=3;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    Engine engine(lowered.executable);MatchContext context;FeatureDelta delta;
    EXPECT_TRUE(engine.fire(lowered.rules[0].family,lowered.rules[0].member,context,delta));
    EXPECT_EQ(engine.state().populations().value(PopulationId(0)),3ll);
}

TEST(NFsimAdapter_ZeroReactantPopulationSynthesisUsesAddedType){
    NativeModelSnapshot n;
    n.molecule_types.push_back(mol("A",1));
    n.molecule_types.push_back(mol("P",0,true));
    NativeReactionSnapshot r=rxn();
    NativeTransformSnapshot t=tr(NATIVE_INCREMENT_POPULATION,0);
    t.added_molecule_type=1;
    t.population_delta=4;
    r.transforms.push_back(t);
    n.rules.push_back(r);

    LegacyModelIR legacy=NFsimSnapshotAdapter::toLegacy(n);
    EXPECT_EQ(legacy.rules[0].transforms.size(),1u);
    EXPECT_EQ(legacy.rules[0].transforms[0].kind,LEGACY_TRANSFORM_POPULATION_ADD);
    EXPECT_EQ(legacy.rules[0].transforms[0].a,0u);
    EXPECT_EQ(legacy.rules[0].transforms[0].value,4ll);

    LegacyLoweringResult lowered=LegacyLowerer::lower(legacy);
    Engine engine(lowered.executable);MatchContext context;FeatureDelta delta;
    EXPECT_TRUE(engine.fire(lowered.rules[0].family,lowered.rules[0].member,context,delta));
    EXPECT_EQ(engine.state().populations().value(PopulationId(0)),4ll);
}

TEST(NFsimAdapter_RootInternalTopologyAndPartnerStateLowerDirectly){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("A",2));n.molecule_types.push_back(mol("B",2));
    NativeReactionSnapshot r=rxn();r.reactant_types.push_back(0);r.reactant_types.push_back(1);
    NativeDependencySnapshot edge=dep(NATIVE_TOPOLOGY,0,0);edge.partner_reactant=1;edge.partner_component=1;
    NativeDependencySnapshot state=dep(NATIVE_PARTNER_STATE_REQUIRED,0,0,7);state.partner_reactant=1;state.partner_state_component=0;
    r.dependencies.push_back(edge);r.dependencies.push_back(state);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_FALSE(x.uses_connected_to);
    EXPECT_EQ(x.predicates.size(),4u);
    EXPECT_EQ(x.predicates[2].kind,LEGACY_PRED_BOND_TO);
    EXPECT_EQ(x.predicates[2].b,1u);
    EXPECT_EQ(x.predicates[3].kind,LEGACY_PRED_STATE_MASK);
    EXPECT_EQ(x.predicates[3].target,1u);
    EXPECT_EQ(x.predicates[3].a,0u);
    EXPECT_EQ(x.predicates[3].value,7u);
}

TEST(NFsimAdapter_ConnectedToPredicateUsesGraphSearchForRootReactants){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("A",2));n.molecule_types.push_back(mol("B",1));
    NativeReactionSnapshot r=rxn();r.reactant_types.push_back(0);r.reactant_types.push_back(1);
    NativeDependencySnapshot edge=dep(NATIVE_TOPOLOGY,0,0);edge.partner_reactant=1;edge.partner_component=NATIVE_INFER_PARTNER_COMPONENT;
    r.dependencies.push_back(edge);n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    EXPECT_EQ(lowered.supported_rule_count,1u);EXPECT_FALSE(lowered.rules[0].reason==LOWERING_CONNECTED_TO);
    Engine engine(lowered.executable);MoleculeHandle a=engine.state().molecules(MoleculeTypeId(0)).create();
    MoleculeHandle bridge=engine.state().molecules(MoleculeTypeId(0)).create();MoleculeHandle b=engine.state().molecules(MoleculeTypeId(1)).create();
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(0),bridge));
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(bridge,0,MoleculeRef(MoleculeTypeId(0),a));
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(bridge,1,MoleculeRef(MoleculeTypeId(1),b));
    MatchContext context;context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));context.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),b));
    EXPECT_TRUE(lowered.executable.matchers().at(lowered.executable.metadata().ruleFamilies()[0].matcher).evaluate(engine.state(),engine.scaffolds(),context));
}

TEST(NFsimAdapter_SynthesisCreatesAddedMoleculeFromZeroReactants){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("A",1));n.molecule_types.push_back(mol("B",1));
    NativeReactionSnapshot r=rxn();NativeTransformSnapshot t=tr(NATIVE_ADD,0);t.added_molecule_type=1;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(x.transforms.size(),1u);
    EXPECT_EQ(x.transforms[0].kind,LEGACY_TRANSFORM_CREATE_MOLECULE);
    EXPECT_EQ(x.transforms[0].target,0u);
    EXPECT_EQ(x.transforms[0].a,1u);
    EXPECT_TRUE(x.transforms[0].changed_feature.valid());
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    EXPECT_EQ(lowered.supported_rule_count,1u);
}

TEST(NFsimAdapter_SynthesisRuleCreatesMoleculeInEngine){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("A",1));n.molecule_types.push_back(mol("B",1));
    NativeReactionSnapshot r=rxn();NativeTransformSnapshot t=tr(NATIVE_ADD,0);t.added_molecule_type=1;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    Engine engine(lowered.executable);MatchContext context;FeatureDelta delta;
    EXPECT_TRUE(engine.fire(lowered.rules[0].family,lowered.rules[0].member,context,delta));
    EXPECT_TRUE(context.moleculeAt(0).valid());EXPECT_EQ(context.moleculeAt(0).type,MoleculeTypeId(1));
    EXPECT_EQ(engine.state().molecules(MoleculeTypeId(1)).liveCount(),1u);
}

TEST(NFsimAdapter_CompartmentPredicateAndMoveLowerDirectly){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));
    NativeReactionSnapshot r=rxn();r.reactant_types.push_back(0);
    NativeDependencySnapshot c=dep(NATIVE_COMPARTMENT_REQUIRED,0,0);c.compartment=2;
    NativeTransformSnapshot m=tr(NATIVE_MOVE,0);m.destination_compartment=3;
    r.dependencies.push_back(c);r.transforms.push_back(m);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(x.predicates.size(),2u);
    EXPECT_EQ(x.predicates[1].kind,LEGACY_PRED_COMPARTMENT);
    EXPECT_EQ(x.predicates[1].target,0u);
    EXPECT_EQ(x.predicates[1].value,2u);
    EXPECT_EQ(x.transforms[0].kind,LEGACY_TRANSFORM_MOVE_MOLECULE);
    EXPECT_EQ(x.transforms[0].a,3u);
}

TEST(NFsimAdapter_CompartmentRuleMatchesAndMovesMolecule){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));
    NativeReactionSnapshot r=rxn();r.reactant_types.push_back(0);NativeDependencySnapshot c=dep(NATIVE_COMPARTMENT_REQUIRED,0,0);c.compartment=2;
    NativeTransformSnapshot m=tr(NATIVE_MOVE,0);m.destination_compartment=3;r.dependencies.push_back(c);r.transforms.push_back(m);n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));Engine engine(lowered.executable);
    MoleculeHandle handle=engine.state().molecules(MoleculeTypeId(0)).create();engine.state().molecules(MoleculeTypeId(0)).setCompartment(handle,2);
    MatchContext context;context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),handle));FeatureDelta delta;
    EXPECT_TRUE(engine.fire(lowered.rules[0].family,lowered.rules[0].member,context,delta));
    EXPECT_EQ(engine.state().molecules(MoleculeTypeId(0)).compartment(handle),3u);
}

TEST(NFsimAdapter_CompartmentDependencyUsesMoleculeTypeOwner){
    NativeModelSnapshot n;
    n.molecule_types.push_back(mol("A",1));
    n.molecule_types.push_back(mol("R",1));
    NativeReactionSnapshot r=rxn();
    r.reactant_types.push_back(1);
    NativeDependencySnapshot c=dep(NATIVE_COMPARTMENT_REQUIRED,0,0);
    c.compartment=2;
    r.dependencies.push_back(c);
    NativeTransformSnapshot move=tr(NATIVE_MOVE,0);
    move.destination_compartment=3;
    r.transforms.push_back(move);
    n.rules.push_back(r);

    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    Engine engine(lowered.executable);
    MoleculeHandle handle=engine.state().molecules(MoleculeTypeId(1)).create();
    engine.state().molecules(MoleculeTypeId(1)).setCompartment(handle,2);
    MatchContext context;
    context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(1),handle));
    FeatureDelta delta;
    EXPECT_TRUE(engine.fire(lowered.rules[0].family,lowered.rules[0].member,context,delta));
    EXPECT_EQ(engine.affectedFamilies(delta).size(),1u);
}

TEST(NFsimAdapter_LocalFunctionAndDORRateLawsCarryExecutableDescriptors){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));n.molecule_types.push_back(mol("S",1));
    NativeReactionSnapshot local=rxn();local.reactant_types.push_back(0);local.rate_law=NATIVE_RATE_LOCAL_LINEAR;local.local_offset=1.0;local.local_slope=0.5;local.local_state_component=0;
    NativeReactionSnapshot dor=rxn();dor.reactant_types.push_back(0);dor.reactant_types.push_back(1);dor.rate_law=NATIVE_RATE_DOR_PRODUCT;dor.dor_weight=2.0;
    n.rules.push_back(local);n.rules.push_back(dor);
    LegacyModelIR m=NFsimSnapshotAdapter::toLegacy(n);
    EXPECT_FALSE(m.rules[0].uses_local_function);EXPECT_FALSE(m.rules[1].uses_local_function);
    EXPECT_EQ(m.rules[0].rate_law.kind,LEGACY_RATE_LOCAL_LINEAR);
    EXPECT_EQ(m.rules[1].rate_law.kind,LEGACY_RATE_DOR_PRODUCT);
    EXPECT_NEAR(m.rules[0].rate_law.offset,1.0,1e-12);
    EXPECT_NEAR(m.rules[1].rate_law.weight,2.0,1e-12);
}

TEST(NFsimAdapter_LocalFunctionAndDORRatesEvaluateFromMatchedState){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));n.molecule_types.push_back(mol("S",1));
    NativeReactionSnapshot local=rxn();local.base_rate=2.0;local.reactant_types.push_back(0);local.rate_law=NATIVE_RATE_LOCAL_LINEAR;local.local_offset=1.0;local.local_slope=0.5;
    NativeReactionSnapshot dor=rxn();dor.base_rate=3.0;dor.reactant_types.push_back(0);dor.reactant_types.push_back(1);dor.rate_law=NATIVE_RATE_DOR_PRODUCT;dor.dor_weight=2.0;
    n.rules.push_back(local);n.rules.push_back(dor);LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));Engine engine(lowered.executable);
    MoleculeHandle left=engine.state().molecules(MoleculeTypeId(0)).create(),right=engine.state().molecules(MoleculeTypeId(1)).create();
    engine.state().molecules(MoleculeTypeId(0)).setStateWord(left,0,4);engine.state().molecules(MoleculeTypeId(1)).setStateWord(right,0,9);
    MatchContext context;context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),left));context.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),right));
    EXPECT_NEAR(engine.evaluateRate(lowered.rules[0].family,lowered.rules[0].member,context),6.0,1e-12);
    EXPECT_NEAR(engine.evaluateRate(lowered.rules[1].family,lowered.rules[1].member,context),6.0,1e-12);
}

TEST(NFsimAdapter_ConstantRateEvaluationRejectsInvalidPropensity){
    CompiledModel model;SimulationState state(model);MatchContext context;RateLawDescriptor law;
    EXPECT_THROW(law.evaluate(state,context,-1.0),std::domain_error);
    EXPECT_THROW(law.evaluate(state,context,std::numeric_limits<double>::infinity()),std::domain_error);
}

TEST(NFsimAdapter_PreservesRateParameterCoordinateAndName){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.name="elong_42";r.base_rate=3.5;r.parameter_index=9;r.coordinate=42;n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];EXPECT_EQ(x.name,std::string("elong_42"));EXPECT_EQ(x.rate,3.5);EXPECT_EQ(x.parameter_index,9u);EXPECT_EQ(x.coordinate,42u);
}

TEST(NFsimAdapter_EmptyReactantPatternStillRequiresLiveType){
    NativeModelSnapshot n;
    n.molecule_types.push_back(mol("R",1));
    NativeReactionSnapshot r=rxn();
    r.reactant_types.push_back(0);
    n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(x.predicates.size(),1u);
    EXPECT_EQ(x.predicates[0].kind,LEGACY_PRED_TYPE_EXISTS);
    EXPECT_EQ(x.predicates[0].target,0u);
    EXPECT_EQ(x.predicates[0].a,0u);
}

TEST(NFsimAdapter_RejectsDependencyReactantOutOfRange){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.reactant_types.push_back(0);r.dependencies.push_back(dep(NATIVE_STATE_REQUIRED,1,0,1));n.rules.push_back(r);
    EXPECT_THROW(NFsimSnapshotAdapter::toLegacy(n),std::out_of_range);
}

TEST(NFsimAdapter_RejectsDependencyComponentOutOfRange){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.reactant_types.push_back(0);r.dependencies.push_back(dep(NATIVE_STATE_REQUIRED,0,5,1));n.rules.push_back(r);
    EXPECT_THROW(NFsimSnapshotAdapter::toLegacy(n),std::out_of_range);
}

TEST(NFsimAdapter_RejectsTransformReactantOutOfRange){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.reactant_types.push_back(0);r.transforms.push_back(tr(NATIVE_STATE_CHANGE,2,0));n.rules.push_back(r);
    EXPECT_THROW(NFsimSnapshotAdapter::toLegacy(n),std::out_of_range);
}

TEST(NFsimAdapter_RejectsNonfiniteBaseRate){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.base_rate=std::numeric_limits<double>::infinity();n.rules.push_back(r);
    EXPECT_THROW(NFsimSnapshotAdapter::toLegacy(n),std::invalid_argument);
}

TEST(NFsimAdapter_OneThousandRepeatedSnapshotsCollapseAfterLowering){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",2));
    for(unsigned i=0;i<1000;++i){NativeReactionSnapshot r=rxn();r.name="elong";r.coordinate=i;r.reactant_types.push_back(0);r.dependencies.push_back(dep(NATIVE_STATE_REQUIRED,0,0,1));NativeTransformSnapshot t=tr(NATIVE_STATE_CHANGE,0,0);t.new_value=2;r.transforms.push_back(t);n.rules.push_back(r);}
    LegacyLoweringResult out=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    EXPECT_EQ(out.supported_rule_count,1000u);EXPECT_EQ(out.executable.metadata().ruleFamilies().size(),1u);EXPECT_EQ(out.executable.metadata().ruleFamilies()[0].members.size(),1000u);
}

TEST(NFsimAdapter_UnbindingCanRequestReciprocalPartnerInference){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("A",2));NativeReactionSnapshot r=rxn();NativeTransformSnapshot t=tr(NATIVE_UNBINDING,0,1);t.other_component=NATIVE_INFER_PARTNER_COMPONENT;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(x.transforms[0].kind,LEGACY_TRANSFORM_UNBIND);EXPECT_EQ(x.transforms[0].b,TRANSFORM_INFER_PARTNER_SLOT);EXPECT_TRUE(x.topology_change_is_local);
}

TEST(NFsimAdapter_ArbitraryGraphExpressionMatchesInternalChain){
    NativeModelSnapshot n;
    n.molecule_types.push_back(mol("A",1));
    n.molecule_types.push_back(mol("B",2));
    n.molecule_types.push_back(mol("C",1));
    NativeReactionSnapshot r=rxn();
    r.reactant_types.push_back(0);
    NativeGraphPatternSnapshot g;
    NativeGraphNodeSnapshot a; a.molecule_type=0; a.reactant=0;
    NativeGraphNodeSnapshot b; b.molecule_type=1;
    NativeGraphNodeSnapshot c; c.molecule_type=2;
    g.nodes={a,b,c};
    NativeGraphEdgeSnapshot ab; ab.first_node=0; ab.first_component=0; ab.second_node=1; ab.second_component=0;
    NativeGraphEdgeSnapshot bc; bc.first_node=1; bc.first_component=1; bc.second_node=2; bc.second_component=0;
    g.edges={ab,bc};
    r.graph_patterns.push_back(g); n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    EXPECT_EQ(lowered.supported_rule_count,1u);
    Engine engine(lowered.executable);
    MoleculeHandle ah=engine.state().molecules(MoleculeTypeId(0)).create();
    MoleculeHandle bh=engine.state().molecules(MoleculeTypeId(1)).create();
    MoleculeHandle ch=engine.state().molecules(MoleculeTypeId(2)).create();
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(ah,0,MoleculeRef(MoleculeTypeId(1),bh));
    engine.state().molecules(MoleculeTypeId(1)).setBondRef(bh,0,MoleculeRef(MoleculeTypeId(0),ah));
    engine.state().molecules(MoleculeTypeId(1)).setBondRef(bh,1,MoleculeRef(MoleculeTypeId(2),ch));
    engine.state().molecules(MoleculeTypeId(2)).setBondRef(ch,0,MoleculeRef(MoleculeTypeId(1),bh));
    MatchContext context; context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),ah));
    EXPECT_TRUE(lowered.executable.matchers().at(lowered.executable.metadata().ruleFamilies()[0].matcher).evaluate(engine.state(),engine.scaffolds(),context));
}

TEST(NFsimAdapter_ArbitraryGraphExpressionPreservesFreeAndBoundSiteConstraints){
    NativeModelSnapshot n; n.molecule_types.push_back(mol("A",2));
    NativeReactionSnapshot r=rxn(); r.reactant_types.push_back(0);
    NativeGraphPatternSnapshot g; NativeGraphNodeSnapshot node; node.molecule_type=0; node.reactant=0;
    node.free_components.push_back(0); node.bound_components.push_back(1); g.nodes.push_back(node); r.graph_patterns.push_back(g); n.rules.push_back(r);
    LegacyRuleIR lowered=NFsimSnapshotAdapter::toLegacy(n).rules[0];
    EXPECT_EQ(lowered.graph_patterns.size(),1u);
    EXPECT_EQ(lowered.graph_patterns[0].nodes[0].free_components.size(),1u);
    EXPECT_EQ(lowered.graph_patterns[0].nodes[0].bound_components.size(),1u);
}

TEST(NFsimAdapter_ArbitraryGraphExpressionRejectsAsymmetricRuntimeBond){
    NativeModelSnapshot n; n.molecule_types.push_back(mol("A",1)); n.molecule_types.push_back(mol("B",1));
    NativeReactionSnapshot r=rxn(); r.reactant_types.push_back(0);
    NativeGraphPatternSnapshot g; NativeGraphNodeSnapshot a; a.molecule_type=0; a.reactant=0; NativeGraphNodeSnapshot b; b.molecule_type=1;
    g.nodes={a,b}; NativeGraphEdgeSnapshot edge; edge.first_node=0; edge.first_component=0; edge.second_node=1; edge.second_component=0; g.edges.push_back(edge); r.graph_patterns.push_back(g); n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n)); Engine engine(lowered.executable);
    const MoleculeHandle ah=engine.state().molecules(MoleculeTypeId(0)).create(); const MoleculeHandle bh=engine.state().molecules(MoleculeTypeId(1)).create();
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(ah,0,MoleculeRef(MoleculeTypeId(1),bh));
    MatchContext context; context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),ah));
    EXPECT_FALSE(lowered.executable.matchers().at(lowered.executable.metadata().ruleFamilies()[0].matcher).evaluate(engine.state(),engine.scaffolds(),context));
}

TEST(NFsimAdapter_RejectsMalformedGraphEdge){
    NativeModelSnapshot n; n.molecule_types.push_back(mol("A",1));
    NativeReactionSnapshot r=rxn(); r.reactant_types.push_back(0);
    NativeGraphPatternSnapshot g; NativeGraphNodeSnapshot node; node.molecule_type=0; node.reactant=0; g.nodes.push_back(node);
    NativeGraphEdgeSnapshot edge; edge.first_node=0; edge.second_node=2; g.edges.push_back(edge); r.graph_patterns.push_back(g); n.rules.push_back(r);
    EXPECT_THROW(NFsimSnapshotAdapter::toLegacy(n),std::invalid_argument);
}

TEST(NFsimAdapter_GeneralExpressionRateEvaluatesTimeAndBothDORReactants){
    NativeModelSnapshot n; n.molecule_types.push_back(mol("A",1)); n.molecule_types.push_back(mol("B",1));
    NativeReactionSnapshot r=rxn(); r.base_rate=1.0; r.reactant_types={0,1};
    r.rate_law=NATIVE_RATE_EXPRESSION; r.rate_expression="if(s0 > 2, s0 * s1 + time, 0)";
    r.rate_expression_components={0,0}; n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    Engine engine(lowered.executable); MoleculeHandle a=engine.state().molecules(MoleculeTypeId(0)).create(); MoleculeHandle b=engine.state().molecules(MoleculeTypeId(1)).create();
    engine.state().molecules(MoleculeTypeId(0)).setStateWord(a,0,3); engine.state().molecules(MoleculeTypeId(1)).setStateWord(b,0,4); engine.state().setTime(2.0);
    MatchContext context; context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a)); context.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),b));
    EXPECT_NEAR(engine.evaluateRate(lowered.rules[0].family,lowered.rules[0].member,context),14.0,1e-12);
}

TEST(NFsimAdapter_GeneralExpressionRateResolvesNamedLocalAndConstantBindings){
    NativeModelSnapshot n; n.molecule_types.push_back(mol("A",1)); n.molecule_types.push_back(mol("B",1));
    NativeReactionSnapshot r=rxn(); r.base_rate=2.0; r.reactant_types={0,1};
    r.rate_law=NATIVE_RATE_EXPRESSION; r.rate_expression="k * (left + right) + time";
    r.rate_expression_bindings.push_back(NativeRateExpressionBindingSnapshot::state("left",0,0));
    r.rate_expression_bindings.push_back(NativeRateExpressionBindingSnapshot::state("right",1,0));
    r.rate_expression_bindings.push_back(NativeRateExpressionBindingSnapshot::constant("k",3.0));
    n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    Engine engine(lowered.executable); MoleculeHandle a=engine.state().molecules(MoleculeTypeId(0)).create(); MoleculeHandle b=engine.state().molecules(MoleculeTypeId(1)).create();
    engine.state().molecules(MoleculeTypeId(0)).setStateWord(a,0,2); engine.state().molecules(MoleculeTypeId(1)).setStateWord(b,0,4); engine.state().setTime(1.0);
    MatchContext context; context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a)); context.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),b));
    EXPECT_NEAR(engine.evaluateRate(lowered.rules[0].family,lowered.rules[0].member,context),38.0,1e-12);
}

TEST(NFsimAdapter_CompartmentInsideRejectsUnknownIdentity){
    NativeModelSnapshot n; n.molecule_types.push_back(mol("A",1));
    NativeCompartmentSnapshot root; root.id=17; n.compartments.push_back(root);
    NativeReactionSnapshot r=rxn(); r.reactant_types.push_back(0); NativeDependencySnapshot d=dep(NATIVE_COMPARTMENT_REQUIRED,0,0); d.compartment=99; d.compartment_ancestry=true; r.dependencies.push_back(d); n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    Engine engine(lowered.executable); MoleculeHandle a=engine.state().molecules(MoleculeTypeId(0)).create(); engine.state().molecules(MoleculeTypeId(0)).setCompartment(a,99);
    MatchContext context; context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));
    EXPECT_FALSE(lowered.executable.matchers().at(lowered.executable.metadata().ruleFamilies()[0].matcher).evaluate(engine.state(),engine.scaffolds(),context));
}

TEST(NFsimAdapter_CompartmentHierarchyPredicateAndSpeciesMove){
    NativeModelSnapshot n; n.molecule_types.push_back(mol("A",1)); n.molecule_types.push_back(mol("B",1));
    NativeCompartmentSnapshot root; root.id=nativeCompartmentId("cell");
    NativeCompartmentSnapshot child; child.id=nativeCompartmentId("cyto"); child.parent=root.id; child.size=2.0; root.size=10.0;
    n.compartments={root,child};
    NativeReactionSnapshot r=rxn(); r.reactant_types.push_back(0);
    NativeDependencySnapshot d=dep(NATIVE_COMPARTMENT_REQUIRED,0,0); d.compartment=child.id; d.compartment_ancestry=true; r.dependencies.push_back(d);
    NativeTransformSnapshot t=tr(NATIVE_MOVE,0); t.destination_compartment=root.id; t.move_connected=true; r.transforms.push_back(t); n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    EXPECT_EQ(lowered.supported_rule_count,1u);
    Engine engine(lowered.executable); MoleculeHandle a=engine.state().molecules(MoleculeTypeId(0)).create(); MoleculeHandle b=engine.state().molecules(MoleculeTypeId(1)).create();
    engine.state().molecules(MoleculeTypeId(0)).setCompartment(a,child.id); engine.state().molecules(MoleculeTypeId(1)).setCompartment(b,child.id);
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(1),b)); engine.state().molecules(MoleculeTypeId(1)).setBondRef(b,0,MoleculeRef(MoleculeTypeId(0),a));
    MatchContext context; context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a)); FeatureDelta delta;
    EXPECT_TRUE(engine.fire(lowered.rules[0].family,lowered.rules[0].member,context,delta));
    EXPECT_EQ(engine.state().molecules(MoleculeTypeId(0)).compartment(a),root.id); EXPECT_EQ(engine.state().molecules(MoleculeTypeId(1)).compartment(b),root.id);
}

TEST(NFsimAdapter_SpeciesMoveRejectsUnknownDestinationAtomically){
    NativeModelSnapshot n; n.molecule_types.push_back(mol("A",1)); n.molecule_types.push_back(mol("B",1));
    NativeCompartmentSnapshot root; root.id=17; n.compartments.push_back(root);
    NativeReactionSnapshot r=rxn(); r.reactant_types.push_back(0); NativeTransformSnapshot t=tr(NATIVE_MOVE,0); t.destination_compartment=99; t.move_connected=true; r.transforms.push_back(t); n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n));
    Engine engine(lowered.executable); MoleculeHandle a=engine.state().molecules(MoleculeTypeId(0)).create(); MoleculeHandle b=engine.state().molecules(MoleculeTypeId(1)).create();
    engine.state().molecules(MoleculeTypeId(0)).setCompartment(a,17); engine.state().molecules(MoleculeTypeId(1)).setCompartment(b,17);
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(1),b)); engine.state().molecules(MoleculeTypeId(1)).setBondRef(b,0,MoleculeRef(MoleculeTypeId(0),a));
    MatchContext context; context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a)); FeatureDelta delta;
    EXPECT_THROW(engine.fire(lowered.rules[0].family,lowered.rules[0].member,context,delta),std::out_of_range);
    EXPECT_EQ(engine.state().molecules(MoleculeTypeId(0)).compartment(a),17u); EXPECT_EQ(engine.state().molecules(MoleculeTypeId(1)).compartment(b),17u);
}

TEST(NFsimAdapter_ConditionalDeletionKeepsSpeciesIntactWhenItWouldSplit){
    NativeModelSnapshot n; n.molecule_types.push_back(mol("A",1)); n.molecule_types.push_back(mol("B",2)); n.molecule_types.push_back(mol("C",1));
    NativeReactionSnapshot r=rxn(); r.reactant_types.push_back(1); NativeTransformSnapshot t=tr(NATIVE_REMOVE,0); t.removal_type=NATIVE_DELETE_MOLECULE_CONDITIONAL; r.transforms.push_back(t); n.rules.push_back(r);
    LegacyLoweringResult lowered=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(n)); EXPECT_EQ(lowered.supported_rule_count,1u);
    Engine engine(lowered.executable); MoleculeHandle a=engine.state().molecules(MoleculeTypeId(0)).create(); MoleculeHandle b=engine.state().molecules(MoleculeTypeId(1)).create(); MoleculeHandle c=engine.state().molecules(MoleculeTypeId(2)).create();
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(1),b));
    engine.state().molecules(MoleculeTypeId(1)).setBondRef(b,0,MoleculeRef(MoleculeTypeId(0),a)); engine.state().molecules(MoleculeTypeId(1)).setBondRef(b,1,MoleculeRef(MoleculeTypeId(2),c));
    engine.state().molecules(MoleculeTypeId(2)).setBondRef(c,0,MoleculeRef(MoleculeTypeId(1),b));
    MatchContext context; context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(1),b)); FeatureDelta delta;
    EXPECT_TRUE(engine.fire(lowered.rules[0].family,lowered.rules[0].member,context,delta));
    EXPECT_TRUE(engine.state().molecules(MoleculeTypeId(0)).alive(a)); EXPECT_TRUE(engine.state().molecules(MoleculeTypeId(1)).alive(b)); EXPECT_TRUE(engine.state().molecules(MoleculeTypeId(2)).alive(c));
}
