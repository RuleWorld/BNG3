"""Regression tests for Wave 1 audit fixes (parser, expressions, units, thermo).

Covers all 11 bugs assigned to Wave 1:
1. MEM-02 / EXPR-08: TFUN NaN heap OOB read and unsorted knot validation
2. EXPR-02 / RULEHUB-07: User parameter named `t` not hijacked as simulation time
3. EXPR-03: ModelFunctionEvaluator argument capture and dynamic scoping leak
4. EXPR-04: Fortran [fFgG] float exponents not silently truncated
5. MEM-03 / EXPR-09: Deeply nested parentheses fail cleanly without stack overflow
6. EXPR-10: Power base unary parenthesization `((-k) ^ 2)` and double negation `-(-x)`
7. ETH-02: Unbound-site energy patterns `A(b) G_free` not turned into wildcards
8. NET-05: Seed species compartment inference uses 2D-surface hierarchy precedence
9. EXPR-16: User functions/observables (`Max`, `Sign`, etc.) not hijacked by builtins
10. ETH-14 / ETH-15: Barrier comma check, `driven_by` right boundary, barrier context leak
11. EXPR-14: Unit power int32 overflow, `0*s` / `1/0*s`, `**`, `L^-2`, unary `~`,
    2D compartments `[um^2]`, and scale mismatch in strict additive unit checks
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from unittest import mock

import pytest

import bionetgen._bionetgen_cpp as _cpp


def _eval_ode_final(source: str, t_end: float = 1.0, n_steps: int = 10):
    model = _cpp.parse_string(source)
    net = _cpp.generate_network(model)
    result = _cpp.simulate_ode(model, net, t_end=t_end, n_steps=n_steps)
    return model, net, result


# ---------------------------------------------------------------------------
# 1. MEM-02 / EXPR-08: TFUN NaN guard & monotonic knot validation
# ---------------------------------------------------------------------------


def test_tfun_nan_returns_nan_without_oob_and_unsorted_rejected():
    # Inline TFUN with NaN counter must evaluate to NaN cleanly (both linear and step)
    nan_model = _cpp.parse_string(
        """begin model
begin parameters
  p_lin  tfun([0, 1], [10, 20], 0/0)
  p_step tfun([0, 1], [10, 20], 0/0, method=>"step")
  p_ok   tfun([0, 1], [10, 20], 0.5)
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
end model
"""
    )
    nan_model.parameter_list.evaluate_all()
    assert math.isnan(nan_model.get_parameter("p_lin").value)
    assert math.isnan(nan_model.get_parameter("p_step").value)
    assert nan_model.get_parameter("p_ok").value == pytest.approx(15.0)

    # Unsorted inline x-values must be rejected
    with pytest.raises(RuntimeError, match="monotonically non-decreasing"):
        _cpp.parse_string(
            """begin model
begin parameters
  p_bad tfun([0, 2, 1, 3], [10, 20, 30, 40], 1.5)
end parameters
end model
"""
        )


def test_tfun_file_unsorted_and_nan_guarded(tmp_path: Path):
    unsorted_tfun = tmp_path / "unsorted.tfun"
    unsorted_tfun.write_text("0.0 1.0\n2.0 3.0\n1.0 2.0\n", encoding="utf-8")
    bngl_unsorted = tmp_path / "unsorted.bngl"
    bngl_unsorted.write_text(
        """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  f() = tfun('unsorted.tfun', time)
end functions
begin reaction rules
  A() -> 0 f()
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode", t_end=>1, n_steps=>5})
""",
        encoding="utf-8",
    )
    model = _cpp.parse_file(str(bngl_unsorted))
    with pytest.raises(RuntimeError, match="monotonically non-decreasing"):
        _cpp.execute(model, str(bngl_unsorted))

    # Valid file-backed tfun with NaN counter must not crash / OOB read
    valid_tfun = tmp_path / "valid.tfun"
    valid_tfun.write_text("0.0 1.0\n1.0 2.0\n", encoding="utf-8")
    bngl_nan = tmp_path / "nan_file.bngl"
    bngl_nan.write_text(
        """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Aobs A()
end observables
begin functions
  f() = tfun('valid.tfun', 0/0)
end functions
begin reaction rules
  A() -> 0 f()
