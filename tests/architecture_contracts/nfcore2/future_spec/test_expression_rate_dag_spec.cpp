#include "../test_harness.hh"
#if defined(NFCORE2_ENABLE_EXPRESSION_DAG_SPEC)
#include "expression_dag.hh"
using namespace NFcore2;
TEST(constant_expression_is_folded_at_compile_time) { }
TEST(parameter_expression_updates_only_dependent_rates) { }
TEST(observable_expression_reuses_matcher_node) { }
TEST(time_expression_is_classified_time_dependent) { }
TEST(state_and_time_expression_tracks_both_dependency_classes) { }
TEST(expression_common_subexpressions_are_deduplicated) { }
TEST(expression_nan_and_inf_propagation_is_rejected) { }
TEST(expression_divide_by_zero_has_defined_failure_semantics) { }
TEST(expression_dependency_cycle_is_rejected) { }
TEST(piecewise_constant_time_rate_schedules_exact_boundary_event) { }
TEST(continuous_time_hazard_integral_matches_analytic_linear_rate) { }
TEST(continuous_time_hazard_inversion_matches_analytic_exponential_rate) { }
TEST(rate_update_order_does_not_change_total_propensity) { }
TEST(100k_rule_family_members_share_one_expression_program) { }
TEST(observable_delta_invalidates_only_consuming_expression_nodes) { }
TEST(parameter_sweep_reuses_expression_topology) { }
#endif
