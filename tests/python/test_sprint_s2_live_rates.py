"""Independent checks for nested live rates across native protocol runs.

Named acceptance checks: ``release-rates`` and ``release-rate-invalidation``.
Capability rows exercised: ``bngl.global-functions``,
``bngl.nested-function-calls``, ``bngl.parameter-dependencies``, and
``bngl.mass-action``.

The source syntax and generated reference artifacts were checked with pinned
BNG2 RuleWorld/bionetgen@9601746f8884ed19ab2acea49fe87fc4660ace46. The
closed-form oracle below is derived from the pure-death hazard law, rather
than from either simulator.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from tests.validation import compare

try:
    from bionetgen import _bionetgen_cpp as cpp
except ImportError:  # pragma: no cover - source-only environments
    cpp = None


INITIAL_A = 30
INITIAL_RATE = 0.2
UPDATED_RATE = 0.7
SSA_RUNS = 100
SSA_SEED_BASE = 20261101
SSA_FAMILYWISE_ALPHA = 0.05
SSA_FAMILYWISE_COMPARISONS = 6


def _source(method: str, seed: int, *, update: float | None, initial_rate: float = 0.2):
    """Build a protocol case; None leaves the parameter unchanged."""
    setter = "" if update is None else f'setParameter("k",{update})\n'
    first_seed = f",seed=>{seed}" if method == "ssa" else ""
    return f"""begin parameters
  k {initial_rate}
end parameters
begin molecule types
  A()
  B()
end molecule types
begin functions
  g() = k/2
  f() = 2*g()
end functions
begin reaction rules
  convert: A() -> B() f()
end reaction rules
begin seed species
  A() 30
  B() 0
end seed species
begin observables
  Molecules A_count A()
  Molecules B_count B()
