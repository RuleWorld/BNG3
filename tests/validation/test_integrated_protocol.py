"""Pure harness contract checks for integrated public protocol evidence."""

from types import SimpleNamespace

import numpy as np

from tests.validation import integrated_protocol as protocol


def test_expected_protocol_checks_are_explicit_and_issue_linked():
    assert protocol.expected_check_names == (
        "modern-run-equivalence",
        "invalid-option-rejection",
        "independent-ssa-state",
        "exception-recovery",
        "parameter-source-controls",
        "lifecycle-construction-isolation",
        "lifecycle-mutation-baseline",
        "lifecycle-public-routes",
        "lifecycle-topology-unavailable",
        "lifecycle-repeated-instantiation",
        "lifecycle-concurrent-instantiation",
        "lifecycle-independent-rng",
        "lifecycle-independent-caches",
        "lifecycle-independent-solver-state",
        "lifecycle-exception-cleanup",
        "lifecycle-parameter-only-reuse",
        "lifecycle-topology-invalidation",
        "lifecycle-compartment-invalidation",
        "protocol-action-option-equivalence",
        "protocol-decision-sharing",
    )
    assert set(protocol._ISSUES) == set(protocol.expected_check_names)
    assert {issue for issues in protocol._ISSUES.values() for issue in issues} == {
        138,
        139,
        140,
        141,
        143,
        171,
        172,
        178,
    }
    for name in protocol.expected_check_names:
        row = protocol._row("generated-case", name, "PASS", "checked")
        assert row == {
            "check": f"generated-case:protocol:{name}",
            "status": "PASS",
            "detail": "checked",
            "first_difference": None,
            "related_issues": protocol._ISSUES[name],
        }


def test_lifecycle_protocol_declares_bounded_work_and_explicit_topology_gap():
    assert protocol.lifecycle_budget == {
        "max_cases": 4,
        "construction_runs_per_model": 3,
        "concurrent_models_per_case": 2,
        "mutation_parameters": ("V", "N", "k"),
        "mutation_methods": ("ode", "ssa"),
        "public_routes_per_case": 2,
        "topology_probes": (
            "add_compartment",
            "add_molecule_type",
            "add_seed_species",
            "remove_seed_species",
            "move_species_to_compartment",
        ),
        "repeated_runs_per_model": 3,
        "concurrent_instances_per_case": 4,
        "concurrent_seeds": (1729, 8123),
        "rng_sample_steps": 100,
        "solver_state_runs_per_model": 4,
        "exception_recovery_iterations": 3,
        "parameter_only_overrides": ("k",),
        "volume_override_factor": 3.0,
    }
    row = protocol._topology_unavailable_row("case")
    assert row["status"] == "UNSUPPORTED"
    assert row["check"] == "case:protocol:lifecycle-topology-unavailable"
    assert "runtime topology mutation" in row["detail"]


def test_every_lifecycle_check_is_named_and_issue_linked():
    names = protocol._LIFECYCLE_CHECK_NAMES
    assert len(names) == len(set(names))
    assert set(names) <= set(protocol.expected_check_names)
    assert set(names) == {
        name
        for name in protocol.expected_check_names
        if name.startswith("lifecycle-") and name != "lifecycle-topology-unavailable"
    }
    for name, detail, check in protocol._LIFECYCLE_CHECKS:
        assert callable(check)
        assert detail and isinstance(detail, str)
        assert protocol._ISSUES[name]
    instance_checks = {
        name
        for name in protocol._LIFECYCLE_CHECK_NAMES
        if name
        not in {
            "lifecycle-construction-isolation",
            "lifecycle-mutation-baseline",
            "lifecycle-public-routes",
        }
    }
    assert instance_checks
    for name in instance_checks:
        assert 141 in protocol._ISSUES[name]


def test_lifecycle_case_slice_respects_declared_budget():
    selected = protocol._lifecycle_case_ids()
    assert len(selected) == protocol.lifecycle_budget["max_cases"] == 4
    assert len(set(selected)) == 4


def test_result_comparison_requires_exact_time_grid_and_observable_set():
    base = SimpleNamespace(
        time=np.array([0.25, 0.5, 1.0]),
        observables={"A": np.array([10.0, 9.0, 8.0])},
    )
    same = SimpleNamespace(
        time=np.array([0.25, 0.5, 1.0]),
        observables={"A": np.array([10.0, 9.0, 8.0 + 1e-11])},
    )
    assert protocol._result_difference(base, same) is None

    shifted = SimpleNamespace(
        time=np.array([0.25, 0.5000000001, 1.0]), observables=same.observables
    )
    assert protocol._result_difference(base, shifted)["field"] == "time"

    wrong_columns = SimpleNamespace(
        time=base.time, observables={"B": base.observables["A"]}
    )
    assert (
        protocol._result_difference(base, wrong_columns)["field"] == "observable_names"
    )


