#include "contract_test.hpp"

#if __has_include("nfnext/compartments.hpp") && __has_include("nfnext/rate_laws.hpp")
#include "nfnext/compartments.hpp"
#include "nfnext/rate_laws.hpp"
#include <cmath>
using namespace nfnext;

CONTRACT_CASE("compartment hierarchy preserves parent relationships") { CompartmentTable c; auto cell=c.add("cell",3,1.0); auto mem=c.add("mem",2,1.0,cell); REQUIRE_EQ(c.parent(mem),cell); }
CONTRACT_CASE("compartment dimension must be 1 2 or 3") { CompartmentTable c; REQUIRE_THROWS_AS(c.add("bad",4,1),CompartmentError); }
CONTRACT_CASE("compartment size must be finite positive") { CompartmentTable c; REQUIRE_THROWS_AS(c.add("zero",3,0),CompartmentError); REQUIRE_THROWS_AS(c.add("neg",3,-1),CompartmentError); REQUIRE_THROWS_AS(c.add("nan",3,std::numeric_limits<double>::quiet_NaN()),CompartmentError); }
CONTRACT_CASE("duplicate compartment names reject") { CompartmentTable c;c.add("cell",3,1);REQUIRE_THROWS_AS(c.add("cell",3,2),CompartmentError); }
CONTRACT_CASE("cyclic compartment hierarchy rejects") { auto c=makeCyclicCompartmentFixture(); REQUIRE_THROWS_AS(c.validate(),CompartmentError); }

CONTRACT_CASE("particle compartment predicate matches exact compartment") { auto f=makeCompartmentStateFixture(); REQUIRE(f.matcher.matches(f.patternIn("cyto"),f.cyto_particle)); REQUIRE(!f.matcher.matches(f.patternIn("nuc"),f.cyto_particle)); }
CONTRACT_CASE("move-compartment transformation updates dependency features") { auto f=makeCompartmentStateFixture(); auto r=f.move(f.cyto_particle,"nuc"); REQUIRE_EQ(f.state.compartment(f.cyto_particle),f.nuc); REQUIRE(r.mutations.containsCompartmentChange(f.cyto_particle,f.cyto,f.nuc)); }

CONTRACT_CASE("elementary rate law returns base rate") { ElementaryRateLaw k(2.5); REQUIRE_NEAR(k.evaluate({}),2.5,0); }
CONTRACT_CASE("elementary negative rate rejects") { REQUIRE_THROWS_AS(ElementaryRateLaw(-1),RateLawError); }
CONTRACT_CASE("Michaelis-Menten law matches analytic formula") { MichaelisMentenRateLaw mm(4.0,3.0); RateContext c;c.substrate_count=6; REQUIRE_NEAR(mm.evaluate(c),4.0*6.0/(3.0+6.0),1e-12); }
CONTRACT_CASE("Michaelis-Menten denominator zero rejects") { REQUIRE_THROWS_AS(MichaelisMentenRateLaw(1,0).evaluate(RateContext{}),RateLawError); }

CONTRACT_CASE("DOR rate chooses branch from reactant state exactly") { auto d=makeDorFixture(); auto c0=d.contextForState(0),c1=d.contextForState(1); REQUIRE_NEAR(d.rate.evaluate(c0),d.k0,0); REQUIRE_NEAR(d.rate.evaluate(c1),d.k1,0); }
CONTRACT_CASE("DOR unknown branch state rejects rather than defaulting") { auto d=makeDorFixture(); REQUIRE_THROWS_AS(d.rate.evaluate(d.contextForState(99)),RateLawError); }

CONTRACT_CASE("energy-based forward reverse rates obey detailed-balance construction") { EnergyRateLaw e=makeTwoStateEnergyLaw(2.0,1.5,-0.7); auto kf=e.forwardRate(); auto kr=e.reverseRate(); REQUIRE_NEAR(std::log(kf/kr),-e.deltaEnergy(),1e-12); }
CONTRACT_CASE("energy pattern count changes energy contribution linearly") { auto e=makeEnergyPatternLaw(); auto c=e.context(); c.pattern_counts={0}; auto a=e.energy(c); c.pattern_counts={3}; auto b=e.energy(c); REQUIRE_NEAR(b-a,3*e.patternEnergy(0),1e-12); }
CONTRACT_CASE("energy local pattern matching agrees with generic matcher count") { auto e=makeEnergyPatternStateFixture(); REQUIRE_EQ(e.rateLaw.patternCount(e.state,0),e.genericMatcherCount(0)); }

CONTRACT_CASE("observable-dependent rate updates after observable mutation") { auto f=makeObservableRateFixture(); auto before=f.rate(); f.mutateObservableUp(); auto after=f.rate(); REQUIRE_NE(after,before); REQUIRE_NEAR(after,f.fullEvaluate(),1e-12); }
CONTRACT_CASE("time-dependent rate receives exact simulation time") { auto r=compileRateExpression("k0*(1+t)",{{"k0",2.0}}); REQUIRE_NEAR(r.evaluate(RateContext::atTime(3.5)),9.0,1e-12); }
CONTRACT_CASE("time-dependent rate scheduler announces next discontinuity") { auto r=makePiecewiseTimeRate({{0,1},{5,2},{10,0}}); REQUIRE_EQ(r.nextDiscontinuityAfter(1),5.0); REQUIRE_EQ(r.nextDiscontinuityAfter(5),10.0); }
CONTRACT_CASE("rate discontinuity is processed before event scheduled beyond it") { auto sim=makeRateDiscontinuityFixture(); auto e=sim.nextEvent(); REQUIRE_EQ(e.kind,EventKind::RateDiscontinuity); REQUIRE_EQ(e.time,5.0); }

CONTRACT_CASE("number-per-quantity-unit scaling enters conversion exactly once") { RateUnitSystem u;u.number_per_quantity_unit=6.022e23; auto k=u.convertBimolecular(1.2,3,1.0); REQUIRE(k>0); REQUIRE_NEAR(u.inverseConvertBimolecular(k,3,1.0),1.2,1e-12); }
CONTRACT_CASE("compartment volume scaling differs for uni and bimolecular rates") { RateUnitSystem u; REQUIRE_EQ(u.scaleElementary(1.0,1,2.0),1.0); REQUIRE_NE(u.scaleElementary(1.0,2,2.0),1.0); }

CONTRACT_CASE("rate law canonical fingerprint changes with every semantic coefficient") { auto a=makeEnergyPatternLaw(),b=a; auto h=a.semanticFingerprint(); b.setPatternEnergy(0,b.patternEnergy(0)+1e-9); REQUIRE_NE(h,b.semanticFingerprint()); }
CONTRACT_CASE("rate law diagnostics metadata does not affect semantic fingerprint") { auto a=makeDorFixture().rate,b=a; a.annotation="x";b.annotation="y";REQUIRE_EQ(a.semanticFingerprint(),b.semanticFingerprint()); }

CONTRACT_MAIN("compartment-rate")
#else
#error "RED CONTRACT: implement compartments and complete legacy rate-law semantics"
#endif
