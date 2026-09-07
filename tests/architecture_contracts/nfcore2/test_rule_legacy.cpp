#include "test_harness.hh"
#include "legacy_bridge.hh"
#include "engine.hh"
#include <sstream>
using namespace NFcore2;

namespace {
RuleInstanceIR inst(const std::string& name,const std::string& ms,const std::string& ts,unsigned mid,unsigned tid,double rate,unsigned param,unsigned coord){
    RuleInstanceIR r;
    r.name=name;
    r.matcher_signature=ms;
    r.transform_signature=ts;
    r.matcher=MatcherId(mid);
    r.transform=TransformProgramId(tid);
    r.rate=rate;
    r.parameter_index=param;
    r.coordinate=coord;
    return r;
}
LegacyPredicateIR pred(LegacyPredicateKind k,unsigned a=0,unsigned b=0,std::uint64_t mask=0,std::uint64_t value=0){
    LegacyPredicateIR p;
    p.kind=k;p.a=a;p.b=b;p.mask=mask;p.value=value;
    return p;
}
LegacyTransformIR trans(LegacyTransformKind k,unsigned a=0,unsigned b=0,std::int64_t value=0,FeatureId f=FeatureId()){
    LegacyTransformIR t;
    t.kind=k;t.a=a;t.b=b;t.value=value;t.changed_feature=f;
    return t;
}
LegacyModelIR baseLegacy(){
    LegacyModelIR m;
    MoleculeTypeDescriptor d;
    d.name="R";
    d.state_words=2;
    d.bond_slots=2;
    m.molecule_types.push_back(d);
    m.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,0));
    m.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,1));
    m.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_BOND,0,0));
    m.features.push_back(FeatureDescriptor(FEATURE_POPULATION,0,0));
    m.features.push_back(FeatureDescriptor(FEATURE_SCAFFOLD_OCCUPANCY,0,0));
    return m;
}
LegacyRuleIR stateRule(const std::string& name,unsigned coord,double rate){
    LegacyRuleIR r;
    r.name=name;
    r.rate=rate;
    r.coordinate=coord;
    r.predicates.push_back(pred(LEGACY_PRED_TYPE_EXISTS));
    r.predicates.push_back(pred(LEGACY_PRED_STATE_MASK,0,0,1,0));
    r.transforms.push_back(trans(LEGACY_TRANSFORM_SET_STATE_WORD,0,0,1,FeatureId(0)));
    return r;
}
}

TEST(RuleCompiler_EmptyInputProducesEmptyCompilation){
    std::vector<RuleInstanceIR> in;
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_TRUE(out.families.empty());
    EXPECT_TRUE(out.instance_to_family.empty());
    EXPECT_TRUE(out.instance_to_member.empty());
}

TEST(RuleCompiler_OneInstanceProducesOneFamilyOneMember){
    std::vector<RuleInstanceIR> in;
    in.push_back(inst("r0","m","t",0,0,2.0,4,17));
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families.size(),1u);
    EXPECT_EQ(out.families[0].members.size(),1u);
    EXPECT_EQ(out.instance_to_family[0],RuleFamilyId(0));
    EXPECT_EQ(out.instance_to_member[0],0u);
    EXPECT_EQ(out.families[0].members[0].rate,2.0);
    EXPECT_EQ(out.families[0].members[0].parameter_index,4u);
    EXPECT_EQ(out.families[0].members[0].coordinate,17u);
}

TEST(RuleCompiler_IdenticalProgramsAndSignaturesCollapse){
    std::vector<RuleInstanceIR> in;
    in.push_back(inst("elong_1","m","t",2,3,1.0,0,1));
    in.push_back(inst("elong_2","m","t",2,3,1.0,0,2));
    in.push_back(inst("elong_3","m","t",2,3,1.0,0,3));
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families.size(),1u);
    EXPECT_EQ(out.families[0].members.size(),3u);
    EXPECT_EQ(out.instance_to_family[0],RuleFamilyId(0));
    EXPECT_EQ(out.instance_to_family[1],RuleFamilyId(0));
    EXPECT_EQ(out.instance_to_family[2],RuleFamilyId(0));
    EXPECT_EQ(out.instance_to_member[2],2u);
}