def test_requested_grid_check_rejects_identically_ignored_grid():
    requested = [0.25, 0.6, 1.7, 3.0]
    ignored = SimpleNamespace(
        time=np.array([0.0, 1.0, 2.0, 3.0]),
        observables={"A": np.array([10.0, 9.0, 8.0, 7.0])},
    )
    difference = protocol._requested_grid_difference(ignored, requested)
    assert difference["field"] == "requested_time_grid"
    assert difference["row"] == 0


def test_result_comparison_rejects_nonfinite_and_malformed_arrays():
    finite_time = np.array([0.0, 1.0])
    finite_values = {"A": np.array([2.0, 1.0])}
    valid = SimpleNamespace(time=finite_time, observables=finite_values)

    nonfinite_time = SimpleNamespace(
        time=np.array([0.0, np.inf]), observables=finite_values
    )
    assert (
        protocol._result_difference(nonfinite_time, valid)["field"]
        == "left.time.finite"
    )

    nonfinite_value = SimpleNamespace(
        time=finite_time, observables={"A": np.array([2.0, np.nan])}
    )
    assert (
        protocol._result_difference(nonfinite_value, valid)["field"] == "left.A.finite"
    )

    malformed = SimpleNamespace(time=np.empty((0,)), observables={"A": np.empty((0,))})
    assert protocol._result_difference(malformed, valid)["field"] == "left.time.shape"

    wrong_length = SimpleNamespace(
        time=finite_time, observables={"A": np.array([2.0, 1.0, 0.0])}
    )
    assert (
        protocol._result_difference(wrong_length, valid)["field"] == "left.A.time_shape"
    )


def test_saved_result_snapshot_detects_mutation():
    result = SimpleNamespace(
        time=np.array([0.0, 1.0]),
        observables={"A": np.array([2.0, 1.0])},
        concentrations=np.array([[2.0], [1.0]]),
    )
    saved = protocol._copy_result(result)
    assert (
        protocol._snapshot_difference(saved, protocol._copy_result(result), "saved")
        is None
    )

    result.observables["A"][1] = 0.5
    assert protocol._snapshot_difference(
        saved, protocol._copy_result(result), "saved"
    ) == {"field": "saved.A"}


def test_public_route_receipt_allows_results_without_concentration_matrix():
    result = SimpleNamespace(
        time=np.array([0.0, 1.0]), observables={"A": np.array([2.0, 1.0])}
    )

    receipt = protocol._result_receipt(result, route="cli")

    assert receipt["concentrations"] is None
    assert (
        protocol._snapshot_difference(
            protocol._copy_result(result), protocol._copy_result(result), "saved"
        )
        is None
    )


def test_lifecycle_baseline_detector_catches_stale_mutated_run():
    baseline = SimpleNamespace(
        time=np.array([0.0, 1.0]),
        observables={"A": np.array([10.0, 8.0])},
        concentrations=np.array([[10.0], [8.0]]),
    )
    stale_after_reset = SimpleNamespace(
        time=np.array([0.0, 1.0]),
        observables={"A": np.array([10.0, 7.0])},
        concentrations=np.array([[10.0], [7.0]]),
    )
    assert protocol._result_difference(baseline, stale_after_reset)["field"] == "A"


def test_lifecycle_receipt_retains_actual_outputs(tmp_path):
    import json

    result = SimpleNamespace(
        time=np.array([0.0, 1.0]),
        observables={"A": np.array([10.0, 8.0])},
        concentrations=np.array([[10.0], [8.0]]),
    )
    protocol._write_lifecycle_receipt(
        tmp_path,
        "lifecycle-mutation-baseline",
        [protocol._result_receipt(result, method="ode", phase="baseline")],
    )
    receipt = json.loads((tmp_path / "lifecycle-results.json").read_text())
    assert receipt["lifecycle-mutation-baseline"][0]["observables"]["A"] == [10.0, 8.0]


def test_rate_parameter_does_not_select_unused_source_parameter():
    model = SimpleNamespace(
        parameters=[SimpleNamespace(name="k", expression="0.4")],
        functions=[],
        reaction_rules=[SimpleNamespace(rates=["0.4"])],
    )
    from tests.validation.integrated_worker import _rate_parameter

    assert protocol._rate_parameter(model) is None
    assert _rate_parameter(model) is None


