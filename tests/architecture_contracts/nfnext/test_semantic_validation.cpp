#include "nfnext/cache.hpp"
#include "nfnext/compiler.hpp"
#include "nfnext/differential.hpp"
#include "nfnext/generic_sim.hpp"
#include "nfnext/generic_state.hpp"
#include "nfnext/legacy_adapter.hpp"
#include "nfnext/matcher.hpp"
#include "nfnext/observable.hpp"
#include "nfnext/transforms.hpp"
#include "nfnext/validation.hpp"
#include "nfnext/xml_import.hpp"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace nfnext;

namespace {

int failures = 0;
int checks = 0;

void fail(const char* expr, const char* file, int line, const std::string& detail = {}) {
    ++failures;
    std::cerr << file << ':' << line << ": CHECK failed: " << expr;
    if (!detail.empty()) std::cerr << " (" << detail << ')';
    std::cerr << '\n';
}

#define CHECK(x) do { ++checks; if (!(x)) fail(#x, __FILE__, __LINE__); } while (0)
#define CHECK_EQ(a,b) do { ++checks; const auto _a=(a); const auto _b=(b); if (!(_a==_b)) fail(#a " == " #b, __FILE__, __LINE__); } while (0)
#define CHECK_NE(a,b) do { ++checks; const auto _a=(a); const auto _b=(b); if ((_a==_b)) fail(#a " != " #b, __FILE__, __LINE__); } while (0)
#define CHECK_NEAR(a,b,eps) do { ++checks; const double _a=(a), _b=(b), _e=(eps); if (std::fabs(_a-_b)>_e) { std::ostringstream _o; _o << _a << " vs " << _b; fail(#a " ~= " #b, __FILE__, __LINE__, _o.str()); } } while (0)
#define CHECK_THROW(stmt, ex) do { ++checks; bool _ok=false; try { stmt; } catch (const ex&) { _ok=true; } catch (...) {} if (!_ok) fail("throws " #ex ": " #stmt, __FILE__, __LINE__); } while (0)

ModelIR oneTypeModel(std::size_t sites = 2) {
    ModelIR m;
    m.model_name = "one-type";
    MoleculeTypeIR mt;
    mt.id = 0;
    mt.name = "A";
    if (sites >= 1) mt.sites.push_back(SiteSpec{"x", {"u", "p"}});
    if (sites >= 2) mt.sites.push_back(SiteSpec{"b", {}});
    for (std::size_t i = 2; i < sites; ++i) mt.sites.push_back(SiteSpec{"s" + std::to_string(i), {}});
    m.molecule_types.push_back(mt);
    return m;
}

PredicateIR statePred(PatternNodeId node, std::uint16_t site, int state) {
    PredicateIR p;
    p.kind = PredicateKind::SiteStateEq;
    p.molecule_type = 0;
    p.site = site;
    p.value = state;
    p.node = node;
    return p;
}

PredicateIR freePred(PatternNodeId node, std::uint16_t site) {
    PredicateIR p;
    p.kind = PredicateKind::SiteFree;
    p.molecule_type = 0;
    p.site = site;
    p.node = node;
    return p;
}

PredicateIR boundPred(PatternNodeId node, std::uint16_t site) {
    PredicateIR p;
    p.kind = PredicateKind::SiteBound;
    p.molecule_type = 0;
    p.site = site;
    p.node = node;
    return p;
}

ActionIR setAction(PatternNodeId node, std::uint16_t site, int state) {
    ActionIR a;
    a.kind = ActionKind::SetSiteState;
    a.molecule_type = 0;
    a.target_node = node;
    a.site = site;
    a.value = state;
    return a;
}

ActionIR bindAction(PatternNodeId lhs, std::uint16_t lhs_site,
                    PatternNodeId rhs, std::uint16_t rhs_site) {
    ActionIR a;
    a.kind = ActionKind::Bind;
    a.molecule_type = 0;
    a.target_node = lhs;
    a.site = lhs_site;
    a.partner_node = rhs;
    a.partner_site = rhs_site;
    return a;
}

ActionIR unbindAction(PatternNodeId node, std::uint16_t site) {
    ActionIR a;
    a.kind = ActionKind::Unbind;
    a.molecule_type = 0;
    a.target_node = node;
    a.site = site;
    return a;
}

std::string minimalXml(const std::string& rate = "k") {
    return std::string(R"XML(<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3" level="3" version="1">
  <model id="mini">
    <ListOfParameters>
      <Parameter id="k" type="Constant" value="2.5"/>
    </ListOfParameters>
    <ListOfMoleculeTypes>
      <MoleculeType id="A">
        <ListOfComponentTypes>
          <ComponentType id="x">
            <ListOfAllowedStates>
              <AllowedState id="u"/>
              <AllowedState id="p"/>
            </ListOfAllowedStates>
          </ComponentType>
          <ComponentType id="b"/>
        </ListOfComponentTypes>
      </MoleculeType>
    </ListOfMoleculeTypes>
    <ListOfSpecies>
      <Species id="S1" concentration="2" name="A(x~u,b)">
        <ListOfMolecules>
          <Molecule id="S1_M1" name="A">
            <ListOfComponents>
              <Component id="S1_M1_C1" name="x" state="u" numberOfBonds="0"/>
              <Component id="S1_M1_C2" name="b" numberOfBonds="0"/>
            </ListOfComponents>
          </Molecule>
        </ListOfMolecules>
      </Species>
    </ListOfSpecies>
    <ListOfReactionRules>
      <ReactionRule id="RR1" name="phos">
        <ListOfReactantPatterns>
          <ReactantPattern id="RR1_RP1">
            <ListOfMolecules>
              <Molecule id="RR1_RP1_M1" name="A">
                <ListOfComponents>
                  <Component id="RR1_RP1_M1_C1" name="x" state="u" numberOfBonds="0"/>
                </ListOfComponents>
              </Molecule>
            </ListOfMolecules>
          </ReactantPattern>
        </ListOfReactantPatterns>
        <RateLaw id="RR1_RateLaw" type="Ele" totalrate="0">
          <ListOfRateConstants><RateConstant value=")XML") + rate + R"XML("/></ListOfRateConstants>
        </RateLaw>
        <ListOfOperations>
          <StateChange site="RR1_RP1_M1_C1" finalState="p"/>
        </ListOfOperations>
      </ReactionRule>
    </ListOfReactionRules>
    <ListOfObservables>
      <Observable id="O1" name="A_p" type="Molecules">
        <ListOfPatterns>
          <Pattern id="O1_P1">
            <ListOfMolecules>
              <Molecule id="O1_P1_M1" name="A">
                <ListOfComponents>
                  <Component id="O1_P1_M1_C1" name="x" state="p" numberOfBonds="0"/>
                </ListOfComponents>
              </Molecule>
            </ListOfMolecules>
          </Pattern>
        </ListOfPatterns>
      </Observable>
    </ListOfObservables>
  </model>
</sbml>)XML";
}

