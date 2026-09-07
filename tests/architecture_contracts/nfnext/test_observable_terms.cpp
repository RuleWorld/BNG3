#include "nfnext/cache.hpp"
#include "nfnext/generic_state.hpp"
#include "nfnext/observable.hpp"
#include "nfnext/validation.hpp"
#include "nfnext/xml_import.hpp"

#include <cstdio>
#include <iostream>
#include <string>
#include <vector>

using namespace nfnext;
namespace {
int failures=0, checks=0;
void fail(const char* e,int l){++failures;std::cerr<<"line "<<l<<": "<<e<<'\n';}
#define C(x) do{++checks;if(!(x))fail(#x,__LINE__);}while(0)
#define E(a,b) do{++checks;if(!((a)==(b)))fail(#a " == " #b,__LINE__);}while(0)

ModelIR baseModel(){
    ModelIR m;
    MoleculeTypeIR a; a.id=0; a.name="A"; a.sites={SiteSpec{"x",{"u","p"}}};
    MoleculeTypeIR b; b.id=1; b.name="B"; b.sites={SiteSpec{"y",{}}};
    m.molecule_types={a,b};
    return m;
}
ObservableTermIR term(TypeId type, PredicateKind kind=PredicateKind::SiteFree, int value=0){
    ObservableTermIR t; t.pattern.nodes={PatternNodeIR{0,type,0,0}};
    PredicateIR p; p.kind=kind; p.molecule_type=type; p.site=0; p.node=0; p.value=value;
    t.predicates.push_back(p); return t;
}

std::string xmlTwoPatterns(const std::string& type="Molecules"){
return std::string(R"XML(<sbml><model id="obs">
<ListOfParameters/>
<ListOfMoleculeTypes>
 <MoleculeType id="A"><ListOfComponentTypes><ComponentType id="x"><ListOfAllowedStates><AllowedState id="u"/><AllowedState id="p"/></ListOfAllowedStates></ComponentType></ListOfComponentTypes></MoleculeType>
</ListOfMoleculeTypes>
<ListOfSpecies>
 <Species id="S0" concentration="2"><ListOfMolecules><Molecule id="S0_M1" name="A"><ListOfComponents><Component id="S0_C" name="x" state="u" numberOfBonds="0"/></ListOfComponents></Molecule></ListOfMolecules></Species>
 <Species id="S1" concentration="3"><ListOfMolecules><Molecule id="S1_M1" name="A"><ListOfComponents><Component id="S1_C" name="x" state="p" numberOfBonds="0"/></ListOfComponents></Molecule></ListOfMolecules></Species>
</ListOfSpecies>
<ListOfReactionRules/>
<ListOfObservables><Observable id="O" name="total" type=")XML")+type+R"XML("><ListOfPatterns>
 <Pattern id="P0"><ListOfMolecules><Molecule id="P0_M1" name="A"><ListOfComponents><Component id="P0_C" name="x" state="u"/></ListOfComponents></Molecule></ListOfMolecules></Pattern>
 <Pattern id="P1"><ListOfMolecules><Molecule id="P1_M1" name="A"><ListOfComponents><Component id="P1_C" name="x" state="p"/></ListOfComponents></Molecule></ListOfMolecules></Pattern>
</ListOfPatterns></Observable></ListOfObservables>
</model></sbml>)XML";
}

