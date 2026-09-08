#include "contract_test.hpp"

#if __has_include("nfnext/backend_equivalence.hpp")
#include "nfnext/backend_equivalence.hpp"
#include <random>
using namespace nfnext;

CONTRACT_CASE("reference and generic backends agree on simple state cycle") { auto f=makeBackendFixture("state_cycle"); REQUIRE(runEquivalent(f,BackendKind::Reference,BackendKind::Generic,10000,42)); }
CONTRACT_CASE("reference and generic backends agree on bimolecular binding") { auto f=makeBackendFixture("simple_bind"); REQUIRE(runEquivalent(f,BackendKind::Reference,BackendKind::Generic,10000,42)); }
CONTRACT_CASE("reference and generic backends agree on symmetric sites") { auto f=makeBackendFixture("symmetric_sites"); REQUIRE(runEquivalent(f,BackendKind::Reference,BackendKind::Generic,10000,42)); }
CONTRACT_CASE("reference and lattice backends agree on unit-footprint translation") { auto f=makeBackendFixture("translation_unit_footprint"); REQUIRE(runEquivalent(f,BackendKind::Reference,BackendKind::Lattice,100000,42)); }
CONTRACT_CASE("reference and lattice backends agree on footprint exclusion") { auto f=makeBackendFixture("translation_footprint_10"); REQUIRE(runEquivalent(f,BackendKind::Reference,BackendKind::Lattice,100000,42)); }
CONTRACT_CASE("reference and population backends agree on unstructured unary chemistry") { auto f=makeBackendFixture("population_unary"); REQUIRE(runEquivalent(f,BackendKind::Reference,BackendKind::Population,10000,42)); }
CONTRACT_CASE("reference and hybrid backends agree on catalyst plus population substrate") { auto f=makeBackendFixture("hybrid_catalysis"); REQUIRE(runEquivalent(f,BackendKind::Reference,BackendKind::Hybrid,10000,42)); }

CONTRACT_CASE("backend auto-selection never chooses backend that compiler says is incompatible") {
    for(auto name:allCompatibilityFixtures()){auto f=makeBackendFixture(name);auto c=compileModel(f.model);REQUIRE(c.compatibility.supports(c.selected_backend));}
}
CONTRACT_CASE("models with arbitrary graph topology do not auto-select lattice") { auto f=makeBackendFixture("branched_polymer"); REQUIRE_NE(compileModel(f.model).selected_backend,BackendKind::Lattice); }
CONTRACT_CASE("models with siteful population type do not auto-select pure population") { auto f=makeBackendFixture("siteful_species"); REQUIRE_NE(compileModel(f.model).selected_backend,BackendKind::Population); }
CONTRACT_CASE("mixed lattice and generic model selects hybrid dispatcher") { auto f=makeBackendFixture("translation_plus_signaling"); REQUIRE_EQ(compileModel(f.model).selected_backend,BackendKind::Hybrid); }

CONTRACT_CASE("forcing unsupported backend rejects before simulation") { auto f=makeBackendFixture("branched_polymer"); CompileOptions o;o.force_backend=BackendKind::Lattice;REQUIRE_THROWS_AS(compileModel(f.model,o),BackendIncompatible); }
CONTRACT_CASE("forcing reference backend is always legal for supported semantic subset") { for(auto name:allSupportedSemanticFixtures()){auto f=makeBackendFixture(name);CompileOptions o;o.force_backend=BackendKind::Reference;REQUIRE_NO_THROW(compileModel(f.model,o));} }

CONTRACT_CASE("backend equivalence compares semantic event identity not internal channel IDs") { auto f=makeBackendFixture("collapsed_elongation_500"); auto a=runTrace(f,BackendKind::Reference,5000,1);auto b=runTrace(f,BackendKind::Lattice,5000,1);REQUIRE_EQ(a.semanticRuleIds,b.semanticRuleIds); }
CONTRACT_CASE("backend equivalence compares canonical state not storage layout") { auto f=makeBackendFixture("population_unary");auto a=runTrace(f,BackendKind::Reference,100,1);auto b=runTrace(f,BackendKind::Population,100,1);REQUIRE_EQ(a.finalCanonicalState,b.finalCanonicalState); }
CONTRACT_CASE("backend equivalence compares observables after every event") { auto f=makeBackendFixture("observable_rate");auto a=runTrace(f,BackendKind::Reference,1000,1),b=runTrace(f,BackendKind::Generic,1000,1);REQUIRE_EQ(a.observableRows,b.observableRows); }
CONTRACT_CASE("backend equivalence compares total propensity before every event") { auto f=makeBackendFixture("simple_bind");auto a=runTrace(f,BackendKind::Reference,1000,1),b=runTrace(f,BackendKind::Generic,1000,1);REQUIRE_EQ(a.totalPropensityBits,b.totalPropensityBits); }

CONTRACT_CASE("all exact backends consume same semantic RNG layout") { for(auto b:{BackendKind::Reference,BackendKind::Generic,BackendKind::Lattice,BackendKind::Population,BackendKind::Hybrid}) REQUIRE_EQ(rngLayoutFor(b),RngLayout::exactSSA()); }
CONTRACT_CASE("backend fallback at runtime cannot restart trajectory with different RNG stream") { auto f=makeBackendFallbackFixture();auto r=runWithFallback(f,42,7);auto ref=runReference(f,42,7);REQUIRE_EQ(r.traceHash,ref.traceHash); }

CONTRACT_CASE("random small lattice-compatible models agree reference versus lattice") {
    std::mt19937_64 rng(123);for(int trial=0;trial<500;++trial){auto f=randomTranslationFixture(rng,5+rng()%100,1+rng()%10);REQUIRE(runEquivalent(f,BackendKind::Reference,BackendKind::Lattice,500,trial));}
}
CONTRACT_CASE("random unstructured population models agree reference versus population") {
    std::mt19937_64 rng(456);for(int trial=0;trial<500;++trial){auto f=randomPopulationFixture(rng,1+rng()%8,1+rng()%20);REQUIRE(runEquivalent(f,BackendKind::Reference,BackendKind::Population,500,trial));}
}
CONTRACT_CASE("random generic graph models agree reference versus compiled matcher") {
    std::mt19937_64 rng(789);for(int trial=0;trial<200;++trial){auto f=randomGenericFixture(rng,1+rng()%5,1+rng()%8);REQUIRE(runEquivalent(f,BackendKind::Reference,BackendKind::Generic,200,trial));}
}

CONTRACT_MAIN("backend-equivalence")
#else
#error "RED CONTRACT: implement backend dispatcher and semantic equivalence harness"
#endif