end reaction rules
end model
""",
        encoding="utf-8",
    )
    # Executing ODE on NaN rate either raises a clean numeric error or produces NaN;
    # critically it must NEVER trigger a heap-buffer-overflow crash.
    nan_file_model = _cpp.parse_file(str(bngl_nan))
    net = _cpp.generate_network(nan_file_model)
    try:
        res = _cpp.simulate_ode(nan_file_model, net, t_end=0.1, n_steps=1)
        assert res is not None
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# 2. EXPR-02 / RULEHUB-07: User parameter named `t` not hijacked as clock
# ---------------------------------------------------------------------------


def test_user_parameter_t_is_not_hijacked_as_simulation_time():
    source = """begin model
begin parameters
  t 5.0
  k 2*t
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 0.01*k
end reaction rules
end model
"""
    model = _cpp.parse_string(source)
    model.parameter_list.evaluate_all(0.0)
    assert model.get_parameter("t").value == pytest.approx(5.0)
    assert model.get_parameter("k").value == pytest.approx(10.0)

    # Also evaluate at a nonzero time t=3.0: user parameter t must remain 5.0!
    model.parameter_list.evaluate_all(3.0)
    assert model.get_parameter("k").value == pytest.approx(10.0)

    # Without a declared parameter `t`, bare `t` and `time` still resolve to clock
    clock_model = _cpp.parse_string(
        """begin model
begin parameters
  k_time 2*time
  k_t    2*t
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 10
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
end observables
begin reaction rules
  A() -> 0 k_time
  B() -> 0 k_t
end reaction rules
end model
"""
    )
    clock_net = _cpp.generate_network(clock_model)
    clock_res = _cpp.simulate_ode(clock_model, clock_net, t_end=1.0, n_steps=10)
    # Integral of 2*t from 0 to 1 is 1.0 -> A(1) = B(1) = 10 * exp(-1)
    assert clock_res["observables"]["Atot"][-1] == pytest.approx(10.0 * math.exp(-1.0), rel=1e-4)
    assert clock_res["observables"]["Btot"][-1] == pytest.approx(10.0 * math.exp(-1.0), rel=1e-4)


# ---------------------------------------------------------------------------
# 3. EXPR-03: ModelFunctionEvaluator argument capture & dynamic scoping
# ---------------------------------------------------------------------------


def test_function_expansion_lexical_scoping_and_no_argument_capture():
    source = """begin model
begin parameters
  a 10
  x 100
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
  B() 100
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
end observables
begin functions
  g() = x
  f_dyn(x) = g()
  add2(a, b) = a + b
  f_capture() = add2(1, a)
  f_dyn_call() = f_dyn(5)
end functions
begin reaction rules
  A() -> 0 0.01 * f_capture()
  B() -> 0 0.01 * f_dyn_call()
end reaction rules
end model
"""
    _, _, result = _eval_ode_final(source, t_end=1.0, n_steps=10)
    # add2(1, a) = 1 + 10 = 11 -> A(1) = 100 * exp(-0.11)
    assert result["observables"]["Atot"][-1] == pytest.approx(
        100.0 * math.exp(-0.11), rel=1e-4
    )
    # f_dyn(5) -> g() -> global x = 100 -> B(1) = 100 * exp(-1.00)
    assert result["observables"]["Btot"][-1] == pytest.approx(
        100.0 * math.exp(-1.0), rel=1e-4
    )


# ---------------------------------------------------------------------------
# 4. EXPR-04: Fortran [fFgG] float exponents
# ---------------------------------------------------------------------------


def test_fortran_float_exponents_not_truncated():
    model = _cpp.parse_string(
        """begin model
begin parameters
  p1 1.5f2
  p2 2F-3
  p3 1g3
  p4 1.5G+2
  p5 2.5D-2
  p6 3.5d+1
