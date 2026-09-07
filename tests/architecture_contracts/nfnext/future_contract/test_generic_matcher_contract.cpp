#include "contract_test.hpp"

#if __has_include("nfnext/generic_matcher.hpp") && __has_include("nfnext/pattern_ir.hpp")
#include "nfnext/generic_matcher.hpp"
#include "nfnext/pattern_ir.hpp"
#include "nfnext/generic_state.hpp"
#include <algorithm>
#include <set>
using namespace nfnext;

static ModelIR graphSchema() {
    ModelIR m;
    MoleculeTypeIR A; A.id=0; A.name="A";
    A.sites = {SiteSpec{"x",{"u","p"}}, SiteSpec{"b",{}}};
    MoleculeTypeIR B; B.id=1; B.name="B";
    B.sites = {SiteSpec{"a",{}}, SiteSpec{"c",{}}};
    MoleculeTypeIR C; C.id=2; C.name="C";
    C.sites = {SiteSpec{"b",{}}};
    m.molecule_types={A,B,C};
    return m;
}

static PatternIR chainABC() {
    PatternIR p;
    auto a=p.addNode(0); auto b=p.addNode(1); auto c=p.addNode(2);
    p.node(a).siteState(0,0);
    p.requireBond(a,1,b,0);
    p.requireBond(b,1,c,0);
    return p;
}

CONTRACT_CASE("single node state pattern counts each matching particle once") {
    auto m=graphSchema(); GenericGraphState s(m);
    auto a0=s.create(0); auto a1=s.create(0); auto a2=s.create(0);
    s.setSiteState(a0,0,0); s.setSiteState(a1,0,1); s.setSiteState(a2,0,0);
    PatternIR p; auto n=p.addNode(0); p.node(n).siteState(0,0);
    GenericMatcher match(m);
    auto embeddings=match.enumerate(p,s);
    REQUIRE_EQ(embeddings.size(),2u);
}

CONTRACT_CASE("connected three-node chain requires exact bond topology") {
    auto m=graphSchema(); GenericGraphState s(m);
    auto a=s.create(0), b=s.create(1), c=s.create(2), loose=s.create(2);
    s.setSiteState(a,0,0); s.bind(a,1,b,0); s.bind(b,1,c,0);
    GenericMatcher match(m);
    auto e=match.enumerate(chainABC(),s);
    REQUIRE_EQ(e.size(),1u);
    REQUIRE_EQ(e[0].particle(0),a); REQUIRE_EQ(e[0].particle(1),b); REQUIRE_EQ(e[0].particle(2),c);
    (void)loose;
}

CONTRACT_CASE("missing required bond rejects otherwise type-compatible assignment") {
    auto m=graphSchema(); GenericGraphState s(m);
    auto a=s.create(0), b=s.create(1), c=s.create(2);
    s.setSiteState(a,0,0); s.bind(a,1,b,0);
    GenericMatcher match(m);
    REQUIRE(match.enumerate(chainABC(),s).empty());
    (void)c;
}

CONTRACT_CASE("required-free predicate rejects bound site") {
    auto m=graphSchema(); GenericGraphState s(m);
    auto a=s.create(0), b=s.create(1); s.bind(a,1,b,0);
    PatternIR p; auto n=p.addNode(0); p.node(n).siteFree(1);
    REQUIRE(GenericMatcher(m).enumerate(p,s).empty());
}

CONTRACT_CASE("required-bound predicate accepts any partner unless partner constrained") {
    auto m=graphSchema(); GenericGraphState s(m);
    auto a=s.create(0), c=s.create(2); s.bind(a,1,c,0);
    PatternIR p; auto n=p.addNode(0); p.node(n).siteBound(1);
    REQUIRE_EQ(GenericMatcher(m).enumerate(p,s).size(),1u);
}

CONTRACT_CASE("same particle cannot satisfy two distinct pattern nodes unless alias explicitly allowed") {
    auto m=graphSchema(); GenericGraphState s(m); auto a=s.create(0);
    PatternIR p; p.addNode(0); p.addNode(0);
    REQUIRE(GenericMatcher(m).enumerate(p,s).empty());
    p.allowAlias(0,1);
    REQUIRE_EQ(GenericMatcher(m).enumerate(p,s).size(),1u);
}

