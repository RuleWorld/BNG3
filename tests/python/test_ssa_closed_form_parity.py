"""Closed-form parity for the direct-method (Gillespie) SSA.

Every quantity asserted here is derived from the reaction network's master
equation, not from a BNG3 output: a birth-death process has a Poisson
stationary law, a fixed population of independently switching molecules has a
Multinomial law, a single molecule in a two-state chain has the stationary
weight ``k01/(k01+k10)``, a pure first-order decay from ``N0`` thins to
``Binomial(N0, e^{-kT})``, and the propensity of ``A() + A() -> ...`` at
declared rate ``k`` is the BNG2 combinatorial ``k*C(n,2)``.

Tolerances are Monte-Carlo error, not fudge factors. For ``B`` i.i.d. draws the
sample mean has SEM ``sqrt(var/B)`` and ``(B-1)s^2/var ~ Chi2(B-1)``, so each
moment is asserted through its Z-score and the Goodness-Of-Fit keeps every cell
at a well-populated expected count. The seed is fixed, so each threshold is
compared against one deterministic number rather than a repeated-sampling
probability: that is the only way to make a statistical test a gate.

Measured at BNG3 ``6889fba`` (BATCH=20000, SEED=1000), so the margin each
threshold has is on the record rather than assumed:

    Poisson(20)                 GOF p=0.0062 (df=30)
                                z_mean +1.38  z_var +0.79  Fano 1.0057
    Multinomial(12; .5,1/3,1/6) GOF p=0.662 (df=62, 91 joint cells), |z| <= 1.63
    Binomial(20, e^-0.5)        GOF p=0.151 (df=15)
                                z_mean +0.88  z_var -1.52  implied k = 0.49888
    A+A firing count            p=0.253 vs k*C(n,2); p=0 vs k*n(n-1) (|z| > 130)

Provenance for those numbers, because a threshold without it is not a
measurement. Command, from the repository root, with the resolution it
actually produced on this host:

    PYTHONPATH=python:build/cpp python -m pytest \
        tests/python/test_ssa_closed_form_parity.py -q
    UNDER TEST (package)     .../BNG3/python/bionetgen/__init__.py
    UNDER TEST (extension)   .../BNG3/build/cpp/_bionetgen_cpp.cpython-314-darwin.so
                             sha256 f6cf5b72ff85b25ad3988e35825b7c5f5326fa8ec46ff72e0f6ecec2e78dc1f0
    10 passed

Two things that resolution depends on, both load-bearing:

* On this host ``bionetgen`` resolves through a scikit-build **editable**
  ``meta_path`` finder that runs before ``sys.path``, so ``PYTHONPATH`` cannot
  override it. The extension it can resolve is a different path from the one
  above, and the two are byte-identical (same sha256) - but a result is only
  meaningful with the path printed next to it.
* The shared ``build/cpp`` extension is one commit behind ``6889fba``, and that
  commit is NFsim-only. Re-derive it in one command rather than trusting the
  sentence:

      git log --oneline --since='2026-09-29 15:08:50' -- cpp/

  which returns exactly ``75b22a7``, touching exactly
  ``cpp/nfsim/NFinput/NFinput_fromCompiled.cpp``. This file calls
  ``simulate_batch_ssa_cpu`` and ``simulate_ssa`` and never touches NFsim, so
  that commit cannot affect anything asserted here.

  The commit log is the evidence, deliberately. A ``find cpp -newer <binary>``
  check is NOT usable for this: it reports two files
  (``cpp/ast/ParameterList.cpp``, ``cpp/engine/OdeIntegrator.cpp``) whose
  mtimes are newer purely because of checkout activity, and it is equally wrong
  in the other direction, reporting a stale binary from a harmless touch. A
  reader must be able to re-run the cited command and get the cited answer.

Import the extension under the name every other file in ``tests/python`` uses.
Loading it a second time under a different module name is not a no-op: pybind11
registers its C++ types globally, so the second load raises ``generic_type:
type "Expression" is already registered!`` and ``importorskip`` turns that into
a SILENT SKIP of this entire file. That is not hypothetical: an interim draft
of this file imported ``_bionetgen_cpp`` top-level, the whole file skipped, and
the suite still reported a green number.

The GOF values are secondary; the moment Z-scores carry the test, and they sit
at least a factor of three inside ``Z_LIMIT`` while a genuine propensity or
stoichiometry error moves them by two orders of magnitude more.

Three reference formulas that are easy to get wrong, each of which makes a
CORRECT engine look broken. All three were hit while writing this file.

1. **A two-state chain's event rate is its stationary exit rate, not
   ``k01+k10``.** A molecule in state 0 leaves at ``k01`` and one in state 1
   leaves at ``k10``, so the flip rate is ``pi0*k01 + pi1*k10``. With
   ``k01=0.7, k10=0.3`` that is 0.42, not 1.0. Asserting ``(k01+k10)*T = 500``
   flips over ``T=500`` gives **z = -41000** against an engine that measured
   210.1 against the correct 210.0.
2. **A fixed total makes the counts a multinomial PAIR, not two independent
   binomials.** The total is conserved, so ``E[nX nY] = N(N-1) pX pY``, not
   ``N^2 pX pY``. For ``N=12, pX=1/2, pY=1/3`` that is 22.0, not 24.0, and
   ``corr(nX,nY) = -sqrt(pX pY / ((1-pX)(1-pY))) = -0.7071``, not 0.
   Asserting independence gives **z = -103** against the correct 21.9662.
3. **Index the CTMC generator, do not hand-derive its entries.** For the
   4 -> 2 -> 0 pure-death chain, ``P(j firings by t)`` is the *j*-th entry of
   ``[exp(Q t)]_{0,:}``. A hand-derived ``p2`` is easy to mis-index: the
   mis-indexed one rejected a correct engine at **z = -123** on the same model
   that the generator gets right at z = -1.42.
"""

