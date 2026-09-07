#include "../test_harness.hh"
#if defined(NFCORE2_ENABLE_PROFILER_SPEC)
#include "runtime_metrics.hh"
using namespace NFcore2;
TEST(metrics_disabled_adds_no_semantic_state) { }
TEST(metrics_disabled_counters_compile_out_of_event_hot_path) { }
TEST(events_counter_increments_only_successful_events) { }
TEST(rejected_match_counter_tracks_rejected_fires) { }
TEST(candidate_updates_per_event_matches_instrumented_reference) { }
TEST(propensity_updates_per_event_matches_instrumented_reference) { }
TEST(bytes_per_molecule_metric_matches_allocator_accounting) { }
TEST(bytes_per_match_metric_matches_materialized_match_storage) { }
TEST(family_activity_distribution_sums_to_total_events) { }
TEST(scaffold_update_radius_reports_true_max_touched_distance) { }
TEST(rejection_rate_denominator_is_well_defined_at_zero_events) { }
TEST(per_family_event_cost_uses_monotonic_clock) { }
TEST(profiler_output_does_not_change_rng_use_or_trajectory) { }
TEST(profiler_overhead_budget_is_below_configured_threshold) { }
#endif
