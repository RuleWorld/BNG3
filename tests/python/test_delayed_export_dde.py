"""Execute exported Python DDE scripts and validate MATLAB dde23 export for delayed rules."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

import bionetgen
from bionetgen import _bionetgen_cpp as cpp


def _exec_exported_python(code: str) -> dict:
    namespace: dict = {}
    exec(compile(code, "<exported_dde>", "exec"), namespace)
    return namespace


def test_python_export_consuming_delayed_rule_matches_analytic_and_cvode(
    tmp_path: Path,
):
    source = """begin model
begin parameters
  tau 2.0
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    network = cpp.generate_network(model)
    bngl_path = tmp_path / "consuming_delay.bngl"
    bngl_path.write_text(
        source
        + "\nbegin actions\n"
        + "  generate_network({overwrite=>1})\n"
        + "  writeCPYfile({t_start=>0,t_end=>5,n_steps=>20})\n"
        + "  writeMfile({t_start=>0,t_end=>5,n_steps=>20})\n"
        + "end actions\n",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl_path)).execute()

    py_code = (tmp_path / "consuming_delay_pyode.py").read_text(encoding="utf-8")
    assert "solve_ivp" in py_code
    assert "dydt_dde" in py_code

    ns = _exec_exported_python(py_code)
    times = np.linspace(0.0, 5.0, 21)
    t_out, y_out, obs_out = ns["simulate"](times)
    np.testing.assert_allclose(t_out, times)

    # Exact closed-form: A(t) = 10*exp(-0.5*t), B(t) = 0 for t<=2 else 10*(1 - exp(-0.5*(t-2)))
    expected_a = 10.0 * np.exp(-0.5 * times)
    expected_b = np.where(
        times <= 2.0, 0.0, 10.0 * (1.0 - np.exp(-0.5 * (times - 2.0)))
    )
    np.testing.assert_allclose(obs_out[:, 0], expected_a, rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(obs_out[:, 1], expected_b, rtol=1e-5, atol=1e-6)

    # Compare against native CVODE
    native = cpp.simulate_ode(model, network, t_end=5.0, n_steps=20)
    np.testing.assert_allclose(
        obs_out[:, 0], native["observables"]["A_obs"], rtol=1e-4, atol=1e-5
    )
    np.testing.assert_allclose(
        obs_out[:, 1], native["observables"]["B_obs"], rtol=1e-4, atol=1e-5
    )

    # Custom parameter override must update lag tau dynamically (tau=3.0, k=0.5)
    _, _, obs_custom = ns["simulate"](times, parameters=np.array([3.0, 0.5]))
    expected_b_tau3 = np.where(
        times <= 3.0, 0.0, 10.0 * (1.0 - np.exp(-0.5 * (times - 3.0)))
    )
    np.testing.assert_allclose(obs_custom[:, 1], expected_b_tau3, rtol=1e-5, atol=1e-6)

    # MATLAB export uses dde23 + ddeset + calc_species_deriv_dde
    m_code = (tmp_path / "consuming_delay.m").read_text(encoding="utf-8")
    assert "dde23(" in m_code
    assert "ddeset(" in m_code
    assert "calc_species_deriv_dde" in m_code
    assert "lags = [" in m_code


def test_python_export_nonconsuming_and_multi_delay_matches_cvode(tmp_path: Path):
    source = """begin model
begin parameters
  tau1 1.2
  tau2 2.0
  k1 0.4
  k2 0.3
  k3 0.2
end parameters
begin molecule types
  G()
  M()
  A()
  B()
  C()
end molecule types
begin seed species
  G() 2
  A() 10
end seed species
begin observables
  Molecules G_obs G()
  Molecules M_obs M()
  Molecules A_obs A()
  Molecules B_obs B()
  Molecules C_obs C()
end observables
begin reaction rules
  G() -> G() + M() k1 delay=tau1 NonConsuming
  A() -> B() k2 delay=tau2
  B() -> C() k3
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    network = cpp.generate_network(model)
    bngl_path = tmp_path / "multi_delay.bngl"
    bngl_path.write_text(
        source
        + "\nbegin actions\n"
        + "  generate_network({overwrite=>1})\n"
        + "  writeCPYfile({t_start=>0,t_end=>5,n_steps=>25})\n"
        + "  writeMfile({t_start=>0,t_end=>5,n_steps=>25})\n"
        + "end actions\n",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl_path)).execute()

    py_code = (tmp_path / "multi_delay_pyode.py").read_text(encoding="utf-8")
    ns = _exec_exported_python(py_code)
    times = np.linspace(0.0, 5.0, 26)
    _, _, obs_out = ns["simulate"](times)

    native = cpp.simulate_ode(model, network, t_end=5.0, n_steps=25)
    for idx, name in enumerate(("G_obs", "M_obs", "A_obs", "B_obs", "C_obs")):
        np.testing.assert_allclose(
            obs_out[:, idx], native["observables"][name], rtol=1e-4, atol=1e-5
        )
    # Exact analytical NonConsuming check: M(t) = 0 for t <= 1.2, 0.8*(t - 1.2) for t > 1.2
    expected_m = np.where(times <= 1.2, 0.0, 0.8 * (times - 1.2))
    np.testing.assert_allclose(obs_out[:, 1], expected_m, rtol=1e-5, atol=1e-6)

    m_code = (tmp_path / "multi_delay.m").read_text(encoding="utf-8")
    assert "dde23(" in m_code
    assert "delayed_ratelaws = zeros(3, 2)" in m_code
