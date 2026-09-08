#include "test_harness.hh"
#include "compiled_model.hh"
#include "scheduler.hh"
#include <algorithm>
#include <limits>
#include <set>
using namespace NFcore2;

namespace {
CompiledModel schedulerModel(){
    CompiledModel m;
    MoleculeTypeDescriptor d;
    d.name="A";
    m.addMoleculeType(d);

    for(unsigned i=0;i<5;++i){
        m.addFeature(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,i));
    }

    RuleFamilyDescriptor f0;
    f0.name="f0";
    f0.matcher=MatcherId(0);
    f0.transform=TransformProgramId(0);
    for(unsigned i=0;i<3;++i){
        RuleMember r;
        r.rate=1.0+i;
        r.coordinate=i;
        f0.members.push_back(r);
    }
    m.addRuleFamily(f0);

    RuleFamilyDescriptor f1;
    f1.name="f1";
    f1.matcher=MatcherId(1);
    f1.transform=TransformProgramId(1);
    for(unsigned i=0;i<2;++i){
        RuleMember r;
        r.rate=10.0*(i+1);
        r.coordinate=10+i;
        f1.members.push_back(r);
    }
    m.addRuleFamily(f1);
    return m;
}
}

TEST(CompiledModel_AddMoleculeTypeReturnsSequentialIds){
    CompiledModel m;
    MoleculeTypeDescriptor a;a.name="A";
    MoleculeTypeDescriptor b;b.name="B";
    EXPECT_EQ(m.addMoleculeType(a),MoleculeTypeId(0));
    EXPECT_EQ(m.addMoleculeType(b),MoleculeTypeId(1));
    EXPECT_EQ(m.moleculeTypes().size(),2u);
    EXPECT_EQ(m.moleculeTypes()[0].name,std::string("A"));
    EXPECT_EQ(m.moleculeTypes()[1].name,std::string("B"));
}

TEST(CompiledModel_AddFeatureReturnsSequentialIds){
    CompiledModel m;
    FeatureId a=m.addFeature(FeatureDescriptor(FEATURE_TIME,0,0));
    FeatureId b=m.addFeature(FeatureDescriptor(FEATURE_POPULATION,3,0));
    EXPECT_EQ(a,FeatureId(0));
    EXPECT_EQ(b,FeatureId(1));
    EXPECT_EQ(m.features().size(),2u);
}

TEST(CompiledModel_FeatureDescriptorsPreserveAllFields){
    CompiledModel m;
    FeatureDescriptor d(FEATURE_SCAFFOLD_OCCUPANCY,17,91);
    FeatureId id=m.addFeature(d);
    const FeatureDescriptor& got=m.features().at(id.value());
    EXPECT_EQ(got.kind,FEATURE_SCAFFOLD_OCCUPANCY);
    EXPECT_EQ(got.owner,17u);
    EXPECT_EQ(got.index,91u);
}

TEST(CompiledModel_AddRuleFamilyPreservesMembers){
    CompiledModel m;
    RuleFamilyDescriptor f;
    f.name="elongation";
    f.matcher=MatcherId(4);
    f.transform=TransformProgramId(2);
    f.uniform_rate=false;
    RuleMember a;a.rate=1.5;a.parameter_index=7;a.coordinate=50;
    RuleMember b;b.rate=2.5;b.parameter_index=8;b.coordinate=51;
    f.members.push_back(a);
    f.members.push_back(b);
    RuleFamilyId id=m.addRuleFamily(f);
    const RuleFamilyDescriptor& got=m.ruleFamilies().at(id.value());
    EXPECT_EQ(got.name,std::string("elongation"));
    EXPECT_EQ(got.matcher,MatcherId(4));
    EXPECT_EQ(got.transform,TransformProgramId(2));
    EXPECT_FALSE(got.uniform_rate);
    EXPECT_EQ(got.members.size(),2u);
    EXPECT_EQ(got.members[1].coordinate,51u);
}

