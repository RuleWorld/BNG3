#include "contract_test.hpp"

#if __has_include("nfnext/replay.hpp") && __has_include("nfnext/trajectory_batch.hpp")
#include "nfnext/replay.hpp"
#include "nfnext/trajectory_batch.hpp"
#include "nfnext/counter_rng.hpp"
#include <set>
#include <thread>
using namespace nfnext;

CONTRACT_CASE("counter RNG is pure function of seed stream and counter") {
    CounterRng a(42,7),b(42,7); for(std::uint64_t i=0;i<100000;++i) REQUIRE_EQ(a.u64(i),b.u64(i));
}
CONTRACT_CASE("different trajectory streams diverge immediately") { CounterRng a(42,0),b(42,1); REQUIRE_NE(a.u64(0),b.u64(0)); }
CONTRACT_CASE("random access counter generation does not depend on request order") { CounterRng r(99,3); auto x=r.u64(1000); (void)r.u64(2);(void)r.u64(999999); REQUIRE_EQ(r.u64(1000),x); }
CONTRACT_CASE("uniformOpen01 never produces endpoints") { CounterRng r(1,2); for(std::uint64_t i=0;i<1000000;++i){auto x=r.uniformOpen01(i);REQUIRE(x>0);REQUIRE(x<1);} }
CONTRACT_CASE("exponential zero rate is infinity and consumes no hidden state") { CounterRng r(1,2); auto before=r.u64(100); REQUIRE(std::isinf(r.exponential(100,0))); REQUIRE_EQ(r.u64(100),before); }
CONTRACT_CASE("negative exponential rate is rejected by strict API") { StrictCounterRng r(1,2); REQUIRE_THROWS_AS(r.exponential(0,-1),RngDomainError); }

CONTRACT_CASE("event RNG allocation is fixed-width per attempted event") {
    RngLayout l=RngLayout::exactSSA(); REQUIRE_EQ(l.wordsPerEvent(),4u); REQUIRE_EQ(l.word(RngPurpose::WaitingTime,17),68u); REQUIRE_EQ(l.word(RngPurpose::FamilyChoice,17),69u);
}
CONTRACT_CASE("backend-specific optimizations cannot consume extra semantic RNG words") { auto l=RngLayout::exactSSA(); REQUIRE(!l.allowBackendDependentConsumption()); }

CONTRACT_CASE("serial and parallel trajectory batches are bit-identical") {
    auto req=makeDeterministicBatchFixture(12345,2000); auto a=TrajectoryBatch::run(req,64,1); auto b=TrajectoryBatch::run(req,64,8); REQUIRE_EQ(a.size(),b.size()); for(std::size_t i=0;i<a.size();++i){REQUIRE_EQ(a[i].traceHash,b[i].traceHash);REQUIRE_EQ(a[i].stateHash,b[i].stateHash);REQUIRE_EQ(a[i].finalTimeBits,b[i].finalTimeBits);}
}
CONTRACT_CASE("parallel result ordering is trajectory ID order not completion order") { auto req=makeVariableRuntimeBatchFixture(); auto r=TrajectoryBatch::run(req,100,16); for(std::size_t i=0;i<r.size();++i) REQUIRE_EQ(r[i].trajectory_id,i); }
CONTRACT_CASE("thread count zero resolves to valid implementation-defined worker count") { auto req=makeDeterministicBatchFixture(1,10); REQUIRE_NO_THROW(TrajectoryBatch::run(req,4,0)); }
CONTRACT_CASE("one trajectory never runs twice under work stealing") { auto req=makeVariableRuntimeBatchFixture(); auto r=TrajectoryBatch::run(req,10000,64); std::set<std::uint64_t> ids; for(auto&x:r)ids.insert(x.trajectory_id); REQUIRE_EQ(ids.size(),10000u); }

CONTRACT_CASE("compiled model is immutable under concurrent trajectory access") { auto m=makeSharedCompiledFixture(); auto before=m->fingerprint(); runConcurrentReadStress(m,64,100000); REQUIRE_EQ(m->fingerprint(),before); }
CONTRACT_CASE("trajectory state does not alias mutable particle arrays across trajectories") { auto m=makeSharedCompiledFixture(); TrajectoryState a(m),b(m); a.createParticle(0); REQUIRE_EQ(a.particleCount(),1u); REQUIRE_EQ(b.particleCount(),0u); }

