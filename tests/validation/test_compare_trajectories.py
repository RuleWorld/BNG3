"""Observable-column identity contracts for parity comparators."""

from __future__ import annotations

import numpy as np
import pytest

from tests.validation.compare import (
    COLUMNS_EXACT,
    COLUMNS_INTERSECT,
    compare_stochastic,
    compare_trajectories,
)

TIME = np.array([0.0, 1.0, 2.0])
REFERENCE = np.column_stack([TIME, [10.0, 12.0, 14.0], [0.0, 1.0, 2.0]])
REFERENCE_COLUMNS = ["time", "Ototal", "RD_Ba"]


def test_exact_rejects_a_missing_required_observable():
    test = REFERENCE[:, :2]

    diff = compare_trajectories(
        REFERENCE,
        REFERENCE_COLUMNS,
        test,
        ["time", "Ototal"],
        rtol=0.0,
        atol=0.0,
        columns=COLUMNS_EXACT,
    )

    assert not diff.ok
    assert "RD_Ba" in diff.note


def test_exact_rejects_a_phantom_observable():
    test = np.column_stack([REFERENCE, [5.0, 5.0, 5.0]])

    diff = compare_trajectories(
        REFERENCE,
        REFERENCE_COLUMNS,
        test,
        [*REFERENCE_COLUMNS, "Ophantom"],
        rtol=0.0,
        atol=0.0,
        columns=COLUMNS_EXACT,
    )

    assert not diff.ok
    assert "Ophantom" in diff.note


def test_exact_aligns_reordered_observables_by_name():
    reordered = REFERENCE[:, [0, 2, 1]]

    diff = compare_trajectories(
        REFERENCE,
        REFERENCE_COLUMNS,
        reordered,
        ["time", "RD_Ba", "Ototal"],
        rtol=0.0,
        atol=0.0,
        columns=COLUMNS_EXACT,
    )

    assert diff.ok
    assert diff.max_rel_err == 0.0


@pytest.mark.parametrize(
    ("data", "columns", "other_data", "other_columns"),
    [
        (
            np.column_stack([TIME, [10.0, 12.0, 14.0], [11.0, 13.0, 15.0]]),
            ["time", "Ototal", "Ototal"],
            REFERENCE,
            REFERENCE_COLUMNS,
        ),
        (
            REFERENCE,
            REFERENCE_COLUMNS,
            np.column_stack([TIME, [10.0, 12.0, 14.0], [11.0, 13.0, 15.0]]),
            ["time", "Ototal", "Ototal"],
        ),
    ],
)
def test_exact_rejects_duplicate_observable_columns(
    data, columns, other_data, other_columns
):
    diff = compare_trajectories(
        data,
        columns,
        other_data,
        other_columns,
        rtol=0.0,
        atol=0.0,
        columns=COLUMNS_EXACT,
    )

    assert not diff.ok
    assert "duplicate" in diff.note.lower()


def test_numeric_trajectory_comparison_can_explicitly_intersect_columns():
    diff = compare_trajectories(
        REFERENCE,
        REFERENCE_COLUMNS,
        REFERENCE[:, :2],
        ["time", "Ototal"],
        rtol=0.0,
        atol=0.0,
        columns=COLUMNS_INTERSECT,
    )

    assert diff.ok
    assert diff.max_rel_err == 0.0


def test_default_column_policy_intersects_when_an_observable_is_missing():
    """Omitting ``columns`` retains the comparator's numeric-intersection default."""
    diff = compare_trajectories(
        REFERENCE,
        REFERENCE_COLUMNS,
        REFERENCE[:, :2],
        ["time", "Ototal"],
        rtol=0.0,
        atol=0.0,
    )

    assert diff.ok
    assert diff.max_rel_err == 0.0


def test_exact_rejects_two_time_only_trajectories_as_unshared():
    time_only = TIME[:, np.newaxis]

    diff = compare_trajectories(
        time_only,
        ["time"],
        time_only,
        ["time"],
        rtol=0.0,
        atol=0.0,
        columns=COLUMNS_EXACT,
    )

    assert not diff.ok
    assert diff.note == "no shared observable columns"


def test_stochastic_comparison_rejects_missing_or_phantom_observables():
    missing = (REFERENCE[:, :2], ["time", "Ototal"])
    phantom = (
        np.column_stack([REFERENCE, [5.0, 5.0, 5.0]]),
        [*REFERENCE_COLUMNS, "Ophantom"],
    )
    reference_runs = [(REFERENCE, REFERENCE_COLUMNS)] * 2

    missing_diff = compare_stochastic(
        reference_runs, [missing, missing], columns=COLUMNS_EXACT
    )
    phantom_diff = compare_stochastic(
        reference_runs, [phantom, phantom], columns=COLUMNS_EXACT
    )

    assert not missing_diff.ok
    assert "RD_Ba" in missing_diff.note
    assert not phantom_diff.ok
    assert "Ophantom" in phantom_diff.note


def test_stochastic_comparison_aligns_reordered_columns_by_name():
    reordered = (REFERENCE[:, [0, 2, 1]], ["time", "RD_Ba", "Ototal"])

    diff = compare_stochastic(
        [(REFERENCE, REFERENCE_COLUMNS)] * 2,
        [reordered, reordered],
        columns=COLUMNS_EXACT,
    )

    assert diff.ok
    assert diff.n_violations == 0


def test_stochastic_comparison_rejects_duplicate_columns():
    duplicate = (
        np.column_stack([TIME, [10.0, 12.0, 14.0], [11.0, 13.0, 15.0]]),
        ["time", "Ototal", "Ototal"],
    )

    diff = compare_stochastic(
        [(REFERENCE, REFERENCE_COLUMNS)] * 2,
        [duplicate, duplicate],
        columns=COLUMNS_EXACT,
    )

    assert not diff.ok
    assert "duplicate" in diff.note.lower()


def test_unknown_column_policy_fails_closed():
    with pytest.raises(ValueError, match="unknown column mode"):
        compare_trajectories(
            REFERENCE,
            REFERENCE_COLUMNS,
            REFERENCE,
            REFERENCE_COLUMNS,
            columns="intersection-ish",
        )

    with pytest.raises(ValueError, match="unknown column mode"):
        compare_stochastic(
            [(REFERENCE, REFERENCE_COLUMNS)] * 2,
            [(REFERENCE, REFERENCE_COLUMNS)] * 2,
            columns="intersection-ish",
        )