TEST(CompiledModel_FamiliesForMatcherTracksAllFamilies){
    CompiledModel m;
    RuleFamilyDescriptor a;a.matcher=MatcherId(9);a.transform=TransformProgramId(0);a.name="a";
    RuleFamilyDescriptor b;b.matcher=MatcherId(9);b.transform=TransformProgramId(0);b.name="b";
    RuleFamilyDescriptor c;c.matcher=MatcherId(10);c.transform=TransformProgramId(0);c.name="c";
    RuleFamilyId ia=m.addRuleFamily(a);
    RuleFamilyId ib=m.addRuleFamily(b);
    m.addRuleFamily(c);
    const std::vector<RuleFamilyId>& out=m.familiesForMatcher(MatcherId(9));
    EXPECT_EQ(out.size(),2u);
    EXPECT_EQ(out[0],ia);
    EXPECT_EQ(out[1],ib);
}

TEST(CompiledModel_FamiliesForUnknownMatcherReturnsEmpty){
    CompiledModel m;
    EXPECT_TRUE(m.familiesForMatcher(MatcherId(999)).empty());
    EXPECT_TRUE(m.familiesForMatcher(MatcherId()).empty());
}

TEST(DependencyIndex_BuildRejectsWrongAdjacencySize){
    DependencyIndex d;
    std::vector<std::vector<MatcherId> > a(2);
    EXPECT_THROW(d.build(3,a),std::invalid_argument);
}

TEST(DependencyIndex_EmptyIndexHasNullRange){
    DependencyIndex d;
    std::vector<std::vector<MatcherId> > a;
    d.build(0,a);
    std::pair<const MatcherId*,const MatcherId*> r=d.dependents(FeatureId(0));
    EXPECT_TRUE(r.first==0);
    EXPECT_TRUE(r.second==0);
}

TEST(DependencyIndex_PreservesFeatureOrderAndMultiplicity){
    DependencyIndex d;
    std::vector<std::vector<MatcherId> > a(3);
    a[0].push_back(MatcherId(4));
    a[0].push_back(MatcherId(4));
    a[0].push_back(MatcherId(2));
    a[2].push_back(MatcherId(9));
    d.build(3,a);
    std::pair<const MatcherId*,const MatcherId*> r0=d.dependents(FeatureId(0));
    EXPECT_EQ(static_cast<std::size_t>(r0.second-r0.first),3u);
    EXPECT_EQ(r0.first[0],MatcherId(4));
    EXPECT_EQ(r0.first[1],MatcherId(4));
    EXPECT_EQ(r0.first[2],MatcherId(2));
    std::pair<const MatcherId*,const MatcherId*> r1=d.dependents(FeatureId(1));
    EXPECT_EQ(r1.first,r1.second);
    std::pair<const MatcherId*,const MatcherId*> r2=d.dependents(FeatureId(2));
    EXPECT_EQ(static_cast<std::size_t>(r2.second-r2.first),1u);
    EXPECT_EQ(r2.first[0],MatcherId(9));
}

TEST(DependencyIndex_OutOfRangeFeatureReturnsNullRange){
    DependencyIndex d;
    std::vector<std::vector<MatcherId> > a(1);
    a[0].push_back(MatcherId(0));
    d.build(1,a);
    std::pair<const MatcherId*,const MatcherId*> r=d.dependents(FeatureId(2));
    EXPECT_TRUE(r.first==0);
    EXPECT_TRUE(r.second==0);
}

TEST(CompiledModel_SetFeatureDependenciesBuildsCSR){
    CompiledModel m;
    m.addFeature(FeatureDescriptor());
    m.addFeature(FeatureDescriptor());
    std::vector<std::vector<MatcherId> > a(2);
    a[0].push_back(MatcherId(3));
    a[1].push_back(MatcherId(5));
    a[1].push_back(MatcherId(7));
    m.setFeatureDependencies(a);
    EXPECT_EQ(m.dependencies().offsets.size(),3u);
    EXPECT_EQ(m.dependencies().offsets[0],0u);
    EXPECT_EQ(m.dependencies().offsets[1],1u);
    EXPECT_EQ(m.dependencies().offsets[2],3u);
    EXPECT_EQ(m.dependencies().matchers.size(),3u);
}

