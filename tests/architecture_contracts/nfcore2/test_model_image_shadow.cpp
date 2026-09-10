#include "test_harness.hh"
#include "model_image.hh"
#include "shadow.hh"
#include <cstdio>
#include <limits>
#include <sstream>
using namespace NFcore2;

namespace {
ExecutableModel imageModel(){
    ExecutableModel e;
    MoleculeTypeDescriptor a;
    a.name="Alpha";
    a.state_words=2;
    a.bond_slots=3;
    e.buildMetadata().addMoleculeType(a);
    MoleculeTypeDescriptor b;
    b.name="Beta";
    b.state_words=1;
    b.bond_slots=1;
    e.buildMetadata().addMoleculeType(b);

    FeatureId f0=e.buildMetadata().addFeature(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,0));
    FeatureId f1=e.buildMetadata().addFeature(FeatureDescriptor(FEATURE_POPULATION,0,0));

    MatcherProgram mp;
    MatchInstruction mx(MATCH_STATE_MASK);
    mx.target=0;
    mx.a=0;
    mx.mask=3;
    mx.value=1;
    mp.add(mx);
    mp.add(MatchInstruction(MATCH_END));
    MatcherId mid=e.buildMatchers().add(mp);

    TransformProgram tp;
    TransformInstruction tx(TRANSFORM_SET_STATE_WORD);
    tx.target=0;
    tx.a=1;
    tx.value=17;
    tx.feature=f0;
    tp.add(tx);
    tp.add(TransformInstruction(TRANSFORM_END));
    TransformProgramId tid=e.buildTransforms().add(tp);

    RuleFamilyDescriptor family;
    family.name="family";
    family.matcher=mid;
    family.transform=tid;
    family.uniform_rate=false;
    RuleMember r0;r0.rate=1.25;r0.parameter_index=4;r0.coordinate=10;
    RuleMember r1;r1.rate=2.50;r1.parameter_index=5;r1.coordinate=11;
    family.members.push_back(r0);
    family.members.push_back(r1);
    e.buildMetadata().addRuleFamily(family);

    std::vector<std::vector<MatcherId> > deps(2);
    deps[0].push_back(mid);
    deps[1].push_back(mid);
    e.buildMetadata().setFeatureDependencies(deps);
    (void)f1;
    return e;
}
std::string writeBytes(const ExecutableModel& e){ std::ostringstream os(std::ios::binary);ModelImage::write(e,os);return os.str(); }
ExecutableModel readBytes(const std::string& s){std::istringstream is(s,std::ios::binary);return ModelImage::read(is);}
void overwriteU32(std::string& s,std::size_t off,std::uint32_t v){ for(unsigned i=0;i<4;++i)s[off+i]=static_cast<char>((v>>(8*i))&0xffu); }
}

TEST(ModelImage_RoundTripMoleculeTypes){
    ExecutableModel a=imageModel();
    ExecutableModel b=readBytes(writeBytes(a));
    EXPECT_EQ(b.metadata().moleculeTypes().size(),2u);
    EXPECT_EQ(b.metadata().moleculeTypes()[0].name,std::string("Alpha"));
    EXPECT_EQ(b.metadata().moleculeTypes()[0].state_words,2u);
    EXPECT_EQ(b.metadata().moleculeTypes()[0].bond_slots,3u);
    EXPECT_EQ(b.metadata().moleculeTypes()[1].name,std::string("Beta"));
}

TEST(ModelImage_RoundTripFeatures){
    ExecutableModel a=imageModel();
    ExecutableModel b=readBytes(writeBytes(a));
    EXPECT_EQ(b.metadata().features().size(),2u);
    EXPECT_EQ(b.metadata().features()[0].kind,FEATURE_MOLECULE_STATE);
    EXPECT_EQ(b.metadata().features()[0].owner,0u);
    EXPECT_EQ(b.metadata().features()[0].index,0u);
    EXPECT_EQ(b.metadata().features()[1].kind,FEATURE_POPULATION);
}

TEST(ModelImage_RoundTripMatcherBytecode){
    ExecutableModel a=imageModel();
    ExecutableModel b=readBytes(writeBytes(a));
    EXPECT_EQ(b.matchers().size(),1u);
    const std::vector<MatchInstruction>& c=b.matchers().at(MatcherId(0)).code();
    EXPECT_EQ(c.size(),2u);
    EXPECT_EQ(c[0].opcode,MATCH_STATE_MASK);
    EXPECT_EQ(c[0].target,0u);
    EXPECT_EQ(c[0].a,0u);
    EXPECT_EQ(c[0].mask,3ull);
    EXPECT_EQ(c[0].value,1ull);
    EXPECT_EQ(c[1].opcode,MATCH_END);
}

