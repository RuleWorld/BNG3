#include "test_harness.hh"
#include "compiled_model.hh"
#include "simulation_state.hh"
#include <limits>
using namespace NFcore2;

namespace {
CompiledModel oneTypeModel(std::uint16_t words=2,std::uint16_t bonds=2){
    CompiledModel m; MoleculeTypeDescriptor d; d.name="A"; d.state_words=words; d.bond_slots=bonds; m.addMoleculeType(d); return m;
}
}

TEST(Id_DefaultIsInvalid){ MoleculeId x; EXPECT_FALSE(x.valid()); EXPECT_EQ(x.value(),MoleculeId::invalid_value()); }
TEST(Id_ExplicitZeroIsValid){ MoleculeId x(0); EXPECT_TRUE(x.valid()); EXPECT_EQ(x.value(),0u); }
TEST(Id_EqualityAndOrdering){ MoleculeId a(1),b(1),c(2); EXPECT_TRUE(a==b); EXPECT_TRUE(a!=c); EXPECT_TRUE(a<c); }
TEST(Id_TypesRemainDistinctAtCompileTimeUsage){ MoleculeTypeId t(3); FeatureId f(3); EXPECT_EQ(t.value(),f.value()); EXPECT_TRUE(t.valid()); EXPECT_TRUE(f.valid()); }
TEST(MoleculeHandle_DefaultInvalid){ MoleculeHandle h; EXPECT_FALSE(h.valid()); }
TEST(MoleculeHandle_GenerationParticipatesInEquality){ MoleculeHandle a(1,2),b(1,3),c(1,2); EXPECT_NE(a,b); EXPECT_EQ(a,c); }
TEST(MoleculeRef_DefaultInvalid){ MoleculeRef r; EXPECT_FALSE(r.valid()); }
TEST(MoleculeRef_RequiresBothTypeAndHandle){ MoleculeRef a(MoleculeTypeId(0),MoleculeHandle()); EXPECT_FALSE(a.valid()); MoleculeRef b(MoleculeTypeId(),MoleculeHandle(0,1)); EXPECT_FALSE(b.valid()); }
TEST(MoleculeRef_ValidWhenBothPartsValid){ MoleculeRef r(MoleculeTypeId(2),MoleculeHandle(7,4)); EXPECT_TRUE(r.valid()); }

