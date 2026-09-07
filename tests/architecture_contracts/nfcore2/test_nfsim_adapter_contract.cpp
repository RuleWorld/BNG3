#include "test_harness.hh"
#include "nfsim_adapter_contract.hh"
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
    EXPECT_EQ(m.features.size(),6u);
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
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();NativeTransformSnapshot t=tr(NATIVE_REMOVE,0);t.removal_type=NATIVE_DELETE_MOLECULE_ONLY;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];EXPECT_EQ(x.transforms[0].kind,LEGACY_TRANSFORM_DELETE_MOLECULE);EXPECT_TRUE(x.topology_change_is_local);
}

TEST(NFsimAdapter_DeleteWholeSpeciesFallsBack){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();NativeTransformSnapshot t=tr(NATIVE_REMOVE,0);t.removal_type=NATIVE_DELETE_COMPLETE_SPECIES;r.transforms.push_back(t);n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];EXPECT_TRUE(x.changes_topology);EXPECT_FALSE(x.topology_change_is_local);EXPECT_EQ(x.transforms[0].kind,LEGACY_TRANSFORM_UNSUPPORTED);
}

TEST(NFsimAdapter_IncrementAndDecrementStateLowerToCheckedAdd){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot a=rxn();a.transforms.push_back(tr(NATIVE_INCREMENT_STATE,0,0));NativeReactionSnapshot b=rxn();b.transforms.push_back(tr(NATIVE_DECREMENT_STATE,0,0));n.rules.push_back(a);n.rules.push_back(b);
    LegacyModelIR m=NFsimSnapshotAdapter::toLegacy(n);EXPECT_EQ(m.rules[0].transforms[0].kind,LEGACY_TRANSFORM_ADD_STATE_WORD);EXPECT_EQ(m.rules[0].transforms[0].value,1);EXPECT_EQ(m.rules[1].transforms[0].kind,LEGACY_TRANSFORM_ADD_STATE_WORD);EXPECT_EQ(m.rules[1].transforms[0].value,-1);
}

TEST(NFsimAdapter_LocalFunctionReferenceMarksRuleFallback){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.transforms.push_back(tr(NATIVE_LOCAL_FUNCTION_REFERENCE,0));n.rules.push_back(r);
    EXPECT_TRUE(NFsimSnapshotAdapter::toLegacy(n).rules[0].uses_local_function);
}

TEST(NFsimAdapter_MoveCompartmentRemainsUnsupported){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.transforms.push_back(tr(NATIVE_MOVE,0));n.rules.push_back(r);
    EXPECT_EQ(NFsimSnapshotAdapter::toLegacy(n).rules[0].transforms[0].kind,LEGACY_TRANSFORM_UNSUPPORTED);
}

TEST(NFsimAdapter_PreservesRateParameterCoordinateAndName){
    NativeModelSnapshot n;n.molecule_types.push_back(mol("R",1));NativeReactionSnapshot r=rxn();r.name="elong_42";r.base_rate=3.5;r.parameter_index=9;r.coordinate=42;n.rules.push_back(r);
    LegacyRuleIR x=NFsimSnapshotAdapter::toLegacy(n).rules[0];EXPECT_EQ(x.name,std::string("elong_42"));EXPECT_EQ(x.rate,3.5);EXPECT_EQ(x.parameter_index,9u);EXPECT_EQ(x.coordinate,42u);
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