CONTRACT_CASE("different-reactant molecularity requires distinct complexes") {
    auto m=graphSchema(); GenericGraphState s(m);
    auto a=s.create(0), b=s.create(1); s.bind(a,1,b,0);
    PatternIR p; p.addNode(0); p.addNode(1); p.requireDifferentComplex(0,1);
    REQUIRE(GenericMatcher(m).enumerate(p,s).empty());
    s.unbind(a,1);
    REQUIRE_EQ(GenericMatcher(m).enumerate(p,s).size(),1u);
}

CONTRACT_CASE("same-complex molecularity can be satisfied through indirect path") {
    auto m=graphSchema(); GenericGraphState s(m);
    auto a=s.create(0), b=s.create(1), c=s.create(2);
    s.bind(a,1,b,0); s.bind(b,1,c,0);
    PatternIR p; p.addNode(0); p.addNode(2); p.requireSameComplex(0,1);
    REQUIRE_EQ(GenericMatcher(m).enumerate(p,s).size(),1u);
}

CONTRACT_CASE("symmetry automorphisms do not overcount identical two-node pattern") {
    ModelIR m; MoleculeTypeIR A; A.id=0; A.name="A"; A.sites={SiteSpec{"b",{}}}; m.molecule_types={A};
    GenericGraphState s(m); auto a=s.create(0), b=s.create(0); s.bind(a,0,b,0);
    PatternIR p; p.addNode(0); p.addNode(0); p.requireBond(0,0,1,0);
    p.markInterchangeable({0,1});
    GenericMatcher gm(m);
    REQUIRE_EQ(gm.enumerate(p,s).size(),1u);
    REQUIRE_EQ(gm.embeddingMultiplicity(p,s),1u);
}

CONTRACT_CASE("asymmetric labeled nodes retain distinct embeddings") {
    ModelIR m; MoleculeTypeIR A; A.id=0; A.name="A"; A.sites={SiteSpec{"x",{"0","1"}},SiteSpec{"b",{}}}; m.molecule_types={A};
    GenericGraphState s(m); auto a=s.create(0), b=s.create(0); s.bind(a,1,b,1); s.setSiteState(a,0,0); s.setSiteState(b,0,1);
    PatternIR p; auto x=p.addNode(0), y=p.addNode(0); p.node(x).siteState(0,0); p.node(y).siteState(0,1); p.requireBond(x,1,y,1);
    REQUIRE_EQ(GenericMatcher(m).enumerate(p,s).size(),1u);
}

CONTRACT_CASE("stateSet predicate accepts exactly listed states") {
    auto m=graphSchema(); GenericGraphState s(m);
    auto a=s.create(0); PatternIR p; auto n=p.addNode(0); p.node(n).siteStateSet(0,{0});
    s.setSiteState(a,0,0); REQUIRE_EQ(GenericMatcher(m).enumerate(p,s).size(),1u);
    s.setSiteState(a,0,1); REQUIRE(GenericMatcher(m).enumerate(p,s).empty());
}

CONTRACT_CASE("connectedTo predicate honors graph reachability rather than direct bond only") {
    auto m=graphSchema(); GenericGraphState s(m);
    auto a=s.create(0), b=s.create(1), c=s.create(2); s.bind(a,1,b,0); s.bind(b,1,c,0);
    PatternIR p; p.addNode(0); p.addNode(2); p.requireConnectedTo(0,1);
    REQUIRE_EQ(GenericMatcher(m).enumerate(p,s).size(),1u);
}

CONTRACT_CASE("connectedTo predicate rejects separate complexes") {
    auto m=graphSchema(); GenericGraphState s(m); s.create(0); s.create(2);
    PatternIR p; p.addNode(0); p.addNode(2); p.requireConnectedTo(0,1);
    REQUIRE(GenericMatcher(m).enumerate(p,s).empty());
}

