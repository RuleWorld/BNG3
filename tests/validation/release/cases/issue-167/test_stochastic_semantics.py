"""Bounded formal propensity, ensemble mean, and kernel proof comparisons for #167."""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "tests" / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _extdep import require_extension  # noqa: E402

import formal_semantics as fm  # noqa: E402

_cpp = require_extension()

BATCH = 4000
SEED = 167
Z_LIMIT = 5.0
T_END = 1.0
N_STEPS = 8


def _network(case: fm.Case, tmp_path):
    path = tmp_path / f"{case.id}.bngl"
    path.write_text(fm.bngl_for(case), encoding="utf-8")
    model = _cpp.parse_file(str(path))
    network = _cpp.generate_network(model)
    return model, network


def _hazard(case: fm.Case, n: int) -> float:
    """Hazard of the declared count law at population n, independent of engine."""
    k = float(case.k)
    if case.convention == "localFunctionState":
        return k * n * n  # f() = k*nA, multiplied by the reactant multiplicity n
    if case.convention == "saturation":
        return k * n / (float(case.constants[1]) + n)
    if case.convention == "hill":
        K = float(case.constants[1])
        h = case.exponent
        return k * n**h / (K**h + n**h)
    if case.symmetry_factor == 2:
        return k * n * (n - 1) / 2.0
    return k * n


def _analytic_moments(case: fm.Case, times) -> np.ndarray:
    """Integrate the pure-death master equation of the declared law."""
    step = 2 if case.symmetry_factor == 2 else 1
    states = list(range(case.n0, -1, -step))
    idx = {value: i for i, value in enumerate(states)}
    rates = [_hazard(case, n) for n in states]
    weights = np.zeros(len(states))
    weights[idx[case.n0]] = 1.0
    out = np.zeros((len(times), 2))
    counts = np.asarray(states)

    def moments():
        mean = weights @ counts
        return mean, weights @ ((counts - mean) ** 2)

    t = 0.0
    # Fine fixed-step RK4; the law is smooth on [0, T_END].
    dt = 1e-4
    ti = 0
    while ti < len(times) and times[ti] <= t + 1e-12:
        out[ti] = moments()
        ti += 1

    def deriv(w):
        d = np.zeros_like(w)
        for i in range(len(states)):
            d[i] -= rates[i] * w[i]
            if i + 1 < len(states):
                d[i + 1] += rates[i] * w[i]
        return d

    total_steps = int(math.ceil(max(times) / dt))
    for _ in range(total_steps):
        k1 = deriv(weights)
        k2 = deriv(weights + 0.5 * dt * k1)
        k3 = deriv(weights + 0.5 * dt * k2)
        k4 = deriv(weights + dt * k3)
        weights = weights + dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
        t += dt
        while ti < len(times) and times[ti] <= t + 1e-12:
            out[ti] = moments()
            ti += 1
    while ti < len(times):
        out[ti] = moments()
        ti += 1
    return out


def _coefficient(model, network, state):
    return list(
        _cpp._validation_ode_rate_coefficients(model, network, 0.0, list(state))
    )


def _as_fraction(value: float) -> Fraction:
    return Fraction(float(value)).limit_denominator(10**6)


# ---------------------------------------------------------------------------
# release-stochastic-correspondence
# ---------------------------------------------------------------------------


def test_exact_propensity_matches_production_coefficients(tmp_path):
    """Formal exact propensity equals the engine's compiled propensity.

    For ordinary laws the engine coefficient is the prefixed rate ``factor*k``
    and the propensity multiplies it by the ordered embedding count.  For
    special rate laws the engine coefficient already evaluates the law at the
    current count and equals the propensity directly.
    """
    for case in fm.CASES:
        if case.convention == "tfun":
            continue  # time-dependent table function: network law identity only
        model, network = _network(case, tmp_path)
        state = [float(case.n0), 0.0]
        formal = case.formal_channel().exact_propensity(case.initial_state())
        coeff = _as_fraction(_coefficient(model, network, state)[0])
        factor = _as_fraction(network.reaction_factors[0])
        raw = fm.raw_embeddings(case.initial_state(), case.reactants)
        if case.convention in {"saturation", "hill", "michaelisMenten"}:
            production = coeff
        else:
            production = coeff * raw
        assert (
            production == formal
        ), f"{case.id}: production propensity {production} != formal {formal}"
        # The generated factor is the rule's reactant symmetry prefix.
        expected_factor = Fraction(1, 2) if case.symmetry_factor == 2 else Fraction(1)
        assert factor == expected_factor, (case.id, factor)
        assert case.rate_law_symbol in network.reaction_rate_laws[0], (
            case.id,
            network.reaction_rate_laws[0],
        )


def test_tfun_network_identity(tmp_path):
    """The table-function convention is carried into the generated network.

    Its seeded SSA distribution is a disposition: a time-dependent functional
    rate is refused by the direct SSA path by contract, so this case establishes
    the production/formal convention identity only, not a distribution claim.
    """
    case = fm.CASES_BY_ID["tfun-n20-k04"]
    model, network = _network(case, tmp_path)
    assert "tfun" in network.reaction_rate_laws[0].lower()
    assert (
        case.formal_channel().exact_propensity(case.initial_state()) == case.k * case.n0
    )
    assert case.distribution_supported is False


def test_seeded_ensemble_mean_matches_master_equation(tmp_path):
    """Compare each sampled mean using variance from the independent count law."""
    for case in fm.CASES:
        if not case.distribution_supported:
            continue
        model, network = _network(case, tmp_path)
        result = _cpp.simulate_batch_ssa_cpu(
            model,
            network,
            batch_size=BATCH,
            t_end=T_END,
            n_steps=N_STEPS,
            threads=0,
            base_seed=SEED,
        )
        times = np.asarray(result["time"], dtype=float)
        means = np.asarray(result["observable_means"]["nA"], dtype=float)
        analytic = _analytic_moments(case, times)
        assert means[0] == case.n0 and analytic[0, 0] == case.n0
        worst = 0.0
        for observed, (expected, variance) in zip(means[1:], analytic[1:]):
            se = math.sqrt(variance / BATCH)
            assert se > 0
            z = (float(observed) - float(expected)) / se
            worst = max(worst, abs(z))
        assert worst < Z_LIMIT, f"{case.id}: ensemble vs analytic max |Z|={worst:.2f}"


def test_stochastic_proofs_and_axioms():
    lean_dir = ROOT / "formal" / "lean"
    if shutil.which("lake") is None:
        pytest.skip("pinned Lean toolchain (lake) is not installed on this host")
    proof = subprocess.run(
        ["lake", "env", "lean", "tests/Issue167Proofs.lean"],
        cwd=lean_dir,
        capture_output=True,
        text=True,
    )
    assert proof.returncode == 0, proof.stderr
    assert proof.stdout.strip(), "Issue167Proofs.lean produced no kernel output"
    audit = subprocess.run(
        ["./scripts/check_axiom_dependencies.sh"],
        cwd=lean_dir,
        capture_output=True,
        text=True,
    )
    assert audit.returncode == 0, audit.stderr
    assert "AXIOM AUDIT PASS" in audit.stdout
