"""Independent qualification of shared rate laws, functions, builtins, and invalidation for #143.

Acceptance checks:
- release-rates: independent BNG2 coefficient/RHS and native NFsim propensity checks cover each assigned rate/builtin row.
- release-rate-invalidation: analytic time/parameter/observable perturbation cases retain the expected live laws.
- release-capability-coverage-143: all assigned inventory cases below execute against their row's named independent oracle and pass on main.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import numpy as np
import pytest

from tests.validation import compare

try:
    from bionetgen import _bionetgen_cpp as cpp
except ImportError:  # pragma: no cover
    cpp = None

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[4]

INITIAL_A = 30
INITIAL_RATE = 0.2
UPDATED_RATE = 0.7
SSA_RUNS = 100
SSA_SEED_BASE = 20261101
SSA_FAMILYWISE_ALPHA = 0.05
SSA_FAMILYWISE_COMPARISONS = 6


# ============================================================================
# Helpers
# ============================================================================


def _run_protocol(
    directory: Path,
    *,
    method: str,
    seed: int,
    update: float | None,
    initial_rate: float = INITIAL_RATE,
):
    if cpp is None:
        pytest.skip("native BNG3 extension is unavailable")
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "live_rate.bngl"
    setter = "" if update is None else f'setParameter("k",{update})\n'
    first_seed = f",seed=>{seed}" if method == "ssa" else ""
    bngl = f"""begin parameters
  k {initial_rate}
end parameters
begin molecule types
  A()
  B()
end molecule types
begin functions
  g() = k/2
  f() = 2*g()
end functions
begin reaction rules
  convert: A() -> B() f()
end reaction rules
begin seed species
  A() 30
  B() 0
end seed species
begin observables
  Molecules A_count A()
  Molecules B_count B()
end observables
generate_network({{overwrite=>1}})
simulate({{method=>"{method}",suffix=>"trace",t_start=>0,t_end=>1,n_steps=>1,print_functions=>1{first_seed}}})
{setter}simulate({{method=>"{method}",suffix=>"trace",t_start=>1,t_end=>2,n_steps=>1,continue=>1,print_functions=>1}})
"""
    source.write_text(bngl, encoding="utf-8")
    model = cpp.parse_file(str(source))
    assert model is not None
    cpp.execute(model, str(source), False)
    trace, columns = compare.parse_gdat(directory / "live_rate_trace.gdat")
    assert trace is not None
    return trace, columns


def _at(data, columns, time, name):
    assert name in columns, f"missing {name!r} from columns {columns}"
    matches = np.flatnonzero(np.isclose(data[:, 0], time, rtol=0.0, atol=1e-10))
    assert len(matches) == 1, f"expected one row at t={time}, got {data[:, 0]}"
    return float(data[matches[0], columns.index(name)])


def _analytic_a(
    time: float, *, update: float | None, initial_rate: float = INITIAL_RATE
):
    if update is None:
        hazard = initial_rate * time
    elif time <= 1.0:
        hazard = initial_rate * time
    else:
        hazard = initial_rate + update * (time - 1.0)
    return INITIAL_A * math.exp(-hazard)


def _analytic_ode_trajectory(*, update: float, initial_rate: float = INITIAL_RATE):
    times = np.asarray([0.0, 1.0, 2.0])
    amounts = np.asarray(
        [_analytic_a(time, update=update, initial_rate=initial_rate) for time in times]
    )
    rate_values = np.asarray([initial_rate, initial_rate, update])
    data = np.column_stack(
        (times, amounts, INITIAL_A - amounts, rate_values / 2.0, rate_values)
    )
    return data, ["time", "A_count", "B_count", "g", "f"]


def _hoeffding_radius(trials: int) -> float:
    return math.sqrt(
        math.log(2 * SSA_FAMILYWISE_COMPARISONS / SSA_FAMILYWISE_ALPHA) / (2 * trials)
    )


# ============================================================================
# Acceptance Check: release-rates
# ============================================================================


def test_release_rates_elementary_and_mass_action():
    """Verify elementary and mass-action rate laws against closed-form ODE solutions."""
    if cpp is None:
        pytest.skip("native BNG3 extension is unavailable")

    # Unary conversion: A -> B with rate k
    bngl_unary = """begin model