TEST(ModelImage_RoundTripSymmetricGraphConstraints){
    ExecutableModel e;
    MoleculeTypeDescriptor a; a.name="A"; a.state_words=2; a.bond_slots=2;
    MoleculeTypeDescriptor b; b.name="B"; b.state_words=1; b.bond_slots=1;
    e.buildMetadata().addMoleculeType(a); e.buildMetadata().addMoleculeType(b);
    MatcherProgram matcher;
    GraphPattern graph;
    GraphNodePattern left; left.molecule_type=0; left.anchor_reactant=0;
    left.state_constraints={{0u,1},{1u,2}};
    left.excluded_states={{0u,3}};
    SymmetricConstraintPattern bound; bound.components={0,1}; bound.bond_state=1; bound.partner_node=1; bound.partner_components={0};
    SymmetricConstraintPattern free; free.components={0,1}; free.bond_state=0;
    left.symmetric_constraints={bound,free};
    GraphNodePattern right; right.molecule_type=1; right.anchor_reactant=1;
    graph.nodes={left,right}; matcher.addGraphPattern(graph); matcher.add(MatchInstruction(MATCH_END));
    e.buildMatchers().add(matcher);
    ExecutableModel roundtrip=readBytes(writeBytes(e));
    const GraphPattern& restored=roundtrip.matchers().at(MatcherId(0)).graphPatterns()[0];
    EXPECT_EQ(restored.nodes.size(),2u);
    EXPECT_EQ(restored.nodes[0].symmetric_constraints.size(),2u);
    EXPECT_EQ(restored.nodes[0].symmetric_constraints[0].components.size(),2u);
    EXPECT_EQ(restored.nodes[0].symmetric_constraints[0].partner_node,1u);
    EXPECT_EQ(restored.nodes[0].symmetric_constraints[0].partner_components[0],0u);
    EXPECT_EQ(restored.nodes[0].symmetric_constraints[1].bond_state,0);
    EXPECT_EQ(restored.nodes[0].state_constraints.size(),2u);
    EXPECT_EQ(restored.nodes[0].state_constraints[1].first,1u);
    EXPECT_EQ(restored.nodes[0].state_constraints[1].second,2);
    EXPECT_EQ(restored.nodes[0].excluded_states.size(),1u);
    EXPECT_EQ(restored.nodes[0].excluded_states[0].second,3);
}

TEST(ModelImage_RoundTripGraphConnectedToConstraints){
    ExecutableModel e;
    MoleculeTypeDescriptor a; a.name="A"; a.bond_slots=2;
    MoleculeTypeDescriptor b; b.name="B"; b.bond_slots=1;
    e.buildMetadata().addMoleculeType(a); e.buildMetadata().addMoleculeType(b);
    MatcherProgram matcher;
    GraphPattern graph;
    GraphNodePattern left; left.molecule_type=0; left.anchor_reactant=0;
    GraphNodePattern right; right.molecule_type=1;
    graph.nodes={left,right}; graph.connected_to.push_back(GraphConnectivityPattern(0,1));
    matcher.addGraphPattern(graph); matcher.add(MatchInstruction(MATCH_END));
    e.buildMatchers().add(matcher);
    ExecutableModel roundtrip=readBytes(writeBytes(e));
    const GraphPattern& restored=roundtrip.matchers().at(MatcherId(0)).graphPatterns()[0];
    EXPECT_EQ(restored.connected_to.size(),1u);
    EXPECT_EQ(restored.connected_to[0].first_node,0u);
    EXPECT_EQ(restored.connected_to[0].second_node,1u);
}

TEST(ModelImage_RoundTripTransformBytecode){
    ExecutableModel a=imageModel();
    ExecutableModel b=readBytes(writeBytes(a));
    EXPECT_EQ(b.transforms().size(),1u);
    const std::vector<TransformInstruction>& c=b.transforms().at(TransformProgramId(0)).code();
    EXPECT_EQ(c.size(),2u);
    EXPECT_EQ(c[0].opcode,TRANSFORM_SET_STATE_WORD);
    EXPECT_EQ(c[0].a,1u);
    EXPECT_EQ(c[0].value,17ull);
    EXPECT_EQ(c[0].feature,FeatureId(0));
}

TEST(ModelImage_RoundTripRuleFamiliesAndMembers){
    ExecutableModel a=imageModel();
    ExecutableModel b=readBytes(writeBytes(a));
    EXPECT_EQ(b.metadata().ruleFamilies().size(),1u);
    const RuleFamilyDescriptor& f=b.metadata().ruleFamilies()[0];
    EXPECT_EQ(f.name,std::string("family"));
    EXPECT_EQ(f.matcher,MatcherId(0));
    EXPECT_EQ(f.transform,TransformProgramId(0));
    EXPECT_FALSE(f.uniform_rate);
    EXPECT_EQ(f.members.size(),2u);
    EXPECT_EQ(f.members[0].rate,1.25);
    EXPECT_EQ(f.members[0].parameter_index,4u);
    EXPECT_EQ(f.members[1].coordinate,11u);
}