std::string bindingXml() {
    return R"XML(<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3" level="3" version="1">
  <model id="binding">
    <ListOfParameters>
      <Parameter id="kon" type="Constant" value="10"/>
      <Parameter id="koff" type="Constant" value="5"/>
    </ListOfParameters>
    <ListOfMoleculeTypes>
      <MoleculeType id="A"><ListOfComponentTypes><ComponentType id="b"/></ListOfComponentTypes></MoleculeType>
      <MoleculeType id="B"><ListOfComponentTypes><ComponentType id="a"/></ListOfComponentTypes></MoleculeType>
    </ListOfMoleculeTypes>
    <ListOfSpecies>
      <Species id="SA" concentration="2" name="A(b)">
        <ListOfMolecules><Molecule id="SA_M1" name="A"><ListOfComponents><Component id="SA_M1_C1" name="b" numberOfBonds="0"/></ListOfComponents></Molecule></ListOfMolecules>
      </Species>
      <Species id="SB" concentration="1" name="B(a)">
        <ListOfMolecules><Molecule id="SB_M1" name="B"><ListOfComponents><Component id="SB_M1_C1" name="a" numberOfBonds="0"/></ListOfComponents></Molecule></ListOfMolecules>
      </Species>
    </ListOfSpecies>
    <ListOfReactionRules>
      <ReactionRule id="RR1" name="bind">
        <ListOfReactantPatterns>
          <ReactantPattern id="RR1_RP1"><ListOfMolecules><Molecule id="RR1_RP1_M1" name="A"><ListOfComponents><Component id="RR1_RP1_M1_C1" name="b" numberOfBonds="0"/></ListOfComponents></Molecule></ListOfMolecules></ReactantPattern>
          <ReactantPattern id="RR1_RP2"><ListOfMolecules><Molecule id="RR1_RP2_M1" name="B"><ListOfComponents><Component id="RR1_RP2_M1_C1" name="a" numberOfBonds="0"/></ListOfComponents></Molecule></ListOfMolecules></ReactantPattern>
        </ListOfReactantPatterns>
        <RateLaw id="RR1_RateLaw" type="Ele" totalrate="0"><ListOfRateConstants><RateConstant value="kon"/></ListOfRateConstants></RateLaw>
        <ListOfOperations><AddBond site1="RR1_RP1_M1_C1" site2="RR1_RP2_M1_C1"/></ListOfOperations>
      </ReactionRule>
      <ReactionRule id="RR2" name="unbind">
        <ListOfReactantPatterns>
          <ReactantPattern id="RR2_RP1">
            <ListOfMolecules>
              <Molecule id="RR2_RP1_M1" name="A"><ListOfComponents><Component id="RR2_RP1_M1_C1" name="b" numberOfBonds="1"/></ListOfComponents></Molecule>
              <Molecule id="RR2_RP1_M2" name="B"><ListOfComponents><Component id="RR2_RP1_M2_C1" name="a" numberOfBonds="1"/></ListOfComponents></Molecule>
            </ListOfMolecules>
            <ListOfBonds><Bond id="RR2_RP1_B1" site1="RR2_RP1_M1_C1" site2="RR2_RP1_M2_C1"/></ListOfBonds>
          </ReactantPattern>
        </ListOfReactantPatterns>
        <RateLaw id="RR2_RateLaw" type="Ele" totalrate="0"><ListOfRateConstants><RateConstant value="koff"/></ListOfRateConstants></RateLaw>
        <ListOfOperations><DeleteBond site1="RR2_RP1_M1_C1" site2="RR2_RP1_M2_C1"/></ListOfOperations>
      </ReactionRule>
    </ListOfReactionRules>
    <ListOfObservables>
      <Observable id="O1" name="complex" type="Species">
        <ListOfPatterns>
          <Pattern id="O1_P1">
            <ListOfMolecules>
              <Molecule id="O1_P1_M1" name="A"><ListOfComponents><Component id="O1_P1_M1_C1" name="b" numberOfBonds="1"/></ListOfComponents></Molecule>
              <Molecule id="O1_P1_M2" name="B"><ListOfComponents><Component id="O1_P1_M2_C1" name="a" numberOfBonds="1"/></ListOfComponents></Molecule>
            </ListOfMolecules>
            <ListOfBonds><Bond id="O1_P1_B1" site1="O1_P1_M1_C1" site2="O1_P1_M2_C1"/></ListOfBonds>
          </Pattern>
        </ListOfPatterns>
      </Observable>
    </ListOfObservables>
  </model>
</sbml>)XML";
}

void test_model_validator_accepts_valid_graph() {
    auto m = oneTypeModel();
    ExpandedRuleIR r;
    r.id = 0;
    r.name = "valid";
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}, PatternNodeIR{1,0,0,0}};
    r.pattern.bonds = {PatternBondIR{0,1,1,1}};
    r.predicates = {freePred(0,1), freePred(1,1)};
    r.actions = {bindAction(0,1,1,1)};
    m.expanded_rules.push_back(r);
    auto issues = ModelValidator::validate(m);
    CHECK(issues.empty());
}

void test_model_validator_rejects_duplicate_type_ids() {
    auto m = oneTypeModel();
    m.molecule_types.push_back(m.molecule_types.front());
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues, "duplicate_type_id"));
}

void test_model_validator_rejects_duplicate_node_ids() {
    auto m = oneTypeModel();
    ExpandedRuleIR r;
    r.id = 0;
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}, PatternNodeIR{0,0,0,0}};
    m.expanded_rules.push_back(r);
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues, "duplicate_pattern_node"));
}

void test_model_validator_rejects_dangling_bond_node() {
    auto m = oneTypeModel();
    ExpandedRuleIR r;
    r.id = 0;
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}};
    r.pattern.bonds = {PatternBondIR{0,1,7,1}};
    m.expanded_rules.push_back(r);
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues, "unknown_bond_node"));
}

void test_model_validator_rejects_invalid_bond_site() {
    auto m = oneTypeModel(1);
    ExpandedRuleIR r;
    r.id = 0;
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}, PatternNodeIR{1,0,0,0}};
    r.pattern.bonds = {PatternBondIR{0,4,1,0}};
    m.expanded_rules.push_back(r);
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues, "invalid_site"));
}

