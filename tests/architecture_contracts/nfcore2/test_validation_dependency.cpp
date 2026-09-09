#include "test_harness.hh"
#include "legacy_bridge.hh"
#include "engine.hh"
#include "model_image.hh"
#include <limits>
#include <sstream>
using namespace NFcore2;

namespace {
LegacyPredicateIR statePred(unsigned word,std::uint64_t mask,std::uint64_t value){
    LegacyPredicateIR p;
    p.kind=LEGACY_PRED_STATE_MASK;
    p.a=word;
    p.mask=mask;
    p.value=value;
    return p;
}
LegacyTransformIR stateWrite(unsigned word,std::uint64_t value,FeatureId feature){
    LegacyTransformIR t;
    t.kind=LEGACY_TRANSFORM_SET_STATE_WORD;
    t.a=word;
    t.value=static_cast<std::int64_t>(value);
    t.changed_feature=feature;
    return t;
}
LegacyModelIR dependencyModel(){
    LegacyModelIR m;
    MoleculeTypeDescriptor d;
    d.name="A";
    d.state_words=2;
    d.bond_slots=2;
    m.molecule_types.push_back(d);
    m.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,0));
    m.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,1));
    m.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_BOND,0,0));
    m.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_BOND,0,1));
    m.features.push_back(FeatureDescriptor(FEATURE_POPULATION,0,0));
    m.features.push_back(FeatureDescriptor(FEATURE_POPULATION,1,0));
    return m;
}
LegacyRuleIR ruleReadingWord(const std::string& name,unsigned word,FeatureId writeFeature){
    LegacyRuleIR r;
    r.name=name;
    r.rate=1.0;
    r.predicates.push_back(statePred(word,1,0));
    r.transforms.push_back(stateWrite(word,1,writeFeature));
    return r;
}
std::vector<MatcherId> dependents(const CompiledModel& m,FeatureId f){
    std::pair<const MatcherId*,const MatcherId*> p=m.dependencies().dependents(f);
    if(!p.first)return std::vector<MatcherId>();
    return std::vector<MatcherId>(p.first,p.second);
}
}

TEST(DependencyPrecision_WriterDoesNotBecomeDependencyMerelyBecauseItWritesFeature){
    LegacyModelIR m=dependencyModel();
    LegacyRuleIR writer=ruleReadingWord("writer",0,FeatureId(1));
    m.rules.push_back(writer);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    std::vector<MatcherId> d=dependents(out.executable.metadata(),FeatureId(1));
    EXPECT_TRUE(d.empty());
}

TEST(DependencyPrecision_ReaderOfFeatureIsDependency){
    LegacyModelIR m=dependencyModel();
    LegacyRuleIR reader=ruleReadingWord("reader",1,FeatureId(0));
    m.rules.push_back(reader);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    std::vector<MatcherId> d=dependents(out.executable.metadata(),FeatureId(1));
    EXPECT_EQ(d.size(),1u);
    EXPECT_EQ(d[0],out.executable.metadata().ruleFamilies()[0].matcher);
}

TEST(DependencyPrecision_DifferentStateWordsDoNotCrossInvalidate){
    LegacyModelIR m=dependencyModel();
    m.rules.push_back(ruleReadingWord("word0",0,FeatureId(0)));
    m.rules.push_back(ruleReadingWord("word1",1,FeatureId(1)));
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    std::vector<MatcherId> d0=dependents(out.executable.metadata(),FeatureId(0));
    std::vector<MatcherId> d1=dependents(out.executable.metadata(),FeatureId(1));
    EXPECT_EQ(d0.size(),1u);
    EXPECT_EQ(d1.size(),1u);
    EXPECT_NE(d0[0],d1[0]);
}

TEST(DependencyPrecision_PopulationOwnerDistinguishesPopulationIds){
    LegacyModelIR m=dependencyModel();
    LegacyRuleIR r0;
    r0.name="p0";r0.rate=1;
    LegacyPredicateIR p0;p0.kind=LEGACY_PRED_POPULATION_AT_LEAST;p0.a=0;p0.value=1;
    r0.predicates.push_back(p0);
    r0.transforms.push_back(stateWrite(0,1,FeatureId(0)));
    LegacyRuleIR r1=r0;
    r1.name="p1";
    r1.predicates[0].a=1;
    m.rules.push_back(r0);
    m.rules.push_back(r1);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    std::vector<MatcherId> a=dependents(out.executable.metadata(),FeatureId(4));
    std::vector<MatcherId> b=dependents(out.executable.metadata(),FeatureId(5));
    EXPECT_EQ(a.size(),1u);
    EXPECT_EQ(b.size(),1u);
    EXPECT_NE(a[0],b[0]);
}

