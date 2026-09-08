#include "compiled_model.hh"
#include "engine.hh"
#include "rule_compiler.hh"
#include "legacy_bridge.hh"
#include "shadow.hh"
#include "model_image.hh"
#include <sstream>
#include <cassert>
#include <cmath>
#include <iostream>
using namespace NFcore2;

static void test_handles(){MoleculeTypeDescriptor d;d.state_words=1;d.bond_slots=1;CompiledModel m;MoleculeTypeId t=m.addMoleculeType(d);SimulationState s(m);MoleculeHandle a=s.molecules(t).create();assert(s.molecules(t).alive(a));s.molecules(t).setStateWord(a,0,7);assert(s.molecules(t).stateWord(a,0)==7);assert(s.molecules(t).erase(a));assert(!s.molecules(t).alive(a));MoleculeHandle b=s.molecules(t).create();assert(b.slot==a.slot&&b.generation!=a.generation);}
static void test_scheduler(){CompiledModel m;RuleFamilyDescriptor f;f.members.resize(3);RuleFamilyId id=m.addRuleFamily(f);HierarchicalScheduler s(m);s.setMemberActivity(id,0,1);s.setMemberActivity(id,1,2);s.setMemberActivity(id,2,7);assert(std::fabs(s.totalActivity()-10)<1e-12);assert(s.sample(0.01).member==0);assert(s.sample(0.15).member==1);assert(s.sample(0.95).member==2);}
static void test_scaffold_match_transform(){ExecutableModel executable;CompiledModel& m=executable.buildMetadata();MoleculeTypeDescriptor td;td.name="RNAP";td.state_words=1;MoleculeTypeId type=m.addMoleculeType(td);FeatureId occ=m.addFeature(FeatureDescriptor(FEATURE_SCAFFOLD_OCCUPANCY,0,0));FeatureId st=m.addFeature(FeatureDescriptor(FEATURE_MOLECULE_STATE,type.value(),0));
MatcherProgram mp;MatchInstruction e(MATCH_TYPE_EXISTS);mp.add(e);MatchInstruction sm(MATCH_STATE_MASK);sm.a=0;sm.mask=1;sm.value=1;mp.add(sm);MatchInstruction free(MATCH_SCAFFOLD_FREE);free.a=1;mp.add(free);mp.add(MatchInstruction(MATCH_END));
TransformProgram tp;TransformInstruction move(TRANSFORM_MOVE_OCCUPANT);move.a=0;move.b=1;move.value=occ.value();tp.add(move);TransformInstruction ss(TRANSFORM_SET_STATE_WORD);ss.a=0;ss.value=1;ss.b=st.value();tp.add(ss);tp.add(TransformInstruction(TRANSFORM_END));
MatcherId mid=executable.buildMatchers().add(mp);TransformProgramId tid=executable.buildTransforms().add(tp);RuleFamilyDescriptor fam;fam.name="elongation";fam.matcher=mid;fam.transform=tid;fam.members.resize(100000);RuleFamilyId fid=m.addRuleFamily(fam);std::vector<std::vector<MatcherId> > deps(m.features().size());deps[occ.value()].push_back(mid);deps[st.value()].push_back(mid);m.setFeatureDependencies(deps);
Engine eng(executable);ScaffoldId sc=eng.scaffolds().create(100000);MoleculeHandle r=eng.state().molecules(type).create();eng.state().molecules(type).setStateWord(r,0,1);eng.scaffolds().setOccupant(sc,1234,r);MatchContext c;c.type=type;c.molecule=r;c.scaffold=sc;c.coordinate=1234;FeatureDelta d;assert(eng.fire(fid,1234,c,d));assert(c.coordinate==1235);assert(!eng.scaffolds().occupant(sc,1234).valid());assert(eng.scaffolds().occupant(sc,1235)==r);std::vector<MatcherId> affected=eng.affectedMatchers(d);assert(affected.size()==1&&affected[0]==mid);
}

