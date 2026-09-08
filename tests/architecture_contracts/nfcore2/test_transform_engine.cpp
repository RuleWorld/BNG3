#include "test_harness.hh"
#include "engine.hh"
#include <limits>
using namespace NFcore2;

namespace {
ExecutableModel makeExec(){
    ExecutableModel e;
    MoleculeTypeDescriptor a;a.name="A";a.state_words=2;a.bond_slots=2;
    MoleculeTypeDescriptor b;b.name="B";b.state_words=1;b.bond_slots=2;
    e.buildMetadata().addMoleculeType(a);e.buildMetadata().addMoleculeType(b);
    for(unsigned i=0;i<8;++i)e.buildMetadata().addFeature(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,i));
    return e;
}
TransformProgramId addProgram(ExecutableModel& e,const std::vector<TransformInstruction>& xs){ TransformProgram p;for(std::size_t i=0;i<xs.size();++i)p.add(xs[i]);p.add(TransformInstruction(TRANSFORM_END));return e.buildTransforms().add(p); }
MatcherId alwaysMatcher(ExecutableModel&e){MatcherProgram p;p.add(MatchInstruction(MATCH_END));return e.buildMatchers().add(p);}
RuleFamilyId addFamily(ExecutableModel&e,MatcherId m,TransformProgramId t,double rate=1.0){RuleFamilyDescriptor f;f.name="f";f.matcher=m;f.transform=t;RuleMember rm;rm.rate=rate;f.members.push_back(rm);return e.buildMetadata().addRuleFamily(f);}
}

