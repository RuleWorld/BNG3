"""Parameterized test suite qualifying native BNGIR reconstruction with compartments and live rates.

Verifies parser-free native reconstruction of compartmented models, hierarchical
compartment geometries, live functional rate laws, and subsequent ODE and SSA simulation
against independently derived closed-form analytic oracles and conservation laws.
"""

from __future__ import annotations

import copy
import importlib
import json
import math

import pytest

import bionetgen
from _extdep import require_extension

require_extension()

from bionetgen.model import _cpp


def _assert_no_source_parsing(monkeypatch):
    """Enforce that native reconstruction does not parse or emit BNGL source."""
    bngir_module = importlib.import_module("bionetgen.bngir")

    def forbidden(*_args, **_kwargs):
        pytest.fail(
            "Native BNGIR reconstruction attempted BNGL source parsing or emission"
        )

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    monkeypatch.setattr(bngir_module, "_as_bngl_v02", forbidden)


def test_ordinary_compartment_live_rate_ode_and_ssa(monkeypatch):
    """Ordinary case: single compartment with live rate law depending on observable.

    Analytic Oracle:
        For dA/dt = - (k_deg * A / V_cyt) * A = - c * A^2 with c = k_deg / V_cyt:
        A(t) = A_0 / (1 + c * A_0 * t)
        B(t) = A_0 - A(t)
    """
    source = """
begin model
begin parameters
    V_cyt 2.5
    k_deg 0.4
end parameters
begin compartments
    cyt 3 V_cyt
end compartments
begin molecule types
    A()
    B()
end molecule types
begin seed species
    @cyt:A() 100
    @cyt:B() 0
end seed species
begin observables
    Molecules A_cyt @cyt:A()
    Molecules B_cyt @cyt:B()
end observables
begin functions
    decay_rate() = k_deg * A_cyt / V_cyt
end functions
begin reaction rules
    @cyt:A() -> @cyt:B() decay_rate()
end reaction rules
end model
"""
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    doc = json.loads(source_model.to_bngir(version="0.2"))

    _assert_no_source_parsing(monkeypatch)
    restored = bionetgen.from_bngir(doc, native=True)

    # Document structure round-trip identity
    assert json.loads(restored.to_bngir(version="0.2")) == doc

    # ODE simulation vs analytic oracle
    res_ode = restored.simulate(method="ode", t_end=2.0, n_steps=10)
    c = 0.4 / 2.5  # 0.16
    a0 = 100.0
    for t, a_sim, b_sim in zip(
        res_ode.time, res_ode.observables["A_cyt"], res_ode.observables["B_cyt"]
    ):
        expected_a = a0 / (1.0 + c * a0 * t)
        expected_b = a0 - expected_a
        assert a_sim == pytest.approx(expected_a, rel=1e-4)
        assert b_sim == pytest.approx(expected_b, rel=1e-4)
        assert a_sim + b_sim == pytest.approx(a0, rel=1e-6)

    # SSA simulation: discrete conservation
    res_ssa = restored.simulate(method="ssa", t_end=2.0, n_steps=10, seed=42)
    for a_count, b_count in zip(
        res_ssa.observables["A_cyt"], res_ssa.observables["B_cyt"]
    ):
        assert a_count + b_count == int(a0)