TEST(RuleCompiler_DifferentMatcherIdPreventsCollapseEvenWithSameSignature){
    std::vector<RuleInstanceIR> in;
    in.push_back(inst("a","m","t",1,3,1,0,0));
    in.push_back(inst("b","m","t",2,3,1,0,1));
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families.size(),2u);
}

TEST(RuleCompiler_DifferentTransformIdPreventsCollapseEvenWithSameSignature){
    std::vector<RuleInstanceIR> in;
    in.push_back(inst("a","m","t",1,3,1,0,0));
    in.push_back(inst("b","m","t",1,4,1,0,1));
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families.size(),2u);
}

TEST(RuleCompiler_DifferentMatcherSignaturePreventsCollapse){
    std::vector<RuleInstanceIR> in;
    in.push_back(inst("a","m0","t",1,3,1,0,0));
    in.push_back(inst("b","m1","t",1,3,1,0,1));
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families.size(),2u);
}

TEST(RuleCompiler_DifferentTransformSignaturePreventsCollapse){
    std::vector<RuleInstanceIR> in;
    in.push_back(inst("a","m","t0",1,3,1,0,0));
    in.push_back(inst("b","m","t1",1,3,1,0,1));
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families.size(),2u);
}

TEST(RuleCompiler_RatesDoNotPreventStructuralFamilyCollapse){
    std::vector<RuleInstanceIR> in;
    in.push_back(inst("a","m","t",1,3,1.0,0,0));
    in.push_back(inst("b","m","t",1,3,2.0,1,1));
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families.size(),1u);
    EXPECT_EQ(out.families[0].members.size(),2u);
    EXPECT_FALSE(out.families[0].uniform_rate);
    EXPECT_EQ(out.families[0].members[0].rate,1.0);
    EXPECT_EQ(out.families[0].members[1].rate,2.0);
}

TEST(RuleCompiler_UniformRateRemainsTrueForIdenticalRates){
    std::vector<RuleInstanceIR> in;
    for(unsigned i=0;i<100;++i)in.push_back(inst("r","m","t",1,3,7.25,i,i));
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families.size(),1u);
    EXPECT_TRUE(out.families[0].uniform_rate);
}

TEST(RuleCompiler_OriginalFirstRuleNamesFamily){
    std::vector<RuleInstanceIR> in;
    in.push_back(inst("first_name","m","t",1,3,1,0,0));
    in.push_back(inst("second_name","m","t",1,3,1,0,1));
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families[0].name,std::string("first_name"));
}

TEST(RuleCompiler_PreservesInputMemberOrder){
    std::vector<RuleInstanceIR> in;
    in.push_back(inst("r","m","t",1,3,1,11,900));
    in.push_back(inst("r","m","t",1,3,1,12,100));
    in.push_back(inst("r","m","t",1,3,1,13,500));
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families[0].members[0].coordinate,900u);
    EXPECT_EQ(out.families[0].members[1].coordinate,100u);
    EXPECT_EQ(out.families[0].members[2].coordinate,500u);
}

TEST(RuleCompiler_MillionLogicalRulesCollapseWithoutMetadataExplosion){
    std::vector<RuleInstanceIR> in;
    in.reserve(100000);
    for(unsigned i=0;i<100000;++i){
        in.push_back(inst("elong","same_match","same_transform",0,0,1.0,0,i));
    }
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families.size(),1u);
    EXPECT_EQ(out.families[0].members.size(),100000u);
    EXPECT_EQ(out.instance_to_family.size(),100000u);
    EXPECT_EQ(out.families[0].members.back().coordinate,99999u);
}

TEST(LegacySignature_IdenticalRulesHaveIdenticalMatcherSignature){
    LegacyRuleIR a=stateRule("a",1,1);
    LegacyRuleIR b=stateRule("b",2,2);
    EXPECT_EQ(LegacyLowerer::matcherSignature(a),LegacyLowerer::matcherSignature(b));
}

TEST(LegacySignature_RateAndCoordinateDoNotAffectMatcherSignature){
    LegacyRuleIR a=stateRule("a",1,1);
    LegacyRuleIR b=stateRule("b",999,123.5);
    EXPECT_EQ(LegacyLowerer::matcherSignature(a),LegacyLowerer::matcherSignature(b));
}

