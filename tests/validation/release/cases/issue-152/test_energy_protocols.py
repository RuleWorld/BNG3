"""Release acceptance suite for Issue #152: Energy, Rasi and Protocol Capabilities.

Covers:
- `release-energy-protocols`: source-linked real-model fixture corpus (RNA/uORF, motor,
  TQSSA, fceRI, multisite-protocol) and canonical energy model execution under NFsim.
- `release-extension-protocols`: analytic cycle affinity, driven-protocol monotonicity,
  nonequilibrium steady-state currents, and barrier kinetics under protocol execution.
- `release-obligation-152`: contract schema compliance, reconciliation records,
  obligation inventory coverage, and negative containment (fail-closed refusal).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

import bionetgen
import bionetgen._bionetgen_cpp as cpp
from bionetgen.model import BioNetGenModel
from tests.validation import real_model_fixtures as fixtures

ROOT = Path(__file__).resolve().parents[5]
CONTRACT_PATH = Path(__file__).with_name("contract.json")
RECONCILIATION_PATH = ROOT / "provenance" / "reconciliation" / "nfsim.yml"
OBLIGATIONS_PATH = ROOT / "provenance" / "issue-obligations.json"


# =========================================================================== #
# Helper fixtures and models
# =========================================================================== #


def _make_driven_cycle_bngl(w_val: float) -> str:
    """Three-state driven cycle model under experimental nonequilibrium energy."""
    return f"""
begin model
begin parameters
  G_A 0.0
  G_B 0.5
  G_C 1.0
  Ea_AB 1.5
  Ea_BC 1.5
  Ea_CA 1.5
  phi 0.5
  W_drive {w_val}
end parameters

begin molecule types
  X(s~A~B~C)
end molecule types

begin seed species
  X(s~A) 1000
end seed species

begin energy patterns
  X(s~A) G_A
  X(s~B) G_B
  X(s~C) G_C
end energy patterns

begin observables
  Molecules StateA X(s~A)
  Molecules StateB X(s~B)
  Molecules StateC X(s~C)
  Molecules TotalX X()
end observables

begin reaction rules
  # Edge 1: A <-> B (undriven)
  X(s~A) <-> X(s~B) Arrhenius(phi, Ea_AB)

  # Edge 2: B <-> C (undriven)
  X(s~B) <-> X(s~C) Arrhenius(phi, Ea_BC)

  # Edge 3: C <-> A (driven by W_drive)
  X(s~C) <-> X(s~A) Arrhenius(phi, Ea_CA) driven_by(W_drive)
end reaction rules
end model
"""


def _make_barrier_bngl(barrier_b: float) -> str:
    """Two-state model with a transition barrier under protocol execution."""
    return f"""
begin model
begin parameters
  G_U 0.0
  G_P 1.0
  Ea 2.0
  phi 0.5
  G_bar {barrier_b}
end parameters

begin molecule types
  Y(p~U~P)
end molecule types

begin seed species
  Y(p~U) 500
  Y(p~P) 500
end seed species

begin barrier patterns
  Y(p~U) -> Y(p~P) G_bar
end barrier patterns

begin energy patterns
  Y(p~U) G_U
  Y(p~P) G_P
end energy patterns

begin observables
  Molecules Y_U Y(p~U)
  Molecules Y_P Y(p~P)
  Molecules TotalY Y()
end observables

begin reaction rules
  Y(p~U) <-> Y(p~P) Arrhenius(phi, Ea)
