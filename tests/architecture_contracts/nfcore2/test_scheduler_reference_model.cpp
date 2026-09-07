#include "test_harness.hh"
#include "scheduler.hh"
#include <vector>
#include <random>
using namespace NFcore2;

static size_t naiveSample(const std::vector<double>&v,double target){double s=0;for(size_t i=0;i<v.size();++i){s+=v[i];if(target<s)return i;}return v.size()-1;}
TEST(fenwick_prefix_matches_naive_after_100k_updates){
    const size_t N=257;FenwickTree f(N);std::vector<double> v(N,0.0);std::mt19937 rng(77);for(unsigned step=0;step<100000;++step){size_t i=rng()%N;double x=(rng()%10000)/100.0;v[i]=x;f.set(i,x);if((step%101)==0){size_t n=rng()%(N+1);double sum=0;for(size_t k=0;k<n;++k)sum+=v[k];EXPECT_NEAR(f.prefix(n),sum,1e-9*(1+sum));}}
}
TEST(fenwick_sampling_matches_naive_grid){
    FenwickTree f(17);std::vector<double>v(17);for(size_t i=0;i<v.size();++i){v[i]=(i%4==0)?0.0:(double)(i+1);f.set(i,v[i]);}double total=f.total();for(unsigned q=0;q<10000;++q){double t=total*(q+0.5)/10000.0;EXPECT_EQ(f.sample(t),naiveSample(v,t));}
}
TEST(fenwick_zero_entries_never_sampled){FenwickTree f(100);for(size_t i=0;i<100;++i)f.set(i,(i==73)?5.0:0.0);for(unsigned q=0;q<1000;++q)EXPECT_EQ(f.sample(5.0*(q+0.5)/1000.0),73u);}
TEST(fenwick_rejects_negative_nan_inf){FenwickTree f(2);EXPECT_THROW(f.set(0,-1),std::exception);EXPECT_THROW(f.set(0,std::numeric_limits<double>::quiet_NaN()),std::exception);EXPECT_THROW(f.set(0,std::numeric_limits<double>::infinity()),std::exception);}
TEST(hierarchical_scheduler_grid_matches_flat_reference){
    CompiledModel m;for(unsigned f=0;f<7;++f){RuleFamilyDescriptor d;d.name="f";d.matcher=MatcherId(f);d.transform=TransformProgramId(0);for(unsigned j=0;j<f+3;++j){RuleMember r;r.rate=(j+1)*0.25;d.members.push_back(r);}m.addRuleFamily(d);}HierarchicalScheduler h(m);std::vector<double> flat;std::vector<std::pair<unsigned,unsigned> > ids;
    for(unsigned f=0;f<7;++f)for(unsigned j=0;j<m.ruleFamilies()[f].members.size();++j){double a=(f+1)*(j+2)*0.125;h.setMemberActivity(RuleFamilyId(f),j,a);flat.push_back(a);ids.push_back({f,j});}
    double total=h.totalActivity();for(unsigned q=0;q<20000;++q){double u=(q+0.5)/20000.0;size_t k=naiveSample(flat,u*total);EventChoice c=h.sample(u);EXPECT_EQ(c.family.value(),ids[k].first);EXPECT_EQ(c.member,ids[k].second);}
}
TEST(hierarchical_repeated_zero_nonzero_toggle_preserves_total){CompiledModel m;RuleFamilyDescriptor d;d.matcher=MatcherId(0);d.transform=TransformProgramId(0);d.members.resize(64);m.addRuleFamily(d);HierarchicalScheduler h(m);for(unsigned round=0;round<1000;++round){double total=0;for(unsigned i=0;i<64;++i){double a=((i+round)%5)?(i+1)*.1:0;h.setMemberActivity(RuleFamilyId(0),i,a);total+=a;}EXPECT_NEAR(h.totalActivity(),total,1e-10*(1+total));}}