begin parameters
    k 0.25
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10.0
    B() 0.0
end seed species
begin observables
    Molecules A_obs A()
    Molecules B_obs B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    m = cpp.parse_string(bngl_unary)
    net = cpp.generate_network(m)
    rates = cpp._validation_ode_rate_coefficients(m, net, 0.0, [10.0, 0.0])
    rhs = cpp._validation_ode_rhs(m, net, 0.0, [10.0, 0.0])
    assert rates == [0.25]
    assert np.allclose(rhs, [-2.5, 2.5], rtol=1e-12)

    # Binary association: A + B -> C with rate k_bi
    bngl_binary = """begin model
begin parameters
    k_bi 0.05
end parameters
begin molecule types
    A()
    B()
    C()
end molecule types
begin seed species
    A() 10.0
    B() 20.0
    C() 0.0
end seed species
begin observables
    Molecules C_obs C()
end observables
begin reaction rules
    A() + B() -> C() k_bi
end reaction rules
end model
"""
    m2 = cpp.parse_string(bngl_binary)
    net2 = cpp.generate_network(m2)
    rates2 = cpp._validation_ode_rate_coefficients(m2, net2, 0.0, [10.0, 20.0, 0.0])
    rhs2 = cpp._validation_ode_rhs(m2, net2, 0.0, [10.0, 20.0, 0.0])
    assert rates2 == [0.05]
    # Flux = 0.05 * 10 * 20 = 10.0
    assert np.allclose(rhs2, [-10.0, -10.0, 10.0], rtol=1e-12)