TEST(LegacySignature_PredicateMaskAffectsMatcherSignature){
    LegacyRuleIR a=stateRule("a",1,1);
    LegacyRuleIR b=a;
    b.predicates[1].mask=3;
    EXPECT_NE(LegacyLowerer::matcherSignature(a),LegacyLowerer::matcherSignature(b));
}

TEST(LegacySignature_PredicateValueAffectsMatcherSignature){
    LegacyRuleIR a=stateRule("a",1,1);
    LegacyRuleIR b=a;
    b.predicates[1].value=1;
    EXPECT_NE(LegacyLowerer::matcherSignature(a),LegacyLowerer::matcherSignature(b));
}

TEST(LegacySignature_PredicateOrderAffectsMatcherSignature){
    LegacyRuleIR a=stateRule("a",1,1);
    LegacyRuleIR b=a;
    std::swap(b.predicates[0],b.predicates[1]);
    EXPECT_NE(LegacyLowerer::matcherSignature(a),LegacyLowerer::matcherSignature(b));
}

TEST(LegacySignature_TransformFeatureAffectsTransformSignature){
    LegacyRuleIR a=stateRule("a",1,1);
    LegacyRuleIR b=a;
    b.transforms[0].changed_feature=FeatureId(1);
    EXPECT_NE(LegacyLowerer::transformSignature(a),LegacyLowerer::transformSignature(b));
}

TEST(LegacySignature_TransformValueAffectsTransformSignature){
    LegacyRuleIR a=stateRule("a",1,1);
    LegacyRuleIR b=a;
    b.transforms[0].value=3;
    EXPECT_NE(LegacyLowerer::transformSignature(a),LegacyLowerer::transformSignature(b));
}

TEST(LegacyLowerer_EmptyModelLowersCleanly){
    LegacyModelIR m;
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.supported_rule_count,0u);
    EXPECT_EQ(out.fallback_rule_count,0u);
    EXPECT_TRUE(out.rules.empty());
    EXPECT_TRUE(out.executable.metadata().ruleFamilies().empty());
}

TEST(LegacyLowerer_CopiesMoleculeTypesAndFeatures){
    LegacyModelIR m=baseLegacy();
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.executable.metadata().moleculeTypes().size(),1u);
    EXPECT_EQ(out.executable.metadata().moleculeTypes()[0].name,std::string("R"));
    EXPECT_EQ(out.executable.metadata().features().size(),5u);
}

TEST(LegacyLowerer_SupportedRuleBuildsMatcherTransformAndFamily){
    LegacyModelIR m=baseLegacy();
    m.rules.push_back(stateRule("r",10,2.5));
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.supported_rule_count,1u);
    EXPECT_EQ(out.fallback_rule_count,0u);
    EXPECT_TRUE(out.rules[0].supported());
    EXPECT_EQ(out.executable.matchers().size(),1u);
    EXPECT_EQ(out.executable.transforms().size(),1u);
    EXPECT_EQ(out.executable.metadata().ruleFamilies().size(),1u);
}

TEST(LegacyLowerer_RepeatedRulesShareMatcherTransformAndFamily){
    LegacyModelIR m=baseLegacy();
    for(unsigned i=0;i<1000;++i)m.rules.push_back(stateRule("r",i,1.0));
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.supported_rule_count,1000u);
    EXPECT_EQ(out.executable.matchers().size(),1u);
    EXPECT_EQ(out.executable.transforms().size(),1u);
    EXPECT_EQ(out.executable.metadata().ruleFamilies().size(),1u);
    EXPECT_EQ(out.executable.metadata().ruleFamilies()[0].members.size(),1000u);
}

TEST(LegacyLowerer_DifferentPredicateGetsDifferentMatcherProgram){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR a=stateRule("a",0,1);
    LegacyRuleIR b=stateRule("b",1,1);
    b.predicates[1].value=1;
    m.rules.push_back(a);
    m.rules.push_back(b);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.executable.matchers().size(),2u);
    EXPECT_EQ(out.executable.metadata().ruleFamilies().size(),2u);
}

