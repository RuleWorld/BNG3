#include "test_harness.hh"
#include "nfsim_system_reader.hh"
using namespace NFcore2;

namespace {
class FakeReader : public NFsimSystemReader {
public:
    std::vector<NativeMoleculeTypeSnapshot> mts;
    std::vector<NativeReactionSnapshot> rxns;
    virtual std::size_t moleculeTypeCount() const { return mts.size(); }
    virtual NativeMoleculeTypeSnapshot moleculeType(std::size_t i) const { return mts.at(i); }
    virtual std::size_t reactionCount() const { return rxns.size(); }
    virtual NativeReactionHeader reactionHeader(std::size_t i) const {
        NativeReactionHeader h; const NativeReactionSnapshot&r=rxns.at(i);h.name=r.name;h.base_rate=r.base_rate;h.parameter_index=r.parameter_index;h.coordinate=r.coordinate;h.uses_local_function=r.uses_local_function;h.uses_connected_to=r.uses_connected_to;h.reactant_types=r.reactant_types;return h;
    }
    virtual void collectDependencies(std::size_t i,std::vector<NativeDependencySnapshot>&out) const { out=rxns.at(i).dependencies; }
    virtual void collectTransforms(std::size_t i,std::vector<NativeTransformSnapshot>&out) const { out=rxns.at(i).transforms; }
};
NativeMoleculeTypeSnapshot mt(const char*n,unsigned c){NativeMoleculeTypeSnapshot x;x.name=n;x.component_count=c;return x;}
NativeReactionSnapshot rr(const char*n,double rate){NativeReactionSnapshot r;r.name=n;r.base_rate=rate;return r;}
}