TEST(Fenwick_ResetStartsAllZero){
    FenwickTree t(8);
    EXPECT_EQ(t.size(),8u);
    EXPECT_EQ(t.total(),0.0);
    for(unsigned i=0;i<8;++i)EXPECT_EQ(t.value(i),0.0);
}

TEST(Fenwick_SetUpdatesSingleValueAndTotal){
    FenwickTree t(5);
    t.set(2,3.5);
    EXPECT_EQ(t.value(2),3.5);
    EXPECT_EQ(t.total(),3.5);
    EXPECT_EQ(t.prefix(2),0.0);
    EXPECT_EQ(t.prefix(3),3.5);
}

TEST(Fenwick_ReplacingValueUsesDeltaNotAccumulation){
    FenwickTree t(4);
    t.set(1,2.0);
    t.set(1,5.0);
    EXPECT_EQ(t.value(1),5.0);
    EXPECT_EQ(t.total(),5.0);
    t.set(1,1.0);
    EXPECT_EQ(t.total(),1.0);
}

TEST(Fenwick_MultipleValuesProduceCorrectPrefixes){
    FenwickTree t(6);
    const double v[6]={1,2,3,4,5,6};
    for(unsigned i=0;i<6;++i)t.set(i,v[i]);
    EXPECT_EQ(t.prefix(0),0.0);
    EXPECT_EQ(t.prefix(1),1.0);
    EXPECT_EQ(t.prefix(2),3.0);
    EXPECT_EQ(t.prefix(3),6.0);
    EXPECT_EQ(t.prefix(4),10.0);
    EXPECT_EQ(t.prefix(5),15.0);
    EXPECT_EQ(t.prefix(6),21.0);
}

TEST(Fenwick_PrefixClampsPastEnd){
    FenwickTree t(2);
    t.set(0,4);
    t.set(1,5);
    EXPECT_EQ(t.prefix(999),9.0);
}

TEST(Fenwick_SetRejectsOutOfRangeIndex){
    FenwickTree t(2);
    EXPECT_THROW(t.set(2,1.0),std::out_of_range);
}

TEST(Fenwick_SetRejectsNegativeActivity){
    FenwickTree t(2);
    EXPECT_THROW(t.set(1,-0.0001),std::out_of_range);
    EXPECT_EQ(t.total(),0.0);
}

TEST(Fenwick_SetRejectsNaNActivity){
    FenwickTree t(2);
    EXPECT_THROW(t.set(1,std::numeric_limits<double>::quiet_NaN()),std::invalid_argument);
    EXPECT_EQ(t.total(),0.0);
}

TEST(Fenwick_SetRejectsInfiniteActivity){
    FenwickTree t(2);
    EXPECT_THROW(t.set(1,std::numeric_limits<double>::infinity()),std::invalid_argument);
    EXPECT_EQ(t.total(),0.0);
}

TEST(Fenwick_SampleRejectsEmptyTree){
    FenwickTree t(0);
    EXPECT_THROW(t.sample(0),std::out_of_range);
}

TEST(Fenwick_SampleRejectsZeroTotal){
    FenwickTree t(3);
    EXPECT_THROW(t.sample(0),std::out_of_range);
}

TEST(Fenwick_SampleRejectsNegativeTarget){
    FenwickTree t(2);
    t.set(0,1);
    EXPECT_THROW(t.sample(-0.1),std::out_of_range);
}

TEST(Fenwick_SampleRejectsTargetAtTotal){
    FenwickTree t(2);
    t.set(0,1);
    t.set(1,2);
    EXPECT_THROW(t.sample(3.0),std::out_of_range);
}