CONTRACT_CASE("trace recorder stores exact selected family channel and RNG counters") { auto sim=makeReplayFixture(7,3); auto t=sim.runWithTrace(100); REQUIRE_EQ(t.events.size(),100u); for(std::size_t i=0;i<t.events.size();++i){REQUIRE_EQ(t.events[i].event_index,i);REQUIRE(t.events[i].rng.wait_counter.valid());REQUIRE(t.events[i].rng.choice_counter.valid());}
}
CONTRACT_CASE("replay from trace reproduces state after every event") { auto sim=makeReplayFixture(7,3); auto t=sim.runWithTrace(500); auto replay=ReplayEngine(sim.compiledModel(),sim.initialState()); for(auto&e:t.events){replay.apply(e);REQUIRE_EQ(replay.stateFingerprint(),e.post_state_fingerprint);} }
CONTRACT_CASE("replay rejects trace event incompatible with pre-state") { auto sim=makeReplayFixture(7,3); auto t=sim.runWithTrace(10); t.events[5].pre_state_fingerprint^=1; REQUIRE_THROWS_AS(ReplayEngine(sim.compiledModel(),sim.initialState()).run(t),ReplayMismatch); }
CONTRACT_CASE("replay can resume from checkpoint at arbitrary event") { auto sim=makeReplayFixture(7,3); auto t=sim.runWithTrace(1000); auto cp=makeCheckpoint(t,400); auto r=ReplayEngine::resume(sim.compiledModel(),cp,t,401); REQUIRE_EQ(r.finalStateFingerprint(),t.final_state_fingerprint); }
CONTRACT_CASE("trace serialization is deterministic") { auto sim=makeReplayFixture(7,3); auto t=sim.runWithTrace(100); REQUIRE_EQ(serializeTrace(t),serializeTrace(t)); }
CONTRACT_CASE("trace corruption is detected by per-block checksum") { auto sim=makeReplayFixture(7,3); auto bytes=serializeTrace(sim.runWithTrace(100)); bytes[bytes.size()/2]^=1; REQUIRE_THROWS_AS(parseTrace(bytes),TraceCorrupt); }

CONTRACT_CASE("checkpoint contains RNG event counter so continuation is exact") { auto sim=makeReplayFixture(42,9); auto full=sim.runWithTrace(1000); auto first=sim.runWithTrace(500); auto resumed=resumeFromCheckpoint(first.checkpoint,500); REQUIRE_EQ(resumed.concatTrace(first).traceHash,full.traceHash); }
CONTRACT_CASE("checkpoint roundtrip preserves generational IDs") { auto s=makeStateWithReusedSlots(); auto bytes=serializeCheckpoint(s); auto x=parseCheckpoint(bytes); REQUIRE_EQ(x.particleIds(),s.particleIds()); }

CONTRACT_CASE("signal-free repeated batch runs have stable hashes") { auto req=makeDeterministicBatchFixture(999,100); auto ref=TrajectoryBatch::run(req,128,8); for(int k=0;k<20;++k) REQUIRE_EQ(batchHashes(TrajectoryBatch::run(req,128,8)),batchHashes(ref)); }
CONTRACT_CASE("adding logging cannot perturb stochastic trajectory") { auto req=makeDeterministicBatchFixture(123,1000); req.logging=false; auto a=TrajectoryBatch::run(req,8,4); req.logging=true; auto b=TrajectoryBatch::run(req,8,4); REQUIRE_EQ(batchHashes(a),batchHashes(b)); }
CONTRACT_CASE("adding profiling cannot perturb stochastic trajectory") { auto req=makeDeterministicBatchFixture(123,1000); req.profiling=false; auto a=TrajectoryBatch::run(req,8,4); req.profiling=true; auto b=TrajectoryBatch::run(req,8,4); REQUIRE_EQ(batchHashes(a),batchHashes(b)); }

CONTRACT_MAIN("rng-replay-concurrency")
#else
#error "RED CONTRACT: implement replay/checkpoints and schedule-independent trajectory batching"
#endif