TEST(LegacyLowerer_DifferentTransformGetsDifferentTransformProgram){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR a=stateRule("a",0,1);
    LegacyRuleIR b=stateRule("b",1,1);
    b.transforms[0].value=2;
    m.rules.push_back(a);
    m.rules.push_back(b);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.executable.transforms().size(),2u);
    EXPECT_EQ(out.executable.metadata().ruleFamilies().size(),2u);
}

TEST(LegacyLowerer_LocalFunctionFallsBackExplicitly){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("r",0,1);
    r.uses_local_function=true;
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.supported_rule_count,0u);
    EXPECT_EQ(out.fallback_rule_count,1u);
    EXPECT_EQ(out.rules[0].reason,LOWERING_LOCAL_FUNCTION);
    EXPECT_FALSE(out.rules[0].supported());
}

TEST(LegacyLowerer_ConnectedToFallsBackExplicitly){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("r",0,1);
    r.uses_connected_to=true;
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.rules[0].reason,LOWERING_CONNECTED_TO);
}

TEST(LegacyLowerer_TopologyChangeFallsBackExplicitly){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("r",0,1);
    r.changes_topology=true;
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.rules[0].reason,LOWERING_TOPOLOGY_CHANGE);
}

TEST(LegacyLowerer_UnsupportedPredicateFallsBackExplicitly){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("r",0,1);
    r.predicates.push_back(pred(LEGACY_PRED_UNSUPPORTED));
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.rules[0].reason,LOWERING_UNSUPPORTED_PREDICATE);
}

TEST(LegacyLowerer_UnsupportedTransformFallsBackExplicitly){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("r",0,1);
    r.transforms.push_back(trans(LEGACY_TRANSFORM_UNSUPPORTED));
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.rules[0].reason,LOWERING_UNSUPPORTED_TRANSFORM);
}

TEST(LegacyLowerer_FallbackPriorityIsStable){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("r",0,1);
    r.uses_local_function=true;
    r.uses_connected_to=true;
    r.changes_topology=true;
    r.predicates.push_back(pred(LEGACY_PRED_UNSUPPORTED));
    r.transforms.push_back(trans(LEGACY_TRANSFORM_UNSUPPORTED));
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.rules[0].reason,LOWERING_LOCAL_FUNCTION);
}

TEST(LegacyLowerer_MixedSupportedAndFallbackCountsAreExact){
    LegacyModelIR m=baseLegacy();
    for(unsigned i=0;i<10;++i)m.rules.push_back(stateRule("ok",i,1));
    for(unsigned i=0;i<3;++i){LegacyRuleIR r=stateRule("bad",i,1);r.uses_connected_to=true;m.rules.push_back(r);}
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.supported_rule_count,10u);
    EXPECT_EQ(out.fallback_rule_count,3u);
    EXPECT_EQ(out.rules.size(),13u);
}

TEST(LegacyLowerer_StatePredicateAndTransformExecuteCorrectly){
    LegacyModelIR m=baseLegacy();
    m.rules.push_back(stateRule("switch",0,1));
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    Engine e(out.executable);
    MoleculeHandle h=e.state().molecules(MoleculeTypeId(0)).create();
    MatchContext c;
    c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),h));
    FeatureDelta d;
    EXPECT_TRUE(e.fire(out.rules[0].family,out.rules[0].member,c,d));
    EXPECT_EQ(e.state().molecules(MoleculeTypeId(0)).stateWord(h,0),1ull);
}

TEST(LegacyLowerer_StatePredicateRejectsAlreadyChangedState){
    LegacyModelIR m=baseLegacy();
    m.rules.push_back(stateRule("switch",0,1));
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    Engine e(out.executable);
    MoleculeHandle h=e.state().molecules(MoleculeTypeId(0)).create();
    e.state().molecules(MoleculeTypeId(0)).setStateWord(h,0,1);
    MatchContext c;
    c.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),h));
    FeatureDelta d;
    EXPECT_FALSE(e.fire(out.rules[0].family,out.rules[0].member,c,d));
}

