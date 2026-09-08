#include "../test_harness.hh"
#if defined(NFCORE2_ENABLE_SCAFFOLD_LOWERING_SPEC)
#include "scaffold_lowering.hh"
using namespace NFcore2;
TEST(linear_polymer_detection_accepts_simple_chain) { }
TEST(linear_polymer_detection_rejects_branch) { }
TEST(linear_polymer_detection_rejects_crosslink_cycle_unless_circular_declared) { }
TEST(circular_scaffold_wraparound_neighbors_are_correct) { }
TEST(position_specific_rules_canonicalize_to_coordinate_family) { }
TEST(elongation_move_is_local_stencil_update) { }
TEST(collision_rule_reads_bounded_neighbor_radius) { }
TEST(pretermination_rule_reads_bounded_neighbor_radius) { }
TEST(scaffold_lowering_preserves_observables) { }
TEST(scaffold_lowering_preserves_rule_propensities) { }
TEST(scaffold_lowering_preserves_selected_event_distribution) { }
TEST(scaffold_lowering_preserves_post_event_semantic_hash) { }
TEST(10kb_1mb_100mb_same_local_state_have_same_event_work) { }
TEST(mostly_empty_100mb_scaffold_memory_tracks_occupancy) { }
TEST(sparse_to_dense_representation_switch_preserves_state) { }
TEST(lowering_falls_back_for_unsupported_polymer_semantics) { }
#endif