end parameters
end model
"""
    )
    model.parameter_list.evaluate_all()
    assert model.get_parameter("p1").value == pytest.approx(150.0)
    assert model.get_parameter("p2").value == pytest.approx(0.002)
    assert model.get_parameter("p3").value == pytest.approx(1000.0)
    assert model.get_parameter("p4").value == pytest.approx(150.0)
    assert model.get_parameter("p5").value == pytest.approx(0.025)
    assert model.get_parameter("p6").value == pytest.approx(35.0)


# ---------------------------------------------------------------------------
# 5. MEM-03 / EXPR-09: Deeply nested parens fail cleanly without SIGSEGV
# ---------------------------------------------------------------------------


def test_deeply_nested_parentheses_fail_cleanly():
    deep = "(" * 2000 + "1" + ")" * 2000
    source = f"begin model\nbegin parameters\n  p {deep}\nend parameters\nend model\n"
    with pytest.raises(RuntimeError, match="nesting depth"):
        _cpp.parse_string(source)

    # Reasonable nesting depth still succeeds
    ok = "(" * 20 + "42" + ")" * 20
    m = _cpp.parse_string(
        f"begin model\nbegin parameters\n  p {ok}\nend parameters\nend model\n"
    )
    m.parameter_list.evaluate_all()
    assert m.get_parameter("p").value == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# 6. EXPR-10: Power base unary parenthesization & double negation
# ---------------------------------------------------------------------------


def test_power_unary_base_and_double_negation_rendering():
    model = _cpp.parse_string(
        """begin model
begin parameters
  k 2
  p_negk (-k)^2
  p_dbl -(-k)
end parameters
begin functions
  f_negk() = (-k)^2
  f_dbl() = -(-k)
end functions
end model
"""
    )
    model.parameter_list.evaluate_all()
    assert model.get_parameter("p_negk").value == pytest.approx(4.0)
    assert model.get_parameter("p_dbl").value == pytest.approx(2.0)

    params_by_name = {p.name: p for p in model.parameters}
    rendered_negk = params_by_name["p_negk"].expression.to_string()
    assert rendered_negk == "((-k) ^ 2)"

    rendered_dbl = params_by_name["p_dbl"].expression.to_string()
    assert rendered_dbl == "-(-k)"
    assert "--" not in rendered_dbl

    # Round-tripping the rendered expressions parses cleanly and keeps values
    rt = _cpp.parse_string(
        f"""begin model
begin parameters
  k 2
  p_negk {rendered_negk}
  p_dbl  {rendered_dbl}
end parameters
end model
"""
    )
    rt.parameter_list.evaluate_all()
    assert rt.get_parameter("p_negk").value == pytest.approx(4.0)
    assert rt.get_parameter("p_dbl").value == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 7. ETH-02: Unbound-site energy patterns `A(b) G_free`
# ---------------------------------------------------------------------------


def test_unbound_site_energy_pattern_affects_delta_g():
    source = """begin model
begin parameters
  phi 0.5
  Ea  1.0
  G_free 5.0
  GAB 3.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 30
  B(a) 30
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin energy patterns
  A(b) G_free
  A(b!1).B(a!1) GAB
end energy patterns
begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    _, _, result = _eval_ode_final(source, t_end=30.0, n_steps=30)
    # Exact Boltzmann equilibrium: AB / (30 - AB)^2 = exp(-(GAB - G_free)) = exp(2)
    # Solving quadratic: exp(2) * (30 - x)^2 - x = 0 -> x ~= 28.052
    keq = math.exp(2.0)
    expected_ab = (2.0 * 30.0 * keq + 1.0 - math.sqrt(1.0 + 4.0 * 30.0 * keq)) / (
        2.0 * keq
    )
    assert result["observables"]["AB"][-1] == pytest.approx(expected_ab, rel=1e-3)


# ---------------------------------------------------------------------------
# 8. NET-05: Seed species compartment inference (2D surface precedence)
# ---------------------------------------------------------------------------


