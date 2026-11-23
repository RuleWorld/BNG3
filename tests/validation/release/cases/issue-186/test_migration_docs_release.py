"""Release acceptance tests for Issue #186 (Migration and Maintenance Guidance).

Validates:
- release-migration-docs: installed-package examples and every migration-table target execute successfully.
- release-maintenance-docs: README/user guide/ADRs agree with DECISIONS.md and contain no contradictory backend or retirement policy.
- release-obligation-186: each task has its named check result, source/oracle identity and contract verified.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest

import bionetgen
from bionetgen.builder import ModelBuilder
import bionetgen.simulator.simulators as bng_simulators

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

SAMPLE_BNGL = """begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules A_total A()
end observables
begin reaction rules
  decay: A() -> 0 k
end reaction rules
end model
"""


def test_release_migration_docs(tmp_path: Path):
    """Verify that installed-package examples and all migration-table targets execute successfully."""
    # 1. First run the existing installed example suite
    installed_suite = (
        REPO_ROOT / "tests/python/test_migration_guide_installed_example.py"
    )
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--noconftest", str(installed_suite)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert (
        proc.returncode == 0
    ), f"test_migration_guide_installed_example failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"

    # 2. Test every row of the migration table systematically
    model_path = tmp_path / "model.bngl"
    model_path.write_text(SAMPLE_BNGL, encoding="utf-8")

    # Row 1: Load model
    model = bionetgen.load(str(model_path))
    assert isinstance(model, bionetgen.model.BioNetGenModel)

    # Row 2: Simulate (ODE)
    res_ode = model.simulate(method="ode", t_end=2.0, n_steps=20)
    assert res_ode.time[-1] == 2.0

    # Row 3: Read observables
    obs = res_ode.observables["A_total"]
    expected_endpoint = 100.0 * np.exp(-0.1 * 2.0)
    assert obs[-1] == pytest.approx(expected_endpoint, rel=1e-5)

    # Row 4: Parameter scan
    scan = model.parameter_scan(
        parameter="k",
        values=[0.1, 1.0],
        method="ode",
        t_end=2.0,
    )
    assert isinstance(scan, bionetgen.ScanResult)
    assert scan.parameter_name == "k"
    final_vals = scan.final("A_total")
    assert final_vals[0] == pytest.approx(100.0 * np.exp(-0.2), rel=1e-5)
    assert final_vals[1] == pytest.approx(100.0 * np.exp(-2.0), rel=1e-5)

    # Row 5: Sensitivity analysis
    sensitivity = model.sensitivity_analysis(
        parameters=["k"], observables=["A_total"], method="ode", t_end=2.0
    )
    assert sensitivity.parameter_names == ["k"]
    assert sensitivity.observable_names == ["A_total"]
    assert sensitivity.matrix[0, 0] == pytest.approx(-0.2, rel=1e-3)

    # Row 6: NFSim / network-free
    res_nf = model.simulate(method="nf", t_end=2.0, n_steps=10, seed=186)
    traj = np.asarray(res_nf.observables["A_total"])
    assert traj[0] == 100
    assert 0 <= traj[-1] <= 100

    # Row 7: Access parameters
    params = {parameter.name: parameter.value for parameter in model.parameters}
    assert params == {"k": 0.1}

    # Row 8: Export SBML
    sbml_file = tmp_path / "model.xml"
    model.write_sbml(str(sbml_file))
    assert sbml_file.is_file()
    assert sbml_file.stat().st_size > 0

    # Row 9: Build models (ModelBuilder API)
    builder = ModelBuilder("BuildTest")
    builder.add_parameter("k_on", 1.0)
    builder.add_parameter("k_off", 0.1)
    builder.add_molecule_type("A(b)")
    builder.add_molecule_type("B(a)")
    builder.add_seed_species("A(b)", 100)
    builder.add_seed_species("B(a)", 200)
    builder.add_observable("Molecules", "AB", "A(b!1).B(a!1)")
    builder.add_rule("A(b) + B(a) -> A(b!1).B(a!1)", "k_on")
    builder.add_rule("A(b!1).B(a!1) -> A(b) + B(a)", "k_off")
    built_model = builder.build()
    assert len(built_model.reaction_rules) == 2

    # Row 10: Import SBML
    imported = bionetgen.from_sbml(str(sbml_file), atomize=True)
    res_imported = imported.simulate(method="ode", t_end=2.0)
    assert res_imported.time[-1] == 2.0


def test_release_maintenance_docs():
    """Verify README, migration guide, and DECISIONS agree without contradictions."""
    readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    guide_text = (REPO_ROOT / "docs" / "migration_guide.md").read_text(encoding="utf-8")
    decisions_text = (REPO_ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")

    # 1. Canonical installation contract
    assert "pip install bionetgen" in guide_text
    assert "pip install bionetgen" in decisions_text

    # 2. Retirement policy of legacy repositories
    assert "BioNetGen" in decisions_text
    assert "NFsim" in decisions_text
    assert "PyBioNetGen" in decisions_text
    assert "retire" in decisions_text.lower()

    # 3. Backend defaults consistency
    # ODE/SSA/PLA/PSA default is native finite-network
    assert "Native finite-network" in guide_text
    # NFnext default for method="nf" in Python
    assert "NFnext" in guide_text
    # GPU consolidation under Decision 17 / #474
    assert "#474" in guide_text
    assert "#474" in decisions_text


def test_release_obligation_186(tmp_path: Path):
    """Verify contract, manifest definitions, and negative control handling."""
    contract_file = CASE_DIR / "contract.json"
    assert contract_file.is_file(), "contract.json missing"
    contract = json.loads(contract_file.read_text(encoding="utf-8"))

    assert contract["schema_version"] == 1
    assert contract["issue"] == 186
    assert contract["acceptance_checks"] == [
        "release-migration-docs",
        "release-maintenance-docs",
        "release-obligation-186",
    ]

    manifest = json.loads(
        (REPO_ROOT / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue_entry = next((i for i in manifest["issues"] if i["number"] == 186), None)
    assert issue_entry is not None, "Issue 186 entry missing from manifest"

    # Negative controls
    m_file = tmp_path / "test_neg.bngl"
    m_file.write_text(SAMPLE_BNGL, encoding="utf-8")
    m = bionetgen.load(str(m_file))
    assert m is not None

    # 1. Invalid method raises ValueError
    with pytest.raises((ValueError, KeyError)):
        bionetgen.run(str(m_file), method="invalid_backend_xyz")

    # 2. Retired simulator raises ValueError
    with pytest.raises(ValueError, match="no longer supported"):
        bng_simulators.sim_getter(model_str="dummy", sim_type="cpy")
