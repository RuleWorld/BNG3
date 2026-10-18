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
