from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

import bionetgen
from bionetgen import _bionetgen_cpp as cpp


def _simple_decay_model() -> tuple[cpp.Model, cpp.GeneratedNetwork]:
    bngl = """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 50
end seed species
begin observables
  Molecules obsA A()
  Molecules obsB B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    net = cpp.generate_network(model)
    return model, net


# ---------------------------------------------------------------------------
# L2-11-01: Flat binary expression chain depth guard in BNGAstVisitor
# ---------------------------------------------------------------------------


def test_flat_binary_expression_chains_fail_cleanly_without_stack_overflow():
    add_chain = "+".join(["1"] * 2000)
    bngl_add = f"""begin model
begin parameters
  k {add_chain}
end parameters
end model
"""
    with pytest.raises(RuntimeError, match="Maximum expression nesting depth"):
        cpp.parse_string(bngl_add)

    pow_chain = "^".join(["2"] * 2000)
    bngl_pow = f"""begin model
begin parameters
  k {pow_chain}
end parameters
end model
"""
    with pytest.raises(RuntimeError, match="Maximum expression nesting depth"):
        cpp.parse_string(bngl_pow)

    # Moderate chains within limit continue to parse and evaluate accurately.
    ok_chain = "+".join(["1"] * 50)
    bngl_ok = f"""begin model
begin parameters
  k {ok_chain}
end parameters
end model
"""
    model = cpp.parse_string(bngl_ok)
    snap = cpp._compiled_snapshot(model)
    assert snap["parameters"][0]["name"] == "k"
    assert snap["parameters"][0]["constant_value"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# L2-11-03: Recursion depth guard in C++ BNGIR expressionFromBngir
# ---------------------------------------------------------------------------


def test_bngir_native_importer_rejects_cyclic_and_deep_expressions():
    model, _ = _simple_decay_model()
    doc = json.loads(bionetgen.to_bngir(bionetgen.BioNetGenModel(model), version="0.2"))
    # Ensure native v0.2 importer reaches parameter expression parsing directly
    doc["model"]["observables"] = []

    # 1. Self-referential cyclic expression dictionary
    cyclic: dict[str, object] = {"kind": "unary", "operator": "negate"}
    cyclic["arguments"] = [cyclic]
    doc_cyclic = json.loads(json.dumps(doc))
    doc_cyclic["model"]["parameters"][0]["expression"] = cyclic
    doc_cyclic["model"]["parameters"][0].pop("constant_value", None)
    with pytest.raises(RuntimeError, match="nesting depth"):
        cpp._model_from_bngir_v02(doc_cyclic["model"])

    # 2. Deep acyclic nested expression (> 256 levels)
    deep: dict[str, object] = {"kind": "number", "value": 1.0}
    for _ in range(600):
        deep = {"kind": "unary", "operator": "negate", "arguments": [deep]}
    doc_deep = json.loads(json.dumps(doc))
    doc_deep["model"]["parameters"][0]["expression"] = deep
    doc_deep["model"]["parameters"][0].pop("constant_value", None)
    with pytest.raises(RuntimeError, match="nesting depth"):
        cpp._model_from_bngir_v02(doc_deep["model"])


# ---------------------------------------------------------------------------
# L2-11-06 & L2-05-07: Simulation binding validation & float64 batch times
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_steps", [-1, -5])
def test_simulation_bindings_reject_negative_n_steps(bad_steps: int):
    model, net = _simple_decay_model()

    with pytest.raises(ValueError, match="n_steps"):
        cpp.simulate_ode(model, net, t_end=1.0, n_steps=bad_steps)
    with pytest.raises(ValueError, match="n_steps"):
        cpp.simulate_ssa(model, net, t_end=1.0, n_steps=bad_steps, seed=1)
    with pytest.raises(ValueError, match="n_steps"):
        cpp.simulate_pla(model, net, t_end=1.0, n_steps=bad_steps, seed=1)
    with pytest.raises(ValueError, match="n_steps"):
        cpp.simulate_psa(
            model, net, t_end=1.0, n_steps=bad_steps, poplevel=10.0, seed=1
        )
    with pytest.raises(ValueError, match="n_steps"):
        cpp.simulate_ode_bngsim(model, net, t_end=1.0, n_steps=bad_steps)
    with pytest.raises(ValueError, match="n_steps"):
        cpp.simulate_ssa_bngsim(model, net, t_end=1.0, n_steps=bad_steps, seed=1)
    with pytest.raises(ValueError, match="n_steps"):
        cpp.simulate_psa_bngsim(
            model, net, t_end=1.0, n_steps=bad_steps, poplevel=10.0, seed=1
        )
    with pytest.raises(ValueError, match="n_steps"):
        cpp.simulate_batch_ssa_cpu(
            model, net, batch_size=4, t_end=1.0, n_steps=bad_steps, base_seed=1
        )
    with pytest.raises(ValueError, match="n_steps"):
        cpp.simulate_batch_ssa_gpu(
            model, net, batch_size=4, t_end=1.0, n_steps=bad_steps, base_seed=1
        )


@pytest.mark.parametrize(
    "bad_poplevel",
    [float("nan"), float("inf"), float("-inf"), -1.0, -1e-9],
)
def test_simulate_psa_rejects_nonfinite_and_negative_poplevel(bad_poplevel: float):
    model, net = _simple_decay_model()
    with pytest.raises(ValueError, match="poplevel"):
        cpp.simulate_psa(
            model, net, t_end=1.0, n_steps=2, poplevel=bad_poplevel, seed=42
        )
    with pytest.raises(ValueError, match="poplevel"):
        cpp.simulate_psa_bngsim(
            model, net, t_end=1.0, n_steps=2, poplevel=bad_poplevel, seed=42
        )


def test_simulate_ode_rejects_negative_seed():
    model, net = _simple_decay_model()
    with pytest.raises(ValueError, match="seed"):
        cpp.simulate_ode(model, net, t_end=1.0, n_steps=2, seed=-1)


def test_batch_ssa_cpu_exports_float64_time_points():
    model, net = _simple_decay_model()
    t0 = 1e7
    res = cpp.simulate_batch_ssa_cpu(
        model, net, batch_size=8, t_start=t0, t_end=t0 + 1.0, n_steps=5, base_seed=42
    )
    times = np.asarray(res["time"])
    assert times.dtype == np.float64
    expected = np.linspace(t0, t0 + 1.0, 6)
    np.testing.assert_allclose(times, expected, rtol=0.0, atol=1e-9)
    assert np.all(np.diff(times) > 0.0)


# ---------------------------------------------------------------------------
# L2-01-11: jax_ode_flatten volume_scales for MM / Sat / Hill in compartments
# ---------------------------------------------------------------------------


def test_jax_ode_flatten_preserves_compartment_volume_scales_for_saturating_rates():
    bngl = """begin model
