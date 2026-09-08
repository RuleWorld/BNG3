#include "contract_test.hpp"

#if __has_include("nfnext/transformation.hpp") && __has_include("nfnext/pattern_ir.hpp")
#include "nfnext/transformation.hpp"
#include "nfnext/pattern_ir.hpp"
#include "nfnext/generic_state.hpp"
using namespace nfnext;

static ModelIR schema() {
    ModelIR m;
    MoleculeTypeIR A; A.id=0; A.name="A"; A.sites={SiteSpec{"x",{"u","p"}},SiteSpec{"b",{}}};
    MoleculeTypeIR B; B.id=1; B.name="B"; B.sites={SiteSpec{"a",{}},SiteSpec{"y",{"0","1"}}};
    m.molecule_types={A,B}; return m;
}

CONTRACT_CASE("state change mutates exactly the mapped site") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0); s.setSiteState(a,0,0);
    MatchEmbedding e; e.bindNode(0,a);
    TransformationIR t; t.setState(0,0,1);
    applyTransformation(t,e,s);
    REQUIRE_EQ(s.siteState(a,0),1); REQUIRE(!s.bound(a,1)); REQUIRE_EQ(s.liveCount(),1u);
}

CONTRACT_CASE("bind action creates symmetric bond endpoints") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1);
    MatchEmbedding e; e.bindNode(0,a); e.bindNode(1,b);
    TransformationIR t; t.addBond(0,1,1,0); applyTransformation(t,e,s);
    REQUIRE(s.bound(a,1)); REQUIRE(s.bound(b,0));
    REQUIRE_EQ(s.bond(a,1).particle,b); REQUIRE_EQ(s.bond(b,0).particle,a);
}

CONTRACT_CASE("delete bond clears both endpoints") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1); s.bind(a,1,b,0);
    MatchEmbedding e; e.bindNode(0,a); e.bindNode(1,b);
    TransformationIR t; t.deleteBond(0,1,1,0); applyTransformation(t,e,s);
    REQUIRE(!s.bound(a,1)); REQUIRE(!s.bound(b,0));
}

CONTRACT_CASE("create molecule initializes all declared states before subsequent actions") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0);
    MatchEmbedding e; e.bindNode(0,a);
    TransformationIR t;
    auto created=t.createMolecule(1,{{1,1}});
    t.addBondExistingToCreated(0,1,created,0);
    auto result=applyTransformation(t,e,s);
    auto b=result.created(created);
    REQUIRE(s.alive(b)); REQUIRE_EQ(s.type(b),1u); REQUIRE_EQ(s.siteState(b,1),1);
    REQUIRE_EQ(s.bond(a,1).particle,b);
}

CONTRACT_CASE("destroy molecule automatically removes all incident bonds") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1); s.bind(a,1,b,0);
    MatchEmbedding e; e.bindNode(0,a); e.bindNode(1,b);
    TransformationIR t; t.destroyMolecule(1); applyTransformation(t,e,s);
    REQUIRE(!s.alive(b)); REQUIRE(!s.bound(a,1)); REQUIRE_EQ(s.liveCount(),1u);
}

CONTRACT_CASE("destroy complex removes every transitively connected member") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1), c=s.create(0);
    s.bind(a,1,b,0); s.bind(c,1,b,1);
    MatchEmbedding e; e.bindNode(0,a);
    TransformationIR t; t.destroyComplexContaining(0); applyTransformation(t,e,s);
    REQUIRE_EQ(s.liveCount(),0u); REQUIRE(!s.alive(a)); REQUIRE(!s.alive(b)); REQUIRE(!s.alive(c));
}

CONTRACT_CASE("delete one molecule does not delete disconnected products") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1), c=s.create(0);
    s.bind(a,1,b,0);
    MatchEmbedding e; e.bindNode(0,a); e.bindNode(1,b); e.bindNode(2,c);
    TransformationIR t; t.destroyMolecule(1); applyTransformation(t,e,s);
    REQUIRE(s.alive(a)); REQUIRE(s.alive(c)); REQUIRE_EQ(s.liveCount(),2u);
}

CONTRACT_CASE("transaction validates all actions before mutating state") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1); s.bind(a,1,b,0);
    auto before=s.snapshot(); MatchEmbedding e; e.bindNode(0,a); e.bindNode(1,b);
    TransformationIR t; t.setState(0,0,1); t.addBond(0,1,1,0); // illegal: already bound
    REQUIRE_THROWS_AS(applyTransformation(t,e,s), TransformationError);
    REQUIRE_EQ(s.snapshot(),before);
}

CONTRACT_CASE("stale embedding makes entire transformation fail atomically") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0); MatchEmbedding e; e.bindNode(0,a); s.destroy(a);
    auto before=s.snapshot(); TransformationIR t; t.createMolecule(1,{});
    REQUIRE_THROWS_AS(applyTransformation(t,e,s), StaleEmbeddingError);
    REQUIRE_EQ(s.snapshot(),before);
}