TEST(LegacyLowerer_PopulationRuleExecutesSignedDelta){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r;
    r.name="consume";
    r.rate=1;
    r.predicates.push_back(pred(LEGACY_PRED_POPULATION_AT_LEAST,0,0,0,3));
    r.transforms.push_back(trans(LEGACY_TRANSFORM_POPULATION_ADD,0,0,-3,FeatureId(3)));
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    Engine e(out.executable);
    PopulationId p=e.state().populations().add(5);
    EXPECT_EQ(p,PopulationId(0));
    MatchContext c;
    FeatureDelta d;
    EXPECT_TRUE(e.fire(out.rules[0].family,out.rules[0].member,c,d));
    EXPECT_EQ(e.state().populations().value(p),2ll);
}

TEST(LegacyLowerer_PopulationRuleRejectsInsufficientPopulation){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r;
    r.name="consume";
    r.rate=1;
    r.predicates.push_back(pred(LEGACY_PRED_POPULATION_AT_LEAST,0,0,0,3));
    r.transforms.push_back(trans(LEGACY_TRANSFORM_POPULATION_ADD,0,0,-3,FeatureId(3)));
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    Engine e(out.executable);
    e.state().populations().add(2);
    MatchContext c;
    FeatureDelta d;
    EXPECT_FALSE(e.fire(out.rules[0].family,out.rules[0].member,c,d));
}

TEST(LegacyLowerer_ScaffoldRuleMatchesAndMovesLocally){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r;
    r.name="elong";
    r.rate=1;
    r.predicates.push_back(pred(LEGACY_PRED_SCAFFOLD_STATE,0,0,0,0));
    r.predicates.push_back(pred(LEGACY_PRED_SCAFFOLD_FREE,1));
    r.transforms.push_back(trans(LEGACY_TRANSFORM_MOVE_OCCUPANT,0,1,0,FeatureId(4)));
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    Engine e(out.executable);
    ScaffoldId sc=e.scaffolds().create(100);
    MoleculeHandle h(3,1);
    e.scaffolds().setOccupant(sc,20,h);
    MatchContext c;
    c.scaffold=sc;
    c.coordinate=20;
    FeatureDelta d;
    EXPECT_TRUE(e.fire(out.rules[0].family,out.rules[0].member,c,d));
    EXPECT_FALSE(e.scaffolds().occupant(sc,20).valid());
    EXPECT_EQ(e.scaffolds().occupant(sc,21),h);
}

TEST(LegacyLowerer_FeatureDependencyIncludesMatchersThatReadChangedState){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR producer=stateRule("producer",0,1);
    LegacyRuleIR reader=stateRule("reader",1,1);
    reader.transforms[0].changed_feature=FeatureId(1);
    m.rules.push_back(producer);
    m.rules.push_back(reader);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    Engine e(out.executable);
    FeatureDelta d;
    d.add(FeatureId(0));
    std::vector<MatcherId> ms=e.affectedMatchers(d);
    EXPECT_FALSE(ms.empty());
}

TEST(LegacyLowerer_FeatureDependencyDoesNotLoseDuplicateStructuralRules){
    LegacyModelIR m=baseLegacy();
    for(unsigned i=0;i<100;++i)m.rules.push_back(stateRule("r",i,1));
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    Engine e(out.executable);
    FeatureDelta d;
    d.add(FeatureId(0));
    std::vector<RuleFamilyId> fs=e.affectedFamilies(d);
    EXPECT_EQ(fs.size(),1u);
    EXPECT_EQ(fs[0],RuleFamilyId(0));
}

TEST(LegacyLowerer_StateExclusionCompilesToNegativePredicate){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("neq",0,1.0);
    r.predicates.clear();
    r.predicates.push_back(pred(LEGACY_PRED_STATE_NOT_EQUAL,1,0,0,3));
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.supported_rule_count,1u);
    EXPECT_EQ(out.executable.matchers().at(MatcherId(0)).code()[0].opcode,(std::uint16_t)MATCH_STATE_NOT_EQUAL);
}

TEST(LegacyLowerer_BondFreeCompilesDirectly){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("free",0,1.0); r.predicates.clear();
    r.predicates.push_back(pred(LEGACY_PRED_BOND_FREE,1));
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_EQ(out.executable.matchers().at(MatcherId(0)).code()[0].opcode,(std::uint16_t)MATCH_BOND_FREE);
}

