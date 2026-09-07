#include "nfnext/cache.hpp"
#include "nfnext/population.hpp"
#include "nfnext/validation.hpp"

#include <cmath>
#include <cstdio>
#include <iostream>
#include <stdexcept>
#include <vector>
using namespace nfnext;
namespace {
int failures=0,checks=0;void fail(const char*e,int l){++failures;std::cerr<<"line "<<l<<": "<<e<<'\n';}
#define C(x) do{++checks;if(!(x))fail(#x,__LINE__);}while(0)
#define E(a,b) do{++checks;if(!((a)==(b)))fail(#a " == " #b,__LINE__);}while(0)
#define NEAR(a,b,e) do{++checks;if(std::fabs((a)-(b))>(e))fail(#a " ~= " #b,__LINE__);}while(0)
#define THROWS(code) do{++checks;bool q=false;try{code;}catch(...){q=true;}if(!q)fail("expected throw",__LINE__);}while(0)

ModelIR base(){ModelIR m;MoleculeTypeIR a;a.id=0;a.name="A";a.storage=StorageKind::Population;MoleculeTypeIR b;b.id=1;b.name="B";b.storage=StorageKind::Population;m.molecule_types={a,b};return m;}
PopulationRuleIR rule(RuleId id,double k,std::initializer_list<PopulationStoichIR> r,std::initializer_list<PopulationStoichIR> p){PopulationRuleIR x;x.id=id;x.name="r"+std::to_string(id);x.reactants=r;x.products=p;x.rate_law.kind=RateLawKind::MassAction;x.rate_law.base_rate=k;x.rate=k;return x;}

void store_initializes_counts(){auto m=base();m.initial_populations={{0,7},{1,2}};PopulationState s(m);E(s.count(0),7u);E(s.count(1),2u);}
void store_unknown_type_throws(){auto m=base();PopulationState s(m);THROWS(s.count(99));}
void store_set_and_add(){auto m=base();PopulationState s(m);s.set(0,4);s.add(0,3);E(s.count(0),7u);s.remove(0,2);E(s.count(0),5u);}
void store_underflow_is_atomic(){auto m=base();PopulationState s(m);s.set(0,2);THROWS(s.remove(0,3));E(s.count(0),2u);}
void duplicate_initial_counts_rejected(){auto m=base();m.initial_populations={{0,1},{0,2}};auto v=ModelValidator::validate(m);C(ModelValidator::hasError(v,"duplicate_initial_population"));}
void particle_initialization_for_population_type_rejected(){auto m=base();m.initial_particles.push_back({0,0,{}});auto v=ModelValidator::validate(m);C(ModelValidator::hasError(v,"population_type_as_particle"));}
void population_initialization_for_particle_type_rejected(){auto m=base();m.molecule_types[0].storage=StorageKind::Particle;m.initial_populations={{0,3}};auto v=ModelValidator::validate(m);C(ModelValidator::hasError(v,"particle_type_as_population"));}

void unary_propensity(){auto m=base();m.initial_populations={{0,9}};auto r=rule(0,2.5,{{0,1}},{});m.population_rules={r};PopulationSimulator s(m);NEAR(s.propensity(r),22.5,1e-12);}
void binary_distinct_propensity(){auto m=base();m.initial_populations={{0,4},{1,7}};auto r=rule(0,.25,{{0,1},{1,1}},{});m.population_rules={r};PopulationSimulator s(m);NEAR(s.propensity(r),7.0,1e-12);}
void same_species_dimer_propensity_uses_combinations(){auto m=base();m.initial_populations={{0,5}};auto r=rule(0,3.0,{{0,2}},{});m.population_rules={r};PopulationSimulator s(m);NEAR(s.propensity(r),30.0,1e-12);}
void same_species_trimer_propensity(){auto m=base();m.initial_populations={{0,6}};auto r=rule(0,2.0,{{0,3}},{});m.population_rules={r};PopulationSimulator s(m);NEAR(s.propensity(r),40.0,1e-12);}
void insufficient_population_zero_propensity(){auto m=base();m.initial_populations={{0,1}};auto r=rule(0,10,{{0,2}},{});m.population_rules={r};PopulationSimulator s(m);E(s.propensity(r),0.0);}
void source_reaction_constant_propensity(){auto m=base();auto r=rule(0,4.5,{},{{0,1}});m.population_rules={r};PopulationSimulator s(m);NEAR(s.propensity(r),4.5,1e-12);}
void unsupported_rate_law_throws(){auto m=base();auto r=rule(0,1,{{0,1}},{});r.rate_law.kind=RateLawKind::GlobalFunction;m.population_rules={r};PopulationSimulator s(m);THROWS(s.propensity(r));}

void apply_unary_decay(){auto m=base();m.initial_populations={{0,3}};auto r=rule(0,1,{{0,1}},{});m.population_rules={r};PopulationSimulator s(m);C(s.fire(r));E(s.state().count(0),2u);}
void apply_conversion_conserves_total(){auto m=base();m.initial_populations={{0,10},{1,0}};auto r=rule(0,1,{{0,1}},{{1,1}});m.population_rules={r};PopulationSimulator s(m);for(int i=0;i<10;++i)C(s.fire(r));E(s.state().count(0),0u);E(s.state().count(1),10u);}
void failed_fire_is_atomic(){auto m=base();m.initial_populations={{0,1},{1,4}};auto r=rule(0,1,{{0,2}},{{1,9}});m.population_rules={r};PopulationSimulator s(m);C(!s.fire(r));E(s.state().count(0),1u);E(s.state().count(1),4u);}
void duplicate_stoich_terms_are_combined(){auto m=base();m.initial_populations={{0,5}};auto r=rule(0,1,{{0,1},{0,1}},{});m.population_rules={r};PopulationSimulator s(m);NEAR(s.propensity(r),10.0,1e-12);C(s.fire(r));E(s.state().count(0),3u);}

void exact_run_decay_exhausts(){auto m=base();m.initial_populations={{0,25}};m.population_rules={rule(0,1,{{0,1}},{})};PopulationSimulator s(m);auto out=s.run(1000,1e9,7);E(out.events,25u);C(out.exhausted);E(s.state().count(0),0u);}
void exact_run_conversion_exhausts(){auto m=base();m.initial_populations={{0,30},{1,0}};m.population_rules={rule(0,1,{{0,1}},{{1,1}})};PopulationSimulator s(m);auto out=s.run(1000,1e9,8);E(out.events,30u);E(s.state().count(0),0u);E(s.state().count(1),30u);C(out.exhausted);}
void source_run_respects_event_limit(){auto m=base();m.population_rules={rule(0,2,{},{{0,1}})};PopulationSimulator s(m);auto out=s.run(17,1e9,9);E(out.events,17u);E(s.state().count(0),17u);C(!out.exhausted);}
void run_reproducible(){auto m=base();m.initial_populations={{0,20},{1,0}};m.population_rules={rule(0,1,{{0,1}},{{1,1}}),rule(1,.2,{{1,1}},{{0,1}})};PopulationSimulator a(m),b(m);auto x=a.run(50,100,42,3,true),y=b.run(50,100,42,3,true);E(x.events,y.events);E(x.trace.size(),y.trace.size());E(a.state().count(0),b.state().count(0));E(a.state().count(1),b.state().count(1));for(size_t i=0;i<x.trace.size();++i){E(x.trace[i].rule,y.trace[i].rule);E(x.trace[i].time,y.trace[i].time);}}
void trajectory_id_changes_stream(){auto m=base();m.initial_populations={{0,20},{1,0}};m.population_rules={rule(0,1,{{0,1}},{{1,1}}),rule(1,.2,{{1,1}},{{0,1}})};PopulationSimulator a(m),b(m);auto x=a.run(20,100,42,0,true),y=b.run(20,100,42,1,true);C(!x.trace.empty()&&!y.trace.empty());C(x.trace[0].time!=y.trace[0].time);}
void time_limit_does_not_fire_past_limit(){auto m=base();m.initial_populations={{0,100}};m.population_rules={rule(0,1,{{0,1}},{})};PopulationSimulator s(m);auto out=s.run(1000,0.0000001,1);E(out.time,0.0000001);E(out.events,0u);E(s.state().count(0),100u);}

void validator_rejects_unknown_stoich_type(){auto m=base();m.population_rules={rule(0,1,{{99,1}},{{0,1}})};auto v=ModelValidator::validate(m);C(ModelValidator::hasError(v,"unknown_population_type"));}
void validator_rejects_zero_stoich(){auto m=base();m.population_rules={rule(0,1,{{0,0}},{{1,1}})};auto v=ModelValidator::validate(m);C(ModelValidator::hasError(v,"zero_stoichiometry"));}
void validator_rejects_particle_type_in_population_rule(){auto m=base();m.molecule_types[0].storage=StorageKind::Particle;m.population_rules={rule(0,1,{{0,1}},{{1,1}})};auto v=ModelValidator::validate(m);C(ModelValidator::hasError(v,"particle_type_in_population_rule"));}
void validator_rejects_duplicate_population_rule_id(){auto m=base();m.population_rules={rule(2,1,{},{{0,1}}),rule(2,1,{},{{1,1}})};auto v=ModelValidator::validate(m);C(ModelValidator::hasError(v,"duplicate_population_rule_id"));}
void validator_rejects_negative_population_rate(){auto m=base();m.population_rules={rule(0,-1,{},{{0,1}})};auto v=ModelValidator::validate(m);C(ModelValidator::hasError(v,"negative_rate"));}

void fingerprint_tracks_storage_kind(){auto m=base();auto h=m.fingerprint();m.molecule_types[0].storage=StorageKind::Particle;C(h!=m.fingerprint());}
void fingerprint_tracks_population_counts(){auto m=base();m.initial_populations={{0,1}};auto h=m.fingerprint();m.initial_populations[0].count=2;C(h!=m.fingerprint());}
void fingerprint_tracks_population_rules(){auto m=base();m.population_rules={rule(0,1,{{0,1}},{{1,1}})};auto h=m.fingerprint();m.population_rules[0].reactants[0].stoich=2;C(h!=m.fingerprint());}
void cache_roundtrip(){auto m=base();m.initial_populations={{0,12},{1,3}};m.population_rules={rule(0,.7,{{0,2}},{{1,1}})};const char* p="/tmp/nfnext_population.nfir";ModelCache::save(m,p);auto x=ModelCache::load(p);std::remove(p);E(x.fingerprint(),m.fingerprint());E(x.initial_populations.size(),2u);E(x.population_rules.size(),1u);E(x.molecule_types[0].storage,StorageKind::Population);E(x.population_rules[0].reactants[0].stoich,2u);}

struct T{const char*n;void(*f)();};T ts[]={
{"init",store_initializes_counts},{"unknown",store_unknown_type_throws},{"set add",store_set_and_add},{"underflow",store_underflow_is_atomic},
{"dup init",duplicate_initial_counts_rejected},{"pop as particle",particle_initialization_for_population_type_rejected},{"particle as pop",population_initialization_for_particle_type_rejected},
{"unary prop",unary_propensity},{"binary prop",binary_distinct_propensity},{"dimer prop",same_species_dimer_propensity_uses_combinations},{"trimer prop",same_species_trimer_propensity},{"insufficient",insufficient_population_zero_propensity},{"source",source_reaction_constant_propensity},{"unsupported",unsupported_rate_law_throws},
{"fire",apply_unary_decay},{"conversion",apply_conversion_conserves_total},{"failed atomic",failed_fire_is_atomic},{"combine",duplicate_stoich_terms_are_combined},
{"run decay",exact_run_decay_exhausts},{"run convert",exact_run_conversion_exhausts},{"run source",source_run_respects_event_limit},{"repro",run_reproducible},{"traj",trajectory_id_changes_stream},{"time",time_limit_does_not_fire_past_limit},
{"unknown stoich",validator_rejects_unknown_stoich_type},{"zero stoich",validator_rejects_zero_stoich},{"particle term",validator_rejects_particle_type_in_population_rule},{"dup rule",validator_rejects_duplicate_population_rule_id},{"neg rate",validator_rejects_negative_population_rate},
{"fp storage",fingerprint_tracks_storage_kind},{"fp count",fingerprint_tracks_population_counts},{"fp rule",fingerprint_tracks_population_rules},{"cache",cache_roundtrip}
};}
int main(){for(auto&t:ts){try{t.f();}catch(const std::exception&e){++failures;std::cerr<<t.n<<": "<<e.what()<<'\n';}catch(...){++failures;}}std::cout<<"population tests: "<<sizeof(ts)/sizeof(ts[0])<<" cases, "<<checks<<" checks, "<<failures<<" failures\n";return failures?1:0;}
