"""The MM rate law's free substrate must be the *root*, not a rounding error.

``MM(kcat, Km)`` on ``S + E -> P + E`` is the self-consistent Michaelis-Menten
law BNG2 defines: the free substrate ``S`` is the positive root of

    S^2 + (Km + Et - St)*S - St*Km = 0,

which is the exact binding equilibrium ``S*E = Km*C`` with ``C = St - S`` and
``E = Et - C``, and the flux is ``kcat*Et*S/(Km + S)``.

Writing ``b = St - Km - Et`` and ``q = sqrt(b*b + 4*St*Km)``, that root is
``0.5*(b + q)``.  When the enzyme is in large excess over substrate, ``b < 0``
and ``|b| >> q``, so ``b + q`` cancels catastrophically: the positive root
collapses towards zero, and at some parameter values it collapses to *exactly*
zero -- which silently zeroes the whole rate law and produces a model that runs
and never converts anything.  BNG2 (``Network3/src/util/misc.cpp``,
``Util::mm_free_substrate``) switches to the algebraically identical
``2*St*Km/(q - b)`` in precisely that case.

The oracle here is a reference trajectory integrated *in the test* from the
60-digit root, so the assertion is "the engine's free substrate is the exact
root", not "the engine agrees with a number someone once recorded".  BNG2 2.9.3
reproduces the same trajectories -- ``test_matches_the_bng2_2_9_3_trajectory``
pins its digits.
"""

from __future__ import annotations

import math
import os
import subprocess
from decimal import Decimal, getcontext
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _bng_cpp() -> str:
    candidate = os.environ.get("BNG_CPP") or str(
        _REPO_ROOT / "build" / "cpp" / "bng_cpp"
    )
    if Path(candidate).exists():
        return candidate
    pytest.skip(f"bng_cpp not available at {candidate}")


def _mm_model(st: float, km: float, et: float, kcat: float, t_end: float) -> str:
    return f"""begin model
begin parameters
  kcat  {kcat}
  Km    {km}
end parameters
begin species
  S()  {st}
  E()  {et}
  P()  0
end species
begin reaction rules
  S() + E() -> P() + E() MM(kcat,Km)
end reaction rules
begin observables
  Molecules St S()
  Molecules Pt P()
end observables
end model

begin actions
  generate_network({{overwrite=>1}})
  simulate({{method=>"ode",t_start=>0,t_end=>{t_end},n_steps=>500,\
atol=>1e-12,rtol=>1e-12}})
end actions
"""


