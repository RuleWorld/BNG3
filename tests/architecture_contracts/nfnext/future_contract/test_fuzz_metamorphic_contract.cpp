#include "contract_test.hpp"

#if __has_include("nfnext/fuzz_model.hpp") && __has_include("nfnext/metamorphic.hpp")
#include "nfnext/fuzz_model.hpp"
#include "nfnext/metamorphic.hpp"
#include <random>
using namespace nfnext;

CONTRACT_CASE("random valid NFIR always validates") { std::mt19937_64 rng(1);for(int i=0;i<10000;++i){auto m=randomValidModel(rng,FuzzLimits::small());REQUIRE_NO_THROW(validateModel(m));} }
CONTRACT_CASE("random single-field corruption is either rejected or semantically distinct") { std::mt19937_64 rng(2);for(int i=0;i<5000;++i){auto m=randomValidModel(rng,FuzzLimits::small());auto x=mutateOneField(m,rng);try{validateModel(x);REQUIRE_NE(canonicalizeModel(m).semanticFingerprint(),canonicalizeModel(x).semanticFingerprint());}catch(const ValidationError&){REQUIRE(true);} } }
CONTRACT_CASE("canonicalization is idempotent on random models") { std::mt19937_64 rng(3);for(int i=0;i<5000;++i){auto m=randomValidModel(rng,FuzzLimits::small());auto a=canonicalizeModel(m);auto b=canonicalizeModel(a.model);REQUIRE_EQ(a.canonicalBytes(),b.canonicalBytes());} }
CONTRACT_CASE("cache roundtrip is identity on random models") { std::mt19937_64 rng(4);for(int i=0;i<1000;++i){auto m=canonicalizeModel(randomValidModel(rng,FuzzLimits::small())).model;auto x=cacheRoundTripInMemory(m);REQUIRE_EQ(m.canonicalBytes(),x.canonicalBytes());} }

CONTRACT_CASE("renaming molecules and rules leaves trajectories semantically unchanged") { std::mt19937_64 rng(5);for(int i=0;i<500;++i){auto m=randomExecutableModel(rng);auto renamed=renameSymbols(m,rng);auto a=runCanonicalTrace(m,42,1000),b=runCanonicalTrace(renamed,42,1000);REQUIRE_EQ(stripNames(a),stripNames(b));} }
CONTRACT_CASE("permuting declaration order leaves canonical model and trajectory unchanged") { std::mt19937_64 rng(6);for(int i=0;i<500;++i){auto m=randomExecutableModel(rng);auto p=permuteDeclarations(m,rng);REQUIRE_EQ(canonicalizeModel(m).canonicalBytes(),canonicalizeModel(p).canonicalBytes());REQUIRE_EQ(runCanonicalTrace(m,7,500),runCanonicalTrace(p,7,500));} }
CONTRACT_CASE("adding unreachable molecule type does not alter trajectory") { std::mt19937_64 rng(7);for(int i=0;i<500;++i){auto m=randomExecutableModel(rng);auto x=addUnreachableType(m);REQUIRE_EQ(runCanonicalTrace(m,9,500),projectReachable(runCanonicalTrace(x,9,500)));} }
CONTRACT_CASE("adding zero-rate rule does not alter trajectory") { std::mt19937_64 rng(8);for(int i=0;i<500;++i){auto m=randomExecutableModel(rng);auto x=addZeroRateRule(m,rng);REQUIRE_EQ(runCanonicalTrace(m,11,500),projectOriginalRules(runCanonicalTrace(x,11,500)));} }
CONTRACT_CASE("splitting one family then recompiling yields same trajectory") { std::mt19937_64 rng(9);for(int i=0;i<500;++i){auto m=randomFamilyModel(rng);auto expanded=expandAllFamilies(m);auto a=runCanonicalTrace(m,13,1000),b=runCanonicalTrace(expanded,13,1000);REQUIRE_EQ(a,b);} }

CONTRACT_CASE("collapse then expand is semantic identity on random indexed families") { std::mt19937_64 rng(10);for(int i=0;i<5000;++i){auto rules=randomIndexedRuleSequence(rng,1+rng()%200);auto fam=compileRuleFamilies(rules);auto exp=expandFamilies(fam.families);REQUIRE(semanticRuleSequenceEqual(rules,exp));} }
CONTRACT_CASE("dependency incremental propensity equals full recomputation after random mutation") { std::mt19937_64 rng(11);for(int i=0;i<5000;++i){auto f=randomExecutableState(rng);auto mut=randomLegalMutation(f.state,rng);auto inc=f.applyIncremental(mut);auto full=f.fullRecompute();REQUIRE_EQ(inc.propensityBits,full.propensityBits);} }
CONTRACT_CASE("incremental observables equal full recomputation after random mutation") { std::mt19937_64 rng(12);for(int i=0;i<5000;++i){auto f=randomObservableState(rng);auto mut=randomLegalMutation(f.state,rng);f.apply(mut);REQUIRE_EQ(f.incrementalValues(),f.fullObservableValues());} }

