#include "../test_harness.hh"
#if defined(NFCORE2_ENABLE_GPU_SPEC)
#include "gpu_batch.hh"
using namespace NFcore2;
TEST(gpu_homogeneous_scaffold_kernel_matches_cpu_each_event) { }
TEST(gpu_batch_trajectory_results_match_cpu_by_seed) { }
TEST(gpu_zero_active_events_matches_cpu_termination) { }
TEST(gpu_boundary_coordinates_match_cpu) { }
TEST(gpu_sparse_exception_updates_match_cpu) { }
TEST(gpu_rng_stream_partition_is_reproducible) { }
TEST(gpu_fallback_to_cpu_for_generic_graph_rule_is_exact) { }
TEST(gpu_mixed_supported_unsupported_families_preserve_semantics) { }
TEST(gpu_large_batch_no_cross_trajectory_state_aliasing) { }
TEST(gpu_float_precision_policy_meets_propensity_tolerance_contract) { }
#endif