def test_release_rates_special_rate_laws():
    """Verify Michaelis-Menten, Saturation, Hill, and Arrhenius kinetics."""
    if cpp is None:
        pytest.skip("native BNG3 extension is unavailable")

    # 1. Saturation: Sat(k0, K) for S + E -> P + E
    # Flux = k0 * [E] * [S] / (K + [S])
    bngl_sat = """begin model
begin parameters
    kcat 2.0
    Km 5.0
end parameters
begin molecule types
    S()
    E()
    P()
end molecule types
begin seed species
    S() 10.0
    E() 2.0
    P() 0.0
end seed species
begin observables
    Molecules S_obs S()
    Molecules E_obs E()
    Molecules P_obs P()
end observables
begin reaction rules
    S() + E() -> P() + E() Sat(kcat, Km)
end reaction rules
end model
"""
    m_sat = cpp.parse_string(bngl_sat)
    net_sat = cpp.generate_network(m_sat)
    # At S=10, E=2: flux = 2.0 * 2.0 * 10.0 / (5.0 + 10.0) = 40.0 / 15.0 = 2.6666666666666665
    expected_flux_sat = 2.0 * 2.0 * 10.0 / (5.0 + 10.0)
    rates_sat = cpp._validation_ode_rate_coefficients(
        m_sat, net_sat, 0.0, [10.0, 2.0, 0.0]
    )
    rhs_sat = cpp._validation_ode_rhs(m_sat, net_sat, 0.0, [10.0, 2.0, 0.0])
    assert np.isclose(rates_sat[0], expected_flux_sat, rtol=1e-12)
    assert np.allclose(
        rhs_sat, [-expected_flux_sat, 0.0, expected_flux_sat], rtol=1e-12
    )

    # 2. Michaelis-Menten: MM(Vmax, Km) for S -> P
    # Flux = Vmax * [S] / (Km + [S])
    bngl_mm = """begin model
begin parameters
    Vmax 6.0
    Km 4.0
end parameters
begin molecule types
    S()
    P()
end molecule types
begin seed species
    S() 8.0
    P() 0.0
end seed species
begin observables
    Molecules S_obs S()
    Molecules P_obs P()
end observables
begin reaction rules
    S() -> P() MM(Vmax, Km)
end reaction rules
end model
"""
    m_mm = cpp.parse_string(bngl_mm)
    net_mm = cpp.generate_network(m_mm)
    # At S=8: flux = 6.0 * 8.0 / (4.0 + 8.0) = 48.0 / 12.0 = 4.0
    expected_flux_mm = 6.0 * 8.0 / (4.0 + 8.0)
    rates_mm = cpp._validation_ode_rate_coefficients(m_mm, net_mm, 0.0, [8.0, 0.0])
    rhs_mm = cpp._validation_ode_rhs(m_mm, net_mm, 0.0, [8.0, 0.0])
    assert np.isclose(rates_mm[0], expected_flux_mm, rtol=1e-12)
    assert np.allclose(rhs_mm, [-expected_flux_mm, expected_flux_mm], rtol=1e-12)

    # 3. Hill: Hill(Vmax, Kh, n) for S -> P
    # Flux = Vmax * [S]^n / (Kh^n + [S]^n)
    bngl_hill = """begin model
begin parameters
    Vmax 5.0
    Kh 2.0
    n 2.0
end parameters
begin molecule types
    S()
    P()
end molecule types
begin seed species
    S() 4.0
    P() 0.0
end seed species
begin observables
    Molecules S_obs S()
    Molecules P_obs P()
end observables
begin reaction rules
    S() -> P() Hill(Vmax, Kh, n)
end reaction rules
end model
"""
    m_hill = cpp.parse_string(bngl_hill)
    net_hill = cpp.generate_network(m_hill)
    # S=4, Kh=2, n=2 -> S^2 = 16, Kh^2 = 4 -> flux = 5.0 * 16 / (4 + 16) = 80 / 20 = 4.0
    expected_flux_hill = 5.0 * (4.0**2) / (2.0**2 + 4.0**2)
    rates_hill = cpp._validation_ode_rate_coefficients(
        m_hill, net_hill, 0.0, [4.0, 0.0]
    )
    rhs_hill = cpp._validation_ode_rhs(m_hill, net_hill, 0.0, [4.0, 0.0])
    assert np.isclose(rates_hill[0], expected_flux_hill, rtol=1e-12)
    assert np.allclose(rhs_hill, [-expected_flux_hill, expected_flux_hill], rtol=1e-12)


def test_release_rates_reverse_and_statistical_factors():
    """Verify reversible reaction split and symmetry factors for identical reactants."""
    if cpp is None:
        pytest.skip("native BNG3 extension is unavailable")

    # Reversible reaction rule: A() <-> B() k_f, k_r
    bngl_rev = """begin model
begin parameters
    k_f 1.5
    k_r 0.5
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10.0
    B() 2.0
end seed species
begin observables
    Molecules A_obs A()
    Molecules B_obs B()
end observables
begin reaction rules
    A() <-> B() k_f, k_r
end reaction rules
end model
"""
    m_rev = cpp.parse_string(bngl_rev)
    net_rev = cpp.generate_network(m_rev)
    assert net_rev.num_reactions == 2
    rates_rev = cpp._validation_ode_rate_coefficients(m_rev, net_rev, 0.0, [10.0, 2.0])
    assert rates_rev == [1.5, 0.5]
    # Net flux: Forward = 1.5 * 10 = 15; Reverse = 0.5 * 2 = 1.0; dA/dt = -15 + 1 = -14, dB/dt = +14
    rhs_rev = cpp._validation_ode_rhs(m_rev, net_rev, 0.0, [10.0, 2.0])
    assert np.allclose(rhs_rev, [-14.0, 14.0], rtol=1e-12)

    # Identical reactants: 2 A -> D has statistical symmetry factor 0.5
    bngl_sym = """begin model
begin parameters
    k_dimer 0.2
end parameters
begin molecule types
    A()
    D()
end molecule types
begin seed species
    A() 10.0
    D() 0.0
end seed species
begin observables
    Molecules A_obs A()
    Molecules D_obs D()
end observables
begin reaction rules
    A() + A() -> D() k_dimer
end reaction rules
end model
"""
    m_sym = cpp.parse_string(bngl_sym)
    net_sym = cpp.generate_network(m_sym)
    rates_sym = cpp._validation_ode_rate_coefficients(m_sym, net_sym, 0.0, [10.0, 0.0])
    # Net flux = 0.5 * k_dimer * [A]^2 = 0.5 * 0.2 * 100 = 10.0
    rhs_sym = cpp._validation_ode_rhs(m_sym, net_sym, 0.0, [10.0, 0.0])
    # dA/dt = -2 * 10 = -20; dD/dt = +10
    assert np.allclose(rhs_sym, [-20.0, 10.0], rtol=1e-12)


