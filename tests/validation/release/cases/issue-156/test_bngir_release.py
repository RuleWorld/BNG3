"""Release acceptance suite for Issue #156: BNGIR & Semantic Equality.

Validates:
- release-bngir-schema: independent BNGL/JSON fixtures cover every
  inventory construct and version migration.
- release-semantic-equality: all EQ-* certified cases pass; numerical
  similarity never establishes equality; undecided raises EqualityUndecided.
- release-capability-coverage-156: verifies exact-revision release contracts,
  inventory rows (bngir.v02, bngir.equality), and live acceptance obligations.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
import yaml

import bionetgen
from bionetgen.bngir import (
    EqualityUndecided,
    from_bngir,
    semantic_equal,
    to_bngir,
)

from bionetgen.model import _cpp

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.validation.eq_catalogue import (  # noqa: E402
    CASES,
    validate_catalogue_report,
)


@pytest.fixture(scope="module")
def eq_catalogue_report():
    """Execute every EQ-* row once for the module's release checks."""
    from tests.validation.eq_catalogue import run_catalogue

    report = run_catalogue()
    validate_catalogue_report(report)
    return report


def _parse_model(bngl: str) -> bionetgen.BioNetGenModel:
    return bionetgen.BioNetGenModel(_cpp.parse_string(bngl))


def test_release_bngir_schema():
    """Validate release-bngir-schema.

    1. BNGIR v0.2 represents delayed rules, units, observable kinds,
       and rule modifiers without data loss.
    2. Document conforms to schema/bngir-0.2.schema.json.
    3. Round trip BNGL -> BNGIR v0.2 -> BNGL preserves semantic identity.
    """
    model_bngl = """
begin model
begin parameters
    k1 1.0
    k2 0.5
    tau 2.0
end parameters
begin molecule types
    A(s~U~P)
    B(s~U~P)
end molecule types
begin compartments
    cell 3 1.0
end compartments
begin seed species
    @cell:A(s~U) 100
end seed species
begin observables
    Molecules TotalA A()
    Species ActiveA @cell:A(s~P)
end observables
begin reaction rules
    r1: A(s~U) -> A(s~P) k1
    r2: A(s~P) -> B(s~U) k2 delay=tau
end reaction rules
end model
"""
    model = _parse_model(model_bngl)

    # Verify BNGIR v0.2 serialization and round-trip
    ir_v02 = json.loads(to_bngir(model, version="0.2"))
    assert ir_v02["version"] == "0.2"
    assert "model" in ir_v02

    # Verify schema conformance against both wire schemas (not just file existence)
    import copy

    import jsonschema

    schema_v02 = json.loads(
        (REPO_ROOT / "provenance" / "schemas" / "bngir-0.2.schema.json").read_text()
    )
    schema_v01 = json.loads(
        (REPO_ROOT / "provenance" / "schemas" / "bngir-0.1.schema.json").read_text()
    )
    jsonschema.validate(ir_v02, schema_v02)

    # Restore from BNGIR v0.2
    restored = from_bngir(ir_v02)
    assert isinstance(restored, bionetgen.BioNetGenModel)
    assert semantic_equal(model, restored, version="0.2") is True

    # Verify default version is v0.2
    ir_default = json.loads(to_bngir(model))
    assert ir_default["version"] == "0.2"

    # Verify wire round trip in v0.1 format
    ir_v01 = json.loads(to_bngir(model, version="0.1"))
    assert ir_v01["version"] == "0.1"
    jsonschema.validate(ir_v01, schema_v01)
    restored_v01 = from_bngir(ir_v01)
    assert isinstance(restored_v01, bionetgen.BioNetGenModel)

    # Negative control: a structurally broken v0.2 document must be rejected
    # by the same schema, so the positive validation is not vacuous.
    broken = copy.deepcopy(ir_v02)
    broken["format"] = "NOT-BNGIR"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, schema_v02)


def test_release_semantic_equality(eq_catalogue_report):
    """Validate release-semantic-equality.

    1. EQ-rename: consistent type/site/state renaming preserves equality.
    2. EQ-split: split rules with equal summed rates preserve equality.
    3. Numerical similarity never establishes equality (distinct hazards
       return False).
    4. Observable patterns and function bodies are strictly verified.
    5. EqualityUndecided is raised when no terminating decision procedure
       exists.
    """
    # EQ-rename: renaming molecule types consistently preserves equality
    base_bngl = """
begin model
begin parameters
    k 0.1
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
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    renamed_bngl = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
    Y()
end molecule types
begin seed species
    X() 10
end seed species
begin observables
    Molecules A_obs X()
end observables
begin reaction rules
    X() -> Y() k
end reaction rules
end model
"""
    m_base = _parse_model(base_bngl)
    m_renamed = _parse_model(renamed_bngl)
    assert semantic_equal(m_base, m_renamed) is True

    # EQ-split: splitting rule into k1 + k2 = k preserves equality
    split_bngl = """
begin model
begin parameters
    k1 0.04
    k2 0.06
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
end observables
begin reaction rules
    r1: A() -> B() k1
    r2: A() -> B() k2
end reaction rules
end model
"""
    m_split = _parse_model(split_bngl)
    assert semantic_equal(m_base, m_split) is True

    # Mutated rate sum (0.04 + 0.07 = 0.11 != 0.10) strictly returns False
    diff_split_bngl = """
begin model
begin parameters
    k1 0.04
    k2 0.07
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
end observables
begin reaction rules
    r1: A() -> B() k1
    r2: A() -> B() k2
end reaction rules
end model
"""
    m_diff = _parse_model(diff_split_bngl)
    assert semantic_equal(m_base, m_diff) is False

    # Numerical similarity never establishes equality:
    # Nearby rational hazards (1.0 vs 1.0000000001) must return False
    hazard_base = """
begin model
begin parameters
    k 1.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    hazard_nearby = """