TEST(MoleculeStore_CreateStartsAlive){ CompiledModel m=oneTypeModel(); SimulationState s(m); MoleculeHandle h=s.molecules(MoleculeTypeId(0)).create(); EXPECT_TRUE(s.molecules(MoleculeTypeId(0)).alive(h)); EXPECT_EQ(s.molecules(MoleculeTypeId(0)).liveCount(),1u); }
TEST(MoleculeStore_CreateInitializesAllStateWordsToZero){ CompiledModel m=oneTypeModel(4,0); SimulationState s(m); MoleculeHandle h=s.molecules(MoleculeTypeId(0)).create(); for(unsigned i=0;i<4;++i) EXPECT_EQ(s.molecules(MoleculeTypeId(0)).stateWord(h,i),0ull); }
TEST(MoleculeStore_SetAndReadStateWords){ CompiledModel m=oneTypeModel(3,0); SimulationState s(m); MoleculeHandle h=s.molecules(MoleculeTypeId(0)).create(); s.molecules(MoleculeTypeId(0)).setStateWord(h,0,7); s.molecules(MoleculeTypeId(0)).setStateWord(h,2,0xf0f0ull); EXPECT_EQ(s.molecules(MoleculeTypeId(0)).stateWord(h,0),7ull); EXPECT_EQ(s.molecules(MoleculeTypeId(0)).stateWord(h,2),0xf0f0ull); }
TEST(MoleculeStore_StateWordBoundsChecked){ CompiledModel m=oneTypeModel(1,0); SimulationState s(m); MoleculeHandle h=s.molecules(MoleculeTypeId(0)).create(); EXPECT_THROW(s.molecules(MoleculeTypeId(0)).stateWord(h,1),std::out_of_range); EXPECT_THROW(s.molecules(MoleculeTypeId(0)).setStateWord(h,1,1),std::out_of_range); }
TEST(MoleculeStore_EraseInvalidatesHandle){ CompiledModel m=oneTypeModel(); SimulationState s(m); MoleculeStore& st=s.molecules(MoleculeTypeId(0)); MoleculeHandle h=st.create(); EXPECT_TRUE(st.erase(h)); EXPECT_FALSE(st.alive(h)); EXPECT_EQ(st.liveCount(),0u); }
TEST(MoleculeStore_DoubleEraseReturnsFalse){ CompiledModel m=oneTypeModel(); SimulationState s(m); MoleculeStore& st=s.molecules(MoleculeTypeId(0)); MoleculeHandle h=st.create(); EXPECT_TRUE(st.erase(h)); EXPECT_FALSE(st.erase(h)); }
TEST(MoleculeStore_StaleHandleCannotReadState){ CompiledModel m=oneTypeModel(); SimulationState s(m); MoleculeStore& st=s.molecules(MoleculeTypeId(0)); MoleculeHandle h=st.create(); st.erase(h); EXPECT_THROW(st.stateWord(h,0),std::out_of_range); }
TEST(MoleculeStore_StaleHandleCannotWriteState){ CompiledModel m=oneTypeModel(); SimulationState s(m); MoleculeStore& st=s.molecules(MoleculeTypeId(0)); MoleculeHandle h=st.create(); st.erase(h); EXPECT_THROW(st.setStateWord(h,0,3),std::out_of_range); }
TEST(MoleculeStore_ReusesSlotWithNewGeneration){ CompiledModel m=oneTypeModel(); SimulationState s(m); MoleculeStore& st=s.molecules(MoleculeTypeId(0)); MoleculeHandle a=st.create(); st.erase(a); MoleculeHandle b=st.create(); EXPECT_EQ(a.slot,b.slot); EXPECT_NE(a.generation,b.generation); EXPECT_FALSE(st.alive(a)); EXPECT_TRUE(st.alive(b)); }
TEST(MoleculeStore_ReusedSlotStateIsCleared){ CompiledModel m=oneTypeModel(2,0); SimulationState s(m); MoleculeStore& st=s.molecules(MoleculeTypeId(0)); MoleculeHandle a=st.create(); st.setStateWord(a,0,99); st.setStateWord(a,1,88); st.erase(a); MoleculeHandle b=st.create(); EXPECT_EQ(st.stateWord(b,0),0ull); EXPECT_EQ(st.stateWord(b,1),0ull); }
TEST(MoleculeStore_ReusedSlotBondsAreCleared){ CompiledModel m=oneTypeModel(1,2); SimulationState s(m); MoleculeStore& st=s.molecules(MoleculeTypeId(0)); MoleculeHandle a=st.create(), q=st.create(); st.setBondRef(a,0,MoleculeRef(MoleculeTypeId(0),q)); st.erase(a); MoleculeHandle b=st.create(); EXPECT_FALSE(st.bondRef(b,0).valid()); EXPECT_FALSE(st.bondRef(b,1).valid()); }
TEST(MoleculeStore_ManyCreateEraseMaintainsLiveCount){ CompiledModel m=oneTypeModel(); SimulationState s(m); MoleculeStore& st=s.molecules(MoleculeTypeId(0)); std::vector<MoleculeHandle> hs; for(int i=0;i<1000;++i)hs.push_back(st.create()); EXPECT_EQ(st.liveCount(),1000u); for(int i=0;i<1000;i+=2)EXPECT_TRUE(st.erase(hs[i])); EXPECT_EQ(st.liveCount(),500u); for(int i=0;i<250;++i)st.create(); EXPECT_EQ(st.liveCount(),750u); }
TEST(MoleculeStore_GenerationPreventsABAUseAfterFree){ CompiledModel m=oneTypeModel(); SimulationState s(m); MoleculeStore& st=s.molecules(MoleculeTypeId(0)); MoleculeHandle old=st.create(); st.erase(old); for(int i=0;i<100;++i){ MoleculeHandle h=st.create(); EXPECT_FALSE(st.alive(old)); st.erase(h); } }
TEST(MoleculeStore_BondBoundsChecked){ CompiledModel m=oneTypeModel(1,1); SimulationState s(m); MoleculeStore& st=s.molecules(MoleculeTypeId(0)); MoleculeHandle h=st.create(); EXPECT_THROW(st.bondRef(h,1),std::out_of_range); EXPECT_THROW(st.setBondRef(h,1,MoleculeRef()),std::out_of_range); }
TEST(MoleculeStore_TypedBondRoundTrip){ CompiledModel m; MoleculeTypeDescriptor a;a.name="A";a.bond_slots=1;MoleculeTypeDescriptor b;b.name="B";b.bond_slots=1;MoleculeTypeId ta=m.addMoleculeType(a),tb=m.addMoleculeType(b); SimulationState s(m); MoleculeHandle ha=s.molecules(ta).create(),hb=s.molecules(tb).create(); s.molecules(ta).setBondRef(ha,0,MoleculeRef(tb,hb)); EXPECT_EQ(s.molecules(ta).bondRef(ha,0),MoleculeRef(tb,hb)); }
TEST(MoleculeStore_BondRefToStaleHandleRetainsIdentityButTargetNotAlive){ CompiledModel m; MoleculeTypeDescriptor a;a.name="A";a.bond_slots=1;MoleculeTypeDescriptor b;b.name="B";b.bond_slots=1;MoleculeTypeId ta=m.addMoleculeType(a),tb=m.addMoleculeType(b); SimulationState s(m); MoleculeHandle ha=s.molecules(ta).create(),hb=s.molecules(tb).create(); s.molecules(ta).setBondRef(ha,0,MoleculeRef(tb,hb)); s.molecules(tb).erase(hb); MoleculeRef r=s.molecules(ta).bondRef(ha,0); EXPECT_TRUE(r.valid()); EXPECT_FALSE(s.molecules(r.type).alive(r.handle)); }