def test_rate_parameter_follows_functions_and_parameter_dependencies():
    model = SimpleNamespace(
        parameters=[SimpleNamespace(name="k", expression="0.4")],
        functions=[SimpleNamespace(name="flux", expression="k * 2", args=[])],
        reaction_rules=[SimpleNamespace(rates=["flux() * 3"])],
    )
    assert protocol._rate_parameter(model) == "k"


def test_lifecycle_detects_rebuilt_network_despite_equal_outputs(tmp_path):
    class RebuildingModel:
        def __init__(self):
            self._network = None

        def set_parameter(self, *args):
            self._network = None

        def simulate(self, **kwargs):
            self._network = object()
            return SimpleNamespace(
                time=np.array([0.0, 2.0]),
                observables={"A": np.array([20.0, 19.0])},
            )

    difference = protocol._lifecycle_construction_isolation(
        SimpleNamespace(load=lambda path: RebuildingModel()),
        dict(
            id="v1-n20-r0-a0",
            family="decay",
            volume=1,
            initial=20,
            reverse=False,
            atomize=False,
        ),
        tmp_path,
    )
    assert difference == {"field": "network_cache_rebuilt", "model": "left"}


def _lifecycle_case():
    return dict(
        id="v1-n20-r0-a0",
        family="decay",
        volume=1,
        initial=20,
        reverse=False,
        atomize=False,
    )


def _stub_result(value):
    return SimpleNamespace(
        time=np.array([0.0, 2.0]),
        observables={"A": np.array([value, value])},
    )


def test_topology_invalidation_detects_a_stale_cached_network(tmp_path):
    class StaleModel:
        def __init__(self):
            self._network = SimpleNamespace(
                species_names=["@cell::A()"], num_species=1, num_reactions=1
            )

        def generate_network(self):
            return self._network

        def execute(self):
            return None

        def simulate(self, **kwargs):
            raise AssertionError("a stale cache must be reported before simulating")

    difference = protocol._lifecycle_topology_invalidation(
        SimpleNamespace(load=lambda path: StaleModel()), _lifecycle_case(), tmp_path
    )
    assert difference["field"] == "topology.network_cache_not_invalidated"


def test_compartment_invalidation_detects_a_stale_cached_network(tmp_path):
    class StaleModel:
        def __init__(self):
            self._network = SimpleNamespace(
                species_names=["@cell::A()"], num_species=1, num_reactions=1
            )

        def execute(self):
            return None

        def simulate(self, **kwargs):
            return _stub_result(1.0)

    difference = protocol._lifecycle_compartment_invalidation(
        SimpleNamespace(load=lambda path: StaleModel()), _lifecycle_case(), tmp_path
    )
    assert difference["field"] == "compartment.network_cache_not_invalidated"


def test_repeated_instantiation_detects_a_diverging_repeat(tmp_path):
    class DriftingModel:
        def __init__(self):
            self.calls = 0

        def simulate(self, **kwargs):
            self.calls += 1
            return _stub_result(float(self.calls))

    difference = protocol._lifecycle_repeated_instantiation(
        SimpleNamespace(load=lambda path: DriftingModel()), _lifecycle_case(), tmp_path
    )
    assert difference["field"].startswith("repeat[0].")


def test_independent_rng_detects_an_ignored_seed(tmp_path):
    class SeedIgnoringModel:
        def simulate(self, **kwargs):
            return _stub_result(1.0)

    difference = protocol._lifecycle_independent_rng(
        SimpleNamespace(load=lambda path: SeedIgnoringModel()),
        _lifecycle_case(),
        tmp_path,
    )
    assert difference == {"field": "rng.seed_not_honored"}


def test_independent_caches_detects_a_shared_network_cache(tmp_path):
    shared = SimpleNamespace(
        species_names=["@cell::A()"], num_species=1, num_reactions=1
    )

    class SharedCacheModel:
        def __init__(self):
            self._network = shared

        def generate_network(self):
            return shared

    difference = protocol._lifecycle_independent_caches(
        SimpleNamespace(load=lambda path: SharedCacheModel()),
        _lifecycle_case(),
        tmp_path,
    )
    assert difference == {"field": "caches.network_shared"}


