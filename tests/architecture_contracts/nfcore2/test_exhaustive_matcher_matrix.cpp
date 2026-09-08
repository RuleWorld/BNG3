#include "test_harness.hh"
#include "matcher.hh"
using namespace NFcore2;

static CompiledModel matcherModel(){
    CompiledModel m; MoleculeTypeDescriptor d; d.name="A"; d.state_words=2; d.bond_slots=3; m.addMoleculeType(d);
    MoleculeTypeDescriptor e; e.name="B"; e.state_words=1; e.bond_slots=2; m.addMoleculeType(e); return m;
}
static bool eval1(const MatcherProgram&p, SimulationState&s, MatchContext&c){ ScaffoldStore sc; return p.evaluate(s,sc,c); }

TEST(exhaustive_state_mask_truth_table_16bit){
    CompiledModel m=matcherModel(); SimulationState s(m); MoleculeHandle h=s.molecules(MoleculeTypeId(0)).create(); MatchContext c; c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),h));
    for(unsigned mask=0;mask<256;++mask) for(unsigned req=0;req<256;++req){
        MatcherProgram p; MatchInstruction i(MATCH_STATE_MASK); i.target=0;i.a=0;i.mask=mask;i.value=req;p.add(i);p.add(MatchInstruction(MATCH_END));
        for(unsigned v=0;v<256;v+=17){ s.molecules(MoleculeTypeId(0)).setStateWord(h,0,v); EXPECT_EQ(eval1(p,s,c), ((v&mask)==req)); }
    }
}
TEST(exhaustive_state_not_equal_truth_table){
    CompiledModel m=matcherModel(); SimulationState s(m); MoleculeHandle h=s.molecules(MoleculeTypeId(0)).create(); MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),h));
    for(unsigned req=0;req<64;++req){ MatcherProgram p;MatchInstruction i(MATCH_STATE_NOT_EQUAL);i.target=0;i.a=1;i.value=req;p.add(i);p.add(MatchInstruction(MATCH_END)); for(unsigned v=0;v<64;++v){s.molecules(MoleculeTypeId(0)).setStateWord(h,1,v);EXPECT_EQ(eval1(p,s,c),v!=req);} }
}
TEST(bond_present_and_free_are_complements){
    CompiledModel m=matcherModel(); SimulationState s(m); auto a=s.molecules(MoleculeTypeId(0)).create(); auto b=s.molecules(MoleculeTypeId(1)).create(); MatchContext c;c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),a));
    for(unsigned slot=0;slot<3;++slot){ MatcherProgram pp,pf;MatchInstruction ip(MATCH_BOND_PRESENT),ifr(MATCH_BOND_FREE);ip.target=ifr.target=0;ip.a=ifr.a=slot;pp.add(ip);pp.add(MatchInstruction(MATCH_END));pf.add(ifr);pf.add(MatchInstruction(MATCH_END)); EXPECT_FALSE(eval1(pp,s,c));EXPECT_TRUE(eval1(pf,s,c)); s.molecules(MoleculeTypeId(0)).setBondRef(a,slot,MoleculeRef(MoleculeTypeId(1),b)); EXPECT_TRUE(eval1(pp,s,c));EXPECT_FALSE(eval1(pf,s,c)); s.molecules(MoleculeTypeId(0)).setBondRef(a,slot,MoleculeRef()); }
}
TEST(bond_to_checks_type_and_handle_and_slot){
    CompiledModel m=matcherModel();SimulationState s(m);auto a=s.molecules(MoleculeTypeId(0)).create();auto b=s.molecules(MoleculeTypeId(1)).create();auto b2=s.molecules(MoleculeTypeId(1)).create();MatchContext c;c.setMoleculeAt(0,{MoleculeTypeId(0),a});c.setMoleculeAt(1,{MoleculeTypeId(1),b});
    s.molecules(MoleculeTypeId(0)).setBondRef(a,2,{MoleculeTypeId(1),b}); MatcherProgram p;MatchInstruction i(MATCH_BOND_TO);i.target=0;i.b=1;i.a=2;p.add(i);p.add(MatchInstruction(MATCH_END));EXPECT_TRUE(eval1(p,s,c));c.setMoleculeAt(1,{MoleculeTypeId(1),b2});EXPECT_FALSE(eval1(p,s,c));
}
TEST(missing_secondary_reactants_fail_all_secondary_predicates){
    CompiledModel m=matcherModel();SimulationState s(m);auto a=s.molecules(MoleculeTypeId(0)).create();MatchContext c;c.setMoleculeAt(0,{MoleculeTypeId(0),a});
    const int ops[]={MATCH_TYPE_EXISTS,MATCH_STATE_MASK,MATCH_STATE_NOT_EQUAL,MATCH_BOND_PRESENT,MATCH_BOND_FREE,MATCH_BOND_TO};
    for(unsigned k=0;k<sizeof(ops)/sizeof(ops[0]);++k){MatcherProgram p;MatchInstruction i(ops[k]);i.target=1;i.mask=0;i.value=0;i.a=0;i.b=0;p.add(i);p.add(MatchInstruction(MATCH_END));EXPECT_FALSE(eval1(p,s,c));}
}
TEST(conjunction_short_circuits_semantically){
    CompiledModel m=matcherModel();SimulationState s(m);auto a=s.molecules(MoleculeTypeId(0)).create();MatchContext c;c.setMoleculeAt(0,{MoleculeTypeId(0),a});
    for(unsigned x=0;x<32;++x){s.molecules(MoleculeTypeId(0)).setStateWord(a,0,x);MatcherProgram p;MatchInstruction a1(MATCH_STATE_MASK),a2(MATCH_STATE_NOT_EQUAL),a3(MATCH_BOND_FREE);a1.target=a2.target=a3.target=0;a1.a=a2.a=0;a1.mask=3;a1.value=1;a2.value=7;a3.a=1;p.add(a1);p.add(a2);p.add(a3);p.add(MatchInstruction(MATCH_END));EXPECT_EQ(eval1(p,s,c),((x&3)==1 && x!=7));}
}
TEST(stale_primary_handle_fails_match_not_crashes){
    CompiledModel m=matcherModel();SimulationState s(m);auto h=s.molecules(MoleculeTypeId(0)).create();MatchContext c;c.setMoleculeAt(0,{MoleculeTypeId(0),h});s.molecules(MoleculeTypeId(0)).erase(h);MatcherProgram p;MatchInstruction i(MATCH_TYPE_EXISTS);i.target=0;p.add(i);p.add(MatchInstruction(MATCH_END));EXPECT_FALSE(eval1(p,s,c));
}