def test_seed_species_compartment_inference_prefers_2d_surface():
    source = """begin model
begin parameters
  kf 1.0
end parameters
begin compartments
  EC 3 10
  PM 2 2 EC
  CP 3 5 PM
end compartments
begin molecule types
  L(r)
  R(l,c)
  C(r)
end molecule types
begin seed species
  R(l!1,c)@PM.L(r!1)@EC 10
  C(r)@CP 10
end seed species
begin reaction rules
  R(c)@PM + C(r)@CP -> R(c!1)@PM.C(r!1)@CP kf
end reaction rules
end model
"""
    model = _cpp.parse_string(source)
    assert model.seed_species[0].compartment == "PM"
    assert model.seed_species[1].compartment == "CP"

    net = _cpp.generate_network(model)
    # Before fix, seed 0 got @EC and reaction R(c)@PM + C(r)@CP yielded 0 reactions!
    assert net.num_species == 3
    assert net.num_reactions == 1

    # 3-compartment spanning complex L@EC.R@PM.C@CP must also infer @PM
    span = _cpp.parse_string(
        """begin model
begin compartments
  EC 3 10
  PM 2 2 EC
  CP 3 5 PM
end compartments
begin molecule types
  L(r)
  R(l,c)
  C(r)
end molecule types
begin seed species
  L(r!1)@EC.R(l!1,c!2)@PM.C(r!2)@CP 5
end seed species
end model
"""
    )
    assert span.seed_species[0].compartment == "PM"


# ---------------------------------------------------------------------------
# 9. EXPR-16: User functions/observables not hijacked by case-insensitive builtins
# ---------------------------------------------------------------------------


def test_user_functions_and_observables_not_hijacked_by_builtins():
    source = """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
  B() 100
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
  Molecules Sign A()
end observables
begin functions
  Max(x) = 2.0
  f_max() = Max(1)
  f_sign() = 0.01 * Sign()
end functions
begin reaction rules
  A() -> 0 0.01 * f_max()
  B() -> 0 0.01 * f_sign()
end reaction rules
end model
"""
    _, _, result = _eval_ode_final(source, t_end=1.0, n_steps=10)
    # Max(1) must return 2.0 (user function), NOT builtin max(1) = 1.0
    assert result["observables"]["Atot"][-1] == pytest.approx(
        100.0 * math.exp(-0.02), rel=1e-4
    )
    # Sign() must resolve to observable Sign (initially 100), not crash on builtin sign()
    assert result["observables"]["Btot"][-1] < 100.0


# ---------------------------------------------------------------------------
# 10. ETH-14 / ETH-15: Barrier commas, driven_by word boundary, barrier context leak
# ---------------------------------------------------------------------------


def test_driven_by_identifier_prefix_and_barrier_commas_and_context_leak(tmp_path: Path):
    # Ordinary parameter starting with `driven_by` must parse and run cleanly
    prefix_source = """begin model
begin parameters
  driven_by_k 0.5
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 100
end seed species
begin observables
  Molecules A1 A(s~1)
end observables
begin reaction rules
  A(s~0) -> A(s~1) driven_by_k
end reaction rules
end model
"""
    _, _, res = _eval_ode_final(prefix_source, t_end=1.0, n_steps=5)
    assert res["observables"]["A1"][-1] == pytest.approx(
        100.0 * (1.0 - math.exp(-0.5)), rel=1e-4
    )

    # Barrier pattern with commas inside molecule parens and 2-arg function must parse
    multi_comp_barrier = """begin model
begin parameters
  phi 0.5
  Ea  1.0
  G1  2.0
  G2  3.0
  GP  -1.0
end parameters
begin molecule types
  A(b, s~0~1)
end molecule types
begin seed species
  A(b, s~0) 100
end seed species
begin energy patterns
  A(s~1) GP
end energy patterns
begin barrier patterns
  A(b!?, s~0) -> A(b!?, s~1) min(G1, G2)
end barrier patterns
begin reaction rules
  A(s~0) <-> A(s~1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    m = _cpp.parse_string(multi_comp_barrier)
    assert len(m.barrier_patterns) == 1
    with mock.patch.dict(os.environ, {"BNG_NFSIM_GENERAL_ENERGY": "1"}):
        net = _cpp.generate_network(m)
        net_path = tmp_path / "barrier_ok.net"
        _cpp.io.write_net(m, net, str(net_path))
        assert "R1Rate_1" in net_path.read_text(encoding="utf-8")

    # Top-level comma (rate pair) in a barrier pattern must still be rejected
    with pytest.raises(RuntimeError, match="not a rate pair"):
        _cpp.parse_string(
            """begin model
begin molecule types
  A(b, s~0~1)
end molecule types
begin barrier patterns
  A(b, s~0) -> A(b, s~1) 1.0, 2.0
end barrier patterns
end model
"""
        )

    # Context-bearing barrier pattern must fail closed instead of leaking onto free A
    context_barrier = """begin model