void test_model_validator_rejects_unknown_predicate_node() {
    auto m = oneTypeModel();
    ExpandedRuleIR r;
    r.id = 0;
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}};
    r.predicates = {statePred(9,0,0)};
    m.expanded_rules.push_back(r);
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues, "unknown_predicate_node"));
}

void test_model_validator_rejects_unknown_action_node() {
    auto m = oneTypeModel();
    ExpandedRuleIR r;
    r.id = 0;
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}};
    r.actions = {setAction(4,0,1)};
    m.expanded_rules.push_back(r);
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues, "unknown_action_node"));
}

void test_model_validator_rejects_state_out_of_range() {
    auto m = oneTypeModel();
    ExpandedRuleIR r;
    r.id = 0;
    r.pattern.nodes = {PatternNodeIR{0,0,0,0}};
    r.predicates = {statePred(0,0,99)};
    m.expanded_rules.push_back(r);
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues, "invalid_state"));
}

void test_model_validator_rejects_duplicate_initial_particle_id() {
    auto m = oneTypeModel();
    m.initial_particles.push_back(InitialParticleIR{1,0,{0,0}});
    m.initial_particles.push_back(InitialParticleIR{1,0,{0,0}});
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues, "duplicate_initial_particle"));
}

void test_model_validator_rejects_initial_bond_missing_particle() {
    auto m = oneTypeModel();
    m.initial_particles.push_back(InitialParticleIR{1,0,{0,0}});
    m.initial_bonds.push_back(InitialBondIR{1,1,77,1});
    auto issues = ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues, "unknown_initial_particle"));
}

void test_model_validator_rejects_symmetry_class_type_mismatch() {
    ModelIR m = oneTypeModel();
    MoleculeTypeIR b; b.id=1; b.name="B"; b.sites={SiteSpec{"x",{}}}; m.molecule_types.push_back(b);
    ExpandedRuleIR r;
    r.id=0;
    r.pattern.nodes={PatternNodeIR{0,0,0,5}, PatternNodeIR{1,1,0,5}};
    m.expanded_rules.push_back(r);
    auto issues=ModelValidator::validate(m);
    CHECK(ModelValidator::hasError(issues,"symmetry_type_mismatch"));
}

void test_generic_state_rejects_invalid_state_value() {
    auto m = oneTypeModel();
    GenericGraphState g(m);
    auto a = g.create(0);
    CHECK_THROW(g.setSiteState(a,0,2), std::out_of_range);
    CHECK_EQ(g.siteState(a,0),0);
    CHECK_THROW(g.setSiteState(a,0,-1), std::out_of_range);
    CHECK_EQ(g.siteState(a,0),0);
}

void test_generic_state_fingerprint_tracks_state_and_bonds() {
    auto m = oneTypeModel();
    GenericGraphState g(m);
    auto a=g.create(0), b=g.create(0);
    const auto f0=g.fingerprint();
    g.setSiteState(a,0,1);
    const auto f1=g.fingerprint();
    CHECK_NE(f0,f1);
    g.bind(a,1,b,1);
    const auto f2=g.fingerprint();
    CHECK_NE(f1,f2);
    g.unbind(a,1);
    CHECK_EQ(g.fingerprint(),f1);
}

void test_matcher_limit_is_exact() {
    auto m=oneTypeModel();
    GenericGraphState g(m);
    for(int i=0;i<10;++i) g.create(0);
    PatternGraphIR p; p.nodes={PatternNodeIR{0,0,0,0}};
    CHECK_EQ(PatternMatcher::findMatches(g,p,{},3).size(),3u);
    CHECK_EQ(PatternMatcher::countMatches(g,p,{},4),4u);
}

void test_matcher_does_not_reuse_particle_for_two_nodes() {
    auto m=oneTypeModel();
    GenericGraphState g(m); g.create(0);
    PatternGraphIR p; p.nodes={PatternNodeIR{0,0,0,0},PatternNodeIR{1,0,0,0}};
    CHECK(PatternMatcher::findMatches(g,p,{}).empty());
}

void test_matcher_symmetry_three_nodes_canonicalizes_factorial_duplicates() {
    auto m=oneTypeModel();
    GenericGraphState g(m); g.create(0); g.create(0); g.create(0);
    PatternGraphIR p;
    p.nodes={PatternNodeIR{0,0,0,7},PatternNodeIR{1,0,0,7},PatternNodeIR{2,0,0,7}};
    CHECK_EQ(PatternMatcher::findMatches(g,p,{}).size(),1u);
}

void test_matcher_predicate_is_node_specific() {
    auto m=oneTypeModel();
    GenericGraphState g(m); auto a=g.create(0), b=g.create(0); g.setSiteState(a,0,1);
    PatternGraphIR p; p.nodes={PatternNodeIR{0,0,0,0},PatternNodeIR{1,0,0,0}};
    auto matches=PatternMatcher::findMatches(g,p,{statePred(0,0,1),statePred(1,0,0)});
    CHECK_EQ(matches.size(),1u);
    CHECK_EQ(matches.front().at(0),a);
    CHECK_EQ(matches.front().at(1),b);
}

void test_matcher_requires_bidirectional_consistent_bond() {
    auto m=oneTypeModel();
    GenericGraphState g(m); auto a=g.create(0), b=g.create(0); g.bind(a,1,b,1);
    PatternGraphIR p; p.nodes={PatternNodeIR{0,0,0,0},PatternNodeIR{1,0,0,0}};
    p.bonds={PatternBondIR{0,1,1,0}};
    CHECK(PatternMatcher::findMatches(g,p,{}).empty());
}

void test_matcher_different_complex_constraint() {
    auto m=oneTypeModel();
    GenericGraphState g(m); auto a=g.create(0), b=g.create(0), c=g.create(0); g.bind(a,1,b,1);
    PatternGraphIR p; p.nodes={PatternNodeIR{0,0,0,0},PatternNodeIR{1,0,1,0}};
    p.molecularity={MolecularityConstraintIR{0,1,ComplexRelation::DifferentComplex}};
    auto matches=PatternMatcher::findMatches(g,p,{});
    CHECK_EQ(matches.size(),4u);
    for(const auto& match:matches) CHECK(!g.sameComplex(match.at(0),match.at(1)));
    (void)c;
}

