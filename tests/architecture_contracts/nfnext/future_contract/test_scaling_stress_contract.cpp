#include "contract_test.hpp"

#if __has_include("nfnext/scaling_probe.hpp")
#include "nfnext/scaling_probe.hpp"
#include <cmath>
using namespace nfnext;

CONTRACT_CASE("indexed-rule family storage is sublinear in expanded rule count") {
    auto a=measureCompile(makeTranslationModel(1'000));auto b=measureCompile(makeTranslationModel(1'000'000));REQUIRE(b.runtime_rule_objects<=a.runtime_rule_objects+8);REQUIRE(b.compiled_families<=a.compiled_families+2);
}
CONTRACT_CASE("million-rule translation model collapses to small family count") { auto r=measureCompile(makeTranslationModel(1'000'000));REQUIRE(r.compiled_families<100u);REQUIRE_EQ(r.expanded_rules,1'000'000u); }
CONTRACT_CASE("runtime memory does not scale with expanded positional rules after compilation") { auto a=measureRuntimeMemory(makeTranslationModel(10'000));auto b=measureRuntimeMemory(makeTranslationModel(1'000'000));REQUIRE(b.bytes < a.bytes*4 + 20'000'000); }
CONTRACT_CASE("empty-billion-coordinate genome does not allocate billion slots") { auto r=measureRuntimeMemory(makeSparseGenomeModel(1'000'000'000ull,0));REQUIRE(r.bytes<10'000'000u); }
CONTRACT_CASE("sparse genome memory scales with occupied features") { auto a=measureRuntimeMemory(makeSparseGenomeModel(1'000'000'000ull,1000));auto b=measureRuntimeMemory(makeSparseGenomeModel(1'000'000'000ull,2000));REQUIRE(b.bytes<2.5*a.bytes); }

CONTRACT_CASE("local event dependency visits stay bounded as rule count grows") { for(std::size_t n:{1000u,10000u,100000u,1000000u}){auto sim=makeTranslationSimulation(n,100);auto stats=sim.runAndProfile(10000);REQUIRE(stats.median_dependency_visits<64);REQUIRE(stats.p99_dependency_visits<256);} }
CONTRACT_CASE("local lattice propensity repair stays bounded as genome grows") { for(std::uint64_t n:{1000ull,1000000ull,1000000000ull}){auto sim=makeSparseTranslationSimulation(n,100);auto stats=sim.runAndProfile(10000);REQUIRE(stats.max_local_repair<=64u);} }
CONTRACT_CASE("generic local state mutation does not scan unrelated molecule types") { auto sim=makeManyTypeGenericModel(10000,10);auto stats=sim.mutateOneStateAndProfile();REQUIRE(stats.types_visited<5u); }
CONTRACT_CASE("observable incremental update does not scan ten thousand unrelated observables") { auto sim=makeManyObservableModel(10000);auto stats=sim.mutateOneStateAndProfile();REQUIRE(stats.observables_visited<64u); }

CONTRACT_CASE("compiled-model sharing makes N trajectories nearly state-memory linear") { auto model=compileLargeTranslationModel();auto one=measureBatchMemory(model,1);auto hundred=measureBatchMemory(model,100);REQUIRE(hundred.bytes < one.compiled_model_bytes*1.2 + 100*one.per_trajectory_bytes*1.2); }
CONTRACT_CASE("compiled model is physically shared across trajectories") { auto model=compileLargeTranslationModel();auto batch=createTrajectoryStates(model,1000);for(auto&s:batch)REQUIRE_EQ(s.compiledModelAddress(),batch[0].compiledModelAddress()); }

CONTRACT_CASE("startup cache hit skips XML parsing and family compilation") { auto f=makeCacheStartupFixture();f.coldCompile();auto s=f.warmStartProfile();REQUIRE_EQ(s.xml_nodes_parsed,0u);REQUIRE_EQ(s.family_rules_analyzed,0u);REQUIRE(s.cache_hit); }
CONTRACT_CASE("cache miss performs full semantic validation") { auto f=makeCacheStartupFixture();f.deleteCache();auto s=f.warmStartProfile();REQUIRE(!s.cache_hit);REQUIRE(s.validation_checks>0); }

CONTRACT_CASE("trajectory throughput scales across independent CPU cores") { auto f=makeCpuScalingFixture();auto one=f.run(1);auto eight=f.run(8);REQUIRE(eight.events_per_second>one.events_per_second*4.0); }
CONTRACT_CASE("parallel trajectories retain exact per-trajectory hashes") { auto f=makeCpuScalingFixture();auto one=f.runHashes(1),eight=f.runHashes(8);REQUIRE_EQ(one,eight); }

CONTRACT_CASE("event loop latency distribution has no periodic O(rule_count) spikes") { auto sim=makeTranslationSimulation(1'000'000,1000);auto lat=sim.eventLatencies(100000);REQUIRE(lat.p999 < lat.median*100); }
CONTRACT_CASE("scheduler update complexity grows logarithmically not linearly") { auto a=measureSchedulerUpdate(1024),b=measureSchedulerUpdate(1<<20);REQUIRE(b.operations < a.operations*4); }
CONTRACT_CASE("family selection complexity grows logarithmically") { auto a=measureSchedulerSample(1024),b=measureSchedulerSample(1<<20);REQUIRE(b.operations<a.operations*4); }

CONTRACT_CASE("Rasi-shaped 9401-rule synthetic model compiles to one elongation family") { auto r=measureCompile(makeRasiShapedSynthetic(9401));REQUIRE_EQ(r.elongation_families,1u);REQUIRE_EQ(r.collapsed_rules,9401u); }
CONTRACT_CASE("Rasi-shaped million-rule proxy remains compilable within bounded memory") { auto r=measureCompile(makeRasiShapedSynthetic(1'000'000));REQUIRE(r.peak_bytes<1'000'000'000ull);REQUIRE(r.compiled_families<1000u); }

CONTRACT_CASE("stress run produces no null events for local lattice kernel") { auto sim=makeTranslationSimulation(1'000'000,10000);auto r=sim.run(10'000'000);REQUIRE_EQ(r.null_events,0u); }
CONTRACT_CASE("stress create/delete run leaves arena internally valid") { auto sim=makeCreateDeleteStressFixture();sim.run(10'000'000);REQUIRE(sim.state().validateInternal()); }

CONTRACT_MAIN("scaling-stress")
#else
#error "RED CONTRACT: implement scaling instrumentation and satisfy asymptotic architecture targets"
#endif