void evaluator_sums_disjoint_molecule_terms(){
    auto m=baseModel(); GenericGraphState g(m);
    auto a=g.create(0), b=g.create(0), c=g.create(0); g.setSiteState(a,0,0);g.setSiteState(b,0,1);g.setSiteState(c,0,1);
    ObservableIR o; o.mode=ObservableMode::Molecules;
    o.terms={term(0,PredicateKind::SiteStateEq,0),term(0,PredicateKind::SiteStateEq,1)};
    E(ObservableEvaluator::evaluate(g,o),3u);
}
void evaluator_preserves_legacy_overlap_multiplicity(){
    auto m=baseModel(); GenericGraphState g(m); auto a=g.create(0); g.setSiteState(a,0,0);
    ObservableIR o; o.mode=ObservableMode::Molecules;
    o.terms={term(0,PredicateKind::SiteStateEq,0),term(0,PredicateKind::SiteFree)};
    // NFsim MoleculesObservable tests each template separately, so one molecule can contribute to multiple terms.
    E(ObservableEvaluator::evaluate(g,o),2u);
}
void evaluator_sums_species_terms(){
    auto m=baseModel(); GenericGraphState g(m); auto a=g.create(0), b=g.create(0), c=g.create(0); g.bind(a,0,b,0);
    ObservableIR o; o.mode=ObservableMode::Complexes;
    o.terms={term(0,PredicateKind::SiteBound),term(0,PredicateKind::SiteFree)};
    // Bound A-containing complex contributes one to first term; free A complex contributes one to second.
    E(ObservableEvaluator::evaluate(g,o),2u); (void)c;
}
void species_overlap_counts_each_pattern(){
    auto m=baseModel(); GenericGraphState g(m); auto a=g.create(0);
    ObservableIR o; o.mode=ObservableMode::Complexes;
    o.terms={term(0,PredicateKind::SiteFree),term(0,PredicateKind::SiteFree)};
    E(ObservableEvaluator::evaluate(g,o),2u); (void)a;
}
void legacy_single_term_remains_supported(){
    auto m=baseModel(); GenericGraphState g(m); g.create(0);g.create(0);
    ObservableIR o; o.mode=ObservableMode::Molecules; o.pattern.nodes={PatternNodeIR{0,0,0,0}};
    E(ObservableEvaluator::evaluate(g,o),2u);
}
void empty_terms_with_empty_legacy_pattern_counts_zero(){
    auto m=baseModel(); GenericGraphState g(m); g.create(0);
    ObservableIR o; o.mode=ObservableMode::Molecules;
    E(ObservableEvaluator::evaluate(g,o),0u);
}
void validator_checks_each_term(){
    auto m=baseModel(); ObservableIR o; o.name="bad"; auto t=term(0); t.pattern.nodes[0].molecule_type=99; o.terms.push_back(t); m.observables.push_back(o);
    auto issues=ModelValidator::validate(m); C(ModelValidator::hasError(issues,"unknown_molecule_type"));
}
void validator_checks_term_predicate_node(){
    auto m=baseModel(); ObservableIR o; auto t=term(0); t.predicates[0].node=4; o.terms.push_back(t); m.observables.push_back(o);
    auto issues=ModelValidator::validate(m); C(ModelValidator::hasError(issues,"unknown_predicate_node"));
}
void fingerprint_changes_when_second_term_changes(){
    auto m=baseModel(); ObservableIR o; o.name="o";o.terms={term(0,PredicateKind::SiteStateEq,0),term(0,PredicateKind::SiteStateEq,1)};m.observables.push_back(o);
    auto h=m.fingerprint();m.observables[0].terms[1].predicates[0].value=0;C(h!=m.fingerprint());
}
void cache_roundtrip_preserves_terms(){
    auto m=baseModel(); ObservableIR o;o.name="o";o.mode=ObservableMode::Molecules;o.terms={term(0,PredicateKind::SiteStateEq,0),term(0,PredicateKind::SiteStateEq,1)};m.observables.push_back(o);
    const char* path="/tmp/nfnext_observable_terms.nfir";ModelCache::save(m,path);auto x=ModelCache::load(path);std::remove(path);
    E(x.observables.size(),1u);E(x.observables[0].terms.size(),2u);E(x.fingerprint(),m.fingerprint());
}
void xml_imports_two_molecule_patterns(){
    auto r=NfXmlImporter::parseString(xmlTwoPatterns(),"multiobs.xml");C(r.ok());E(r.model.observables.size(),1u);if(r.model.observables.empty())return;
    E(r.model.observables[0].terms.size(),2u);E(r.model.observables[0].mode,ObservableMode::Molecules);
}
void xml_imported_molecule_terms_evaluate_like_legacy(){
    auto r=NfXmlImporter::parseString(xmlTwoPatterns(),"multiobs-eval.xml");C(r.ok());if(!r.ok())return;
    GenericGraphState g(r.model);for(const auto& p:r.model.initial_particles){auto id=g.create(p.molecule_type);for(std::size_t s=0;s<p.site_states.size();++s)g.setSiteState(id,(std::uint16_t)s,p.site_states[s]);}
    E(ObservableEvaluator::evaluate(g,r.model.observables[0]),5u);
}
void xml_imports_two_species_patterns(){
    auto r=NfXmlImporter::parseString(xmlTwoPatterns("Species"),"multi-species.xml");C(r.ok());E(r.model.observables.size(),1u);if(r.model.observables.empty())return;
    E(r.model.observables[0].terms.size(),2u);E(r.model.observables[0].mode,ObservableMode::Complexes);
}
void xml_imported_species_terms_evaluate(){
    auto r=NfXmlImporter::parseString(xmlTwoPatterns("Species"),"multi-species-eval.xml");C(r.ok());if(!r.ok())return;
    GenericGraphState g(r.model);for(const auto& p:r.model.initial_particles){auto id=g.create(p.molecule_type);for(std::size_t s=0;s<p.site_states.size();++s)g.setSiteState(id,(std::uint16_t)s,p.site_states[s]);}
    E(ObservableEvaluator::evaluate(g,r.model.observables[0]),5u);
}
void xml_rejects_observable_without_patterns(){
    auto x=xmlTwoPatterns(); auto begin=x.find("<Pattern id=\"P0\""); auto end=x.find("</ListOfPatterns>"); C(begin!=std::string::npos&&end!=std::string::npos); if(begin==std::string::npos||end==std::string::npos)return;
    x.erase(begin,end-begin);auto r=NfXmlImporter::parseString(x,"emptyobs.xml");C(!r.ok());C(r.hasError("empty_observable_patterns"));
}
void evaluate_all_handles_multi_terms(){
    auto m=baseModel(); GenericGraphState g(m);g.create(0);g.create(0);
    ObservableIR a;a.mode=ObservableMode::Molecules;a.terms={term(0),term(0)};ObservableIR b;b.mode=ObservableMode::Molecules;b.terms={term(0)};
    auto v=ObservableEvaluator::evaluateAll(g,{a,b});E(v.size(),2u);E(v[0],4u);E(v[1],2u);
}