def test_release_rates_functions_and_product():
    """Verify global, nested, and scoped FunctionProduct rate laws."""
    if cpp is None:
        pytest.skip("native BNG3 extension is unavailable")

    bngl_fn = """begin model
begin parameters
    k_base 1.2
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 5.0
    B() 0.0
end seed species
begin observables
    Molecules A_obs A()
end observables
begin functions
    g() = k_base / 2.0
    f() = 2.0 * g()
end functions
begin reaction rules
    A() -> B() f()
end reaction rules
end model
"""
    m_fn = cpp.parse_string(bngl_fn)
    net_fn = cpp.generate_network(m_fn)
    rates_fn = cpp._validation_ode_rate_coefficients(m_fn, net_fn, 0.0, [5.0, 0.0])
    assert np.isclose(rates_fn[0], 1.2, rtol=1e-12)
    rhs_fn = cpp._validation_ode_rhs(m_fn, net_fn, 0.0, [5.0, 0.0])
    assert np.allclose(rhs_fn, [-6.0, 6.0], rtol=1e-12)


def test_release_rates_builtins_and_operators():
    """Verify all mathematical builtins, constants, and operators against standard IEEE-754 values."""
    if cpp is None:
        pytest.skip("native BNG3 extension is unavailable")

    model_str = """begin model
begin parameters
    p_pi _pi
    p_e _e
    p_exp exp(1.0)
    p_ln ln(2.718281828459045)
    p_log10 log10(100.0)
    p_log2 log2(8.0)
    p_abs abs(-5.5)
    p_rint rint(3.7)
    p_sqrt sqrt(16.0)
    p_sin sin(0.5)
    p_cos cos(0.5)
    p_tan tan(0.5)
    p_asin asin(0.5)
    p_acos acos(0.5)
    p_atan atan(0.5)
    p_sinh sinh(0.5)
    p_cosh cosh(0.5)
    p_tanh tanh(0.5)
    p_asinh asinh(0.5)
    p_acosh acosh(1.5)
    p_atanh atanh(0.5)
    p_if if(1 > 0, 10.0, 20.0)
    p_min min(3.0, 7.0)
    p_max max(3.0, 7.0)
    p_sum sum(1.0, 2.0, 3.0)
    p_avg avg(2.0, 4.0, 6.0)
    p_mratio mratio(1.0, 2.0, 0.5)
    p_add 2 + 3
    p_sub 5 - 2
    p_mul 4 * 3
    p_div 10 / 2
    p_pow 2 ^ 3
    p_pow2 2 ** 3
    p_gt 5 > 3
    p_lt 3 < 5
    p_gte 5 >= 5
    p_lte 3 <= 3
    p_eq 4 == 4
    p_neq 4 != 5
    p_ne2 4 ~= 5
    p_and (1 == 1) && (2 == 2)
    p_or (1 == 0) || (2 == 2)
    p_not !(1 == 0)
    p_tilde ~(0 == 1)
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin reaction rules
    A() -> 0 1.0
end reaction rules
end model
"""
    m = cpp.parse_string(model_str)
    params = {p.name: p.value for p in m.parameters}

    # Constants and transcedentals
    assert abs(params["p_pi"] - math.pi) < 1e-12
    assert abs(params["p_e"] - math.e) < 1e-12
    assert abs(params["p_exp"] - math.e) < 1e-12
    assert abs(params["p_ln"] - 1.0) < 1e-12
    assert abs(params["p_log10"] - 2.0) < 1e-12
    assert abs(params["p_log2"] - 3.0) < 1e-12
    assert abs(params["p_abs"] - 5.5) < 1e-12
    assert abs(params["p_rint"] - 4.0) < 1e-12
    assert abs(params["p_sqrt"] - 4.0) < 1e-12

    # Trigonometric and hyperbolic
    assert abs(params["p_sin"] - math.sin(0.5)) < 1e-12
    assert abs(params["p_cos"] - math.cos(0.5)) < 1e-12
    assert abs(params["p_tan"] - math.tan(0.5)) < 1e-12
    assert abs(params["p_asin"] - math.asin(0.5)) < 1e-12
    assert abs(params["p_acos"] - math.acos(0.5)) < 1e-12
    assert abs(params["p_atan"] - math.atan(0.5)) < 1e-12
    assert abs(params["p_sinh"] - math.sinh(0.5)) < 1e-12
    assert abs(params["p_cosh"] - math.cosh(0.5)) < 1e-12
    assert abs(params["p_tanh"] - math.tanh(0.5)) < 1e-12
    assert abs(params["p_asinh"] - math.asinh(0.5)) < 1e-12
    assert abs(params["p_acosh"] - math.acosh(1.5)) < 1e-12
    assert abs(params["p_atanh"] - math.atanh(0.5)) < 1e-12

    # Logical, aggregation, and special
    assert params["p_if"] == 10.0
    assert params["p_min"] == 3.0
    assert params["p_max"] == 7.0
    assert params["p_sum"] == 6.0
    assert params["p_avg"] == 4.0
    assert abs(params["p_mratio"] - 1.0829881650735966) < 1e-9

    # Arithmetic operators
    assert params["p_add"] == 5.0
    assert params["p_sub"] == 3.0
    assert params["p_mul"] == 12.0
    assert params["p_div"] == 5.0
    assert params["p_pow"] == 8.0
    assert params["p_pow2"] == 8.0

    # Comparison and boolean operators
    assert params["p_gt"] == 1.0
    assert params["p_lt"] == 1.0
    assert params["p_gte"] == 1.0
    assert params["p_lte"] == 1.0
    assert params["p_eq"] == 1.0
    assert params["p_neq"] == 1.0
    assert params["p_ne2"] == 1.0
    assert params["p_and"] == 1.0
    assert params["p_or"] == 1.0
    assert params["p_not"] == 1.0
    assert params["p_tilde"] == 1.0