import math

import numpy as np
import pytest

from _extdep import require_extension

_cpp = require_extension()
scipy_stats = pytest.importorskip("scipy.stats")

BATCH = 20000
SEED = 1000
# A Z-score of 5 is a 5.7e-7 two-sided normal tail. It is far outside the
# largest |Z| any closed form below produces (1.43) and far inside what a real
# propensity or stoichiometry error would produce (>=30), so it discriminates
# without being a coin flip.
Z_LIMIT = 5.0
# Pearson's approximation is unreliable below ~5 expected counts per cell.
MIN_EXPECTED = 5.0
GOF_ALPHA = 1e-3


def _batch(bngl, tmp_path, t_end, n_steps=10, batch=BATCH, seed=SEED, threads=0):
    path = tmp_path / "model.bngl"
    path.write_text(bngl)
    model = _cpp.parse_file(str(path))
    network = _cpp.generate_network(model)
    res = _cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=batch,
        t_end=t_end,
        n_steps=n_steps,
        threads=threads,
        base_seed=seed,
    )
    return res, list(res["observable_names"])


def _finals(res, names):
    """Final molecule counts, keyed by observable, as int64."""
    table = np.asarray(res["final_observables"], dtype=np.int64)
    return {n: table[:, names.index(n)] for n in names}


def _z_mean(sample, target, var):
    return (sample.mean() - target) / math.sqrt(var / sample.size)


def _z_var(sample, var):
    return (sample.var(ddof=1) - var) / math.sqrt(2.0 * var * var / sample.size)


def _hist(sample, pmf):
    """Observed cell counts for a sample whose values index the pmf."""
    return np.bincount(sample, minlength=len(pmf)).astype(float)[: len(pmf)]


def _gof(counts, pmf, batch):
    """Pearson GOF over the given cell counts, pooling ONLY the cells the
    approximation cannot support.

    Pearson's statistic is unreliable below roughly five expected counts, so
    exactly those cells are merged into one tail cell. Cells that already clear
    the bar are kept separate: merging them as well re-weights the statistic
    and can move a well-fitting sample's p-value by orders of magnitude, which
    would make the threshold meaningless.
    """
    expected = np.asarray(pmf, dtype=float) * batch
    head = [i for i in range(len(pmf)) if expected[i] >= MIN_EXPECTED]
    tail = [i for i in range(len(pmf)) if expected[i] < MIN_EXPECTED]
    assert tail, "no sparse tail to pool; lower MIN_EXPECTED or widen the grid"
    obs = np.array([counts[i] for i in head] + [sum(counts[i] for i in tail)])
    exp = np.array([expected[i] for i in head] + [sum(expected[i] for i in tail)])
    assert (
        exp.min() >= MIN_EXPECTED
    ), f"pooled tail holds only {exp[-1]:.1f} expected counts; raise BATCH"
    chi2, p = scipy_stats.chisquare(obs, exp)
    return chi2, len(exp) - 1, p, exp.min()


