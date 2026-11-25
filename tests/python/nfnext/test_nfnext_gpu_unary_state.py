"""Physical-device qualification for the NFnext unary state-change GPU slice."""

import math

import numpy as np
import pytest

from bionetgen import gpu_backend_capabilities
from bionetgen.model import BioNetGenModel, _cpp as cpp

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


BONDED_MODEL = """begin model
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 1
  B(a) 1
end seed species
begin observables
  Molecules A_free A(b)
end observables
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) 1.0
end reaction rules
end model
"""


BOUND_RULE_MODEL = """begin model
begin parameters
  kf 0.5
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 10
end seed species
begin reaction rules
  A(x~u!+) -> A(x~p!+) kf
end reaction rules
end model
"""


TIMES = (0.0, 0.5, 1.0, 2.0, 5.0)
PARTICLES = 100
BATCH_SIZE = 2048
KF = 0.5
KR = 0.3
SEED = 474141


def _analytic_fraction_p(time):
    return KF / (KF + KR) * (1.0 - math.exp(-(KF + KR) * time))


def _metal_available():
    return any(
        backend["name"] == "metal" and backend["compiled"] and backend["available"]
        for backend in gpu_backend_capabilities()
    )


def _cuda_available():
    return any(
        backend["name"] == "cuda" and backend["compiled"] and backend["available"]
        for backend in gpu_backend_capabilities()
    )


def test_gpu_backend_report_distinguishes_compilation_from_device_availability():
    backends = gpu_backend_capabilities()
    assert {backend["name"] for backend in backends} == {"cuda", "metal"}
    for backend in backends:
        assert not backend["available"] or backend["compiled"]
        if "nfnext_unary_state_change" in backend["implemented_routes"]:
            assert backend["name"] in {"metal", "cuda"}
            assert backend["compiled"]


def _assert_unary_state_change_backend(backend_name: str):
    model = BioNetGenModel(cpp.parse_string(MODEL))
    result = model.simulate_nfnext_gpu(
        list(TIMES),
        seed=SEED,
        batch_size=BATCH_SIZE,
        backend=backend_name,
    )

    assert result.backend == backend_name
    assert result.device
    assert result.engine == "nfnext-gpu"
    assert result.wall_time_ms >= result.dispatch_wait_time_ms > 0.0
    assert np.array_equal(np.asarray(result.time), np.asarray(TIMES))
    p = np.asarray(result.observables["P"])
    u = np.asarray(result.observables["U"])
    assert p.shape == (BATCH_SIZE, len(TIMES))
    assert u.shape == (BATCH_SIZE, len(TIMES))
    assert np.array_equal(p[:, 0], np.zeros(BATCH_SIZE))
    assert np.array_equal(u[:, 0], np.full(BATCH_SIZE, PARTICLES))
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
        assert (
            0.9 <= variance_ratio <= 1.1
        ), f"sample time {time}: observed/expected variance={variance_ratio:.4f}"

    # A no-reverse-rate implementation has a different closed-form law and
    # must not fit this declared CTMC sample.
    p_no_reverse = 1.0 - math.exp(-KF * TIMES[-1])
    wrong_mean = PARTICLES * p_no_reverse
    right_variance = (
        PARTICLES
        * _analytic_fraction_p(TIMES[-1])
        * (1.0 - _analytic_fraction_p(TIMES[-1]))
    )
    right_se = math.sqrt(right_variance / BATCH_SIZE)
    assert abs(float(np.mean(p[:, -1])) - wrong_mean) > 10.0 * right_se

    replay = model.simulate_nfnext_gpu(
        list(TIMES),
        seed=SEED,
        batch_size=BATCH_SIZE,
        backend=backend_name,
    )
    interleaved = model.simulate_nfnext_gpu(
        list(TIMES),
        seed=SEED + 1,
        batch_size=64,
        backend=backend_name,
    )
    prefix = model.simulate_nfnext_gpu(
        list(TIMES),
        seed=SEED,
        batch_size=64,
        backend=backend_name,
    )
    for observable in ("U", "P"):
        assert np.array_equal(
            np.asarray(result.observables[observable]),
            np.asarray(replay.observables[observable]),
        )
        assert np.array_equal(
            np.asarray(result.observables[observable])[:64],
            np.asarray(prefix.observables[observable]),
        )
    assert np.array_equal(result.event_counts, replay.event_counts)
    assert not np.array_equal(result.event_counts[:64], interleaved.event_counts)


@pytest.mark.skipif(not _metal_available(), reason="physical Metal device unavailable")
def test_unary_state_change_metal_batch_matches_exact_ctmc_and_replays():
    _assert_unary_state_change_backend("metal")


def test_unary_state_change_cuda_batch_matches_exact_ctmc_and_replays():
    if not _cuda_available():
        return
    _assert_unary_state_change_backend("cuda")


def test_nfnext_gpu_refuses_bond_form_before_backend_selection():
    model = BioNetGenModel(cpp.parse_string(BONDED_MODEL))
    with pytest.raises(RuntimeError, match="unary single-site state-change"):
        model.simulate_nfnext_gpu(
            [0.0, 1.0],
            batch_size=16,
            backend="metal",
        )


def test_nfnext_gpu_refuses_bound_rule_constraint():
    model = BioNetGenModel(cpp.parse_string(BOUND_RULE_MODEL))
    with pytest.raises(RuntimeError, match="invariant free-site constraint only"):
        model.simulate_nfnext_gpu(
            [0.0, 1.0],
            batch_size=16,
            backend="metal",
        )


def test_nfnext_gpu_refuses_observable_counts_outside_float_exact_range():
    model_source = MODEL.replace("  A(x~u) 100", "  A(x~u) 16777217")
    model = BioNetGenModel(cpp.parse_string(model_source))
    with pytest.raises(
        RuntimeError, match="exact (?:Metal|GPU) single-precision observable counts"
    ):
        model.simulate_nfnext_gpu(
            [0.0, 1.0],
            batch_size=1,
            backend="metal",
            max_particles=(1 << 32) - 1,
        )


def test_nfnext_gpu_refuses_output_index_overflow_before_device_selection():
    model_source = MODEL.replace("  A(x~u) 100", "  A(x~u) 0")
    model = BioNetGenModel(cpp.parse_string(model_source))
    with pytest.raises(
        RuntimeError, match="output element count exceeds (?:Metal|GPU) kernel indexing"
    ):
        model.simulate_nfnext_gpu(
            [0.0, 1.0],
            batch_size=1 << 31,
            backend="metal",
            max_particles=0,
        )


def test_nfnext_gpu_cuda_selection_refuses_without_cpu_or_metal_fallback():
    model = BioNetGenModel(cpp.parse_string(MODEL))
    if _cuda_available():
        with pytest.raises(
            RuntimeError, match="backend must explicitly select 'metal' or 'cuda'"
        ):
            model.simulate_nfnext_gpu(
                list(TIMES),
                batch_size=16,
                backend="unsupported",
            )
        return
    with pytest.raises(
        RuntimeError,
        match=(
            "network-free CUDA execution is not implemented|"
            "CUDA backend is not compiled into this build|"
            "CUDA backend has no usable device"
        ),
    ):
        model.simulate_nfnext_gpu(
            list(TIMES),
            batch_size=16,
            backend="cuda",
        )