TEST(DependencyPrecision_BondSlotsDoNotCrossInvalidate){
    LegacyModelIR m=dependencyModel();
    LegacyRuleIR r0;
    r0.name="b0";r0.rate=1;
    LegacyPredicateIR p0;p0.kind=LEGACY_PRED_BOND_PRESENT;p0.a=0;
    r0.predicates.push_back(p0);
    r0.transforms.push_back(stateWrite(0,1,FeatureId(0)));
    LegacyRuleIR r1=r0;
    r1.name="b1";
    r1.predicates[0].a=1;
    m.rules.push_back(r0);
    m.rules.push_back(r1);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    std::vector<MatcherId> a=dependents(out.executable.metadata(),FeatureId(2));
    std::vector<MatcherId> b=dependents(out.executable.metadata(),FeatureId(3));
    EXPECT_EQ(a.size(),1u);
    EXPECT_EQ(b.size(),1u);
    EXPECT_NE(a[0],b[0]);
}

TEST(DependencyPrecision_ExpressionObservableTracksStateAndCompartment){
    LegacyModelIR m=dependencyModel();
    m.features.push_back(FeatureDescriptor(FEATURE_MOLECULE_COMPARTMENT,0,0));
    LegacyRuleIR r;
    r.name="expression"; r.rate=1.0;
    r.rate_law.kind=LEGACY_RATE_EXPRESSION;
    r.rate_law.expression="active";
    RateExpressionBinding binding;
    binding.kind=RATE_EXPRESSION_GLOBAL_MOLECULE_COUNT;
    binding.name="active"; binding.molecule_type=0;
    binding.state_component=1; binding.state_value=1;
    binding.compartment=7;
    r.rate_law.expression_bindings.push_back(binding);
    m.rules.push_back(r);
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    std::vector<MatcherId> state=dependents(out.executable.metadata(),FeatureId(1));
    std::vector<MatcherId> compartment=dependents(out.executable.metadata(),FeatureId(6));
    EXPECT_EQ(state.size(),1u);
    EXPECT_EQ(compartment.size(),1u);
    EXPECT_EQ(state[0],compartment[0]);
}

TEST(DependencyPrecision_DuplicateRulesDoNotDuplicateMatcherDependencyEntries){
    LegacyModelIR m=dependencyModel();
    for(unsigned i=0;i<100;++i){
        LegacyRuleIR r=ruleReadingWord("dup",0,FeatureId(1));
        r.coordinate=i;
        m.rules.push_back(r);
    }
    LegacyLoweringResult out=LegacyLowerer::lower(m);
    std::vector<MatcherId> d=dependents(out.executable.metadata(),FeatureId(0));
    EXPECT_EQ(d.size(),1u);
}

TEST(RuleCompiler_RejectsNegativeRate){
    RuleInstanceIR r;
    r.name="bad";
    r.matcher_signature="m";
    r.transform_signature="t";
    r.matcher=MatcherId(0);
    r.transform=TransformProgramId(0);
    r.rate=-1.0;
    std::vector<RuleInstanceIR> in(1,r);
    EXPECT_THROW(RuleFamilyCompiler::compile(in),std::invalid_argument);
}

TEST(RuleCompiler_RejectsNaNRate){
    RuleInstanceIR r;
    r.name="bad";
    r.matcher_signature="m";
    r.transform_signature="t";
    r.matcher=MatcherId(0);
    r.transform=TransformProgramId(0);
    r.rate=std::numeric_limits<double>::quiet_NaN();
    std::vector<RuleInstanceIR> in(1,r);
    EXPECT_THROW(RuleFamilyCompiler::compile(in),std::invalid_argument);
}

TEST(RuleCompiler_RejectsInfiniteRate){
    RuleInstanceIR r;
    r.name="bad";
    r.matcher_signature="m";
    r.transform_signature="t";
    r.matcher=MatcherId(0);
    r.transform=TransformProgramId(0);
    r.rate=std::numeric_limits<double>::infinity();
    std::vector<RuleInstanceIR> in(1,r);
    EXPECT_THROW(RuleFamilyCompiler::compile(in),std::invalid_argument);
}