BIRTH_DEATH = """begin model
begin parameters
    k_on   1.0
    k_off  0.05
end parameters
begin molecule types
    P()
end molecule types
begin seed species
    P()  0
end seed species
begin observables
    Molecules  nP  P()
end observables
begin reaction rules
    0 -> P()   k_on
    P() -> 0   k_off
end reaction rules
end model
"""


def test_birth_death_stationary_is_poisson(tmp_path):
    """``0 -> P`` at k_on and ``P -> 0`` at k_off is Poisson(k_on/k_off).

    The immigration-death process relaxes at k_on + k_off = 1.05 /s, so
    t_end = 200 leaves a bias of exp(-210); the stationary law is reached long
    before the sample is read.
    """
    lam = 1.0 / 0.05
    res, names = _batch(BIRTH_DEATH, tmp_path, t_end=200.0)
    n = _finals(res, names)["nP"]

    assert n.min() >= 0, "molecule counts cannot be negative"
    assert np.all(n == np.round(n.astype(float))), "counts must be integral"

    # Poisson(lam): mean and variance both lam, so the Fano factor is 1.
    assert abs(_z_mean(n, lam, lam)) < Z_LIMIT
    assert abs(_z_var(n, lam)) < Z_LIMIT
    assert 0.9 < n.var(ddof=1) / n.mean() < 1.1

    kmax = 70
    head = np.array([scipy_stats.poisson.pmf(k, lam) for k in range(kmax)])
    pmf = np.concatenate([head, [1.0 - head.sum()]])
    _, dof, p, minexp = _gof(_hist(n, pmf), pmf, BATCH)
    assert p > GOF_ALPHA, f"Poisson({lam}) GOF p={p:.3g} (chi2 df={dof})"


def test_birth_death_time_course_matches_deterministic_solution(tmp_path):
    """The ODE/SSA boundary: at large copy number the batch mean must track the
    deterministic trajectory to within Monte-Carlo error at EVERY timepoint.

    For a birth-death process the distribution at time ``t`` is exactly
    ``Binomial(x0, e^{-k t}) + Poisson(lam (1 - e^{-k t}))``, so both the mean
    and the spread are known analytically and the stochastic engine is checked
    against them, not against itself.
    """
    lam, k_off, batch = 50.0 / 0.01, 0.01, 2000
    res, _ = _batch(
        BIRTH_DEATH.replace("k_on   1.0", "k_on   50.0").replace(
            "k_off  0.05", "k_off  0.01"
        ),
        tmp_path,
        t_end=400.0,
        n_steps=8,
        batch=batch,
    )
    times = np.asarray(res["time"], dtype=float)
    mean = np.asarray(res["observable_means"]["nP"], dtype=float)
    std = np.asarray(res["observable_stds"]["nP"], dtype=float)

    assert times[0] == 0.0 and mean[0] == 0.0, "the initial condition is not P()=0"
    worst_z = 0.0
    worst_fano = 0.0
    for t, m, s in zip(times[1:], mean[1:], std[1:]):
        e = math.exp(-k_off * t)
        exp_mean = lam * (1.0 - e)
        exp_sd = math.sqrt(lam * (1.0 - e))  # Poisson variance
        z = (m - exp_mean) / (exp_sd / math.sqrt(batch))
        worst_z = max(worst_z, abs(z))
        # the measured spread must be the analytic Poisson spread, and the
        # Fano factor must be 1 to within sqrt(2/batch)
        worst_fano = max(worst_fano, abs(s * s / exp_sd**2 - 1.0))
    assert (
        worst_z < Z_LIMIT
    ), f"SSA mean departs from the ODE solution, max |Z|={worst_z}"
    assert worst_fano < 5.0 * math.sqrt(2.0 / batch), "Fano factor is not 1"