TEST(PopulationStore_AddAndRead){ PopulationStore p; PopulationId a=p.add(4),b=p.add(0); EXPECT_EQ(a.value(),0u); EXPECT_EQ(b.value(),1u); EXPECT_EQ(p.value(a),4ll); p.addTo(a,6); EXPECT_EQ(p.value(a),10ll); }
TEST(PopulationStore_SubtractWithinRange){ PopulationStore p; PopulationId a=p.add(10); p.addTo(a,-10); EXPECT_EQ(p.value(a),0ll); }
TEST(PopulationStore_PreventsNegativeCounts){ PopulationStore p; PopulationId a=p.add(3); EXPECT_THROW(p.addTo(a,-4),std::underflow_error); EXPECT_EQ(p.value(a),3ll); }
TEST(PopulationStore_IndexBoundsChecked){ PopulationStore p; p.add(1); EXPECT_THROW(p.value(PopulationId(5)),std::out_of_range); EXPECT_THROW(p.addTo(PopulationId(5),1),std::out_of_range); }
TEST(PopulationStore_Int64MinSubtractionDoesNotOverflowSilently){ PopulationStore p; PopulationId a=p.add(1); EXPECT_THROW(p.addTo(a,std::numeric_limits<std::int64_t>::min()),std::underflow_error); EXPECT_EQ(p.value(a),1ll); }
TEST(PopulationStore_PositiveOverflowRejected){ PopulationStore p; PopulationId a=p.add(std::numeric_limits<std::int64_t>::max()); EXPECT_THROW(p.addTo(a,1),std::overflow_error); EXPECT_EQ(p.value(a),std::numeric_limits<std::int64_t>::max()); }
TEST(PopulationStore_NegativeInitialCountRejected){ PopulationStore p; EXPECT_THROW(p.add(-1),std::invalid_argument); }

TEST(SimulationState_StartsAtZeroTime){ CompiledModel m=oneTypeModel(); SimulationState s(m); EXPECT_EQ(s.time(),0.0); }
TEST(SimulationState_TimeRoundTrip){ CompiledModel m=oneTypeModel(); SimulationState s(m); s.setTime(4.25); EXPECT_EQ(s.time(),4.25); }
TEST(SimulationState_NegativeTimeRejected){ CompiledModel m=oneTypeModel(); SimulationState s(m); EXPECT_THROW(s.setTime(-0.01),std::invalid_argument); }
TEST(SimulationState_NaNTimeRejected){ CompiledModel m=oneTypeModel(); SimulationState s(m); EXPECT_THROW(s.setTime(std::numeric_limits<double>::quiet_NaN()),std::invalid_argument); }
TEST(SimulationState_TypeIndexBoundsChecked){ CompiledModel m=oneTypeModel(); SimulationState s(m); EXPECT_THROW(s.molecules(MoleculeTypeId(9)),std::out_of_range); }

TEST(FeatureDelta_ClearRemovesAllEntries){ FeatureDelta d; d.add(FeatureId(1)); d.add(FeatureId(2)); EXPECT_EQ(d.changed.size(),2u); d.clear(); EXPECT_TRUE(d.changed.empty()); }
TEST(FeatureDelta_AllowsDuplicateRawEntriesForCheapHotPath){ FeatureDelta d; d.add(FeatureId(1)); d.add(FeatureId(1)); EXPECT_EQ(d.changed.size(),2u); }