TEST(RuleCompiler_ZeroRateIsValid){
    RuleInstanceIR r;
    r.name="zero";
    r.matcher_signature="m";
    r.transform_signature="t";
    r.matcher=MatcherId(0);
    r.transform=TransformProgramId(0);
    r.rate=0.0;
    std::vector<RuleInstanceIR> in(1,r);
    RuleFamilyCompilation out=RuleFamilyCompiler::compile(in);
    EXPECT_EQ(out.families[0].members[0].rate,0.0);
}

TEST(LegacyLowerer_RejectsNegativeRateAtSemanticBoundary){
    LegacyModelIR m=dependencyModel();
    LegacyRuleIR r=ruleReadingWord("bad",0,FeatureId(0));
    r.rate=-0.1;
    m.rules.push_back(r);
    EXPECT_THROW(LegacyLowerer::lower(m),std::invalid_argument);
}

TEST(LegacyLowerer_RejectsNaNRateAtSemanticBoundary){
    LegacyModelIR m=dependencyModel();
    LegacyRuleIR r=ruleReadingWord("bad",0,FeatureId(0));
    r.rate=std::numeric_limits<double>::quiet_NaN();
    m.rules.push_back(r);
    EXPECT_THROW(LegacyLowerer::lower(m),std::invalid_argument);
}

TEST(Matcher_InvalidOpcodeThrowsRatherThanSilentlyMatching){
    CompiledModel m;
    MoleculeTypeDescriptor d;d.name="A";m.addMoleculeType(d);
    SimulationState s(m);
    ScaffoldStore sc;
    MatcherProgram p;
    p.add(MatchInstruction(999));
    MatchContext c;
    EXPECT_THROW(p.evaluate(s,sc,c),std::logic_error);
}

TEST(Transform_InvalidOpcodeThrowsRatherThanSilentlySkipping){
    CompiledModel m;
    MoleculeTypeDescriptor d;d.name="A";m.addMoleculeType(d);
    SimulationState s(m);
    ScaffoldStore sc;
    TransformProgram p;
    p.add(TransformInstruction(999));
    MatchContext c;
    FeatureDelta dlt;
    EXPECT_THROW(p.execute(s,sc,c,dlt),std::logic_error);
}

TEST(CompiledModel_RejectsRuleFamilyWithInvalidMatcherId){
    CompiledModel m;
    RuleFamilyDescriptor f;
    f.name="bad";
    f.matcher=MatcherId();
    f.transform=TransformProgramId(0);
    EXPECT_THROW(m.addRuleFamily(f),std::invalid_argument);
}

TEST(CompiledModel_RejectsRuleFamilyWithInvalidTransformId){
    CompiledModel m;
    RuleFamilyDescriptor f;
    f.name="bad";
    f.matcher=MatcherId(0);
    f.transform=TransformProgramId();
    EXPECT_THROW(m.addRuleFamily(f),std::invalid_argument);
}

TEST(CompiledModel_RejectsRuleFamilyMemberWithNegativeRate){
    CompiledModel m;
    RuleFamilyDescriptor f;
    f.name="bad";
    f.matcher=MatcherId(0);
    f.transform=TransformProgramId(0);
    RuleMember r;r.rate=-1;
    f.members.push_back(r);
    EXPECT_THROW(m.addRuleFamily(f),std::invalid_argument);
}

TEST(CompiledModel_RejectsRuleFamilyMemberWithNaNRate){
    CompiledModel m;
    RuleFamilyDescriptor f;
    f.name="bad";
    f.matcher=MatcherId(0);
    f.transform=TransformProgramId(0);
    RuleMember r;r.rate=std::numeric_limits<double>::quiet_NaN();
    f.members.push_back(r);
    EXPECT_THROW(m.addRuleFamily(f),std::invalid_argument);
}

TEST(Engine_FireInvalidFamilyThrowsBoundsError){
    ExecutableModel e;
    Engine engine(e);
    MatchContext c;
    FeatureDelta d;
    EXPECT_THROW(engine.fire(RuleFamilyId(100),0,c,d),std::out_of_range);
}

TEST(Scheduler_RateTimesMultiplicityOverflowIsRejected){
    CompiledModel m;
    RuleFamilyDescriptor f;
    f.name="huge";
    f.matcher=MatcherId(0);
    f.transform=TransformProgramId(0);
    RuleMember r;r.rate=std::numeric_limits<double>::max();
    f.members.push_back(r);
    m.addRuleFamily(f);
    HierarchicalScheduler s(m);
    EXPECT_THROW(s.setMemberMultiplicity(RuleFamilyId(0),0,2.0),std::invalid_argument);
}