TEST(Fenwick_SampleMapsIntervalsExactly){
    FenwickTree t(4);
    t.set(0,1);
    t.set(1,2);
    t.set(2,0);
    t.set(3,4);
    EXPECT_EQ(t.sample(0.0),0u);
    EXPECT_EQ(t.sample(0.999999),0u);
    EXPECT_EQ(t.sample(1.0),1u);
    EXPECT_EQ(t.sample(2.999999),1u);
    EXPECT_EQ(t.sample(3.0),3u);
    EXPECT_EQ(t.sample(6.999999),3u);
}

TEST(Fenwick_RandomizedPrefixMatchesNaiveArray){
    FenwickTree t(128);
    std::vector<double> v(128,0.0);
    std::uint32_t x=0x12345678u;
    for(unsigned step=0;step<5000;++step){
        x=x*1664525u+1013904223u;
        unsigned idx=(x>>8)%128;
        x=x*1664525u+1013904223u;
        double value=(x%10000)/100.0;
        v[idx]=value;
        t.set(idx,value);
        if(step%17==0){
            x=x*1664525u+1013904223u;
            unsigned count=x%129;
            double expected=0;
            for(unsigned i=0;i<count;++i)expected+=v[i];
            EXPECT_NEAR(t.prefix(count),expected,1e-9);
        }
    }
    double expected=0;
    for(unsigned i=0;i<128;++i)expected+=v[i];
    EXPECT_NEAR(t.total(),expected,1e-9);
}

TEST(Fenwick_RandomizedSamplingMatchesNaiveSelection){
    FenwickTree t(64);
    std::vector<double> v(64,0.0);
    for(unsigned i=0;i<64;++i){
        v[i]=(i%7==0)?0.0:(i+1)*0.25;
        t.set(i,v[i]);
    }
    const double total=t.total();
    for(unsigned k=0;k<1000;++k){
        double target=total*(k+0.5)/1000.0;
        std::size_t expected=0;
        double acc=0;
        for(;expected<v.size();++expected){
            if(target<acc+v[expected])break;
            acc+=v[expected];
        }
        EXPECT_EQ(t.sample(target),expected);
    }
}

TEST(HierarchicalScheduler_StartsWithZeroActivity){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    EXPECT_EQ(s.totalActivity(),0.0);
}

TEST(HierarchicalScheduler_MultiplicityScalesMemberRate){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    s.setMemberMultiplicity(RuleFamilyId(0),0,3.0);
    s.setMemberMultiplicity(RuleFamilyId(0),1,2.0);
    EXPECT_EQ(s.totalActivity(),3.0*1.0+2.0*2.0);
}

TEST(HierarchicalScheduler_MatchedConvenienceUsesZeroOrOneMultiplicity){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    s.setMemberMatched(RuleFamilyId(0),2,true);
    EXPECT_EQ(s.totalActivity(),3.0);
    s.setMemberMatched(RuleFamilyId(0),2,false);
    EXPECT_EQ(s.totalActivity(),0.0);
}

TEST(HierarchicalScheduler_SetMemberActivityOverridesRateDerivedValue){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    s.setMemberActivity(RuleFamilyId(1),1,123.0);
    EXPECT_EQ(s.totalActivity(),123.0);
}

TEST(HierarchicalScheduler_RejectsNegativeMultiplicity){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    EXPECT_THROW(s.setMemberMultiplicity(RuleFamilyId(0),0,-1.0),std::out_of_range);
}

TEST(HierarchicalScheduler_RejectsNaNMultiplicity){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    EXPECT_THROW(s.setMemberMultiplicity(RuleFamilyId(0),0,std::numeric_limits<double>::quiet_NaN()),std::invalid_argument);
}

TEST(HierarchicalScheduler_RejectsInfiniteMultiplicity){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    EXPECT_THROW(s.setMemberMultiplicity(RuleFamilyId(0),0,std::numeric_limits<double>::infinity()),std::invalid_argument);
}

TEST(HierarchicalScheduler_RejectsInvalidFamily){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    EXPECT_THROW(s.setMemberActivity(RuleFamilyId(99),0,1.0),std::out_of_range);
}

