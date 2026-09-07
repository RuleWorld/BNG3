#include "../test_harness.hh"
#if defined(NFCORE2_ENABLE_REFERENCE_DIFF_SPEC)
#include "reference_engine.hh"
#include "shadow_runner.hh"
using namespace NFcore2;
TEST(reference_and_optimized_initial_semantic_hash_match) { }
TEST(reference_and_optimized_each_rule_propensity_match) { }
TEST(reference_and_optimized_total_propensity_match) { }
TEST(reference_and_optimized_embedding_counts_match) { }
TEST(reference_and_optimized_selected_rule_match_under_shared_random_draw) { }
TEST(reference_and_optimized_selected_mapping_match_when_order_compat_enabled) { }
TEST(reference_and_optimized_post_event_hash_match) { }
TEST(reference_and_optimized_observables_match_after_every_event) { }
TEST(reference_and_optimized_populations_match_after_every_event) { }
TEST(reference_and_optimized_100k_events_zero_mismatches_tiny_models) { }
TEST(reference_and_optimized_random_generated_models_zero_mismatches) { }
TEST(reference_and_optimized_symmetric_site_models_zero_mismatches) { }
TEST(reference_and_optimized_creation_deletion_pool_reuse_zero_mismatches) { }
TEST(reference_and_optimized_time_dependent_rates_zero_mismatches) { }
TEST(reference_and_optimized_observable_dependent_rates_zero_mismatches) { }
TEST(reference_and_optimized_connectedTo_models_zero_mismatches) { }
TEST(reference_and_optimized_null_event_semantics_match) { }
TEST(reference_and_optimized_multi_reactant_overlap_semantics_match) { }
TEST(rasi_500_seed_424242_sim4_hash_matches_known_reference) { }
TEST(uorf_sim30_event_count_and_hash_match_reference) { }
#endif