begin parameters
  V_CP 5.0
  kcat 0.5
  Km 150.0
  Vmax 40.0
  Kh 120.0
  nh 2.0
  k_tot 1.0
end parameters
begin compartments
  CP 3 V_CP
end compartments
begin molecule types
  E()
  X()
  Y()
  S()
  P()
  U()
  V()
end molecule types
begin seed species
  E()@CP 200
  X()@CP 350
  S()@CP 300
  U()@CP 250
end seed species
begin reaction rules
  r_mm: X()@CP + E()@CP -> Y()@CP + E()@CP MM(kcat, Km)
  r_sat: S()@CP + E()@CP -> P()@CP + E()@CP Sat(kcat, Km)
  r_hill: U()@CP + E()@CP -> V()@CP + E()@CP Hill(Vmax, Kh, nh)
  r_tot: X()@CP + E()@CP -> Y()@CP + E()@CP k_tot TotalRate
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    net = cpp.generate_network(model)
    flat = cpp.jax_ode_flatten(model, net)
    # MM, Sat, and Hill are bimolecular in V_CP=5 -> volume_scales = 1/5 = 0.2;
    # authored TotalRate rule retains volume_scales = 1.0.
    np.testing.assert_allclose(flat["volume_scales"], [0.2, 0.2, 0.2, 1.0], rtol=1e-12)


# ---------------------------------------------------------------------------
# L2-01-06 & L2-05-01: jax_ssa_flatten fails closed on functional & absolute-flux
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bngl",
    [
        """begin model
begin parameters
  k0 2.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 20
end seed species
begin observables
  Molecules obsA A()
end observables
begin functions
  rate_f() = k0 / (1 + obsA/10)
end functions
begin reaction rules
  A() -> B() rate_f()
end reaction rules
end model
""",
        """begin model
begin molecule types
  S()
  P()
end molecule types
begin seed species
  S() 100
end seed species
begin reaction rules
  S() -> P() Sat(50.0, 100.0)
end reaction rules
end model
""",
        """begin model
begin molecule types
  X()
  E()
  Y()
end molecule types
begin seed species
  X() 100
  E() 50
end seed species
begin reaction rules
  X() + E() -> Y() + E() MM(0.5, 150.0)
end reaction rules
end model
""",
        """begin model
begin molecule types
  U()
  V()
end molecule types
begin seed species
  U() 100
end seed species
begin reaction rules
  U() -> V() Hill(40.0, 120.0, 2.0)
end reaction rules
end model
""",
        """setOption("BNG3AbsoluteFluxRules", "r_abs")
begin model
begin parameters
  k 3.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 50
  B() 0
end seed species
begin reaction rules
  r_abs: A() -> B() k TotalRate
end reaction rules
end model
""",
    ],
)
def test_jax_ssa_flatten_fails_closed_on_functional_and_absolute_flux(bngl: str):
    model = cpp.parse_string(bngl)
    net = cpp.generate_network(model)
    with pytest.raises(RuntimeError, match="JAX SSA does not yet support"):
        cpp.jax_ssa_flatten(model, net)


