#include "nfnext/cache.hpp"
#include "nfnext/compiler.hpp"
#include "nfnext/generic_sim.hpp"
#include "nfnext/generic_state.hpp"
#include "nfnext/matcher.hpp"
#include "nfnext/rule_family.hpp"
#include "nfnext/validation.hpp"
#include "nfnext/xml_import.hpp"

#include <algorithm>
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>

using namespace nfnext;

namespace {
int failures = 0;
int checks = 0;

void fail(const char* expr, int line) {
    ++failures;
    std::cerr << "line " << line << ": " << expr << '\n';
}

#define CHECK(x) do { ++checks; if (!(x)) fail(#x, __LINE__); } while (0)
#define CHECK_EQ(a,b) do { ++checks; if (!((a)==(b))) fail(#a " == " #b, __LINE__); } while (0)

ModelIR modelWithStates() {
    ModelIR m;
    MoleculeTypeIR t;
    t.id = 0;
    t.name = "A";
    t.sites = {SiteSpec{"x", {"u", "p", "q", "r"}}};
    m.molecule_types.push_back(t);
    return m;
}

PredicateIR setPredicate(PatternNodeId node, std::initializer_list<int> values) {
    PredicateIR p;
    p.kind = PredicateKind::SiteStateInSet;
    p.molecule_type = 0;
    p.site = 0;
    p.node = node;
    p.values.assign(values.begin(), values.end());
    return p;
}

std::string stateSetXml(const std::string& state_set,
                        const std::string& extra = {}) {
    return std::string(R"XML(<sbml><model id="stateset">
<ListOfParameters><Parameter id="k" value="1"/></ListOfParameters>
<ListOfMoleculeTypes>
  <MoleculeType id="A">
    <ListOfComponentTypes>
      <ComponentType id="x">
        <ListOfAllowedStates>
          <AllowedState id="u"/>
          <AllowedState id="p"/>
          <AllowedState id="q"/>
          <AllowedState id="r"/>
        </ListOfAllowedStates>
      </ComponentType>
    </ListOfComponentTypes>
  </MoleculeType>
</ListOfMoleculeTypes>
<ListOfSpecies>
  <Species id="S" concentration="4">
    <ListOfMolecules>
      <Molecule id="S_M1" name="A">
        <ListOfComponents><Component id="S_C" name="x" state="u" numberOfBonds="0"/></ListOfComponents>
      </Molecule>
    </ListOfMolecules>
  </Species>
</ListOfSpecies>
<ListOfReactionRules>
  <ReactionRule id="R" name="select">
    <ListOfReactantPatterns>
      <ReactantPattern id="RP">
        <ListOfMolecules>
          <Molecule id="RP_M1" name="A">
            <ListOfComponents>
              <Component id="RP_C" name="x" stateSet=")XML") + state_set + "\" " + extra + R"XML(/>
            </ListOfComponents>
          </Molecule>
        </ListOfMolecules>
      </ReactantPattern>
    </ListOfReactantPatterns>
    <RateLaw type="Ele"><ListOfRateConstants><RateConstant value="k"/></ListOfRateConstants></RateLaw>
    <ListOfOperations><StateChange site="RP_C" finalState="r"/></ListOfOperations>
  </ReactionRule>
</ListOfReactionRules>
</model></sbml>)XML";
}

void stateset_match_accepts_each_member() {
    auto m = modelWithStates();
    GenericGraphState g(m);
    auto a = g.create(0), b = g.create(0), c = g.create(0), d = g.create(0);
    g.setSiteState(a,0,0);
    g.setSiteState(b,0,1);
    g.setSiteState(c,0,2);
    g.setSiteState(d,0,3);

    PatternGraphIR pattern;
    pattern.nodes = {PatternNodeIR{0,0,0,0}};
    auto matches = PatternMatcher::findMatches(g, pattern, {setPredicate(0,{0,2})});

    CHECK_EQ(matches.size(),2u);
    std::vector<ParticleId> ids;
    for (const auto& match : matches) ids.push_back(match.at(0));
    CHECK(std::find(ids.begin(),ids.end(),a)!=ids.end());
    CHECK(std::find(ids.begin(),ids.end(),c)!=ids.end());
    CHECK(std::find(ids.begin(),ids.end(),b)==ids.end());
    CHECK(std::find(ids.begin(),ids.end(),d)==ids.end());
}

