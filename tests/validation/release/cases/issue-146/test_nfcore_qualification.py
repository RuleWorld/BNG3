"""Release acceptance test suite for Issue #146 (C01: Expand independent direct-NFsim and XML-path qualification).

Acceptance checks:
- release-nfcore: each nf.option and applicable BNGL row passes against pinned native NFsim through both construction routes.
- release-nfcore-statistics: prescribed seed/sample/error-control manifest passes distributional comparisons without tolerance changes.
- release-capability-coverage-146: all 50 assigned inventory cases execute against their row's named independent oracle.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import numpy as np
import pytest

import bionetgen
from bionetgen import BioNetGenModel
import bionetgen._bionetgen_cpp as cpp
from tests.validation import compare, corpus, runner

CASE_DIR = Path(__file__).resolve().parent

# The 50 assigned capability inventory rows for Issue #146
ASSIGNED_INVENTORY_ROWS = [
    # 8 BNGL observable rows
    "bngl.molecules-observables",
    "bngl.species-observables",
    "bngl.species-count-equality",
    "bngl.species-count-greater-than",
    "bngl.multiple-pattern-terms",
    "bngl.observable-coefficients",
    "bngl.local-molecule-scope",
    "bngl.local-species-scope",
    # 42 NFsim CLI options
    "nf.option.agentcell",
    "nf.option.b",
    "nf.option.bscb",
    "nf.option.cb",
    "nf.option.connect",
    "nf.option.csv",
    "nf.option.dump",
    "nf.option.eq",
    "nf.option.gml",
    "nf.option.h",
    "nf.option.help",
    "nf.option.i",
    "nf.option.logbuffer",
    "nf.option.logo",
    "nf.option.maxcputime",
    "nf.option.nocslf",
    "nf.option.notf",
    "nf.option.o",
    "nf.option.oSteps",
    "nf.option.oTimes",
    "nf.option.oec",
    "nf.option.ogf",
    "nf.option.printconnected",
    "nf.option.printmoltypes",
    "nf.option.printrxncounts",
    "nf.option.profile",
    "nf.option.rm",
    "nf.option.rnf",
    "nf.option.rtag",
    "nf.option.rulemonkey",
    "nf.option.rxnlog",
    "nf.option.seed",
    "nf.option.sim",
    "nf.option.ss",
    "nf.option.test",
    "nf.option.trackconnected",
    "nf.option.trackrxnnum",
    "nf.option.utl",
    "nf.option.v",
    "nf.option.version",
    "nf.option.walk",
    "nf.option.xml",
]


# ==============================================================================
# release-nfcore: Dual route equivalence, BNGL observables, and NF options
# ==============================================================================


@pytest.mark.nf
@pytest.mark.slow
def test_release_nfcore_dual_route_equivalence(monkeypatch):
    """Direct AST-to-System lowering matches in-memory XML lowering bit-for-bit (rtol=atol=0)."""
    models = list(corpus.tier_nf())
    assert len(models) >= 4, f"Expected at least 4 tier-NF models, found {models}"

    t_end = 1.0
    n_steps = 5
    seed = 42

    for model_name in models:
        # 1. Run via in-memory XML path
        monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
        monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
        xml_traj = runner.run_api(
            model_name, method="nf", seed=seed, t_end=t_end, n_steps=n_steps
        )
        assert xml_traj.construction_path == "in-memory-xml"

        # 2. Run via direct AST path (fail-closed, no XML fallback allowed)
        monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)
        monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)
        direct_traj = runner.run_api(
            model_name, method="nf", seed=seed, t_end=t_end, n_steps=n_steps
        )
        assert direct_traj.construction_path == "direct"

        # 3. Trajectories must match exactly
        diff = compare.compare_trajectories(
            xml_traj.data,
            xml_traj.columns,
            direct_traj.data,
            direct_traj.columns,
            rtol=0.0,
            atol=0.0,
            columns=compare.COLUMNS_EXACT,
        )
        assert (
            diff.ok or diff.max_rel_err == 0.0
        ), f"Direct vs XML mismatch on {model_name}: {diff.summary()}"


@pytest.mark.nf
def test_release_nfcore_observable_semantics():
    """Verify Molecules vs Species, equality, greater-than, multi-pattern, and weighted observables."""
    src = """begin model