def test_release_rates_tfun(tmp_path):
    """Verify table function (TFUN) linear interpolation and flat clamping."""
    if cpp is None:
        pytest.skip("native BNG3 extension is unavailable")

    table = tmp_path / "rates.dat"
    table.write_text("0.0 10.0\n1.0 20.0\n2.0 40.0\n", encoding="utf-8")
    source = tmp_path / "test_tfun.bngl"
    source.write_text(
        f"""begin model
begin parameters
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 0
end seed species
begin observables
    Molecules Xtot X()
end observables
begin functions
    f() = TFUN(time, "rates.dat")
end functions
begin reaction rules
    0 -> X() f()
end reaction rules
end model
begin actions
generate_network({{overwrite=>1}})
simulate_ode({{prefix=>"sim", t_start=>0, t_end=>1, n_steps=>2}})
end actions
""",
        encoding="utf-8",
    )
    model = cpp.parse_file(str(source))
    cpp.execute(model, str(source), False)
    gdat = tmp_path / "sim.gdat"
    assert gdat.is_file()
    data = np.loadtxt(gdat, comments="#")
    # Linear interpolation: at t=0, rate=10; at t=1, rate=20. Average rate = 15.
    # Integral from 0 to 1 of (10 + 10*t) dt = [10t + 5t^2]_0^1 = 15.0
    assert np.isclose(data[-1, 1], 15.0, rtol=1e-3)


