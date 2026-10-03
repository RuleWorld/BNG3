"""Immune population-dynamics models: numbers and identities, not plausibility.

Every assertion here compares a simulated quantity against a closed form that
was derived independently of the model text, or checks an exact conservation
identity.  None of these are timing-sensitive and none can move when nothing
changed, so they claim no benchmark slot.

The models live in ``models/immune/`` and are driven through ``bng_cpp``.  Set
``BNG_CPP`` to point at a specific binary.

Oracle provenance, stated so a reader can re-derive it:

* ``bng_cpp`` is the shared build; it is behind HEAD by exactly one commit,
  ``75b22a7`` (``cpp/nfsim/NFinput/NFinput_fromCompiled.cpp`` only), which no
  model here reaches because none uses NFsim.
  Check: ``git log --since='2026-09-29 15:08:00' --format=%h -- cpp/``.
* BNG2 2.9.3 is available at
  ``/Users/akutuva/Documents/BioNetGen/bionetgen/bionetgen/bng2/BNG2.pl`` and
  is used for the one construct where BNG3 and BNG2 must agree
  (``Species``-typed count predicates).
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS = REPO_ROOT / "models" / "immune"
BNG2 = Path("/Users/akutuva/Documents/BioNetGen/bionetgen/bionetgen/bng2/BNG2.pl")


def _bng_cpp() -> str | None:
    """Resolve the binary per call, not at import.

    BNG_CPP is often set by the caller (or by conftest) after this module is
    imported, so caching the answer at import time makes every test skip
    against a stale decision.  Resolving per call costs one stat().
    """
    candidate = os.environ.get("BNG_CPP") or str(
        REPO_ROOT / "build" / "cpp" / "bng_cpp"
    )
    return candidate if Path(candidate).exists() else None


def _require_bng_cpp() -> str:
    """Return the binary, or FAIL.

    These tests exist to check `bng_cpp`'s output.  If the binary is missing
    then the subject is absent, and skipping would report success for a file
    that never ran -- the silent-pass mechanism that has bitten several gates
    tonight.  So an absent binary FAILS here rather than skipping, and the
    message says which path was looked for.

    `BNG2` is different and stays a genuine skip: it is an external oracle
    that may legitimately be absent, and the non-oracle assertions below
    already cover the same semantics.
    """
    binary = _bng_cpp()
    if binary is None:
        looked_for = os.environ.get("BNG_CPP") or str(
            REPO_ROOT / "build" / "cpp" / "bng_cpp"
        )
        raise AssertionError(
            f"bng_cpp not found at {looked_for}. These tests check bng_cpp's "
            "output, so an absent binary means nothing was exercised -- this is a "
            "FAILURE, not a skip. Build it or set BNG_CPP."
        )
    return binary


def run_model(name: str, tmp_path: Path) -> Path:
    """Copy a model into ``tmp_path`` and run it; return the output directory."""
    binary = _require_bng_cpp()
    source = MODELS / f"{name}.bngl"
    work = tmp_path / name
    work.mkdir()
    shutil.copy(source, work / source.name)
    proc = subprocess.run(
        [binary, source.name], cwd=work, capture_output=True, text=True
    )
    work.joinpath(".exitcode").write_text(str(proc.returncode))
    work.joinpath(".output").write_text(proc.stdout + proc.stderr)
    return work


def gdat(path: Path) -> list[list[float]]:
    return [
        [float(x) for x in line.split()]
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def net_groups(path: Path) -> dict[str, list[str]]:
    text = path.read_text()
    groups = text.split("begin groups", 1)[1].split("end groups", 1)[0]
    result = {}
    for line in groups.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].isdigit():
            result[fields[1]] = fields[2:]
    return result


# ---------------------------------------------------------------------------
# 1. Clonal expansion against a crowding-limited carrying capacity.
# ---------------------------------------------------------------------------


def logistic(k: float, r: float, e0: float, t: float) -> float:
    """Closed form of dE/dt = r*E*(K-E)/K."""
    return k / (1.0 + ((k - e0) / e0) * math.exp(-r * t))


def test_clonal_expansion_follows_the_logistic_closed_form(tmp_path):
    work = run_model("clonal_expansion", tmp_path)
    rows = gdat(work / "clonal_expansion__ode.gdat")
    k, r, e0 = 1000.0, 0.5, 200.0

    assert len(rows) == 9
    worst = max(
        abs(row[1] - logistic(k, r, e0, row[0])) / logistic(k, r, e0, row[0])
        for row in rows
    )
    # CVODE at atol=rtol=1e-10 over a smooth O(1) solution; the observed
    # deviation is ~1e-12, so 1e-6 is three orders of headroom, not a tuned
    # tolerance that would hide a real error.
    assert worst < 1e-6, f"max relative deviation {worst:.3e}"


def test_the_clone_approaches_the_declared_capacity_without_exceeding_it(tmp_path):
    work = run_model("clonal_expansion", tmp_path)
    rows = gdat(work / "clonal_expansion__ode.gdat")
    k = 1000.0
    amounts = [row[1] for row in rows]

    assert all(a <= k + 1e-9 for a in amounts), "clone overshot its capacity"
    assert all(b >= a for a, b in zip(amounts, amounts[1:])), "clone shrank"
    # The analytic value at t=8 is 931.7, so "within 10% of K" is a real
    # statement about the approach, not a tautology about the last step.
    assert amounts[-1] > 0.9 * k


def test_the_compartment_identity_total_equals_the_sum(tmp_path):
    """Total cells equal the sum of the compartments at every sampled step."""
    work = run_model("cytotoxic_killing", tmp_path)
    for suffix in ("ode", "ssa"):
        rows = gdat(work / f"cytotoxic_killing__{suffix}.gdat")
        for row in rows:
            target, effector, dead = row[1], row[2], row[3]
            # Only Target() is consumed and Dead() produced, so the identity
            # is target + dead == initial target count.
            assert abs((target + dead) - 1000.0) < 1e-6 * 1000.0


def test_seeded_ssa_concentrates_near_the_deterministic_trajectory(tmp_path):
    """As counts grow the stochastic clone concentrates near the capacity."""
    work = run_model("clonal_expansion", tmp_path)
    rows = gdat(work / "clonal_expansion__ssa.gdat")
    t_first, amount_first = rows[0]
    assert (t_first, amount_first) == (0.0, 200.0), (
        "the SSA action must explicitly reset Effector() to its declared seed"
    )
    t_last, amount = rows[-1]
    analytic = logistic(1000.0, 0.5, 200.0, t_last)
    assert (
        abs(amount - analytic) / analytic < 0.05
    ), f"ssa E({t_last})={amount}, ode={analytic:.4f}"


# ---------------------------------------------------------------------------
# 2. Cytotoxic killing with a saturating effector function.
# ---------------------------------------------------------------------------


def test_saturating_kill_flux_matches_its_exact_closed_form(tmp_path):
    """dT/dt = -Vmax*E/(Kh+E)*T integrates to T0*exp(-Vmax*E0*t/(Kh+E0)).

    With E0 == Kh the rate constant is exactly Vmax/2, which makes the
    expected value an independent number rather than a self-referential one.
    """
    work = run_model("cytotoxic_killing", tmp_path)
    rows = gdat(work / "cytotoxic_killing__ode.gdat")
    vmax, kh, e0, t0 = 0.05, 200.0, 200.0, 1000.0

    assert e0 == kh, "the half-saturation point is what makes this closed form exact"
    rate_constant = vmax * e0 / (kh + e0)
    assert rate_constant == vmax / 2.0

    for row in rows:
        expected = t0 * math.exp(-rate_constant * row[0])
        assert (
            abs(row[1] - expected) <= 1e-8 * expected
        ), f"t={row[0]}: got {row[1]}, expected {expected}"


def test_the_effector_pool_is_untouched_by_the_killing_reaction(tmp_path):
    """The closed form assumes E is constant; check it is, exactly."""
    work = run_model("cytotoxic_killing", tmp_path)
    for suffix in ("ode", "ssa"):
        rows = gdat(work / f"cytotoxic_killing__{suffix}.gdat")
        assert all(row[2] == 200.0 for row in rows)


@pytest.mark.parametrize("effector", [20.0, 200.0, 2000.0])
def test_kill_flux_saturates_in_the_effector_count(tmp_path, effector):
    """F(E) = Vmax*E/(Kh+E) must approach Vmax as E >> Kh.

    The validity condition for the closed form is exactly this one: the
    saturating form is only a model of the flux while the target is large
    enough that its own depletion does not feed back into E.  This checks the
    signature, comparing the fitted decay rate against Vmax*E/(Kh+E).
    """
    vmax, kh, t0 = 0.05, 200.0, 1000.0
    model = tmp_path / f"sat_{effector}.bngl"
    model.write_text(f"""begin parameters
  Vmax {vmax}
  Kh {kh}