def test_three_state_switching_is_multinomial(tmp_path):
    """N molecules each switching X<->Y<->Z independently is Multinomial(N; pi).

    Because the total is fixed at N the counts are negatively correlated; the
    joint law, not just the three marginals, is what the test pins.
    """
    n_mol = 12
    # Rates chosen so the stationary weights of the per-molecule chain are
    # exactly pi: detail balance gives piY/piX = kXY/kYX and piZ/piX = kXZ/kZX.
    pi = np.array([0.5, 1.0 / 3.0, 1.0 / 6.0])
    bngl = """begin model
begin parameters
    kXY  0.40
    kYX  0.60
    kXZ  0.15
    kZX  0.45
    N    %d
end parameters
begin molecule types
    A(s~X~Y~Z)
end molecule types
begin seed species
    A(s~X)  N
end seed species
begin observables
    Molecules  nX  A(s~X)
    Molecules  nY  A(s~Y)
    Molecules  nZ  A(s~Z)
    Molecules  nT  A(s)
end observables
begin reaction rules
    A(s~X) <-> A(s~Y)  kXY, kYX
    A(s~X) <-> A(s~Z)  kXZ, kZX
end reaction rules
end model
""" % n_mol
    # slowest mode of the per-molecule chain is kYX = 0.6 /s; t_end = 200
    # leaves e^{-120}.
    res, names = _batch(bngl, tmp_path, t_end=200.0)
    f = _finals(res, names)
    nx, ny, nz = f["nX"], f["nY"], f["nZ"]

    # Conservation is exact, not statistical.
    assert np.all(
        nx + ny + nz == n_mol
    ), "the three conformations must partition the pool"
    assert np.all(f["nT"] == n_mol)

    for obs, p in ((nx, pi[0]), (ny, pi[1]), (nz, pi[2])):
        var = n_mol * p * (1 - p)
        assert abs(_z_mean(obs, n_mol * p, var)) < Z_LIMIT
        assert abs(_z_var(obs, var)) < Z_LIMIT

    # Multinomial cross-moment: E[nX nY] = N(N-1) pX pY, NOT N^2 pX pY. Using
    # the independent value here is the classic way to "fail" a correct engine.
    exp_cross = n_mol * (n_mol - 1) * pi[0] * pi[1]
    m2 = (
        n_mol * (n_mol - 1) * (n_mol - 2) * (n_mol - 3) * pi[0] ** 2 * pi[1] ** 2
        + n_mol * (n_mol - 1) * (n_mol - 2) * (pi[0] ** 2 * pi[1] + pi[0] * pi[1] ** 2)
        + n_mol * (n_mol - 1) * pi[0] * pi[1]
    )
    se = math.sqrt((m2 - exp_cross**2) / BATCH)
    assert abs((nx * ny).mean() - exp_cross) / se < Z_LIMIT

    rho = -math.sqrt(pi[0] * pi[1] / ((1 - pi[0]) * (1 - pi[1])))
    got = float(np.corrcoef(nx, ny)[0, 1])
    assert abs(got - rho) / ((1 - rho**2) / math.sqrt(BATCH)) < Z_LIMIT

    cells = [(i, j) for i in range(n_mol + 1) for j in range(n_mol + 1 - i)]
    pmf = np.array(
        [
            scipy_stats.multinomial.pmf([i, j, n_mol - i - j], n_mol, pi)
            for i, j in cells
        ]
    )
    index = {c: k for k, c in enumerate(cells)}
    key = np.array([index[(int(a), int(b))] for a, b in zip(nx, ny)])
    counts = np.bincount(key, minlength=len(cells))
    _, dof, p, _ = _gof(counts.astype(float), pmf, BATCH)
    assert p > GOF_ALPHA, f"exact Multinomial GOF p={p:.3g} (chi2 df={dof})"


