import copy
import json
from pathlib import Path

from scripts.audit_architecture_contracts import audit

ROOT = Path(__file__).resolve().parents[4]


def manifest():
    return json.loads((ROOT / "provenance/architecture-contracts.json").read_text())


def test_imported_contracts_have_explicit_dispositions():
    report = audit(ROOT, manifest())
    assert report["passed"], report


def test_empty_spec_cannot_be_promoted_by_changing_status():
    data = manifest()
    entry = next(e for e in data["contracts"] if e["status"] == "design-only")
    entry["status"] = "reference"
    entry["target"] = "bng3_nfcore2_reference_tests"
    assert not audit(ROOT, data)["passed"]


def test_missing_inventory_entry_is_not_silently_ignored():
    data = copy.deepcopy(manifest())
    data["contracts"].pop()
    assert not audit(ROOT, data)["passed"]
