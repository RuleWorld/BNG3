#include "nfnext/fenwick.hpp"
#include "nfnext/generic_state.hpp"
#include "nfnext/lattice.hpp"
#include "nfnext/matcher.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <set>
#include <vector>

using namespace nfnext;
namespace {
int failures=0,checks=0;
void fail(const char* e,int l){++failures;std::cerr<<"line "<<l<<": "<<e<<'\n';}
#define C(x) do{++checks;if(!(x))fail(#x,__LINE__);}while(0)
#define E(a,b) do{++checks;if(!((a)==(b)))fail(#a " == " #b,__LINE__);}while(0)
#define NEAR(a,b,e) do{++checks;if(std::fabs((a)-(b))>(e))fail(#a " ~= " #b,__LINE__);}while(0)

ModelIR graphModel(){ModelIR m;MoleculeTypeIR a;a.id=0;a.name="A";a.sites={SiteSpec{"x",{"u","p","q"}},SiteSpec{"y",{}}};m.molecule_types={a};return m;}

bool pred(const GenericGraphState& g,ParticleId id,const PredicateIR& p){
    if(g.type(id)!=p.molecule_type)return false;
    switch(p.kind){
        case PredicateKind::SiteStateEq:return g.siteState(id,p.site)==p.value;
        case PredicateKind::SiteStateInSet:return std::find(p.values.begin(),p.values.end(),g.siteState(id,p.site))!=p.values.end();
        case PredicateKind::SiteBound:return g.bound(id,p.site);
        case PredicateKind::SiteFree:return !g.bound(id,p.site);
        default:return false;
    }
}
std::size_t bruteTwoNode(const GenericGraphState& g,const PatternGraphIR& pat,const std::vector<PredicateIR>& ps){
    auto live=g.liveParticles(0);std::size_t n=0;
    for(auto a:live)for(auto b:live){if(a==b)continue;bool ok=true;
        for(const auto& p:ps){auto id=p.node==1?b:a;if(!pred(g,id,p)){ok=false;break;}}
        if(!ok)continue;
        for(const auto& edge:pat.bonds){auto l=edge.lhs==1?b:a, r=edge.rhs==1?b:a;if(!g.bound(l,edge.lhs_site)){ok=false;break;}auto x=g.bond(l,edge.lhs_site);if(x.particle!=r||x.site!=edge.rhs_site){ok=false;break;}}
        if(!ok)continue;
        for(const auto& rel:pat.molecularity){bool same=g.sameComplex(a,b);if(rel.relation==ComplexRelation::SameComplex?!same:same){ok=false;break;}}
        if(ok)++n;
    }
    return n;
}

void randomized_single_node_predicates_match_oracle(){
    std::mt19937 rng(11);auto m=graphModel();GenericGraphState g(m);std::vector<ParticleId> ids;
    for(int i=0;i<40;++i){auto id=g.create(0);g.setSiteState(id,0,rng()%3);ids.push_back(id);}
    for(int k=0;k<200;++k){PredicateIR p;p.molecule_type=0;p.node=0;p.site=0;switch(rng()%4){case 0:p.kind=PredicateKind::SiteStateEq;p.value=rng()%3;break;case 1:p.kind=PredicateKind::SiteStateInSet;p.values={(int)(rng()%3),(int)(rng()%3)};std::sort(p.values.begin(),p.values.end());p.values.erase(std::unique(p.values.begin(),p.values.end()),p.values.end());break;case 2:p.kind=PredicateKind::SiteFree;break;default:p.kind=PredicateKind::SiteBound;break;}
        PatternGraphIR pat;pat.nodes={PatternNodeIR{0,0,0,0}};std::size_t expected=0;for(auto id:ids)if(pred(g,id,p))++expected;E(PatternMatcher::countMatches(g,pat,{p}),expected);
    }
}
void randomized_two_node_bond_patterns_match_oracle(){
    std::mt19937 rng(22);for(int rep=0;rep<80;++rep){auto m=graphModel();GenericGraphState g(m);std::vector<ParticleId> ids;for(int i=0;i<8;++i){auto id=g.create(0);g.setSiteState(id,0,rng()%3);ids.push_back(id);}std::shuffle(ids.begin(),ids.end(),rng);for(int i=0;i+1<8;i+=2)if(rng()%2)g.bind(ids[i],1,ids[i+1],1);
        PatternGraphIR pat;pat.nodes={PatternNodeIR{0,0,0,0},PatternNodeIR{1,0,0,0}};if(rng()%2)pat.bonds.push_back({0,1,1,1});std::vector<PredicateIR> ps;for(int node=0;node<2;++node){PredicateIR p;p.molecule_type=0;p.node=node;p.site=0;p.kind=PredicateKind::SiteStateEq;p.value=rng()%3;ps.push_back(p);}E(PatternMatcher::countMatches(g,pat,ps),bruteTwoNode(g,pat,ps));}
}
void randomized_molecularity_matches_oracle(){
    std::mt19937 rng(33);for(int rep=0;rep<60;++rep){auto m=graphModel();GenericGraphState g(m);std::vector<ParticleId> ids;for(int i=0;i<6;++i)ids.push_back(g.create(0));for(int i=0;i+1<6;i+=2)if(rng()%2)g.bind(ids[i],1,ids[i+1],1);
        PatternGraphIR pat;pat.nodes={PatternNodeIR{0,0,0,0},PatternNodeIR{1,0,1,0}};pat.molecularity={{0,1,(rng()%2)?ComplexRelation::SameComplex:ComplexRelation::DifferentComplex}};E(PatternMatcher::countMatches(g,pat,{}),bruteTwoNode(g,pat,{}));}
}
void randomized_symmetry_is_unordered_pair_count(){
    for(int n=1;n<=15;++n){auto m=graphModel();GenericGraphState g(m);for(int i=0;i<n;++i)g.create(0);PatternGraphIR p;p.nodes={PatternNodeIR{0,0,0,7},PatternNodeIR{1,0,0,7}};E(PatternMatcher::countMatches(g,p,{}),(std::size_t)n*(n-1)/2);}
}

void fenwick_random_updates_match_vector(){
    std::mt19937 rng(44);for(int n=1;n<=128;n*=2){FenwickTree f(n);std::vector<double> v(n);for(int step=0;step<1000;++step){int i=rng()%n;double x=(rng()%1000)/100.0;v[i]=x;f.set(i,x);double sum=0;for(double q:v)sum+=q;NEAR(f.total(),sum,1e-9);int cut=rng()%(n+1);double pre=0;for(int j=0;j<cut;++j)pre+=v[j];NEAR(f.prefix(cut),pre,1e-9);}}
}
void fenwick_lower_bound_matches_linear_scan(){
    std::mt19937 rng(55);for(int rep=0;rep<120;++rep){int n=1+rng()%100;FenwickTree f(n);std::vector<double> v(n);double total=0;for(int i=0;i<n;++i){v[i]=(rng()%5==0)?0.0:(1+rng()%100)/10.0;f.set(i,v[i]);total+=v[i];}if(total==0)continue;for(int q=0;q<30;++q){double target=std::generate_canonical<double,53>(rng)*total;if(target>=total)target=std::nextafter(total,0.0);double acc=0;std::size_t expected=0;while(expected<v.size()&&acc+v[expected]<=target){acc+=v[expected];++expected;}E(f.lowerBound(target),expected);}}
}

std::vector<int> occupancyFromHeads(int length,int footprint,const std::set<int>& heads){std::vector<int> occ(length);for(int h:heads)for(int x=h;x<h+footprint&&x<length;++x)occ[x]=1;return occ;}
bool bruteCanHop(int h,int length,int footprint,const std::vector<int>& occ){int entering=h+footprint;return entering<length&&!occ[entering];}
void randomized_lattice_propensity_matches_bruteforce(){
    std::mt19937 rng(66);for(int rep=0;rep<180;++rep){int length=5+rng()%45;int footprint=1+rng()%std::min(8,length);double rate=(1+rng()%50)/7.0;GenomeLattice l({(std::uint32_t)length,rate,false,(std::uint32_t)footprint,0,0,0});std::set<int> heads;std::vector<int> occ(length);for(int tries=0;tries<length*3;++tries){int h=rng()%length;if(h+footprint>length)continue;bool free=true;for(int x=h;x<h+footprint;++x)if(occ[x])free=false;if(free&&rng()%3==0){l.place(h);heads.insert(h);for(int x=h;x<h+footprint;++x)occ[x]=1;}}
        int eligible=0;for(int h:heads){bool expected=bruteCanHop(h,length,footprint,occ);E(l.canHop(h),expected);if(expected)++eligible;}NEAR(l.hopPropensity(),eligible*rate,1e-9);
    }
}
void randomized_hops_preserve_occupancy_and_propensity(){
    std::mt19937 rng(77);for(int rep=0;rep<100;++rep){int length=20+rng()%30,footprint=1+rng()%6;GenomeLattice l({(std::uint32_t)length,2.5,false,(std::uint32_t)footprint,0,0,0});std::set<int> heads;std::vector<int> occ(length);for(int h=0;h+footprint<=length;h+=footprint+2)if(rng()%2){l.place(h);heads.insert(h);for(int x=h;x<h+footprint;++x)occ[x]=1;}
        for(int step=0;step<80;++step){std::vector<int> eligible;for(int h:heads)if(bruteCanHop(h,length,footprint,occ))eligible.push_back(h);NEAR(l.hopPropensity(),eligible.size()*2.5,1e-9);if(eligible.empty())break;int h=eligible[rng()%eligible.size()];C(l.hop(h));heads.erase(h);heads.insert(h+1);occ=occupancyFromHeads(length,footprint,heads);for(int x=0;x<length;++x)E(l.occupied(x),occ[x]!=0);}
    }
}
void initiation_and_termination_match_brute_conditions(){
    std::mt19937 rng(88);for(int rep=0;rep<100;++rep){int length=10+rng()%30,fp=1+rng()%std::min(6,length);int init=rng()%(length-fp+1);GenomeLattice l({(std::uint32_t)length,1,false,(std::uint32_t)fp,3,5,(std::uint32_t)init});std::vector<int> occ(length);for(int h=0;h+fp<=length;h+=fp+1)if(rng()%3==0){bool free=true;for(int x=h;x<h+fp;++x)if(occ[x])free=false;if(free){l.place(h);for(int x=h;x<h+fp;++x)occ[x]=1;}}
        bool initfree=true;for(int x=init;x<init+fp;++x)if(occ[x])initfree=false;E(l.canInitiate(),initfree);bool terminal=true;for(int x=length-fp;x<length;++x)if(!occ[x])terminal=false; // placement spans guarantee one head iff all terminal cells occupied
        E(l.canTerminate(),terminal&&l.isHead(length-fp));
    }
}
void lattice_selected_hop_is_always_eligible(){
    GenomeLattice l({40,1.7,false,3,0,0,0});for(int p:{0,5,11,20,30})l.place(p);double total=l.hopPropensity();C(total>0);for(int i=0;i<1000;++i){double target=total*(i+0.5)/1000.0;auto h=l.selectHop(target);C(l.isHead(h));C(l.canHop(h));}
}
void lattice_run_never_reports_null_events(){
    for(std::uint64_t seed=0;seed<50;++seed){GenomeLattice l({80,1.3,false,4,2.1,3.2,0});auto r=l.run(500,1e9,seed);E(r.null_events,0u);E(r.events,r.initiations+r.hops+r.terminations);}
}

struct T{const char*n;void(*f)();};T tests[]={
{"single predicates",randomized_single_node_predicates_match_oracle},{"two node",randomized_two_node_bond_patterns_match_oracle},{"molecularity",randomized_molecularity_matches_oracle},{"symmetry",randomized_symmetry_is_unordered_pair_count},
{"fenwick update",fenwick_random_updates_match_vector},{"fenwick select",fenwick_lower_bound_matches_linear_scan},{"lattice propensity",randomized_lattice_propensity_matches_bruteforce},{"lattice hops",randomized_hops_preserve_occupancy_and_propensity},
{"init term",initiation_and_termination_match_brute_conditions},{"lattice select",lattice_selected_hop_is_always_eligible},{"lattice run",lattice_run_never_reports_null_events}
};
}
int main(){for(auto&t:tests){try{t.f();}catch(const std::exception&e){++failures;std::cerr<<t.n<<": "<<e.what()<<'\n';}catch(...){++failures;std::cerr<<t.n<<": unknown\n";}}std::cout<<"randomized oracle tests: "<<sizeof(tests)/sizeof(tests[0])<<" cases, "<<checks<<" checks, "<<failures<<" failures\n";return failures?1:0;}
