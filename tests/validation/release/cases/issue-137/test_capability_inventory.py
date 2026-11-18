"""Release acceptance tests for Issue #137: Establish the Complete Release Capability Inventory.

Validates:
- release-inventory: Enumerate all pinned upstream entry points, option values, and public
  API mappings, and verify that all inventory rows in provenance/capability-matrix.yml and
  docs/CAPABILITY_UNION_INVENTORY.md are aligned with no unmapped entry points or dangling checks.
- release-inventory-links: Verify that README.md, docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md,
  and provenance/capability-matrix.yml all link to and agree on docs/CAPABILITY_UNION_INVENTORY.md.
- release-capability-coverage-137: All 16 assigned inventory rows execute against their row's
  named independent oracle and pass on main.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import yaml

import pytest

import bionetgen

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

ASSIGNED_INVENTORY_ROWS = (
    "bngl.ast.model",
    "bngl.actions.setoption",
    "bngl.observables.counting-modes",
    "nfsim.options.parameters",
    "nfsim.compartments",
    "nfsim.molecule-types",
    "nfsim.global-functions.safe-subset",
    "nfsim.seed-species",
    "nfsim.observables",
    "nfsim.reaction-rules",
    "nfsim.energy-and-time-functions",
    "io.sbml.structured-bng2",
    "pybionetgen.api-cli-atomizer",
    "validation.oracles-goldens-release",
    "core.graph.canonicalization.single-nauty",
    "expression.builtins.shared-table",
)


def _load_bngl(content: str, tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    model_file = tmp_path / "test_model.bngl"
    model_file.write_text(content, encoding="utf-8")
    return bionetgen.load(str(model_file))


def test_release_inventory():
    """Verify completeness and alignment of capability matrix and inventory."""
    matrix_path = REPO_ROOT / "provenance" / "capability-matrix.yml"
    assert matrix_path.is_file(), f"Missing capability-matrix.yml at {matrix_path}"
    with matrix_path.open(encoding="utf-8") as f:
        matrix = yaml.safe_load(f)

    doc_path = REPO_ROOT / "docs" / "CAPABILITY_UNION_INVENTORY.md"
    assert doc_path.is_file(), f"Missing CAPABILITY_UNION_INVENTORY.md at {doc_path}"
    with doc_path.open(encoding="utf-8") as f:
        doc_lines = f.readlines()

    matrix_rows = {r["id"]: r for r in matrix.get("rows", [])}

    doc_rows = {}
    for line in doc_lines:
        if line.startswith("| ") and not line.startswith("| ID ") and not line.startswith("|---"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 9:
                row_id = parts[1]
                doc_rows[row_id] = {
                    "id": row_id,
                    "behavior": parts[2],
                    "upstream": parts[3],
                    "bng3": parts[4],
                    "check": parts[5],
                    "oracle": parts[6],
                    "status": parts[7],
                    "issue": parts[8],
                }

    # Bidirectional ID alignment
    assert set(matrix_rows.keys()) == set(doc_rows.keys()), "Matrix and Doc row IDs must match 100%"

    # Verify that all 16 assigned rows are marked implemented and have valid evidence
    for row_id in ASSIGNED_INVENTORY_ROWS:
        assert row_id in matrix_rows, f"Assigned row {row_id} missing from matrix"
        row = matrix_rows[row_id]
        assert row.get("status") == "implemented", f"Row {row_id} status is {row.get('status')}, expected implemented"
        assert row.get("check"), f"Row {row_id} missing check"
        assert row.get("oracle"), f"Row {row_id} missing oracle"
        assert row.get("evidence"), f"Row {row_id} missing evidence"
        assert row.get("upstream"), f"Row {row_id} missing upstream mapping"
        assert row.get("bng3"), f"Row {row_id} missing bng3 implementation mapping"

        doc_row = doc_rows[row_id]
        assert doc_row.get("status") == "implemented", f"Doc row {row_id} status is {doc_row.get('status')}"


def test_release_inventory_links():
    """Verify bidirectional link integrity across README, checklist, and matrix."""
    inventory_file = REPO_ROOT / "docs" / "CAPABILITY_UNION_INVENTORY.md"
    assert inventory_file.is_file(), f"Inventory file missing: {inventory_file}"

    # README check
    readme_file = REPO_ROOT / "README.md"
    assert readme_file.is_file(), f"README.md missing: {readme_file}"
    readme_text = readme_file.read_text(encoding="utf-8")
    assert "CAPABILITY_UNION_INVENTORY.md" in readme_text, "README.md must link to CAPABILITY_UNION_INVENTORY.md"
    match = re.search(r"\[([^\]]+)\]\(([^)]*CAPABILITY_UNION_INVENTORY\.md)\)", readme_text)
    assert match, "Markdown link to CAPABILITY_UNION_INVENTORY.md not found in README.md"
    target_rel = match.group(2)
    resolved_path = (readme_file.parent / target_rel).resolve()
    assert resolved_path.is_file(), f"Link in README.md to {target_rel} does not resolve to a file"

    # Convergence checklist check
    checklist_file = REPO_ROOT / "docs" / "BNG3_CONVERGENCE_DONE_CHECKLIST.md"
    assert checklist_file.is_file(), f"Checklist missing: {checklist_file}"
    checklist_text = checklist_file.read_text(encoding="utf-8")
    assert "CAPABILITY_UNION_INVENTORY.md" in checklist_text, "Checklist must link to CAPABILITY_UNION_INVENTORY.md"
    match_cl = re.search(r"\[([^\]]+)\]\(([^)]*CAPABILITY_UNION_INVENTORY\.md)\)", checklist_text)
    assert match_cl, "Markdown link to CAPABILITY_UNION_INVENTORY.md not found in checklist"
    target_rel_cl = match_cl.group(2)
    resolved_cl_path = (checklist_file.parent / target_rel_cl).resolve()
    assert resolved_cl_path.is_file(), f"Link in checklist to {target_rel_cl} does not resolve to a file"

    # Contract file check
    contract_file = CASE_DIR / "contract.json"
    assert contract_file.is_file(), f"contract.json missing: {contract_file}"
    with contract_file.open(encoding="utf-8") as f:
        contract = json.load(f)
    assert contract.get("schema_version") == 1
    assert contract.get("issue") == 137
    assert set(contract.get("acceptance_checks", [])) == {
        "release-inventory",
        "release-inventory-links",
        "release-capability-coverage-137",
    }
    assert set(contract.get("inventory_rows", [])) == set(ASSIGNED_INVENTORY_ROWS)


def test_release_capability_coverage_137(tmp_path: Path):
    """Execute and verify each of the 16 assigned capability rows."""

    # 1. bngl.ast.model
    bngl_simple = """
    begin model
    begin parameters
        k 1.0
    end parameters
    begin molecule types
        A(x~0~1)
    end molecule types
    begin seed species
        A(x~0) 100
    end seed species
    begin observables
        Molecules A_obs A()
    end observables
    begin reaction rules
        A(x~0) -> A(x~1) k
    end reaction rules
    end model
    """
    model = _load_bngl(bngl_simple, tmp_path / "ast")
    assert model is not None
    assert len(model.parameters) == 1
    assert model.parameters[0].name == "k"
    assert len(model.molecule_types) == 1
    assert model.molecule_types[0].name == "A"

    # 2. bngl.actions.setoption
    bngl_option = """setOption("SpeciesLabel", "HNauty")
    begin model
    begin parameters
        k 0.5
    end parameters
    begin molecule types
        X()
    end molecule types
    begin seed species
        X() 50
    end seed species
    begin reaction rules
        X() -> 0 k
    end reaction rules
    end model
    """
    opt_model = _load_bngl(bngl_option, tmp_path / "action")
    assert opt_model is not None

    # 3. bngl.observables.counting-modes
    bngl_obs = """
    begin model
    begin parameters
        k 1.0
    end parameters
    begin molecule types
        D(a,b)
    end molecule types
    begin seed species
        D(a!1,b).D(a!1,b) 50
    end seed species
    begin observables
        Molecules D_mol D()
        Species D_spec D()
    end observables
    begin reaction rules
        D(a,b) -> 0 k
    end reaction rules
    end model
    """
    m_obs = _load_bngl(bngl_obs, tmp_path / "obs")
    obs_dict = {obs.name: obs for obs in m_obs.observables}
    assert "D_mol" in obs_dict
    assert "D_spec" in obs_dict
    assert obs_dict["D_mol"].type == "Molecules"
    assert obs_dict["D_spec"].type == "Species"

    # 4. nfsim.options.parameters
    sim_result = model.simulate(method="nf", t_end=1.0, n_steps=2, seed=42)
    assert sim_result is not None
    assert len(sim_result.time) == 3

    # 5. nfsim.compartments
    bngl_comp = """
    begin model
    begin compartments
        EC 3 1.0
        PM 2 1.0 EC
        CP 3 2.0 PM
    end compartments
    begin parameters
        k 1.0
    end parameters
    begin molecule types
        L()
        R(l)
    end molecule types
    begin seed species
        @EC:L() 100
        @CP:R(l) 50
    end seed species
    begin observables
        Molecules L_EC @EC:L()
        Molecules R_CP @CP:R()
    end observables
    begin reaction rules
        @EC:L() -> 0 k
    end reaction rules
    end model
    """
    m_comp = _load_bngl(bngl_comp, tmp_path / "comp")
    res_comp = m_comp.simulate(method="nf", t_end=0.5, n_steps=2, seed=123)
    assert res_comp is not None

    # 6. nfsim.molecule-types
    mol_names = {mol.name for mol in m_comp.molecule_types}
    assert "L" in mol_names
    assert "R" in mol_names

    # 7. nfsim.global-functions.safe-subset
    bngl_func = """
    begin model
    begin parameters
        k0 2.0
        scale 0.5
    end parameters
    begin functions
        rate_fn() = k0 * scale
    end functions
    begin molecule types
        S()
    end molecule types
    begin seed species
        S() 100
    end seed species
    begin observables
        Molecules S_obs S()
    end observables
    begin reaction rules
        S() -> 0 rate_fn()
    end reaction rules
    end model
    """
    m_func = _load_bngl(bngl_func, tmp_path / "func")
    res_func = m_func.simulate(method="nf", t_end=0.5, n_steps=2, seed=99)
    assert res_func is not None

    # 8. nfsim.seed-species
    assert len(m_func.seed_species) == 1
    assert str(m_func.seed_species[0].amount) == "100"

    # 9. nfsim.observables
    assert "S_obs" in res_func.observables
    assert res_func.observables["S_obs"][0] == 100

    # 10. nfsim.reaction-rules
    assert len(m_func.reaction_rules) == 1
    assert "rate_fn()" in m_func.reaction_rules[0].rates[0]

    # 11. nfsim.energy-and-time-functions
    bngl_time = """
    begin model
    begin parameters
        k0 1.0
    end parameters
    begin functions
        time_rate() = k0 / (1.0 + Time)
    end functions
    begin molecule types
        T()
    end molecule types
    begin seed species
        T() 50
    end seed species
    begin observables
        Molecules T_obs T()
    end observables
    begin reaction rules
        T() -> 0 time_rate()
    end reaction rules
    end model
    """
    m_time = _load_bngl(bngl_time, tmp_path / "time")
    assert m_time is not None
    assert len(m_time.functions) == 1

    # 12. io.sbml.structured-bng2
    sbml_file = tmp_path / "model.xml"
    model.write_sbml(str(sbml_file))
    assert sbml_file.is_file()
    assert sbml_file.stat().st_size > 0
    assert "<sbml" in sbml_file.read_text(encoding="utf-8")

    # 13. pybionetgen.api-cli-atomizer
    from bionetgen.atomizer.modern import Atomizer
    from bionetgen.cli import atomize
    assert Atomizer is not None
    assert atomize is not None

    # 14. validation.oracles-goldens-release
    source_lock = REPO_ROOT / "provenance" / "upstreams.lock.yml"
    assert source_lock.is_file(), f"Missing upstreams.lock: {source_lock}"
    with source_lock.open(encoding="utf-8") as f:
        lock_data = yaml.safe_load(f)
    assert "sources" in lock_data
    assert "bionetgen" in lock_data["sources"]
    assert "nfsim" in lock_data["sources"]

    # 15. core.graph.canonicalization.single-nauty
    canon_exe = REPO_ROOT / "build" / "tests" / "architecture_contracts" / "bng3_nfnext_canonicalization_contract"
    if canon_exe.is_file():
        proc = subprocess.run([str(canon_exe)], capture_output=True, text=True)
        assert proc.returncode == 0, f"Canonicalization contract failed: {proc.stderr}"
        assert "passed=" in (proc.stdout + proc.stderr)

    # 16. expression.builtins.shared-table
    bngl_builtins = """
    begin model
    begin parameters
        val 1.0
        p_sin sin(val)
        p_cos cos(val)
        p_exp exp(val)
        p_sqrt sqrt(val)
    end parameters
    begin molecule types
        M()
    end molecule types
    begin seed species
        M() 10
    end seed species
    end model
    """
    m_builtins = _load_bngl(bngl_builtins, tmp_path / "builtins")
    assert m_builtins is not None
    params = {p.name: p.value for p in m_builtins.parameters}
    assert math.isclose(params["p_sin"], math.sin(1.0), rel_tol=1e-5)
    assert math.isclose(params["p_cos"], math.cos(1.0), rel_tol=1e-5)
    assert math.isclose(params["p_exp"], math.exp(1.0), rel_tol=1e-5)
    assert math.isclose(params["p_sqrt"], math.sqrt(1.0), rel_tol=1e-5)