# ---------------------------------------------------------------------------
# L2-11-08: TfunReader rejects NaN/Inf/garbage/truncated/trailing-token rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "0 1\n2 nan\n1 3\n",
        "0 nan\n1 2\n",
        "0 1\n1 inf\n2 3\n",
        "0 1\n1 -inf\n2 3\n",
        "0 1\n1 not_a_number\n2 3\n",
        "0 1\n1\n2 3\n",
        "0 1\n1 2 3\n",
        "0 1\n1 2abc\n",
        "0 1\n2 5\n1 3\n",
    ],
)
def test_tfun_reader_rejects_malformed_and_nonfinite_rows(tmp_path: Path, content: str):
    tfun_path = tmp_path / "bad.tfun"
    tfun_path.write_text(content, encoding="utf-8")
    bngl_path = tmp_path / "m.bngl"
    bngl_path.write_text(
        """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules obsB B()
end observables
begin functions
  f() = tfun('bad.tfun', time)
end functions
begin reaction rules
  A() -> B() f()
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode", t_end=>2, n_steps=>2})
""",
        encoding="utf-8",
    )
    model = cpp.parse_file(str(bngl_path))
    with pytest.raises(RuntimeError, match="TFUN"):
        cpp.execute(model, str(bngl_path), False)


def test_tfun_reader_accepts_inline_comments_and_whitespace(tmp_path: Path):
    tfun_path = tmp_path / "good.tfun"
    tfun_path.write_text(
        "# header comment\n   \n  0.0   1.0  # first knot\n  2.0   1.0\n",
        encoding="utf-8",
    )
    bngl_path = tmp_path / "m.bngl"
    bngl_path.write_text(
        """begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules obsA A()
end observables
begin functions
  f() = tfun('good.tfun', time)
end functions
begin reaction rules
  A() -> B() f()
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode", t_end=>1, n_steps=>2})
""",
        encoding="utf-8",
    )
    model = cpp.parse_file(str(bngl_path))
    cpp.execute(model, str(bngl_path), False)
    gdat = (tmp_path / "m.gdat").read_text(encoding="utf-8").strip().splitlines()
    final_a = float(gdat[-1].split()[1])
    assert final_a == pytest.approx(100.0 * math.exp(-1.0), rel=1e-4)


# ---------------------------------------------------------------------------
# L2-01-10: tfun file cache keys by (filename, method)
# ---------------------------------------------------------------------------