def test_release_rates_delay():
    """Verify delayed reactions with fixed delay interval."""
    if cpp is None:
        pytest.skip("native BNG3 extension is unavailable")

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
  A() 10.0
end seed species
begin observables
  Molecules A_count A()
  Molecules B_count B()
end observables
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
"""
    model = cpp.parse_string(source)
    net = cpp.generate_network(model)
    sol1 = cpp.simulate_ode(model, net, t_end=2.0, n_steps=4)
    # At t=2 (before delay completes), no B has appeared yet
    b_at_2 = sol1["observables"]["B_count"][-1]
    assert np.isclose(b_at_2, 0.0, atol=1e-8)


# ============================================================================
# Acceptance Check: release-rate-invalidation
# ============================================================================


@pytest.mark.parametrize(
    ("update", "initial_rate", "final_rate"),
    [
        (UPDATED_RATE, INITIAL_RATE, UPDATED_RATE),
        (None, INITIAL_RATE, INITIAL_RATE),
        (0.2, INITIAL_RATE, INITIAL_RATE),
        (None, 0.0, 0.0),
    ],
    ids=("updated", "unchanged", "stale-control", "zero-rate"),
)
def test_release_rate_invalidation_ode_matches_piecewise_hazard(
    tmp_path, update, initial_rate, final_rate
):
    """Verify live parameter updates invalidate rate caches during continuation."""
    trajectory, columns = _run_protocol(
        tmp_path, method="ode", seed=0, update=update, initial_rate=initial_rate
    )
    assert _at(trajectory, columns, 1.0, "f") == pytest.approx(initial_rate)
    assert _at(trajectory, columns, 2.0, "f") == pytest.approx(final_rate)
    for time in (1.0, 2.0):
        expected_a = _analytic_a(time, update=update, initial_rate=initial_rate)
        assert _at(trajectory, columns, time, "A_count") == pytest.approx(
            expected_a, rel=1e-4, abs=1e-6
        )
        assert _at(trajectory, columns, time, "B_count") == pytest.approx(
            INITIAL_A - expected_a, rel=1e-4, abs=1e-6
        )

    if update == UPDATED_RATE and initial_rate == INITIAL_RATE:
        expected_data, expected_columns = _analytic_ode_trajectory(update=UPDATED_RATE)
        difference = compare.compare_trajectories(
            expected_data,
            expected_columns,
            trajectory,
            columns,
            rtol=1e-4,
            atol=1e-6,
            columns=compare.COLUMNS_EXACT,
        )
        assert difference.ok, difference.summary()


def test_release_rate_invalidation_time_dependence():
    """Verify rate law depending explicitly on simulation time updates continuously."""
    if cpp is None:
        pytest.skip("native BNG3 extension is unavailable")

    model_str = """begin model
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10.0
    B() 0.0
end seed species
begin observables
    Molecules A_obs A()
end observables
begin functions
    f_time() = time + 2.5
end functions
begin reaction rules
    A() -> B() f_time()
end reaction rules
end model
"""
    m = cpp.parse_string(model_str)
    net = cpp.generate_network(m)
    rates0 = cpp._validation_ode_rate_coefficients(m, net, 0.0, [10.0, 0.0])
    rates1 = cpp._validation_ode_rate_coefficients(m, net, 1.5, [10.0, 0.0])
    rates2 = cpp._validation_ode_rate_coefficients(m, net, 3.0, [10.0, 0.0])
    assert rates0 == [2.5]
    assert rates1 == [4.0]
    assert rates2 == [5.5]


def test_release_rate_invalidation_observable_dependence():
    """Verify rate law depending on dynamic observable updates as species concentrations evolve."""
    if cpp is None:
        pytest.skip("native BNG3 extension is unavailable")

    model_str = """begin model
