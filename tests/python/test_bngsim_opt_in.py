"""Focused regression tests for the opt-in LANL BNGsim backend surface.

Verifies:
- Native BNG3 solvers remain the strict default across Python API, scans,
  sensitivities, CLI, and BNGL action execution.
- Public capability introspection (``bionetgen.bngsim_available()``,
  ``bionetgen.bngsim_capabilities()``, ``bionetgen.bngsim_version()``, and
  ``model.check_bngsim_lowering()``).
- Explicit fail-closed diagnostics when ``backend="bngsim"`` is opted into
  without an available adapter/package, on unsupported methods/options, or on
  unsupported model constructs (events, delays, compartments, energy,
  non-reference rates, local function args, population maps).
- Optional Python ``bngsim`` package bridge end-to-end with an analytic
  in-memory fake ``bngsim`` module (never silently falling back to native).
- CLI ``--backend`` option across ``run``, ``scan``, and ``sensitivity``,
  conflict detection with ``--no-bngsim``, and ``info --detail`` reporting.
"""

from __future__ import annotations

import math
import sys
import textwrap
import types
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

import bionetgen
from bionetgen.cli import main as cli_main

DECAY_BNGL = textwrap.dedent("""
begin model
begin parameters
    k 0.2
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")

TWO_PARAM_BNGL = textwrap.dedent("""
begin model
begin parameters
    k1 0.2
    k2 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
    B() 0
end seed species
begin observables
    Molecules Atot A()
    Molecules Btot B()
end observables
begin reaction rules
    A() -> B() k1
    B() -> A() k2
end reaction rules
end model
""")

EVENT_BNGL = textwrap.dedent("""
begin model
begin parameters
    k 0.5
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules X A()
end observables
begin reaction rules
    A() -> 0 k
end reaction rules
begin bng3_events version 1
    event "reset"
    trigger: X <= 5
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: X = 10
    end event
end bng3_events
end model
""")

DELAY_BNGL = textwrap.dedent("""
begin model
begin parameters
    k 0.2
    tau 1.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules Aobs A()
    Molecules Bobs B()
end observables
begin reaction rules
    A() -> B() k delay=tau
end reaction rules
end model
""")

EVENT_DISTRIB_BNGL = textwrap.dedent("""
begin model
begin parameters
    k 0.5
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules X A()
end observables
begin reaction rules
    A() -> 0 k
end reaction rules
begin bng3_events version 1
    event "draw"
    trigger: time >= 1
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    assignment: X = distrib_uniform(1, 5)
    end event
end bng3_events
end model
""")

DYNAMIC_COMPARTMENT_BNGL = textwrap.dedent("""
begin model
begin parameters
    k 0.1
end parameters
begin compartments
    CYT 3 1+time
end compartments
begin molecule types
    X()
end molecule types
begin seed species
    @CYT:X() 10
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    @CYT:X() -> 0 k
end reaction rules
end model
""")

COMPARTMENT_PARAM_BNGL = textwrap.dedent("""
begin model
begin parameters
    kbind 0.5
    kunbind 0.1
end parameters
begin compartments
    EC 3 10.0
    PM 2 2.0 EC
end compartments
begin molecule types
    L(r)
    R(l)
end molecule types
begin seed species
    @EC:L(r) 40
    @PM:R(l) 20
end seed species
begin observables
    Molecules RL @PM:L(r!1).R(l!1)
end observables
begin reaction rules
    @EC:L(r) + @PM:R(l) <-> @PM:L(r!1).R(l!1) kbind, kunbind
end reaction rules
end model
""")

TOTALRATE_BNGL = textwrap.dedent("""
begin model
begin parameters
    k 0.05
end parameters
begin molecule types
    A()
    D()
end molecule types
begin seed species
    A() 10
    D() 0
end seed species
begin observables
    Molecules Atot A()
    Molecules Dtot D()
end observables
begin reaction rules
    A() + A() -> D() k TotalRate
end reaction rules
end model
""")

EVENT_PARAM_BNGL = textwrap.dedent("""
begin model
begin parameters
    k 0.2
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
    B() 0
end seed species
begin observables
    Molecules Aobs A()
    Molecules Bobs B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
begin bng3_events version 1
    event "boost"
    trigger: time >= 1.0
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    delay: 0.5
    assignment: k = 1.0
    end event
end bng3_events
end model
""")

ENERGY_BNGL = textwrap.dedent("""
begin model
begin parameters
    RT 0.6
end parameters
begin molecule types
    A(x~u~p)
end molecule types
begin seed species
    A(x~u) 10
end seed species
begin energy patterns
    A(x~p) 1.0
end energy patterns
begin reaction rules
    A(x~u) -> A(x~p) 1.0
end reaction rules
end model
""")

NON_REF_RATE_BNGL = textwrap.dedent("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin reaction rules
    X() -> 0 k*2
end reaction rules
end model
""")

