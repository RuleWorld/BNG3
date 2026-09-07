#include "test_harness.hh"
#include "engine.hh"
#include <algorithm>
#include <map>
#include <set>
#include <utility>
using namespace NFcore2;

namespace {
struct GraphFixture {
    ExecutableModel executable;
    MatcherId always;
    TransformProgramId bind_program;
    TransformProgramId unbind_program;
    TransformProgramId delete_program;
    RuleFamilyId bind_family;
    RuleFamilyId unbind_family;
    RuleFamilyId delete_family;

    GraphFixture(){
        MoleculeTypeDescriptor a;
        a.name="A";
        a.state_words=1;
        a.bond_slots=3;
        executable.buildMetadata().addMoleculeType(a);

        MoleculeTypeDescriptor b;
        b.name="B";
        b.state_words=1;
        b.bond_slots=3;
        executable.buildMetadata().addMoleculeType(b);

        FeatureId bond_feature=executable.buildMetadata().addFeature(
            FeatureDescriptor(FEATURE_MOLECULE_BOND,0,0));

        MatcherProgram mp;
        mp.add(MatchInstruction(MATCH_END));
        always=executable.buildMatchers().add(mp);

        TransformProgram bp;
        TransformInstruction bi(TRANSFORM_BIND);
        bi.target=0;
        bi.other=1;
        bi.a=0;
        bi.b=0;
        bi.feature=bond_feature;
        bp.add(bi);
        bp.add(TransformInstruction(TRANSFORM_END));
        bind_program=executable.buildTransforms().add(bp);

        TransformProgram up;
        TransformInstruction ui(TRANSFORM_UNBIND);
        ui.target=0;
        ui.a=0;
        ui.b=0;
        ui.feature=bond_feature;
        up.add(ui);
        up.add(TransformInstruction(TRANSFORM_END));
        unbind_program=executable.buildTransforms().add(up);

        TransformProgram dp;
        TransformInstruction di(TRANSFORM_DELETE_MOLECULE);
        di.target=0;
        di.feature=bond_feature;
        dp.add(di);
        dp.add(TransformInstruction(TRANSFORM_END));
        delete_program=executable.buildTransforms().add(dp);

        RuleFamilyDescriptor bf;
        bf.name="bind";
        bf.matcher=always;
        bf.transform=bind_program;
        bf.members.push_back(RuleMember());
        bf.members[0].rate=1;
        bind_family=executable.buildMetadata().addRuleFamily(bf);

        RuleFamilyDescriptor uf;
        uf.name="unbind";
        uf.matcher=always;
        uf.transform=unbind_program;
        uf.members.push_back(RuleMember());
        uf.members[0].rate=1;
        unbind_family=executable.buildMetadata().addRuleFamily(uf);

        RuleFamilyDescriptor df;
        df.name="delete";
        df.matcher=always;
        df.transform=delete_program;
        df.members.push_back(RuleMember());
        df.members[0].rate=1;
        delete_family=executable.buildMetadata().addRuleFamily(df);

        std::vector<std::vector<MatcherId> > deps(1);
        deps[0].push_back(always);
        executable.buildMetadata().setFeatureDependencies(deps);
    }
};

void assertReciprocalSlotZero(const Engine& e,
                              const std::vector<MoleculeHandle>& as,
                              const std::vector<MoleculeHandle>& bs){
    const SimulationState& s=e.state();
    for(std::size_t i=0;i<as.size();++i){
        if(!s.molecules(MoleculeTypeId(0)).alive(as[i]))continue;
        MoleculeRef q=s.molecules(MoleculeTypeId(0)).bondRef(as[i],0);
        if(!q.valid())continue;
        EXPECT_EQ(q.type,MoleculeTypeId(1));
        EXPECT_TRUE(s.molecules(q.type).alive(q.handle));
        MoleculeRef back=s.molecules(q.type).bondRef(q.handle,0);
        EXPECT_EQ(back,MoleculeRef(MoleculeTypeId(0),as[i]));
    }
    for(std::size_t i=0;i<bs.size();++i){
        if(!s.molecules(MoleculeTypeId(1)).alive(bs[i]))continue;
        MoleculeRef q=s.molecules(MoleculeTypeId(1)).bondRef(bs[i],0);
        if(!q.valid())continue;
        EXPECT_EQ(q.type,MoleculeTypeId(0));
        EXPECT_TRUE(s.molecules(q.type).alive(q.handle));
        MoleculeRef back=s.molecules(q.type).bondRef(q.handle,0);
        EXPECT_EQ(back,MoleculeRef(MoleculeTypeId(1),bs[i]));
    }
}

std::uint32_t lcg(std::uint32_t& x){
    x=x*1664525u+1013904223u;
    return x;
}
}

