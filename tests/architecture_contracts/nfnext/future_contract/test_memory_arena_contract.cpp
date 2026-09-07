#include "contract_test.hpp"

#if __has_include("nfnext/arena_v2.hpp") && __has_include("nfnext/allocation_probe.hpp")
#include "nfnext/arena_v2.hpp"
#include "nfnext/allocation_probe.hpp"
#include <set>
using namespace nfnext;

CONTRACT_CASE("new particle ID is valid and alive") { ParticleArenaV2 a;auto p=a.create(3);REQUIRE(p.valid());REQUIRE(a.alive(p));REQUIRE_EQ(a.type(p),3u); }
CONTRACT_CASE("destroyed ID becomes stale immediately") { ParticleArenaV2 a;auto p=a.create(3);a.destroy(p);REQUIRE(!a.alive(p));REQUIRE_THROWS_AS(a.type(p),StaleParticleId); }
CONTRACT_CASE("slot reuse increments generation") { ParticleArenaV2 a;auto p=a.create(3);a.destroy(p);auto q=a.create(4);REQUIRE_EQ(p.index,q.index);REQUIRE_NE(p.generation,q.generation); }
CONTRACT_CASE("generation wrap is detected and slot retired rather than resurrecting ancient ID") { ParticleArenaV2 a;auto p=a.create(0);forceGenerationForTest(a,p.index,std::numeric_limits<std::uint32_t>::max());auto old=ParticleId{p.index,std::numeric_limits<std::uint32_t>::max()};a.destroy(old);auto q=a.create(0);REQUIRE_NE(q.index,old.index); }
CONTRACT_CASE("double destroy rejects") { ParticleArenaV2 a;auto p=a.create(0);a.destroy(p);REQUIRE_THROWS_AS(a.destroy(p),StaleParticleId); }

CONTRACT_CASE("SoA fields are contiguous by field") { ParticleArenaV2 a;for(int i=0;i<1000;++i)a.create(i%4);REQUIRE(a.layout().types_contiguous);REQUIRE(a.layout().generations_contiguous);REQUIRE(a.layout().states_contiguous); }
CONTRACT_CASE("hot type array contains no pointers") { ParticleArenaV2 a;for(int i=0;i<100;++i)a.create(0);REQUIRE_EQ(a.layout().type_element_bytes,sizeof(TypeId)); }
CONTRACT_CASE("bond storage uses compact particle IDs not raw pointers") { GenericArenaSchema s=makeBondedArenaSchema();GenericArenaV2 a(s);REQUIRE_EQ(a.layout().bond_partner_element_bytes,sizeof(ParticleId)); }
CONTRACT_CASE("site-state stride is compiler-known and direct-indexable") { GenericArenaSchema s=makeBondedArenaSchema();GenericArenaV2 a(s);REQUIRE_EQ(a.siteOffset(10,2),10*a.stride()+2); }

CONTRACT_CASE("steady-state state-change event performs zero heap allocations") { auto sim=makeAllocationProbeFixture("state_change");sim.warmup(100);AllocationProbe p;sim.run(100000);REQUIRE_EQ(p.allocations(),0u); }
CONTRACT_CASE("steady-state bind-unbind event performs zero heap allocations") { auto sim=makeAllocationProbeFixture("bind_unbind");sim.warmup(100);AllocationProbe p;sim.run(100000);REQUIRE_EQ(p.allocations(),0u); }
CONTRACT_CASE("steady-state lattice hop performs zero heap allocations") { auto sim=makeAllocationProbeFixture("lattice");sim.warmup(100);AllocationProbe p;sim.run(100000);REQUIRE_EQ(p.allocations(),0u); }
CONTRACT_CASE("steady-state population event performs zero heap allocations") { auto sim=makeAllocationProbeFixture("population");sim.warmup(100);AllocationProbe p;sim.run(100000);REQUIRE_EQ(p.allocations(),0u); }

CONTRACT_CASE("create-destroy churn reuses capacity instead of unbounded growth") { ParticleArenaV2 a;for(int cycle=0;cycle<10000;++cycle){std::vector<ParticleId> p;for(int i=0;i<1000;++i)p.push_back(a.create(0));for(auto x:p)a.destroy(x);}REQUIRE(a.capacity()<=1000u); }
CONTRACT_CASE("generic graph create-destroy churn clears all stale site data") { auto s=makeBondedArenaSchema();GenericArenaV2 a(s);for(int cycle=0;cycle<1000;++cycle){auto p=a.create(0);a.setState(p,0,7);a.destroy(p);auto q=a.create(0);REQUIRE_EQ(a.state(q,0),s.defaultState(0,0));a.destroy(q);} }
CONTRACT_CASE("bonded particle destroy clears reverse endpoint without scanning all particles") { auto s=makeBondedArenaSchema();GenericArenaV2 a(s);std::vector<ParticleId> p;for(int i=0;i<100000;++i)p.push_back(a.create(0));a.bind(p[123],0,p[99999],0);auto before=a.bondRepairVisits();a.destroy(p[123]);REQUIRE(a.bondRepairVisits()-before<8u);REQUIRE(!a.bound(p[99999],0)); }

CONTRACT_CASE("arena reserves exact requested capacity without initializing semantic particles") { ParticleArenaV2 a;a.reserve(1'000'000);REQUIRE(a.capacityReserved()>=1'000'000u);REQUIRE_EQ(a.liveCount(),0u); }
CONTRACT_CASE("memory usage scales linearly with live/capacity particles not rule count") { auto a=makeArenaMemoryFixture(100000,100);auto b=makeArenaMemoryFixture(100000,100000);REQUIRE_NEAR(static_cast<double>(a.memoryBytes()),static_cast<double>(b.memoryBytes()),a.memoryBytes()*0.05); }
CONTRACT_CASE("per-particle storage target remains bounded") { auto a=makeArenaMemoryFixture(1'000'000,100);REQUIRE(a.bytesPerParticleCapacity()<128.0); }

CONTRACT_CASE("free-list integrity survives randomized churn") { ParticleArenaV2 a;std::vector<ParticleId> live;std::mt19937_64 rng(4);for(int step=0;step<1000000;++step){if(live.empty()||(rng()&1)){live.push_back(a.create(rng()%8));}else{auto i=rng()%live.size();a.destroy(live[i]);live[i]=live.back();live.pop_back();}REQUIRE_EQ(a.liveCount(),live.size());}REQUIRE(a.validateInternal()); }
CONTRACT_CASE("no two simultaneously live particles share same ID") { ParticleArenaV2 a;std::set<std::pair<uint32_t,uint32_t>> ids;for(int i=0;i<100000;++i){auto p=a.create(0);REQUIRE(ids.insert({p.index,p.generation}).second);} }

CONTRACT_MAIN("memory-arena")
#else
#error "RED CONTRACT: implement production generational SoA arena and allocation probes"
#endif