LOCAL_FUNC_BNGL = textwrap.dedent("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A(b)
end molecule types
begin seed species
    A(b) 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin functions
    f(x) = k
end functions
begin reaction rules
    A(b) -> 0 k
end reaction rules
end model
""")


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _make_fake_python_bngsim(
    *,
    return_wrong_sample_len: bool = False,
    recorded_calls: list | None = None,
):
    """Build a minimal in-memory fake LANL ``bngsim`` module for bridge tests."""
    calls = recorded_calls if recorded_calls is not None else []
    mod = types.ModuleType("bngsim")
    mod.__version__ = "0.18.0-fake"

    class FakeModel:
        def __init__(self, net_text: str):
            self.net_text = net_text
            # Parse first parameter k and initial species amount from .net
            self.k = 0.2
            self.x0 = 100.0
            self.obs_names: list[str] = []
            section = None
            for raw_line in net_text.splitlines():
                line = raw_line.split("#", 1)[0].strip()
                if not line:
                    continue
                if line.startswith("begin "):
                    section = line[6:].strip()
                    continue
                if line.startswith("end "):
                    section = None
                    continue
                parts = line.split()
                if section == "parameters" and len(parts) >= 3 and parts[1] == "k":
                    self.k = float(parts[2])
                elif section == "species" and len(parts) >= 3:
                    self.x0 = float(parts[2])
                elif section == "groups" and len(parts) >= 2:
                    self.obs_names.append(parts[1])

        @classmethod
        def from_net(cls, path: str) -> "FakeModel":
            text = Path(path).read_text(encoding="utf-8")
            calls.append(("from_net", text))
            return cls(text)

    class FakeResult:
        def __init__(self, time, species, observables, observable_names):
            self.time = time
            self.species = species
            self.observables = observables
            self.observable_names = observable_names

    class FakeSimulator:
        def __init__(
            self,
            model: FakeModel,
            method: str = "ode",
            poplevel: float | None = None,
        ):
            self.model = model
            self.method = method
            self.poplevel = poplevel
            calls.append(("Simulator", method, poplevel))

        def run(self, **kwargs):
            calls.append(("run", dict(kwargs)))
            if "sample_times" in kwargs:
                times = np.asarray(kwargs["sample_times"], dtype=float)
                if return_wrong_sample_len:
                    times = times[:-1]
            else:
                t0, t1 = kwargs["t_span"]
                n_points = kwargs["n_points"]
                times = np.linspace(t0, t1, n_points)
            if self.method == "ode":
                x = self.model.x0 * np.exp(-self.model.k * times)
            else:
                # Deterministic seeded integer counts for SSA bridge test
                rng = np.random.default_rng(kwargs.get("seed", 0))
                x = np.maximum(
                    0.0,
                    np.round(
                        self.model.x0 * np.exp(-self.model.k * times)
                        + rng.normal(0.0, 0.0, size=times.shape)
                    ),
                )
            species = x[:, None]
            observables = (
                x[:, None] if self.model.obs_names else np.empty((len(times), 0))
            )
            return FakeResult(times, species, observables, list(self.model.obs_names))

    mod.Model = FakeModel
    mod.Simulator = FakeSimulator
    return mod


# ---------------------------------------------------------------------------
# 1. Public introspection & native default contract
# ---------------------------------------------------------------------------


def test_public_bngsim_introspection_api():
    assert callable(bionetgen.bngsim_available)
    assert callable(bionetgen.bngsim_capabilities)
    assert callable(bionetgen.bngsim_version)

    caps = bionetgen.bngsim_capabilities()
    for key in (
        "available",
        "provider",
        "cpp_adapter",
        "python_package",
        "version",
        "supports_ode",
        "supports_ssa",
        "supports_psa",
        "supports_pla",
    ):
        assert key in caps
    assert bionetgen.bngsim_available() is caps["available"]
    assert bionetgen.bngsim_version() == caps["version"]
    if not caps["available"]:
        assert caps["provider"] is None
        assert caps["version"] == "unavailable"
        assert caps["supports_ode"] is False
        assert caps["supports_ssa"] is False


def test_model_check_bngsim_lowering_method(tmp_path):
    for name, src in (
        ("decay.bngl", DECAY_BNGL),
        ("event.bngl", EVENT_BNGL),
        ("event_param.bngl", EVENT_PARAM_BNGL),
        ("comp_ok.bngl", COMPARTMENT_PARAM_BNGL),
        ("totalrate.bngl", TOTALRATE_BNGL),
    ):
        model = bionetgen.load(_write(tmp_path, name, src))
        chk_ok = model.check_bngsim_lowering()
        assert chk_ok["supported"] is True, (name, chk_ok)
        assert chk_ok["blockers"] == []

    for name, src, expected_substr in (
        ("event_distrib.bngl", EVENT_DISTRIB_BNGL, "distrib"),
        ("delay.bngl", DELAY_BNGL, "delay"),
        ("dyn_comp.bngl", DYNAMIC_COMPARTMENT_BNGL, "compartment"),
        ("energy.bngl", ENERGY_BNGL, "energy"),
        ("nonref.bngl", NON_REF_RATE_BNGL, "rate law"),
        ("localfn.bngl", LOCAL_FUNC_BNGL, "function arguments"),
    ):
        model = bionetgen.load(_write(tmp_path, name, src))
        chk = model.check_bngsim_lowering()
        assert chk["supported"] is False
        assert any(expected_substr in b.lower() for b in chk["blockers"]), chk


def test_native_is_strict_default_across_python_surfaces(tmp_path):
    path = _write(tmp_path, "two_param.bngl", TWO_PARAM_BNGL)
    model = bionetgen.load(path)

    r_sim = model.simulate(method="ode", t_end=1.0, n_steps=4)
    assert r_sim.backend == "native"

    r_run = bionetgen.run(path, method="ode", t_end=1.0, n_steps=4)
    assert r_run.backend == "native"

    scan = model.parameter_scan("k1", values=[0.1, 0.3], t_end=1.0, n_steps=4)
    assert all(res.backend == "native" for res in scan.results)

    scan2d = model.parameter_scan_2d(
        "k1", [0.1, 0.2], "k2", [0.05, 0.1], t_end=1.0, n_steps=4
    )
    assert all(res.backend == "native" for row in scan2d.results for res in row)

    sens = model.sensitivity_analysis(parameters=["k1"], t_end=1.0, n_steps=4)
    assert sens.baseline.backend == "native"


# ---------------------------------------------------------------------------
# 2. Fail-closed backend validation across all entry points
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["nf", "nfcore", "nfnext"])
@pytest.mark.parametrize("bad_backend", ["bngsim", "bng-sim", "bng_sim"])
def test_network_free_rejects_all_bngsim_aliases(tmp_path, method, bad_backend):
    model = bionetgen.load(_write(tmp_path, "decay.bngl", DECAY_BNGL))
    with pytest.raises(ValueError, match="not valid for method"):
        model.simulate(method=method, backend=bad_backend, t_end=1.0, n_steps=2)


@pytest.mark.parametrize("method", ["ode", "ssa", "nf", "nfnext"])
def test_unknown_or_nonstring_backend_fails_closed(tmp_path, method):
    model = bionetgen.load(_write(tmp_path, "decay.bngl", DECAY_BNGL))
    with pytest.raises(ValueError, match="Unknown backend"):
        model.simulate(method=method, backend="bogus_solver", t_end=1.0, n_steps=2)
    with pytest.raises(TypeError, match="backend must be a string"):
        model.simulate(method=method, backend=123, t_end=1.0, n_steps=2)  # type: ignore[arg-type]


def test_explicit_bngsim_fails_closed_for_incompatible_options(tmp_path):
    model = bionetgen.load(_write(tmp_path, "decay.bngl", DECAY_BNGL))

    with pytest.raises(RuntimeError, match="does not yet support method='pla'"):
        model.simulate(method="pla", backend="bngsim", t_end=1.0, n_steps=2)
    with pytest.raises(RuntimeError, match="continue_simulation"):
        model.simulate(
            method="ode",
            backend="bngsim",
            continue_simulation=True,
            t_end=1.0,
            n_steps=2,
        )
    with pytest.raises(RuntimeError, match="batch_size"):
        model.simulate(
            method="ssa", backend="bngsim", batch_size=4, t_end=1.0, n_steps=2
        )
    with pytest.raises(ValueError, match="batch_size"):
        model.simulate(
            method="psa", backend="bngsim", batch_size=4, t_end=1.0, n_steps=2
        )
    if not bionetgen.bngsim_available():
        with pytest.raises(RuntimeError, match="unavailable"):
            model.simulate(
                method="psa", backend="bngsim", t_end=1.0, n_steps=2, psa_poplevel=10.0
            )
    else:
        with pytest.raises(RuntimeError, match="poplevel"):
            model.simulate(
                method="psa", backend="bngsim", t_end=1.0, n_steps=2, psa_poplevel=1.0
            )


def test_scan_and_sensitivity_forward_backend_and_fail_closed(tmp_path):
    path = _write(tmp_path, "two_param.bngl", TWO_PARAM_BNGL)
    model = bionetgen.load(path)

    if not bionetgen.bngsim_available():
        with pytest.raises(RuntimeError, match="unavailable"):
            model.parameter_scan(
                "k1", values=[0.1, 0.2], t_end=1.0, n_steps=2, backend="bngsim"
            )
        with pytest.raises(RuntimeError, match="unavailable"):
            model.parameter_scan_2d(
                "k1", [0.1], "k2", [0.1], t_end=1.0, n_steps=2, backend="bngsim"
            )
        with pytest.raises(RuntimeError, match="unavailable"):
            model.sensitivity_analysis(
                parameters=["k1"], t_end=1.0, n_steps=2, backend="bngsim"
            )


def test_bngl_action_backend_opt_in_and_fail_closed(tmp_path):
    native_action = DECAY_BNGL + textwrap.dedent("""
        generate_network({overwrite=>1})
        simulate({method=>"ode",backend=>"native",t_end=>1,n_steps=>2})
    """)
    native_path = _write(tmp_path, "action_native.bngl", native_action)
    bionetgen.load(native_path).execute()
    assert (tmp_path / "action_native.gdat").is_file()

    unknown_action = DECAY_BNGL + textwrap.dedent("""
        generate_network({overwrite=>1})
        simulate({method=>"ode",backend=>"bogus",t_end=>1,n_steps=>2})
    """)
    with pytest.raises(ValueError, match="Unknown finite backend"):
        bionetgen.load(_write(tmp_path, "action_bad.bngl", unknown_action)).execute()

    bngsim_action = DECAY_BNGL + textwrap.dedent("""
        generate_network({overwrite=>1})
        simulate({method=>"ode",backend=>"bngsim",t_end=>1,n_steps=>2})
    """)
    with pytest.raises(RuntimeError, match="unavailable|BNGsim adapter rejected"):
        bionetgen.load(_write(tmp_path, "action_bngsim.bngl", bngsim_action)).execute()


# ---------------------------------------------------------------------------
# 3. CLI --backend flag & info reporting
# ---------------------------------------------------------------------------


def test_cli_backend_opt_in_and_conflicts(tmp_path):
    path = _write(tmp_path, "decay.bngl", DECAY_BNGL)
    runner = CliRunner()

    # Native explicit works
    out_native = tmp_path / "native.tsv"
    res_native = runner.invoke(
        cli_main,
        [
            "run",
            str(path),
            "--backend",
            "native",
            "--t-end",
            "1",
            "--n-steps",
            "2",
            "--output",
            str(out_native),
        ],
    )
    assert res_native.exit_code == 0, res_native.output
    assert out_native.is_file()

    # Conflict: --no-bngsim + --backend bngsim rejected cleanly
    res_conflict = runner.invoke(
        cli_main,
        ["run", str(path), "--no-bngsim", "--backend", "bngsim"],
    )
    assert res_conflict.exit_code != 0
    assert "cannot be combined" in res_conflict.output

    # Explicit --backend bngsim fails closed when unavailable
    if not bionetgen.bngsim_available():
        for args in (
            ["run", str(path), "--backend", "bngsim", "--t-end", "1", "--n-steps", "2"],
            [
                "scan",
                str(path),
                "--parameter",
                "k",
                "--min",
                "0.1",
                "--max",
                "0.3",
                "--n-points",
                "2",
                "--t-end",
                "1",
                "--n-steps",
                "2",
                "--backend",
                "bngsim",
            ],
            [
                "sensitivity",
                str(path),
                "--parameter",
                "k",
                "--t-end",
                "1",
                "--n-steps",
                "2",
                "--backend",
                "bngsim",
            ],
        ):
            res = runner.invoke(cli_main, args)
            assert res.exit_code != 0
            assert "unavailable" in res.output.lower()

    # info --detail surfaces finite backend policy and BNGsim status
    res_info = runner.invoke(cli_main, ["info", "--detail"])
    assert res_info.exit_code == 0, res_info.output
    assert "Default finite backend: native" in res_info.output
    assert "Optional BNGsim backend:" in res_info.output


# ---------------------------------------------------------------------------
# 4. Optional Python ``bngsim`` package bridge (mocked in-memory)
# ---------------------------------------------------------------------------


def test_python_bngsim_bridge_end_to_end_and_fail_closed(tmp_path, monkeypatch):
    import bionetgen._bionetgen_cpp as _cpp

    if _cpp.bngsim_available():
        pytest.skip(
            "C++ BUILD_BNGSIM_ADAPTER is active; Python bridge is fallback only"
        )

    calls: list = []
    fake_mod = _make_fake_python_bngsim(recorded_calls=calls)
    monkeypatch.setitem(sys.modules, "bngsim", fake_mod)

    caps = bionetgen.bngsim_capabilities()
    assert caps["available"] is True
    assert caps["provider"] == "python"
    assert caps["cpp_adapter"] is False
    assert caps["python_package"] is True
    assert caps["version"] == "0.18.0-fake"
    assert bionetgen.bngsim_available() is True

    # Native MUST remain the default even when Python bngsim is installed!
    decay_path = _write(tmp_path, "decay.bngl", DECAY_BNGL)
    model = bionetgen.load(decay_path)
    r_default = model.simulate(method="ode", t_end=2.0, n_steps=4)
    assert r_default.backend == "native"
    assert calls == []

    # Explicit opt-in uses Python bngsim bridge and matches analytic decay
    r_ode = model.simulate(method="ode", t_end=2.0, n_steps=4, backend="bngsim")
    assert r_ode.backend == "bngsim"
    assert r_ode.construction_path == "python-bngsim"
    expected = 100.0 * np.exp(-0.2 * r_ode.time)
    np.testing.assert_allclose(r_ode.observables["Xtot"], expected, rtol=1e-12)
    assert any(c[0] == "from_net" for c in calls)

    # Explicit SSA opt-in works via Python bngsim bridge
    r_ssa = model.simulate(
        method="ssa", t_end=2.0, n_steps=4, seed=42, backend="bngsim"
    )
    assert r_ssa.backend == "bngsim"
    assert r_ssa.construction_path == "python-bngsim"
    assert any(c == ("Simulator", "ssa", None) for c in calls)

    # Explicit PSA opt-in works via Python bngsim bridge
    r_psa = model.simulate(
        method="psa",
        t_end=2.0,
        n_steps=4,
        seed=42,
        psa_poplevel=10.0,
        backend="bngsim",
    )
    assert r_psa.backend == "bngsim"
    assert r_psa.construction_path == "python-bngsim"
    assert any(c == ("Simulator", "psa", 10.0) for c in calls)
    with pytest.raises(RuntimeError, match="poplevel"):
        model.simulate(
            method="psa",
            t_end=2.0,
            n_steps=4,
            seed=42,
            psa_poplevel=1.0,
            backend="bngsim",
        )

    # Unsupported model constructs STILL fail closed BEFORE Python bngsim runs
    calls.clear()
    for name, src, substr in (
        ("ev_distrib.bngl", EVENT_DISTRIB_BNGL, "distrib"),
        ("dl.bngl", DELAY_BNGL, "delay"),
        ("dyn_cp.bngl", DYNAMIC_COMPARTMENT_BNGL, "compartment"),
        ("en.bngl", ENERGY_BNGL, "energy"),
        ("nr.bngl", NON_REF_RATE_BNGL, "rate law"),
    ):
        bad_model = bionetgen.load(_write(tmp_path, name, src))
        with pytest.raises(RuntimeError, match=substr):
            bad_model.simulate(method="ode", t_end=1.0, n_steps=2, backend="bngsim")
    assert calls == [], "Unsupported models must fail closed before invoking bngsim"

    # Unsupported runtime options fail closed identically to C++ BngsimBackend
    with pytest.raises(RuntimeError, match="stop_if"):
        model.simulate(
            method="ode", t_end=1.0, n_steps=2, stop_if="Xtot < 50", backend="bngsim"
        )
    with pytest.raises(RuntimeError, match="sparse"):
        model.simulate(
            method="ode", t_end=1.0, n_steps=2, sparse=True, backend="bngsim"
        )
    with pytest.raises(RuntimeError, match="check_product_scale"):
        model.simulate(
            method="ode",
            t_end=1.0,
            n_steps=2,
            check_product_scale=10.0,
            backend="bngsim",
        )
    with pytest.raises(RuntimeError, match="max_sim_steps"):
        model.simulate(
            method="ssa", t_end=1.0, n_steps=2, max_sim_steps=5, backend="bngsim"
        )
    with pytest.raises(RuntimeError, match="output_step_interval"):
        model.simulate(
            method="ssa",
            t_end=1.0,
            n_steps=2,
            output_step_interval=2,
            backend="bngsim",
        )

    # sample_times length mismatch fails closed
    bad_sample_mod = _make_fake_python_bngsim(return_wrong_sample_len=True)
    monkeypatch.setitem(sys.modules, "bngsim", bad_sample_mod)
    with pytest.raises(RuntimeError, match="sample_times"):
        model.simulate(
            method="ode",
            t_end=2.0,
            sample_times=[0.0, 1.0, 2.0],
            backend="bngsim",
        )

    # Parameter scan with backend="bngsim" routes through Python bngsim bridge
    monkeypatch.setitem(sys.modules, "bngsim", fake_mod)
    scan_res = model.parameter_scan(
        "k", values=[0.1, 0.5], t_end=2.0, n_steps=2, backend="bngsim"
    )
    assert all(r.backend == "bngsim" for r in scan_res.results)
    assert math.isclose(scan_res.final("Xtot")[0], 100.0 * math.exp(-0.2), rel_tol=1e-9)
    assert math.isclose(scan_res.final("Xtot")[1], 100.0 * math.exp(-1.0), rel_tol=1e-9)


# ---------------------------------------------------------------------------
# 5. Real C++ BNGsim v0.18.0 differential parity tests (ODE, SSA, PSA,
#    TotalRate, static 2D/3D compartments, and bng3_events)
# ---------------------------------------------------------------------------


def test_cpp_bngsim_differential_parity_suite(tmp_path):
    import bionetgen._bionetgen_cpp as _cpp

    if not _cpp.bngsim_available():
        pytest.skip("C++ BUILD_BNGSIM_ADAPTER is not enabled in this build")

    caps = bionetgen.bngsim_capabilities()
    assert caps["provider"] == "cpp"
    assert caps["version"] == "3295c4d31f2e8c75d07372f33ec2e6b578850540"
    assert caps["supports_ode"] is True
    assert caps["supports_ssa"] is True
    assert caps["supports_psa"] is True

    # 1. TotalRate ODE parity (homodimer omits 0.5 symmetry factor)
    tr_model = bionetgen.load(_write(tmp_path, "tr.bngl", TOTALRATE_BNGL))
    tr_native = tr_model.simulate(method="ode", t_end=2.0, n_steps=10)
    tr_bngsim = tr_model.simulate(method="ode", t_end=2.0, n_steps=10, backend="bngsim")
    assert tr_bngsim.backend == "bngsim"
    np.testing.assert_allclose(
        tr_bngsim.observables["Atot"], tr_native.observables["Atot"], atol=1e-5
    )
    np.testing.assert_allclose(
        tr_bngsim.observables["Dtot"], tr_native.observables["Dtot"], atol=1e-5
    )

    # 2. Static 2D/3D compartment ODE parity
    comp_model = bionetgen.load(_write(tmp_path, "comp.bngl", COMPARTMENT_PARAM_BNGL))
    comp_native = comp_model.simulate(method="ode", t_end=2.0, n_steps=10)
    comp_bngsim = comp_model.simulate(
        method="ode", t_end=2.0, n_steps=10, backend="bngsim"
    )
    assert comp_bngsim.backend == "bngsim"
    np.testing.assert_allclose(
        comp_bngsim.observables["RL"], comp_native.observables["RL"], atol=1e-5
    )

    # 3. bng3_events (threshold reset + delayed parameter mutation) ODE parity
    ev_model = bionetgen.load(_write(tmp_path, "ev.bngl", EVENT_BNGL))
    ev_native = ev_model.simulate(method="ode", t_end=4.0, n_steps=20)
    ev_bngsim = ev_model.simulate(method="ode", t_end=4.0, n_steps=20, backend="bngsim")
    assert ev_bngsim.backend == "bngsim"
    np.testing.assert_allclose(
        ev_bngsim.observables["X"], ev_native.observables["X"], atol=1e-4
    )

    evp_model = bionetgen.load(_write(tmp_path, "evp.bngl", EVENT_PARAM_BNGL))
    evp_native = evp_model.simulate(method="ode", t_end=3.0, n_steps=15)
    evp_bngsim = evp_model.simulate(
        method="ode", t_end=3.0, n_steps=15, backend="bngsim"
    )
    assert evp_bngsim.backend == "bngsim"
    assert evp_bngsim.concentrations.shape == evp_native.concentrations.shape
    assert list(evp_bngsim.observables.keys()) == list(evp_native.observables.keys())
    np.testing.assert_allclose(
        evp_bngsim.observables["Aobs"], evp_native.observables["Aobs"], atol=1e-4
    )
    np.testing.assert_allclose(
        evp_bngsim.observables["Bobs"], evp_native.observables["Bobs"], atol=1e-4
    )

    # 4. PSA conservation, seed reproducibility, and fail-closed poplevel guard
    psa_bngl = textwrap.dedent("""
        begin model
        begin parameters
            k 0.25
        end parameters
        begin molecule types
            A()
            B()
        end molecule types
        begin seed species
            A() 10000
            B() 0
        end seed species
        begin observables
            Molecules Aobs A()
            Molecules Bobs B()
        end observables
        begin reaction rules
            A() -> B() k
        end reaction rules
        end model
    """)
    psa_model = bionetgen.load(_write(tmp_path, "psa.bngl", psa_bngl))
    r_psa1 = psa_model.simulate(
        method="psa",
        t_end=2.0,
        n_steps=4,
        seed=42,
        psa_poplevel=100.0,
        backend="bngsim",
    )
    r_psa2 = psa_model.simulate(
        method="psa",
        t_end=2.0,
        n_steps=4,
        seed=42,
        psa_poplevel=100.0,
        backend="bngsim",
    )
    assert r_psa1.backend == "bngsim"
    np.testing.assert_array_equal(
        r_psa1.observables["Aobs"], r_psa2.observables["Aobs"]
    )
    np.testing.assert_allclose(
        r_psa1.observables["Aobs"] + r_psa1.observables["Bobs"], 10000.0, atol=1e-6
    )
    assert math.isclose(
        float(r_psa1.observables["Aobs"][-1]), 10000.0 * math.exp(-0.5), rel_tol=0.08
    )
