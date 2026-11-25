"""Focused regression tests for full network-free GPU graph SSA (issue #474)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import bionetgen

REPO = Path(__file__).resolve().parents[3]


def _usable_gpu_backend() -> str | None:
    for entry in bionetgen.gpu_backend_capabilities():
        if entry.get("available") and "nfnext_graph_corpus" in entry.get(
            "implemented_routes", []
        ):
            return str(entry["name"])
    return None


@pytest.mark.parametrize(
    ("model_rel", "times", "expected_observables"),
    [
        (
            "models/flagellar_motor/motor.bngl",
            [0.0, 2.5, 5.0],
            ("CheYp", "MotCW", "MotCCW"),
        ),
        (
            "models/simple_system.bngl",
            [0.0, 0.25, 0.5],
            ("X_free", "X_p_total", "Xp_free", "XY", "Ytotal", "Xtotal"),
        ),
        (
            "models/localfunc.bngl",
            [0.0, 2.5, 5.0],
            ("Atot", "Btot", "Ctot", "AB0", "AB1", "AB2", "AB3", "AB_motif"),
        ),
        (
            "models/tlbr/tlbr.bngl",
            [0.0, 5.0, 10.0],
            ("Rfree", "Lfree"),
        ),
    ],
)
def test_nfnext_gpu_graph_corpus_runs_and_replays_deterministically(
    model_rel: str, times: list[float], expected_observables: tuple[str, ...]
):
    backend = _usable_gpu_backend()
    if backend is None:
        pytest.skip("no usable GPU backend with nfnext_graph_corpus route")

    model = bionetgen.load(str(REPO / model_rel))
    res1 = model.simulate_nfnext_gpu(
        times,
        seed=12345,
        batch_size=16,
        backend=backend,
        mode="graph",
        max_events=20_000_000,
    )
    res2 = model.simulate_nfnext_gpu(
        times,
        seed=12345,
        batch_size=16,
        backend=backend,
        mode="graph",
        max_events=20_000_000,
    )

    assert res1.backend == backend
    assert tuple(res1.observable_names) == expected_observables
    assert len(res1.event_counts) == 16
    assert int(sum(res1.event_counts)) > 0

    for name in expected_observables:
        a = res1.observables[name]
        b = res2.observables[name]
        assert a.shape == (16, len(times))
        assert np.array_equal(
            a, b
        ), f"non-deterministic GPU replay on {model_rel}:{name}"


def test_nfnext_gpu_graph_conservation_invariants():
    backend = _usable_gpu_backend()
    if backend is None:
        pytest.skip("no usable GPU backend with nfnext_graph_corpus route")

    # simple_system: Xtotal == 5000, Ytotal == 500, X_free + XY + X_p_total == 5000
    simple = bionetgen.load(
        str(REPO / "models/simple_system.bngl")
    ).simulate_nfnext_gpu(
        [0.0, 0.25, 0.5], seed=7, batch_size=32, backend=backend, mode="graph"
    )
    assert np.all(simple.observables["Xtotal"] == 5000.0)
    assert np.all(simple.observables["Ytotal"] == 500.0)
    assert np.all(
        simple.observables["X_free"]
        + simple.observables["XY"]
        + simple.observables["X_p_total"]
        == 5000.0
    )

    # localfunc: AB0 + AB1 + AB2 + AB3 == 1, AB1 + 2*AB2 + 3*AB3 == AB_motif
    local = bionetgen.load(str(REPO / "models/localfunc.bngl")).simulate_nfnext_gpu(
        [0.0, 2.5, 5.0], seed=9, batch_size=32, backend=backend, mode="graph"
    )
    assert np.all(local.observables["Atot"] == 1.0)
    assert np.all(local.observables["Btot"] == 3.0)
    assert np.all(
        local.observables["AB0"]
        + local.observables["AB1"]
        + local.observables["AB2"]
        + local.observables["AB3"]
        == 1.0
    )
    assert np.all(
        local.observables["AB1"]
        + 2.0 * local.observables["AB2"]
        + 3.0 * local.observables["AB3"]
        == local.observables["AB_motif"]
    )


def test_nfnext_gpu_graph_refuses_unsupported_constructs_fail_closed(tmp_path: Path):
    backend = _usable_gpu_backend()
    if backend is None:
        pytest.skip("no usable GPU backend with nfnext_graph_corpus route")

    # Multi-copy local-function scope must refuse rather than approximate globally
    multi_local = """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A(b)
  B(a)
  C()
end molecule types
begin seed species
  A(b) 2
  B(a) 2
  C() 0
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
  Molecules Ctot C()
end observables
begin functions
  f(x) = k * AB(x)
end functions
begin reaction rules
  %x::A() -> %x::A() + C() f(x)
  A(b) + B(a) <-> A(b!1).B(a!1) 1.0, 0.5
end reaction rules
end model
"""
    multi_path = tmp_path / "multi_local.bngl"
    multi_path.write_text(multi_local, encoding="utf-8")
    with pytest.raises(RuntimeError, match="multi-copy local-function scoping"):
        bionetgen.load(str(multi_path)).simulate_nfnext_gpu(
            [0.0, 1.0], seed=1, batch_size=4, backend=backend, mode="graph"
        )

    # Compartments must fail closed
    comp_model = """begin model
begin compartments
  EC 3 10
  PM 2 1 EC
end compartments
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  @EC:A(x~u) 10
end seed species
begin observables
  Molecules Au A(x~u)
end observables
begin reaction rules
  @EC:A(x~u) -> @EC:A(x~p) 1.0
end reaction rules
end model
"""
    comp_path = tmp_path / "comp.bngl"
    comp_path.write_text(comp_model, encoding="utf-8")
    with pytest.raises(RuntimeError, match="compartments"):
        bionetgen.load(str(comp_path)).simulate_nfnext_gpu(
            [0.0, 1.0], seed=1, batch_size=4, backend=backend, mode="graph"
        )
