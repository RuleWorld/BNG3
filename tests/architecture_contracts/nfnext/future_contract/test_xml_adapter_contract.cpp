#include "contract_test.hpp"

#if __has_include("nfnext/xml_adapter.hpp")
#include "nfnext/xml_adapter.hpp"
#include "nfnext/validator.hpp"
#include <string>
using namespace nfnext;

static std::string wrap(const std::string& body) {
    return "<?xml version=\"1.0\"?><sbml><model id=\"m\"><ListOfParameters/>" + body + "</model></sbml>";
}

CONTRACT_CASE("adapter rejects malformed XML with source location") {
    try { (void)XmlAdapter().parse("<sbml><model>"); REQUIRE(false); }
    catch(const XmlAdapterError& e){ REQUIRE(e.line()>0); REQUIRE(!e.whatString().empty()); }
}

CONTRACT_CASE("adapter requires molecule type before reference") {
    auto xml=wrap("<ListOfMoleculeTypes/><ListOfSpecies><Species id=\"S\" concentration=\"1\"><ListOfMolecules><Molecule id=\"M\" name=\"Missing\"/></ListOfMolecules></Species></ListOfSpecies><ListOfReactionRules/><ListOfObservables/>");
    REQUIRE_THROWS_AS(XmlAdapter().parse(xml),XmlAdapterError);
}

CONTRACT_CASE("molecule type allowed states preserve declaration order") {
    auto ir=XmlAdapter().parse(loadFixtureXml("molecule_states.xml")); auto& s=ir.molecule_types.at(0).sites.at(0).states; REQUIRE_EQ(s,std::vector<std::string>({"u","p","q"}));
}

CONTRACT_CASE("duplicate molecule type IDs reject rather than overwrite") { REQUIRE_THROWS_AS(XmlAdapter().parse(loadFixtureXml("duplicate_molecule_id.xml")),XmlAdapterError); }
CONTRACT_CASE("duplicate component IDs reject rather than overwrite") { REQUIRE_THROWS_AS(XmlAdapter().parse(loadFixtureXml("duplicate_component_id.xml")),XmlAdapterError); }
CONTRACT_CASE("unknown allowed state in species rejects") { REQUIRE_THROWS_AS(XmlAdapter().parse(loadFixtureXml("unknown_state_species.xml")),XmlAdapterError); }
CONTRACT_CASE("multiple initial bonds on one site reject") { REQUIRE_THROWS_AS(XmlAdapter().parse(loadFixtureXml("multiply_bonded_site.xml")),XmlAdapterError); }

CONTRACT_CASE("elementary rate constant parameter resolves exactly") {
    auto ir=XmlAdapter().parse(loadFixtureXml("simple_system.xml")); auto r=findRule(ir,"Rule1"); REQUIRE_EQ(r.rate_law.kind,RateLawKind::Elementary); REQUIRE_NEAR(r.rate_law.base_rate,10.0,0.0);
}

CONTRACT_CASE("unknown rate parameter rejects") { REQUIRE_THROWS_AS(XmlAdapter().parse(loadFixtureXml("unknown_rate_parameter.xml")),XmlAdapterError); }
CONTRACT_CASE("unsupported rate law explicitly reports fallback requirement") { try{(void)XmlAdapter().parse(loadFixtureXml("unsupported_rate.xml"));REQUIRE(false);}catch(const UnsupportedSemantic& e){REQUIRE(e.canFallbackToLegacy());REQUIRE(e.feature().size()>0);} }

CONTRACT_CASE("reactant patterns become distinct-complex constraints where legacy molecularity requires it") {
    auto ir=XmlAdapter(XmlAdapterOptions::legacyMolecularityStrict()).parse(loadFixtureXml("two_reactant_bind.xml")); auto r=findRule(ir,"bind"); REQUIRE(r.pattern.requiresDifferentComplexBetweenReactants(0,1));
}

CONTRACT_CASE("same reactant pattern preserves same-complex topology") {
    auto ir=XmlAdapter().parse(loadFixtureXml("single_complex_unbind.xml")); auto r=findRule(ir,"unbind"); REQUIRE(r.pattern.requiresSameComplex(0,1));
}

