#include "../test_harness.hh"
#if defined(NFCORE2_ENABLE_POPULATION_HYBRID_SPEC)
#include "hybrid_population.hh"
using namespace NFcore2;
TEST(particle_population_conversion_preserves_total_count) { }
TEST(population_reactant_propensity_matches_exact_combinatorics) { }
TEST(two_identical_population_reactants_use_n_choose_2) { }
TEST(population_underflow_is_impossible_after_event_selection) { }
TEST(population_to_particle_creation_is_atomic) { }
TEST(particle_to_population_deletion_clears_all_bonds_first) { }
TEST(hybrid_rule_crossing_particle_population_representation_matches_reference) { }
TEST(population_observable_updates_incrementally) { }
TEST(large_population_count_does_not_allocate_per_particle_objects) { }
TEST(population_count_near_int64_limit_detects_overflow) { }
TEST(hybrid_snapshot_restore_preserves_counts) { }
TEST(hybrid_model_image_roundtrip_preserves_representation_metadata) { }
TEST(random_birth_death_network_matches_reference_ssa_distribution) { }
#endif