def test_two_state_telegraph_stationary_weight(tmp_path):
    """One molecule in a two-state chain settles at P(state 1) = k01/(k01+k10),
    and its event rate is the stationary exit rate, not k01 + k10.
    """
    bngl = """begin model
begin parameters
    k01  0.7
    k10  0.3
end parameters
begin molecule types
    G(s~0~1)
end molecule types
begin seed species
    G(s~0)  1
end seed species
begin observables
    Molecules  n1  G(s~1)
    Molecules  nT  G(s)
end observables
begin reaction rules
    G(s~0) <-> G(s~1)  k01, k10
end reaction rules
end model
"""
    t_end = 500.0
    res, names = _batch(bngl, tmp_path, t_end=t_end)
    f = _finals(res, names)
    p_eq = 0.7 / (0.7 + 0.3)

    assert np.all(f["nT"] == 1), "a single molecule cannot be created or destroyed"
    assert np.all((f["n1"] == 0) | (f["n1"] == 1))

    p = f["n1"].mean()
    se = math.sqrt(p_eq * (1 - p_eq) / BATCH)
    assert abs(p - p_eq) / se < Z_LIMIT

    events = np.asarray(res["event_counts"], dtype=float)
    # A two-state chain leaves state 0 at rate k01 and state 1 at rate k10, so
    # the stationary flip rate is pi0*k01 + pi1*k10 = 0.21 + 0.21.
    rate = (1 - p_eq) * 0.7 + p_eq * 0.3
    z = (events.mean() - rate * t_end) / (events.std(ddof=1) / math.sqrt(BATCH))
    assert abs(z) < Z_LIMIT, f"flip rate is off: z={z}"


def test_unimolecular_decay_is_binomial_thinning(tmp_path):
    """``A() -> 0`` at rate k is a thinning of the initial N0 molecules, so
    A(t) is exactly Binomial(N0, e^{-kT}). This pins the propensity of a plain
    first-order reaction against the declared rate constant.
    """
    n0, k, t = 20, 0.5, 1.0
    bngl = """begin model
begin parameters
    k  %f
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A()  %d
end seed species
begin observables
    Molecules  nA  A()
end observables
begin reaction rules
    A() -> 0  k
end reaction rules
end model
""" % (k, n0)
    res, names = _batch(bngl, tmp_path, t_end=t)
    na = _finals(res, names)["nA"]

    q = math.exp(-k * t)
    var = n0 * q * (1 - q)
    assert abs(_z_mean(na, n0 * q, var)) < Z_LIMIT
    assert abs(_z_var(na, var)) < Z_LIMIT
    # the rate the sample actually implies
    assert abs(-math.log(na.mean() / n0) / t - k) < Z_LIMIT * math.sqrt(var / BATCH) / (
        n0 * q
    )

    pmf = scipy_stats.binom.pmf(np.arange(n0 + 1), n0, q)
    _, dof, p, _ = _gof(_hist(na, pmf), pmf, BATCH)
    assert p > GOF_ALPHA, f"Binomial({n0}, e^(-{k}*{t})) GOF p={p:.3g} (chi2 df={dof})"


def test_identical_reactant_propensity_is_the_combinatorial_one(tmp_path):
    """``A() + A() -> B()`` at declared rate k fires at ``k*C(n,2)``.

    Seeded with A(0)=4 the network is a pure-death chain 4 -> 2 -> 0 whose
    exit rates are a(4)=6k and a(2)=k under the BNG2 convention, and twice
    that under the "no factor" reading. The firing-count distribution at t=1
    separates the two by more than 130 standard deviations, so this is a
    statement about the convention, not a tolerance choice.
    """
    k, n0, t = 0.5, 4, 1.0
    bngl = """begin model
begin parameters
    k  %f
    N  %d
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A()  N
end seed species
begin observables
    Molecules  nA  A()
    Molecules  nB  B()
end observables
begin reaction rules
    A() + A() -> B()  k
end reaction rules
end model
""" % (k, n0)
    res, names = _batch(bngl, tmp_path, t_end=t, n_steps=4)
    f = _finals(res, names)
    events = np.asarray(res["event_counts"], dtype=np.int64)

    # exact mass balance, not a statistical identity
    assert np.all(f["nA"] == n0 - 2 * events)
    assert np.all(f["nB"] == events)
    assert int(events.max()) == n0 // 2

    observed = np.array([np.sum(events == j) for j in (0, 1, 2)], dtype=float)
    scipy_linalg = pytest.importorskip("scipy.linalg")
    for label, a4, a2 in (
        ("k*C(n,2)", 0.5 * k * n0 * (n0 - 1), 0.5 * k * 2),
        ("k*n(n-1)", k * n0 * (n0 - 1), k * 2),
    ):
        gen = np.array([[-a4, a4, 0.0], [0.0, -a2, a2], [0.0, 0.0, 0.0]])
        expected = scipy_linalg.expm(gen * t)[0] * BATCH
        # Read the reference off the generator rather than hand-deriving p2: a
        # hand-derived one was mis-indexed here and rejected a correct engine
        # at z = -123, where this gives z = -1.42. Row 0 of exp(Q t) is
        # P(j firings by t) for j = 0, 1, 2.
        chi2, p = scipy_stats.chisquare(observed, expected)
        if label == "k*C(n,2)":
            assert (
                p > GOF_ALPHA
            ), f"firing count departs from {label}: p={p:.3g} chi2={chi2}"
        else:
            assert p < GOF_ALPHA, f"firing count is indistinguishable from {label}"


