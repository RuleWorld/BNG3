"""Epidemiology, predator-prey and ion-channel dynamics: analytic identities.

Every model here is hand-authored for this file (the repository ships no
epidemic, Lotka-Volterra or Hodgkin-Huxley-style model).  Each test pins a
quantity that is fixed by the model in closed form -- a conservation law, a
stability threshold, a first integral, a time constant, or the moments of an
exact offspring distribution -- so a change that silently turns one of these
mechanisms into a different one fails here rather than producing a
plausible-but-wrong trajectory.

The stochastic cases are the deterministic/stochastic boundary: a population
of two-state Markov units is *binomial*, not Poisson, and a Markovian
continuous-time infector has *geometric*, not Poisson, offspring.  Both facts
have exact variance-to-mean ratios, so a silent Poisson substitution would move
the measured ratio by a factor of five.

BNGL spelling notes, both verified against the BNG2 oracle in
``~/Documents/BioNetGen/bionetgen``:

* ``2I()`` is rejected by both BNG3 and BNG2 ("Invalid Molecule name in
  '2I()'"), so the doubled reactant is written ``I() + I()``.
* Observable patterns carry no expression, so ``O(s~o)/Nch`` is rejected by
  both; the open fraction is computed from the count in the test.
"""

from __future__ import annotations

import collections
import math
import os
import subprocess
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


