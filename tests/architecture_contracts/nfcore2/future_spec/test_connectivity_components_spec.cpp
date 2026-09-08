#include "../test_harness.hh"
#if defined(NFCORE2_ENABLE_CONNECTIVITY_SPEC)
#include "component_index.hh"
using namespace NFcore2;
TEST(singletons_have_unique_component_ids) { }
TEST(bind_unions_two_components) { }
TEST(bind_within_component_does_not_change_component_size) { }
TEST(delete_bridge_splits_component_into_two_correct_sets) { }
TEST(delete_nonbridge_preserves_single_component) { }
TEST(split_relabels_smaller_side_only_when_optimization_enabled) { }
TEST(component_version_increments_on_topology_change) { }
TEST(component_predicate_cache_invalidates_by_version) { }
TEST(component_size_cache_matches_bfs_reference_random_graphs) { }
TEST(connectivity_random_100k_edge_mutations_matches_naive_bfs) { }
TEST(ring_opening_multiple_deleted_edges_computes_final_components_once) { }
TEST(stale_component_ids_are_never_observed_after_split) { }
TEST(scaffold_structural_connectivity_bypasses_generic_component_index) { }
TEST(connectedTo_query_on_large_general_complex_remains_exact) { }
#endif