CONTRACT_CASE("matcher never returns stale particle handles") {
    auto m=graphSchema(); GenericGraphState s(m); auto old=s.create(0); s.destroy(old); auto fresh=s.create(0);
    PatternIR p; p.addNode(0);
    auto e=GenericMatcher(m).enumerate(p,s);
    REQUIRE_EQ(e.size(),1u); REQUIRE_EQ(e[0].particle(0),fresh); REQUIRE_NE(e[0].particle(0),old);
}

CONTRACT_CASE("matcher result is invariant to particle allocation order") {
    auto m=graphSchema(); GenericGraphState a(m),b(m);
    auto aA=a.create(0), aB=a.create(1), aC=a.create(2); a.setSiteState(aA,0,0); a.bind(aA,1,aB,0); a.bind(aB,1,aC,0);
    auto bC=b.create(2), bB=b.create(1), bA=b.create(0); b.setSiteState(bA,0,0); b.bind(bA,1,bB,0); b.bind(bB,1,bC,0);
    auto ca=GenericMatcher(m).canonicalEmbeddings(chainABC(),a);
    auto cb=GenericMatcher(m).canonicalEmbeddings(chainABC(),b);
    REQUIRE_EQ(ca.size(),cb.size()); REQUIRE_EQ(ca[0].typeSignature(),cb[0].typeSignature());
}

CONTRACT_CASE("matcher prefilter cannot introduce false negatives") {
    auto m=graphSchema(); GenericGraphState s(m);
    std::vector<ParticleId> as,bs,cs;
    for(int i=0;i<100;++i){ as.push_back(s.create(0)); bs.push_back(s.create(1)); cs.push_back(s.create(2)); s.setSiteState(as.back(),0,i%2); }
    for(int i=0;i<100;i+=7){ s.bind(as[i],1,bs[i],0); s.bind(bs[i],1,cs[i],0); }
    GenericMatcher gm(m);
    auto exact=gm.enumerate(chainABC(),s,MatchMode::ReferenceBacktracking);
    auto fast=gm.enumerate(chainABC(),s,MatchMode::CompiledPlan);
    REQUIRE_EQ(gm.canonicalize(exact),gm.canonicalize(fast));
}

CONTRACT_CASE("compiled match plan contains no heap allocation in hot match call") {
    auto m=graphSchema(); auto plan=compileMatchPlan(chainABC(),m);
    REQUIRE(plan.isImmutable());
    REQUIRE_EQ(plan.dynamicAllocationCountDuringDryRun(),0u);
}

CONTRACT_CASE("pattern with impossible local constraint is rejected by compiler") {
    auto m=graphSchema(); PatternIR p; auto n=p.addNode(0); p.node(n).siteState(0,0); p.node(n).siteState(0,1);
    REQUIRE_THROWS_AS(compileMatchPlan(p,m), PatternCompileError);
}

CONTRACT_CASE("pattern requiring same site both free and bound is rejected") {
    auto m=graphSchema(); PatternIR p; auto n=p.addNode(0); p.node(n).siteFree(1); p.node(n).siteBound(1);
    REQUIRE_THROWS_AS(compileMatchPlan(p,m), PatternCompileError);
}

CONTRACT_CASE("automorphism count agrees with brute-force permutation oracle on tiny patterns") {
    ModelIR m; MoleculeTypeIR A; A.id=0; A.name="A"; A.sites={SiteSpec{"b",{}}}; m.molecule_types={A};
    for (int n=1;n<=5;++n) {
        PatternIR p; for(int i=0;i<n;++i)p.addNode(0);
        for(int i=0;i+1<n;++i)p.requireBond(i,0,i+1,0);
        auto compiled=compileMatchPlan(p,m);
        REQUIRE_EQ(compiled.automorphismCount(), bruteForceAutomorphismCount(p,m));
    }
}

CONTRACT_MAIN("generic-matcher")
#else
#error "RED CONTRACT: implement arbitrary graph pattern IR and generic matcher"
#endif