CONTRACT_CASE("AddBond lowers to exact site-mapped bind action") {
    auto ir=XmlAdapter().parse(loadFixtureXml("simple_system.xml")); auto r=findRule(ir,"Rule1"); REQUIRE(r.transformation.hasAddBond("X","y","Y","x"));
}

CONTRACT_CASE("DeleteBond lowers to exact site-mapped unbind action") {
    auto ir=XmlAdapter().parse(loadFixtureXml("simple_system.xml")); auto r=findRule(ir,"Rule2"); REQUIRE(r.transformation.hasDeleteBond("X","y","Y","x"));
}

CONTRACT_CASE("StateChange lowers finalState name to enumerated state ID") {
    auto ir=XmlAdapter().parse(loadFixtureXml("simple_system.xml")); auto r=findRule(ir,"Rule3"); REQUIRE(r.transformation.hasStateChange("X","p",1));
}

CONTRACT_CASE("Add operation creates product molecule with declared component states") {
    auto ir=XmlAdapter().parse(loadFixtureXml("add_molecule.xml")); auto r=findRule(ir,"birth"); auto c=r.transformation.createdMolecule(0); REQUIRE_EQ(ir.molecule_types[c.type].name,"B"); REQUIRE_EQ(c.initial_state.at(siteId(ir,c.type,"x")),1);
}

CONTRACT_CASE("AddBond may target a newly created molecule") {
    auto ir=XmlAdapter().parse(loadFixtureXml("add_then_bind.xml")); auto r=findRule(ir,"birth_bind"); REQUIRE(r.transformation.bindsCreatedMolecule());
}

CONTRACT_CASE("Delete with DeleteMolecules=1 lowers to individual molecule deletion") {
    auto ir=XmlAdapter().parse(loadFixtureXml("delete_molecule.xml")); auto r=findRule(ir,"delete"); REQUIRE(r.transformation.hasDestroyMolecule()); REQUIRE(!r.transformation.hasDestroyComplex());
}

CONTRACT_CASE("Delete whole pattern with DeleteMolecules=0 lowers to complete species removal") {
    auto ir=XmlAdapter().parse(loadFixtureXml("delete_species.xml")); auto r=findRule(ir,"delete_complex"); REQUIRE(r.transformation.hasDestroyComplex());
}

CONTRACT_CASE("ambiguous BNGL delete behavior rejected instead of approximated") { REQUIRE_THROWS_AS(XmlAdapter().parse(loadFixtureXml("delete_ambiguous_no_keyword.xml")),UnsupportedSemantic); }

CONTRACT_CASE("stateSet parses into one finite-set predicate") {
    auto ir=XmlAdapter().parse(loadFixtureXml("stateset.xml")); auto p=findRule(ir,"r").pattern.sitePredicate("A","x"); REQUIRE_EQ(p.kind,PatternPredicateKind::StateSet); REQUIRE_EQ(p.state_set,std::vector<StateId>({0,2,3}));
}

CONTRACT_CASE("state and stateSet together reject") { REQUIRE_THROWS_AS(XmlAdapter().parse(loadFixtureXml("state_and_stateset.xml")),XmlAdapterError); }
CONTRACT_CASE("stateSet duplicate member rejects") { REQUIRE_THROWS_AS(XmlAdapter().parse(loadFixtureXml("stateset_duplicate.xml")),XmlAdapterError); }
CONTRACT_CASE("stateSet unknown member rejects") { REQUIRE_THROWS_AS(XmlAdapter().parse(loadFixtureXml("stateset_unknown.xml")),XmlAdapterError); }
CONTRACT_CASE("empty stateSet rejects") { REQUIRE_THROWS_AS(XmlAdapter().parse(loadFixtureXml("stateset_empty.xml")),XmlAdapterError); }

CONTRACT_CASE("Molecules observable with multiple patterns preserves term order") {
    auto ir=XmlAdapter().parse(loadFixtureXml("multi_observable.xml")); auto o=findObservable(ir,"O"); REQUIRE_EQ(o.kind,ObservableKind::Molecules); REQUIRE_EQ(o.terms.size(),3u);
}