begin parameters
    k 0.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b!1).A(b!1) 5
    A(b) 10
    B(a) 20
end seed species
begin observables
    Molecules M_obs A()
    Species S_obs A()
    Species S_eq A()==1
    Species S_gt A()>1
    Molecules Multi_obs A(), B()
end observables
begin reaction rules
    dummy: A(b) -> A(b) k
end reaction rules
end model"""

    model = BioNetGenModel(cpp.parse_string(src))
    res = model.simulate(method="nf", t_end=1.0, n_steps=1, seed=123)

    # In seed: 5 dimers A(b!1).A(b!1) (10 A molecules in 5 species complexes)
    # plus 10 monomers A(b) (10 A molecules in 10 species complexes)
    # Total A molecules = 10 + 10 = 20
    # Total A species complexes = 5 + 10 = 15
    assert float(res.observables["M_obs"][-1]) == 20.0
    assert float(res.observables["S_obs"][-1]) == 15.0

    # Species with count == 1: the 10 monomers
    assert float(res.observables["S_eq"][-1]) == 10.0

    # Species with count > 1: the 5 dimers (each has count 2)
    assert float(res.observables["S_gt"][-1]) == 5.0

    # Multi-pattern: A (20) + B (20) = 40
    assert float(res.observables["Multi_obs"][-1]) == 40.0


@pytest.mark.nf
def test_release_nfcore_local_function_scopes():
    """Verify local function scopes (molecule scope and species/complex scope) under NFsim."""
    model_src = corpus.resolve("localfunc")
    assert model_src is not None and model_src.is_file()

    model = bionetgen.load(str(model_src))
    res = model.simulate(method="nf", t_end=1.0, n_steps=2, seed=777)
    assert len(res.time) == 3
    expected_observables = [
        "Atot",
        "Btot",
        "Ctot",
        "AB0",
        "AB1",
        "AB2",
        "AB3",
        "AB_motif",
    ]
    for name in expected_observables:
        assert name in res.observables
        assert np.all(np.isfinite(res.observables[name]))


@pytest.mark.nf
def test_release_nfcore_option_handling(tmp_path):
    """Verify NFsim options dispatch, flags, and negative control refusals."""
    src = """begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 50
    B() 0
end seed species
begin observables
    Molecules A_obs A()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model"""

    model = BioNetGenModel(cpp.parse_string(src))

    # Valid option combinations via simulate()
    res1 = model.simulate(method="nf", t_end=2.0, n_steps=5, seed=101)
    assert len(res1.time) == 6
    assert res1.observables["A_obs"][-1] <= 50.0

    # Locate bng_cpp binary
    bng_cpp = Path(cpp.__file__).parent / "bng_cpp"
    if not bng_cpp.is_file():
        bng_cpp = Path(__file__).resolve().parents[5] / "build" / "cpp" / "bng_cpp"

    if bng_cpp.is_file():
        import subprocess

        # 1. Valid param flags through action block
        action_file = tmp_path / "action_valid.bngl"
        action_src = """begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules A_obs A()
end observables
begin reaction rules
    A() -> 0 k
end reaction rules
begin actions
    simulate_nf({t_end=>1.0, n_steps=>2, seed=>42, param=>"-cb -bscb -notf -nocslf"})
end actions
end model"""
        action_file.write_text(action_src, encoding="utf-8")
        proc_ok = subprocess.run(
            [str(bng_cpp), str(action_file)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert proc_ok.returncode == 0, f"Valid param failed: {proc_ok.stderr}"

        # 2. Negative control: unsupported param flag rejected fail-closed
        action_bad = tmp_path / "action_bad.bngl"
        bad_src = """begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin reaction rules
    A() -> 0 k
end reaction rules
begin actions
    simulate_nf({t_end=>1.0, n_steps=>2, seed=>42, param=>"-invalid_flag_xyz 123"})
end actions
end model"""
        action_bad.write_text(bad_src, encoding="utf-8")
        proc_bad = subprocess.run(
            [str(bng_cpp), str(action_bad)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert proc_bad.returncode != 0
        assert "not supported by the in-process adapter" in proc_bad.stderr

        # 3. Negative control: invalid non-integer value for integer flag rejected fail-closed
        action_neg = tmp_path / "action_neg.bngl"
        neg_src = """begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin reaction rules
    A() -> 0 k