TEST(ModelImage_RoundTripRateExpressionFunctions){
    ExecutableModel e;
    MoleculeTypeDescriptor type; type.name="X"; e.buildMetadata().addMoleculeType(type);
    MatcherProgram matcher; matcher.add(MatchInstruction(MATCH_END));
    const MatcherId matcherId=e.buildMatchers().add(matcher);
    TransformProgram transform; transform.add(TransformInstruction(TRANSFORM_END));
    const TransformProgramId transformId=e.buildTransforms().add(transform);
    RuleFamilyDescriptor family; family.matcher=matcherId; family.transform=transformId;
    RuleMember member; member.rate=1.0;
    member.rate_law.kind=LEGACY_RATE_EXPRESSION;
    member.rate_law.expression="f(x)";
    member.rate_law.expression_functions.push_back(
        RateExpressionFunction{"f", "k*x", {"x"}});
    RateExpressionBinding constant;
    constant.kind=RATE_EXPRESSION_CONSTANT;
    constant.name="k";
    constant.value=2.0;
    member.rate_law.expression_bindings.push_back(constant);
    family.members.push_back(member);
    e.buildMetadata().addRuleFamily(family);
    ExecutableModel b=readBytes(writeBytes(e));
    const RuleMember& restored=b.metadata().ruleFamilies()[0].members[0];
    EXPECT_EQ(restored.rate_law.expression,std::string("f(x)"));
    EXPECT_EQ(restored.rate_law.expression_functions.size(),1u);
    EXPECT_EQ(restored.rate_law.expression_functions[0].name,std::string("f"));
    EXPECT_EQ(restored.rate_law.expression_functions[0].arguments.size(),1u);
    EXPECT_EQ(restored.rate_law.expression_functions[0].arguments[0],std::string("x"));
}

TEST(ModelImage_RoundTripDependencyIndex){
    ExecutableModel a=imageModel();
    ExecutableModel b=readBytes(writeBytes(a));
    std::pair<const MatcherId*,const MatcherId*> d0=b.metadata().dependencies().dependents(FeatureId(0));
    std::pair<const MatcherId*,const MatcherId*> d1=b.metadata().dependencies().dependents(FeatureId(1));
    EXPECT_EQ(static_cast<std::size_t>(d0.second-d0.first),1u);
    EXPECT_EQ(static_cast<std::size_t>(d1.second-d1.first),1u);
    EXPECT_EQ(d0.first[0],MatcherId(0));
    EXPECT_EQ(d1.first[0],MatcherId(0));
}

TEST(ModelImage_RoundTripFamiliesForMatcherReverseIndex){
    ExecutableModel a=imageModel();
    ExecutableModel b=readBytes(writeBytes(a));
    const std::vector<RuleFamilyId>& fs=b.metadata().familiesForMatcher(MatcherId(0));
    EXPECT_EQ(fs.size(),1u);
    EXPECT_EQ(fs[0],RuleFamilyId(0));
}

TEST(ModelImage_RoundTripIsByteStable){
    ExecutableModel a=imageModel();
    std::string bytes1=writeBytes(a);
    ExecutableModel b=readBytes(bytes1);
    std::string bytes2=writeBytes(b);
    EXPECT_EQ(bytes1,bytes2);
}

TEST(ModelImage_RoundTripExecutableSemanticsMatch){
    ExecutableModel a=imageModel();
    ExecutableModel b=readBytes(writeBytes(a));
    SimulationState sa(a.metadata()),sb(b.metadata());
    ScaffoldStore sca,scb;
    MoleculeHandle ha=sa.molecules(MoleculeTypeId(0)).create();
    MoleculeHandle hb=sb.molecules(MoleculeTypeId(0)).create();
    sa.molecules(MoleculeTypeId(0)).setStateWord(ha,0,1);
    sb.molecules(MoleculeTypeId(0)).setStateWord(hb,0,1);
    MatchContext ca,cb;
    ca.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),ha));
    cb.setMoleculeAt(0,MoleculeRef(MoleculeTypeId(0),hb));
    EXPECT_EQ(a.matchers().at(MatcherId(0)).evaluate(sa,sca,ca),b.matchers().at(MatcherId(0)).evaluate(sb,scb,cb));
    FeatureDelta da,db;
    a.transforms().at(TransformProgramId(0)).execute(sa,sca,ca,da);
    b.transforms().at(TransformProgramId(0)).execute(sb,scb,cb,db);
    EXPECT_EQ(sa.molecules(MoleculeTypeId(0)).stateWord(ha,1),sb.molecules(MoleculeTypeId(0)).stateWord(hb,1));
}