def test_boundary_hierarchical_compartment_transport(monkeypatch):
    """Boundary case: 3D/2D/3D hierarchical compartments with inter-compartment transport.

    Analytic Oracle:
        dS_out/dt = - (k_trans / V_out) * S_out
        S_out(t) = S_0 * exp(- (k_trans / V_out) * t)
        S_in(t) = S_0 - S_out(t)
    """
    source = """
begin model
begin parameters
    V_out 10.0
    A_mem 2.0
    V_in 1.0
    k_trans 1.5
end parameters
begin compartments
    out 3 V_out
    mem 2 A_mem out
    in 3 V_in mem
end compartments
begin molecule types
    S()
end molecule types
begin seed species
    @out:S() 200
    @in:S() 0
end seed species
begin observables
    Molecules S_out @out:S()
    Molecules S_in @in:S()
end observables
begin functions
    trans_rate() = k_trans / V_out
end functions
begin reaction rules
    @out:S() -> @in:S() trans_rate()
end reaction rules
end model
"""
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    doc = json.loads(source_model.to_bngir(version="0.2"))

    _assert_no_source_parsing(monkeypatch)
    restored = bionetgen.from_bngir(doc, native=True)

    assert json.loads(restored.to_bngir(version="0.2")) == doc

    res = restored.simulate(method="ode", t_end=5.0, n_steps=10)
    rate_const = 1.5 / 10.0
    s0 = 200.0
    for t, s_out, s_in in zip(
        res.time, res.observables["S_out"], res.observables["S_in"]
    ):
        expected_out = s0 * math.exp(-rate_const * t)
        expected_in = s0 - expected_out
        assert s_out == pytest.approx(expected_out, rel=1e-4)
        assert s_in == pytest.approx(expected_in, rel=1e-4)


def test_interaction_cross_compartment_feedback_live_rate(monkeypatch):
    """Interaction case: non-linear feedback rate dependent on target compartment observable.

    Analytic Oracle:
        dS_ec/dt = - k_feed * S_ec / (Km + S_cyt)
        With S_cyt = S_0 - S_ec and C = Km + S_0:
        C * ln(S_ec(t) / S_0) - (S_ec(t) - S_0) = - k_feed * t
    """
    source = """
begin model
begin parameters
    V_ec 10.0
    V_cyt 2.0
    k_feed 2.0
    Km 10.0
end parameters
begin compartments
    ec 3 V_ec
    cyt 3 V_cyt
end compartments
begin molecule types
    S()
end molecule types
begin seed species
    @ec:S() 100
    @cyt:S() 0
end seed species
begin observables
    Molecules S_ec @ec:S()
    Molecules S_cyt @cyt:S()
end observables
begin functions
    feed_rate() = k_feed / (Km + S_cyt)
end functions
begin reaction rules
    trans: @ec:S() -> @cyt:S() feed_rate()
end reaction rules
end model
"""
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    doc = json.loads(source_model.to_bngir(version="0.2"))

    _assert_no_source_parsing(monkeypatch)
    restored = bionetgen.from_bngir(doc, native=True)

    res = restored.simulate(method="ode", t_end=5.0, n_steps=10)
    s0 = 100.0
    c_const = 10.0 + s0  # Km + S_0 = 110.0
    k_feed = 2.0

    for t, s_ec, s_cyt in zip(
        res.time, res.observables["S_ec"], res.observables["S_cyt"]
    ):
        assert s_ec + s_cyt == pytest.approx(s0, rel=1e-5)
        # Verify transcendental relation: C * ln(S_ec/S0) - (S_ec - S0) == -k_feed * t
        lhs = c_const * math.log(s_ec / s0) - (s_ec - s0)
        rhs = -k_feed * t
        assert lhs == pytest.approx(rhs, abs=1e-3)