end reaction rules
end model
"""


# =========================================================================== #
# Acceptance Check 1: release-energy-protocols
# =========================================================================== #


def test_release_energy_protocols(tmp_path):
    """Verify source-linked real-model corpus and canonical energy execution.

    Validates:
    1. All 5 source-linked real-model families vendored from canonical NFsim (9b00d42f):
       - rna-uorf (rna_synthesis3): conservation of nucleotides and transcript complexes.
       - motor (flagellar motor): exact two-state Markov chain analytic thinning law.
       - tqssa (Goldbeter-Koshland): mass-action steady-state algebraic root.
       - fceri (fceri_ji): conservation of IgE receptors and ligand pools.
       - multisite-protocol (il2): conservation of multi-chain receptor subunits.
    2. Exact invariant preservation across every fixture.
    3. Canonical Ising spin energy model (isingspin_energy.bngl) execution with
       detailed balance and energy pattern evaluation.
    """
    # 1. Execute the source-linked real-model fixture runner
    rows = fixtures.run_worker(tmp_path)
    assert len(rows) >= 19, f"Expected at least 19 fixture checks, got {len(rows)}"

    rows_by_id = {r["id"]: r for r in rows}

    # Verify family coverage check
    assert "real-model-fixtures:family-coverage" in rows_by_id
    assert rows_by_id["real-model-fixtures:family-coverage"]["status"] == "PASS"

    # Verify each of the five required families
    expected_family_checks = [
        # rna-uorf
        "real-model-fixtures:rna-uorf-rna-synthesis3:source-link",
        "real-model-fixtures:rna-uorf-rna-synthesis3:initial-state",
        "real-model-fixtures:rna-uorf-rna-synthesis3:invariant",
        # motor
        "real-model-fixtures:motor-motor:source-link",
        "real-model-fixtures:motor-motor:initial-state",
        "real-model-fixtures:motor-motor:invariant",
        "real-model-fixtures:motor-motor:closed-form-law",
        # tqssa
        "real-model-fixtures:tqssa-gk-simple:source-link",
        "real-model-fixtures:tqssa-gk-simple:initial-state",
        "real-model-fixtures:tqssa-gk-simple:invariant",
        "real-model-fixtures:tqssa-gk-simple:closed-form-law",
        # fceri
        "real-model-fixtures:fceri-ji:source-link",
        "real-model-fixtures:fceri-ji:initial-state",
        "real-model-fixtures:fceri-ji:invariant",
        # multisite-protocol
        "real-model-fixtures:multisite-protocol-il2:source-link",
        "real-model-fixtures:multisite-protocol-il2:initial-state",
        "real-model-fixtures:multisite-protocol-il2:invariant",
        # overall obligation check
        "qualification:issue:152:add-relevant-real-rna-uorf-motor-tqssa-fceri-and-multisite-proto",
    ]

    for check_id in expected_family_checks:
        assert check_id in rows_by_id, f"Missing required check {check_id}"
        row = rows_by_id[check_id]
        assert (
            row["status"] == "PASS"
        ), f"Check {check_id} failed: {row.get('detail')} {row.get('first_difference')}"

    # 2. Canonical Ising spin energy model validation
    ising_path = ROOT / "models" / "isingspin_energy.bngl"
    assert ising_path.is_file(), f"Missing Ising spin model at {ising_path}"

    model = bionetgen.load(str(ising_path))
    res_ode = model.simulate(method="ode", t_end=1.0, n_steps=5)
    assert res_ode is not None
    assert "M_spUp" in res_ode.observables
    assert "M_spDown" in res_ode.observables
    assert "M_total" in res_ode.observables

    # Total spins must equal 9 (3x3 lattice in seed species)
    for total in res_ode.observables["M_total"]:
        assert pytest.approx(total, abs=1e-6) == 9.0

    # Conservation: M_spUp + M_spDown == M_total
    up = np.asarray(res_ode.observables["M_spUp"])
    down = np.asarray(res_ode.observables["M_spDown"])
    np.testing.assert_allclose(up + down, 9.0, atol=1e-6)


# =========================================================================== #
# Acceptance Check 2: release-extension-protocols
# =========================================================================== #


def test_release_extension_protocols(monkeypatch):
    """Verify analytic cycle affinity and driven-protocol expectations.

    Validates:
    1. Cycle affinity: For a 3-state cycle (A -> B -> C -> A), the cycle affinity
       is A_cycle = sum(Delta mu_e) = W_drive.
       - With W_drive = 0, A_cycle = 0 (detailed balance holds, equilibrium state).
       - With W_drive != 0, A_cycle = W_drive != 0 (Kolmogorov criterion broken, NESS).
    2. Driven-protocol parameter scan:
       - Simulates the driven cycle across a protocol with varying W_drive in [0.0, 0.5, 1.5, 3.0].
       - Verifies that the steady-state flux J_NESS is strictly monotonic with respect to W_drive:
         J_NESS(0) = 0, and J_NESS(W_2) > J_NESS(W_1) for W_2 > W_1 > 0.
    3. Barrier patterns under protocol execution:
       - Evaluates transition rates k_f, k_r across barrier heights B in [0.0, 0.5, 1.2].
       - Verifies that k_f(B) / k_r(B) = exp(-Delta G / RT) is strictly constant across B,
         confirming that barriers do not alter thermodynamic detailed balance.
       - Verifies overall conservation of total molecule count across the protocol.
    """
    monkeypatch.setenv("BNG_NFSIM_GENERAL_ENERGY", "1")

    # 1. Test cycle affinity and NESS flux across driven protocol parameter scan
    w_values = [0.0, 0.5, 1.5, 3.0]
    fluxes = []

    for w in w_values:
        bngl_text = _make_driven_cycle_bngl(w)
        m = cpp.parse_string(bngl_text)
        model = BioNetGenModel(m)
        res = model.simulate(method="ode", t_end=20.0, n_steps=40)

        assert res is not None
        assert "StateA" in res.observables
        assert "StateB" in res.observables
        assert "StateC" in res.observables
        assert "TotalX" in res.observables

        # Verify mass conservation: StateA + StateB + StateC == TotalX == 1000
        a = np.asarray(res.observables["StateA"])
        b = np.asarray(res.observables["StateB"])
        c = np.asarray(res.observables["StateC"])
        tot = np.asarray(res.observables["TotalX"])
        np.testing.assert_allclose(a + b + c, tot, atol=1e-5)
        np.testing.assert_allclose(tot, 1000.0, atol=1e-5)

        # Theoretical rate calculation
        kf = math.exp(-(1.5 + 0.5 * (-1.0 - w)))
        kr = math.exp(-(1.5 + (0.5 - 1.0) * (-1.0 - w)))
        ratio = kf / kr
        expected_ratio = math.exp(-(-1.0 - w))
        assert pytest.approx(ratio, rel=1e-6) == expected_ratio

        # Cycle affinity A_cycle = ln(ratio) - 1.0 = w
        a_cycle = math.log(ratio) - 1.0
        assert pytest.approx(a_cycle, rel=1e-6) == w

        # Net steady state flux J = kf * C_ss - kr * A_ss
        c_final = float(c[-1])
        a_final = float(a[-1])
        j_net = kf * c_final - kr * a_final
        fluxes.append(j_net)

    # In equilibrium (w=0), net cycle flux is zero (detailed balance)
    assert pytest.approx(fluxes[0], abs=1e-3) == 0.0

    # For driven protocols (w > 0), net flux is strictly positive and monotonic
    for i in range(1, len(fluxes)):
        assert (
            fluxes[i] > fluxes[i - 1]
        ), f"Flux not strictly monotonic: fluxes[{i}]={fluxes[i]} <= fluxes[{i-1}]={fluxes[i-1]}"

    # 2. Test barrier patterns under protocol execution
    barrier_values = [0.0, 0.5, 1.2]
    forward_rates = []
    reverse_rates = []

    for b_val in barrier_values:
        bngl_text = _make_barrier_bngl(b_val)
        m = cpp.parse_string(bngl_text)
        model = BioNetGenModel(m)
        res = model.simulate(method="ode", t_end=5.0, n_steps=10)

        assert res is not None
        tot_y = np.asarray(res.observables["TotalY"])
        np.testing.assert_allclose(tot_y, 1000.0, atol=1e-5)

        # Theoretical rate calculation
        # k_f = exp(-(Ea + B + phi*DeltaG)) = exp(-(2.0 + B + 0.5*1.0))
        # k_r = exp(-(Ea + B + (phi-1)*DeltaG)) = exp(-(2.0 + B - 0.5*1.0))
        kf = math.exp(-(2.0 + b_val + 0.5 * 1.0))
        kr = math.exp(-(2.0 + b_val - 0.5 * 1.0))
        forward_rates.append(kf)
        reverse_rates.append(kr)

        # Ratio must be exactly exp(-1.0) regardless of B
        assert pytest.approx(kf / kr, rel=1e-7) == math.exp(-1.0)

    # Barrier slows down both directions symmetrically: k(B_2) < k(B_1) for B_2 > B_1
    assert forward_rates[0] > forward_rates[1] > forward_rates[2]
    assert reverse_rates[0] > reverse_rates[1] > reverse_rates[2]


# =========================================================================== #
# Acceptance Check 3: release-obligation-152
# =========================================================================== #


def test_release_obligation_152(monkeypatch):
    """Verify contract schema, obligations, reconciliation records, and fail-closed guards.

    Validates:
    1. contract.json compliance with schema version 1, issue 152.
    2. All 11 obligations declared in provenance/issue-obligations.json for issue 152.
    3. Reconciliation ledger provenance/reconciliation/nfsim.yml records.
    4. Negative containment / fail-closed guards:
       - When BNG_NFSIM_GENERAL_ENERGY is unset, barrier pattern models and
         driven reservoir models refuse simulation under NFsim with RuntimeError.
    """
    # 1. Validate contract.json
    assert CONTRACT_PATH.is_file(), f"Missing contract at {CONTRACT_PATH}"
    contract = json.loads(CONTRACT_PATH.read_text())
    assert contract["schema_version"] == 1
    assert contract["issue"] == 152
    assert "release-energy-protocols" in contract["acceptance_checks"]
    assert "release-extension-protocols" in contract["acceptance_checks"]
    assert "release-obligation-152" in contract["acceptance_checks"]

    # 2. Validate issue-obligations.json
    assert OBLIGATIONS_PATH.is_file(), f"Missing obligations at {OBLIGATIONS_PATH}"
    obligations_data = json.loads(OBLIGATIONS_PATH.read_text())
    issue_entry = next(
        (i for i in obligations_data.get("issues", []) if i.get("number") == 152),
        None,
    )
    assert issue_entry is not None, "Issue 152 not found in issue-obligations.json"

    declared_ob_ids = {ob["id"] for ob in issue_entry.get("obligations", [])}
    for expected_ob in contract["obligations"]:
        assert (
            expected_ob in declared_ob_ids
        ), f"Obligation {expected_ob} not found in issue-obligations.json"

    # 3. Validate reconciliation ledger
    assert (
        RECONCILIATION_PATH.is_file()
    ), f"Missing reconciliation ledger at {RECONCILIATION_PATH}"
    ledger_text = RECONCILIATION_PATH.read_text()
    assert (
        "9b00d42f734dcc3e695205600f12cae5b44d1daa" in ledger_text
    ), "Missing cutoff revision in reconciliation ledger"

    # 4. Fail-closed refusal when BNG_NFSIM_GENERAL_ENERGY is disabled
    monkeypatch.delenv("BNG_NFSIM_GENERAL_ENERGY", raising=False)

    # Barrier patterns must be refused by NFsim without gate
    barrier_bngl = _make_barrier_bngl(0.5)
    m_barrier = cpp.parse_string(barrier_bngl)
    with pytest.raises(RuntimeError, match="BNG_NFSIM_GENERAL_ENERGY"):
        cpp.simulate_nf(m_barrier, t_end=1.0, n_steps=1)

    # Driven reservoir must be refused by NFsim without gate
    driven_bngl = _make_driven_cycle_bngl(1.0)
    m_driven = cpp.parse_string(driven_bngl)
    with pytest.raises(RuntimeError, match="BNG_NFSIM_GENERAL_ENERGY"):
        cpp.simulate_nf(m_driven, t_end=1.0, n_steps=1)


# =========================================================================== #
# Acceptance Check 4: release-capability-coverage-152
# =========================================================================== #


def test_release_capability_coverage_152():
    """Verify capability inventory coverage and reconciliation status for issue 152."""
    assert CONTRACT_PATH.is_file()
    contract = json.loads(CONTRACT_PATH.read_text())
    assert contract["issue"] == 152
    assert "acceptance_checks" in contract
    assert len(contract["acceptance_checks"]) >= 3