void stateset_local_match_works() {
    auto m = modelWithStates();
    GenericGraphState g(m);
    auto a = g.create(0);
    g.setSiteState(a,0,2);
    CHECK(g.matchesLocal(a,{setPredicate(0,{1,2})}));
    CHECK(!g.matchesLocal(a,{setPredicate(0,{0,3})}));
}

void stateset_validator_accepts_unique_valid_values() {
    auto m = modelWithStates();
    ExpandedRuleIR r;
    r.id = 0;
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}};
    r.predicates = {setPredicate(0,{0,2,3})};
    m.expanded_rules.push_back(r);
    auto issues = ModelValidator::validate(m);
    CHECK(!ModelValidator::hasError(issues));
}

void stateset_validator_rejects_empty_set() {
    auto m = modelWithStates();
    ExpandedRuleIR r;
    r.id = 0;
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}};
    r.predicates = {setPredicate(0,{})};
    m.expanded_rules.push_back(r);
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues,"empty_state_set"));
}

void stateset_validator_rejects_duplicate_values() {
    auto m = modelWithStates();
    ExpandedRuleIR r;
    r.id = 0;
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}};
    r.predicates = {setPredicate(0,{0,2,2})};
    m.expanded_rules.push_back(r);
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues,"duplicate_state_set_value"));
}

void stateset_validator_rejects_out_of_range_value() {
    auto m = modelWithStates();
    ExpandedRuleIR r;
    r.id = 0;
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}};
    r.predicates = {setPredicate(0,{0,9})};
    m.expanded_rules.push_back(r);
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues,"invalid_state"));
}

void stateset_xml_parses_names_to_indices() {
    auto result = NfXmlImporter::parseString(stateSetXml("u,q"),"stateset.xml");
    CHECK(result.ok());
    CHECK_EQ(result.model.expanded_rules.size(),1u);
    if (result.model.expanded_rules.empty()) return;

    const auto& predicates = result.model.expanded_rules[0].predicates;
    auto it = std::find_if(predicates.begin(),predicates.end(),[](const PredicateIR& p){
        return p.kind == PredicateKind::SiteStateInSet;
    });
    CHECK(it != predicates.end());
    if (it == predicates.end()) return;
    CHECK_EQ(it->values.size(),2u);
    CHECK_EQ(it->values[0],0);
    CHECK_EQ(it->values[1],2);
}

void stateset_xml_trims_whitespace() {
    auto result = NfXmlImporter::parseString(stateSetXml(" u , q , r "),"spaces.xml");
    CHECK(result.ok());
    const auto& predicates = result.model.expanded_rules[0].predicates;
    auto it = std::find_if(predicates.begin(),predicates.end(),[](const PredicateIR& p){return p.kind==PredicateKind::SiteStateInSet;});
    CHECK(it != predicates.end());
    if (it != predicates.end()) CHECK_EQ(it->values.size(),3u);
}

