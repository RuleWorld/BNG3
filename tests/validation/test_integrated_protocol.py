"""Pure harness contract checks for integrated public protocol evidence."""

from types import SimpleNamespace

import numpy as np
import pytest

from tests.validation import (
    integrated_consumers,
    integrated_protocol as protocol,
    reporting,
)
from tests.validation.reproduce_issue141_lifecycle import _native_extension_path


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
        "lifecycle-topology-edits",
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
    }
    assert "lifecycle-topology-edits" in protocol.expected_check_names
    # The former unavailability row is retired now that the edits exist.
    retired = "case:protocol:lifecycle-topology-unavailable"
    assert retired not in {f"case:protocol:{n}" for n in protocol.expected_check_names}
    assert protocol._ISSUES["lifecycle-topology-edits"] == [141, 143, 171]


def test_topology_contract_builds_an_independent_fresh_source():
    source = (
        "begin model\nbegin compartments\n  C 3 1\nend compartments\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  @C:A() 10\nend seed species\nend model\n"
    )
    assert protocol._source_compartments(source) == ["C"]
    edited = protocol._insert_source_line(source, "molecule types", "P()")
    edited = protocol._insert_source_line(edited, "seed species", "@C:P() 3")
    assert "  A()\n  P()\nend molecule types" in edited
    assert "  @C:A() 10\n  @C:P() 3\nend seed species" in edited
    without = "begin model\nbegin seed species\n  A() 1\nend seed species\nend model\n"
    added = protocol._insert_source_line(without, "molecule types", "A()")
    assert added.index("begin molecule types") < added.index("begin seed species")


def test_lifecycle_case_slice_respects_declared_budget():
    selected = protocol._lifecycle_case_ids()
    assert len(selected) == protocol.lifecycle_budget["max_cases"] == 4
    assert len(set(selected)) == 4


def test_out_of_slice_lifecycle_checks_are_non_gating_but_remain_not_tested():
    from tests.validation.integrated_cases import generated_cases

    selected_ids = set(protocol._lifecycle_case_ids())
    outside_case = next(
        case for case in generated_cases(full=True) if case["id"] not in selected_ids
    )
    rows = protocol._lifecycle_not_tested_rows(
        outside_case["id"],
        outside_case,
    )
    assert [row["check"].rsplit(":", 1)[-1] for row in rows] == [
        "lifecycle-construction-isolation",
        "lifecycle-mutation-baseline",
        "lifecycle-public-routes",
    ]
    assert [row["status"] for row in rows] == ["NOT_TESTED"] * 3
    assert all(
        row["detail"]
        == "generated case is outside the declared four-case lifecycle slice"
        for row in rows
    )
    assert all(row["applicability"] == "not-applicable" for row in rows)

    report_rows = [dict(row, id=row["check"]) for row in rows]
    worker_summary = {
        "id": outside_case["id"] + ":protocol",
        "status": "NOT_TESTED",
        "detail": "protocol lifecycle slice was not selected",
    }
    integrated_consumers.mark_process_summary(worker_summary, report_rows)
    assert worker_summary["aggregate"] is True
    assert reporting.gate_failures([*report_rows, worker_summary]) == []

    required = dict(report_rows[0], support_required=True)
    assert reporting.gate_failures([required]) == [required]

    missing_source = [
        dict(row, id=row["check"])
        for row in protocol._lifecycle_not_tested_rows("missing-source", None)
    ]
    assert all("applicability" not in row for row in missing_source)
    assert reporting.gate_failures(missing_source) == missing_source

    selected_case_ids = (
        "v1-n20-r0-a0",
        "reversible-v3-n80-r0-a0",
        "dimerization-v1-n20-r0-a0",
        "dimerization-v3-n80-r0-a0",
    )
    for case_id in selected_case_ids:
        assert protocol._lifecycle_not_tested_rows(case_id, {"id": case_id}) == []
        selected_failure = protocol._row(
            case_id,
            "lifecycle-mutation-baseline",
            "FAIL",
            "trajectory differed",
        )
        selected_failure["id"] = selected_failure["check"]
        assert reporting.gate_failures([selected_failure]) == [selected_failure]


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


def test_protocol_progress_records_last_native_stage(tmp_path):
    import json

    protocol._write_protocol_progress(
        tmp_path,
        "dimerization-v3-n80-r0-a0",
        "lifecycle-construction-isolation",
        "simulate-model",
        model="left",
        suffix="parallel",
        seed=1729,
    )

    receipt = json.loads((tmp_path / "protocol-progress.json").read_text())
    assert receipt == {
        "schema_version": 1,
        "case_id": "dimerization-v3-n80-r0-a0",
        "check": "lifecycle-construction-isolation",
        "stage": "simulate-model",
        "context": {"model": "left", "suffix": "parallel", "seed": 1729},
    }
    assert not list(tmp_path.glob("protocol-progress.*.tmp"))


def test_antlr_thread_local_cache_probe_reads_compiler_definitions():
    assert not protocol._antlr_thread_local_cache_enabled(
        {"command": "c++ -Iantlr/runtime -c cpp/parser/generated/BNGParser.cpp"}
    )
    assert protocol._antlr_thread_local_cache_enabled(
        {
            "arguments": [
                "c++",
                "-DANTLR4_USE_THREAD_LOCAL_CACHE=1",
                "-c",
                "cpp/parser/generated/BNGParser.cpp",
            ]
        }
    )
    assert not protocol._antlr_thread_local_cache_enabled(
        {
            "arguments": [
                "c++",
                "-DANTLR4_USE_THREAD_LOCAL_CACHE=0",
                "-c",
                "cpp/parser/generated/BNGParser.cpp",
            ]
        }
    )


def test_issue141_reproducer_uses_the_native_module_bound_by_model(tmp_path):
    extension = tmp_path / "_bionetgen_cpp.test.so"
    model_module = SimpleNamespace(_cpp=SimpleNamespace(__file__=str(extension)))
    assert _native_extension_path(model_module) == extension.resolve()

    with pytest.raises(RuntimeError, match="did not bind a native extension"):
        _native_extension_path(SimpleNamespace(_cpp=None))


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
