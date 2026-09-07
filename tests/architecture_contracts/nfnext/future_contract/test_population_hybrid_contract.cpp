#include "contract_test.hpp"

#if __has_include("nfnext/population.hpp") && __has_include("nfnext/hybrid_state.hpp")
#include "nfnext/population.hpp"
#include "nfnext/hybrid_state.hpp"
#include <limits>
using namespace nfnext;

CONTRACT_CASE("population dimer propensity uses exact combinatorial falling factorial convention") {
    PopulationState s; auto A=s.addSpecies("A",5); PopulationReaction r; r.rate=3.0; r.consume(A,2);
    REQUIRE_NEAR(r.propensity(s),30.0,1e-12);
}

CONTRACT_CASE("population trimer propensity is zero below stoichiometric requirement") {
    PopulationState s; auto A=s.addSpecies("A",2); PopulationReaction r; r.rate=10; r.consume(A,3); REQUIRE_EQ(r.propensity(s),0.0);
}

CONTRACT_CASE("population update is atomic on underflow") {
    PopulationState s; auto A=s.addSpecies("A",1),B=s.addSpecies("B",4); PopulationReaction r; r.consume(A,2); r.produce(B,9); auto before=s.snapshot(); REQUIRE_THROWS_AS(r.fire(s),PopulationError); REQUIRE_EQ(s.snapshot(),before);
}

CONTRACT_CASE("population count uses at least 64-bit storage") {
    PopulationState s; auto A=s.addSpecies("A",static_cast<std::uint64_t>(1)<<40); REQUIRE_EQ(s.count(A),static_cast<std::uint64_t>(1)<<40);
}

CONTRACT_CASE("population overflow is rejected rather than wrapping") {
    PopulationState s; auto A=s.addSpecies("A",std::numeric_limits<std::uint64_t>::max()); PopulationReaction r; r.produce(A,1); REQUIRE_THROWS_AS(r.fire(s),PopulationOverflow);
}

CONTRACT_CASE("hybrid model allows particle catalyst with population substrate") {
    HybridSchema h; auto E=h.particleType("E",{{"b",{}}}); auto S=h.populationType("S"); auto P=h.populationType("P");
    HybridRule r; auto e=r.particleReactant(E); r.requireFree(e,"b"); r.consumePopulation(S,1); r.producePopulation(P,1); r.rate=2.0;
    REQUIRE_NO_THROW(h.validate(r));
}

CONTRACT_CASE("hybrid propensity multiplies particle embeddings by population combinatorics") {
    HybridSchema h; auto E=h.particleType("E",{{"b",{}}}); auto S=h.populationType("S"); auto P=h.populationType("P"); HybridState s(h); s.create(E); s.create(E); s.setPopulation(S,7);
    HybridRule r; auto e=r.particleReactant(E); r.requireFree(e,"b"); r.consumePopulation(S,2); r.producePopulation(P,1); r.rate=.5;
    // 2 enzyme embeddings * C(7,2) * 0.5 = 21
    REQUIRE_NEAR(h.compile(r).propensity(s),21.0,1e-12);
}

CONTRACT_CASE("hybrid firing mutates particle and population sides atomically") {
    HybridSchema h; auto E=h.particleType("E",{{"x",{"0","1"}}}); auto S=h.populationType("S"); auto P=h.populationType("P"); HybridState s(h); auto e=s.create(E); s.setPopulation(S,3);
    HybridRule r; auto er=r.particleReactant(E); r.requireState(er,"x","0"); r.setState(er,"x","1"); r.consumePopulation(S,1); r.producePopulation(P,1); r.rate=1;
    auto ev=h.compile(r).firstEvent(s); ev.fire(s); REQUIRE_EQ(s.siteState(e,"x"),"1"); REQUIRE_EQ(s.population(S),2u); REQUIRE_EQ(s.population(P),1u);
}

CONTRACT_CASE("failed hybrid particle transformation rolls back population decrements") {
    HybridSchema h; auto E=h.particleType("E",{{"b",{}}}); auto F=h.particleType("F",{{"b",{}}}); auto S=h.populationType("S"); HybridState s(h); auto e=s.create(E),f=s.create(F); s.bind(e,"b",f,"b"); s.setPopulation(S,10);
    HybridRule r; auto er=r.particleReactant(E); auto fr=r.particleReactant(F); r.consumePopulation(S,2); r.addBond(er,"b",fr,"b"); r.rate=1; auto before=s.snapshot(); REQUIRE_THROWS_AS(h.compile(r).firstEvent(s).fire(s),HybridTransformationError); REQUIRE_EQ(s.snapshot(),before);
}