TEST(ModelImage_RejectsWrongMagic){
    std::string bytes=writeBytes(imageModel());
    bytes[0]='X';
    EXPECT_THROW(readBytes(bytes),std::runtime_error);
}

TEST(ModelImage_RejectsWrongVersion){
    std::string bytes=writeBytes(imageModel());
    overwriteU32(bytes,8,999);
    EXPECT_THROW(readBytes(bytes),std::runtime_error);
}

TEST(ModelImage_RejectsEmptyInput){
    EXPECT_THROW(readBytes(std::string()),std::runtime_error);
}

TEST(ModelImage_RejectsEveryTruncationPointNearHeader){
    std::string bytes=writeBytes(imageModel());
    for(std::size_t n=0;n<32 && n<bytes.size();++n){
        EXPECT_THROW(readBytes(bytes.substr(0,n)),std::runtime_error);
    }
}

TEST(ModelImage_RejectsEveryTruncationPointInTail){
    std::string bytes=writeBytes(imageModel());
    std::size_t start=bytes.size()>64?bytes.size()-64:0;
    for(std::size_t n=start;n<bytes.size();++n){
        EXPECT_THROW(readBytes(bytes.substr(0,n)),std::runtime_error);
    }
}

TEST(ModelImage_FileRoundTripWorks){
    const std::string path="nfcore2_model_image_test.bin";
    ExecutableModel a=imageModel();
    ModelImage::writeFile(a,path);
    ExecutableModel b=ModelImage::readFile(path);
    EXPECT_EQ(writeBytes(a),writeBytes(b));
    std::remove(path.c_str());
}

TEST(ModelImage_ReadFileMissingPathThrows){
    EXPECT_THROW(ModelImage::readFile("definitely_missing_nfcore2_model_image.bin"),std::runtime_error);
}

TEST(ModelImage_WriteFileInvalidDirectoryThrows){
    EXPECT_THROW(ModelImage::writeFile(imageModel(),"/definitely/missing/path/model.nfc"),std::runtime_error);
}

TEST(ModelImage_EmptyExecutableRoundTrips){
    ExecutableModel a;
    a.buildMetadata().setFeatureDependencies(std::vector<std::vector<MatcherId> >());
    ExecutableModel b=readBytes(writeBytes(a));
    EXPECT_TRUE(b.metadata().moleculeTypes().empty());
    EXPECT_TRUE(b.metadata().features().empty());
    EXPECT_TRUE(b.metadata().ruleFamilies().empty());
    EXPECT_EQ(b.matchers().size(),0u);
    EXPECT_EQ(b.transforms().size(),0u);
}

TEST(ModelImage_LongNamesRoundTrip){
    ExecutableModel e;
    MoleculeTypeDescriptor d;
    d.name=std::string(10000,'x');
    e.buildMetadata().addMoleculeType(d);
    e.buildMetadata().setFeatureDependencies(std::vector<std::vector<MatcherId> >());
    ExecutableModel b=readBytes(writeBytes(e));
    EXPECT_EQ(b.metadata().moleculeTypes()[0].name,d.name);
}

TEST(SemanticHasher_DefaultSeedIsStable){
    SemanticHasher a,b;
    EXPECT_EQ(a.value(),b.value());
    EXPECT_EQ(a.value(),1469598103934665603ULL);
}

TEST(SemanticHasher_SameIntegerSequenceProducesSameHash){
    SemanticHasher a,b;
    for(std::uint64_t i=0;i<100;++i){a.addU64(i);b.addU64(i);}
    EXPECT_EQ(a.value(),b.value());
}

TEST(SemanticHasher_DifferentIntegerOrderChangesHash){
    SemanticHasher a,b;
    a.addU64(1);a.addU64(2);
    b.addU64(2);b.addU64(1);
    EXPECT_NE(a.value(),b.value());
}

TEST(SemanticHasher_SignedAndUnsignedBitPatternAgree){
    SemanticHasher a,b;
    a.addI64(-1);
    b.addU64(std::numeric_limits<std::uint64_t>::max());
    EXPECT_EQ(a.value(),b.value());
}

TEST(SemanticHasher_StringBoundaryIsUnambiguous){
    SemanticHasher a,b;
    a.addString("ab");a.addString("c");
    b.addString("a");b.addString("bc");
    EXPECT_NE(a.value(),b.value());
}

TEST(SemanticHasher_EmptyStringStillAffectsHash){
    SemanticHasher a,b;
    a.addString("");
    EXPECT_NE(a.value(),b.value());
}

TEST(SemanticHasher_DeterministicAcrossRepeatedRuns){
    std::uint64_t first=0;
    for(unsigned run=0;run<100;++run){
        SemanticHasher h;
        h.addString("molecule:A");
        h.addU64(17);
        h.addI64(-8);
        h.addString("state");
        if(run==0)first=h.value();
        EXPECT_EQ(h.value(),first);
    }
}