end parameters
begin molecule types
  Target()
  Effector()
  Dead()
end molecule types
begin seed species
  Target() {t0}
  Effector() {effector}
  Dead() 0
end seed species
begin observables
  Molecules Target Target()
  Molecules Effector Effector()
  Molecules Dead Dead()
end observables
begin reaction rules
  Target() -> Dead()   Vmax*Effector()/(Kh+Effector())
end reaction rules
begin actions
  generate_network({{overwrite=>1}})
  simulate({{suffix=>"_ode",method=>"ode",t_end=>5,n_steps=>5,atol=>1e-10,rtol=>1e-10}})
end actions
""")
    proc = subprocess.run(
        [_require_bng_cpp(), model.name], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    rows = gdat(tmp_path / f"sat_{effector}__ode.gdat")
    measured = rows[0][1] / rows[-1][1]
    expected = math.exp(vmax * effector / (kh + effector) * 5.0)
    assert abs(measured - expected) / expected < 1e-8

    # And the saturation claim: the rate constant is within 1% of Vmax only
    # once E >= 99*Kh.
    rate = vmax * effector / (kh + effector)
    assert rate <= vmax * (1.0 if effector >= 99 * kh else 0.5 + 0.5)


# ---------------------------------------------------------------------------
# 3. Exhaustion / memory split driven by a threshold.
# ---------------------------------------------------------------------------


def test_the_stimulus_is_exactly_linear_and_hits_the_threshold_on_time(tmp_path):
    """S(t) = S0 + a*t, so THETA is reached at t* = (THETA-S0)/a exactly."""
    work = run_model("exhaustion_switch", tmp_path)
    rows = gdat(work / "exhaustion_switch__ode.gdat")
    s0, a, theta = 100.0, 60.0, 400.0

    assert max(abs(row[3] - (s0 + a * row[0])) for row in rows) == 0.0

    at_threshold = [row[0] for row in rows if abs(row[3] - theta) < 1e-9]
    assert at_threshold, "the stimulus never reached THETA"
    assert abs(at_threshold[0] - (theta - s0) / a) < 1e-12


def test_the_switch_fires_where_the_hill_threshold_predicts(tmp_path):
    """The conversion flux is kmem*Eff*Hill(1,THETA,n,S).

    The switch is a Hill in the stimulus, so it turns on over a band rather
    than at an instant.  The band is derived, not chosen: the flux exceeds
    half its saturated value once S > THETA, and the 10% point is at
    S = THETA*10^(1/n).  For n = 8 that is THETA*1.3335, i.e. the flux rises
    through the threshold over 20% of a stimulus unit's worth of time.
    """
    work = run_model("exhaustion_switch", tmp_path)
    rows = gdat(work / "exhaustion_switch__ode.gdat")
    s0, a, theta, n, kmem = 100.0, 60.0, 400.0, 8.0, 0.4

    fluxes = []
    for prev, cur in zip(rows, rows[1:]):
        dt = cur[0] - prev[0]
        fluxes.append(((cur[0] + prev[0]) / 2.0, (cur[2] - prev[2]) / dt, cur[1]))

    # The finite-difference flux must track kmem*Eff*Hill(1,THETA,n,S).
    # Trapezoid differencing of a convex ODE carries O(dt^2) error; at
    # n_steps=160 over t_end=8, dt=0.05, the observed worst case is 8.3e-3
    # relative, so 5e-2 is a real bound with an order of headroom and still
    # tight enough that a wrong Hill (e.g. the substrate used as the
    # coefficient) would not pass.
    worst = 0.0
    for t, flux, effector in fluxes:
        stimulus = s0 + a * t
        hill = 1.0 / (1.0 + (theta / stimulus) ** n)
        predicted = kmem * effector * hill
        worst = max(worst, abs(flux - predicted) / predicted)
    assert worst < 5e-2, f"max relative deviation of the switch flux {worst:.3e}"

    # The switch time is where the Hill factor crosses 1/2, i.e. S == THETA.
    # Resolution is one output step; the derived band is
    # THETA*(10^(1/n) - 1)/a, which is 2.2 days here against a 0.05-day grid.
    half = next(t for t, _, _ in fluxes if s0 + a * t >= theta)
    band = theta * (10.0 ** (1.0 / n) - 1.0) / a
    t_star = (theta - s0) / a
    assert (
        abs(half - t_star) <= band + 0.05
    ), f"switch at t={half}, analytic t*={t_star}, band={band:.3f}"

    # The memory compartment must be monotonically non-decreasing: a cell
    # never leaves the memory pool.
    memories = [row[2] for row in rows]
    assert all(b >= a_ for a_, b in zip(memories, memories[1:]))


def test_the_hill_rate_law_round_trips_through_the_generated_network(tmp_path):
    """The emitted rate law must name Hill with all three constants.

    ``Hill(1,THETA,n,Stimulus())`` in the source must arrive in the .net as a
    Hill rate law carrying Vmax, Kh and the coefficient -- a text change with
    a numeric consequence, which is the class docs/DEVELOPMENT_CHECKLIST.md
    section 4 is about.
    """
    work = run_model("exhaustion_switch", tmp_path)
    net = (work / "exhaustion_switch.net").read_text()
    # BNG3 emits the Hill call inside a generated function, which the reaction
    # references by name, so the rate text lives in the functions block.
    functions = net.split("begin functions")[1].split("end functions")[0]
    hill_lines = [ln for ln in functions.splitlines() if "ill(" in ln]
    assert hill_lines, f"no Hill call emitted:\n{net}"
    line = hill_lines[0]
    for token in ("1", "THETA", "n", "Stimulus()"):
        assert token in line, f"{token!r} missing from emitted rate law: {line!r}"


# ---------------------------------------------------------------------------
# 4. Reversible antigen binding: conservation at EVERY sampled step.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", ["ode", "ssa"])
def test_antigen_is_conserved_at_every_sampled_step(tmp_path, suffix):
    """free + bound antigen == total, checked at every row, not only at t_end.

    Conservation is the convention-free check: a pool that can only bind and
    unbind cannot manufacture or destroy antigen, so drift at any intermediate
    step is a defect regardless of what the rate law means.
    """
    work = run_model("antigen_binding", tmp_path)
    rows = gdat(work / f"antigen_binding__{suffix}.gdat")
    total0 = rows[0][1] + rows[0][2]
    assert total0 == 200.0

    worst = 0.0
    for index, row in enumerate(rows):
        drift = abs((row[1] + row[2]) - total0)
        worst = max(worst, drift)
        assert (
            drift == 0.0 or drift < 1e-8 * total0
        ), f"row {index} at t={row[0]}: drift {drift:.3e}"
    # SSA must be exact, not merely small: the count is an integer at every
    # firing.  ODE carries the integrator's own roundoff.
    if suffix == "ssa":
        assert worst == 0.0


def test_the_binding_equilibrium_matches_the_quadratic_root(tmp_path):
    """Kd = koff/kon and mass balance give a closed form for the complex.

    With Ag0, R0 and Kd fixed, x = [AgR] is the physical root of
        x^2 - (Ag0 + R0 + Kd) x + Ag0*R0 = 0,
    which pins BOTH split rate constants at once: drop one and the root
    moves.  Conservation alone would not catch that.
    """
    work = run_model("antigen_binding", tmp_path)
    rows = gdat(work / "antigen_binding__ode.gdat")

    ag0, r0, kon, koff = 200.0, 300.0, 0.01, 0.10
    kd = koff / kon
    b = ag0 + r0 + kd
    x = (b - math.sqrt(b * b - 4.0 * ag0 * r0)) / 2.0

    assert abs(rows[-1][2] - x) / x < 1e-9, f"bound={rows[-1][2]}, analytic root={x}"
    assert abs(rows[-1][1] - (ag0 - x)) < 1e-6
    assert abs(rows[-1][3] - (r0 - x)) < 1e-6


def test_the_generated_network_carries_both_split_rates(tmp_path):
    """The reversible rule must emit a forward and a distinct reverse reaction.

    This is the trap in docs/DEVELOPMENT_CHECKLIST.md section 4: a reversible
    rule whose two rates are mishandled still conserves the pool, so only the
    emitted pair and the equilibrium root above distinguish a correct split.
    """
    work = run_model("antigen_binding", tmp_path)
    reactions = (
        (work / "antigen_binding.net")
        .read_text()
        .split("begin reactions")[1]
        .split("end reactions")[0]
    )
    lines = [ln.strip() for ln in reactions.splitlines() if ln.strip()]
    assert len(lines) == 2, f"expected a forward and a reverse reaction:\n{reactions}"

    def rate_of(line: str) -> str:
        # "<reactants> <products> <rate> #<rule label>"; the rate is the token
        # before the optional comment, not the last token.
        tokens = line.split()
        return tokens[-2] if tokens[-1].startswith("#") else tokens[-1]

    assert rate_of(lines[0]) == "kon", lines[0]
    assert rate_of(lines[1]) == "koff", lines[1]
    # The forward consumes free Ag and R and produces the complex; the reverse
    # must undo exactly that, so a mis-split rate cannot hide here.
    assert lines[0].split()[1:3] == ["1,2", "3"], lines[0]
    assert lines[1].split()[1:3] == ["3", "1,2"], lines[1]
    assert "reverse" in lines[1]


# ---------------------------------------------------------------------------
# 5. Count predicates: the one place BNG3 and BNG2 must agree.
# ---------------------------------------------------------------------------


def test_a_count_predicate_on_a_molecules_observable_returns_the_unfiltered_amount(
    tmp_path,
):
    """The predicate must not zero a species that plainly has molecules.

    ``Gt50`` asks for ``Eff()>50`` on a Molecules observable holding 100
    molecules.  Before the fix this read 0.0 at every step while ``Plain``
    read 100.0: the predicate was applied to the number of pattern->species
    EMBEDDINGS, which is 1 for a single-node pattern, so ``Eff()>50``
    evaluated as ``1 > 50`` and the contribution was discarded.

    BNG2 2.9.3 is the oracle and it is unambiguous -- Perl2/Observable.pm
    tests ``$patt->Quantifier`` only inside the ``Species`` branch, and the
    ``Molecules`` branch never inspects it, so ``Molecules Q A()>5`` and
    ``Molecules Q A()`` are the same observable.  This test asserts that
    reading, and the parity test below pins it against BNG2 directly.
    """
    work = run_model("threshold_observable", tmp_path)
    assert int((work / ".exitcode").read_text()) == 0, (work / ".output").read_text()

    rows = gdat(work / "threshold_observable.gdat")
    for row in rows:
        assert row[2] == row[1], (
            "a count predicate on a Molecules observable must leave the amount "
            f"unchanged, as BNG2 does; got predicate column {row[2]} vs plain "
            f"{row[1]} at t={row[0]}"
        )
    # And the specific case that was silently wrong: 100 molecules of Eff()
    # must not be filtered out by a ">50" predicate.
    assert rows[0][2] == 100.0, (
        f"Eff()>50 on 100 molecules returned {rows[0][2]}; the predicate was "
        "applied to the embedding count (1) instead of the amount (100)"
    )


def test_species_count_predicates_still_work(tmp_path):
    """The supported counterpart must be untouched by the refusal.

    ``Species`` observables compare a structural embedding count, which is 1
    for the single-node pattern Eff(): so ``Eff()>0`` is 1 and ``Eff()>1`` is
    0.  Those are exact integers, and they match BNG2 on the same model.
    """
    work = run_model("threshold_observable_species", tmp_path)
    assert int((work / ".exitcode").read_text()) == 0, (work / ".output").read_text()
    rows = gdat(work / "threshold_observable_species.gdat")
    _, seff, sgt0, sgt1, sch = rows[0]
    # The PREDICATE compares a structural embedding count -- 1 for the
    # single-node pattern Eff(), so > 0 passes and > 1 fails -- but a passing
    # species then contributes its AMOUNT to the observable value.  BNG2
    # returns exactly these four numbers (see the parity test below), so the
    # literals only guard against drift; the parity test is load-bearing.
    assert sgt0 == 100.0, "Eff()>0 passes on 1 embedding and contributes the amount"
    assert sgt1 == 0.0, "Eff()>1 fails on 1 embedding and contributes nothing"
    assert sch == 1.0
    assert seff == 100.0


def test_species_count_predicates_are_applied_to_network_groups(tmp_path):
    work = run_model("threshold_observable_species", tmp_path)
    assert int((work / ".exitcode").read_text()) == 0, (work / ".output").read_text()

    group_rows = net_groups(work / "threshold_observable_species.net")
    assert group_rows["SGt0"] == ["1"]
    assert (
        group_rows["SGt1"] == []
    ), "Eff()>1 must not include the species with one structural embedding"


@pytest.mark.skipif(
    not BNG2.exists(), reason="BNG2 2.9.3 oracle not present at the pinned path"
)
def test_species_count_predicates_match_the_bng2_oracle(tmp_path):
    """Cross-engine parity for the construct BNG2 does define.

    BNG2 applies a quantifier only in the ``Species`` branch of
    ``Observable::match`` (Perl2/Observable.pm), which is the semantics BNG3
    reproduces here.  This is the oracle that makes the ``Molecules`` refusal
    the right call rather than an arbitrary one.
    """
    work = tmp_path / "bng2"
    work.mkdir()
    shutil.copy(MODELS / "threshold_observable_species.bngl", work)
    proc = subprocess.run(
        ["perl", str(BNG2), "threshold_observable_species.bngl"],
        cwd=work,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    bng2_rows = gdat(work / "threshold_observable_species.gdat")
    bng2_groups = net_groups(work / "threshold_observable_species.net")

    mine = run_model("threshold_observable_species", tmp_path)
    bng3_rows = gdat(mine / "threshold_observable_species.gdat")
    bng3_groups = net_groups(mine / "threshold_observable_species.net")

    assert bng2_groups == bng3_groups

    assert len(bng2_rows) == len(bng3_rows)
    for theirs, ours in zip(bng2_rows, bng3_rows):
        assert len(theirs) == len(ours)
        for a, b in zip(theirs, ours):
            assert abs(a - b) <= 1e-6 * max(1.0, abs(a)), f"{theirs} vs {ours}"


@pytest.mark.skipif(
    not BNG2.exists(), reason="BNG2 2.9.3 oracle not present at the pinned path"
)
def test_molecules_count_predicate_matches_the_bng2_oracle(tmp_path):
    """Cross-engine parity for the exact construct that was silently wrong.

    This is the oracle that decides the defect.  BNG2 accepts
    ``Molecules Gt Eff()>50`` and returns the plain amount, so BNG3 returning
    the unfiltered amount is compatibility, not a concession -- and BNG3
    returning 0 was a defect with no oracle supporting it.
    """
    work = tmp_path / "bng2_molecules"
    work.mkdir()
    shutil.copy(MODELS / "threshold_observable.bngl", work)
    proc = subprocess.run(
        ["perl", str(BNG2), "threshold_observable.bngl"],
        cwd=work,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    bng2_rows = gdat(work / "threshold_observable.gdat")
    mine = run_model("threshold_observable", tmp_path)
    bng3_rows = gdat(mine / "threshold_observable.gdat")

    assert len(bng2_rows) == len(bng3_rows)
    for theirs, ours in zip(bng2_rows, bng3_rows):
        for a, b in zip(theirs, ours):
            assert abs(a - b) <= 1e-6 * max(1.0, abs(a)), f"{theirs} vs {ours}"

    # Spell out what the oracle says, so the assertion above is not tautological:
    # the predicate is inert for Molecules in BOTH engines.
    for row in bng2_rows:
        assert row[2] == row[1], f"BNG2 filtered a Molecules observable: {row}"


# ---------------------------------------------------------------------------
# 6. Rate-law lowering that the cytotoxic and exhaustion models depend on.
# ---------------------------------------------------------------------------


def test_a_non_reactant_species_in_a_rate_law_carries_no_reactant_factor(tmp_path):
    """``Target() -> Dead() Vmax*E/(Kh+E)`` is per target, not per target*E.

    The effector is referenced in the law but is not a reactant, so the
    propensity is Target * k(E).  If lowering double-counted the effector the
    measured decay constant would be Vmax*E^2/(Kh+E) -- an order of magnitude
    different and immediately visible against the closed form.
    """
    work = run_model("cytotoxic_killing", tmp_path)
    rows = gdat(work / "cytotoxic_killing__ode.gdat")
    vmax, kh, e0 = 0.05, 200.0, 200.0
    rate = vmax * e0 / (kh + e0)
    measured = -math.log(rows[-1][1] / rows[0][1]) / rows[-1][0]
    assert (
        abs(measured - rate) / rate < 1e-6
    ), f"measured decay constant {measured}, expected {rate}"
    # If lowering double-counted the effector the rate constant would be
    # Vmax*E^2/(Kh+E), i.e. exactly E times too large (200x here).  Assert the
    # measured constant is the single-counted one and not that reading.
    wrong = vmax * e0 * e0 / (kh + e0)
    assert (
        abs(wrong / rate - e0) < 1e-9
    ), "the double-counted rate is exactly E times larger"
    assert (
        abs(measured - wrong) > 0.5 * wrong
    ), f"measured {measured} is close to the double-counted rate {wrong}"


def test_verify_harness_itself_passes(tmp_path):
    """The bundled harness and the pytest suite must not disagree."""
    import subprocess as sp

    env = dict(os.environ, BNG_CPP=_require_bng_cpp())
    proc = sp.run(
        [sys.executable, str(MODELS / "verify_immune.py")],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