def test_zero_rate_reaction_never_fires(tmp_path):
    """A reaction declared with rate 0 must produce nothing, ever."""
    bngl = """begin model
begin parameters
    k_on    1.0
    k_off   0.05
    k_synth_Q  0.0
end parameters
begin molecule types
    P()
    Q()
end molecule types
begin seed species
    P()  0
end seed species
begin observables
    Molecules  nP  P()
    Molecules  nQ  Q()
end observables
begin reaction rules
    0 -> P()         k_on
    P() -> 0         k_off
    0 -> Q()         k_synth_Q
end reaction rules
end model
"""
    res, names = _batch(bngl, tmp_path, t_end=200.0)
    f = _finals(res, names)
    assert f["nQ"].max() == 0, "a zero-rate reaction fired"
    # the zero-rate rule must not stop the live part of the network either
    assert f["nP"].mean() > 0.0


def test_fixed_seed_is_reproducible_across_runs_and_thread_counts(tmp_path):
    """Per-trajectory seeds are ``base_seed + b``, so a base seed determines the
    whole batch: reruns and any worker count must be bit-identical.
    """
    path = tmp_path / "model.bngl"
    path.write_text(BIRTH_DEATH)
    model = _cpp.parse_file(str(path))
    network = _cpp.generate_network(model)

    def batch(threads, n=5000):
        return _cpp.simulate_batch_ssa_cpu(
            model,
            network,
            batch_size=n,
            t_end=200.0,
            n_steps=10,
            threads=threads,
            base_seed=SEED,
        )

    ref = batch(0)
    for threads in (0, 1, 3):
        other = batch(threads)
        for key in ("final_observables", "final_species", "event_counts"):
            assert np.array_equal(
                np.asarray(ref[key]), np.asarray(other[key])
            ), f"{key} differs at threads={threads}"
        for name in ref["observable_names"]:
            assert np.array_equal(
                np.asarray(ref["observable_means"][name]),
                np.asarray(other["observable_means"][name]),
            )


def test_single_trajectory_seed_is_reproducible(tmp_path):
    path = tmp_path / "model.bngl"
    path.write_text(BIRTH_DEATH)
    model = _cpp.parse_file(str(path))
    network = _cpp.generate_network(model)
    runs = [
        np.asarray(
            _cpp.simulate_ssa(model, network, t_end=100.0, n_steps=10, seed=4242)[
                "concentrations"
            ]
        )
        for _ in range(3)
    ]
    for r in runs[1:]:
        assert np.array_equal(runs[0], r)


def test_seed_zero_is_the_system_default_and_is_not_reproducible(tmp_path):
    """``seed=0`` means "draw a fresh seed", so it must NOT be reproducible.

    This is BNG2-compatible and deliberate, not a bug, and it is kept rather
    than turned into a refusal. Pinning it stops the contract drifting in
    either direction: making ``seed=0`` mean literal seed 0 would silently
    change what a reproducibility claim means for every model that relies on
    the default. The matching rule for contributors is that no test may assert
    reproducibility from a ``seed=0`` run — the test above uses 4242 — and no
    performance claim may quote reproducibility evidence from one.
    """
    path = tmp_path / "model.bngl"
    path.write_text(BIRTH_DEATH)
    model = _cpp.parse_file(str(path))
    network = _cpp.generate_network(model)
    runs = [
        np.asarray(
            _cpp.simulate_ssa(model, network, t_end=100.0, n_steps=10, seed=0)[
                "concentrations"
            ]
        )
        for _ in range(3)
    ]
    assert not all(
        np.array_equal(runs[0], r) for r in runs[1:]
    ), "seed=0 produced identical trajectories; it must draw a fresh seed"