TEST(HierarchicalScheduler_RejectsInvalidMember){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    EXPECT_THROW(s.setMemberActivity(RuleFamilyId(0),99,1.0),std::out_of_range);
}

TEST(HierarchicalScheduler_SampleRejectsInvalidUnitInterval){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    s.setMemberActivity(RuleFamilyId(0),0,1);
    EXPECT_THROW(s.sample(-0.1),std::out_of_range);
    EXPECT_THROW(s.sample(1.0),std::out_of_range);
    EXPECT_THROW(s.sample(std::numeric_limits<double>::quiet_NaN()),std::out_of_range);
}

TEST(HierarchicalScheduler_SampleRejectsZeroTotal){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    EXPECT_THROW(s.sample(0.5),std::out_of_range);
}

TEST(HierarchicalScheduler_SelectsCorrectFamilyAndMemberIntervals){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    s.setMemberActivity(RuleFamilyId(0),0,1);
    s.setMemberActivity(RuleFamilyId(0),1,2);
    s.setMemberActivity(RuleFamilyId(1),0,3);
    s.setMemberActivity(RuleFamilyId(1),1,4);
    EXPECT_EQ(s.totalActivity(),10.0);

    EventChoice c0=s.sample(0.00);
    EXPECT_EQ(c0.family,RuleFamilyId(0));
    EXPECT_EQ(c0.member,0u);

    EventChoice c1=s.sample(0.10);
    EXPECT_EQ(c1.family,RuleFamilyId(0));
    EXPECT_EQ(c1.member,1u);

    EventChoice c2=s.sample(0.30);
    EXPECT_EQ(c2.family,RuleFamilyId(1));
    EXPECT_EQ(c2.member,0u);

    EventChoice c3=s.sample(0.60);
    EXPECT_EQ(c3.family,RuleFamilyId(1));
    EXPECT_EQ(c3.member,1u);
}

TEST(HierarchicalScheduler_ZeroWeightMembersAreNeverSelected){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    s.setMemberActivity(RuleFamilyId(0),0,0);
    s.setMemberActivity(RuleFamilyId(0),1,7);
    s.setMemberActivity(RuleFamilyId(0),2,0);
    for(unsigned i=0;i<1000;++i){
        EventChoice c=s.sample((i+0.5)/1000.0);
        EXPECT_EQ(c.family,RuleFamilyId(0));
        EXPECT_EQ(c.member,1u);
    }
}

TEST(HierarchicalScheduler_UpdatesFamilyTotalWhenMemberChanges){
    CompiledModel m=schedulerModel();
    HierarchicalScheduler s(m);
    s.setMemberActivity(RuleFamilyId(0),0,2);
    s.setMemberActivity(RuleFamilyId(0),1,3);
    s.setMemberActivity(RuleFamilyId(1),0,5);
    EXPECT_EQ(s.totalActivity(),10.0);
    s.setMemberActivity(RuleFamilyId(0),1,30);
    EXPECT_EQ(s.totalActivity(),37.0);
    s.setMemberActivity(RuleFamilyId(1),0,0);
    EXPECT_EQ(s.totalActivity(),32.0);
}

TEST(HierarchicalScheduler_LargeFamilySamplingRemainsCorrect){
    CompiledModel m;
    RuleFamilyDescriptor f;
    f.name="million-ish";
    f.matcher=MatcherId(0);
    f.transform=TransformProgramId(0);
    for(unsigned i=0;i<10000;++i){
        RuleMember r;
        r.rate=1;
        f.members.push_back(r);
    }
    m.addRuleFamily(f);
    HierarchicalScheduler s(m);
    for(unsigned i=0;i<10000;++i)s.setMemberActivity(RuleFamilyId(0),i,1.0);
    EXPECT_EQ(s.totalActivity(),10000.0);
    for(unsigned i=0;i<1000;++i){
        double u=(i+0.25)/1000.0;
        EventChoice c=s.sample(u);
        EXPECT_EQ(c.family,RuleFamilyId(0));
        EXPECT_TRUE(c.member<10000u);
    }
}