TEST(Transform_SetStateWordMutatesTargetAndReportsFeature){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;MoleculeHandle h=s.molecules(MoleculeTypeId(0)).create();MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),h));TransformProgram p;TransformInstruction x(TRANSFORM_SET_STATE_WORD);x.target=0;x.a=1;x.value=44;x.feature=FeatureId(3);p.add(x);FeatureDelta d;p.execute(s,sc,c,d);EXPECT_EQ(s.molecules(MoleculeTypeId(0)).stateWord(h,1),44ull);EXPECT_EQ(d.changed.size(),1u);EXPECT_EQ(d.changed[0],FeatureId(3)); }
TEST(Transform_SetStateWordMissingTargetThrows){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;MatchContext c;TransformProgram p;TransformInstruction x(TRANSFORM_SET_STATE_WORD);x.target=1;p.add(x);FeatureDelta d;EXPECT_THROW(p.execute(s,sc,c,d),std::out_of_range); }
TEST(Transform_SetScaffoldStateMutatesOffset){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;ScaffoldId id=sc.create(20);MatchContext c;c.scaffold=id;c.coordinate=4;TransformProgram p;TransformInstruction x(TRANSFORM_SET_SCAFFOLD_STATE);x.a=3;x.value=9;x.feature=FeatureId(2);p.add(x);FeatureDelta d;p.execute(s,sc,c,d);EXPECT_EQ(sc.state(id,7),9u);EXPECT_EQ(d.changed[0],FeatureId(2)); }
TEST(Transform_SetScaffoldStateBoundsChecked){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;ScaffoldId id=sc.create(5);MatchContext c;c.scaffold=id;c.coordinate=4;TransformProgram p;TransformInstruction x(TRANSFORM_SET_SCAFFOLD_STATE);x.a=2;x.value=9;p.add(x);FeatureDelta d;EXPECT_THROW(p.execute(s,sc,c,d),std::out_of_range); }
TEST(Transform_MoveOccupantMovesExactlyOneHandle){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;ScaffoldId id=sc.create(10);MoleculeHandle h(9,2);sc.setOccupant(id,2,h);MatchContext c;c.scaffold=id;c.coordinate=2;TransformProgram p;TransformInstruction x(TRANSFORM_MOVE_OCCUPANT);x.a=0;x.b=1;x.feature=FeatureId(1);p.add(x);FeatureDelta d;p.execute(s,sc,c,d);EXPECT_FALSE(sc.occupant(id,2).valid());EXPECT_EQ(sc.occupant(id,3),h);EXPECT_EQ(c.coordinate,3u); }
TEST(Transform_MoveOccupantRejectsOccupiedDestination){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;ScaffoldId id=sc.create(10);sc.setOccupant(id,2,MoleculeHandle(1,1));sc.setOccupant(id,3,MoleculeHandle(2,1));MatchContext c;c.scaffold=id;c.coordinate=2;TransformProgram p;TransformInstruction x(TRANSFORM_MOVE_OCCUPANT);x.a=0;x.b=1;p.add(x);FeatureDelta d;EXPECT_THROW(p.execute(s,sc,c,d),std::logic_error);EXPECT_EQ(sc.occupant(id,2),MoleculeHandle(1,1));EXPECT_EQ(sc.occupant(id,3),MoleculeHandle(2,1)); }
TEST(Transform_MoveOccupantRejectsEmptySource){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;ScaffoldId id=sc.create(10);MatchContext c;c.scaffold=id;c.coordinate=2;TransformProgram p;TransformInstruction x(TRANSFORM_MOVE_OCCUPANT);x.a=0;x.b=1;p.add(x);FeatureDelta d;EXPECT_THROW(p.execute(s,sc,c,d),std::logic_error); }
TEST(Transform_PopulationAddSupportsPositiveDelta){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;PopulationId id=s.populations().add(5);MatchContext c;TransformProgram p;TransformInstruction x(TRANSFORM_POPULATION_ADD);x.a=id.value();x.value=3;x.feature=FeatureId(5);p.add(x);FeatureDelta d;p.execute(s,sc,c,d);EXPECT_EQ(s.populations().value(id),8ll); }
TEST(Transform_PopulationAddSupportsNegativeBitPattern){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;PopulationId id=s.populations().add(5);MatchContext c;TransformProgram p;TransformInstruction x(TRANSFORM_POPULATION_ADD);x.a=id.value();x.value=static_cast<std::uint64_t>(static_cast<std::int64_t>(-2));x.feature=FeatureId(5);p.add(x);FeatureDelta d;p.execute(s,sc,c,d);EXPECT_EQ(s.populations().value(id),3ll); }
TEST(Transform_BindCreatesSymmetricTypedBond){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;MoleculeHandle a=s.molecules(MoleculeTypeId(0)).create(),b=s.molecules(MoleculeTypeId(1)).create();MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));c.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),b));TransformProgram p;TransformInstruction x(TRANSFORM_BIND);x.target=0;x.other=1;x.a=1;x.b=0;x.feature=FeatureId(2);p.add(x);FeatureDelta d;p.execute(s,sc,c,d);EXPECT_EQ(s.molecules(MoleculeTypeId(0)).bondRef(a,1),MoleculeRef(MoleculeTypeId(1),b));EXPECT_EQ(s.molecules(MoleculeTypeId(1)).bondRef(b,0),MoleculeRef(MoleculeTypeId(0),a)); }
TEST(Transform_BindRejectsOccupiedLeftEndpointWithoutMutation){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;MoleculeHandle a=s.molecules(MoleculeTypeId(0)).create(),b=s.molecules(MoleculeTypeId(1)).create(),old=s.molecules(MoleculeTypeId(1)).create();s.molecules(MoleculeTypeId(0)).setBondRef(a,1,MoleculeRef(MoleculeTypeId(1),old));s.molecules(MoleculeTypeId(1)).setBondRef(old,0,MoleculeRef(MoleculeTypeId(0),a));MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));c.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),b));TransformProgram p;TransformInstruction x(TRANSFORM_BIND);x.target=0;x.other=1;x.a=1;x.b=0;p.add(x);FeatureDelta d;EXPECT_THROW(p.execute(s,sc,c,d),std::logic_error);EXPECT_EQ(s.molecules(MoleculeTypeId(0)).bondRef(a,1),MoleculeRef(MoleculeTypeId(1),old)); }
TEST(Transform_BindRejectsOccupiedRightEndpointWithoutMutation){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;MoleculeHandle a=s.molecules(MoleculeTypeId(0)).create(),b=s.molecules(MoleculeTypeId(1)).create(),old=s.molecules(MoleculeTypeId(0)).create();s.molecules(MoleculeTypeId(1)).setBondRef(b,0,MoleculeRef(MoleculeTypeId(0),old));s.molecules(MoleculeTypeId(0)).setBondRef(old,0,MoleculeRef(MoleculeTypeId(1),b));MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));c.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),b));TransformProgram p;TransformInstruction x(TRANSFORM_BIND);x.target=0;x.other=1;x.a=1;x.b=0;p.add(x);FeatureDelta d;EXPECT_THROW(p.execute(s,sc,c,d),std::logic_error);EXPECT_FALSE(s.molecules(MoleculeTypeId(0)).bondRef(a,1).valid()); }
TEST(Transform_UnbindClearsBothEndpoints){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;MoleculeHandle a=s.molecules(MoleculeTypeId(0)).create(),b=s.molecules(MoleculeTypeId(1)).create();s.molecules(MoleculeTypeId(0)).setBondRef(a,1,MoleculeRef(MoleculeTypeId(1),b));s.molecules(MoleculeTypeId(1)).setBondRef(b,0,MoleculeRef(MoleculeTypeId(0),a));MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));TransformProgram p;TransformInstruction x(TRANSFORM_UNBIND);x.target=0;x.a=1;x.b=0;p.add(x);FeatureDelta d;p.execute(s,sc,c,d);EXPECT_FALSE(s.molecules(MoleculeTypeId(0)).bondRef(a,1).valid());EXPECT_FALSE(s.molecules(MoleculeTypeId(1)).bondRef(b,0).valid()); }
TEST(Transform_UnbindFreeSiteIsIdempotent){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;MoleculeHandle a=s.molecules(MoleculeTypeId(0)).create();MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));TransformProgram p;TransformInstruction x(TRANSFORM_UNBIND);x.target=0;x.a=1;x.b=0;p.add(x);FeatureDelta d;EXPECT_NO_THROW(p.execute(s,sc,c,d));EXPECT_FALSE(s.molecules(MoleculeTypeId(0)).bondRef(a,1).valid()); }
TEST(Transform_CreateMoleculeWritesContextTarget){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;MatchContext c;TransformProgram p;TransformInstruction x(TRANSFORM_CREATE_MOLECULE);x.target=2;x.a=1;p.add(x);FeatureDelta d;p.execute(s,sc,c,d);EXPECT_TRUE(c.moleculeAt(2).valid());EXPECT_EQ(c.moleculeAt(2).type,MoleculeTypeId(1));EXPECT_EQ(s.molecules(MoleculeTypeId(1)).liveCount(),1u); }
TEST(Transform_DeleteMoleculeInvalidatesHandle){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;MoleculeHandle a=s.molecules(MoleculeTypeId(0)).create();MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));TransformProgram p;TransformInstruction x(TRANSFORM_DELETE_MOLECULE);x.target=0;p.add(x);FeatureDelta d;p.execute(s,sc,c,d);EXPECT_FALSE(s.molecules(MoleculeTypeId(0)).alive(a)); }
TEST(Transform_DeleteMoleculeClearsReciprocalBonds){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;MoleculeHandle a=s.molecules(MoleculeTypeId(0)).create(),b=s.molecules(MoleculeTypeId(1)).create();s.molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(1),b));s.molecules(MoleculeTypeId(1)).setBondRef(b,1,MoleculeRef(MoleculeTypeId(0),a));MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));TransformProgram p;TransformInstruction x(TRANSFORM_DELETE_MOLECULE);x.target=0;p.add(x);FeatureDelta d;p.execute(s,sc,c,d);EXPECT_FALSE(s.molecules(MoleculeTypeId(1)).bondRef(b,1).valid()); }
TEST(Transform_DeleteCompleteSpeciesErasesEveryConnectedMolecule){
    ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;
    MoleculeHandle a=s.molecules(MoleculeTypeId(0)).create(),b=s.molecules(MoleculeTypeId(1)).create();
    s.molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(1),b));
    s.molecules(MoleculeTypeId(1)).setBondRef(b,1,MoleculeRef(MoleculeTypeId(0),a));
    MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));TransformProgram p;
    p.add(TransformInstruction(TRANSFORM_DELETE_SPECIES));FeatureDelta d;p.execute(s,sc,c,d);
    EXPECT_FALSE(s.molecules(MoleculeTypeId(0)).alive(a));EXPECT_FALSE(s.molecules(MoleculeTypeId(1)).alive(b));
}
TEST(Transform_ConditionalDeleteReportsEveryAffectedSpeciesMember){
    ExecutableModel e=makeExec();
    MoleculeTypeDescriptor c;c.name="C";c.state_words=1;c.bond_slots=3;e.buildMetadata().addMoleculeType(c);
    MoleculeTypeDescriptor d;d.name="D";d.state_words=1;d.bond_slots=1;e.buildMetadata().addMoleculeType(d);
    for(unsigned owner=0; owner<4; ++owner) e.buildMetadata().addFeature(FeatureDescriptor(FEATURE_MOLECULE_EXISTENCE,owner,0));
    Engine engine(e); auto a=engine.state().molecules(MoleculeTypeId(0)).create(); auto b=engine.state().molecules(MoleculeTypeId(1)).create(); auto c0=engine.state().molecules(MoleculeTypeId(2)).create(); auto d0=engine.state().molecules(MoleculeTypeId(3)).create();
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(1),b));
    engine.state().molecules(MoleculeTypeId(1)).setBondRef(b,0,MoleculeRef(MoleculeTypeId(0),a)); engine.state().molecules(MoleculeTypeId(1)).setBondRef(b,1,MoleculeRef(MoleculeTypeId(2),c0));
    engine.state().molecules(MoleculeTypeId(2)).setBondRef(c0,0,MoleculeRef(MoleculeTypeId(1),b)); engine.state().molecules(MoleculeTypeId(2)).setBondRef(c0,1,MoleculeRef(MoleculeTypeId(3),d0));
    engine.state().molecules(MoleculeTypeId(3)).setBondRef(d0,0,MoleculeRef(MoleculeTypeId(2),c0));
    // A-B-C-D chain: deleting B would split A from C-D, so conditional delete is a no-op.
    MatchContext context; context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(1),b)); TransformProgram p; TransformInstruction x(TRANSFORM_DELETE_MOLECULE_CONDITIONAL); x.target=0; p.add(x); FeatureDelta delta; p.execute(engine.state(),engine.scaffolds(),context,delta);
    EXPECT_TRUE(engine.state().molecules(MoleculeTypeId(1)).alive(b));
    EXPECT_TRUE(delta.changed.empty());
}
TEST(Transform_ConditionalDeleteReportsIndirectMemberWhenCycleKeepsSpeciesConnected){
    ExecutableModel e=makeExec();
    MoleculeTypeDescriptor c;c.name="C";c.state_words=1;c.bond_slots=3;e.buildMetadata().addMoleculeType(c);
    MoleculeTypeDescriptor d;d.name="D";d.state_words=1;d.bond_slots=1;e.buildMetadata().addMoleculeType(d);
    for(unsigned owner=0; owner<4; ++owner) e.buildMetadata().addFeature(FeatureDescriptor(FEATURE_MOLECULE_EXISTENCE,owner,0));
    Engine engine(e); auto a=engine.state().molecules(MoleculeTypeId(0)).create(); auto b=engine.state().molecules(MoleculeTypeId(1)).create(); auto c0=engine.state().molecules(MoleculeTypeId(2)).create(); auto d0=engine.state().molecules(MoleculeTypeId(3)).create();
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(1),b)); engine.state().molecules(MoleculeTypeId(0)).setBondRef(a,1,MoleculeRef(MoleculeTypeId(2),c0));
    engine.state().molecules(MoleculeTypeId(1)).setBondRef(b,0,MoleculeRef(MoleculeTypeId(0),a)); engine.state().molecules(MoleculeTypeId(1)).setBondRef(b,1,MoleculeRef(MoleculeTypeId(2),c0));
    engine.state().molecules(MoleculeTypeId(2)).setBondRef(c0,0,MoleculeRef(MoleculeTypeId(0),a)); engine.state().molecules(MoleculeTypeId(2)).setBondRef(c0,1,MoleculeRef(MoleculeTypeId(1),b)); engine.state().molecules(MoleculeTypeId(2)).setBondRef(c0,2,MoleculeRef(MoleculeTypeId(3),d0));
    engine.state().molecules(MoleculeTypeId(1)).setBondRef(b,1,MoleculeRef(MoleculeTypeId(2),c0));
    engine.state().molecules(MoleculeTypeId(3)).setBondRef(d0,0,MoleculeRef(MoleculeTypeId(2),c0));
    MatchContext context; context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a)); TransformProgram p; TransformInstruction x(TRANSFORM_DELETE_MOLECULE_CONDITIONAL); x.target=0; p.add(x); FeatureDelta delta; p.execute(engine.state(),engine.scaffolds(),context,delta);
    EXPECT_FALSE(engine.state().molecules(MoleculeTypeId(0)).alive(a));
    EXPECT_TRUE(engine.state().molecules(MoleculeTypeId(3)).alive(d0));
    EXPECT_TRUE(std::find(delta.changed.begin(),delta.changed.end(),FeatureId(11)) != delta.changed.end());
}
TEST(Transform_ConditionalDeleteRejectsAsymmetricRuntimeGraph){
    ExecutableModel e=makeExec();
    MoleculeTypeDescriptor c;c.name="C";c.state_words=1;c.bond_slots=1;e.buildMetadata().addMoleculeType(c);
    Engine engine(e); auto a=engine.state().molecules(MoleculeTypeId(0)).create(); auto b=engine.state().molecules(MoleculeTypeId(1)).create(); auto c0=engine.state().molecules(MoleculeTypeId(2)).create();
    engine.state().molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(1),b)); engine.state().molecules(MoleculeTypeId(0)).setBondRef(a,1,MoleculeRef(MoleculeTypeId(2),c0));
    // The B->C edge is one-way. A conditional deletion must fail closed even
    // though the directed traversal would otherwise see one remaining piece.
    engine.state().molecules(MoleculeTypeId(1)).setBondRef(b,0,MoleculeRef(MoleculeTypeId(2),c0));
    MatchContext context; context.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a)); TransformProgram p; TransformInstruction x(TRANSFORM_DELETE_MOLECULE_CONDITIONAL); x.target=0; p.add(x); FeatureDelta delta; p.execute(engine.state(),engine.scaffolds(),context,delta);
    EXPECT_TRUE(engine.state().molecules(MoleculeTypeId(0)).alive(a)); EXPECT_TRUE(delta.changed.empty());
}
TEST(Transform_MoveMoleculeUpdatesCompartmentAndFeatureDelta){
    ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;
    MoleculeHandle a=s.molecules(MoleculeTypeId(0)).create();s.molecules(MoleculeTypeId(0)).setCompartment(a,2);
    MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));TransformProgram p;TransformInstruction x(TRANSFORM_MOVE_MOLECULE);x.target=0;x.a=3;x.feature=FeatureId(0);p.add(x);FeatureDelta d;p.execute(s,sc,c,d);
    EXPECT_EQ(s.molecules(MoleculeTypeId(0)).compartment(a),3u);EXPECT_EQ(d.changed.size(),1u);EXPECT_EQ(d.changed[0],FeatureId(0));
}
TEST(Transform_EndStopsLaterInstructions){ ExecutableModel e=makeExec();SimulationState s(e.metadata());ScaffoldStore sc;MoleculeHandle a=s.molecules(MoleculeTypeId(0)).create();MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));TransformProgram p;p.add(TransformInstruction(TRANSFORM_END));TransformInstruction x(TRANSFORM_SET_STATE_WORD);x.value=99;p.add(x);FeatureDelta d;p.execute(s,sc,c,d);EXPECT_EQ(s.molecules(MoleculeTypeId(0)).stateWord(a,0),0ull); }