TEST(ShadowComparator_IdenticalEmptyStatesMatch){
    ShadowState a,b;
    ShadowMismatch m=ShadowComparator::compareState(a,b);
    EXPECT_FALSE(m.mismatch);
    EXPECT_TRUE(m.field.empty());
}

TEST(ShadowComparator_TimeMismatchIsReportedFirst){
    ShadowState a,b;
    b.time=1;
    b.populations.push_back(2);
    ShadowMismatch m=ShadowComparator::compareState(a,b);
    EXPECT_TRUE(m.mismatch);
    EXPECT_EQ(m.field,std::string("time"));
}

TEST(ShadowComparator_TimeToleranceAllowsSmallDifference){
    ShadowState a,b;
    a.time=1.0;
    b.time=1.0001;
    EXPECT_FALSE(ShadowComparator::compareState(a,b,0.001).mismatch);
}

TEST(ShadowComparator_TimeOutsideToleranceFails){
    ShadowState a,b;
    a.time=1.0;
    b.time=1.1;
    ShadowMismatch m=ShadowComparator::compareState(a,b,0.01);
    EXPECT_TRUE(m.mismatch);
    EXPECT_EQ(m.field,std::string("time"));
}

TEST(ShadowComparator_PopulationMismatchReported){
    ShadowState a,b;
    a.populations.push_back(4);
    b.populations.push_back(5);
    ShadowMismatch m=ShadowComparator::compareState(a,b);
    EXPECT_TRUE(m.mismatch);
    EXPECT_EQ(m.field,std::string("populations"));
}

TEST(ShadowComparator_PopulationVectorLengthMismatchReported){
    ShadowState a,b;
    a.populations.push_back(4);
    ShadowMismatch m=ShadowComparator::compareState(a,b);
    EXPECT_TRUE(m.mismatch);
    EXPECT_EQ(m.field,std::string("populations"));
}

TEST(ShadowComparator_ObservableCountMismatchReported){
    ShadowState a,b;
    ShadowObservable o;o.name="x";o.value=1;
    a.observables.push_back(o);
    ShadowMismatch m=ShadowComparator::compareState(a,b);
    EXPECT_TRUE(m.mismatch);
    EXPECT_EQ(m.field,std::string("observables"));
}

TEST(ShadowComparator_ObservableNameMismatchReported){
    ShadowState a,b;
    ShadowObservable x;x.name="x";x.value=1;
    ShadowObservable y;y.name="y";y.value=1;
    a.observables.push_back(x);
    b.observables.push_back(y);
    ShadowMismatch m=ShadowComparator::compareState(a,b);
    EXPECT_TRUE(m.mismatch);
    EXPECT_EQ(m.field,std::string("observables"));
}

TEST(ShadowComparator_ObservableValueUsesTolerance){
    ShadowState a,b;
    ShadowObservable x;x.name="x";x.value=1.0;
    ShadowObservable y;y.name="x";y.value=1.00001;
    a.observables.push_back(x);
    b.observables.push_back(y);
    EXPECT_FALSE(ShadowComparator::compareState(a,b,0.001).mismatch);
    EXPECT_TRUE(ShadowComparator::compareState(a,b,0.000001).mismatch);
}

TEST(ShadowComparator_SemanticHashMismatchReportedLast){
    ShadowState a,b;
    a.semantic_hash=1;
    b.semantic_hash=2;
    ShadowMismatch m=ShadowComparator::compareState(a,b);
    EXPECT_TRUE(m.mismatch);
    EXPECT_EQ(m.field,std::string("semantic_hash"));
}

TEST(ShadowComparator_NaNStateTimeDoesNotCompareEqual){
    ShadowState a,b;
    a.time=std::numeric_limits<double>::quiet_NaN();
    b.time=std::numeric_limits<double>::quiet_NaN();
    EXPECT_TRUE(ShadowComparator::compareState(a,b,1.0).mismatch);
}

TEST(ShadowComparator_IdenticalEventMatches){
    ShadowEvent a,b;
    a.rule_name=b.rule_name="r";
    a.logical_member=b.logical_member=3;
    a.propensity=b.propensity=4.5;
    ShadowMismatch m=ShadowComparator::compareEvent(a,b);
    EXPECT_FALSE(m.mismatch);
}

TEST(ShadowComparator_EventRuleNameMismatchReported){
    ShadowEvent a,b;
    a.rule_name="a";
    b.rule_name="b";
    ShadowMismatch m=ShadowComparator::compareEvent(a,b);
    EXPECT_TRUE(m.mismatch);
    EXPECT_EQ(m.field,std::string("rule_name"));
}