TEST(RandomizedGraph_RepeatedBindUnbindMaintainsReciprocity){
    GraphFixture f;
    Engine e(f.executable);
    std::vector<MoleculeHandle> as(64),bs(64);
    for(unsigned i=0;i<64;++i){
        as[i]=e.state().molecules(MoleculeTypeId(0)).create();
        bs[i]=e.state().molecules(MoleculeTypeId(1)).create();
    }

    std::uint32_t rng=1;
    for(unsigned step=0;step<10000;++step){
        unsigned ai=lcg(rng)%64;
        unsigned bi=lcg(rng)%64;
        MoleculeStore& ast=e.state().molecules(MoleculeTypeId(0));
        MoleculeStore& bst=e.state().molecules(MoleculeTypeId(1));
        bool afree=!ast.bondRef(as[ai],0).valid();
        bool bfree=!bst.bondRef(bs[bi],0).valid();

        MatchContext c;
        c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),as[ai]));
        FeatureDelta d;
        if(afree&&bfree){
            c.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),bs[bi]));
            EXPECT_TRUE(e.fire(f.bind_family,0,c,d));
        }else if(!afree){
            EXPECT_TRUE(e.fire(f.unbind_family,0,c,d));
        }
        if(step%101==0)assertReciprocalSlotZero(e,as,bs);
    }
    assertReciprocalSlotZero(e,as,bs);
}

TEST(RandomizedGraph_DeleteBoundMoleculesNeverLeavesLiveStalePartner){
    GraphFixture f;
    Engine e(f.executable);
    std::vector<MoleculeHandle> as;
    std::vector<MoleculeHandle> bs;
    for(unsigned i=0;i<128;++i){
        as.push_back(e.state().molecules(MoleculeTypeId(0)).create());
        bs.push_back(e.state().molecules(MoleculeTypeId(1)).create());
        MatchContext c;
        c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),as.back()));
        c.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),bs.back()));
        FeatureDelta d;
        EXPECT_TRUE(e.fire(f.bind_family,0,c,d));
    }

    for(unsigned i=0;i<128;i+=3){
        MatchContext c;
        c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),as[i]));
        FeatureDelta d;
        EXPECT_TRUE(e.fire(f.delete_family,0,c,d));
        EXPECT_FALSE(e.state().molecules(MoleculeTypeId(1)).bondRef(bs[i],0).valid());
    }
    assertReciprocalSlotZero(e,as,bs);
}

TEST(RandomizedGraph_GenerationReuseCannotReconnectOldDeletedIdentity){
    GraphFixture f;
    Engine e(f.executable);
    MoleculeStore& ast=e.state().molecules(MoleculeTypeId(0));
    MoleculeStore& bst=e.state().molecules(MoleculeTypeId(1));
    MoleculeHandle olda=ast.create();
    MoleculeHandle b=bst.create();

    MatchContext bind;
    bind.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),olda));
    bind.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),b));
    FeatureDelta d;
    EXPECT_TRUE(e.fire(f.bind_family,0,bind,d));

    MatchContext del;
    del.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),olda));
    EXPECT_TRUE(e.fire(f.delete_family,0,del,d));
    EXPECT_FALSE(bst.bondRef(b,0).valid());

    MoleculeHandle newa=ast.create();
    EXPECT_EQ(newa.slot,olda.slot);
    EXPECT_NE(newa.generation,olda.generation);
    EXPECT_FALSE(ast.alive(olda));
    EXPECT_TRUE(ast.alive(newa));
    EXPECT_FALSE(bst.bondRef(b,0).valid());
}

TEST(RandomizedState_StateWordsSurviveIndependentSlotReuse){
    CompiledModel m;
    MoleculeTypeDescriptor d;
    d.name="X";
    d.state_words=4;
    d.bond_slots=0;
    m.addMoleculeType(d);
    SimulationState s(m);
    MoleculeStore& st=s.molecules(MoleculeTypeId(0));

    std::vector<MoleculeHandle> live;
    std::map<std::uint32_t,std::vector<std::uint64_t> > expected;
    std::uint32_t rng=99;
    for(unsigned step=0;step<20000;++step){
        bool create=live.empty()||(lcg(rng)&3u)!=0;
        if(create){
            MoleculeHandle h=st.create();
            live.push_back(h);
            std::vector<std::uint64_t> values(4);
            for(unsigned w=0;w<4;++w){
                values[w]=lcg(rng);
                st.setStateWord(h,w,values[w]);
            }
            expected[h.slot]=values;
        }else{
            unsigned i=lcg(rng)%live.size();
            MoleculeHandle h=live[i];
            EXPECT_TRUE(st.erase(h));
            expected.erase(h.slot);
            live[i]=live.back();
            live.pop_back();
        }

        if(step%73==0){
            for(std::size_t i=0;i<live.size();++i){
                const std::vector<std::uint64_t>& values=expected[live[i].slot];
                for(unsigned w=0;w<4;++w)EXPECT_EQ(st.stateWord(live[i],w),values[w]);
            }
            EXPECT_EQ(st.liveCount(),live.size());
        }
    }
}