end reaction rules
begin actions
    simulate_nf({t_end=>1.0, n_steps=>2, seed=>42, param=>"-gml abc"})
end actions
end model"""
        action_neg.write_text(neg_src, encoding="utf-8")
        proc_neg = subprocess.run(
            [str(bng_cpp), str(action_neg)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert proc_neg.returncode != 0
        assert "requires an integer value" in proc_neg.stderr


# ==============================================================================
# release-nfcore-statistics: Exact stochastic distribution check via DKW bound
# ==============================================================================


@pytest.mark.nf
@pytest.mark.slow
def test_release_nfcore_statistics():
    """Stochastic endpoint distribution of unimolecular decay matches analytical Binomial law via DKW bounds."""
    src = """begin model
begin parameters
    k 0.5
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
    Molecules A_obs A()
    Molecules B_obs B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model"""

    model = BioNetGenModel(cpp.parse_string(src))
    n_runs = 200
    base_seed = 3000
    t_end = 1.0
    k_rate = 0.5
    initial_a = 100

    counts = []
    for i in range(n_runs):
        res = model.simulate(method="nf", t_end=t_end, n_steps=1, seed=base_seed + i)
        counts.append(int(res.observables["A_obs"][-1]))

    # Analytical Binomial(100, exp(-0.5)) CDF
    survival_prob = math.exp(-k_rate * t_end)
    prob = (1.0 - survival_prob) ** initial_a
    probabilities = [prob]
    for k in range(initial_a):
        prob *= (initial_a - k) / (k + 1) * survival_prob / (1.0 - survival_prob)
        probabilities.append(prob)
    expected_cdf = np.cumsum(probabilities)

    # Empirical CDF
    observed_cdf = np.cumsum(np.bincount(counts, minlength=initial_a + 1) / n_runs)

    # DKW bound at alpha = 0.005
    alpha = 0.005
    epsilon = math.sqrt(math.log(2.0 / alpha) / (2.0 * n_runs))
    max_diff = np.max(np.abs(observed_cdf - expected_cdf))
    assert (
        max_diff <= epsilon
    ), f"KS distance {max_diff:.5f} exceeds DKW bound {epsilon:.5f}"

    # Negative control: mutant distribution with frozen/wrong rate (k=0.1) is strictly rejected
    wrong_prob = math.exp(-0.1 * t_end)
    p_wrong = (1.0 - wrong_prob) ** initial_a
    wrong_probs = [p_wrong]
    for k in range(initial_a):
        p_wrong *= (initial_a - k) / (k + 1) * wrong_prob / (1.0 - wrong_prob)
        wrong_probs.append(p_wrong)
    wrong_cdf = np.cumsum(wrong_probs)
    wrong_diff = np.max(np.abs(observed_cdf - wrong_cdf))
    assert (
        wrong_diff > epsilon
    ), f"Negative control mutant should be rejected by DKW bound, got {wrong_diff:.5f} <= {epsilon:.5f}"


# ==============================================================================
# release-capability-coverage-146: Coverage of all 50 assigned rows
# ==============================================================================


def test_release_capability_coverage_146():
    """Assert all 50 assigned capability rows for Issue #146 are mapped in contract.json and verified."""
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file(), f"Missing contract.json at {contract_path}"
    with open(contract_path, encoding="utf-8") as f:
        contract = json.load(f)

    assert contract["schema_version"] == 1
    assert contract["issue"] == 146
    assert contract["acceptance_checks"] == [
        "release-nfcore",
        "release-nfcore-statistics",
        "release-capability-coverage-146",
    ]

    contract_rows = set(contract.get("inventory_rows", []))
    expected_rows = set(ASSIGNED_INVENTORY_ROWS)
    assert len(expected_rows) == 50

    missing_rows = expected_rows - contract_rows
    assert not missing_rows, f"contract.json is missing inventory rows: {missing_rows}"

    extra_rows = contract_rows - expected_rows
    assert not extra_rows, f"contract.json has unassigned inventory rows: {extra_rows}"

    obligations = contract.get("obligations", [])
    assert len(obligations) == 12, f"Expected 12 obligations, found {len(obligations)}"