begin parameters
  phi 0.5
  Ea  1.0
  Gbar 3.0
  GP  -1.0
end parameters
begin molecule types
  A(b, s~0~1)
  B(a)
end molecule types
begin seed species
  A(b, s~0) 50
  A(b!1, s~0).B(a!1) 50
end seed species
begin energy patterns
  A(s~1) GP
end energy patterns
begin barrier patterns
  A(b!1, s~0).B(a!1) -> A(b!1, s~1).B(a!1) Gbar
end barrier patterns
begin reaction rules
  A(s~0) <-> A(s~1) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    cm = _cpp.parse_string(context_barrier)
    with mock.patch.dict(os.environ, {"BNG_NFSIM_GENERAL_ENERGY": "1"}):
        cnet = _cpp.generate_network(cm)
        with pytest.raises(RuntimeError, match="context"):
            _cpp.io.write_net(cm, cnet, str(tmp_path / "context_barrier.net"))


# ---------------------------------------------------------------------------
# 11. EXPR-14: Unit overflow, 0*s / 1/0*s, **, L^-2, ~x, 2D compartments,
#              and scale mismatch in strict additive unit checks
# ---------------------------------------------------------------------------


def test_unit_parser_overflow_and_zero_scale_rejected():
    # Overflowing nested exponent must fail cleanly without int32 UB wrap
    with pytest.raises(RuntimeError, match="overflow|Unknown unit"):
        _cpp.parse_string(
            """begin model
begin parameters
  p = 1.0 [((((s^1000)^1000)^1000)^1000)]
end parameters
end model
"""
        )

    # 0*s and 1/0*s must be rejected
    for bad_unit in ("0*s", "1/0*s", "0.0*metre"):
        with pytest.raises(RuntimeError, match="positive|Unknown unit"):
            _cpp.parse_string(
                f"""begin model
begin parameters
  p = 1.0 [{bad_unit}]
end parameters
end model
"""
            )


def test_unit_analysis_power_neg_exp_tilde_2d_comp_and_scale_mismatch():
    # Valid strict model with L^-2, L**2, unary ~, and 2D compartment [um^2]
    valid_strict = _cpp.parse_string(
        """begin model
setOption("units", "strict")
begin parameters
  L = 2.0 [metre]
  inv_area = L^-2 [metre^-2]
  area_pow = L**2 [metre^2]
  t1 = 1.0 [s]
  not_t = ~t1 [dimensionless]
  k = 0.5 [s^-1]
end parameters
begin compartments
  EC 3 10 [fL]
  PM 2 5 EC [um^2]
end compartments
begin molecule types
  A()
end molecule types
begin seed species
  A()@PM 10 [molecule]
end seed species
begin reaction rules
  A()@PM -> 0 k
end reaction rules
end model
"""
    )
    snap = _cpp._compiled_snapshot(valid_strict)
    assert snap is not None

    # `L**2 [second]` must be rejected in strict mode (was bypassed because `**` was omitted)
    bad_pow = _cpp.parse_string(
        """begin model
setOption("units", "strict")
begin parameters
  L = 2.0 [metre]
  bogus = L**2 [second]
end parameters
end model
"""
    )
    with pytest.raises(RuntimeError, match="invalid model"):
        _cpp._compiled_snapshot(bad_pow)

    # `1 [s] + 1 [min]` must be rejected (differently scaled units cannot be added without conversion)
    scale_mismatch = _cpp.parse_string(
        """begin model
setOption("units", "strict")
begin parameters
  t1 = 1.0 [s]
  t2 = 1.0 [min]
  tsum = t1 + t2 [s]
end parameters
end model
"""
    )
    with pytest.raises(RuntimeError, match="invalid model"):
        _cpp._compiled_snapshot(scale_mismatch)

    # 2D compartment with non-spatial unit [second] must be rejected (2D accepts area L^2 or effective volume L^3)
    bad_2d_comp = _cpp.parse_string(
        """begin model
setOption("units", "strict")
begin compartments
  EC 3 10 [fL]
  PM 2 5 EC [second]
end compartments
end model
"""
    )
    with pytest.raises(RuntimeError, match="invalid model"):
        _cpp._compiled_snapshot(bad_2d_comp)