TEST(RandomizedPopulation_ConservativeTransfersPreserveTotal){
    PopulationStore p;
    const unsigned n=32;
    std::vector<PopulationId> ids;
    for(unsigned i=0;i<n;++i)ids.push_back(p.add(1000));
    const std::int64_t total0=32000;
    std::uint32_t rng=123;

    for(unsigned step=0;step<100000;++step){
        unsigned a=lcg(rng)%n;
        unsigned b=lcg(rng)%n;
        if(a==b)continue;
        std::int64_t va=p.value(ids[a]);
        if(va==0)continue;
        std::int64_t amount=1+(lcg(rng)%static_cast<std::uint32_t>(std::min<std::int64_t>(va,10)));
        p.addTo(ids[a],-amount);
        p.addTo(ids[b],amount);
        if(step%997==0){
            std::int64_t total=0;
            for(unsigned i=0;i<n;++i){
                EXPECT_TRUE(p.value(ids[i])>=0);
                total+=p.value(ids[i]);
            }
            EXPECT_EQ(total,total0);
        }
    }
}

TEST(RandomizedScaffold_SparseMatchesNaiveDenseReference){
    const unsigned n=10000;
    ScaffoldStore s;
    ScaffoldId id=s.create(n,3,SCAFFOLD_SPARSE);
    std::vector<std::uint8_t> ref(n,3);
    std::map<unsigned,MoleculeHandle> occupants;
    std::uint32_t rng=777;

    for(unsigned step=0;step<50000;++step){
        unsigned pos=lcg(rng)%n;
        unsigned op=lcg(rng)%3;
        if(op==0){
            std::uint8_t value=static_cast<std::uint8_t>(lcg(rng)%8);
            s.setState(id,pos,value);
            ref[pos]=value;
        }else if(op==1){
            MoleculeHandle h(pos+1,step+1);
            s.setOccupant(id,pos,h);
            occupants[pos]=h;
        }else{
            s.setOccupant(id,pos,MoleculeHandle());
            occupants.erase(pos);
        }

        if(step%211==0){
            for(unsigned k=0;k<100;++k){
                unsigned q=lcg(rng)%n;
                EXPECT_EQ(s.state(id,q),ref[q]);
                std::map<unsigned,MoleculeHandle>::const_iterator it=occupants.find(q);
                if(it==occupants.end())EXPECT_FALSE(s.occupant(id,q).valid());
                else EXPECT_EQ(s.occupant(id,q),it->second);
            }
            EXPECT_EQ(s.occupiedCount(id),occupants.size());
        }
    }
}

TEST(RandomizedScheduler_SamplingAgreesWithNaiveAcrossUpdates){
    CompiledModel m;
    RuleFamilyDescriptor f;
    f.name="f";
    f.matcher=MatcherId(0);
    f.transform=TransformProgramId(0);
    for(unsigned i=0;i<256;++i){
        RuleMember r;
        r.rate=1;
        f.members.push_back(r);
    }
    m.addRuleFamily(f);
    HierarchicalScheduler s(m);
    std::vector<double> weights(256,0);
    std::uint32_t rng=42;

    for(unsigned step=0;step<10000;++step){
        unsigned idx=lcg(rng)%256;
        double w=(lcg(rng)%1000)/10.0;
        weights[idx]=w;
        s.setMemberActivity(RuleFamilyId(0),idx,w);

        if(step%31==0 && s.totalActivity()>0){
            double u=((lcg(rng)%1000000)+0.5)/1000000.0;
            EventChoice c=s.sample(u);
            double target=u*s.totalActivity();
            double acc=0;
            unsigned expected=0;
            for(;expected<weights.size();++expected){
                if(target<acc+weights[expected])break;
                acc+=weights[expected];
            }
            EXPECT_EQ(c.member,expected);
        }
    }
}

TEST(RandomizedEngine_CopyDivergenceDoesNotLeakAcrossTrajectories){
    GraphFixture f;
    Engine a(f.executable);
    std::vector<MoleculeHandle> as,bs;
    for(unsigned i=0;i<20;++i){
        as.push_back(a.state().molecules(MoleculeTypeId(0)).create());
        bs.push_back(a.state().molecules(MoleculeTypeId(1)).create());
    }
    Engine b(a);

    for(unsigned i=0;i<10;++i){
        MatchContext c;
        c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),as[i]));
        c.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),bs[i]));
        FeatureDelta d;
        EXPECT_TRUE(a.fire(f.bind_family,0,c,d));
    }

    for(unsigned i=10;i<20;++i){
        MatchContext c;
        c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),as[i]));
        c.setMoleculeAt(1,MoleculeRef(MoleculeTypeId(1),bs[i]));
        FeatureDelta d;
        EXPECT_TRUE(b.fire(f.bind_family,0,c,d));
    }

    for(unsigned i=0;i<20;++i){
        bool abound=a.state().molecules(MoleculeTypeId(0)).bondRef(as[i],0).valid();
        bool bbound=b.state().molecules(MoleculeTypeId(0)).bondRef(as[i],0).valid();
        EXPECT_NE(abound,bbound);
    }
}