def test_protocol_action_budget_declares_typed_probes_and_bounded_slices():
    budget = protocol.protocol_action_budget
    assert budget["max_cases"] == len(budget["cases"]) == 1
    assert budget["surfaces"] == ("cli", "python-api", "bngl-action")
    assert set(budget["explicit_options"]) == {
        "method",
        "t_start",
        "t_end",
        "n_steps",
        "atol",
        "rtol",
    }
    assert set(budget["default_options"]) == {"method", "t_end"}
    assert budget["default_points"] == 101
    names = [name for name, _options in budget["invalid_options"]]
    assert names == [
        "zero-steps",
        "non-positive-atol",
        "non-positive-rtol",
        "reversed-window",
    ]
    for name, options in budget["invalid_options"]:
        assert options["method"] in {"ode", "ssa"}, name
    assert protocol._protocol_action_case_ids(budget["cases"]) == budget["cases"]
    assert protocol.decision_sharing_budget["max_cases"] == len(
        protocol.decision_sharing_budget["cases"]
    )
    assert protocol.decision_sharing_budget["capability_surfaces"] == (
        "bngl-action",
        "python-api",
    )


def test_protocol_checks_are_named_and_issue_linked():
    names = protocol._PROTOCOL_CHECK_NAMES
    assert len(names) == len(set(names))
    assert set(names) == {
        "protocol-action-option-equivalence",
        "protocol-decision-sharing",
    }
    assert set(names) <= set(protocol.expected_check_names)
    for name, detail, check in protocol._PROTOCOL_CHECKS:
        assert callable(check)
        assert detail and isinstance(detail, str)
        assert protocol._ISSUES[name]
    assert protocol._ISSUES["protocol-action-option-equivalence"] == [140]
    assert protocol._ISSUES["protocol-decision-sharing"] == [178]


def test_protocol_probes_render_typed_option_values():
    assert protocol._render_option_value(True) == "1"
    assert protocol._render_option_value(False) == "0"
    assert protocol._render_option_value(4) == "4"
    assert protocol._render_option_value(0.5) == "0.5"
    assert protocol._render_option_value("ode") == '"ode"'
    assert (
        protocol._render_action("simulate", {"method": "ode", "n_steps": 4})
        == 'simulate({method=>"ode",n_steps=>4})'
    )
    assert protocol._cli_option_arguments({"t_end": 2.0, "n_steps": 4}) == [
        "--t-end",
        "2.0",
        "--n-steps",
        "4",
    ]
    assert protocol._api_options({"t_end": 2.0, "sparse": 1}) == {
        "t_end": 2.0,
        "sparse": 1,
    }


def test_protocol_probe_outcomes_cover_the_defaults_and_the_invalid_options():
    probes = protocol._protocol_action_probes()
    assert [name for name, _options, _expected in probes] == [
        "explicit-options",
        "default-options",
        "zero-steps",
        "non-positive-atol",
        "non-positive-rtol",
        "reversed-window",
    ]
    assert [expected for _name, _options, expected in probes] == [
        "accepted",
        "accepted",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
    ]


def test_trajectory_comparison_detects_a_divergent_surface():
    left = (
        np.array([0.0, 1.0, 2.0]),
        ["A"],
        [np.array([10.0, 9.0, 8.0])],
    )
    same = (
        np.array([0.0, 1.0, 2.0]),
        ["A"],
        [np.array([10.0, 9.0, 8.0])],
    )
    assert protocol._trajectory_difference(left, same, atol=1e-9, rtol=1e-9) is None

    shifted = (
        np.array([0.0, 1.0, 2.0]),
        ["A"],
        [np.array([10.0, 9.5, 8.0])],
    )
    difference = protocol._trajectory_difference(left, shifted, atol=1e-9, rtol=1e-9)
    assert difference["field"] == "observable0"
    assert difference["left"] == 9.0
    assert difference["right"] == 9.5

    regridded = (
        np.array([0.0, 1.0, 2.5]),
        ["A"],
        [np.array([10.0, 9.0, 8.0])],
    )
    difference = protocol._trajectory_difference(left, regridded, atol=1e-9, rtol=1e-9)
    assert difference["field"] == "time"

    renamed = (
        np.array([0.0, 1.0, 2.0]),
        ["B"],
        [np.array([10.0, 9.0, 8.0])],
    )
    assert protocol._observable_name_difference(["A"], ["B"]) == {
        "field": "observable_names",
        "left": ["A"],
        "right": ["B"],
    }
    assert protocol._observable_name_difference(["A"], ["A"]) is None
    assert renamed[1] == ["B"]