def _rows(path: Path) -> list[list[float]]:
    return [
        [float(v) for v in line.split()]
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _run(tmp_path: Path, name: str, model: str):
    """Write ``model`` under ``tmp_path``, run it, return the (.gdat, .bdat) rows.

    A ``simulate`` action writes the batch mean to .gdat and, for batched SSA,
    the batch standard deviation to .bdat.  Both are columned
    ``[time, <observable 0>, ...]``, so the mean and the standard deviation of
    one observable come from the same column of two different files.
    """
    exe = _bng_cpp()
    (tmp_path / f"{name}.bngl").write_text(model)
    proc = subprocess.run(
        [exe, f"{name}.bngl"], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode == 0, f"{name}: {proc.stdout}\n{proc.stderr}"
    gdat = tmp_path / f"{name}.gdat"
    assert gdat.exists(), sorted(p.name for p in tmp_path.iterdir())
    bdat = tmp_path / f"{name}.bdat"
    return _rows(gdat), (_rows(bdat) if bdat.exists() else None)


# ---------------------------------------------------------------------------
# SIR: conservation, the R0 threshold, and the final-size law
# ---------------------------------------------------------------------------

_SIR = """begin parameters
  N     {N}
  beta  {beta}
  gamma {gamma}
  I0    {I0}
end parameters
begin species
  S() N-I0
  I() I0
  R() 0
end species
begin reactions
  S() + I() -> I() + I() {rate}
  I() -> R() gamma
end reactions
begin observables
  S S()
  I I()
  R R()
end observables
begin actions
  simulate({{method=>"ode",t_end=>{t_end},n_steps=>{n}}})
end actions
"""


def _sir(tmp_path, name, *, N, beta, gamma, rate, I0, t_end, n):
    return _run(
        tmp_path,
        name,
        _SIR.format(N=N, beta=beta, gamma=gamma, rate=rate, I0=I0, t_end=t_end, n=n),
    )[0]


def _max_population_defect(rows, N):
    """max |S + I + R - N| over the trajectory."""
    return max(abs(s + i + r - N) for _, s, i, r in rows)


@pytest.mark.parametrize("rate", ["beta", "beta/N"])
@pytest.mark.parametrize("beta", ["5e-5", "1e-4", "2.5e-4"])
def test_sir_conserves_the_total_population_exactly(tmp_path, rate, beta):
    # S + E + I + R is a stoichiometric invariant of an SIR: every reaction
    # moves one unit between compartments, so the sum is conserved to solver
    # precision, not to a modelling tolerance.
    N = 1000
    rows = _sir(
        tmp_path,
        f"cons_{rate.replace('/', '_')}_{beta}",
        N=N,
        beta=beta,
        gamma=0.1,
        rate=rate,
        I0=100,
        t_end=100,
        n=20000,
    )
    assert _max_population_defect(rows, N) < 1e-8


_COMPARTMENTAL = """begin parameters
  N     1000
  beta  {beta}
  gamma {gamma}
  vol   {V}
end parameters
begin compartments
  cell 3 {V}
end compartments
begin species
  S()@cell 900
  I()@cell 1
  R()@cell 0
end species
begin reactions
  S()@cell + I()@cell -> I()@cell + I()@cell {rate}
  I()@cell -> R()@cell gamma
end reactions
begin observables
  S S()@cell
  I I()@cell
  R R()@cell
end observables
begin actions
  simulate({{method=>"{method}",t_end=>{t_end},n_steps=>{n}{extra}}})
end actions
"""


@pytest.mark.parametrize("method", ["ode", "ssa"])
@pytest.mark.parametrize("V", ["1", "100"])
def test_a_bare_compartmental_seed_is_a_volume_independent_molecule_count(
    tmp_path, method, V
):
    # A seed written without a unit annotation (`S()@cell 900`) is a MOLECULE
    # COUNT: the same numbers seed the same population whatever the
    # compartment's volume.  This is the fact the whole units story rests on,
    # and it is the opposite of the volume dependence a bare seed would have
    # if it were a concentration (which would seed 900*V).
    #
    # Conservation is checked too, because that is the invariant that makes the
    # reading unambiguous: whatever the units, S+I+R is stoichiometrically
    # conserved, and it equals the sum of the seed values.
    #
    # NOTE WHAT IS *NOT* PINNED HERE: the volume dependence of the bimolecular
    # rate law.  BNG3's propensity for `A + B` in a declared compartment is
    # k*n_A*n_B/V (measured: I(t=0.1) matches exp((beta*S0/V - gamma)*t) to 8
    # significant figures at V = 1, 2, 10, 100), so the effective R0 of a
    # compartmental epidemic scales as 1/V.  That is the standard mass-action
    # units convention rather than a demonstrated defect -- BNG2 parity was NOT
    # established, see the PR -- so pinning it here would re-pin behaviour that
    # is still legitimately in question.
    extra = "" if method == "ode" else ",batch_size=>4000,seed=>31"
    t_end, n = (0.1, 200) if method == "ode" else (0.1, 1)
    gdat, _ = _run(
        tmp_path,
        f"comp_{method}_{V}",
        _COMPARTMENTAL.format(
            beta=0.1,
            gamma=0.1,
            V=V,
            rate="beta",
            method=method,
            t_end=t_end,
            n=n,
            extra=extra,
        ),
    )
    # The initial state is the seed, unchanged, at every volume.
    assert gdat[0][1:] == [900.0, 1.0, 0.0]
    # And conservation holds to solver precision.
    for _, s, i, r in gdat:
        assert s + i + r == pytest.approx(901.0, abs=1e-8)


@pytest.mark.parametrize(
    "rate,beta,expected_r0",
    [
        ("beta", "5e-5", 0.5),  # mass action:    R0 = beta*N/gamma
        ("beta", "1e-4", 1.0),
        ("beta", "2.5e-4", 2.5),
        ("beta/N", "0.05", 0.5),  # per-capita:     R0 = beta/gamma
        ("beta/N", "0.1", 1.0),
        ("beta/N", "0.25", 2.5),
    ],
)
def test_disease_free_state_is_stable_below_r0_one_and_unstable_above(
    tmp_path, rate, beta, expected_r0
):
    # Linearise about the disease-free state (S = N, I = 0) and perturb it by
    # an infinitesimal: dI/dt = (beta*S0 - gamma) I.  The disease-free state is
    # a repeller exactly when R0 > 1, and the growth rate is gamma*(R0 - 1).
    N, gamma = 1000, 0.1
    rows = _sir(
        tmp_path,
        f"lin_{rate.replace('/', '_')}_{beta}",
        N=N,
        beta=beta,
        gamma=gamma,
        rate=rate,
        I0=1e-6,
        t_end=5,
        n=20000,
    )
    r0 = (float(beta) * N / gamma) if rate == "beta" else (float(beta) / gamma)
    assert r0 == pytest.approx(expected_r0)
    t0, _, i0, _ = rows[0]
    t1, _, i1, _ = rows[200]  # t = 1.0
    measured = (math.log(i1) - math.log(i0)) / (t1 - t0)
    assert measured == pytest.approx(gamma * (r0 - 1.0), abs=1e-4)


def test_sir_final_size_satisfies_the_analytic_final_size_law(tmp_path):
    # Integrating dS/dR = -R0 * S over the trajectory gives
    # ln(s_inf) - ln(s_0) = -R0 * (r_inf - r_0), the epidemic final-size
    # relation.  It is exact for any s_0, so it tests the whole trajectory and
    # not just its endpoint.
    N, gamma, beta, s0, r0 = 1000, 0.1, "2.5e-4", 0.9, 0.0
    rows = _sir(
        tmp_path,
        "final_size",
        N=N,
        beta=beta,
        gamma=gamma,
        rate="beta",
        I0=100,
        t_end=100,
        n=20000,
    )
    _, s_inf, _i_inf, r_inf = rows[-1]
    R0 = float(beta) * N / gamma
    lhs = math.log(s_inf / N) - math.log(s0)
    rhs = -R0 * (r_inf / N - r0)
    assert lhs == pytest.approx(rhs, abs=1e-6)


def test_mass_action_and_per_capita_mixing_differ_by_exactly_the_population_size(
    tmp_path,
):
    # True mass action gives rate beta*S*I; per-capita (standard incidence)
    # gives rate beta*S*I/N.  The two are the same epidemic only after rescaling
    # beta by N -- with the *same pairwise* beta they are not the same epidemic
    # at all, because R0 differs by exactly N: one goes epidemic, one dies.
    N, gamma, beta = 1000, 0.1, "2.5e-4"

    mass = _sir(
        tmp_path,
        "mix_mass",
        N=N,
        beta=beta,
        gamma=gamma,
        rate="beta",
        I0=100,
        t_end=100,
        n=20000,
    )
    same_beta = _sir(
        tmp_path,
        "mix_pc_same",
        N=N,
        beta=beta,
        gamma=gamma,
        rate="beta/N",
        I0=100,
        t_end=100,
        n=20000,
    )
    rescaled = _sir(
        tmp_path,
        "mix_pc_rescaled",
        N=N,
        beta="0.25",
        gamma=gamma,
        rate="beta/N",
        I0=100,
        t_end=100,
        n=20000,
    )

    for rows in (mass, same_beta, rescaled):
        assert _max_population_defect(rows, N) < 1e-8

    # Same pairwise beta: mass action R0 = 2.5, per-capita R0 = 0.0025.
    mass_s, mass_i = mass[-1][1], mass[-1][2]
    pc_s, pc_i = same_beta[-1][1], same_beta[-1][2]
    assert mass_i < 0.05 * mass_s  # epidemic burnt through
    assert pc_i < 0.01 * pc_s  # died out immediately

    # beta_pc = N * beta_mass reproduces the mass-action trajectory exactly.
    assert len(mass) == len(rescaled)
    for (t, s1, i1, r1), (t2, s2, i2, r2) in zip(mass, rescaled):
        assert t == pytest.approx(t2)
        assert s1 == pytest.approx(s2, abs=1e-6)
        assert i1 == pytest.approx(i2, abs=1e-6)
        assert r1 == pytest.approx(r2, abs=1e-6)


# ---------------------------------------------------------------------------
# Lotka-Volterra: first integral, closed orbit, neutral stability
# ---------------------------------------------------------------------------

# The Gause mass-action predator-prey system
#     dx/dt = px*x - a*x*y,   dy/dt = a*x*y - qy*y
# has the first integral  H = qy*ln x + px*ln y - a*x - a*y  and a coexistence
# fixed point at (qy/a, px/a) whose linearisation has eigenvalues
# +-i*sqrt(px*qy), i.e. a centre with small-amplitude period
# 2*pi/sqrt(px*qy).
_LV_PX, _LV_A, _LV_QY = 1.5, 1.0, 1.0
_LV_X_STAR = _LV_QY / _LV_A
_LV_Y_STAR = _LV_PX / _LV_A

_LV = """begin parameters
  px {px}
  a  {a}
  qy {qy}
end parameters
begin species
  X() {x0}
  Y() {y0}
end species
begin reactions
  X() -> X() + X() px
  X() + Y() -> Y() + Y() a
  Y() -> 0 qy
end reactions
begin observables
  X X()
  Y Y()
end observables
begin actions
  simulate({{method=>"ode",t_end=>{t_end},n_steps=>{n}}})
end actions
"""


def _lv_h(x, y):
    return _LV_QY * math.log(x) + _LV_PX * math.log(y) - _LV_A * (x + y)


def _lv_run(tmp_path, name, x0, y0, t_end=30, n=200000):
    return _run(
        tmp_path,
        name,
        _LV.format(px=_LV_PX, a=_LV_A, qy=_LV_QY, x0=x0, y0=y0, t_end=t_end, n=n),
    )[0]


def _lv_upcrossings(rows):
    """Times at which X(t) rises through the coexistence fixed point."""
    return [
        p[0] + (q[0] - p[0]) * (_LV_X_STAR - p[1]) / (q[1] - p[1])
        for p, q in zip(rows, rows[1:])
        if p[1] - _LV_X_STAR < 0 <= q[1] - _LV_X_STAR
    ]


@pytest.mark.parametrize("x0,y0", [(1.02, 1.5), (1.35, 1.5), (2.2, 0.6)])
def test_lotka_volterra_conserves_its_first_integral(tmp_path, x0, y0):
    rows = _lv_run(tmp_path, f"lv_h_{x0}", x0, y0)
    h0 = _lv_h(rows[0][1], rows[0][2])
    assert max(abs(_lv_h(x, y) - h0) for _, x, y in rows) < 1e-5


def test_lotka_volterra_small_orbit_is_closed_after_the_nominal_period(tmp_path):
    period = 2 * math.pi / math.sqrt(_LV_PX * _LV_QY)
    rows = _lv_run(tmp_path, "lv_closed", _LV_X_STAR + 0.02, _LV_Y_STAR)

    crossings = _lv_upcrossings(rows)
    assert len(crossings) >= 3
    cycles = [b - a for a, b in zip(crossings, crossings[1:])]
    assert sum(cycles) / len(cycles) == pytest.approx(period, rel=2e-3)

    x0, y0 = rows[0][1], rows[0][2]
    closest = min(rows, key=lambda r: abs(r[0] - period))
    assert abs(closest[1] - x0) < 1e-5
    assert abs(closest[2] - y0) < 1e-4


def test_lotka_volterra_is_a_center_not_a_focus(tmp_path):
    # A neutrally stable cycle keeps its amplitude cycle over cycle; a focus
    # would shrink it.  The nominal period is only a small-amplitude limit, so
    # a large orbit must have a strictly longer period.
    rows = _lv_run(tmp_path, "lv_center", 2.2, 0.6)
    crossings = _lv_upcrossings(rows)
    peaks = [
        max(r[2] for r in rows if crossings[i] <= r[0] <= crossings[i + 1])
        for i in range(len(crossings) - 1)
    ]
    assert len(peaks) >= 4
    assert peaks[-1] == pytest.approx(peaks[0], rel=1e-5)

    periods = [b - a for a, b in zip(crossings, crossings[1:])]
    assert sum(periods) / len(periods) > 2 * math.pi / math.sqrt(_LV_PX * _LV_QY)


# ---------------------------------------------------------------------------
# Two-state ion-channel gating: P_inf, tau, and the boundary to the stochastic
# treatment
# ---------------------------------------------------------------------------

_GATE_ALPHA, _GATE_BETA = 0.4, 0.1
_P_INF = _GATE_ALPHA / (_GATE_ALPHA + _GATE_BETA)
_TAU = 1.0 / (_GATE_ALPHA + _GATE_BETA)

_GATE = """begin parameters
  alpha {alpha}
  beta  {beta}
end parameters
begin species
  C(s~c) {nch}
  O(s~o) 0
end species
begin reactions
  C(s~c) -> O(s~o) alpha
  O(s~o) -> C(s~c) beta
end reactions
begin observables
  Nopen  O(s~o)
  Nclose C(s~c)
end observables
begin actions
  simulate({{method=>"{method}",t_end=>{t_end},n_steps=>{n}{extra}}})
end actions
"""


def test_gating_ode_matches_the_exponential_approach_to_its_steady_state(tmp_path):
    nch = 500
    rows, _ = _run(
        tmp_path,
        "gate_ode",
        _GATE.format(
            alpha=_GATE_ALPHA,
            beta=_GATE_BETA,
            nch=nch,
            method="ode",
            t_end=20,
            n=200000,
            extra="",
        ),
    )
    for t, n_open, n_close in rows:
        assert n_open + n_close == pytest.approx(nch, abs=1e-8)
        expected = nch * _P_INF * (1.0 - math.exp(-t / _TAU))
        assert n_open == pytest.approx(expected, abs=1e-4)

    # tau = 1/(alpha+beta), read off the decay of the gap to steady state.
    window = [r for r in rows if 4.0 <= r[0] <= 8.0]
    rate = (
        math.log(nch * _P_INF - window[0][1]) - math.log(nch * _P_INF - window[-1][1])
    ) / (window[-1][0] - window[0][0])
    assert rate == pytest.approx(1.0 / _TAU, rel=1e-5)

    # The steady-state open probability is alpha/(alpha+beta), reached from
    # rest, so the residual at t is exactly P_inf*exp(-t/tau).
    t_end, n_open = rows[-1][0], rows[-1][1]
    assert n_open / nch == pytest.approx(
        _P_INF * (1.0 - math.exp(-t_end / _TAU)), abs=1e-7
    )
    assert _P_INF * (1.0 - math.exp(-20.0 / _TAU)) == pytest.approx(_P_INF, abs=1e-4)


def test_channel_population_is_binomial_not_poisson_at_steady_state(tmp_path):
    # N independent two-state units in stationarity are Binomial(N, P_inf), so
    # Var/Mean = 1 - P_inf.  A Poisson treatment of the same process would
    # give 1.0 -- five times too large here.
    nch, batch = 500, 4000
    gdat, bdat = _run(
        tmp_path,
        "gate_pop",
        _GATE.format(
            alpha=_GATE_ALPHA,
            beta=_GATE_BETA,
            nch=nch,
            method="ssa",
            t_end=200,
            n=1,
            extra=f",batch_size=>{batch},seed=>4242",
        ),
    )
    mean, sd = gdat[-1][1], bdat[-1][1]
    assert mean == pytest.approx(nch * _P_INF, rel=0.02)
    assert sd == pytest.approx(math.sqrt(nch * _P_INF * (1 - _P_INF)), rel=0.05)
    ratio = sd * sd / mean
    assert 0.17 < ratio < 0.23
    assert ratio < 0.5  # decisively not Poisson


def test_single_channel_open_probability_matches_the_deterministic_ode(tmp_path):
    # For one channel the ODE variable *is* the open probability, and the SSA
    # indicator is Bernoulli(P_inf).  This is the boundary: the means agree and
    # the variance is P_inf*(1-P_inf), not Poisson.
    batch = 8000
    gdat, bdat = _run(
        tmp_path,
        "gate_one",
        _GATE.format(
            alpha=_GATE_ALPHA,
            beta=_GATE_BETA,
            nch=1,
            method="ssa",
            t_end=200,
            n=1,
            extra=f",batch_size=>{batch},seed=>99",
        ),
    )
    mean, sd = gdat[-1][1], bdat[-1][1]
    assert mean == pytest.approx(_P_INF, abs=4.0 / math.sqrt(batch))
    assert sd == pytest.approx(math.sqrt(_P_INF * (1 - _P_INF)), rel=0.03)


# ---------------------------------------------------------------------------
# Offspring distributions at the deterministic/stochastic boundary
# ---------------------------------------------------------------------------

# A single infector that reproduces at rate lam and dies at rate mu.  Its
# offspring count is Poisson(lam*T) with T ~ Exp(mu), which is *geometric*, not
# Poisson: Var/Mean = 1 + lam/mu = 1 + R0.  Poisson offspring is not
# representable by a Markovian continuous-time infector, so a model that
# silently treated it as Poisson would be wrong by a factor of four here.
_MARKOVIAN_PARENT = """begin parameters
  lam {lam}
  mu  {mu}
end parameters
begin species
  P() 1
  C() 0
end species
begin reactions
  P() -> P() + C() lam
  P() -> 0 mu
end reactions
begin observables
  Offspring C()
end observables
"""

# An Erlang(r) infectious period, written as r sequential exponential stages
# that emit and advance at the same rate, makes the offspring count negative
# binomial with Var/Mean = 1 + m/r for the same mean m.
_ERLANG_PARENT = """begin parameters
  q {q}
end parameters
begin species
{parents}
  C() 0
end species
begin reactions
{rules}
end reactions
begin observables
  Offspring C()
end observables
"""

_SSA_BLOCK = (
    "begin actions\n"
    'simulate({{method=>"ssa",t_end=>400,n_steps=>1,batch_size=>{batch},seed=>{seed}}})\n'
    "end actions\n"
)


def _erlang_parent_source(r, q):
    parents = "\n".join(f"  P{j}() {1 if j == 1 else 0}" for j in range(1, r + 1))
    rules = []
    for j in range(1, r + 1):
        rules.append(f"  P{j}() -> P{j}() + C() q")
        rules.append(f"  P{j}() -> {'0' if j == r else f'P{j + 1}()'} q")
    return _ERLANG_PARENT.format(q=q, parents=parents, rules="\n".join(rules))


def _markovian_parent_model(lam, mu, batch, seed):
    return _MARKOVIAN_PARENT.format(lam=lam, mu=mu) + _SSA_BLOCK.format(
        batch=batch, seed=seed
    )


def _erlang_parent_model(r, q, batch, seed):
    return _erlang_parent_source(r, q) + _SSA_BLOCK.format(batch=batch, seed=seed)


def _moments(tmp_path, name, model):
    gdat, bdat = _run(tmp_path, name, model)
    return gdat[-1][1], bdat[-1][1] ** 2


def test_markovian_continuous_time_infector_has_geometric_not_poisson_offspring(
    tmp_path,
):
    lam, mu, batch = 1.5, 0.5, 4000
    mean, var = _moments(
        tmp_path, "off_markovian", _markovian_parent_model(lam, mu, batch, 13)
    )
    m = lam / mu
    assert mean == pytest.approx(m, rel=0.1)
    # E[K^2] = 2(lam/mu)^2 + lam/mu, so Var = 2m^2 + m - m^2.
    assert var == pytest.approx(2 * m * m + m - m * m, rel=0.1)
    # Var/Mean = 1 + R0 = 4.  Poisson would give 1.
    assert 3.4 < var / mean < 4.6
    assert var / mean > 2.0


def test_negative_binomial_offspring_is_expressible_and_dispersion_drops_by_r(
    tmp_path,
):
    # r Erlang stages give NB(r, mean m) with the same mean as the Markovian
    # parent and Var/Mean = 1 + m/r, i.e. half the variance-to-mean ratio.
    r, m, batch = 3, 3.0, 4000
    mean, var = _moments(tmp_path, "off_nb", _erlang_parent_model(r, 0.75, batch, 17))
    assert mean == pytest.approx(m, rel=0.1)
    assert var == pytest.approx(m + m * m / r, rel=0.1)
    assert 1.7 < var / mean < 2.3
    assert var / mean < 3.0  # clearly under-dispersed relative to the geometric


# ---------------------------------------------------------------------------
# The moments above fix the dispersion, but two distributions can share a mean
# and a variance.  These two run the models one replicate at a time through
# the in-process SSA binding so the whole offspring *distribution* can be
# compared with the closed-form pmf, which is the claim that actually matters
# epidemiologically: it sets the probability of a major outbreak.
# ---------------------------------------------------------------------------


def _cpp():
    # Decide shadowing BEFORE importing, because the order matters.  If this
    # worktree has its own extension and the import then fails or resolves
    # elsewhere, that is the silent-skip hazard, not a missing optional
    # dependency.  Checking only after a successful import let the skip swallow
    # the very case the check exists for, which I found by running it rather
    # than by reading it.
    root = Path(__file__).resolve().parents[2]
    local = [p.resolve() for p in (root / "build" / "cpp").glob("_bionetgen_cpp*.so")]
    try:
        import bionetgen._bionetgen_cpp as module
    except ImportError:  # pragma: no cover - depends on the build
        if local:
            raise AssertionError(
                f"extension shadowing: this worktree has its own build at "
                f"{[str(p) for p in local]} but importing "
                f"bionetgen._bionetgen_cpp failed. The two pmf tests below "
                f"would silently skip instead of measuring that build."
            ) from None
        pytest.skip("compiled extension bionetgen._bionetgen_cpp unavailable")
    resolved = getattr(module, "__file__", None)
    if local and resolved is not None and Path(resolved).resolve() not in local:
        raise AssertionError(
            f"extension shadowing: tests resolve to {resolved}, but this worktree "
            f"has its own build at {[str(p) for p in local]}. The two pmf tests "
            f"below would measure a binary that is not the one under test."
        )
    return module


def _offspring_counts(source, n):
    """One independent single-trajectory SSA run per seed; returns the counts."""
    cpp = _cpp()
    model = cpp.parse_string(source)
    network = cpp.generate_network(model)
    return [
        int(
            cpp.simulate_ssa(model, network, 400.0, 1, 0.0, seed + 1)["observables"][
                "Offspring"
            ][-1]
        )
        for seed in range(n)
    ]


def _chi_square(counts, total, pmf):
    """Pearson chi-square, pooling the tail so every cell has >= 5 expected."""
    cells, expected, run_obs, run_exp = [], [], 0, 0.0
    for k in sorted(counts) + [None]:
        exp = pmf(k) * total if k is not None else 0.0
        if k is not None and run_exp + exp < 5.0:
            run_obs += counts[k]
            run_exp += exp
            continue
        if run_exp > 0:
            cells.append(run_obs)
            expected.append(run_exp)
        run_obs, run_exp = (counts.get(k, 0), exp) if k is not None else (0, 0.0)
    return sum((o - e) ** 2 / e for o, e in zip(cells, expected)), len(cells) - 1


def test_markovian_infector_offspring_pmf_is_geometric_not_poisson():
    # Geometric on {0,1,...} with P(k) = (mu/(mu+lam)) * (lam/(mu+lam))^k.
    counts = collections.Counter(
        _offspring_counts(_MARKOVIAN_PARENT.format(lam=1.5, mu=0.5), 20000)
    )
    total = sum(counts.values())
    geometric = lambda k: 0.25 * 0.75**k  # noqa: E731
    poisson = lambda k: math.exp(-3.0) * 3.0**k / math.factorial(k)  # noqa: E731
    chi2, dof = _chi_square(counts, total, geometric)
    assert chi2 < 3.84 * dof, f"geometric rejected: chi2={chi2} dof={dof}"
    chi2_poisson, dof_poisson = _chi_square(counts, total, poisson)
    assert chi2_poisson > 50 * dof_poisson, (
        f"Poisson not decisively rejected: chi2={chi2_poisson} dof={dof_poisson}"
    )


def test_erlang_parent_offspring_pmf_is_negative_binomial():
    # NB(r=3, mean 3): P(k) = C(k+2,2) p^3 (1-p)^k with p = m/(m+r) = 1/2.
    counts = collections.Counter(
        _offspring_counts(_erlang_parent_source(3, 0.75), 20000)
    )
    total = sum(counts.values())
    negbin = lambda k: math.comb(k + 2, 2) * 0.5 ** (k + 3)  # noqa: E731
    geometric = lambda k: 0.25 * 0.75**k  # noqa: E731
    chi2, dof = _chi_square(counts, total, negbin)
    assert chi2 < 3.84 * dof, f"negative binomial rejected: chi2={chi2} dof={dof}"
    chi2_geo, dof_geo = _chi_square(counts, total, geometric)
    assert chi2_geo > 20 * dof_geo, (
        f"geometric not decisively rejected: chi2={chi2_geo} dof={dof_geo}"
    )
