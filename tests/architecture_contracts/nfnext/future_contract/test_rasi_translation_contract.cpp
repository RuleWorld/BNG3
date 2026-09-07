#include "contract_test.hpp"

#if __has_include("nfnext/rasi_translation.hpp")
#include "nfnext/rasi_translation.hpp"
#include <algorithm>
using namespace nfnext;

CONTRACT_CASE("Rasi indexed elongation family lowers to coordinate-parameterized kernel") { auto m=loadRasiIrFixture("Rasi-500");auto c=compileRasiTranslation(m);REQUIRE(c.hasElongationKernel());REQUIRE(c.elongationKernel().sourceRuleCount()>100); }
CONTRACT_CASE("coordinate family preserves source rule mapping for every position") { auto m=loadRasiIrFixture("Rasi-500");auto c=compileRasiTranslation(m);for(auto&p:c.elongationKernel().coordinates())REQUIRE(c.elongationKernel().sourceRuleFor(p).valid()); }
CONTRACT_CASE("collision rules are not incorrectly merged with elongation rules") { auto m=loadRasiIrFixture("Rasi-500");auto c=compileRasiTranslation(m);REQUIRE_NE(c.familyOf("collision_10"),c.familyOf("elongation_10")); }
CONTRACT_CASE("pretermination rules remain distinct when predicate structure differs") { auto m=loadRasiIrFixture("Rasi-500");auto c=compileRasiTranslation(m);REQUIRE(!c.familySemanticEqual("preterm_10","elongation_10")); }
CONTRACT_CASE("endocleavage rules remain distinct when topology differs") { auto m=loadRasiIrFixture("Rasi-500");auto c=compileRasiTranslation(m);REQUIRE(!c.familySemanticEqual("endocleave_10","elongation_10")); }

CONTRACT_CASE("ribosome footprint exclusion prevents physically overlapping positions") { auto s=makeRasiLatticeFixture(500,10);REQUIRE(s.placeRibosome(100));for(Position p=91;p<=109;++p)REQUIRE(!s.canPlaceRibosome(p)); }
CONTRACT_CASE("elongation becomes eligible immediately when blocking ribosome moves away") { auto s=makeRasiLatticeFixture(500,10);s.placeRibosome(100);s.placeRibosome(110);REQUIRE(!s.canElongate(100));REQUIRE(s.canElongate(110));s.elongate(110);REQUIRE(s.canElongate(100)); }
CONTRACT_CASE("collision predicate activates only at exact spacing required by model") { auto s=makeRasiCollisionFixture();for(int d=1;d<30;++d){s.reset();s.placePair(100,100+d);REQUIRE_EQ(s.collisionEligible(100),d==s.collisionSpacing());} }
CONTRACT_CASE("stateSet translational gate accepts each declared state and rejects others") { auto s=makeRasiStateSetFixture({1,4,7});for(int q=0;q<10;++q){s.setLocalState(q);REQUIRE_EQ(s.ruleEligible(),q==1||q==4||q==7);} }

CONTRACT_CASE("transcript birth creates sparse transcript without genome-sized allocation") { auto s=makeWholeGenomeRasiFixture();auto before=s.memoryBytes();auto t=s.transcribe(1'000'000,1'010'000);REQUIRE(t.valid());REQUIRE(s.memoryBytes()-before<1'000'000u); }
CONTRACT_CASE("transcript deletion removes attached runtime state without touching unrelated transcripts") { auto s=makeWholeGenomeRasiFixture();auto a=s.transcribe(100,1000),b=s.transcribe(2000,3000);auto before=s.transcriptFingerprint(b);s.destroyTranscript(a);REQUIRE_EQ(s.transcriptFingerprint(b),before); }
CONTRACT_CASE("multiple transcripts share immutable genome annotation") { auto s=makeWholeGenomeRasiFixture();std::vector<TranscriptId> t;for(int i=0;i<10000;++i)t.push_back(s.transcribe(i*100,i*100+90));auto addr=s.genomeAnnotationAddress();for(auto x:t)REQUIRE_EQ(s.genomeAnnotationAddressFor(x),addr); }

