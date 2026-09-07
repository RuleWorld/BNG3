#include "contract_test.hpp"

#if __has_include("nfnext/interval_genome.hpp") && __has_include("nfnext/lattice_kernel.hpp")
#include "nfnext/interval_genome.hpp"
#include "nfnext/lattice_kernel.hpp"
#include <algorithm>
#include <random>
using namespace nfnext;

CONTRACT_CASE("empty billion-base genome uses constant-scale sparse metadata") {
    IntervalGenome g(1'000'000'000ull);
    REQUIRE_EQ(g.length(),1'000'000'000ull);
    REQUIRE_EQ(g.segmentCount(),1u);
    REQUIRE(g.memoryBytes() < 4096u);
}

CONTRACT_CASE("setting one coordinate splits only local interval") {
    IntervalGenome g(1'000'000); g.setState(500000, GenomeState::Active);
    REQUIRE(g.segmentCount() <= 3u); REQUIRE_EQ(g.state(499999),GenomeState::Default); REQUIRE_EQ(g.state(500000),GenomeState::Active); REQUIRE_EQ(g.state(500001),GenomeState::Default);
}

CONTRACT_CASE("adjacent equal intervals coalesce") {
    IntervalGenome g(1000); g.setRange(100,199,GenomeState::Active); g.setRange(200,299,GenomeState::Active);
    REQUIRE_EQ(g.segmentCount(),3u); REQUIRE_EQ(g.state(150),GenomeState::Active); REQUIRE_EQ(g.state(250),GenomeState::Active);
}

CONTRACT_CASE("reverting range to default coalesces aggressively") {
    IntervalGenome g(1000); g.setRange(100,899,GenomeState::Active); g.setRange(100,899,GenomeState::Default);
    REQUIRE_EQ(g.segmentCount(),1u);
}

CONTRACT_CASE("range query is exact on boundaries") {
    IntervalGenome g(100); g.setRange(10,20,GenomeState::Blocked);
    REQUIRE_EQ(g.state(9),GenomeState::Default); REQUIRE_EQ(g.state(10),GenomeState::Blocked); REQUIRE_EQ(g.state(20),GenomeState::Blocked); REQUIRE_EQ(g.state(21),GenomeState::Default);
}

CONTRACT_CASE("out of range coordinate is rejected") {
    IntervalGenome g(10); REQUIRE_THROWS_AS(g.state(10),std::out_of_range); REQUIRE_THROWS_AS(g.setRange(9,10,GenomeState::Active),std::out_of_range);
}

CONTRACT_CASE("transcript sparse coordinate state does not instantiate empty bases") {
    TranscriptState t(50'000'000); for(std::uint64_t p: {5ull,1000ull,4'000'000ull,49'999'999ull}) t.markFeature(p,TranscriptFeature::Pause);
    REQUIRE_EQ(t.materializedCoordinateCount(),4u); REQUIRE(t.memoryBytes()<8192u);
}

CONTRACT_CASE("footprint exclusion blocks overlapping ribosomes") {
    TranslationLatticeConfig c; c.length=100; c.footprint=10; c.hop_rate=1;
    TranslationLattice s(c); REQUIRE(s.placeRibosome(20));
    for(Position p=11;p<=29;++p) REQUIRE(!s.canPlaceRibosome(p));
    REQUIRE(s.canPlaceRibosome(30));
}

CONTRACT_CASE("hop eligibility depends only on entering footprint coordinate") {
    TranslationLatticeConfig c; c.length=100; c.footprint=10; c.hop_rate=1;
    TranslationLattice s(c); s.placeRibosome(20); REQUIRE(s.canHop(20)); s.blockCoordinate(30); REQUIRE(!s.canHop(20)); s.unblockCoordinate(30); REQUIRE(s.canHop(20));
}

CONTRACT_CASE("single occupancy mutation repairs bounded local channels") {
    TranslationLatticeConfig c; c.length=1'000'000; c.footprint=10; TranslationLattice s(c);
    for(Position p=100;p<900000;p+=1000) s.placeRibosome(p);
    auto before=s.repairCounter(); s.blockCoordinate(450000); auto delta=s.repairCounter()-before;
    REQUIRE(delta <= 2*c.footprint+8);
}

CONTRACT_CASE("lattice propensity equals explicit scan oracle") {
    TranslationLatticeConfig c; c.length=500; c.footprint=10; c.hop_rate=2.25; c.initiation_rate=.7; c.termination_rate=1.2;
    TranslationLattice s(c); for(Position p: {10u,40u,71u,130u,300u,470u}) REQUIRE(s.placeRibosome(p));
    double ref=0; for(Position p=0;p<c.length;++p) if(s.isHead(p)&&s.canHop(p)) ref+=c.hop_rate; if(s.canInitiate())ref+=c.initiation_rate; if(s.canTerminate())ref+=c.termination_rate;
    REQUIRE_NEAR(s.totalPropensity(),ref,1e-12);
}

CONTRACT_CASE("periodic footprint greater than one handles wraparound exclusion") {
    TranslationLatticeConfig c; c.length=20; c.footprint=4; c.periodic=true; TranslationLattice s(c); REQUIRE(s.placeRibosome(18));
    REQUIRE(!s.canPlaceRibosome(0)); REQUIRE(!s.canPlaceRibosome(1)); REQUIRE(!s.canPlaceRibosome(17)); REQUIRE(s.canPlaceRibosome(3));
}

CONTRACT_CASE("termination removes full footprint occupancy") {
    TranslationLatticeConfig c; c.length=30; c.footprint=5; c.termination_rate=1; TranslationLattice s(c); REQUIRE(s.placeRibosome(25)); REQUIRE(s.canTerminate()); REQUIRE(s.terminate());
    for(Position p=25;p<30;++p) REQUIRE(!s.occupied(p)); REQUIRE_EQ(s.ribosomeCount(),0u);
}

CONTRACT_CASE("initiation cannot overlap existing footprint") {
    TranslationLatticeConfig c; c.length=100; c.footprint=8; c.initiation_position=0; c.initiation_rate=1; TranslationLattice s(c); REQUIRE(s.placeRibosome(7)); REQUIRE(!s.canInitiate());
}

CONTRACT_CASE("coordinate-specific elongation rates match explicit family rates") {
    TranslationLatticeConfig c; c.length=100; c.footprint=1; c.hop_rate=1; c.coordinate_rates.resize(100,1.0); c.coordinate_rates[20]=9.0;
    TranslationLattice s(c); s.placeRibosome(20); REQUIRE_NEAR(s.hopPropensityAt(20),9.0,0.0);
}

CONTRACT_CASE("blocked genome interval disables all entering hops across range") {
    TranslationLatticeConfig c; c.length=1000; c.footprint=1; TranslationLattice s(c); for(Position p=90;p<130;p+=2)s.placeRibosome(p); s.blockRange(100,110);
    for(Position p=99;p<=109;++p) if(s.isHead(p)) REQUIRE(!s.canHop(p));
}

CONTRACT_CASE("large coordinate uses 64-bit positions without truncation") {
    TranslationLatticeConfig c; c.length=6'000'000'000ull; c.footprint=1; TranslationLattice s(c); const std::uint64_t p=5'000'000'000ull; REQUIRE(s.placeRibosome(p)); REQUIRE(s.isHead(p)); REQUIRE_EQ(s.headPositionAt(p),p);
}

CONTRACT_CASE("sparse lattice representation scales with particles not genome length") {
    TranslationLatticeConfig c; c.length=10'000'000'000ull; c.footprint=10; c.storage=LatticeStorage::Sparse; TranslationLattice s(c); for(std::uint64_t p=1000;p<1'000'000;p+=10000)s.placeRibosome(p);
    REQUIRE(s.memoryBytes() < 2'000'000u); REQUIRE(s.materializedSites() < 5000u);
}

CONTRACT_CASE("dense and sparse lattice backends are state-equivalent on small genome") {
    TranslationLatticeConfig a; a.length=300; a.footprint=7; a.storage=LatticeStorage::Dense;
    auto b=a; b.storage=LatticeStorage::Sparse; TranslationLattice x(a),y(b);
    for(Position p: {10u,50u,100u,160u,240u}){REQUIRE(x.placeRibosome(p));REQUIRE(y.placeRibosome(p));}
    for(int step=0;step<100;++step){auto e=x.selectByUnit((step*0.61803398875)-std::floor(step*0.61803398875)); auto f=y.selectByUnit((step*0.61803398875)-std::floor(step*0.61803398875)); REQUIRE_EQ(e,f); REQUIRE_EQ(x.fire(e),y.fire(f)); REQUIRE_EQ(x.canonicalState(),y.canonicalState()); if(x.totalPropensity()==0)break;}
}

CONTRACT_CASE("random local update propensity agrees with full recomputation oracle") {
    std::mt19937_64 rng(7788); TranslationLatticeConfig c; c.length=5000; c.footprint=10; c.initiation_rate=.1; c.termination_rate=.3; TranslationLattice s(c);
    for(int trial=0;trial<2000;++trial){Position p=rng()%c.length; if((rng()&1)&&s.canPlaceRibosome(p))s.placeRibosome(p); else if(s.isHead(p)&&s.canHop(p))s.hop(p); REQUIRE_NEAR(s.totalPropensity(),s.fullRecomputeTotalPropensity(),1e-12);}
}

CONTRACT_MAIN("lattice-interval")
#else
#error "RED CONTRACT: implement sparse interval genome and production lattice kernel"
#endif