struct T{const char* n;void(*f)();};
T tests[]={
{"molecules disjoint",evaluator_sums_disjoint_molecule_terms},{"molecules overlap",evaluator_preserves_legacy_overlap_multiplicity},
{"species terms",evaluator_sums_species_terms},{"species overlap",species_overlap_counts_each_pattern},{"legacy",legacy_single_term_remains_supported},
{"empty",empty_terms_with_empty_legacy_pattern_counts_zero},{"validate term",validator_checks_each_term},{"validate node",validator_checks_term_predicate_node},
{"fingerprint",fingerprint_changes_when_second_term_changes},{"cache",cache_roundtrip_preserves_terms},{"xml molecules",xml_imports_two_molecule_patterns},
{"xml molecules eval",xml_imported_molecule_terms_evaluate_like_legacy},{"xml species",xml_imports_two_species_patterns},{"xml species eval",xml_imported_species_terms_evaluate},
{"xml no patterns",xml_rejects_observable_without_patterns},{"all",evaluate_all_handles_multi_terms}
};
}
int main(){for(auto& t:tests){try{t.f();}catch(const std::exception& e){++failures;std::cerr<<t.n<<": "<<e.what()<<'\n';}catch(...){++failures;}}std::cout<<"observable-term tests: "<<sizeof(tests)/sizeof(tests[0])<<" cases, "<<checks<<" checks, "<<failures<<" failures\n";return failures?1:0;}