TEST(LegacyLowerer_BondToCompilesWithReactantIndex){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("bondto",0,1.0); r.predicates.clear();
    LegacyPredicateIR p=pred(LEGACY_PRED_BOND_TO,1,1); p.target=0;
    r.predicates.push_back(p);
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    const MatchInstruction& x=out.executable.matchers().at(MatcherId(0)).code()[0];
    EXPECT_EQ(x.opcode,(std::uint16_t)MATCH_BOND_TO);
    EXPECT_EQ(x.target,0u); EXPECT_EQ(x.a,1u); EXPECT_EQ(x.b,1u);
}

TEST(LegacyLowerer_PredicateTargetParticipatesInSignature){
    LegacyRuleIR a=stateRule("a",0,1.0),b=a;
    a.predicates[0].target=0; b.predicates[0].target=1;
    EXPECT_NE(LegacyLowerer::matcherSignature(a),LegacyLowerer::matcherSignature(b));
}

TEST(LegacyLowerer_BindTransformCompilesBothEndpoints){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("bind",0,1.0); r.transforms.clear();
    LegacyTransformIR t=trans(LEGACY_TRANSFORM_BIND,0,1,0,FeatureId(2)); t.target=0; t.other=1;
    r.transforms.push_back(t); m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    const TransformInstruction& x=out.executable.transforms().at(TransformProgramId(0)).code()[0];
    EXPECT_EQ(x.opcode,(std::uint16_t)TRANSFORM_BIND); EXPECT_EQ(x.target,0u); EXPECT_EQ(x.other,1u);
    EXPECT_EQ(x.a,0u); EXPECT_EQ(x.b,1u); EXPECT_EQ(x.feature,FeatureId(2));
}

TEST(LegacyLowerer_UnbindTransformCompilesPartnerSite){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("unbind",0,1.0); r.transforms.clear();
    LegacyTransformIR t=trans(LEGACY_TRANSFORM_UNBIND,1,0,0,FeatureId(2)); t.target=0;
    r.transforms.push_back(t); m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    const TransformInstruction& x=out.executable.transforms().at(TransformProgramId(0)).code()[0];
    EXPECT_EQ(x.opcode,(std::uint16_t)TRANSFORM_UNBIND); EXPECT_EQ(x.a,1u); EXPECT_EQ(x.b,0u);
}

TEST(LegacyLowerer_CreateDeleteTransformsCompile){
    LegacyModelIR m=baseLegacy();
    LegacyRuleIR r=stateRule("life",0,1.0); r.transforms.clear();
    LegacyTransformIR c=trans(LEGACY_TRANSFORM_CREATE_MOLECULE,0); c.target=1;
    LegacyTransformIR d=trans(LEGACY_TRANSFORM_DELETE_MOLECULE); d.target=0;
    r.transforms.push_back(c); r.transforms.push_back(d); m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    const std::vector<TransformInstruction>& code=out.executable.transforms().at(TransformProgramId(0)).code();
    EXPECT_EQ(code[0].opcode,(std::uint16_t)TRANSFORM_CREATE_MOLECULE); EXPECT_EQ(code[0].target,1u);
    EXPECT_EQ(code[1].opcode,(std::uint16_t)TRANSFORM_DELETE_MOLECULE); EXPECT_EQ(code[1].target,0u);
}

TEST(LegacyLowerer_BindIsNoLongerRejectedAsGenericTopologyChange){
    LegacyModelIR m=baseLegacy(); LegacyRuleIR r=stateRule("bind",0,1.0); r.transforms.clear();
    LegacyTransformIR t=trans(LEGACY_TRANSFORM_BIND,0,1); t.target=0; t.other=1; r.transforms.push_back(t);
    r.changes_topology=true; r.topology_change_is_local=true; m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    EXPECT_TRUE(out.rules[0].supported());
}

TEST(LegacyLowerer_NonlocalTopologyStillFallsBack){
    LegacyModelIR m=baseLegacy(); LegacyRuleIR r=stateRule("delSpecies",0,1.0);
    r.changes_topology=true; r.topology_change_is_local=false; m.rules.push_back(r);
    EXPECT_EQ(LegacyLowerer::lower(m).rules[0].reason,LOWERING_TOPOLOGY_CHANGE);
}
