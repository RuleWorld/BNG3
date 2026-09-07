#include "../test_harness.hh"
#if defined(NFCORE2_ENABLE_SPECIALIZATION_SPEC)
#include "specializer.hh"
using namespace NFcore2;
TEST(specialized_matcher_matches_generic_bytecode_for_all_16bit_states) { }
TEST(specialized_transform_matches_generic_bytecode_random_states) { }
TEST(simd_batch_matcher_matches_scalar_lane_by_lane) { }
TEST(simd_tail_handling_matches_scalar_for_nonvector_multiple) { }
TEST(jit_matcher_matches_interpreter_random_programs) { }
TEST(jit_transform_matches_interpreter_random_programs) { }
TEST(jit_cache_key_includes_all_semantic_program_fields) { }
TEST(jit_cache_reuse_does_not_cross_model_identity_unsafely) { }
TEST(specialization_fallback_for_unsupported_opcode_is_exact) { }
TEST(specialization_never_changes_rng_consumption) { }
TEST(specialization_hotness_threshold_does_not_change_results) { }
TEST(compiling_profiler_counters_out_does_not_change_semantics) { }
#endif