TEST(Engine_AffectedMatchersDeduplicatesAcrossDuplicateDeltas){ ExecutableModel e=makeExec();MatcherId m0=e.buildMatchers().add(MatcherProgram()),m1=e.buildMatchers().add(MatcherProgram());std::vector<std::vector<MatcherId> > deps(e.metadata().features().size());deps[1].push_back(m0);deps[1].push_back(m1);deps[2].push_back(m0);e.buildMetadata().setFeatureDependencies(deps);Engine eng(e);FeatureDelta d;d.add(FeatureId(1));d.add(FeatureId(2));d.add(FeatureId(1));std::vector<MatcherId> out=eng.affectedMatchers(d);EXPECT_EQ(out.size(),2u);EXPECT_EQ(out[0],m0);EXPECT_EQ(out[1],m1); }
TEST(Engine_AffectedFamiliesDeduplicatesSharedMatcherFamilies){ ExecutableModel e=makeExec();MatcherId m=alwaysMatcher(e);TransformProgramId t=addProgram(e,std::vector<TransformInstruction>());RuleFamilyId f0=addFamily(e,m,t),f1=addFamily(e,m,t);std::vector<std::vector<MatcherId> > deps(e.metadata().features().size());deps[0].push_back(m);e.buildMetadata().setFeatureDependencies(deps);Engine eng(e);FeatureDelta d;d.add(FeatureId(0));std::vector<RuleFamilyId> out=eng.affectedFamilies(d);EXPECT_EQ(out.size(),2u);EXPECT_EQ(out[0],f0);EXPECT_EQ(out[1],f1); }
TEST(Engine_FireRejectsMatcherFailureAndDoesNotTransform){ ExecutableModel e=makeExec();MatcherProgram mp;MatchInstruction mx(MATCH_STATE_MASK);mx.mask=1;mx.value=1;mp.add(mx);MatcherId m=e.buildMatchers().add(mp);TransformInstruction tx(TRANSFORM_SET_STATE_WORD);tx.value=7;TransformProgramId t=addProgram(e,std::vector<TransformInstruction>(1,tx));RuleFamilyId f=addFamily(e,m,t);Engine eng(e);MoleculeHandle h=eng.state().molecules(MoleculeTypeId(0)).create();MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),h));FeatureDelta d;EXPECT_FALSE(eng.fire(f,0,c,d));EXPECT_EQ(eng.state().molecules(MoleculeTypeId(0)).stateWord(h,0),0ull);EXPECT_EQ(eng.counters().rejected_fires,1ull);EXPECT_EQ(eng.counters().events,0ull); }
TEST(Engine_FireExecutesMatchingRuleAndCountsDelta){ ExecutableModel e=makeExec();MatcherId m=alwaysMatcher(e);TransformInstruction tx(TRANSFORM_SET_STATE_WORD);tx.value=7;tx.feature=FeatureId(2);TransformProgramId t=addProgram(e,std::vector<TransformInstruction>(1,tx));RuleFamilyId f=addFamily(e,m,t);Engine eng(e);MoleculeHandle h=eng.state().molecules(MoleculeTypeId(0)).create();MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),h));FeatureDelta d;EXPECT_TRUE(eng.fire(f,0,c,d));EXPECT_EQ(eng.state().molecules(MoleculeTypeId(0)).stateWord(h,0),7ull);EXPECT_EQ(eng.counters().events,1ull);EXPECT_EQ(eng.counters().feature_deltas,1ull); }
TEST(Engine_FireInvalidMemberReturnsFalseWithoutMatcherEvaluation){ ExecutableModel e=makeExec();MatcherId m=alwaysMatcher(e);TransformProgramId t=addProgram(e,std::vector<TransformInstruction>());RuleFamilyId f=addFamily(e,m,t);Engine eng(e);MatchContext c;FeatureDelta d;EXPECT_FALSE(eng.fire(f,5,c,d));EXPECT_EQ(eng.counters().matcher_evaluations,0ull); }
TEST(Engine_CopyCreatesIndependentState){ ExecutableModel e=makeExec();Engine a(e);MoleculeHandle h=a.state().molecules(MoleculeTypeId(0)).create();a.state().molecules(MoleculeTypeId(0)).setStateWord(h,0,1);Engine b(a);b.state().molecules(MoleculeTypeId(0)).setStateWord(h,0,9);EXPECT_EQ(a.state().molecules(MoleculeTypeId(0)).stateWord(h,0),1ull);EXPECT_EQ(b.state().molecules(MoleculeTypeId(0)).stateWord(h,0),9ull); }
TEST(Engine_CopyCreatesIndependentScaffolds){ ExecutableModel e=makeExec();Engine a(e);ScaffoldId id=a.scaffolds().create(10);a.scaffolds().setState(id,1,2);Engine b(a);b.scaffolds().setState(id,1,8);EXPECT_EQ(a.scaffolds().state(id,1),2u);EXPECT_EQ(b.scaffolds().state(id,1),8u); }