CONTRACT_CASE("initiation depends on local occupancy not total ribosome count") { auto s=makeRasiInitiationFixture();for(int i=0;i<1000;++i)s.placeFarRibosome(1000+i*20);REQUIRE(s.canInitiate());s.placeAtInitiationBlocker();REQUIRE(!s.canInitiate()); }
CONTRACT_CASE("termination removes only terminating ribosome and preserves upstream eligibility") { auto s=makeRasiTerminationFixture();auto upstream=s.placeRibosome(s.end()-30);auto terminal=s.placeRibosome(s.end()-s.footprint());auto before=s.eligibility(upstream);s.terminate(terminal);REQUIRE(s.alive(upstream));REQUIRE(s.eligibility(upstream)>=before); }

CONTRACT_CASE("local mutation candidate filter has no false negatives for collision elongation preterm endocleave") { auto f=makeRasiCandidateOracleFixture();for(int event=0;event<100000;++event){auto mut=f.randomLegalMutation(event);auto exact=f.fullAffectedRules(mut);auto filtered=f.filteredAffectedRules(mut);for(auto r:exact)REQUIRE(std::find(filtered.begin(),filtered.end(),r)!=filtered.end());f.apply(mut);} }
CONTRACT_CASE("candidate filter false positives are allowed but bounded") { auto f=makeRasiCandidateOracleFixture();std::uint64_t exact=0,cand=0;for(int event=0;event<10000;++event){auto mut=f.randomLegalMutation(event);exact+=f.fullAffectedRules(mut).size();cand+=f.filteredAffectedRules(mut).size();f.apply(mut);}REQUIRE(cand<exact*20+10000); }

CONTRACT_CASE("Rasi-500 seed 424242 sim4 exact hash gate") { auto r=runRasiNext("Rasi-500",424242,4.0);REQUIRE_EQ(r.events,3489u);REQUIRE_EQ(r.output_sha256,"a1e661a995a80f5ec65267d0c907d637e30f137d6dad4eb47dcf959717921011"); }
CONTRACT_CASE("Rasi short seeds preserve previously validated reaction counts") { REQUIRE_EQ(runRasiNext("Rasi-500",1,2.0).events,336u);REQUIRE_EQ(runRasiNext("Rasi-500",42,2.0).events,512u);REQUIRE_EQ(runRasiNext("Rasi-500",2026,2.0).events,766u); }
CONTRACT_CASE("uORF sim30 preserves 1244-event gate") { REQUIRE_EQ(runRasiNext("uORF",424242,30.0).events,1244u); }
CONTRACT_CASE("uORF sim200 preserves 15415-event gate") { REQUIRE_EQ(runRasiNext("uORF",424242,200.0).events,15415u); }

CONTRACT_CASE("family-collapsed and expanded reference Rasi traces map to same source rules") { auto a=runRasiExpandedTrace("Rasi-500",77,10000),b=runRasiCollapsedTrace("Rasi-500",77,10000);REQUIRE_EQ(a.source_rule_ids,b.source_rule_ids);REQUIRE_EQ(a.state_hashes,b.state_hashes); }
CONTRACT_CASE("Rasi lattice never emits null event") { auto r=runRasiNext("Rasi-500",42,100000,RunLimitKind::Events);REQUIRE_EQ(r.null_events,0u); }
CONTRACT_CASE("whole-genome proxy runtime representation remains family-scale") { auto c=compileRasiTranslation(loadRasiIrFixture("whole-genome-proxy"));REQUIRE(c.runtimeRuleObjects()<10000u);REQUIRE(c.expandedInputRules()>100000u); }
CONTRACT_CASE("whole-genome proxy sparse genome has no object per empty coordinate") { auto s=makeWholeGenomeRasiFixture();REQUIRE(s.materializedGenomeCoordinates()<s.genomeLength()/1000); }
CONTRACT_CASE("Rasi compiled model can be shared across 1000 trajectories") { auto m=compileRasiTranslation(loadRasiIrFixture("Rasi-500"));auto t=makeRasiTrajectories(m,1000);for(auto&x:t)REQUIRE_EQ(x.compiledModelAddress(),t[0].compiledModelAddress()); }
CONTRACT_CASE("Rasi trajectory hashes are independent of worker count") { auto a=runRasiBatch("Rasi-500",100,1),b=runRasiBatch("Rasi-500",100,16);REQUIRE_EQ(a.trace_hashes,b.trace_hashes); }

CONTRACT_MAIN("rasi-translation")
#else
#error "RED CONTRACT: implement Rasi semantic compiler/lattice integration and real-fixture gates"
#endif