def test_interaction_two_way_transport_steady_state(monkeypatch):
    """Interaction case: two-way transport across compartments relaxing to steady state.

    Analytic Oracle:
        k_fwd_eff = kf / V_out, k_rev_eff = kr / V_in
        lambda_rate = k_fwd_eff + k_rev_eff
        S_out_eq = S_0 * k_rev_eff / lambda_rate
        S_in_eq = S_0 * k_fwd_eff / lambda_rate
        S_out(t) = S_out_eq + (S_0 - S_out_eq) * exp(- lambda_rate * t)
    """
    source = """
begin model
begin parameters
    V_out 5.0
    V_in 2.0
    kf 1.0
    kr 0.5
end parameters
begin compartments
    out 3 V_out
    in 3 V_in
end compartments
begin molecule types
    S()
end molecule types
begin seed species
    @out:S() 140
    @in:S() 0
end seed species
begin observables
    Molecules S_out @out:S()
    Molecules S_in @in:S()
end observables
begin functions
    rate_fwd() = kf / V_out
    rate_rev() = kr / V_in
end functions
begin reaction rules
    trans_fwd: @out:S() -> @in:S() rate_fwd()
    trans_rev: @in:S() -> @out:S() rate_rev()
end reaction rules
end model
"""
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    doc = json.loads(source_model.to_bngir(version="0.2"))

    _assert_no_source_parsing(monkeypatch)
    restored = bionetgen.from_bngir(doc, native=True)

    kf_eff = 1.0 / 5.0  # 0.2
    kr_eff = 0.5 / 2.0  # 0.25
    lam = kf_eff + kr_eff  # 0.45
    s0 = 140.0
    s_out_eq = s0 * kr_eff / lam
    s_in_eq = s0 * kf_eff / lam

    res = restored.simulate(method="ode", t_end=10.0, n_steps=10)
    for t, s_out, s_in in zip(
        res.time, res.observables["S_out"], res.observables["S_in"]
    ):
        exp_out = s_out_eq + (s0 - s_out_eq) * math.exp(-lam * t)
        exp_in = s_in_eq * (1.0 - math.exp(-lam * t))
        assert s_out == pytest.approx(exp_out, rel=1e-4)
        assert s_in == pytest.approx(exp_in, rel=1e-4)
        assert s_out + s_in == pytest.approx(s0, rel=1e-6)


def test_compartment_volume_mutation_wire_preservation(monkeypatch):
    """Mutating compartment volume directly on the wire is preserved in restored model."""
    source = """
begin model
begin compartments
    cyt 3 2.0
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    @cyt:A() 50
end seed species
end model
"""
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    doc = json.loads(source_model.to_bngir(version="0.2"))

    doc["model"]["compartments"][0]["volume"] = 15.0

    _assert_no_source_parsing(monkeypatch)
    restored = bionetgen.from_bngir(doc, native=True)
    restored_doc = json.loads(restored.to_bngir(version="0.2"))

    assert restored_doc["model"]["compartments"][0]["volume"] == 15.0


@pytest.mark.parametrize(
    ("source", "expected_pattern"),
    [
        (
            """
begin model
begin compartments
    cyt 3 1.0
end compartments
begin molecule types
    A(s~u~p)
end molecule types
begin seed species
    @cyt:A(s~u) 10
end seed species
begin reaction rules
    @cyt:A(s~u) -> @cyt:A(s~p) 0.1
end reaction rules
end model
""",
            "state transitions do not support compartments",
        ),
        (
            """
begin model
begin compartments
    cyt 3 1.0
end compartments
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    @cyt:A(b) 10
    @cyt:B(a) 10
end seed species
begin reaction rules
    @cyt:A(b) + @cyt:B(a) -> @cyt:A(b!1).B(a!1) 0.1
end reaction rules
end model
""",
            "bond changes do not support compartments",
        ),
        (
            """
begin model
begin compartments
    cyt 3 1.0
end compartments
begin molecule types
    A()
    B()
end molecule types
begin seed species
    @cyt:A() 10
    @cyt:B() 0
end seed species
begin observables
    Molecules A_tot @cyt:A()
end observables
begin reaction rules
    @cyt:A() -> @cyt:B() A_tot
end reaction rules
end model
""",
            "outside the supported expression subset",
        ),
    ],
)
def test_unsupported_compartment_boundaries_fail_closed(
    source, expected_pattern, monkeypatch
):
    """Explicitly assert fail-closed rejection for out-of-scope compartment patterns."""
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    doc = json.loads(source_model.to_bngir(version="0.2"))

    _assert_no_source_parsing(monkeypatch)
    with pytest.raises(ValueError, match=expected_pattern):
        bionetgen.from_bngir(doc, native=True)