CONTRACT_CASE("multiple state changes on same site normalize to final state") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0); MatchEmbedding e; e.bindNode(0,a);
    TransformationIR t; t.setState(0,0,1); t.setState(0,0,0); t.setState(0,0,1);
    auto compiled=compileTransformation(t,m);
    REQUIRE_EQ(compiled.writeSet().size(),1u); applyTransformation(compiled,e,s); REQUIRE_EQ(s.siteState(a,0),1);
}

CONTRACT_CASE("conflicting create IDs are rejected at compile time") {
    auto m=schema(); TransformationIR t; t.createMoleculeWithId(5,1,{}); t.createMoleculeWithId(5,1,{});
    REQUIRE_THROWS_AS(compileTransformation(t,m), TransformationCompileError);
}

CONTRACT_CASE("binding one site twice in the same product is rejected") {
    auto m=schema(); TransformationIR t; auto x=t.createMolecule(0,{}), y=t.createMolecule(1,{}), z=t.createMolecule(1,{});
    t.addBondCreated(x,1,y,0); t.addBondCreated(x,1,z,0);
    REQUIRE_THROWS_AS(compileTransformation(t,m), TransformationCompileError);
}

CONTRACT_CASE("product mapping preserves identity of unchanged reactants") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1); MatchEmbedding e; e.bindNode(0,a); e.bindNode(1,b);
    TransformationIR t; t.setState(0,0,1); auto r=applyTransformation(t,e,s);
    REQUIRE_EQ(r.productParticleForReactantNode(0),a); REQUIRE_EQ(r.productParticleForReactantNode(1),b);
}

CONTRACT_CASE("unbinding may split one complex into two without deleting either") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1); s.bind(a,1,b,0);
    MatchEmbedding e; e.bindNode(0,a); e.bindNode(1,b); TransformationIR t; t.deleteBond(0,1,1,0); applyTransformation(t,e,s);
    REQUIRE_NE(s.complexId(a),s.complexId(b)); REQUIRE_EQ(s.liveCount(),2u);
}

CONTRACT_CASE("binding merges complexes and preserves all particles") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1);
    auto ca=s.complexId(a), cb=s.complexId(b); REQUIRE_NE(ca,cb);
    MatchEmbedding e; e.bindNode(0,a); e.bindNode(1,b); TransformationIR t; t.addBond(0,1,1,0); applyTransformation(t,e,s);
    REQUIRE_EQ(s.complexId(a),s.complexId(b)); REQUIRE_EQ(s.liveCount(),2u);
}

CONTRACT_CASE("transformation reports exact mutation set for dependency repair") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1); MatchEmbedding e; e.bindNode(0,a); e.bindNode(1,b);
    TransformationIR t; t.setState(0,0,1); t.addBond(0,1,1,0);
    auto r=applyTransformation(t,e,s);
    REQUIRE(r.mutations.contains(Mutation::siteStateChanged(a,0,0,1)));
    REQUIRE(r.mutations.containsBondChange(a,1,b,0));
}

CONTRACT_CASE("failed transformation emits no dependency mutations") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0); MatchEmbedding e; e.bindNode(0,a);
    TransformationIR t; t.addBond(0,1,999,0);
    TransformationResult out;
    REQUIRE_THROWS_AS(out=applyTransformation(t,e,s),TransformationError);
    REQUIRE(out.mutations.empty());
}

CONTRACT_CASE("transform then inverse transform restores canonical state") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1); MatchEmbedding e; e.bindNode(0,a); e.bindNode(1,b);
    auto before=s.canonicalState();
    TransformationIR fwd; fwd.setState(0,0,1); fwd.addBond(0,1,1,0);
    auto compiled=compileTransformation(fwd,m); auto inv=compiled.inverseFor(e,s);
    applyTransformation(compiled,e,s); applyTransformation(inv,e,s);
    REQUIRE_EQ(s.canonicalState(),before);
}

CONTRACT_CASE("destroy and slot reuse never resurrects old bonds") {
    auto m=schema(); GenericGraphState s(m); auto a=s.create(0), b=s.create(1); s.bind(a,1,b,0); s.destroy(b); auto b2=s.create(1);
    REQUIRE(!s.bound(a,1)); REQUIRE(!s.bound(b2,0)); REQUIRE_NE(b,b2);
}

CONTRACT_CASE("compiled transformation performs no dynamic allocation in event hot path") {
    auto m=schema(); TransformationIR t; t.setState(0,0,1); t.createMolecule(1,{{1,1}});
    auto c=compileTransformation(t,m); REQUIRE_EQ(c.dynamicAllocationCountDuringDryRun(),0u);
}

CONTRACT_MAIN("transformations")
#else
#error "RED CONTRACT: implement exact transformation IR/compiler/application"
#endif