TEST(EngineValidation_RejectsFamilyMatcherOutsideRegistry){
    ExecutableModel e;
    RuleFamilyDescriptor f;
    f.name="bad_matcher_ref";
    f.matcher=MatcherId(7);
    f.transform=TransformProgramId(0);
    RuleMember r;r.rate=1;
    f.members.push_back(r);
    e.buildMetadata().addRuleFamily(f);
    TransformProgram tp;tp.add(TransformInstruction(TRANSFORM_END));
    e.buildTransforms().add(tp);
    EXPECT_THROW(Engine(e),std::invalid_argument);
}

TEST(EngineValidation_RejectsFamilyTransformOutsideRegistry){
    ExecutableModel e;
    MatcherProgram mp;mp.add(MatchInstruction(MATCH_END));
    e.buildMatchers().add(mp);
    RuleFamilyDescriptor f;
    f.name="bad_transform_ref";
    f.matcher=MatcherId(0);
    f.transform=TransformProgramId(9);
    RuleMember r;r.rate=1;
    f.members.push_back(r);
    e.buildMetadata().addRuleFamily(f);
    EXPECT_THROW(Engine(e),std::invalid_argument);
}

TEST(EngineValidation_RejectsDependencyMatcherOutsideRegistry){
    ExecutableModel e;
    e.buildMetadata().addFeature(FeatureDescriptor(FEATURE_TIME,0,0));
    std::vector<std::vector<MatcherId> > deps(1);
    deps[0].push_back(MatcherId(12));
    e.buildMetadata().setFeatureDependencies(deps);
    EXPECT_THROW(Engine(e),std::invalid_argument);
}

TEST(EngineValidation_RejectsInvalidMatcherOpcodeBeforeAnyFire){
    ExecutableModel e;
    MatcherProgram mp;
    mp.add(MatchInstruction(777));
    MatcherId mid=e.buildMatchers().add(mp);
    TransformProgram tp;tp.add(TransformInstruction(TRANSFORM_END));
    TransformProgramId tid=e.buildTransforms().add(tp);
    RuleFamilyDescriptor f;
    f.name="bad_matcher_opcode";f.matcher=mid;f.transform=tid;
    RuleMember r;r.rate=1;f.members.push_back(r);
    e.buildMetadata().addRuleFamily(f);
    EXPECT_THROW(Engine(e),std::invalid_argument);
}

TEST(EngineValidation_RejectsInvalidTransformOpcodeBeforeAnyFire){
    ExecutableModel e;
    MatcherProgram mp;mp.add(MatchInstruction(MATCH_END));
    MatcherId mid=e.buildMatchers().add(mp);
    TransformProgram tp;
    tp.add(TransformInstruction(888));
    TransformProgramId tid=e.buildTransforms().add(tp);
    RuleFamilyDescriptor f;
    f.name="bad_transform_opcode";f.matcher=mid;f.transform=tid;
    RuleMember r;r.rate=1;f.members.push_back(r);
    e.buildMetadata().addRuleFamily(f);
    EXPECT_THROW(Engine(e),std::invalid_argument);
}

TEST(EngineValidation_ValidEmptyExecutableIsAccepted){
    ExecutableModel e;
    EXPECT_NO_THROW(Engine(e));
}

TEST(EngineValidation_ValidReferencedProgramsAreAccepted){
    ExecutableModel e;
    MatcherProgram mp;mp.add(MatchInstruction(MATCH_END));
    MatcherId mid=e.buildMatchers().add(mp);
    TransformProgram tp;tp.add(TransformInstruction(TRANSFORM_END));
    TransformProgramId tid=e.buildTransforms().add(tp);
    RuleFamilyDescriptor f;
    f.name="ok";f.matcher=mid;f.transform=tid;
    RuleMember r;r.rate=1;f.members.push_back(r);
    e.buildMetadata().addRuleFamily(f);
    EXPECT_NO_THROW(Engine(e));
}

TEST(EngineValidation_DependencyAtLastValidMatcherIsAccepted){
    ExecutableModel e;
    MatcherProgram a;a.add(MatchInstruction(MATCH_END));
    MatcherProgram b;b.add(MatchInstruction(MATCH_END));
    e.buildMatchers().add(a);
    e.buildMatchers().add(b);
    e.buildMetadata().addFeature(FeatureDescriptor(FEATURE_TIME,0,0));
    std::vector<std::vector<MatcherId> > deps(1);
    deps[0].push_back(MatcherId(1));
    e.buildMetadata().setFeatureDependencies(deps);
    EXPECT_NO_THROW(Engine(e));
}