TEST(Transform_AddStateWordPositiveDelta){
    ExecutableModel x; MoleculeTypeDescriptor d; d.name="Counter"; d.state_words=1; d.bond_slots=0; x.buildMetadata().addMoleculeType(d);
    Engine e(x); MoleculeHandle h=e.state().molecules(MoleculeTypeId(0)).create(); e.state().molecules(MoleculeTypeId(0)).setStateWord(h,0,10);
    TransformProgram p; TransformInstruction a(TRANSFORM_ADD_STATE_WORD); a.target=0; a.a=0; a.value=5; p.add(a); p.add(TransformInstruction(TRANSFORM_END));
    MatchContext c; c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),h)); FeatureDelta delta; p.execute(e.state(),e.scaffolds(),c,delta);
    EXPECT_EQ(e.state().molecules(MoleculeTypeId(0)).stateWord(h,0),15u);
}

TEST(Transform_AddStateWordNegativeDelta){
    ExecutableModel x; MoleculeTypeDescriptor d; d.name="Counter"; d.state_words=1; x.buildMetadata().addMoleculeType(d);
    Engine e(x); MoleculeHandle h=e.state().molecules(MoleculeTypeId(0)).create(); e.state().molecules(MoleculeTypeId(0)).setStateWord(h,0,10);
    TransformProgram p; TransformInstruction a(TRANSFORM_ADD_STATE_WORD); a.target=0; a.a=0; a.value=static_cast<std::uint64_t>(static_cast<std::int64_t>(-3)); p.add(a); p.add(TransformInstruction(TRANSFORM_END));
    MatchContext c; c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),h)); FeatureDelta delta; p.execute(e.state(),e.scaffolds(),c,delta);
    EXPECT_EQ(e.state().molecules(MoleculeTypeId(0)).stateWord(h,0),7u);
}

