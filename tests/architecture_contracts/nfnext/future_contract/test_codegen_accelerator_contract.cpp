#include "contract_test.hpp"

#if __has_include("nfnext/native_codegen.hpp") && __has_include("nfnext/accelerator.hpp")
#include "nfnext/native_codegen.hpp"
#include "nfnext/accelerator.hpp"
using namespace nfnext;

CONTRACT_CASE("native codegen is optional and never required for correctness") { CompileOptions o;o.enable_native_codegen=false;REQUIRE_NO_THROW(compileModel(makeCodegenFixture(),o)); }
CONTRACT_CASE("generated matcher agrees with interpreted compiled matcher") { auto f=makeCodegenFixture();auto i=compileInterpretedMatcher(f.pattern,f.model),n=compileNativeMatcher(f.pattern,f.model);for(auto&s:f.states)REQUIRE_EQ(i.enumerate(s),n.enumerate(s)); }
CONTRACT_CASE("generated transformation agrees with interpreted transformation") { auto f=makeTransformationCodegenFixture();auto i=compileInterpretedTransformation(f.t,f.model),n=compileNativeTransformation(f.t,f.model);for(auto&s:f.states){auto a=s,b=s;i.apply(f.embedding,a);n.apply(f.embedding,b);REQUIRE_EQ(a.canonicalState(),b.canonicalState());} }
CONTRACT_CASE("generated rate function agrees bitwise where strict-FP mode requested") { auto f=makeFunctionCodegenFixture();auto i=compileFunctionVM(f.expr,f.env),n=compileNativeFunction(f.expr,f.env,NativeFpMode::Strict);for(auto&e:f.environments)REQUIRE_EQ(doubleBits(i.evaluate(e)),doubleBits(n.evaluate(e))); }
CONTRACT_CASE("native cache key includes architecture and compiler codegen version") { auto a=makeNativeCacheKey("arm64","v1"),b=makeNativeCacheKey("x86_64","v1"),c=makeNativeCacheKey("arm64","v2");REQUIRE_NE(a.digest(),b.digest());REQUIRE_NE(a.digest(),c.digest()); }
CONTRACT_CASE("native code page is immutable after finalization") { auto c=compileNativeMatcher(makeCodegenFixture().pattern,makeCodegenFixture().model);REQUIRE(c.codeMemoryReadExecuteOnly()); }

CONTRACT_CASE("SIMD candidate filtering agrees lane-for-lane with scalar reference") { auto f=makeSimdCandidateFixture(100000);auto s=scalarFilter(f),v=simdFilter(f);REQUIRE_EQ(s,v); }
CONTRACT_CASE("SIMD stateSet predicate agrees with scalar for all state values") { for(int state=0;state<256;++state){auto f=makeStateSetLaneFixture(state,{1,3,5,8,13,21});REQUIRE_EQ(simdMatch(f),scalarMatch(f));} }
CONTRACT_CASE("SIMD path handles tail lanes without reading past buffers") { for(std::size_t n=1;n<128;++n){auto f=makeSimdCandidateFixture(n);REQUIRE_EQ(simdFilter(f),scalarFilter(f));REQUIRE(!f.guardPageTouched());} }
CONTRACT_CASE("disabling SIMD leaves trajectory trace identical") { auto f=makeSimdSimulationFixture();auto a=runWithSimd(f,false,42),b=runWithSimd(f,true,42);REQUIRE_EQ(a.traceHash,b.traceHash); }

CONTRACT_CASE("accelerator eligibility rejects irregular generic graph rules") { auto m=makeBranchedGenericModel();REQUIRE(!AcceleratorPlanner().eligible(m)); }
CONTRACT_CASE("accelerator eligibility accepts homogeneous batched lattice propensity evaluation") { auto m=makeBatchedLatticeModel();REQUIRE(AcceleratorPlanner().eligible(m)); }
CONTRACT_CASE("GPU is never selected for single tiny trajectory by default") { auto m=makeTinyLatticeModel();AcceleratorContext c;c.trajectories=1;REQUIRE_NE(AcceleratorPlanner().select(m,c),AcceleratorKind::GPU); }
CONTRACT_CASE("GPU batch kernel agrees with CPU scalar on propensity arrays") { auto f=makeGpuLatticeBatchFixture(4096);auto cpu=cpuPropensities(f),gpu=gpuPropensities(f);REQUIRE_EQ(cpu.size(),gpu.size());for(std::size_t i=0;i<cpu.size();++i)REQUIRE_NEAR(cpu[i],gpu[i],0.0); }
CONTRACT_CASE("GPU exact-selection kernel returns same semantic channel for supplied target") { auto f=makeGpuSelectionFixture(10000);for(int i=0;i<10000;++i){double target=(i+.5)/10000.0*f.total;REQUIRE_EQ(cpuSelect(f,target),gpuSelect(f,target));} }
CONTRACT_CASE("GPU kernel cannot own stochastic RNG stream independently") { REQUIRE(!AcceleratorContract::gpuMayGenerateSemanticRng()); }
CONTRACT_CASE("GPU failure falls back before consuming event RNG") { auto f=makeInjectedGpuFailureFixture();auto a=runWithGpuFallback(f,42),b=runCpu(f,42);REQUIRE_EQ(a.traceHash,b.traceHash); }
CONTRACT_CASE("accelerator profiling is excluded from semantic fingerprint") { auto a=makeCompileOptions(),b=a;a.enable_accelerator_profiling=false;b.enable_accelerator_profiling=true;REQUIRE_EQ(semanticCompileKey(a),semanticCompileKey(b)); }
CONTRACT_CASE("accelerator strict-FP requirement is explicit") { AcceleratorOptions o;o.exact_semantics=true;REQUIRE_EQ(o.fp_mode,AcceleratorFpMode::Strict); }

CONTRACT_MAIN("codegen-accelerator")
#else
#error "RED CONTRACT: implement optional native/SIMD/accelerator contracts only after CPU semantics are green"
#endif