TEST(ShadowComparator_EventMemberMismatchReported){
    ShadowEvent a,b;
    a.rule_name=b.rule_name="r";
    a.logical_member=1;
    b.logical_member=2;
    ShadowMismatch m=ShadowComparator::compareEvent(a,b);
    EXPECT_TRUE(m.mismatch);
    EXPECT_EQ(m.field,std::string("logical_member"));
}

TEST(ShadowComparator_EventPropensityUsesTolerance){
    ShadowEvent a,b;
    a.rule_name=b.rule_name="r";
    a.logical_member=b.logical_member=0;
    a.propensity=1;
    b.propensity=1.01;
    EXPECT_FALSE(ShadowComparator::compareEvent(a,b,0.02).mismatch);
    EXPECT_TRUE(ShadowComparator::compareEvent(a,b,0.001).mismatch);
}

TEST(ShadowComparator_BeforeStateFieldGetsPrefix){
    ShadowEvent a,b;
    a.rule_name=b.rule_name="r";
    a.logical_member=b.logical_member=0;
    a.propensity=b.propensity=1.0;
    a.before.semantic_hash=1;
    b.before.semantic_hash=2;
    ShadowMismatch m=ShadowComparator::compareEvent(a,b);
    EXPECT_TRUE(m.mismatch);
    EXPECT_EQ(m.field,std::string("before.semantic_hash"));
}

TEST(ShadowComparator_AfterStateFieldGetsPrefix){
    ShadowEvent a,b;
    a.rule_name=b.rule_name="r";
    a.logical_member=b.logical_member=0;
    a.propensity=b.propensity=1.0;
    a.after.populations.push_back(1);
    b.after.populations.push_back(2);
    ShadowMismatch m=ShadowComparator::compareEvent(a,b);
    EXPECT_TRUE(m.mismatch);
    EXPECT_EQ(m.field,std::string("after.populations"));
}

TEST(ModelImage_RoundTripNewMatcherAndTransformOpcodes){
    ExecutableModel e;
    MoleculeTypeDescriptor d;d.name="X";d.state_words=1;d.bond_slots=2;e.buildMetadata().addMoleculeType(d);
    FeatureId sf=e.buildMetadata().addFeature(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,0));
    MatcherProgram mp;MatchInstruction mi(MATCH_STATE_NOT_EQUAL);mi.target=0;mi.a=0;mi.value=7;mp.add(mi);mp.add(MatchInstruction(MATCH_END));MatcherId mid=e.buildMatchers().add(mp);
    TransformProgram tp;TransformInstruction add(TRANSFORM_ADD_STATE_WORD);add.target=0;add.a=0;add.value=static_cast<std::uint64_t>(static_cast<std::int64_t>(-1));add.feature=sf;tp.add(add);TransformInstruction un(TRANSFORM_UNBIND);un.target=0;un.a=1;un.b=TRANSFORM_INFER_PARTNER_SLOT;tp.add(un);tp.add(TransformInstruction(TRANSFORM_END));TransformProgramId tid=e.buildTransforms().add(tp);
    RuleFamilyDescriptor f;f.name="newops";f.matcher=mid;f.transform=tid;RuleMember rm;rm.rate=1;f.members.push_back(rm);e.buildMetadata().addRuleFamily(f);
    std::vector<std::vector<MatcherId> > deps(1);deps[0].push_back(mid);e.buildMetadata().setFeatureDependencies(deps);
    ExecutableModel b=readBytes(writeBytes(e));
    EXPECT_EQ(b.matchers().at(MatcherId(0)).code()[0].opcode,MATCH_STATE_NOT_EQUAL);
    const std::vector<TransformInstruction>& c=b.transforms().at(TransformProgramId(0)).code();
    EXPECT_EQ(c[0].opcode,TRANSFORM_ADD_STATE_WORD);EXPECT_EQ(c[1].opcode,TRANSFORM_UNBIND);EXPECT_EQ(c[1].b,TRANSFORM_INFER_PARTNER_SLOT);
}

TEST(ModelImage_RoundTripBondToReciprocalComponentCheck){
    ExecutableModel e;
    MoleculeTypeDescriptor a;a.name="A";a.bond_slots=2;
    MoleculeTypeDescriptor b;b.name="B";b.bond_slots=2;
    e.buildMetadata().addMoleculeType(a);e.buildMetadata().addMoleculeType(b);
    MatcherProgram p;
    MatchInstruction x(MATCH_BOND_TO);x.target=0;x.a=1;x.b=1;x.value=0;x.check_partner_component=true;
    p.add(x);p.add(MatchInstruction(MATCH_END));
    e.buildMatchers().add(p);
    ExecutableModel roundtrip=readBytes(writeBytes(e));
    const std::vector<MatchInstruction>& code=roundtrip.matchers().at(MatcherId(0)).code();
    EXPECT_EQ(code.size(),2u);
    EXPECT_EQ(code[0].opcode,MATCH_BOND_TO);
    EXPECT_TRUE(code[0].check_partner_component);
    EXPECT_EQ(code[0].value,0u);
}

