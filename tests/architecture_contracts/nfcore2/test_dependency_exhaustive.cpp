#include "test_harness.hh"
#include "engine.hh"
#include <set>
#include <random>
using namespace NFcore2;

static ExecutableModel depModel(unsigned F,unsigned M,unsigned R){
    ExecutableModel e; MoleculeTypeDescriptor d; d.name="x"; e.buildMetadata().addMoleculeType(d);
    for(unsigned i=0;i<F;++i)e.buildMetadata().addFeature(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,i));
    for(unsigned i=0;i<M;++i){MatcherProgram p;p.add(MatchInstruction(MATCH_END));e.buildMatchers().add(p);}
    TransformProgram t;t.add(TransformInstruction(TRANSFORM_END));auto tid=e.buildTransforms().add(t);
    for(unsigned i=0;i<R;++i){RuleFamilyDescriptor f;f.name="r";f.matcher=MatcherId(i%M);f.transform=tid;f.members.resize(1);e.buildMetadata().addRuleFamily(f);}return e;
}
TEST(csr_dependency_index_matches_adjacency_for_random_graphs){
    std::mt19937 g(19);for(unsigned trial=0;trial<50;++trial){unsigned F=1+g()%80,M=1+g()%40;CompiledModel m;for(unsigned z=0;z<F;++z)m.addFeature(FeatureDescriptor(FEATURE_MOLECULE_STATE,0,z));std::vector<std::vector<MatcherId> >adj(F);for(unsigned f=0;f<F;++f){for(unsigned j=0;j<M;++j)if((g()%7)==0)adj[f].push_back(MatcherId(j));}m.setFeatureDependencies(adj);for(unsigned f=0;f<F;++f){auto p=m.dependencies().dependents(FeatureId(f));std::vector<unsigned>got;for(auto q=p.first;q!=p.second;++q)got.push_back(q->value());std::vector<unsigned>want;for(auto x:adj[f])want.push_back(x.value());EXPECT_EQ(got,want);}}
}
TEST(affected_matchers_deduplicate_across_many_changed_features){
    auto e=depModel(100,25,50);std::vector<std::vector<MatcherId> >a(100);for(unsigned f=0;f<100;++f){a[f].push_back(MatcherId(f%25));a[f].push_back(MatcherId((f*7)%25));}e.buildMetadata().setFeatureDependencies(a);Engine en(e);FeatureDelta d;for(unsigned f=0;f<100;++f)d.add(FeatureId(f));auto got=en.affectedMatchers(d);std::set<unsigned>s;for(auto x:got)s.insert(x.value());EXPECT_EQ(got.size(),s.size());for(unsigned i=0;i<25;++i)EXPECT_TRUE(s.count(i)!=0);
}
TEST(affected_families_equal_union_of_matcher_reverse_index){
    auto e=depModel(30,10,100);std::vector<std::vector<MatcherId> >a(30);for(unsigned f=0;f<30;++f)a[f].push_back(MatcherId(f%10));e.buildMetadata().setFeatureDependencies(a);Engine en(e);for(unsigned f=0;f<30;++f){FeatureDelta d;d.add(FeatureId(f));auto fam=en.affectedFamilies(d);std::set<unsigned>got;for(auto x:fam)got.insert(x.value());std::set<unsigned>want;for(unsigned r=0;r<100;++r)if(r%10==f%10)want.insert(r);EXPECT_EQ(got,want);}
}
TEST(empty_delta_affects_nothing){auto e=depModel(3,2,4);e.buildMetadata().setFeatureDependencies(std::vector<std::vector<MatcherId> >(3));Engine en(e);FeatureDelta d;EXPECT_TRUE(en.affectedMatchers(d).empty());EXPECT_TRUE(en.affectedFamilies(d).empty());}
TEST(duplicate_feature_ids_do_not_duplicate_results){auto e=depModel(2,2,2);std::vector<std::vector<MatcherId> >a(2);a[0].push_back(MatcherId(0));e.buildMetadata().setFeatureDependencies(a);Engine en(e);FeatureDelta d;for(int i=0;i<1000;++i)d.add(FeatureId(0));EXPECT_EQ(en.affectedMatchers(d).size(),1u);EXPECT_EQ(en.affectedFamilies(d).size(),1u);}