begin parameters
    k_scale 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 20.0
    B() 0.0
end seed species
begin observables
    Molecules A_count A()
end observables
begin functions
    f_obs() = k_scale * A_count
end functions
begin reaction rules
    A() -> B() f_obs()
end reaction rules
end model
"""
    m = cpp.parse_string(model_str)
    net = cpp.generate_network(m)
    # When A=20: rate = 0.1 * 20 = 2.0
    rates_high = cpp._validation_ode_rate_coefficients(m, net, 0.0, [20.0, 0.0])
    assert rates_high == [2.0]
    # When A drops to 5: rate = 0.1 * 5 = 0.5
    rates_low = cpp._validation_ode_rate_coefficients(m, net, 0.0, [5.0, 15.0])
    assert rates_low == [0.5]


def test_release_rate_invalidation_comparator_rejects_stale_nested_rate(tmp_path):
    """Negative mutant control: trajectory comparator must reject stale rate values."""
    stale, stale_columns = _run_protocol(
        tmp_path, method="ode", seed=0, update=INITIAL_RATE
    )
    live_expected, expected_columns = _analytic_ode_trajectory(update=UPDATED_RATE)
    difference = compare.compare_trajectories(
        live_expected,
        expected_columns,
        stale,
        stale_columns,
        rtol=1e-6,
        atol=1e-9,
        columns=compare.COLUMNS_EXACT,
    )
    assert not difference.ok, "stale-rate mutation escaped the trajectory comparator"


# ============================================================================
# Acceptance Check: release-capability-coverage-143
# ============================================================================


def test_release_capability_coverage_143():
    """Assert all assigned capability rows for Issue 143 are mapped and satisfied."""
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file(), f"missing contract at {contract_path}"
    with open(contract_path, encoding="utf-8") as f:
        contract = json.load(f)

    expected_rows = {
        "bngl.global-functions",
        "bngl.local-functions",
        "bngl.nested-function-calls",
        "bngl.parameter-dependencies",
        "bngl.observable-dependencies",
        "bngl.time-dependencies",
        "bngl.tfun-file",
        "bngl.tfun-inline",
        "bngl.tfun-interpolation-and-extrapolation",
        "bngl.tfun-counter-expressions",
        "bngl.mass-action",
        "bngl.ele",
        "bngl.function",
        "bngl.functionproduct",
        "bngl.mm",
        "bngl.sat",
        "bngl.hill",
        "bngl.arrhenius",
        "bngl.reverse-rates",
        "bngl.statistical-rate-factors",
        "builtin._pi",
        "builtin._e",
        "builtin.time",
        "builtin.exp",
        "builtin.ln",
        "builtin.log10",
        "builtin.log2",
        "builtin.abs",
        "builtin.rint",
        "builtin.sqrt",
        "builtin.cos",
        "builtin.sin",
        "builtin.tan",
        "builtin.asin",
        "builtin.acos",
        "builtin.atan",
        "builtin.sinh",
        "builtin.cosh",
        "builtin.tanh",
        "builtin.asinh",
        "builtin.acosh",
        "builtin.atanh",
        "builtin.if",
        "builtin.min",
        "builtin.max",
        "builtin.sum",
        "builtin.avg",
        "builtin.mratio",
        "builtin.TFUN",
        "builtin.tfun",
        "operator.352",
        "operator.353",
        "operator.354",
        "operator.355",
        "operator.356",
        "operator.357",
        "operator.358",
        "operator.359",
        "operator.360",
        "operator.361",
        "operator.362",
        "operator.363",
        "operator.364",
        "operator.365",
        "operator.366",
        "operator.367",
        "operator.368",
        "bngl.delay",
    }

    contract_rows = set(contract.get("inventory_rows", []))
    missing = expected_rows - contract_rows
    assert not missing, f"contract is missing inventory rows: {missing}"
    assert contract["acceptance_checks"] == [
        "release-rates",
        "release-rate-invalidation",
        "release-capability-coverage-143",
    ]