def test_tfun_file_cache_separates_linear_and_step_methods(tmp_path: Path):
    (tmp_path / "pulse.tfun").write_text(
        "# time value\n0.0 0.0\n1.0 0.5\n2.5 2.0\n4.0 0.2\n5.0 1.5\n",
        encoding="utf-8",
    )
    bngl_path = tmp_path / "m_tfun_methods.bngl"
    bngl_path.write_text(
        """begin model
begin parameters
  kbase 0.1
end parameters
begin molecule types
  A()
  B()
  C()
  D()
end molecule types
begin seed species
  A() 400
  C() 400
end seed species
begin observables
  Molecules A_obs A()
  Molecules C_obs C()
  Molecules D_obs D()
end observables
begin functions
  f_lin() = kbase + 0.5 * tfun('pulse.tfun', time, method=>'linear')
  f_step() = tfun('pulse.tfun', time, method=>'step') * 0.4 + kbase
end functions
begin reaction rules
  A() -> B() f_lin()
  C() -> D() f_step()
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode", t_end=>5, n_steps=>10})
""",
        encoding="utf-8",
    )
    model = cpp.parse_file(str(bngl_path))
    cpp.execute(model, str(bngl_path), False)
    rows = [
        [float(x) for x in line.split()]
        for line in (tmp_path / "m_tfun_methods.gdat")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    # Row at t = 0.5:
    # - step holds 0.0 on [0, 1) => rate = 0.1 => C(0.5) = 400 * exp(-0.05)
    # - linear interpolates 0.25*t on [0, 1] => integral(0.1 + 0.25*t, 0..0.5) = 0.08125
    row_half = next(r for r in rows if abs(r[0] - 0.5) < 1e-9)
    assert row_half[2] == pytest.approx(400.0 * math.exp(-0.05), rel=1e-4)
    assert row_half[1] == pytest.approx(400.0 * math.exp(-0.08125), rel=1e-4)

    # Row at t = 2.5:
    # step integral on [0, 2.5]: [0,1)->0.1*1=0.1; [1,2.5)->(0.1+0.2)*1.5=0.45 => total=0.55
    # D(2.5) = 400 * (1 - exp(-0.55)) = 169.220...
    row_25 = next(r for r in rows if abs(r[0] - 2.5) < 1e-9)
    assert row_25[3] == pytest.approx(400.0 * (1.0 - math.exp(-0.55)), rel=1e-3)


# ---------------------------------------------------------------------------
# L2-11-10a, L2-11-05, & L2-08-02: Compartments & energy-pattern prefix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_dim", [4, 999999, 99999999999999999999])
def test_compartment_invalid_spatial_dimension_rejected(bad_dim: int):
    bngl = f"""begin model
begin compartments
  EC {bad_dim} 1.0
end compartments
end model
"""
    with pytest.raises(RuntimeError, match="spatial dimension"):
        cpp.parse_string(bngl)


@pytest.mark.parametrize("valid_dim", [0, 1, 2, 3])
def test_compartment_valid_spatial_dimensions_accepted(valid_dim: int):
    bngl = f"""begin model
begin compartments
  C {valid_dim} 1.0
end compartments
end model
"""
    model = cpp.parse_string(bngl)
    assert len(model.compartments) == 1


@pytest.mark.parametrize("bad_vol", ["1/0", "0/0"])
def test_compartment_nonfinite_volume_rejected(bad_vol: str):
    bngl = f"""begin model
begin compartments
  EC 3 {bad_vol}
end compartments
end model
"""
    with pytest.raises(RuntimeError, match="finite"):
        cpp.parse_string(bngl)


@pytest.mark.parametrize(
    "comp_block",
    [
        "  C1 3 1 C1\n",
        "  C1 3 1 C2\n  C2 3 1 C1\n",
        "  C1 3 1 C2\n  C2 3 1 C3\n  C3 3 1 C1\n",
    ],
)
def test_cyclic_compartment_parent_hierarchy_rejected_at_parse(comp_block: str):
    bngl = f"""begin model
begin compartments
{comp_block}end compartments
begin molecule types
  A(b)
  B(b)
end molecule types
begin seed species
  A(b!1)@C1.B(b!1)@C1 10
end seed species
end model
"""
    with pytest.raises(RuntimeError, match="Cyclic compartment"):
        cpp.parse_string(bngl)


def test_energy_pattern_preserves_species_prefix_compartment():
    bngl = """begin model
begin parameters
  G_pm -2.0
  G_cp  2.0
  phi   0.5
  Ea    0.0
end parameters
begin compartments
  EC 3 1.0
  PM 2 1.0 EC
  CP 3 1.0 PM
end compartments
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  @PM:A(s~U) 100
  @CP:A(s~U) 100
end seed species
begin energy patterns
  E1: @PM:A(s~P) G_pm
  E2: @CP:A(s~P) G_cp
end energy patterns
begin reaction rules
  R_pm: @PM:A(s~U) <-> @PM:A(s~P) Arrhenius(phi, Ea)
  R_cp: @CP:A(s~U) <-> @CP:A(s~P) Arrhenius(phi, Ea)
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    snap = cpp._compiled_snapshot(model)
    eps = snap["energy_patterns"]
    assert len(eps) == 2
    assert eps[0]["pattern"]["compartment"] == "PM"
    assert eps[0]["pattern"]["compartment_prefix"] is True
    assert eps[1]["pattern"]["compartment"] == "CP"
    assert eps[1]["pattern"]["compartment_prefix"] is True


# ---------------------------------------------------------------------------
# L2-10-08a: Reversible one-sided local scope in compiled snapshot / BNGIR
# ---------------------------------------------------------------------------


def test_reversible_one_sided_local_scope_snapshot_and_bngir_roundtrip():
    bngl = """begin model
begin parameters
  lp2 0.5
  lm2 0.2
end parameters
begin molecule types
  R(P~1~x,a)
end molecule types
begin seed species
  R(P~1,a) 100
end seed species
begin observables
  Molecules Crosslink R(a!+)
  Molecules Rx R(P~x)
end observables
begin reaction rules
  %x:R(P~1) <-> R(P~x) if(Crosslink(x)>0,0,lp2), lm2
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    snap = cpp._compiled_snapshot(model)
    rule = snap["rules"][0]
    assert len(rule["forward"]["local_scopes"]) == 1
    assert rule["forward"]["local_scopes"][0]["name"] == "x"
    assert rule["forward"]["local_scopes"][0]["reactant_pattern"] == 0
    assert rule["reverse"]["local_scopes"] == []

    wrapped = bionetgen.BioNetGenModel(model)
    ir_text = bionetgen.to_bngir(wrapped)
    restored = bionetgen.from_bngir(ir_text)
    assert restored is not None