void test_transform_preflight_keeps_state_atomic_on_bad_second_action() {
    auto m=oneTypeModel();
    GenericGraphState g(m); auto a=g.create(0);
    PatternMatch match; match.nodes={a};
    ActionIR good=setAction(0,0,1);
    ActionIR bad=setAction(9,0,0);
    const auto before=g.fingerprint();
    CHECK_THROW(TransformationExecutor::apply(g,match,{good,bad}),std::invalid_argument);
    CHECK_EQ(g.fingerprint(),before);
    CHECK_EQ(g.siteState(a,0),0);
}

void test_transform_preflight_does_not_leak_created_particle() {
    auto m=oneTypeModel();
    GenericGraphState g(m); auto a=g.create(0);
    PatternMatch match; match.nodes={a};
    ActionIR create; create.kind=ActionKind::Create; create.molecule_type=0; create.target_node=1;
    ActionIR bad=bindAction(1,99,0,1);
    const auto before=g.fingerprint();
    const auto live=g.liveCount();
    CHECK_THROW(TransformationExecutor::apply(g,match,{create,bad}),std::out_of_range);
    CHECK_EQ(g.liveCount(),live);
    CHECK_EQ(g.fingerprint(),before);
}

void test_transform_rejects_type_mismatched_target() {
    auto m=oneTypeModel();
    MoleculeTypeIR b; b.id=1; b.name="B"; b.sites={SiteSpec{"x",{"u","p"}}}; m.molecule_types.push_back(b);
    GenericGraphState g(m); auto p=g.create(1);
    PatternMatch match; match.nodes={p};
    auto action=setAction(0,0,1);
    CHECK_THROW(TransformationExecutor::apply(g,match,{action}),std::invalid_argument);
    CHECK_EQ(g.siteState(p,0),0);
}

void test_transform_destroy_unbinds_partner() {
    auto m=oneTypeModel();
    GenericGraphState g(m); auto a=g.create(0), b=g.create(0); g.bind(a,1,b,1);
    PatternMatch match; match.nodes={a,b};
    ActionIR destroy; destroy.kind=ActionKind::Destroy; destroy.molecule_type=0; destroy.target_node=0;
    TransformationExecutor::apply(g,match,{destroy});
    CHECK(!g.alive(a));
    CHECK(g.alive(b));
    CHECK(!g.bound(b,1));
}

void test_transform_unbind_free_site_is_safe_noop() {
    auto m=oneTypeModel();
    GenericGraphState g(m); auto a=g.create(0);
    PatternMatch match; match.nodes={a};
    const auto before=g.fingerprint();
    auto record=TransformationExecutor::apply(g,match,{unbindAction(0,1)});
    CHECK_EQ(g.fingerprint(),before);
    CHECK_EQ(record.touched.size(),1u);
}

void test_observable_embeddings_molecules_complexes_distinct() {
    auto m=oneTypeModel();
    GenericGraphState g(m); auto a=g.create(0), b=g.create(0), c=g.create(0); g.bind(a,1,b,1);
    ObservableIR o; o.name="A"; o.pattern.nodes={PatternNodeIR{0,0,0,0}};
    o.mode=ObservableMode::Embeddings; CHECK_EQ(ObservableEvaluator::evaluate(g,o),3u);
    o.mode=ObservableMode::Molecules; CHECK_EQ(ObservableEvaluator::evaluate(g,o),3u);
    o.mode=ObservableMode::Complexes; CHECK_EQ(ObservableEvaluator::evaluate(g,o),2u);
    (void)c;
}

void test_observable_species_pattern_counts_one_per_matching_complex() {
    auto m=oneTypeModel();
    GenericGraphState g(m); auto a=g.create(0), b=g.create(0), c=g.create(0), d=g.create(0);
    g.bind(a,1,b,1); g.bind(c,1,d,1);
    ObservableIR o; o.mode=ObservableMode::Complexes;
    o.pattern.nodes={PatternNodeIR{0,0,0,1},PatternNodeIR{1,0,0,1}};
    o.pattern.bonds={PatternBondIR{0,1,1,1}};
    CHECK_EQ(ObservableEvaluator::evaluate(g,o),2u);
}

void test_generic_sim_reproducible_trace() {
    auto m=oneTypeModel(1);
    for(std::uint32_t i=0;i<5;++i) m.initial_particles.push_back(InitialParticleIR{i,0,{0}});
    ExpandedRuleIR r; r.id=0; r.name="phos"; r.rate=1.5; r.rate_law.kind=RateLawKind::MassAction; r.rate_law.base_rate=1.5;
    r.pattern.nodes={PatternNodeIR{0,0,0,0}}; r.predicates={statePred(0,0,0)}; r.actions={setAction(0,0,1)}; m.expanded_rules.push_back(r);
    GenericSimulator a(m),b(m);
    auto ar=a.run(100,100,999,4,true), br=b.run(100,100,999,4,true);
    CHECK_EQ(ar.events,br.events);
    CHECK_NEAR(ar.time,br.time,0.0);
    CHECK_EQ(ar.trace.size(),br.trace.size());
    for(std::size_t i=0;i<ar.trace.size();++i) {
        CHECK_EQ(ar.trace[i].rule,br.trace[i].rule);
        CHECK_NEAR(ar.trace[i].time,br.trace[i].time,0.0);
        CHECK_NEAR(ar.trace[i].total_propensity,br.trace[i].total_propensity,0.0);
    }
    CHECK_EQ(a.state().fingerprint(),b.state().fingerprint());
}

void test_generic_sim_different_trajectory_stream_changes_trace() {
    auto m=oneTypeModel(1);
    for(std::uint32_t i=0;i<20;++i) m.initial_particles.push_back(InitialParticleIR{i,0,{0}});
    ExpandedRuleIR r; r.id=0; r.name="phos"; r.rate=1.5; r.rate_law.base_rate=1.5;
    r.pattern.nodes={PatternNodeIR{0,0,0,0}}; r.predicates={statePred(0,0,0)}; r.actions={setAction(0,0,1)}; m.expanded_rules.push_back(r);
    GenericSimulator a(m),b(m);
    auto ar=a.run(3,100,999,4,true), br=b.run(3,100,999,5,true);
    CHECK_EQ(ar.events,3u); CHECK_EQ(br.events,3u);
    CHECK(ar.trace.front().time != br.trace.front().time);
}