CONTRACT_CASE("generic matcher compiled plan equals brute-force matcher on tiny random graphs") { std::mt19937_64 rng(13);for(int i=0;i<10000;++i){auto g=randomTinyGraph(rng,6);auto p=randomTinyPattern(rng,g.schema,4);auto fast=compiledMatches(p,g.state),ref=bruteForceMatches(p,g.state);REQUIRE_EQ(canonicalEmbeddings(fast),canonicalEmbeddings(ref));} }
CONTRACT_CASE("automorphism factor agrees with brute-force permutation oracle") { std::mt19937_64 rng(14);for(int i=0;i<5000;++i){auto p=randomTinyPatternGraph(rng,6);REQUIRE_EQ(computeAutomorphisms(p),bruteForceAutomorphisms(p));} }
CONTRACT_CASE("complex connectivity cache agrees with BFS oracle after random bond churn") { std::mt19937_64 rng(15);auto f=randomGraphState(rng,100);for(int i=0;i<100000;++i){applyRandomBondMutation(f,rng);for(int q=0;q<20;++q){auto a=f.randomParticle(rng),b=f.randomParticle(rng);REQUIRE_EQ(f.state.sameComplex(a,b),bfsConnected(f.state,a,b));}} }

CONTRACT_CASE("dense and sparse lattice match after random legal events") { std::mt19937_64 rng(16);for(int trial=0;trial<500;++trial){auto cfg=randomSmallLatticeConfig(rng);auto d=makeDenseLattice(cfg),s=makeSparseLattice(cfg);seedSameRandomOccupancy(d,s,rng);for(int step=0;step<1000&&d.totalPropensity()>0;++step){double u=unitFrom(rng());auto de=d.selectByUnit(u),se=s.selectByUnit(u);REQUIRE_EQ(de,se);d.fire(de);s.fire(se);REQUIRE_EQ(d.canonicalState(),s.canonicalState());}} }
CONTRACT_CASE("population propensity matches direct combinatorial oracle on random stoichiometry") { std::mt19937_64 rng(17);for(int i=0;i<100000;++i){auto f=randomPopulationReaction(rng,6,4);REQUIRE_NEAR(f.compiled.propensity(f.state),directMassActionPropensity(f),1e-12);} }

CONTRACT_CASE("serialization parser fuzz never crashes or overallocates") { std::mt19937_64 rng(18);for(int i=0;i<100000;++i){auto bytes=randomBytes(rng,rng()%4096);CacheLoadOptions o;o.max_bytes=8192;try{(void)parseCache(bytes,o);}catch(const CacheError&){}REQUIRE(processResidentMemoryDelta()<16*1024*1024);} }
CONTRACT_CASE("XML parser fuzz either rejects or produces valid NFIR") { std::mt19937_64 rng(19);for(int i=0;i<50000;++i){auto xml=randomXmlishBytes(rng,rng()%8192);try{auto m=XmlAdapter().parse(xml);REQUIRE_NO_THROW(validateModel(m));}catch(const XmlAdapterError&){}catch(const UnsupportedSemantic&){} } }

CONTRACT_CASE("event replay mutation fuzz detects corrupted event payload") { std::mt19937_64 rng(20);for(int i=0;i<1000;++i){auto t=makeValidTrace(rng,100);auto x=mutateOneTraceField(t,rng);if(x==t)continue;REQUIRE_THROWS_AS(replayStrict(x),ReplayError);} }
CONTRACT_CASE("checkpoint fuzz rejects stale particle generations") { std::mt19937_64 rng(21);for(int i=0;i<1000;++i){auto c=makeValidCheckpoint(rng);corruptOneGeneration(c,rng);REQUIRE_THROWS_AS(loadCheckpointStrict(c),CheckpointError);} }

CONTRACT_CASE("random backend-compatible model agrees with reference for many seeds") { std::mt19937_64 rng(22);for(int m=0;m<100;++m){auto f=randomBackendCompatibleFixture(rng);for(int seed=0;seed<20;++seed)REQUIRE(runEquivalent(f,BackendKind::Reference,f.optimizedBackend(),500,seed));} }
CONTRACT_CASE("shrinker preserves failing predicate while reducing model") { auto fail=makeSyntheticFuzzFailure();auto shrunk=shrinkFailure(fail);REQUIRE(shrunk.stillFails());REQUIRE(shrunk.modelSize()<fail.modelSize()); }
CONTRACT_CASE("fuzz seed is always emitted on failure") { auto r=runFuzzCampaignWithInjectedFailure(123456);REQUIRE(!r.ok);REQUIRE_EQ(r.reproducer.seed,123456u);REQUIRE(!r.reproducer.serialized_model.empty()); }

CONTRACT_MAIN("fuzz-metamorphic")
#else
#error "RED CONTRACT: implement fuzz generators, shrinkers, and metamorphic semantic harness"
#endif