TEST(Transform_AddStateWordRejectsUnderflow){
    ExecutableModel x; MoleculeTypeDescriptor d; d.name="Counter"; d.state_words=1; x.buildMetadata().addMoleculeType(d);
    Engine e(x); MoleculeHandle h=e.state().molecules(MoleculeTypeId(0)).create(); e.state().molecules(MoleculeTypeId(0)).setStateWord(h,0,1);
    TransformProgram p; TransformInstruction a(TRANSFORM_ADD_STATE_WORD); a.target=0; a.a=0; a.value=static_cast<std::uint64_t>(static_cast<std::int64_t>(-2)); p.add(a);
    MatchContext c; c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),h)); FeatureDelta delta;
    EXPECT_THROW(p.execute(e.state(),e.scaffolds(),c,delta),std::overflow_error);
    EXPECT_EQ(e.state().molecules(MoleculeTypeId(0)).stateWord(h,0),1u);
}

TEST(Transform_AddStateWordRejectsOverflow){
    ExecutableModel x; MoleculeTypeDescriptor d; d.name="Counter"; d.state_words=1; x.buildMetadata().addMoleculeType(d);
    Engine e(x); MoleculeHandle h=e.state().molecules(MoleculeTypeId(0)).create(); e.state().molecules(MoleculeTypeId(0)).setStateWord(h,0,std::numeric_limits<std::uint64_t>::max());
    TransformProgram p; TransformInstruction a(TRANSFORM_ADD_STATE_WORD); a.target=0; a.a=0; a.value=1; p.add(a);
    MatchContext c; c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),h)); FeatureDelta delta;
    EXPECT_THROW(p.execute(e.state(),e.scaffolds(),c,delta),std::overflow_error);
}