void test_generic_sim_no_propensity_exhausts_without_time_advance() {
    auto m=oneTypeModel(1);
    m.initial_particles.push_back(InitialParticleIR{0,0,{1}});
    ExpandedRuleIR r; r.id=0; r.name="needs-u"; r.rate=1.0; r.rate_law.base_rate=1.0;
    r.pattern.nodes={PatternNodeIR{0,0,0,0}}; r.predicates={statePred(0,0,0)}; m.expanded_rules.push_back(r);
    GenericSimulator sim(m); auto out=sim.run(10,10,1,0,true);
    CHECK(out.exhausted); CHECK_EQ(out.events,0u); CHECK_NEAR(out.time,0.0,0.0); CHECK(out.trace.empty());
}

void test_generic_sim_respects_symmetry_factor() {
    auto m=oneTypeModel();
    m.initial_particles.push_back(InitialParticleIR{0,0,{0,0}});
    m.initial_particles.push_back(InitialParticleIR{1,0,{0,0}});
    ExpandedRuleIR r; r.id=0; r.name="pair"; r.rate=4.0; r.rate_law.base_rate=4.0; r.rate_law.symmetry_factor=2.0;
    r.pattern.nodes={PatternNodeIR{0,0,0,1},PatternNodeIR{1,0,0,1}}; m.expanded_rules.push_back(r);
    GenericSimulator sim(m); auto out=sim.run(1,100,123,0,true);
    CHECK_EQ(out.events,1u);
    CHECK_EQ(out.trace.size(),1u);
    if (!out.trace.empty()) CHECK_NEAR(out.trace[0].total_propensity,2.0,1e-12);
}

void test_generic_sim_rejects_unsupported_rate_before_mutation() {
    auto m=oneTypeModel(1); m.initial_particles.push_back(InitialParticleIR{0,0,{0}});
    ExpandedRuleIR r; r.id=0; r.name="bad"; r.rate_law.kind=RateLawKind::Energy; r.rate_law.base_rate=1.0;
    r.pattern.nodes={PatternNodeIR{0,0,0,0}}; r.actions={setAction(0,0,1)}; m.expanded_rules.push_back(r);
    GenericSimulator sim(m); const auto before=sim.state().fingerprint();
    CHECK_THROW(sim.run(1,10,4,0,true),std::runtime_error);
    CHECK_EQ(sim.state().fingerprint(),before);
}

void test_cache_roundtrip_preserves_dependency_index() {
    auto m=oneTypeModel();
    RuleFamilyIR f; f.id=0; f.name="f"; f.predicates={statePred(0,0,1)}; m.rule_families.push_back(f);
    ModelCompiler::buildDependencies(m);
    const auto before=m.fingerprint();
    const std::string path="/tmp/nfnext_semantic_cache.nfir";
    ModelCache::save(m,path);
    auto loaded=ModelCache::load(path);
    CHECK_EQ(loaded.dependencies.feature_to_families.size(),m.dependencies.feature_to_families.size());
    CHECK_EQ(loaded.fingerprint(),before);
    std::remove(path.c_str());
}

void test_cache_fingerprint_changes_when_dependency_index_changes() {
    auto m=oneTypeModel();
    const auto before=m.fingerprint();
    m.dependencies.feature_to_families[123]={4,5};
    CHECK_NE(m.fingerprint(),before);
}

void test_cache_rejects_trailing_garbage() {
    auto m=oneTypeModel(); const std::string path="/tmp/nfnext_trailing.nfir";
    ModelCache::save(m,path);
    { std::ofstream out(path,std::ios::binary|std::ios::app); out << "garbage"; }
    CHECK_THROW(ModelCache::load(path),std::runtime_error);
    std::remove(path.c_str());
}

void test_cache_rejects_truncation() {
    auto m=oneTypeModel(); const std::string path="/tmp/nfnext_truncated.nfir";
    ModelCache::save(m,path);
    std::ifstream in(path,std::ios::binary); std::string bytes((std::istreambuf_iterator<char>(in)),{}); in.close();
    bytes.resize(bytes.size()/2); std::ofstream out(path,std::ios::binary|std::ios::trunc); out.write(bytes.data(),bytes.size()); out.close();
    CHECK_THROW(ModelCache::load(path),std::runtime_error);
    std::remove(path.c_str());
}

void test_cache_expectations_reject_semantics_changes() {
    auto m=oneTypeModel(); m.metadata.source_hash=9; m.metadata.parser_semantics_version=4; m.metadata.compiler_semantics_version=7; m.metadata.compile_flags=11;
    const std::string path="/tmp/nfnext_expect.nfir"; ModelCache::save(m,path);
    CacheExpectations e; e.require_source_hash=true; e.source_hash=10;
    CHECK_THROW(ModelCache::load(path,e),std::runtime_error);
    e.source_hash=9; e.parser_semantics_version=3;
    CHECK_THROW(ModelCache::load(path,e),std::runtime_error);
    e.parser_semantics_version=4; e.compiler_semantics_version=6;
    CHECK_THROW(ModelCache::load(path,e),std::runtime_error);
    e.compiler_semantics_version=7; e.require_compile_flags=true; e.compile_flags=12;
    CHECK_THROW(ModelCache::load(path,e),std::runtime_error);
    std::remove(path.c_str());
}

void test_legacy_adapter_rejects_bad_initial_bond_before_lowering() {
    LegacyModelDescriptor d; d.name="bad"; d.molecule_types=oneTypeModel().molecule_types;
    d.initial_particles.push_back(InitialParticleIR{0,0,{0,0}});
    d.initial_bonds.push_back(InitialBondIR{0,1,99,1});
    CHECK_THROW(LegacyAdapter::lower(d),std::invalid_argument);
}

void test_xml_import_minimal_model() {
    auto result=NfXmlImporter::parseString(minimalXml(),"minimal.xml");
    CHECK(result.ok());
    CHECK(result.diagnostics.empty());
    CHECK_EQ(result.model.model_name,"mini");
    CHECK_EQ(result.model.molecule_types.size(),1u);
    CHECK_EQ(result.model.molecule_types[0].sites.size(),2u);
    CHECK_EQ(result.model.molecule_types[0].sites[0].states.size(),2u);
    CHECK_EQ(result.model.initial_particles.size(),2u);
    CHECK_EQ(result.model.expanded_rules.size(),1u);
    CHECK_EQ(result.model.observables.size(),1u);
    CHECK_EQ(result.model.metadata.source_identity,"minimal.xml");
    CHECK_NE(result.model.metadata.source_hash,0u);
}

void test_xml_import_parameter_rate_resolution() {
    auto result=NfXmlImporter::parseString(minimalXml("k"),"r.xml");
    CHECK(result.ok());
    CHECK_NEAR(result.model.expanded_rules[0].rate_law.base_rate,2.5,1e-12);
    CHECK_NEAR(result.model.expanded_rules[0].rate,2.5,1e-12);
}