CONTRACT_CASE("particleization threshold migration preserves total molecule number") {
    HybridSchema h; auto A=h.hybridizableType("A"); HybridState s(h); s.setPopulation(A,100000); auto before=s.totalCopies(A); s.particleize(A,100); REQUIRE_EQ(s.totalCopies(A),before); REQUIRE_EQ(s.particleCount(A),100u); REQUIRE_EQ(s.population(A),99900u);
}

CONTRACT_CASE("departicleization of equivalent free particles preserves observables") {
    HybridSchema h; auto A=h.hybridizableType("A"); HybridState s(h); for(int i=0;i<500;++i)s.create(A); auto obs=s.observableTotal(A); s.departicleizeEligible(A); REQUIRE_EQ(s.observableTotal(A),obs); REQUIRE_EQ(s.particleCount(A),0u); REQUIRE_EQ(s.population(A),500u);
}

CONTRACT_CASE("bound or internally distinct particles are not departicleized") {
    HybridSchema h; auto A=h.hybridizableType("A",{{"x",{"0","1"}},{"b",{}}}); HybridState s(h); auto a=s.create(A),b=s.create(A); s.setSiteState(a,"x","1"); s.bind(a,"b",b,"b"); s.departicleizeEligible(A); REQUIRE_EQ(s.particleCount(A),2u);
}

CONTRACT_CASE("hybrid representation switching is optional and does not affect RNG stream") {
    HybridSchema h; auto A=h.hybridizableType("A"); HybridSimulator x(h,42,9),y(h,42,9); x.state().setPopulation(A,1000); y.state().setPopulation(A,1000); y.state().particleize(A,100);
    for(int i=0;i<100;++i) REQUIRE_EQ(x.randomBits(i),y.randomBits(i));
}

CONTRACT_CASE("exact hybrid mode never uses tau leaping") {
    HybridOptions o; o.exact=true; HybridSimulator s(HybridSchema{},1,0,o); REQUIRE_EQ(s.integratorKind(),HybridIntegratorKind::ExactSSA);
}

CONTRACT_CASE("approximate population acceleration requires explicit opt-in") {
    HybridOptions o; REQUIRE(!o.allow_tau_leaping); o.allow_tau_leaping=true; REQUIRE(o.allow_tau_leaping);
}

CONTRACT_CASE("hybrid compiler rejects population type in bond predicate") {
    HybridSchema h; auto A=h.populationType("A"); HybridRule r; auto a=r.populationReactant(A,1); r.requireFree(a,"x"); REQUIRE_THROWS_AS(h.validate(r),HybridValidationError);
}

CONTRACT_CASE("hybrid compiler rejects particle stoichiometry encoded as population count") {
    HybridSchema h; auto A=h.particleType("A",{}); HybridRule r; r.consumePopulation(A,2); REQUIRE_THROWS_AS(h.validate(r),HybridValidationError);
}

CONTRACT_CASE("population and particle backends agree for unary unstructured chemistry") {
    HybridSchema h; auto A=h.hybridizableType("A"),B=h.hybridizableType("B"); HybridRule r; r.consumePopulation(A,1); r.producePopulation(B,1); r.rate=.7;
    auto pop=runAsPurePopulation(h,r,100,50,123); auto particles=runAsPureParticles(h,r,100,50,123); REQUIRE_EQ(pop.eventRuleTrace,particles.eventRuleTrace); REQUIRE_NEAR(pop.finalTime,particles.finalTime,0.0); REQUIRE_EQ(pop.total(A),particles.total(A)); REQUIRE_EQ(pop.total(B),particles.total(B));
}

CONTRACT_CASE("same seed hybrid trajectory is bit reproducible") {
    auto fixture=makeHybridBirthDeathFixture(); auto a=runHybrid(fixture,777,5,1000); auto b=runHybrid(fixture,777,5,1000); REQUIRE_EQ(a.traceBytes,b.traceBytes); REQUIRE_EQ(a.stateFingerprint,b.stateFingerprint);
}

CONTRACT_MAIN("population-hybrid")
#else
#error "RED CONTRACT: finish population backend and implement exact particle/population hybrid state"
#endif
