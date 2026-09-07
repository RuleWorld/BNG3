#include "../test_harness.hh"
#if defined(NFCORE2_ENABLE_REPRODUCIBILITY_SPEC)
#include "rng_policy.hh"
using namespace NFcore2;
TEST(same_model_seed_build_repeats_same_trajectory) { }
TEST(compiled_image_reload_preserves_seeded_trajectory) { }
TEST(snapshot_restore_preserves_next_random_draw) { }
TEST(batch_worker_scheduling_does_not_change_rng_stream) { }
TEST(rule_family_compression_preserves_semantic_distribution) { }
TEST(nfsim_compat_mode_preserves_legacy_draw_count_supported_subset) { }
TEST(nfsim_compat_mode_preserves_legacy_reaction_order_supported_subset) { }
TEST(optimized_mode_documents_when_internal_order_is_not_legacy_compatible) { }
TEST(rejection_sampling_consumes_rng_under_explicit_policy) { }
TEST(selector_zero_activity_changes_do_not_consume_rng) { }
TEST(parameter_update_without_event_does_not_consume_rng) { }
TEST(profiling_on_off_does_not_consume_different_rng) { }
TEST(serialization_does_not_persist_accidental_pointer_identity) { }
#endif