void test_xml_import_numeric_rate_resolution() {
    auto result=NfXmlImporter::parseString(minimalXml("3.125"),"r.xml");
    CHECK(result.ok());
    CHECK_NEAR(result.model.expanded_rules[0].rate_law.base_rate,3.125,1e-12);
}

void test_xml_import_state_name_becomes_state_index() {
    auto result=NfXmlImporter::parseString(minimalXml(),"state.xml");
    CHECK(result.ok());
    const auto& r=result.model.expanded_rules[0];
    CHECK_EQ(r.predicates.size(),2u); // state u plus explicitly free bond count on x
    bool found=false;
    for(const auto& p:r.predicates) if(p.kind==PredicateKind::SiteStateEq) { found=true; CHECK_EQ(p.value,0); }
    CHECK(found);
    CHECK_EQ(r.actions.size(),1u);
    CHECK_EQ(r.actions[0].kind,ActionKind::SetSiteState);
    CHECK_EQ(r.actions[0].value,1);
}

void test_xml_import_binding_and_unbinding_operations() {
    auto result=NfXmlImporter::parseString(bindingXml(),"binding.xml");
    CHECK(result.ok());
    CHECK_EQ(result.model.expanded_rules.size(),2u);
    CHECK_EQ(result.model.expanded_rules[0].actions.size(),1u);
    CHECK_EQ(result.model.expanded_rules[0].actions[0].kind,ActionKind::Bind);
    CHECK_EQ(result.model.expanded_rules[1].actions.size(),1u);
    CHECK_EQ(result.model.expanded_rules[1].actions[0].kind,ActionKind::Unbind);
    CHECK_EQ(result.model.expanded_rules[1].pattern.bonds.size(),1u);
}

void test_xml_import_species_observable_maps_to_complexes() {
    auto result=NfXmlImporter::parseString(bindingXml(),"binding.xml");
    CHECK(result.ok());
    CHECK_EQ(result.model.observables.size(),1u);
    CHECK_EQ(result.model.observables[0].mode,ObservableMode::Complexes);
    CHECK_EQ(result.model.observables[0].pattern.nodes.size(),2u);
    CHECK_EQ(result.model.observables[0].pattern.bonds.size(),1u);
}

void test_xml_import_molecules_observable_maps_to_molecules() {
    auto result=NfXmlImporter::parseString(minimalXml(),"obs.xml");
    CHECK(result.ok());
    CHECK_EQ(result.model.observables[0].mode,ObservableMode::Molecules);
}

void test_xml_import_initial_multiplicity_is_exact() {
    auto result=NfXmlImporter::parseString(minimalXml(),"init.xml");
    CHECK(result.ok());
    CHECK_EQ(result.model.initial_particles.size(),2u);
    CHECK_EQ(result.model.initial_particles[0].site_states[0],0);
    CHECK_EQ(result.model.initial_particles[1].site_states[0],0);
}

void test_xml_import_bonded_species_replication() {
    std::string xml=R"XML(<?xml version="1.0"?><sbml><model id="d"><ListOfMoleculeTypes>
<MoleculeType id="A"><ListOfComponentTypes><ComponentType id="b"/></ListOfComponentTypes></MoleculeType>
</ListOfMoleculeTypes><ListOfSpecies><Species id="S" concentration="2"><ListOfMolecules>
<Molecule id="S_M1" name="A"><ListOfComponents><Component id="S_M1_C1" name="b" numberOfBonds="1"/></ListOfComponents></Molecule>
<Molecule id="S_M2" name="A"><ListOfComponents><Component id="S_M2_C1" name="b" numberOfBonds="1"/></ListOfComponents></Molecule>
</ListOfMolecules><ListOfBonds><Bond id="B" site1="S_M1_C1" site2="S_M2_C1"/></ListOfBonds></Species></ListOfSpecies></model></sbml>)XML";
    auto result=NfXmlImporter::parseString(xml,"dimer.xml");
    CHECK(result.ok());
    CHECK_EQ(result.model.initial_particles.size(),4u);
    CHECK_EQ(result.model.initial_bonds.size(),2u);
    auto state=instantiateInitialState(result.model);
    CHECK_EQ(state.liveCount(),4u);
    CHECK_EQ(state.componentKey(state.liveParticles()[0]),state.componentKey(state.liveParticles()[1]));
}

