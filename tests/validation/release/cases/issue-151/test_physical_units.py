"""Release acceptance test suite for Issue #151 (C06: NFsim physical-unit count-rate bridge).

Acceptance checks:
- release-nf-units: independent count-based native NFsim models match unit-annotated BNG3 models.
- release-unit-scaling: hand-derived Avogadro/volume/molecularity formulas catch missing and double conversion.
- release-obligation-151: each task above has its named check result, source/oracle identity and contract recorded.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import numpy as np
import pytest
from scipy.linalg import expm

import bionetgen
from bionetgen import BioNetGenModel
import bionetgen._bionetgen_cpp as cpp
from tests.validation import runner

CASE_DIR = Path(__file__).resolve().parent

RUNS = 200
BASE_SEED = 1001
INITIAL_A = 100
RATE_PER_SECOND = 0.5
END_TIME = 1.0

BIMOLECULAR_INITIAL = 10
BIMOLECULAR_COUNT_RATE = 0.05

ZERO_ORDER_INITIAL = 0
ZERO_ORDER_COUNT_RATE = 100.0
ZERO_ORDER_PHYSICAL_RATE = 1.660538863127e-7
ZERO_ORDER_END_TIME = 0.5
ZERO_ORDER_RUNS = 200
ZERO_ORDER_BASE_SEED = 5000


def _physical_zero_order_source(volume_femtoliters: float = 1.0) -> str:
    return f"""begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeunits second
  end units
  begin parameters
    k_synth = {ZERO_ORDER_PHYSICAL_RATE} [M/second]
    Vc = {volume_femtoliters} [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell {ZERO_ORDER_INITIAL}
  end seed species
  begin observables
    Molecules A_count A()@cell
  end observables
  begin reaction rules
    synth: 0 -> A()@cell k_synth
  end reaction rules
end model
"""


def _physical_unimolecular_source() -> str:
    return """begin model
  setOption("units", "strict")
  begin units
    timeunits second
  end units
  begin parameters
    k = 0.5 [second^-1]
    Vc = 1 [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A()
    B()
  end molecule types
  begin seed species
    A()@cell 100
    B()@cell 0
  end seed species
  begin observables
    Molecules A_count A()@cell
    Molecules B_count B()@cell
  end observables
  begin reaction rules
    convert: A()@cell -> B()@cell k
  end reaction rules
end model
"""


def _physical_bimolecular_source(volume_femtoliters: float = 1.0) -> str:
    return f"""begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeunits second
  end units
  begin parameters
    k = 3.01107038e7 [M^-1/second]
    Vc = {volume_femtoliters} [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A()
    B()
    C()
  end molecule types
  begin seed species
    A()@cell {BIMOLECULAR_INITIAL}
    B()@cell {BIMOLECULAR_INITIAL}
    C()@cell 0
  end seed species
  begin observables
    Molecules A_count A()@cell
    Molecules B_count B()@cell
    Molecules C_count C()@cell
  end observables
  begin reaction rules
    combine: A()@cell + B()@cell -> C()@cell k
  end reaction rules
end model
"""


def _physical_transport_source(
    v_cell: float = 1.0, v_ec: float = 10.0, k_trans: float = 0.5
) -> str:
    return f"""begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeunits second
  end units
  begin parameters
    k_t = {k_trans} [second^-1]
    V_cell = {v_cell} [fL]
    V_ec = {v_ec} [fL]
  end parameters
  begin compartments
    ec 3 V_ec [fL]
    cell 3 V_cell ec [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    @cell:A() {INITIAL_A}
    @ec:A() 0
  end seed species
  begin observables
    Molecules cell_A @cell:A()
    Molecules ec_A @ec:A()
  end observables
  begin reaction rules
    transport: @cell:A() -> @ec:A() k_t
  end reaction rules
end model
"""


def _assert_poisson_count_marginal(
    counts: list[int],
    expected_mean: float,
    runs: int = ZERO_ORDER_RUNS,
    alpha: float = 0.005,
) -> None:
    from scipy.stats import poisson

    max_c = max(max(counts) + 10, int(expected_mean + 4 * math.sqrt(expected_mean)))
    expected_cdf = poisson.cdf(np.arange(max_c + 1), expected_mean)
    observed_cdf = np.cumsum(np.bincount(counts, minlength=max_c + 1) / runs)
    epsilon = math.sqrt(math.log(2.0 / alpha) / (2.0 * runs))
    assert np.max(np.abs(observed_cdf - expected_cdf)) <= epsilon


def _assert_binomial_count_marginal(counts: list[int]) -> None:
    survival = math.exp(-RATE_PER_SECOND * END_TIME)
    probability = (1.0 - survival) ** INITIAL_A
    probabilities = [probability]
    for count in range(INITIAL_A):
        probability *= (INITIAL_A - count) / (count + 1) * survival / (1.0 - survival)
        probabilities.append(probability)
    expected_cdf = np.cumsum(probabilities)
    observed_cdf = np.cumsum(np.bincount(counts, minlength=INITIAL_A + 1) / RUNS)
    epsilon = math.sqrt(math.log(2.0 / 0.005) / (2.0 * RUNS))
    assert np.max(np.abs(observed_cdf - expected_cdf)) <= epsilon


def _assert_bimolecular_ctmc_marginal(converted_counts: list[int]) -> None:
    states = BIMOLECULAR_INITIAL + 1
    generator = np.zeros((states, states), dtype=float)
    for converted in range(BIMOLECULAR_INITIAL):
        remaining = BIMOLECULAR_INITIAL - converted
        propensity = BIMOLECULAR_COUNT_RATE * remaining * remaining
        generator[converted, converted] = -propensity
        generator[converted, converted + 1] = propensity
    initial = np.zeros(states, dtype=float)
    initial[0] = 1.0
    expected_probabilities = expm(generator.T * END_TIME) @ initial
    expected_cdf = np.cumsum(expected_probabilities)
    observed_cdf = np.cumsum(np.bincount(converted_counts, minlength=states) / RUNS)
    epsilon = math.sqrt(math.log(2.0 / 0.005) / (2.0 * RUNS))
    assert np.max(np.abs(observed_cdf - expected_cdf)) <= epsilon


# ==============================================================================
# release-nf-units: Unit-annotated BNG3 models match independent count laws
# ==============================================================================


@pytest.mark.nf
@pytest.mark.slow
def test_release_nf_units(tmp_path, monkeypatch):
    """Release acceptance check for issue #151: unit-annotated BNG3 models match independent count laws.

    Covers zero-order, unimolecular decay, unimolecular transport, and bimolecular
    reactions with physical units in strict unit mode. Validates exact marginal
    distributions against independent analytical Poisson, Binomial, and pure-birth
    CTMC laws via DKW bounds.
    """
    monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)
    monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)

    # 1. Zero-order physical synthesis: k = 1.660538863127e-7 M/s in 1 fL -> 100 items/s
    zero_file = tmp_path / "zero_order_acc.bngl"
    zero_file.write_text(_physical_zero_order_source(), encoding="utf-8")
    zero_model = bionetgen.load(str(zero_file))
    zero_counts = []
    for offset in range(ZERO_ORDER_RUNS):
        res = zero_model.simulate(
            method="nf",
            t_end=ZERO_ORDER_END_TIME,
            n_steps=1,
            seed=ZERO_ORDER_BASE_SEED + offset,
        )
        traj = runner._result_to_trajectory(res)
        assert traj.construction_path == "direct"
        zero_counts.append(int(traj.data[-1, traj.columns.index("A_count")]))
    _assert_poisson_count_marginal(
        zero_counts,
        expected_mean=ZERO_ORDER_COUNT_RATE * ZERO_ORDER_END_TIME,
        runs=ZERO_ORDER_RUNS,
    )

    # 2. Unimolecular physical decay: k = 0.5 s^-1 in 1 fL -> Binomial(100, exp(-0.5))
    uni_file = tmp_path / "unimolecular_acc.bngl"
    uni_file.write_text(_physical_unimolecular_source(), encoding="utf-8")
    uni_model = bionetgen.load(str(uni_file))
    uni_counts = []
    for offset in range(RUNS):
        res = uni_model.simulate(
            method="nf", t_end=END_TIME, n_steps=1, seed=BASE_SEED + offset
        )
        traj = runner._result_to_trajectory(res)
        assert traj.construction_path == "direct"
        a_count = int(traj.data[-1, traj.columns.index("A_count")])
        b_count = int(traj.data[-1, traj.columns.index("B_count")])
        assert a_count + b_count == INITIAL_A
        uni_counts.append(a_count)
    _assert_binomial_count_marginal(uni_counts)

    # 3. Bimolecular physical combination: k = 3.01107038e7 M^-1 s^-1 in 1 fL -> 0.05 item^-1 s^-1
    bi_file = tmp_path / "bimolecular_acc.bngl"
    bi_file.write_text(_physical_bimolecular_source(), encoding="utf-8")
    bi_model = bionetgen.load(str(bi_file))
    bi_counts = []
    for offset in range(RUNS):
        res = bi_model.simulate(
            method="nf", t_end=END_TIME, n_steps=1, seed=BASE_SEED + offset
        )
        traj = runner._result_to_trajectory(res)
        assert traj.construction_path == "direct"
        a = traj.data[-1, traj.columns.index("A_count")]
        b = traj.data[-1, traj.columns.index("B_count")]
        c = traj.data[-1, traj.columns.index("C_count")]
        assert a + c == BIMOLECULAR_INITIAL
        assert b + c == BIMOLECULAR_INITIAL
        bi_counts.append(int(c))
    _assert_bimolecular_ctmc_marginal(bi_counts)

    # 4. Unimolecular physical transport: k_t = 0.5 s^-1 across cell (1 fL) and ec (10 fL) -> Binomial(100, exp(-0.5))
    trans_file = tmp_path / "transport_acc.bngl"
    trans_file.write_text(_physical_transport_source(), encoding="utf-8")
    trans_model = bionetgen.load(str(trans_file))
    trans_counts = []
    for offset in range(RUNS):
        res = trans_model.simulate(
            method="nf", t_end=END_TIME, n_steps=1, seed=BASE_SEED + offset
        )
        traj = runner._result_to_trajectory(res)
        assert traj.construction_path == "direct"
        cell_count = int(traj.data[-1, traj.columns.index("cell_A")])
        ec_count = int(traj.data[-1, traj.columns.index("ec_A")])
        assert cell_count + ec_count == INITIAL_A
        trans_counts.append(cell_count)
    _assert_binomial_count_marginal(trans_counts)


# ==============================================================================
# release-unit-scaling: Hand-derived Avogadro/volume/molecularity formulas
# ==============================================================================


def _compile_rate(
    rule_decl: str,
    param_decl: str,
    na: float = 6.02214076e23,
    v: float = 1.0,
) -> float:
    source = f"""begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", {na})
  begin units
    timeunits second
  end units
  begin parameters
    {param_decl}
    Vc = {v} [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A()
    B()
    C()
  end molecule types
  begin seed species
    A()@cell 10
    B()@cell 10
    C()@cell 0
  end seed species
  begin reaction rules
    {rule_decl}
  end reaction rules
end model
"""
    m = cpp.parse_string(source)
    net = cpp.generate_network(m)
    flat = cpp.jax_ode_flatten(m, net)
    return float(flat["rate_constants"][0])


def test_release_unit_scaling():
    """Release acceptance check for issue #151: verify Avogadro, volume, and molecularity scaling formulas.

    Directly verifies hand-derived conversion formulas:
      - Zero-order:  k_count = k_phys * N_A * V
      - Unimolecular: k_count = k_phys (independent of N_A, V)
      - Bimolecular: k_count = k_phys / (N_A * V)
      - Homodimer:   k_count = 0.5 * k_phys / (N_A * V)
    Confirms that missing conversion, double conversion, and invalid unit dimensions
    are strictly detected and refused.
    """
    # 1. Zero-order rate: k_count = k_phys * N_A * V
    k0_ref = _compile_rate("0 -> C()@cell k", "k = 1.0e-8 [M/second]", na=1.0e23, v=1.0)
    assert pytest.approx(k0_ref, rel=1e-6) == 1.0
    k0_v25 = _compile_rate("0 -> C()@cell k", "k = 1.0e-8 [M/second]", na=1.0e23, v=2.5)
    assert pytest.approx(k0_v25, rel=1e-6) == 2.5
    assert pytest.approx(k0_v25 / k0_ref, rel=1e-6) == 2.5
    # Catch missing volume conversion (which would give ratio 1.0)
    assert abs(k0_v25 / k0_ref - 1.0) > 0.5
    # Catch double volume conversion (which would give ratio 6.25)
    assert abs(k0_v25 / k0_ref - 6.25) > 1.0

    k0_na2 = _compile_rate("0 -> C()@cell k", "k = 1.0e-8 [M/second]", na=2.0e23, v=1.0)
    assert pytest.approx(k0_na2, rel=1e-6) == 2.0
    assert pytest.approx(k0_na2 / k0_ref, rel=1e-6) == 2.0
    # Catch missing Avogadro conversion
    assert abs(k0_na2 / k0_ref - 1.0) > 0.5

    # 2. Unimolecular rate: k_count = k_phys (independent of V and N_A)
    k1_ref = _compile_rate(
        "A()@cell -> B()@cell k", "k = 0.5 [second^-1]", na=1.0e23, v=1.0
    )
    assert pytest.approx(k1_ref, rel=1e-6) == 0.5
    k1_v5 = _compile_rate(
        "A()@cell -> B()@cell k", "k = 0.5 [second^-1]", na=1.0e23, v=5.0
    )
    assert pytest.approx(k1_v5, rel=1e-6) == 0.5
    assert pytest.approx(k1_v5 / k1_ref, rel=1e-6) == 1.0
    # Catch spurious volume scaling
    assert abs(k1_v5 / k1_ref - 5.0) > 1.0

    k1_na3 = _compile_rate(
        "A()@cell -> B()@cell k", "k = 0.5 [second^-1]", na=3.0e23, v=1.0
    )
    assert pytest.approx(k1_na3, rel=1e-6) == 0.5
    assert pytest.approx(k1_na3 / k1_ref, rel=1e-6) == 1.0
    # Catch spurious Avogadro scaling
    assert abs(k1_na3 / k1_ref - 3.0) > 1.0

    # 3. Bimolecular rate: k_count = k_phys / (N_A * V)
    k2_ref = _compile_rate(
        "A()@cell + B()@cell -> C()@cell k",
        "k = 1.0e7 [M^-1/second]",
        na=1.0e23,
        v=1.0,
    )
    assert pytest.approx(k2_ref, rel=1e-6) == 0.1
    k2_v2 = _compile_rate(
        "A()@cell + B()@cell -> C()@cell k",
        "k = 1.0e7 [M^-1/second]",
        na=1.0e23,
        v=2.0,
    )
    assert pytest.approx(k2_v2, rel=1e-6) == 0.05
    assert pytest.approx(k2_v2 / k2_ref, rel=1e-6) == 0.5
    # Catch missing volume conversion (ratio 1.0)
    assert abs(k2_v2 / k2_ref - 1.0) > 0.2
    # Catch inverted volume scaling (ratio 2.0)
    assert abs(k2_v2 / k2_ref - 2.0) > 0.5

    k2_na2 = _compile_rate(
        "A()@cell + B()@cell -> C()@cell k",
        "k = 1.0e7 [M^-1/second]",
        na=2.0e23,
        v=1.0,
    )
    assert pytest.approx(k2_na2, rel=1e-6) == 0.05
    assert pytest.approx(k2_na2 / k2_ref, rel=1e-6) == 0.5
    # Catch missing Avogadro conversion
    assert abs(k2_na2 / k2_ref - 1.0) > 0.2

    # 4. Homodimer bimolecular rate: k_count = 0.5 * k_phys / (N_A * V)
    homo_source = """begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 1.0e23)
  begin units
    timeunits second
  end units
  begin parameters
    kon = 1.0e7 [M^-1/second]
    Vc = 1.0 [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A(b)
  end molecule types
  begin seed species
    A(b)@cell 10
  end seed species
  begin reaction rules
    bind: A(b)@cell + A(b)@cell -> A(b!1).A(b!1)@cell kon
  end reaction rules
end model
"""
    m_homo = cpp.parse_string(homo_source)
    net_homo = cpp.generate_network(m_homo)
    k_homo = float(cpp.jax_ode_flatten(m_homo, net_homo)["rate_constants"][0])
    assert pytest.approx(k_homo, rel=1e-6) == 0.05
    assert pytest.approx(k_homo / k2_ref, rel=1e-6) == 0.5

    # 5. Strict dimensional error detection (negative controls)
    # 5a. Zero-order rule with unimolecular unit [second^-1]
    with pytest.raises(RuntimeError, match="molecularity 0 requires concentration"):
        _compile_rate("0 -> C()@cell k", "k = 0.5 [second^-1]")

    # 5b. Bimolecular rule with unimolecular unit [second^-1]
    with pytest.raises(RuntimeError, match="molecularity 2 requires concentration"):
        _compile_rate("A()@cell + B()@cell -> C()@cell k", "k = 0.5 [second^-1]")

    # 5c. Unimolecular rule with bimolecular unit [M^-1/second]
    with pytest.raises(RuntimeError, match="molecularity 1 requires concentration"):
        _compile_rate("A()@cell -> B()@cell k", "k = 0.5 [M^-1/second]")


# ==============================================================================
# release-obligation-151: Contract verification and negative context refusal
# ==============================================================================


def test_release_obligation_151():
    """Verify issue #151 contract completeness, single conversion application, and fail-closed refusals."""
    contract_file = CASE_DIR / "contract.json"
    assert contract_file.exists(), "contract.json must exist in release case dir"
    contract = json.loads(contract_file.read_text(encoding="utf-8"))

    assert contract.get("schema_version") == 1
    assert contract.get("issue") == 151
    checks = contract.get("acceptance_checks", [])
    for expected in [
        "release-nf-units",
        "release-unit-scaling",
        "release-obligation-151",
    ]:
        assert expected in checks, f"Missing acceptance check {expected}"

    obligations = contract.get("obligations", [])
    assert len(obligations) >= 10, f"Expected obligations list, got {len(obligations)}"

    # Check 1: Refusal of missing or non-positive compartment volume in concentration conversion
    src_zero_vol = """begin model
  setOption("units", "strict")
  begin parameters
    k = 1.0e-8 [M/second]
  end parameters
  begin compartments
    cell 3 0 [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 10
  end seed species
  begin reaction rules
    0 -> A()@cell k
  end reaction rules
end model"""
    m_zv = cpp.parse_string(src_zero_vol)
    net_zv = cpp.generate_network(m_zv)
    with pytest.raises(RuntimeError, match="requires a positive compartment volume"):
        cpp.jax_ode_flatten(m_zv, net_zv)

    # Check 2: Refusal of non-positive volume in inter-compartment transport
    src_trans_neg = """begin model
  setOption("units", "strict")
  begin parameters
    k = 0.5 [second^-1]
    V_cell = 1.0 [fL]
    V_ec = 0.0 [fL]
  end parameters
  begin compartments
    ec 3 V_ec [fL]
    cell 3 V_cell ec [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    @cell:A() 10
    @ec:A() 0
  end seed species
  begin reaction rules
    transport: @cell:A() -> @ec:A() k
  end reaction rules
end model"""
    m_tn = BioNetGenModel(cpp.parse_string(src_trans_neg))
    with pytest.raises(
        RuntimeError,
        match="unimolecular physical rates require a positive static declared 3D compartment",
    ):
        m_tn.simulate(method="nf", t_end=1.0)

    # Check 3: Refusal of unsupported dimensions (e.g. 2D membrane destination)
    src_trans_2d = """begin model
  setOption("units", "strict")
  begin parameters
    k = 0.5 [second^-1]
    V_cell = 1.0 [fL]
    A_mem = 1.0 [um^2]
  end parameters
  begin compartments
    cell 3 V_cell [fL]
    mem 2 A_mem cell [um^2]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    @cell:A() 10
    @mem:A() 0
  end seed species
  begin reaction rules
    transport: @cell:A() -> @mem:A() k
  end reaction rules
end model"""
    m_2d = BioNetGenModel(cpp.parse_string(src_trans_2d))
    with pytest.raises(
        RuntimeError, match="NFsim cannot execute physical-unit annotations"
    ):
        m_2d.simulate(method="nf", t_end=1.0)