CONTRACT_CASE("Species observable forces complex-aware execution requirement") {
    auto ir=XmlAdapter().parse(loadFixtureXml("species_observable.xml")); REQUIRE(ir.requirements.needs_complex_tracking);
}

CONTRACT_CASE("stoichiometric observable relation and quantity lower exactly") {
    auto ir=XmlAdapter().parse(loadFixtureXml("stoich_observable.xml")); auto t=findObservable(ir,"O").terms[0]; REQUIRE_EQ(t.stoich.op,StoichOp::Ge); REQUIRE_EQ(t.stoich.quantity,2);
}

CONTRACT_CASE("functions are parsed before function-dependent reaction lowering") {
    auto ir=XmlAdapter().parse(loadFixtureXml("function_rate.xml")); auto r=findRule(ir,"r"); REQUIRE_EQ(r.rate_law.kind,RateLawKind::Function); REQUIRE(r.rate_law.function_id.valid());
}

CONTRACT_CASE("compartment references lower without losing dimensionality") {
    auto ir=XmlAdapter().parse(loadFixtureXml("compartments.xml")); auto c=findCompartment(ir,"mem"); REQUIRE_EQ(c.dimension,2); REQUIRE_NEAR(c.size,4.0,0.0);
}

CONTRACT_CASE("population molecule type lowers to population storage") {
    auto ir=XmlAdapter().parse(loadFixtureXml("population_type.xml")); REQUIRE_EQ(findType(ir,"P").storage,StorageKind::Population);
}

CONTRACT_CASE("energy rule unsupported path returns precise diagnostic not generic parse error") {
    try{(void)XmlAdapter().parse(loadFixtureXml("energy_rule.xml"));REQUIRE(false);}catch(const UnsupportedSemantic&e){REQUIRE_EQ(e.feature(),"energy_rate_law");REQUIRE(e.ruleName().size()>0);}
}

CONTRACT_CASE("DOR rule unsupported path returns precise diagnostic") {
    try{(void)XmlAdapter().parse(loadFixtureXml("dor_rule.xml"));REQUIRE(false);}catch(const UnsupportedSemantic&e){REQUIRE_EQ(e.feature(),"dor_rate_law");}
}

CONTRACT_CASE("streaming parser and DOM parser produce identical canonical NFIR") {
    auto xml=loadFixtureXml("large_generated.xml"); XmlAdapterOptions a,b; a.parse_mode=XmlParseMode::Streaming; b.parse_mode=XmlParseMode::Dom; auto x=XmlAdapter(a).parse(xml),y=XmlAdapter(b).parse(xml); REQUIRE_EQ(x.semanticFingerprint(),y.semanticFingerprint()); REQUIRE_EQ(x.canonicalBytes(),y.canonicalBytes());
}

CONTRACT_CASE("rule streaming preserves original rule order exactly") {
    auto ir=XmlAdapter(XmlAdapterOptions::streaming()).parse(loadFixtureXml("1000_rules.xml")); for(std::size_t i=0;i<ir.expanded_rules.size();++i) REQUIRE_EQ(ir.expanded_rules[i].source_order,i);
}

CONTRACT_CASE("adapter can return partial compile coverage without executing unsupported semantics") {
    XmlAdapterOptions o; o.unsupported_policy=UnsupportedPolicy::CollectDiagnostics; auto result=XmlAdapter(o).analyze(loadFixtureXml("mixed_supported_unsupported.xml")); REQUIRE(result.supported_rule_count>0); REQUIRE(result.unsupported_rule_count>0); REQUIRE(!result.executable);
}

CONTRACT_CASE("strict adapter never marks partial model executable") {
    auto result=XmlAdapter(XmlAdapterOptions::strict()).analyze(loadFixtureXml("mixed_supported_unsupported.xml")); REQUIRE(!result.executable);
}

CONTRACT_MAIN("xml-adapter")
#else
#error "RED CONTRACT: implement strict NFsim XML to NFIR adapter"
#endif