TEST(Transform_UnbindCanDiscoverReciprocalPartnerSlot){
    ExecutableModel x=makeExec(); Engine e(x);
    MoleculeHandle a=e.state().molecules(MoleculeTypeId(0)).create(); MoleculeHandle b=e.state().molecules(MoleculeTypeId(1)).create();
    e.state().molecules(MoleculeTypeId(0)).setBondRef(a,1,MoleculeRef(MoleculeTypeId(1),b));
    e.state().molecules(MoleculeTypeId(1)).setBondRef(b,0,MoleculeRef(MoleculeTypeId(0),a));
    TransformProgram p; TransformInstruction u(TRANSFORM_UNBIND);u.target=0;u.a=1;u.b=TRANSFORM_INFER_PARTNER_SLOT;p.add(u);
    MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));FeatureDelta d;p.execute(e.state(),e.scaffolds(),c,d);
    EXPECT_FALSE(e.state().molecules(MoleculeTypeId(0)).bondRef(a,1).valid());EXPECT_FALSE(e.state().molecules(MoleculeTypeId(1)).bondRef(b,0).valid());
}

TEST(Transform_UnbindDiscoveryFindsNonzeroPartnerSlot){
    ExecutableModel x=makeExec(); Engine e(x);
    MoleculeHandle a=e.state().molecules(MoleculeTypeId(0)).create(); MoleculeHandle b=e.state().molecules(MoleculeTypeId(1)).create();
    e.state().molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(1),b));
    e.state().molecules(MoleculeTypeId(1)).setBondRef(b,1,MoleculeRef(MoleculeTypeId(0),a));
    TransformProgram p; TransformInstruction u(TRANSFORM_UNBIND);u.target=0;u.a=0;u.b=TRANSFORM_INFER_PARTNER_SLOT;p.add(u);
    MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));FeatureDelta d;p.execute(e.state(),e.scaffolds(),c,d);
    EXPECT_FALSE(e.state().molecules(MoleculeTypeId(1)).bondRef(b,1).valid());
}

TEST(Transform_UnbindDiscoveryRejectsAsymmetricGraphInsteadOfLeavingStaleEdge){
    ExecutableModel x=makeExec(); Engine e(x);
    MoleculeHandle a=e.state().molecules(MoleculeTypeId(0)).create(); MoleculeHandle b=e.state().molecules(MoleculeTypeId(1)).create();
    e.state().molecules(MoleculeTypeId(0)).setBondRef(a,0,MoleculeRef(MoleculeTypeId(1),b));
    TransformProgram p; TransformInstruction u(TRANSFORM_UNBIND);u.target=0;u.a=0;u.b=TRANSFORM_INFER_PARTNER_SLOT;p.add(u);
    MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));FeatureDelta d;
    EXPECT_THROW(p.execute(e.state(),e.scaffolds(),c,d),std::logic_error);
    EXPECT_TRUE(e.state().molecules(MoleculeTypeId(0)).bondRef(a,0).valid());
}