TEST(SystemReader_EmptyReaderProducesEmptySnapshot){FakeReader f;NativeModelSnapshot n=readNFsimSystem(f);EXPECT_TRUE(n.molecule_types.empty());EXPECT_TRUE(n.rules.empty());}
TEST(SystemReader_CopiesMoleculeTypesInStableOrder){FakeReader f;f.mts.push_back(mt("A",2));f.mts.push_back(mt("B",3));NativeModelSnapshot n=readNFsimSystem(f);EXPECT_EQ(n.molecule_types[0].name,std::string("A"));EXPECT_EQ(n.molecule_types[1].name,std::string("B"));}
TEST(SystemReader_CopiesReactionHeaders){FakeReader f;f.mts.push_back(mt("A",1));NativeReactionSnapshot r=rr("elong_17",4.25);r.parameter_index=8;r.coordinate=17;r.reactant_types.push_back(0);f.rxns.push_back(r);NativeReactionSnapshot x=readNFsimSystem(f).rules[0];EXPECT_EQ(x.name,std::string("elong_17"));EXPECT_EQ(x.base_rate,4.25);EXPECT_EQ(x.parameter_index,8u);EXPECT_EQ(x.coordinate,17u);EXPECT_EQ(x.reactant_types.size(),1u);}
TEST(SystemReader_CopiesDependencyPayloadExactly){FakeReader f;f.mts.push_back(mt("A",2));NativeReactionSnapshot r=rr("r",1);NativeDependencySnapshot d;d.kind=NATIVE_STATE_EXCLUDED;d.reactant=0;d.component=1;d.state=3;r.dependencies.push_back(d);f.rxns.push_back(r);NativeDependencySnapshot x=readNFsimSystem(f).rules[0].dependencies[0];EXPECT_EQ(x.kind,NATIVE_STATE_EXCLUDED);EXPECT_EQ(x.component,1u);EXPECT_EQ(x.state,3);}
TEST(SystemReader_CopiesTransformPayloadExactly){FakeReader f;f.mts.push_back(mt("A",2));NativeReactionSnapshot r=rr("r",1);NativeTransformSnapshot t;t.kind=NATIVE_STATE_CHANGE;t.reactant=0;t.component=1;t.new_value=4;r.transforms.push_back(t);f.rxns.push_back(r);NativeTransformSnapshot x=readNFsimSystem(f).rules[0].transforms[0];EXPECT_EQ(x.kind,NATIVE_STATE_CHANGE);EXPECT_EQ(x.component,1u);EXPECT_EQ(x.new_value,4);}
TEST(SystemReader_CopiesFallbackFlags){FakeReader f;f.mts.push_back(mt("A",1));NativeReactionSnapshot r=rr("r",1);r.uses_local_function=true;r.uses_connected_to=true;f.rxns.push_back(r);NativeReactionSnapshot x=readNFsimSystem(f).rules[0];EXPECT_TRUE(x.uses_local_function);EXPECT_TRUE(x.uses_connected_to);}
TEST(SystemReader_DoesNotAliasReaderVectors){FakeReader f;f.mts.push_back(mt("A",1));NativeReactionSnapshot r=rr("r",1);r.reactant_types.push_back(0);f.rxns.push_back(r);NativeModelSnapshot n=readNFsimSystem(f);f.mts[0].name="mutated";f.rxns[0].name="mutated";EXPECT_EQ(n.molecule_types[0].name,std::string("A"));EXPECT_EQ(n.rules[0].name,std::string("r"));}
TEST(SystemReader_RejectsEmptyMoleculeTypeName){FakeReader f;f.mts.push_back(mt("",1));EXPECT_THROW(readNFsimSystem(f),std::invalid_argument);}
TEST(SystemReader_RejectsEmptyReactionName){FakeReader f;f.mts.push_back(mt("A",1));f.rxns.push_back(rr("",1));EXPECT_THROW(readNFsimSystem(f),std::invalid_argument);}
TEST(SystemReader_RejectsReactantTypeOutsideModel){FakeReader f;f.mts.push_back(mt("A",1));NativeReactionSnapshot r=rr("r",1);r.reactant_types.push_back(9);f.rxns.push_back(r);EXPECT_THROW(readNFsimSystem(f),std::out_of_range);}
TEST(SystemReader_RejectsDuplicateMoleculeTypeNames){FakeReader f;f.mts.push_back(mt("A",1));f.mts.push_back(mt("A",2));EXPECT_THROW(readNFsimSystem(f),std::invalid_argument);}
TEST(SystemReader_PreservesPopulationFlag){FakeReader f;NativeMoleculeTypeSnapshot p=mt("ATP",1);p.population=true;f.mts.push_back(p);EXPECT_TRUE(readNFsimSystem(f).molecule_types[0].population);}
TEST(SystemReader_ManyRulesMaintainInputOrdering){FakeReader f;f.mts.push_back(mt("A",1));for(unsigned i=0;i<5000;++i){NativeReactionSnapshot r=rr("r",1);r.coordinate=i;f.rxns.push_back(r);}NativeModelSnapshot n=readNFsimSystem(f);EXPECT_EQ(n.rules.size(),5000u);EXPECT_EQ(n.rules.front().coordinate,0u);EXPECT_EQ(n.rules.back().coordinate,4999u);}
TEST(SystemReader_FullPipelineRepeatedRulesCompress){FakeReader f;f.mts.push_back(mt("A",1));for(unsigned i=0;i<2000;++i){NativeReactionSnapshot r=rr("elong",1);r.coordinate=i;r.reactant_types.push_back(0);NativeDependencySnapshot d;d.kind=NATIVE_STATE_REQUIRED;d.reactant=0;d.component=0;d.state=0;r.dependencies.push_back(d);NativeTransformSnapshot t;t.kind=NATIVE_STATE_CHANGE;t.reactant=0;t.component=0;t.new_value=1;r.transforms.push_back(t);f.rxns.push_back(r);}LegacyLoweringResult out=LegacyLowerer::lower(NFsimSnapshotAdapter::toLegacy(readNFsimSystem(f)));EXPECT_EQ(out.supported_rule_count,2000u);EXPECT_EQ(out.executable.metadata().ruleFamilies().size(),1u);}
