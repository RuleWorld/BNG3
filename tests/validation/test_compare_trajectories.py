"""Column-set policy of `compare_trajectories`.

The comparator has two policies for a column the two legs do not share, and
they answer different questions:

- `COLUMNS_INTERSECT` asks "do the values both legs report agree?". It cannot
  see an absent column, by construction -- that is what makes it usable as a
  numeric comparator over a column set that is allowed to vary.
- `COLUMNS_EXACT` asks "are these the same trajectory?". A dropped observable
  and a phantom extra observable are both failures, because a leg that has
  lost a population is indistinguishable, to the intersect policy, from a leg
  whose population is perfectly stable -- which is the shape a seed-handling
  or observable-emission regression takes.

These are the numbers, not the mechanism: each test feeds a leg with an
altered column set and states what the policy reports.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.validation.compare import (
    COLUMNS_EXACT,
    COLUMNS_INTERSECT,
    compare_trajectories,
)

TIME = [0.0, 1.0, 2.0]
REF = np.array([TIME, [10.0, 12.0, 14.0], [0.0, 1.0, 2.0]]).T
REF_COLS = ["time", "Otot", "RD_Ba"]


def test_intersect_reports_a_perfect_score_when_a_leg_drops_an_observable():
    """The default policy's blind spot, pinned so it stays a stated choice.

    This is what the comparator did for *every* caller before the mode
    existed: the missing column drops out of the shared set, `Otot` matches
    exactly, and the result is `ok=True, max_rel_err=0.0`. A caller that means
    "the same trajectory" must not be on this policy.
    """
    dropped = np.array([TIME, [10.0, 12.0, 14.0]]).T

    diff = compare_trajectories(
        REF, REF_COLS, dropped, ["time", "Otot"], rtol=0.0, atol=0.0
    )

    assert diff.ok
    assert diff.max_rel_err == 0.0


def test_intersect_reports_a_perfect_score_on_a_phantom_observable():
    phantom = np.column_stack([REF, [5.0, 5.0, 5.0]])

    diff = compare_trajectories(
        REF,
        REF_COLS,
        phantom,
        [*REF_COLS, "Oghost"],
        rtol=0.0,
        atol=0.0,
        columns=COLUMNS_INTERSECT,
    )

    assert diff.ok
    assert diff.max_rel_err == 0.0


def test_exact_rejects_a_dropped_observable_and_names_it():
    dropped = np.array([TIME, [10.0, 12.0, 14.0]]).T

    diff = compare_trajectories(
        REF, REF_COLS, dropped, ["time", "Otot"], rtol=0.0, atol=0.0,
        columns=COLUMNS_EXACT,
    )

    assert not diff.ok
    assert "RD_Ba" in diff.note
    assert "Oghost" not in diff.note
    assert np.isinf(diff.max_rel_err)


def test_exact_rejects_a_phantom_observable_and_names_it():
    phantom = np.column_stack([REF, [5.0, 5.0, 5.0]])

    diff = compare_trajectories(
        REF,
        REF_COLS,
        phantom,
        [*REF_COLS, "Oghost"],
        rtol=0.0,
        atol=0.0,
        columns=COLUMNS_EXACT,
    )

    assert not diff.ok
    assert "Oghost" in diff.note


def test_exact_accepts_the_same_observables_reported_in_a_different_order():
    """Order is deliberately not part of the policy; values are located by name.

    A leg that emits `Otot` before `RD_Ba` rather than after is reporting the
    same two numbers, and this comparator can align them. Ordered identity is
    a stronger claim than the parity gates make, and
    `test_parity_nfsim_seed._identity_report` is where that claim lives.
    """
    reordered = REF[:, [0, 2, 1]]

    diff = compare_trajectories(
        REF, REF_COLS, reordered, ["time", "RD_Ba", "Otot"],
        rtol=0.0, atol=0.0, columns=COLUMNS_EXACT,
    )

    assert diff.ok
    assert diff.max_rel_err == 0.0


def test_exact_still_reports_a_model_with_no_observables_as_unshared():
    """Both legs empty is agreement; it must not be reported as a set mismatch.

    The tier-P direct-path sweep measures models that expose no observables at
    all (`docs/TIER_P_DIRECT_PATH_SWEEP.md`). That is a distinct fact from a
    column-set disagreement and has its own bucket in the sweep record, so
    `exact` must not swallow it into "the sets differ".
    """
    time_only = np.array([TIME]).T

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


def test_an_unknown_column_mode_is_rejected_rather_than_defaulted():
    for mode in ("intersect-then-check", "", None):
        with pytest.raises(ValueError, match="unknown column mode"):
            compare_trajectories(
                REF, REF_COLS, REF, REF_COLS, rtol=0.0, atol=0.0, columns=mode
            )