end observables
generate_network({{overwrite=>1}})
simulate({{method=>"{method}",suffix=>"trace",t_start=>0,t_end=>1,n_steps=>1,print_functions=>1{first_seed}}})
{setter}simulate({{method=>"{method}",suffix=>"trace",t_start=>1,t_end=>2,n_steps=>1,continue=>1,print_functions=>1}})
"""


def _run_protocol(
    directory: Path,
    *,
    method: str,
    seed: int,
    update: float | None,
    initial_rate: float = INITIAL_RATE,
):
    if cpp is None:
        pytest.skip("native BNG3 extension is unavailable")
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "live_rate.bngl"
    source.write_text(
        _source(method, seed, update=update, initial_rate=initial_rate),
        encoding="utf-8",
    )
    model = cpp.parse_file(str(source))
    assert model is not None
    cpp.execute(model, str(source), False)
    # Keep one output prefix across continuation so the runtime appends both
    # segments to one headed trajectory, preserving the pre/post boundary rows.
    trace, columns = compare.parse_gdat(directory / "live_rate_trace.gdat")
    assert trace is not None
    return trace, columns


def _at(data, columns, time, name):
    assert name in columns, f"missing {name!r} from columns {columns}"
    matches = np.flatnonzero(np.isclose(data[:, 0], time, rtol=0.0, atol=1e-10))
    assert len(matches) == 1, f"expected one row at t={time}, got {data[:, 0]}"
    return float(data[matches[0], columns.index(name)])


def _analytic_a(
    time: float, *, update: float | None, initial_rate: float = INITIAL_RATE
):
    if update is None:
        hazard = initial_rate * time
    elif time <= 1.0:
        hazard = initial_rate * time
    else:
        hazard = initial_rate + update * (time - 1.0)
    return INITIAL_A * math.exp(-hazard)


def _analytic_ode_trajectory(*, update: float, initial_rate: float = INITIAL_RATE):
    times = np.asarray([0.0, 1.0, 2.0])
    amounts = np.asarray(
        [_analytic_a(time, update=update, initial_rate=initial_rate) for time in times]
    )
    rate_values = np.asarray([initial_rate, initial_rate, update])
    data = np.column_stack(
        (times, amounts, INITIAL_A - amounts, rate_values / 2.0, rate_values)
    )
    return data, ["time", "A_count", "B_count", "g", "f"]


@pytest.mark.parametrize(
    ("update", "initial_rate", "final_rate"),
    [
        (UPDATED_RATE, INITIAL_RATE, UPDATED_RATE),
        (None, INITIAL_RATE, INITIAL_RATE),
        (0.2, INITIAL_RATE, INITIAL_RATE),  # bounded stale-rate mutation control
        (None, 0.0, 0.0),  # zero-rate boundary
    ],
    ids=("updated", "unchanged", "stale-control", "zero-rate"),
)
def test_release_rate_invalidation_ode_matches_piecewise_hazard(
    tmp_path, update, initial_rate, final_rate
):
    trajectory, columns = _run_protocol(
        tmp_path, method="ode", seed=0, update=update, initial_rate=initial_rate
    )
    assert _at(trajectory, columns, 1.0, "f") == pytest.approx(initial_rate)
    assert _at(trajectory, columns, 2.0, "f") == pytest.approx(final_rate)
    for time in (1.0, 2.0):
        expected_a = _analytic_a(time, update=update, initial_rate=initial_rate)
        assert _at(trajectory, columns, time, "A_count") == pytest.approx(
            expected_a, rel=1e-7, abs=1e-9
        )
        assert _at(trajectory, columns, time, "B_count") == pytest.approx(
            INITIAL_A - expected_a, rel=1e-7, abs=1e-9
        )
    if initial_rate == INITIAL_RATE:
        expected, expected_columns = _analytic_ode_trajectory(
            update=final_rate, initial_rate=initial_rate
        )
        difference = compare.compare_trajectories(
            expected,
            expected_columns,
            trajectory,
            columns,
            rtol=1e-6,
            atol=1e-9,
            columns=compare.COLUMNS_EXACT,
        )
        assert difference.ok, difference.summary()


def test_release_rate_invalidation_comparator_rejects_stale_nested_rate(tmp_path):
    stale, stale_columns = _run_protocol(
        tmp_path, method="ode", seed=0, update=INITIAL_RATE
    )
    live_expected, expected_columns = _analytic_ode_trajectory(update=UPDATED_RATE)
    difference = compare.compare_trajectories(
        live_expected,
        expected_columns,
        stale,
        stale_columns,
        rtol=1e-6,
        atol=1e-9,
        columns=compare.COLUMNS_EXACT,
    )
    assert not difference.ok, "stale-rate mutation escaped the trajectory comparator"


def _hoeffding_radius(trials: int) -> float:
    """Two-sided Hoeffding radius with a Bonferroni familywise budget."""
    return math.sqrt(
        math.log(2 * SSA_FAMILYWISE_COMPARISONS / SSA_FAMILYWISE_ALPHA) / (2 * trials)
    )


def _ssa_replicates(
    root: Path,
    *,
    label: str,
    update: float | None,
    initial_rate: float = INITIAL_RATE,
):
    a_at_one = []
    a_at_two = []
    rates_at_one = []
    rates_at_two = []
    for index in range(SSA_RUNS):
        seed = SSA_SEED_BASE + index
        trajectory, columns = _run_protocol(
            root / label / f"run-{index:03d}",
            method="ssa",
            seed=seed,
            update=update,
            initial_rate=initial_rate,
        )
        a_at_one.append(_at(trajectory, columns, 1.0, "A_count"))
        a_at_two.append(_at(trajectory, columns, 2.0, "A_count"))
        rates_at_one.append(_at(trajectory, columns, 1.0, "f"))
        rates_at_two.append(_at(trajectory, columns, 2.0, "f"))
    return (
        np.asarray(a_at_one),
        np.asarray(a_at_two),
        np.asarray(rates_at_one),
        np.asarray(rates_at_two),
    )


def test_release_rates_ssa_distribution_and_stale_mutation_control(
    tmp_path,
):
    # For unary A -> B, the source propensity is A*f. Conditional on the
    # observed A population at t=1, a live f=0.7 gives survivor probability
    # exp(-0.7) over the second interval; a stale f=0.2 gives exp(-0.2).
    # Each sample is one independent trajectory. Across 100 trajectories there
    # are 3,000 molecule-survival Bernoulli trials at each fixed time. The
    # changed-rate endpoint (p=e^-0.9) differs from a stale k=0.2 endpoint
    # (p=e^-0.4) by 0.264, far beyond the familywise Hoeffding radius.
    changed_one, changed_two, changed_rate_before, changed_rate_after = _ssa_replicates(
        tmp_path, label="changed", update=UPDATED_RATE
    )
    changed_p1 = float(changed_one.sum() / (SSA_RUNS * INITIAL_A))
    changed_p2 = float(changed_two.sum() / (SSA_RUNS * INITIAL_A))
    changed_step2_p = float(changed_two.sum() / changed_one.sum())
    assert np.all(changed_rate_before == pytest.approx(INITIAL_RATE))
    assert np.all(changed_rate_after == pytest.approx(UPDATED_RATE))
    assert abs(changed_p1 - math.exp(-INITIAL_RATE)) <= _hoeffding_radius(
        SSA_RUNS * INITIAL_A
    )
    assert abs(changed_step2_p - math.exp(-UPDATED_RATE)) <= _hoeffding_radius(
        int(changed_one.sum())
    )
    assert abs(changed_p2 - math.exp(-(INITIAL_RATE + UPDATED_RATE))) <= (
        _hoeffding_radius(SSA_RUNS * INITIAL_A)
    )

    _unchanged_one, unchanged_two, unchanged_rate_before, unchanged_rate_after = (
        _ssa_replicates(tmp_path, label="unchanged", update=None)
    )
    unchanged_p2 = float(unchanged_two.sum() / (SSA_RUNS * INITIAL_A))
    assert np.all(unchanged_rate_before == pytest.approx(INITIAL_RATE))
    assert np.all(unchanged_rate_after == pytest.approx(INITIAL_RATE))
    assert abs(unchanged_p2 - math.exp(-2 * INITIAL_RATE)) <= _hoeffding_radius(
        SSA_RUNS * INITIAL_A
    )

    zero_one, zero_two, zero_rate_before, zero_rate_after = _ssa_replicates(
        tmp_path, label="zero", update=None, initial_rate=0.0
    )
    assert np.all(zero_one == INITIAL_A)
    assert np.all(zero_two == INITIAL_A)
    assert np.all(zero_rate_before == pytest.approx(0.0))
    assert np.all(zero_rate_after == pytest.approx(0.0))

    _stale_one, stale_two, stale_rate_before, stale_rate_after = _ssa_replicates(
        tmp_path, label="stale", update=INITIAL_RATE
    )
    stale_p2 = float(stale_two.sum() / (SSA_RUNS * INITIAL_A))
    assert np.all(stale_rate_before == pytest.approx(INITIAL_RATE))
    assert np.all(stale_rate_after == pytest.approx(INITIAL_RATE))
    assert abs(stale_p2 - math.exp(-2 * INITIAL_RATE)) <= _hoeffding_radius(
        SSA_RUNS * INITIAL_A
    )
    # Negative control: the same comparator must reject the unchanged-rate
    # trajectory when evaluated against the live k=0.7 source law.
    assert abs(stale_p2 - math.exp(-(INITIAL_RATE + UPDATED_RATE))) > (
        _hoeffding_radius(SSA_RUNS * INITIAL_A)
    )
