"""Negative and structural controls for the #137 inventory consumers.

These tests exercise the check implementation; they are not product-support
evidence and a passing check here never promotes a capability row.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import issue137_checks as checks  # noqa: E402

REVISION = "641a2e144a4ce8cc8cf20305fd289288477c6524"


def _report(rows):
    return {
        "schema_version": 1,
        "source": {"revision": REVISION, "dirty": False},
        "references": {
            "bionetgen": {
                "revision": checks.json.loads(
                    (
                        checks.ROOT
                        / "provenance/reconciliation/inventory-oracle-map.json"
                    ).read_text()
                )["pins"]["bionetgen"]
            },
            "nfsim": {
                "revision": checks.json.loads(
                    (
                        checks.ROOT
                        / "provenance/reconciliation/inventory-oracle-map.json"
                    ).read_text()
                )["pins"]["nfsim"]
            },
            "pybionetgen": {
                "revision": checks.json.loads(
                    (
                        checks.ROOT
                        / "provenance/reconciliation/inventory-oracle-map.json"
                    ).read_text()
                )["pins"]["pybionetgen"]
            },
            "analytic": {"law": "independent detailed-balance derivation"},
            "structural-contract": {"contract": "provenance/golden/README.md manifest"},
        },
        "results": [
            {
                "id": f"release-capability[{row}]",
                "status": "PASS",
                "evidence_kind": "supported-execution",
                "supported_execution": True,
                "related_issues": [137],
            }
            for row in rows
        ],
    }


def test_structural_and_link_contracts_hold_at_audit_revision():
    assert checks.structural_gaps() == []
    assert checks.link_gaps() == []


def test_coverage_requires_every_row_with_a_pinned_oracle(tmp_path):
    report = _report(checks.ROW_IDS)
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(report))
    assert checks.coverage_gaps([json.loads(path.read_text())], REVISION) == []


@pytest.mark.parametrize("mutated", ["drop-row", "stale-revision", "loss-diagnostic"])
def test_coverage_rejects_missing_or_unverifiable_results(tmp_path, mutated):
    report = _report(checks.ROW_IDS)
    if mutated == "drop-row":
        report["results"] = report["results"][1:]
    elif mutated == "stale-revision":
        report["source"]["revision"] = "0" * 40
    else:
        report["results"][0]["diagnostics"] = [{"severity": "approximated"}]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(report))
    assert checks.coverage_gaps([json.loads(path.read_text())], REVISION)


def _copy_inventory_root(root: Path) -> None:
    for rel in (
        "provenance/capability-matrix.yml",
        "provenance/reconciliation/inventory-oracle-map.json",
        "docs/CAPABILITY_UNION_INVENTORY.md",
        "provenance/upstreams.lock.yml",
        "README.md",
        "docs/CURRENT_PROGRESS.md",
    ):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text((checks.ROOT / rel).read_text())


def test_generic_oracle_declaration_is_rejected(tmp_path):
    root = tmp_path / "repo"
    _copy_inventory_root(root)
    matrix = root / "provenance/capability-matrix.yml"
    rows = checks._yaml(matrix)["rows"]
    target = next(row for row in rows if row["id"] in checks.ROW_IDS)
    text = matrix.read_text().replace(
        '"oracle": "' + target["oracle"] + '"',
        '"oracle": "' + checks.GENERIC_ORACLE + '"',
    )
    matrix.write_text(text)
    assert checks.structural_gaps(root)


def test_structural_gaps_uses_supplied_root_oracle_map(tmp_path):
    root = tmp_path / "repo"
    _copy_inventory_root(root)
    map_path = root / "provenance/reconciliation/inventory-oracle-map.json"
    mapping = json.loads(map_path.read_text())
    for entry in mapping["rows"].values():
        selector = root / entry["selector"]
        selector.parent.mkdir(parents=True, exist_ok=True)
        selector.write_text("")
    assert checks.structural_gaps(root) == []

    mapping["pins"]["bionetgen"] = "0" * 40
    map_path.write_text(json.dumps(mapping))
    gaps = checks.structural_gaps(root)
    assert any("oracle map pin" in gap for gap in gaps)


def test_declaration_only_cannot_qualify_coverage():
    assert checks.coverage_gaps([], REVISION)
