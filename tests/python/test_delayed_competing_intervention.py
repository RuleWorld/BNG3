"""Independent delayed-jump-process qualification for a competing NonConsuming completion (#475).

Predeclared seed budget, analytic Poisson law, tolerances and wire-format
semantics: analysis/c-delay-competing/PREDECLARED_PLAN.md.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import bionetgen
from bionetgen import BioNetGenModel
from bionetgen.bngir import EqualityUndecided, semantic_equal

PLAN_SHA256 = "7fe66c893885c6d653a10d2a484e17a103168b80114ec451ac5cd1af90d2ca3a"

SOURCE = """begin model
begin parameters
  tau 1.0
  k 2.0
  kd 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 20
  B() 0
end seed species
begin observables
  Molecules A A()
  Molecules B B()
end observables
begin reaction rules
  A() -> A() + B() k delay=tau NonConsuming
  B() -> 0 kd
end reaction rules
end model
"""

SAMPLE_TIMES = [1.5, 2.0, 3.0, 4.0]
SEED_BASE = 7000
N_RUNS = 300


def _cpp():
    return bionetgen.model._cpp


def _model(source=SOURCE):
    return BioNetGenModel(_cpp().parse_string(source))


def _poisson_lambda(t):
    """Independent law: 80*(1-exp(-0.5(t-1))) for t>=1, else 0."""
    return 0.0 if t < 1.0 else 80.0 * (1.0 - math.exp(-0.5 * (t - 1.0)))


def _ssa_uninterrupted(seed):
    res = _model().simulate(
        method="ssa",
        t_start=0.0,
        t_end=4.0,
        sample_times=SAMPLE_TIMES,
        seed=seed,
    )
    return np.asarray(res.observables["B"], dtype=float)


def _ssa_split(seed):
    m = _model()
    m.simulate(method="ssa", t_start=0.0, t_end=0.5, sample_times=[0.5], seed=seed)
    res = m.simulate(
        method="ssa",
        t_start=0.5,
        t_end=4.0,
        sample_times=SAMPLE_TIMES,
        seed=seed,
        continue_simulation=True,
    )
    return np.asarray(res.observables["B"], dtype=float)


def test_delayed_nonconsuming_competing_decay_ode_split_and_uninterrupted():
    """Analytic DDE law and state continuity across pre- and post-completion splits."""
    model = _model()
    full = model.simulate(method="ode", t_end=4.0, n_steps=80, rtol=1e-9, atol=1e-12)
    t = np.asarray(full.time)
    expected = np.where(t < 1.0, 0.0, 80.0 * (1.0 - np.exp(-0.5 * (t - 1.0))))
    np.testing.assert_allclose(full.observables["B"], expected, rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(full.observables["A"], 20.0, rtol=1e-9)

    for boundary in (0.5, 2.0):
        m = _model()
        p1 = m.simulate(method="ode", t_start=0.0, t_end=boundary, n_steps=10)
        p2 = m.simulate(
            method="ode",
            t_start=boundary,
            t_end=4.0,
            n_steps=70,
            continue_simulation=True,
            rtol=1e-9,
            atol=1e-12,
        )
        np.testing.assert_allclose(
            p2.observables["B"][-1], expected[-1], rtol=1e-5, atol=1e-6
        )
        # Boundary state is preserved: resume equals the end of the first run.
        np.testing.assert_allclose(
            p2.observables["B"][0], p1.observables["B"][-1], rtol=1e-6, atol=1e-8
        )


def test_delayed_nonconsuming_competing_decay_ssa_poisson_law():
    """Independent Poisson law with predeclared seeds, 4-sigma control and wrong-law controls."""
    full = np.array([_ssa_uninterrupted(SEED_BASE + i) for i in range(N_RUNS)])
    split = np.array([_ssa_split(SEED_BASE + i) for i in range(N_RUNS)])

    for j, t in enumerate(SAMPLE_TIMES):
        lam = _poisson_lambda(t)
        sigma = math.sqrt(lam / N_RUNS)
        assert abs(full[:, j].mean() - lam) <= 4.0 * sigma
        assert abs(split[:, j].mean() - lam) <= 4.0 * sigma
        assert abs(full[:, j].var() - lam) <= 0.5 * lam
        assert np.all(full[:, j] >= 0)
        # Split and uninterrupted runs obey the same law (pending queue survives).
        assert abs(full[:, j].mean() - split[:, j].mean()) <= 4.0 * math.sqrt(
            2.0 * lam / N_RUNS
        )

    j = SAMPLE_TIMES.index(3.0)
    observed = full[:, j].mean()
    # Wrong-implementation controls (must be rejected by the analytic law).
    no_decay = 40.0 * (3.0 - 1.0)
    assert abs(observed - no_decay) > 4.0 * math.sqrt(_poisson_lambda(3.0) / N_RUNS)
    halved = 40.0 * (1.0 - math.exp(-0.5 * (3.0 - 1.0)))
    assert abs(observed - halved) > 4.0 * math.sqrt(halved / N_RUNS)


def _find_key(node, key):
    """Recursively locate the first value for a key in a BNGIR document."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


def test_delayed_nonconsuming_bngir_reconstruction_source_law():
    """v0.1/v0.2 documents carry the delay law and reconstruct into a real consumer."""
    import json

    model = _model()
    for version in ("0.1", "0.2"):
        document = model.to_bngir(version=version)
        parsed = json.loads(document) if isinstance(document, str) else dict(document)
        # Wire format is a model specification, not a live pending-queue checkpoint.
        assert _find_key(parsed, "delay") is not None
        assert _find_key(parsed, "non_consuming") is True
        restored = bionetgen.from_bngir(parsed)
        res = restored.simulate(
            method="ode", t_end=4.0, n_steps=80, rtol=1e-9, atol=1e-12
        )
        expected = np.where(
            np.asarray(res.time) < 1.0,
            0.0,
            80.0 * (1.0 - np.exp(-0.5 * (np.asarray(res.time) - 1.0))),
        )
        np.testing.assert_allclose(res.observables["B"], expected, rtol=1e-5, atol=1e-6)

        # Distribution-level downstream check on the reconstructed model.
        samples = []
        for i in range(100):
            restored.reset_simulation()
            r = restored.simulate(
                method="ssa",
                t_start=0.0,
                t_end=4.0,
                sample_times=[3.0, 4.0],
                seed=8100 + i,
            )
            samples.append(float(r.observables["B"][0]))
        lam = _poisson_lambda(3.0)
        assert abs(np.mean(samples) - lam) <= 4.0 * math.sqrt(lam / 100)


def test_delayed_semantic_equal_counterexamples():
    """Changing the delay or NonConsuming flag must never certify equality."""
    base = _model()
    variants = [
        _model(SOURCE.replace("tau 1.0", "tau 2.0")),
        _model(SOURCE.replace(" delay=tau NonConsuming", " delay=tau")),
    ]
    for other in variants:
        try:
            result = semantic_equal(base, other)
        except EqualityUndecided:
            continue  # Explicit honest decline is allowed by the predeclared plan.
        assert result is False