TEST(ModelImage_RoundTripPopulationAndRateLawMetadata){
    ExecutableModel e;
    MoleculeTypeDescriptor population;
    population.name="ATP";
    population.state_words=0;
    population.bond_slots=0;
    population.population=true;
    e.buildMetadata().addMoleculeType(population);
    const FeatureId feature=e.buildMetadata().addFeature(
        FeatureDescriptor(FEATURE_POPULATION,0,0));

    MatcherProgram matcher;
    MatchInstruction threshold(MATCH_POPULATION_AT_LEAST);
    threshold.a=0;
    threshold.value=2;
    matcher.add(threshold);
    matcher.add(MatchInstruction(MATCH_END));
    const MatcherId matcherId=e.buildMatchers().add(matcher);

    TransformProgram transform;
    TransformInstruction add(TRANSFORM_POPULATION_ADD);
    add.a=0;
    add.value=3;
    add.feature=feature;
    transform.add(add);
    transform.add(TransformInstruction(TRANSFORM_END));
    const TransformProgramId transformId=e.buildTransforms().add(transform);

    RuleFamilyDescriptor family;
    family.name="population-rate";
    family.matcher=matcherId;
    family.transform=transformId;
    RuleMember member;
    member.rate=4.0;
    member.rate_law.kind=LEGACY_RATE_LOCAL_LINEAR;
    member.rate_law.target=1;
    member.rate_law.component=2;
    member.rate_law.offset=1.5;
    member.rate_law.slope=0.25;
    member.rate_law.weight=3.0;
    family.members.push_back(member);
    e.buildMetadata().addRuleFamily(family);
    std::vector<std::vector<MatcherId> > dependencies(1);
    dependencies[0].push_back(matcherId);
    e.buildMetadata().setFeatureDependencies(dependencies);

    const ExecutableModel roundtrip=readBytes(writeBytes(e));
    EXPECT_EQ(roundtrip.metadata().moleculeTypes().size(),1u);
    EXPECT_TRUE(roundtrip.metadata().moleculeTypes()[0].population);
    EXPECT_EQ(roundtrip.metadata().ruleFamilies().size(),1u);
    const RuleMember& restored=roundtrip.metadata().ruleFamilies()[0].members[0];
    EXPECT_EQ(restored.rate_law.kind,LEGACY_RATE_LOCAL_LINEAR);
    EXPECT_EQ(restored.rate_law.target,1u);
    EXPECT_EQ(restored.rate_law.component,2u);
    EXPECT_EQ(restored.rate_law.offset,1.5);
    EXPECT_EQ(restored.rate_law.slope,0.25);
    EXPECT_EQ(restored.rate_law.weight,3.0);
}