static void test_rule_family_compiler(){std::vector<RuleInstanceIR> r(10000);for(std::size_t i=0;i<r.size();++i){r[i].name="elongation";r[i].matcher_signature="RNAP(state~elongating)+free(next)";r[i].transform_signature="move(+1)";r[i].matcher=MatcherId(3);r[i].transform=TransformProgramId(2);r[i].rate=1.0;r[i].coordinate=static_cast<std::uint32_t>(i);}RuleFamilyCompilation c=RuleFamilyCompiler::compile(r);assert(c.families.size()==1);assert(c.families[0].members.size()==10000);assert(c.instance_to_member[9999]==9999);}
static void test_sparse_genome_scaffold(){ScaffoldStore s;ScaffoldId id=s.create(100000000,0,SCAFFOLD_SPARSE);assert(s.materializedStateCount(id)==0);s.setState(id,98765432,2);assert(s.state(id,98765432)==2);assert(s.state(id,1)==0);assert(s.materializedStateCount(id)==1);MoleculeHandle h(4,1);s.setOccupant(id,12345678,h);assert(s.occupiedCount(id)==1);assert(s.occupant(id,12345678)==h);}

static void test_legacy_lowerer_and_fallback(){
    LegacyModelIR lm; MoleculeTypeDescriptor td;td.name="RNAP";td.state_words=1;lm.molecule_types.push_back(td);
    lm.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,0));
    lm.features.push_back(FeatureDescriptor(FEATURE_SCAFFOLD_OCCUPANCY,0,0));
    for(std::uint32_t i=0;i<5000;++i){LegacyRuleIR r;r.name="elongation";r.rate=2.0;r.coordinate=i;
        LegacyPredicateIR p;p.kind=LEGACY_PRED_STATE_MASK;p.a=0;p.mask=1;p.value=1;r.predicates.push_back(p);
        LegacyPredicateIR f;f.kind=LEGACY_PRED_SCAFFOLD_FREE;f.a=1;r.predicates.push_back(f);
        LegacyTransformIR t;t.kind=LEGACY_TRANSFORM_MOVE_OCCUPANT;t.a=0;t.b=1;t.changed_feature=FeatureId(1);r.transforms.push_back(t);
        lm.rules.push_back(r);
    }
    LegacyRuleIR fallback;fallback.name="connected";fallback.uses_connected_to=true;lm.rules.push_back(fallback);
    LegacyLoweringResult x=LegacyLowerer::lower(lm);assert(x.supported_rule_count==5000);assert(x.fallback_rule_count==1);
    assert(x.executable.metadata().ruleFamilies().size()==1);assert(x.executable.metadata().ruleFamilies()[0].members.size()==5000);
    assert(x.executable.matchers().size()==1);assert(x.executable.transforms().size()==1);assert(!x.rules.back().supported());assert(x.rules.back().reason==LOWERING_CONNECTED_TO);
}
static void test_shadow_comparator(){ShadowState a,b;a.time=b.time=1.0;a.populations.push_back(4);b.populations.push_back(4);a.semantic_hash=b.semantic_hash=99;ShadowObservable oa;oa.name="X";oa.value=3.0;a.observables.push_back(oa);b.observables.push_back(oa);assert(!ShadowComparator::compareState(a,b).mismatch);b.semantic_hash=100;ShadowMismatch m=ShadowComparator::compareState(a,b);assert(m.mismatch&&m.field=="semantic_hash");SemanticHasher h1,h2;h1.addString("A");h1.addU64(4);h2.addString("A");h2.addU64(4);assert(h1.value()==h2.value());}


static void test_cross_type_graph_bytecode(){ExecutableModel e;CompiledModel&m=e.buildMetadata();MoleculeTypeDescriptor a;a.name="A";a.bond_slots=1;MoleculeTypeDescriptor b;b.name="B";b.bond_slots=1;MoleculeTypeId at=m.addMoleculeType(a),bt=m.addMoleculeType(b);FeatureId bf=m.addFeature(FeatureDescriptor(FEATURE_MOLECULE_BOND,at.value(),0));MatcherProgram mp;MatchInstruction ex(MATCH_TYPE_EXISTS);ex.target=0;mp.add(ex);MatchInstruction free0(MATCH_BOND_FREE);free0.target=0;free0.a=0;mp.add(free0);MatchInstruction ex1(MATCH_TYPE_EXISTS);ex1.target=1;mp.add(ex1);MatchInstruction free1(MATCH_BOND_FREE);free1.target=1;free1.a=0;mp.add(free1);mp.add(MatchInstruction(MATCH_END));TransformProgram tp;TransformInstruction bind(TRANSFORM_BIND);bind.target=0;bind.other=1;bind.a=0;bind.b=0;bind.feature=bf;tp.add(bind);tp.add(TransformInstruction(TRANSFORM_END));MatcherId mid=e.buildMatchers().add(mp);TransformProgramId tid=e.buildTransforms().add(tp);RuleFamilyDescriptor f;f.matcher=mid;f.transform=tid;f.members.resize(1);RuleFamilyId fid=m.addRuleFamily(f);std::vector<std::vector<MatcherId> >deps(1);deps[0].push_back(mid);m.setFeatureDependencies(deps);Engine eng(e);MoleculeHandle ah=eng.state().molecules(at).create(),bh=eng.state().molecules(bt).create();MatchContext c;c.setMoleculeAt(0,MoleculeRef(at,ah));c.setMoleculeAt(1,MoleculeRef(bt,bh));FeatureDelta d;assert(eng.fire(fid,0,c,d));assert(eng.state().molecules(at).bondRef(ah,0)==MoleculeRef(bt,bh));assert(eng.state().molecules(bt).bondRef(bh,0)==MoleculeRef(at,ah));}