def _simulate(
    tmp_path: Path, st: float, km: float, et: float, kcat: float, t_end: float
) -> list[list[float]]:
    """Rows of [time, St, Pt], including the t=0 seed row."""
    executable = _bng_cpp()
    path = tmp_path / f"mm_{st:g}_{km:g}_{et:g}_{t_end:g}.bngl"
    path.write_text(_mm_model(st, km, et, kcat, t_end))
    subprocess.run([executable, path.name], cwd=tmp_path, check=True,
                   capture_output=True)
    gdat = tmp_path / f"{path.stem}.gdat"
    assert gdat.exists(), sorted(p.name for p in tmp_path.iterdir())
    return [
        [float(x) for x in line.split()]
        for line in gdat.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _row_at(rows: list[list[float]], t: float) -> list[float]:
    matches = [row for row in rows if abs(row[0] - t) < 1e-9]
    assert len(matches) == 1, (t, [row[0] for row in rows])
    return matches[0]


def exact_free_substrate(st: float, km: float, et: float) -> float:
    """60-digit positive root of S^2 + (Km + Et - St)*S - St*Km = 0."""
    getcontext().prec = 60
    b = Decimal(repr(km)) + Decimal(repr(et)) - Decimal(repr(st))
    disc = b * b + 4 * Decimal(repr(st)) * Decimal(repr(km))
    return float((-b + disc.sqrt()) / 2)


def reference_trajectory(
    st: float, km: float, et: float, kcat: float, t_end: float,
    steps: int = 20000,
) -> tuple[float, float]:
    """RK4 on dSt/dt = -v(St), dPt/dt = v(St) with v built from the exact root.

    E is a catalyst, so Et is constant.  This is the trajectory the model
    encodes *if* the free substrate the rate law uses is the root above.
    Returns (St(t_end), Pt(t_end)).
    """

    def flux(total_substrate: float) -> float:
        root = exact_free_substrate(total_substrate, km, et)
        return kcat * et * root / (km + root)

    h = t_end / steps
    s, p = st, 0.0
    for _ in range(steps):
        k1 = flux(s)
        k2 = flux(s - 0.5 * h * k1)
        k3 = flux(s - 0.5 * h * k2)
        k4 = flux(s - h * k3)
        dp = h / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
        s -= dp
        p += dp
    return s, p


# --------------------------------------------------------------------------
# The defect: enzyme in large enough excess that b + q cancels to exactly zero.
# --------------------------------------------------------------------------


def test_enzyme_in_huge_excess_does_not_silently_stop_turning_over_substrate(
    tmp_path,
):
    # Before the fix the free substrate came out as exactly 0.0 here, so the
    # rate law was identically zero and Pt stayed at its seed for every output
    # step of a model that reported a normal-looking trajectory.
    st, km, et, kcat, t_end = 10.0, 1.0, 1e10, 1.0, 1.0
    rows = _simulate(tmp_path, st, km, et, kcat, t_end)

    assert rows[0] == [0.0, st, 0.0]
    assert _row_at(rows, 0.5)[1] == pytest.approx(6.065306597445e00, abs=5e-9)
    assert rows[-1][1] == pytest.approx(st * math.exp(-kcat * t_end), rel=1e-8)
    assert rows[-1][2] == pytest.approx(6.321205587887e00, abs=5e-8)


def test_enzyme_in_large_excess_keeps_the_exact_binding_equilibrium_rate(
    tmp_path,
):
    # b = St - Km - Et = -1e8 and |b| >> sqrt(4*St*Km) = 2.  The pre-fix
    # quadratic returned 7.45e-9 where the root is 1e-8, i.e. 25.5% low, which
    # made the whole flux 25% slow for the entire run.
    st, km, et, kcat, t_end = 1.0, 1.0, 1e8, 1.0, 0.5
    rows = _simulate(tmp_path, st, km, et, kcat, t_end)

    assert _row_at(rows, 0.5)[1] == pytest.approx(0.6065306627457, abs=5e-10)
    assert _row_at(rows, 0.5)[2] == pytest.approx(0.3934693372543, abs=5e-10)
    assert rows[-1][1] == pytest.approx(st * math.exp(-kcat * t_end), rel=1e-8)
    # The seed is not evidence; the flux has to have integrated.
    assert rows[-1][2] > 0.39


# (St, Km, Et) spanning both branches of the quadratic, the two that collapsed
# to exactly 0.0 before the fix, and two well-conditioned cases that must be
# unchanged by it.
@pytest.mark.parametrize(
    "st, km, et",
    [
        (1.0, 1.0, 1e4),
        (1.0, 1.0, 1e6),
        (1.0, 1.0, 1e8),
        (1e-3, 1.0, 1e8),
        (1000.0, 1.0, 1e9),
        (10.0, 1.0, 1e10),
        (100.0, 1.0, 50.0),
        (100.0, 1.0, 100.0),
    ],
)
def test_the_rate_law_uses_the_exact_root_of_the_binding_equilibrium(
    st, km, et, tmp_path
):
    # The claim is about the state the rate law produces, so it is asserted on
    # St rather than on Pt: over this window Pt is ~1e-3 of St, so the ODE
    # solver's own accumulated error at rtol=1e-12 would otherwise dominate
    # the comparison.  The worst agreement measured over these eight parameter
    # sets is 1.1e-11 relative, so 1e-9 is the solver's bound with two orders
    # of margin, and it still rejects the pre-fix behaviour decisively: the
    # flux was 25% low for (1, 1, 1e8) and identically zero for (1e-3, 1,
    # 1e8) and (10, 1, 1e10).
    t_end = 1e-3
    rows = _simulate(tmp_path, st, km, et, 1.0, t_end)
    expected_st, expected_pt = reference_trajectory(st, km, et, 1.0, t_end)

    assert rows[-1][1] == pytest.approx(expected_st, rel=1e-9)
    # The product carries the same absolute error as the substrate total.
    assert rows[-1][2] == pytest.approx(expected_pt, abs=1e-8)
    assert rows[-1][2] > 0.0


# --------------------------------------------------------------------------
# Parity with the reference implementation.
# --------------------------------------------------------------------------


def test_matches_the_bng2_2_9_3_trajectory(tmp_path):
    # BNG2 2.9.3, run as
    #   perl ~/Documents/BioNetGen/bionetgen/bionetgen/bng2/BNG2.pl mm.bngl
    # on the same model, wrote St = 6.065306597445e+00 at t=0.5 and
    # 3.678794412113e+00 at t=1.0 for (St, Km, Et) = (10, 1, 1e10).
    st, km, et, kcat = 10.0, 1.0, 1e10, 1.0
    rows = _simulate(tmp_path, st, km, et, kcat, 1.0)

    assert _row_at(rows, 0.5)[1] == pytest.approx(6.065306597445e00, abs=5e-10)
    assert _row_at(rows, 0.5)[2] == pytest.approx(3.934693402555e00, abs=5e-10)
    assert rows[-1][1] == pytest.approx(3.678794412113e00, abs=5e-10)
    assert rows[-1][2] == pytest.approx(6.321205587887e00, abs=5e-10)
    # 10*exp(-0.5) is 6.065306597126; the 3.2e-10 gap is the O(St/Et) the
    # leading-order closed form drops, not solver error.
    assert _row_at(rows, 0.5)[1] == pytest.approx(10.0 * math.exp(-0.5), rel=1e-9)