TEST(ModelImage_RoundTripCompartmentGraphAndExpressionMetadata){
    ExecutableModel e;
    MoleculeTypeDescriptor a; a.name="A"; a.bond_slots=1;
    MoleculeTypeDescriptor b; b.name="B"; b.bond_slots=1;
    e.buildMetadata().addMoleculeType(a); e.buildMetadata().addMoleculeType(b);
    CompartmentDescriptor root; root.id=10; root.size=20.0;
    CompartmentDescriptor child; child.id=11; child.parent=10; child.size=5.0;
    e.buildMetadata().addCompartment(root); e.buildMetadata().addCompartment(child);

    MatcherProgram matcher;
    GraphPattern graph;
    GraphNodePattern left; left.molecule_type=0; left.anchor_reactant=0;
    GraphNodePattern right; right.molecule_type=1; right.compartment=11;
    right.free_components.push_back(0);
    graph.nodes.push_back(left); graph.nodes.push_back(right);
    GraphEdgePattern edge; edge.first_node=0; edge.first_component=0; edge.second_node=1; edge.second_component=0;
    graph.edges.push_back(edge);
    const std::uint32_t graphId=matcher.addGraphPattern(graph);
    MatchInstruction graphInstruction(MATCH_GRAPH); graphInstruction.a=graphId;
    matcher.add(graphInstruction); matcher.add(MatchInstruction(MATCH_END));
    const MatcherId matcherId=e.buildMatchers().add(matcher);

    TransformProgram transform; transform.add(TransformInstruction(TRANSFORM_END));
    const TransformProgramId transformId=e.buildTransforms().add(transform);
    RuleFamilyDescriptor family; family.name="graph-expression"; family.matcher=matcherId; family.transform=transformId;
    RuleMember member; member.rate=2.0; member.rate_law.kind=LEGACY_RATE_EXPRESSION;
    member.rate_law.expression="s0 + time"; member.rate_law.expression_components.push_back(0);
    RateExpressionBinding binding; binding.kind=RATE_EXPRESSION_CONSTANT; binding.name="k"; binding.value=3.0;
    member.rate_law.expression_bindings.push_back(binding);
    RateExpressionBinding count; count.kind=RATE_EXPRESSION_REACTANT_COUNT; count.name="rc"; count.target=1;
    member.rate_law.expression_bindings.push_back(count);
    RateExpressionBinding scoped; scoped.kind=RATE_EXPRESSION_SPECIES_MOLECULE_COUNT;
    scoped.name="atotal_1"; scoped.target=0; scoped.molecule_type=1; scoped.scope=0;
    scoped.state_component=0; scoped.state_value=1; scoped.bond_component=0; scoped.bond_state=0;
    scoped.compartment=11; scoped.compartment_ancestry=true;
    member.rate_law.expression_bindings.push_back(scoped);
    RateExpressionBinding volume; volume.kind=RATE_EXPRESSION_COMPARTMENT_VOLUME; volume.name="vol"; volume.target=0;
    member.rate_law.expression_bindings.push_back(volume);
    RateExpressionBinding transport; transport.kind=RATE_EXPRESSION_TRANSPORT_VOLUME_RATIO;
    transport.name="transport"; transport.target=0; transport.destination_compartment=11;
    member.rate_law.expression_bindings.push_back(transport);
    RateExpressionBinding global; global.kind=RATE_EXPRESSION_GLOBAL_MOLECULE_COUNT;
    global.name="global"; global.molecule_type=1;
    global.state_component=0; global.state_value=1; global.bond_component=0; global.bond_state=1;
    member.rate_law.expression_bindings.push_back(global);
    RateExpressionBinding complex; complex.kind=RATE_EXPRESSION_COMPLEX_MOLECULE_COUNT;
    complex.name="complex"; complex.molecule_type=0; complex.component=0;
    complex.partner_molecule_type=1; complex.partner_component=0; complex.scope=-1;
    member.rate_law.expression_bindings.push_back(complex);
    family.members.push_back(member); e.buildMetadata().addRuleFamily(family);
    e.buildMetadata().setFeatureDependencies(std::vector<std::vector<MatcherId> >());

    ExecutableModel roundtrip=readBytes(writeBytes(e));
    EXPECT_EQ(roundtrip.metadata().compartments().size(),2u);
    EXPECT_EQ(roundtrip.metadata().compartments()[1].parent,10u);
    const MatcherProgram& restored=roundtrip.matchers().at(matcherId);
    EXPECT_EQ(restored.graphPatterns().size(),1u);
    EXPECT_EQ(restored.graphPatterns()[0].edges.size(),1u);
    EXPECT_EQ(restored.graphPatterns()[0].nodes[1].compartment,11u);
    EXPECT_EQ(restored.graphPatterns()[0].nodes[1].free_components.size(),1u);
    const RuleMember& restoredMember=roundtrip.metadata().ruleFamilies()[0].members[0];
    EXPECT_EQ(restoredMember.rate_law.kind,LEGACY_RATE_EXPRESSION);
    EXPECT_EQ(restoredMember.rate_law.expression,std::string("s0 + time"));
    EXPECT_EQ(restoredMember.rate_law.expression_components.size(),1u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings.size(),7u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[0].name,std::string("k"));
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[0].value,3.0);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[1].kind,RATE_EXPRESSION_REACTANT_COUNT);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[1].target,1u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[2].kind,RATE_EXPRESSION_SPECIES_MOLECULE_COUNT);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[2].target,0u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[2].molecule_type,1u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[2].scope,0);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[2].state_component,0u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[2].state_value,1);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[2].bond_component,0u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[2].bond_state,0);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[2].compartment,11u);
    EXPECT_TRUE(restoredMember.rate_law.expression_bindings[2].compartment_ancestry);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[3].kind,RATE_EXPRESSION_COMPARTMENT_VOLUME);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[3].target,0u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[4].kind,RATE_EXPRESSION_TRANSPORT_VOLUME_RATIO);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[4].target,0u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[4].destination_compartment,11u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[5].kind,RATE_EXPRESSION_GLOBAL_MOLECULE_COUNT);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[5].molecule_type,1u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[5].state_component,0u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[5].state_value,1);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[5].bond_component,0u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[5].bond_state,1);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[6].kind,
              RATE_EXPRESSION_COMPLEX_MOLECULE_COUNT);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[6].molecule_type,0u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[6].component,0u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[6].partner_molecule_type,1u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[6].partner_component,0u);
    EXPECT_EQ(restoredMember.rate_law.expression_bindings[6].scope,-1);
}