begin model
begin parameters
    k 1.0000000001
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    m_hz1 = _parse_model(hazard_base)
    m_hz2 = _parse_model(hazard_nearby)
    assert semantic_equal(m_hz1, m_hz2) is False

    # Differing observable patterns produce a verified inequivalence
    # certificate (False), never a numerical-similarity "close enough" result.
    obs_diff = """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules B_obs B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""
    m_obs_diff = _parse_model(obs_diff)
    assert semantic_equal(m_base, m_obs_diff) is False

    # EqualityUndecided is raised for non-terminating / infinite models
    infinite_polymer = """
begin model
begin parameters
    k 1.0
end parameters
begin molecule types
    M(l,r)
end molecule types
begin seed species
    M(l,r) 10
end seed species
begin reaction rules
    M(r) + M(l) <-> M(r!1).M(l!1) k, k
end reaction rules
end model
"""
    other_polymer = """
begin model
begin parameters
    k 2.0
end parameters
begin molecule types
    M(l,r)
end molecule types
begin seed species
    M(l,r) 10
end seed species
begin reaction rules
    M(r) + M(l) <-> M(r!1).M(l!1) k, k
end reaction rules
end model
"""
    m_poly1 = _parse_model(infinite_polymer)
    m_poly2 = _parse_model(other_polymer)
    with pytest.raises(EqualityUndecided):
        semantic_equal(m_poly1, m_poly2)

    # Independent catalogue: every EQ-* family is executed with a declared
    # outcome and a named oracle.  Membership in a design document is not
    # evidence, so the strict validator is part of this check.
    validate_catalogue_report(eq_catalogue_report)
    assert {case.id for case in CASES} <= {
        row["case"] for row in eq_catalogue_report["results"]
    }


def test_release_capability_coverage_156(eq_catalogue_report):
    """Validate release-capability-coverage-156.

    Each assigned inventory row must execute against its named independent
    oracle.  Inventory membership and contract-file existence are necessary
    bookkeeping, never a substitute for per-row results:
      * bngir.v02  -> the EQ-serialization rows of the independent catalogue;
      * bngir.equality -> all EQ-* rows with equal/different/undecided outcomes.
    """
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file(), "contract.json missing"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    assert contract["schema_version"] == 1
    assert contract["issue"] == 156
    assert contract["acceptance_checks"] == [
        "release-bngir-schema",
        "release-semantic-equality",
        "release-capability-coverage-156",
    ]

    # Verify inventory rows exist in capability-matrix.yml
    matrix_path = REPO_ROOT / "provenance" / "capability-matrix.yml"
    assert matrix_path.is_file(), "capability-matrix.yml missing"
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    matrix_ids = {row["id"] for row in matrix.get("rows", [])}
    for row_id in contract["inventory_rows"]:
        assert row_id in matrix_ids, f"Row {row_id} not in capability matrix"

    # Verify live acceptance obligations in issue-obligations.json
    obligations_path = REPO_ROOT / "provenance" / "issue-obligations.json"
    assert obligations_path.is_file(), "issue-obligations.json missing"
    prov = json.loads(obligations_path.read_text(encoding="utf-8"))
    issue_entry = next(
        (item for item in prov.get("issues", []) if item.get("number") == 156),
        None,
    )
    assert issue_entry is not None, "Issue 156 missing from issue-obligations"
    declared_ob_ids = {ob["id"] for ob in issue_entry.get("obligations", [])}
    for req_ob in contract["obligations"]:
        assert (
            req_ob in declared_ob_ids
        ), f"Obligation {req_ob} not found in issue-obligations for issue 156"

    # Per-row executable evidence.  A document that only lists the inventory
    # ids cannot satisfy this check: validate_catalogue_report rejects it.
    validate_catalogue_report(eq_catalogue_report)
    rows = eq_catalogue_report["results"]
    assert eq_catalogue_report["case_count"] == len(CASES)
    assert eq_catalogue_report["row_count"] == len(rows) == 2 * len(CASES)
    assert all(row["status"] == "PASS" for row in rows)
    assert all(row["oracle"] for row in rows)
    by_case = {}
    for row in rows:
        by_case.setdefault(row["case"], []).append(row)
    assert set(by_case) == {case.id for case in CASES}
    serialization = by_case["EQ-serialization"]
    assert {row["variant"] for row in serialization} == {"equal", "different"}
    assert all(row["observed"] == row["expected"] for row in serialization)
    outcomes = {row["observed"] for row in rows}
    assert outcomes == {"equal", "different", "undecided"}
