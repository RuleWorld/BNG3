"""CUDA unary state-change route checks for simulate_nfnext_gpu."""

from __future__ import annotations

import math

import numpy as np
import pytest

from bionetgen import gpu_backend_capabilities
from bionetgen.model import BioNetGenModel, _cpp as cpp

KF = 0.5
KR = 0.3
PARTICLES = 100
TIMES = (0.0, 0.25, 0.75, 1.5, 3.0)
BATCH_SIZE = 2048
SEED = 47401

MODEL = """begin model
begin parameters
  kf 0.5
  kr 0.3
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 100
end seed species
begin observables
  Molecules U A(x~u)
  Molecules P A(x~p)
end observables
begin reaction rules
  A(x~u) -> A(x~p) kf
  A(x~p) -> A(x~u) kr
end reaction rules
end model
"""


def _analytic_fraction_p(time: float) -> float:
    total = KF + KR
    return (KF / total) * (1.0 - math.exp(-total * time))


def _cuda_available() -> bool:
    return any(
        backend["name"] == "cuda" and backend["compiled"] and backend["available"]
        for backend in gpu_backend_capabilities()
    )


def test_cuda_nfnext_route_capability_matches_compilation():
    backends = {backend["name"]: backend for backend in gpu_backend_capabilities()}
    assert {"cuda", "metal"} <= set(backends)
    cuda = backends["cuda"]
    assert not cuda["available"] or cuda["compiled"]
    if cuda["compiled"]:
        assert "nfnext_unary_state_change" in cuda["implemented_routes"]
    else:
        assert "nfnext_unary_state_change" not in cuda["implemented_routes"]


def test_cuda_nfnext_unary_state_ctmc_and_no_fallback():
    model = BioNetGenModel(cpp.parse_string(MODEL))
    if not _cuda_available():
        with pytest.raises(
            RuntimeError,
            match=(
                "CUDA backend is not compiled into this build|"
                "CUDA backend has no usable device"
            ),
        ):
            model.simulate_nfnext_gpu(list(TIMES), batch_size=16, backend="cuda")
        return

    result = model.simulate_nfnext_gpu(
        list(TIMES),
        seed=SEED,
        batch_size=BATCH_SIZE,
        backend="cuda",
    )
    assert result.backend == "cuda"
    assert result.device
    assert result.engine == "nfnext-gpu"
    assert result.wall_time_ms >= result.dispatch_wait_time_ms > 0.0
    p = np.asarray(result.observables["P"])
    u = np.asarray(result.observables["U"])
    assert p.shape == (BATCH_SIZE, len(TIMES))
    assert np.array_equal(p + u, np.full((BATCH_SIZE, len(TIMES)), PARTICLES))

    for index, time in enumerate(TIMES[1:], start=1):
        probability = _analytic_fraction_p(time)
        expected_mean = PARTICLES * probability
        expected_variance = PARTICLES * probability * (1.0 - probability)
        observed_mean = float(np.mean(p[:, index]))
        observed_variance = float(np.var(p[:, index], ddof=1))
        standard_error = math.sqrt(expected_variance / BATCH_SIZE)
        assert abs(observed_mean - expected_mean) <= 5.0 * standard_error
        variance_ratio = observed_variance / expected_variance
        assert 0.9 <= variance_ratio <= 1.1

    replay = model.simulate_nfnext_gpu(
        list(TIMES),
        seed=SEED,
        batch_size=BATCH_SIZE,
        backend="cuda",
    )
    for observable in ("U", "P"):
        assert np.array_equal(
            np.asarray(result.observables[observable]),
            np.asarray(replay.observables[observable]),
        )
    assert np.array_equal(result.event_counts, replay.event_counts)

    with pytest.raises(
        RuntimeError, match="backend must explicitly select 'metal' or 'cuda'"
    ):
        model.simulate_nfnext_gpu(list(TIMES), batch_size=16, backend="unsupported")