void test_xml_import_rejects_fractional_particle_concentration() {
    auto xml=minimalXml();
    auto at=xml.find("concentration=\"2\""); xml.replace(at,std::string("concentration=\"2\"").size(),"concentration=\"2.5\"");
    auto result=NfXmlImporter::parseString(xml,"fraction.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("fractional_particle_count"));
}

void test_xml_import_rejects_negative_particle_concentration() {
    auto xml=minimalXml();
    auto at=xml.find("concentration=\"2\""); xml.replace(at,std::string("concentration=\"2\"").size(),"concentration=\"-1\"");
    auto result=NfXmlImporter::parseString(xml,"negative.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("negative_particle_count"));
}

void test_xml_import_rejects_unknown_parameter_rate() {
    auto result=NfXmlImporter::parseString(minimalXml("missing"),"bad-rate.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("unknown_rate_constant"));
}

void test_xml_import_rejects_unknown_molecule_type() {
    auto xml=minimalXml();
    auto at=xml.find("name=\"A\"",xml.find("ReactantPattern")); xml.replace(at,8,"name=\"Z\"");
    auto result=NfXmlImporter::parseString(xml,"bad-type.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("unknown_molecule_type"));
}

void test_xml_import_rejects_unknown_component_name() {
    auto xml=minimalXml();
    auto at=xml.find("name=\"x\"",xml.find("ReactantPattern")); xml.replace(at,8,"name=\"q\"");
    auto result=NfXmlImporter::parseString(xml,"bad-site.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("unknown_component"));
}

void test_xml_import_rejects_unknown_state_name() {
    auto xml=minimalXml();
    auto at=xml.find("state=\"u\"",xml.find("ReactantPattern")); xml.replace(at,9,"state=\"wat\"");
    auto result=NfXmlImporter::parseString(xml,"bad-state.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("unknown_state"));
}

void test_xml_import_rejects_unsupported_operation_without_partial_rule() {
    auto xml=minimalXml();
    auto at=xml.find("<StateChange"); auto end=xml.find("/>",at)+2;
    xml.replace(at,end-at,"<Teleport site=\"RR1_RP1_M1_C1\"/>");
    auto result=NfXmlImporter::parseString(xml,"unsupported-op.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("unsupported_operation"));
    CHECK(result.model.expanded_rules.empty());
}

void test_xml_import_rejects_unsupported_rate_law_without_guessing() {
    auto xml=minimalXml();
    auto at=xml.find("type=\"Ele\""); xml.replace(at,10,"type=\"MM\"");
    auto result=NfXmlImporter::parseString(xml,"unsupported-rate.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("unsupported_rate_law"));
    CHECK(result.model.expanded_rules.empty());
}

void test_xml_import_reports_malformed_xml() {
    auto result=NfXmlImporter::parseString("<sbml><model>","broken.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("malformed_xml"));
}

void test_xml_import_source_hash_is_content_sensitive() {
    auto a=NfXmlImporter::parseString(minimalXml(),"same.xml");
    auto b=NfXmlImporter::parseString(minimalXml("3.0"),"same.xml");
    CHECK(a.ok()); CHECK(b.ok());
    CHECK_NE(a.model.metadata.source_hash,b.model.metadata.source_hash);
}

void test_xml_import_source_hash_is_path_independent() {
    auto a=NfXmlImporter::parseString(minimalXml(),"one.xml");
    auto b=NfXmlImporter::parseString(minimalXml(),"two.xml");
    CHECK(a.ok()); CHECK(b.ok());
    CHECK_EQ(a.model.metadata.source_hash,b.model.metadata.source_hash);
    CHECK_NE(a.model.metadata.source_identity,b.model.metadata.source_identity);
}

void test_xml_import_parse_file_matches_parse_string() {
    const std::string path="/tmp/nfnext_import.xml";
    { std::ofstream out(path); out << minimalXml(); }
    auto a=NfXmlImporter::parseString(minimalXml(),path);
    auto b=NfXmlImporter::parseFile(path);
    CHECK(a.ok()); CHECK(b.ok());
    CHECK_EQ(a.model.fingerprint(),b.model.fingerprint());
    std::remove(path.c_str());
}

void test_xml_import_missing_file_is_diagnostic() {
    auto result=NfXmlImporter::parseFile("/tmp/does-not-exist-nfnext.xml");
    CHECK(!result.ok());
    CHECK(result.hasError("io_error"));
}

void test_xml_imported_minimal_model_executes() {
    auto result=NfXmlImporter::parseString(minimalXml(),"exec.xml");
    CHECK(result.ok());
    GenericSimulator sim(result.model);
    auto before=ObservableEvaluator::evaluateAll(sim.state(),result.model.observables);
    CHECK_EQ(before[0],0u);
    auto run=sim.run(10,100,123,0,true);
    CHECK_EQ(run.events,2u);
    CHECK(run.exhausted);
    auto after=ObservableEvaluator::evaluateAll(sim.state(),result.model.observables);
    CHECK_EQ(after[0],2u);
}

void test_xml_imported_binding_model_executes_and_observable_changes() {
    auto result=NfXmlImporter::parseString(bindingXml(),"bind-exec.xml");
    CHECK(result.ok());
    GenericSimulator sim(result.model);
    auto before=ObservableEvaluator::evaluateAll(sim.state(),result.model.observables);
    CHECK_EQ(before[0],0u);
    auto run=sim.run(1,100,8123,0,true);
    CHECK_EQ(run.events,1u);
    auto after=ObservableEvaluator::evaluateAll(sim.state(),result.model.observables);
    CHECK_EQ(after[0],1u);
}

void test_differential_snapshot_identical_runs_compare_equal() {
    auto result=NfXmlImporter::parseString(minimalXml(),"diff.xml");
    CHECK(result.ok());
    auto a=TrajectorySnapshot::runGeneric(result.model,100,100,88,2,true);
    auto b=TrajectorySnapshot::runGeneric(result.model,100,100,88,2,true);
    auto report=DifferentialValidator::compareExact(a,b);
    CHECK(report.equal);
    CHECK(report.mismatches.empty());
}

void test_differential_snapshot_detects_state_difference() {
    auto result=NfXmlImporter::parseString(minimalXml(),"diff.xml");
    CHECK(result.ok());
    auto a=TrajectorySnapshot::runGeneric(result.model,1,100,88,2,true);
    auto b=TrajectorySnapshot::runGeneric(result.model,2,100,88,2,true);
    auto report=DifferentialValidator::compareExact(a,b);
    CHECK(!report.equal);
    CHECK(report.hasMismatch("events") || report.hasMismatch("state_fingerprint"));
}

void test_differential_snapshot_detects_observable_difference() {
    TrajectorySnapshot a,b;
    a.events=b.events=1; a.time=b.time=1.0; a.state_fingerprint=b.state_fingerprint=7;
    a.observables={1,2}; b.observables={1,3};
    auto report=DifferentialValidator::compareExact(a,b);
    CHECK(!report.equal);
    CHECK(report.hasMismatch("observables"));
}

void test_differential_snapshot_detects_trace_rule_difference() {
    TrajectorySnapshot a,b;
    a.events=b.events=1; a.time=b.time=1.0; a.state_fingerprint=b.state_fingerprint=7;
    a.trace.push_back(GenericEventTrace{0,1,0.4,2.0});
    b.trace.push_back(GenericEventTrace{0,2,0.4,2.0});
    auto report=DifferentialValidator::compareExact(a,b);
    CHECK(!report.equal);
    CHECK(report.hasMismatch("trace.rule"));
}

void test_differential_snapshot_exact_time_is_strict() {
    TrajectorySnapshot a,b;
    a.events=b.events=1; a.time=1.0; b.time=std::nextafter(1.0,2.0); a.state_fingerprint=b.state_fingerprint=7;
    auto report=DifferentialValidator::compareExact(a,b);
    CHECK(!report.equal);
    CHECK(report.hasMismatch("time"));
}

void test_end_to_end_cache_import_run_reproducibility() {
    auto imported=NfXmlImporter::parseString(minimalXml(),"e2e.xml");
    CHECK(imported.ok());
    ModelCompiler compiler; compiler.compile(imported.model);
    const std::string path="/tmp/nfnext_e2e.nfir"; ModelCache::save(imported.model,path);
    CacheExpectations e; e.require_source_hash=true; e.source_hash=imported.model.metadata.source_hash;
    e.parser_semantics_version=imported.model.metadata.parser_semantics_version;
    e.compiler_semantics_version=imported.model.metadata.compiler_semantics_version;
    auto loaded=ModelCache::load(path,e);
    auto a=TrajectorySnapshot::runGeneric(imported.model,100,100,45,3,true);
    auto b=TrajectorySnapshot::runGeneric(loaded,100,100,45,3,true);
    auto report=DifferentialValidator::compareExact(a,b);
    CHECK(report.equal);
    std::remove(path.c_str());
}

struct TestCase { const char* name; void(*fn)(); };

const TestCase tests[] = {
    {"validator valid graph",test_model_validator_accepts_valid_graph},
    {"validator duplicate type",test_model_validator_rejects_duplicate_type_ids},
    {"validator duplicate node",test_model_validator_rejects_duplicate_node_ids},
    {"validator dangling bond node",test_model_validator_rejects_dangling_bond_node},
    {"validator bad bond site",test_model_validator_rejects_invalid_bond_site},
    {"validator bad predicate node",test_model_validator_rejects_unknown_predicate_node},
    {"validator bad action node",test_model_validator_rejects_unknown_action_node},
    {"validator bad state",test_model_validator_rejects_state_out_of_range},
    {"validator duplicate initial particle",test_model_validator_rejects_duplicate_initial_particle_id},
    {"validator bad initial bond",test_model_validator_rejects_initial_bond_missing_particle},
    {"validator symmetry type mismatch",test_model_validator_rejects_symmetry_class_type_mismatch},
    {"generic state state range",test_generic_state_rejects_invalid_state_value},
    {"generic state fingerprint",test_generic_state_fingerprint_tracks_state_and_bonds},
    {"matcher limit",test_matcher_limit_is_exact},
    {"matcher no particle reuse",test_matcher_does_not_reuse_particle_for_two_nodes},
    {"matcher three-way symmetry",test_matcher_symmetry_three_nodes_canonicalizes_factorial_duplicates},
    {"matcher node predicate",test_matcher_predicate_is_node_specific},
    {"matcher bond consistency",test_matcher_requires_bidirectional_consistent_bond},
    {"matcher molecularity",test_matcher_different_complex_constraint},
    {"transform atomic bad second",test_transform_preflight_keeps_state_atomic_on_bad_second_action},
    {"transform no leaked create",test_transform_preflight_does_not_leak_created_particle},
    {"transform target type",test_transform_rejects_type_mismatched_target},
    {"transform destroy unbind",test_transform_destroy_unbinds_partner},
    {"transform free unbind",test_transform_unbind_free_site_is_safe_noop},
    {"observable modes",test_observable_embeddings_molecules_complexes_distinct},
    {"observable species complex",test_observable_species_pattern_counts_one_per_matching_complex},
    {"generic sim reproducible",test_generic_sim_reproducible_trace},
    {"generic sim stream separation",test_generic_sim_different_trajectory_stream_changes_trace},
    {"generic sim exhausted",test_generic_sim_no_propensity_exhausts_without_time_advance},
    {"generic sim symmetry factor",test_generic_sim_respects_symmetry_factor},
    {"generic sim unsupported rate",test_generic_sim_rejects_unsupported_rate_before_mutation},
    {"cache dependencies roundtrip",test_cache_roundtrip_preserves_dependency_index},
    {"cache dependencies fingerprint",test_cache_fingerprint_changes_when_dependency_index_changes},
    {"cache trailing bytes",test_cache_rejects_trailing_garbage},
    {"cache truncation",test_cache_rejects_truncation},
    {"cache expectations",test_cache_expectations_reject_semantics_changes},
    {"legacy adapter bad initial bond",test_legacy_adapter_rejects_bad_initial_bond_before_lowering},
    {"xml minimal",test_xml_import_minimal_model},
    {"xml parameter rate",test_xml_import_parameter_rate_resolution},
    {"xml numeric rate",test_xml_import_numeric_rate_resolution},
    {"xml state mapping",test_xml_import_state_name_becomes_state_index},
    {"xml bind/unbind",test_xml_import_binding_and_unbinding_operations},
    {"xml species observable",test_xml_import_species_observable_maps_to_complexes},
    {"xml molecules observable",test_xml_import_molecules_observable_maps_to_molecules},
    {"xml initial multiplicity",test_xml_import_initial_multiplicity_is_exact},
    {"xml bonded species replication",test_xml_import_bonded_species_replication},
    {"xml fractional concentration",test_xml_import_rejects_fractional_particle_concentration},
    {"xml negative concentration",test_xml_import_rejects_negative_particle_concentration},
    {"xml unknown rate",test_xml_import_rejects_unknown_parameter_rate},
    {"xml unknown type",test_xml_import_rejects_unknown_molecule_type},
    {"xml unknown site",test_xml_import_rejects_unknown_component_name},
    {"xml unknown state",test_xml_import_rejects_unknown_state_name},
    {"xml unsupported operation",test_xml_import_rejects_unsupported_operation_without_partial_rule},
    {"xml unsupported rate",test_xml_import_rejects_unsupported_rate_law_without_guessing},
    {"xml malformed",test_xml_import_reports_malformed_xml},
    {"xml content hash",test_xml_import_source_hash_is_content_sensitive},
    {"xml path independent hash",test_xml_import_source_hash_is_path_independent},
    {"xml parse file",test_xml_import_parse_file_matches_parse_string},
    {"xml missing file",test_xml_import_missing_file_is_diagnostic},
    {"xml execute state",test_xml_imported_minimal_model_executes},
    {"xml execute binding",test_xml_imported_binding_model_executes_and_observable_changes},
    {"diff identical",test_differential_snapshot_identical_runs_compare_equal},
    {"diff state",test_differential_snapshot_detects_state_difference},
    {"diff observable",test_differential_snapshot_detects_observable_difference},
    {"diff trace rule",test_differential_snapshot_detects_trace_rule_difference},
    {"diff time strict",test_differential_snapshot_exact_time_is_strict},
    {"end-to-end cache import run",test_end_to_end_cache_import_run_reproducibility},
};

} // namespace

int main() {
    for (const auto& test : tests) {
        try {
            test.fn();
        } catch (const std::exception& e) {
            ++failures;
            std::cerr << "UNCAUGHT in " << test.name << ": " << e.what() << '\n';
        } catch (...) {
            ++failures;
            std::cerr << "UNCAUGHT in " << test.name << ": unknown exception\n";
        }
    }
    std::cout << "semantic tests: " << (sizeof(tests)/sizeof(tests[0]))
              << " cases, " << checks << " checks, " << failures << " failures\n";
    return failures == 0 ? 0 : 1;
}