static void test_rate_aware_scheduler_and_family_dependencies(){CompiledModel m;FeatureId f=m.addFeature(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,0));RuleFamilyDescriptor a;a.matcher=MatcherId(0);a.members.resize(2);a.members[0].rate=2.5;a.members[1].rate=4.0;RuleFamilyId fa=m.addRuleFamily(a);RuleFamilyDescriptor b;b.matcher=MatcherId(1);b.members.resize(1);b.members[0].rate=7;RuleFamilyId fb=m.addRuleFamily(b);std::vector<std::vector<MatcherId> >d(1);d[0].push_back(MatcherId(0));d[0].push_back(MatcherId(1));m.setFeatureDependencies(d);HierarchicalScheduler sch(m);sch.setMemberMatched(fa,0,true);sch.setMemberMultiplicity(fa,1,3);sch.setMemberMatched(fb,0,false);assert(std::fabs(sch.totalActivity()-(2.5+12.0))<1e-12);assert(m.familiesForMatcher(MatcherId(0)).size()==1&&m.familiesForMatcher(MatcherId(0))[0]==fa);}


static void test_model_image_roundtrip(){ExecutableModel e;CompiledModel&m=e.buildMetadata();MoleculeTypeDescriptor t;t.name="X";t.state_words=2;t.bond_slots=1;m.addMoleculeType(t);m.addFeature(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,1));MatcherProgram mp;MatchInstruction mi(MATCH_STATE_MASK);mi.a=1;mi.mask=3;mi.value=2;mp.add(mi);mp.add(MatchInstruction(MATCH_END));MatcherId mid=e.buildMatchers().add(mp);TransformProgram tp;TransformInstruction ti(TRANSFORM_SET_STATE_WORD);ti.a=1;ti.value=2;ti.feature=FeatureId(0);tp.add(ti);tp.add(TransformInstruction(TRANSFORM_END));TransformProgramId tid=e.buildTransforms().add(tp);RuleFamilyDescriptor f;f.name="r";f.matcher=mid;f.transform=tid;f.members.resize(2);f.members[0].rate=1.5;f.members[1].rate=2.5;m.addRuleFamily(f);std::vector<std::vector<MatcherId> > dep(1);dep[0].push_back(mid);m.setFeatureDependencies(dep);std::stringstream ss(std::ios::in|std::ios::out|std::ios::binary);ModelImage::write(e,ss);ss.seekg(0);ExecutableModel r=ModelImage::read(ss);assert(r.metadata().moleculeTypes().size()==1);assert(r.metadata().moleculeTypes()[0].name=="X");assert(r.matchers().size()==1&&r.transforms().size()==1);assert(r.metadata().ruleFamilies().size()==1&&r.metadata().ruleFamilies()[0].members.size()==2);assert(std::fabs(r.metadata().ruleFamilies()[0].members[1].rate-2.5)<1e-12);std::pair<const MatcherId*,const MatcherId*> dr=r.metadata().dependencies().dependents(FeatureId(0));assert(dr.first&&dr.second-dr.first==1&&*dr.first==MatcherId(0));}

int main(){test_handles();test_scheduler();test_rule_family_compiler();test_sparse_genome_scaffold();test_scaffold_match_transform();test_legacy_lowerer_and_fallback();test_shadow_comparator();test_cross_type_graph_bytecode();test_rate_aware_scheduler_and_family_dependencies();test_model_image_roundtrip();std::cout<<"NFcore2 tests passed\n";return 0;}