void stateset_xml_rejects_unknown_state() {
    auto result = NfXmlImporter::parseString(stateSetXml("u,nope"),"unknown.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("unknown_state"));
    CHECK(result.model.expanded_rules.empty());
}

void stateset_xml_rejects_duplicate_state() {
    auto result = NfXmlImporter::parseString(stateSetXml("u,q,u"),"duplicate.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("duplicate_state_set_value"));
}

void stateset_xml_rejects_empty_entry() {
    auto result = NfXmlImporter::parseString(stateSetXml("u,,q"),"empty-entry.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("empty_state_set_entry"));
}

void stateset_xml_rejects_empty_set() {
    auto result = NfXmlImporter::parseString(stateSetXml(""),"empty-set.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("empty_state_set"));
}

void stateset_xml_rejects_state_and_stateset_together() {
    auto result = NfXmlImporter::parseString(stateSetXml("u,q","state=\"u\""),"both.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("state_and_state_set"));
}

void stateset_cache_roundtrip_preserves_values() {
    auto m = modelWithStates();
    ExpandedRuleIR r;
    r.id = 0;
    r.name = "set";
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}};
    r.predicates = {setPredicate(0,{0,2,3})};
    m.expanded_rules.push_back(r);

    const std::string path = "/tmp/nfnext_stateset.nfir";
    ModelCache::save(m,path);
    auto loaded = ModelCache::load(path);
    std::remove(path.c_str());

    CHECK_EQ(loaded.expanded_rules.size(),1u);
    CHECK_EQ(loaded.expanded_rules[0].predicates.size(),1u);
    CHECK_EQ(loaded.expanded_rules[0].predicates[0].kind,PredicateKind::SiteStateInSet);
    CHECK_EQ(loaded.expanded_rules[0].predicates[0].values.size(),3u);
    CHECK_EQ(loaded.fingerprint(),m.fingerprint());
}

void stateset_fingerprint_changes_with_membership() {
    auto m = modelWithStates();
    ExpandedRuleIR r;
    r.id = 0;
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}};
    r.predicates = {setPredicate(0,{0,2})};
    m.expanded_rules.push_back(r);
    const auto a = m.fingerprint();
    m.expanded_rules[0].predicates[0].values.push_back(3);
    CHECK(a != m.fingerprint());
}

void stateset_family_shape_differs_if_set_differs() {
    ExpandedRuleIR a,b;
    a.id=0; b.id=1;
    a.name="family_1"; b.name="family_2";
    a.rate=b.rate=1;
    a.pattern.nodes={PatternNodeIR{0,0,0,0}};
    b.pattern.nodes=a.pattern.nodes;
    a.predicates={setPredicate(0,{0,1})};
    b.predicates={setPredicate(0,{0,2})};
    auto result=collapseIndexedRuleFamilies({a,b});
    CHECK_EQ(result.families.size(),2u);
}

void stateset_dependency_index_registers_members() {
    auto m = modelWithStates();
    RuleFamilyIR f;
    f.id=0;
    f.predicates={setPredicate(0,{0,2,3})};
    m.rule_families.push_back(f);
    ModelCompiler::buildDependencies(m);
    CHECK_EQ(m.dependencies.feature_to_families.size(),3u);
    CHECK(m.dependencies.feature_to_families.count(encodeFeature(0,0,PredicateKind::SiteStateInSet,0))==1);
    CHECK(m.dependencies.feature_to_families.count(encodeFeature(0,0,PredicateKind::SiteStateInSet,2))==1);
    CHECK(m.dependencies.feature_to_families.count(encodeFeature(0,0,PredicateKind::SiteStateInSet,3))==1);
}

void stateset_imported_rule_executes_only_matching_particles() {
    auto result=NfXmlImporter::parseString(stateSetXml("u,q"),"execute.xml");
    CHECK(result.ok());
    // Initial particles are all u, therefore all four initially match.
    GenericSimulator sim(result.model);
    auto run=sim.run(4,100,9,0,true);
    CHECK_EQ(run.events,4u);
    auto live=sim.state().liveParticles(0);
    CHECK_EQ(live.size(),4u);
    for(auto id:live) CHECK_EQ(sim.state().siteState(id,0),3);
}

struct Test { const char* name; void(*fn)(); };
const Test tests[] = {
    {"match members",stateset_match_accepts_each_member},
    {"local match",stateset_local_match_works},
    {"validator valid",stateset_validator_accepts_unique_valid_values},
    {"validator empty",stateset_validator_rejects_empty_set},
    {"validator duplicate",stateset_validator_rejects_duplicate_values},
    {"validator range",stateset_validator_rejects_out_of_range_value},
    {"xml parse",stateset_xml_parses_names_to_indices},
    {"xml trim",stateset_xml_trims_whitespace},
    {"xml unknown",stateset_xml_rejects_unknown_state},
    {"xml duplicate",stateset_xml_rejects_duplicate_state},
    {"xml empty entry",stateset_xml_rejects_empty_entry},
    {"xml empty set",stateset_xml_rejects_empty_set},
    {"xml state plus set",stateset_xml_rejects_state_and_stateset_together},
    {"cache",stateset_cache_roundtrip_preserves_values},
    {"fingerprint",stateset_fingerprint_changes_with_membership},
    {"family",stateset_family_shape_differs_if_set_differs},
    {"dependencies",stateset_dependency_index_registers_members},
    {"execute",stateset_imported_rule_executes_only_matching_particles},
};
}

int main() {
    for(const auto& test:tests) {
        try { test.fn(); }
        catch(const std::exception& e) { ++failures; std::cerr<<test.name<<": "<<e.what()<<'\n'; }
        catch(...) { ++failures; std::cerr<<test.name<<": unknown exception\n"; }
    }
    std::cout<<"stateSet tests: "<<sizeof(tests)/sizeof(tests[0])<<" cases, "<<checks<<" checks, "<<failures<<" failures\n";
    return failures?1:0;
}
