#include "contract_test.hpp"

#if __has_include("nfnext/differential.hpp")
#include "nfnext/differential.hpp"
#include <fstream>
using namespace nfnext;

CONTRACT_CASE("differential runner compares event family before applying event") { auto f=makeDifferentialFixture("simple_bind"); auto r=DifferentialRunner(f).step(); REQUIRE(r.pre_state_equal); REQUIRE(r.selected_semantic_rule_equal); }
CONTRACT_CASE("differential runner compares waiting time bits when RNG contract is shared") { auto f=makeDifferentialFixture("simple_bind"); auto r=DifferentialRunner(f).step(); REQUIRE_EQ(r.legacy_wait_bits,r.next_wait_bits); }
CONTRACT_CASE("differential runner compares post-state canonical fingerprints") { auto f=makeDifferentialFixture("simple_bind"); auto r=DifferentialRunner(f).step(); REQUIRE_EQ(r.legacy_post_state,r.next_post_state); }
CONTRACT_CASE("differential runner compares observables after every event") { auto f=makeDifferentialFixture("observable_rate"); auto rr=DifferentialRunner(f).run(100); for(auto&s:rr.steps) REQUIRE_EQ(s.legacy_observables,s.next_observables); }
CONTRACT_CASE("differential runner stops at first divergence and preserves diagnostic context") { auto f=makeInjectedMismatchFixture(17); auto r=DifferentialRunner(f).run(100); REQUIRE(!r.equal); REQUIRE_EQ(r.first_mismatch_event,17u); REQUIRE(!r.diagnostic.legacy_state.empty()); REQUIRE(!r.diagnostic.next_state.empty()); }
CONTRACT_CASE("differential mismatch reports candidate counts and propensities") { auto f=makeInjectedMismatchFixture(3); auto r=DifferentialRunner(f).run(10); REQUIRE(r.diagnostic.legacy_total_propensity>=0); REQUIRE(r.diagnostic.next_total_propensity>=0); REQUIRE(!r.diagnostic.family_rows.empty()); }
CONTRACT_CASE("differential mismatch reports source rule and XML location") { auto f=makeInjectedMismatchFixture(3); auto r=DifferentialRunner(f).run(10); REQUIRE(r.diagnostic.source_rule.size()>0); REQUIRE(r.diagnostic.source_line>0); }

CONTRACT_CASE("semantic comparison can ignore internal family collapse representation") { auto f=makeDifferentialFixture("collapsed_elongation_500"); auto r=DifferentialRunner(f).run(1000); REQUIRE(r.equal); }
CONTRACT_CASE("semantic comparison can map one family channel back to original expanded rule ID") { auto f=makeDifferentialFixture("collapsed_elongation_500"); auto step=DifferentialRunner(f).step(); REQUIRE_EQ(step.legacy_expanded_rule_id,step.next_source_rule_id); }

CONTRACT_CASE("small binding fixture is exact for 100 seeds") { for(std::uint64_t seed=0;seed<100;++seed){auto f=makeDifferentialFixture("simple_bind",seed);REQUIRE(DifferentialRunner(f).run(1000).equal);} }
CONTRACT_CASE("state-change fixture is exact for 100 seeds") { for(std::uint64_t seed=0;seed<100;++seed){auto f=makeDifferentialFixture("state_cycle",seed);REQUIRE(DifferentialRunner(f).run(1000).equal);} }
CONTRACT_CASE("polymer fixture is exact across deletion and slot reuse") { for(std::uint64_t seed=0;seed<50;++seed){auto f=makeDifferentialFixture("polymer_delete_reuse",seed);REQUIRE(DifferentialRunner(f).run(5000).equal);} }
CONTRACT_CASE("symmetric-site fixture is exact") { for(std::uint64_t seed=0;seed<100;++seed) REQUIRE(DifferentialRunner(makeDifferentialFixture("symmetric_sites",seed)).run(2000).equal); }
CONTRACT_CASE("species observable fixture is exact") { for(std::uint64_t seed=0;seed<20;++seed) REQUIRE(DifferentialRunner(makeDifferentialFixture("species_observable",seed)).run(2000).equal); }
CONTRACT_CASE("observable-dependent rate fixture is exact") { for(std::uint64_t seed=0;seed<20;++seed) REQUIRE(DifferentialRunner(makeDifferentialFixture("observable_rate",seed)).run(2000).equal); }
CONTRACT_CASE("time-varying rate fixture is exact") { for(std::uint64_t seed=0;seed<20;++seed) REQUIRE(DifferentialRunner(makeDifferentialFixture("time_rate",seed)).run(2000).equal); }

CONTRACT_CASE("Rasi-500 gate seed 424242 sim4 retains known reaction count") { auto f=loadRasiDifferentialFixture("Rasi-500",424242,4.0); auto r=DifferentialRunner(f).runToTime(4.0); REQUIRE(r.equal); REQUIRE_EQ(r.legacy_events,3489u); REQUIRE_EQ(r.next_events,3489u); }
CONTRACT_CASE("Rasi-500 legacy output hash remains known oracle") { auto f=loadRasiDifferentialFixture("Rasi-500",424242,4.0); auto r=DifferentialRunner(f).runToTime(4.0); REQUIRE_EQ(r.legacy_output_sha256,"a1e661a995a80f5ec65267d0c907d637e30f137d6dad4eb47dcf959717921011"); REQUIRE_EQ(r.next_output_sha256,r.legacy_output_sha256); }
CONTRACT_CASE("uORF short gate is event-exact") { auto f=loadRasiDifferentialFixture("uORF",424242,30.0); auto r=DifferentialRunner(f).runToTime(30.0); REQUIRE(r.equal); REQUIRE_EQ(r.legacy_events,1244u); }
CONTRACT_CASE("uORF long gate is event-exact") { auto f=loadRasiDifferentialFixture("uORF",424242,200.0); auto r=DifferentialRunner(f).runToTime(200.0); REQUIRE(r.equal); REQUIRE_EQ(r.legacy_events,15415u); }

CONTRACT_CASE("differential runner supports compare-at-checkpoints for engines with different internal event metadata") { auto f=makeDifferentialFixture("generic"); DifferentialOptions o; o.compare_every=10; o.require_internal_candidate_identity=false; auto r=DifferentialRunner(f,o).run(1000); REQUIRE(r.equal); }
CONTRACT_CASE("differential runner can emit minimal reproducer XML on mismatch") { auto f=makeInjectedMismatchFixture(10); DifferentialOptions o;o.minimize_on_failure=true; auto r=DifferentialRunner(f,o).run(100); REQUIRE(!r.equal); REQUIRE(r.minimized_reproducer_xml.size()>0); }
CONTRACT_CASE("minimized reproducer still exhibits same mismatch class") { auto f=makeInjectedMismatchFixture(10); DifferentialOptions o;o.minimize_on_failure=true; auto r=DifferentialRunner(f,o).run(100); auto again=DifferentialRunner::fromXml(r.minimized_reproducer_xml).run(100); REQUIRE_EQ(again.diagnostic.kind,r.diagnostic.kind); }

CONTRACT_MAIN("differential-oracle")
#else
#error "RED CONTRACT: implement legacy-vs-NFnext differential oracle runner"
#endif
