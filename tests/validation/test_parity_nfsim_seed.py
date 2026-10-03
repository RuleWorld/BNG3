"""Verification that the NFsim parity evidence is real.

`test_parity_nfsim.py` is the only `tests/validation/` module any CI job runs
(`parity.yml:149,161,167`), so a defect in what it *asserts* is invisible: the
suite would report green either way. This module closes the three gaps that
silence produces, and each check here is written to fail when the thing it
claims to verify is absent.

  1. no silent skip        a parity gate must fail, not skip, when the oracle
                           it names is unavailable under strict mode, and must
                           still skip locally so an unconfigured checkout is
                           usable
  2. seed handling         a fixed seed must produce the same trajectory on
                           both legs, different seeds must produce different
                           ones (a seed that is accepted and ignored is
                           indistinguishable from a seed that works), and the
                           result must hold for every tier-NF model rather
                           than the one the existing gate happens to name
  3. seed-state order      the empty `_KNOWN_SEED_STATE_ORDER_DIVERGENCES`
                           marker is an *assertion* that the AN-family
                           divergence is gone. Only the slow tier-P sweep
                           checks it, and no CI job runs that sweep, so today
                           nothing verifies the marker is honest.

The seed-state-order cases are compared against NATIVE NFsim. The two block
orders in `test_parity_nfsim._SEED_STATE_ORDER_CASES` are semantically
identical BNGL that differ only in the order the atomizer discovers a
pattern-only site state in; `docs/TIER_P_SEED_STATE_ORDER_DIVERGENCE.md`
records the pre-fix measurement (`species_first` reporting the whole seed pool
under `O0`). Pinning those against the independent oracle is what makes the
empty marker a measurement rather than an assumption.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tests.validation import compare, corpus, oracle_nfsim, runner
from tests.validation.strict import require_oracle
from tests.validation.test_parity_nfsim import (
    _SEED_STATE_ORDER_CASES,
    _KNOWN_SEED_STATE_ORDER_DIVERGENCES,
)

# The seed and horizon the existing fixed-seed gate uses, so the two tests
# measure the same thing rather than two unrelated comparisons.
SEED = 7
T_END = 50.0
N_STEPS = 50

# The short horizon the tier-P sweep and the seed-state-order regression use:
# every construction-stage decision is made before the first time step.
SHORT_T_END = 0.1
SHORT_N_STEPS = 10

# The AN family, measured as diverging by the sweep before the seed-species
# fix (docs/TIER_P_SEED_STATE_ORDER_DIVERGENCE.md, `diverged_models`).
AN_FAMILY = ("AN", "ANx", "ANx_noActivity")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _write_xml(source: Path, out_xml: Path) -> Path | None:
    """BNG-XML for an explicit .bngl path.

    `oracle_nfsim.write_model_xml` resolves through the committed corpus, which
    cannot address the two synthetic block-order models. Both sides still start
    from the engine's own XML, so the oracle stays independent of the
    simulation engine it is checking.
    """
    import bionetgen

    if not source.is_file():
        return None
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    bionetgen.load(str(source)).write_xml(str(out_xml))
    return out_xml if out_xml.exists() else None


def _native_trajectory(xml_path: Path, work_dir: Path, *, seed: int, t_end: float,
                       n_steps: int):
    """(data, columns) from native NFsim, or (None, reason)."""
    gdat, error = oracle_nfsim.run_nfsim(
        xml_path, work_dir, t_end=t_end, n_steps=n_steps, seed=seed
    )
    if gdat is None:
        return None, error
    data, columns = compare.parse_gdat(gdat)
    if data is None:
        return None, "native NFsim output could not be parsed"
    return (data, columns), ""


def _trajectory(result) -> tuple:
    """(data, columns) from a bionetgen SimResult: time first, then observables."""
    names = list(result.observables)
    data = np.column_stack(
        [np.asarray(result.time, dtype=float)]
        + [np.asarray(result.observables[name], dtype=float) for name in names]
    )
    return data, ["time", *names]


def _identity_report(left, right) -> str | None:
    """None when the two legs agree exactly on observables; else why they do not.

    Strictly stricter than `compare_trajectories`, which intersects the column
    sets: a leg that silently drops an observable compares clean against the
    leg that still reports it, and a population ceasing to be reported is
    exactly how a seed-handling regression would present. So the observable
    columns must match by identity, in order, and match bit-for-bit in value.

    The time column is deliberately excluded from the bit-for-bit clause. The
    two legs do not compute it the same way -- native NFsim formats and reparses
    `1.00000000e-01`, BNG3 computes `t_end / n_steps` -- so the grid can differ
    in the last bit (measured: `0.1` vs `0.09999999999999999`, a 1.4e-17
    absolute gap) while describing the same 11 sample points. That gap is
    formatting, not behaviour, and the grid is checked separately below at the
    tolerance `compare._align_times` already uses.
    """
    ldata, lcols = left
    rdata, rcols = right
    if lcols != rcols:
        only_left = sorted(set(lcols) - set(rcols))
        only_right = sorted(set(rcols) - set(lcols))
        if only_left or only_right:
            return (
                f"observable columns differ: only on one leg {only_left}, "
                f"only on the other {only_right} (order: {lcols} vs {rcols})"
            )
        return f"observable columns are the same set in a different order: {lcols} vs {rcols}"
    if ldata.shape != rdata.shape:
        return f"shape {ldata.shape} vs {rdata.shape}"
    # Column 0 is time; every column after it is an observable population.
    if not np.array_equal(ldata[:, 1:], rdata[:, 1:]):
        worst = float(np.max(np.abs(ldata[:, 1:] - rdata[:, 1:])))
        return f"observable values differ, max absolute gap {worst:g}"
    if not np.allclose(ldata[:, 0], rdata[:, 0], rtol=0.0, atol=1e-9):
        return f"time grids differ: {ldata[:4, 0]} vs {rdata[:4, 0]}"
    return None


# --------------------------------------------------------------------------- #
# 1. No silent skip
# --------------------------------------------------------------------------- #


def _run_gate(nodeid: str, env_overrides: dict[str, str], tmp_path: Path):
    """Run one parity node in a child pytest and return (proc, stdout+stderr)."""
    env = dict(os.environ)
    env.pop("NFSIM_BIN", None)
    env.pop("BNG3_CI_STRICT_ORACLES", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(corpus.REPO / "python"), str(corpus.REPO)]
    )
    env.update(env_overrides)
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(corpus.REPO / "tests" / "validation" / "pytest.ini"),
        f"{corpus.REPO / 'tests' / 'validation' / 'test_parity_nfsim.py'}::{nodeid}",
        "-q",
        "-p",
        "no:randomly",
    ]
    proc = subprocess.run(
        argv, cwd=str(corpus.REPO), env=env, capture_output=True, text=True,
        timeout=900,
    )
    return proc, proc.stdout + proc.stderr


@pytest.mark.slow
def test_parity_gate_fails_rather_than_skips_when_the_oracle_is_missing(tmp_path):
    """A named parity gate must not report success for having not run.

    `require_oracle` (tests/validation/strict.py) downgrades a missing oracle
    to `pytest.skip` unless `BNG3_CI_STRICT_ORACLES=1`. The oracle-gated node
    is therefore only as good as that flag, and the flag's presence is a
    property of the invoking job rather than of the test. This asserts the
    behaviour on both sides of the switch: strict means failure, non-strict
    means a skip that names the missing oracle, and neither is a pass.
    """
    nodeid = "test_nf_vs_native[simple_system]"

    strict_proc, strict_out = _run_gate(
        nodeid,
        {"BNG3_CI_STRICT_ORACLES": "1", "NFSIM_BIN": str(tmp_path / "absent")},
        tmp_path,
    )
    assert strict_proc.returncode != 0, (
        "strict mode reported success with no native NFsim binary:\n" + strict_out
    )
    assert "passed" not in strict_out, strict_out
    assert "NFsim binary not found" in strict_out, strict_out

    lenient_proc, lenient_out = _run_gate(
        nodeid, {"NFSIM_BIN": str(tmp_path / "absent")}, tmp_path
    )
    assert lenient_proc.returncode == 0, lenient_out
    # A skip is a legitimate local outcome, but it must be a skip and not a
    # silent pass: if this node ever stops consulting require_oracle it will
    # report `passed` here and the assertion below catches it.
    assert "skipped" in lenient_out, lenient_out
    assert "1 passed" not in lenient_out, lenient_out

@pytest.mark.slow
def test_every_oracle_gated_parity_node_is_reachable_under_strict_mode(tmp_path):
    """Each oracle-gated node must fail loudly when its oracle is missing.

    `test_nf_vs_native` and `test_nf_fixed_seed_direct_matches_native_at_final_endpoint`
    are the two nodes `parity.yml` names directly, and they reach the oracle
    through different calls (`oracle_nfsim.nfsim_available()` versus
    `oracle_nfsim.run_nfsim`'s return value). A guard added to only one of them
    is a real and invisible hole, so both are exercised here rather than the
    one that happens to be checked.
    """
    for nodeid in (
        "test_nf_vs_native[simple_system]",
        "test_nf_fixed_seed_direct_matches_native_at_final_endpoint",
    ):
        proc, out = _run_gate(
            nodeid,
            {"BNG3_CI_STRICT_ORACLES": "1", "NFSIM_BIN": str(tmp_path / "absent")},
            tmp_path,
        )
        assert proc.returncode != 0, f"{nodeid} passed without an oracle:\n{out}"
        assert "passed" not in out, out


def test_strict_oracle_flag_is_not_read_from_the_tree_under_test(monkeypatch):
    """`require_oracle` must key on the environment, not on a repo file.

    A `.env`, `conftest` default, or committed fixture that turned strict mode
    on would make the whole gate non-strict while every document still claimed
    it was strict. The flag has exactly one source.
    """
    monkeypatch.delenv("BNG3_CI_STRICT_ORACLES", raising=False)
    with pytest.raises(pytest.skip.Exception):
        require_oracle(False, "probe")
    monkeypatch.setenv("BNG3_CI_STRICT_ORACLES", "0")
    with pytest.raises(pytest.skip.Exception):
        require_oracle(False, "probe")
    monkeypatch.setenv("BNG3_CI_STRICT_ORACLES", "1")
    with pytest.raises(pytest.fail.Exception):
        require_oracle(False, "probe")


# --------------------------------------------------------------------------- #
# 2. Seed handling
# --------------------------------------------------------------------------- #


@pytest.mark.nf
@pytest.mark.parametrize("model_name", list(corpus.tier_nf()))
def test_fixed_seed_reproduces_the_same_trajectory_on_both_legs(
    model_name, api, work_dir
):
    """One seed, one trajectory, on BNG3's direct path and on native NFsim.

    `test_nf_fixed_seed_direct_matches_native_at_final_endpoint` pins
    `simple_system` alone. The other three tier-NF models are named as
    fixed-seed parity targets in `docs/CI_PARITY.md:38` and
    `docs/BNG3_INTEGRATION_PLAN.md:39`, but no test compares them against the
    oracle at a fixed seed, so a seed-handling regression in any of them would
    be reported by nothing. rtol=atol=0: this is a trajectory-identity claim.
    """
    require_oracle(
        oracle_nfsim.nfsim_available(), "native NFsim binary not found (set NFSIM_BIN)"
    )

    direct = runner.run_api(
        model_name, method="nf", seed=SEED, t_end=T_END, n_steps=N_STEPS
    )
    assert direct.construction_path == "direct", (
        f"{model_name} did not run on the direct path: "
        f"{direct.construction_path!r}"
    )

    xml_path = oracle_nfsim.write_model_xml(
        model_name, work_dir / "native" / f"{model_name}.xml"
    )
    require_oracle(xml_path is not None, f"no BNG-XML emitted for {model_name}")
    native, error = _native_trajectory(
        xml_path, work_dir / "native", seed=SEED, t_end=T_END, n_steps=N_STEPS
    )
    require_oracle(native is not None, f"native NFsim produced no output: {error}")

    diff = compare.compare_trajectories(
        native[0],
        native[1],
        direct.data,
        direct.columns,
        rtol=0.0,
        atol=0.0,
        columns=compare.COLUMNS_EXACT,
    )
    assert diff.ok or diff.max_rel_err == 0.0, (
        f"fixed-seed direct/native mismatch [{model_name}]: {diff.summary()}"
    )


@pytest.mark.nf
def test_fixed_seed_is_deterministic_within_bng3(api, work_dir):
    """The same seed twice must be the same trajectory, exactly.

    A seed parameter that is accepted and then ignored still satisfies a
    one-leg determinism check, so both halves are needed: repeat-with-same-seed
    catches a seed that perturbs nothing, and the oracle leg below catches a
    seed that perturbs everything.
    """
    first = runner.run_api(
        "simple_system", method="nf", seed=SEED, t_end=T_END, n_steps=N_STEPS
    )
    second = runner.run_api(
        "simple_system", method="nf", seed=SEED, t_end=T_END, n_steps=N_STEPS
    )
    report = _identity_report(
        (first.data, first.columns), (second.data, second.columns)
    )
    assert report is None, f"the same seed produced two different trajectories: {report}"


@pytest.mark.nf
def test_different_seeds_produce_different_trajectories_on_both_legs(api, work_dir):
    """Seed N+1 must move the result on BNG3 and on native NFsim.

    This is the discriminating half of the seed contract. Without it, an engine
    that ignored the seed entirely would pass every fixed-seed equality check
    above, because both legs would agree on a constant trajectory.
    """
    require_oracle(
        oracle_nfsim.nfsim_available(), "native NFsim binary not found (set NFSIM_BIN)"
    )

    base = runner.run_api(
        "simple_system", method="nf", seed=SEED, t_end=T_END, n_steps=N_STEPS
    )
    other = runner.run_api(
        "simple_system", method="nf", seed=SEED + 1, t_end=T_END, n_steps=N_STEPS
    )
    report = _identity_report((base.data, base.columns), (other.data, other.columns))
    assert report is not None, (
        "seeds 7 and 8 produced identical trajectories; the seed is not consumed"
    )

    xml_path = oracle_nfsim.write_model_xml(
        "simple_system", work_dir / "native" / "simple_system.xml"
    )
    require_oracle(xml_path is not None, "no BNG-XML emitted for simple_system")
    native_base, error_a = _native_trajectory(
        xml_path, work_dir / "native" / f"seed{SEED}",
        seed=SEED, t_end=T_END, n_steps=N_STEPS,
    )
    require_oracle(native_base is not None, f"native NFsim produced no output: {error_a}")
    native_other, error_b = _native_trajectory(
        xml_path, work_dir / "native" / f"seed{SEED + 1}",
        seed=SEED + 1, t_end=T_END, n_steps=N_STEPS,
    )
    require_oracle(native_other is not None, f"native NFsim produced no output: {error_b}")
    native_report = _identity_report(native_base, native_other)
    assert native_report is not None, (
        "native NFsim produced identical trajectories for two different seeds; "
        "the oracle is not varying, so a fixed-seed comparison against it "
        "cannot distinguish agreement from a constant"
    )


# --------------------------------------------------------------------------- #
# 3. Seed-state order, verified rather than assumed
# --------------------------------------------------------------------------- #


@pytest.mark.nf
@pytest.mark.parametrize("block_order", sorted(_SEED_STATE_ORDER_CASES))
def test_seed_state_order_matches_native_nfsim(block_order, api, work_dir, monkeypatch):
    """A pattern-only seed state must be bound by name on every leg.

    The two cases are the same model with the species and observables blocks
    swapped, which changes only the order the atomizer discovers `s~2` in.
    Before the seed-species fix the direct path used that discovery index as an
    NFsim state value, so `species_first` built all 100 molecules in state 0 and
    reported them under `O0` while `observables_first` reported them correctly
    under `O2`. `test_nf_seed_site_state_is_resolved_by_name` compares the two
    BNG3 construction routes, which catches the disagreement but leaves both
    free to be wrong together. Native NFsim is the third leg, and it is the one
    that says which answer is right.
    """
    require_oracle(
        oracle_nfsim.nfsim_available(), "native NFsim binary not found (set NFSIM_BIN)"
    )

    source = work_dir / f"{block_order}.bngl"
    source.write_text(_SEED_STATE_ORDER_CASES[block_order], encoding="utf-8")

    # The direct leg must not be allowed to fall back to in-memory XML, or a
    # decline would silently read as an accepted direct run. `monkeypatch`
    # rather than manual save/restore: it also reverts any pre-existing value,
    # so a caller's environment cannot leak into the leg under test.
    monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)
    monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)
    direct_result = api.load(str(source)).simulate(
        method="nf", seed=SEED, t_end=SHORT_T_END, n_steps=SHORT_N_STEPS
    )
    assert direct_result.construction_path == "direct", (
        "the direct path declined a model the XML path accepts: "
        f"{direct_result.direct_unavailable_reason!r}"
    )
    direct = _trajectory(direct_result)

    xml_path = _write_xml(source, work_dir / f"{block_order}.xml")
    require_oracle(xml_path is not None, f"no BNG-XML emitted for {block_order}")
    native, error = _native_trajectory(
        xml_path,
        work_dir / "native",
        seed=SEED,
        t_end=SHORT_T_END,
        n_steps=SHORT_N_STEPS,
    )
    require_oracle(native is not None, f"native NFsim produced no output: {error}")

    diff = compare.compare_trajectories(
        native[0],
        native[1],
        direct[0],
        direct[1],
        rtol=0.0,
        atol=0.0,
        columns=compare.COLUMNS_EXACT,
    )
    report = _identity_report(native, direct)
    assert report is None, (
        f"seed-state order diverges from native NFsim [{block_order}]: {report}; "
        f"numeric comparator said {diff.summary()}"
    )

    # The seed pool is 100 molecules declared `A(s~2)`, so it belongs under O2
    # and nowhere else. Asserted against the oracle's own output: a shared
    # wrong answer on both BNG3 legs would still pass the comparison above.
    native_final = {
        native[1][i]: float(native[0][-1][i])
        for i in range(len(native[1]))
        if native[1][i] != "time"
    }
    assert native_final["O2"] == 100.0, native_final
    assert native_final["Otot"] == 100.0, native_final
    for name in ("O0", "O1", "O3"):
        assert native_final[name] == 0.0, native_final


@pytest.mark.nf
@pytest.mark.parametrize("model_name", AN_FAMILY)
def test_an_family_seed_state_order_matches_native_nfsim(model_name, api, work_dir):
    """The three models the tier-P sweep measured as diverging must not.

    `_KNOWN_SEED_STATE_ORDER_DIVERGENCES` is empty because the seed-species fix
    removed the divergence, and the sweep enforces that emptiness in both
    directions. But the sweep is `slow` and no CI job runs it -- `parity.yml`
    selects `-m "nf and not slow"`, then two `-k` expressions that name neither
    it nor the sweep -- so nothing in CI currently checks that the marker is
    honest. These are the real models, at the sweep's own seed and horizon,
    compared against the independent oracle.
    """
    require_oracle(
        oracle_nfsim.nfsim_available(), "native NFsim binary not found (set NFSIM_BIN)"
    )
    source = corpus.resolve(model_name)
    require_oracle(source is not None, f"{model_name} is not on disk")

    direct = runner.run_api(
        model_name, method="nf", seed=7, t_end=SHORT_T_END, n_steps=SHORT_N_STEPS
    )
    assert direct.construction_path == "direct", (
        f"{model_name} did not run on the direct path: {direct.construction_path!r}"
    )

    xml_path = oracle_nfsim.write_model_xml(
        model_name, work_dir / "native" / f"{model_name}.xml"
    )
    require_oracle(xml_path is not None, f"no BNG-XML emitted for {model_name}")
    native, error = _native_trajectory(
        xml_path,
        work_dir / "native",
        seed=7,
        t_end=SHORT_T_END,
        n_steps=SHORT_N_STEPS,
    )
    require_oracle(native is not None, f"native NFsim produced no output: {error}")
    diff = compare.compare_trajectories(
        native[0],
        native[1],
        direct.data,
        direct.columns,
        rtol=0.0,
        atol=0.0,
        columns=compare.COLUMNS_EXACT,
    )

    report = _identity_report(native, (direct.data, direct.columns))
    assert report is None, (
        f"{model_name} still diverges from native NFsim at the sweep horizon: "
        f"{report}; numeric comparator said {diff.summary()}"
    )


def test_seed_state_order_marker_list_is_empty_and_the_families_still_run(api):
    """The marker must stay empty, and the families it names must still resolve.

    The empty tuple is the fix's whole evidence (`75b22a7`, per
    `docs/TIER_P_SEED_STATE_ORDER_DIVERGENCE.md`). Asserting it is empty guards
    against someone re-adding a name to silence a regression; asserting the
    models still exist and still load guards against the marker being emptied
    by deleting the models instead. Neither substitutes for the native-oracle
    comparison above -- this is the cheap local half.
    """
    assert _KNOWN_SEED_STATE_ORDER_DIVERGENCES == (), (
        "a seed-state-order divergence is marked known again: "
        + ", ".join(_KNOWN_SEED_STATE_ORDER_DIVERGENCES)
        + ". If this is real, it needs an entry in the sweep report and a "
        "decision, not a silent marker."
    )
    for model_name in AN_FAMILY:
        assert corpus.resolve(model_name) is not None, (
            f"{model_name} was removed from the corpus, which empties the "
            "divergence marker without fixing anything"
        )
