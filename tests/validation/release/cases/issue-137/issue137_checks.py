"""Fail-closed release consumers for issue #137 inventory obligations.

This package maps the 16 capability rows owned by #137 from the generic oracle
declaration to named independent oracles and existing executable selectors.  A
mapping is a structural contract, not an execution result: a row counts as
covered only when an exact-revision ``release-capability[ID]`` case result from
an independent oracle consumes that row.  No BNG3-generated expected answer is
accepted as an oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
GENERIC_ORACLE = "canonical source or analytic specification as appropriate"
MAP_PATH = ROOT / "provenance/reconciliation/inventory-oracle-map.json"
ROW_IDS = (
    "bngl.ast.model",
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
    "bngl.actions.setoption",
    "bngl.observables.counting-modes",
)
LOSS_SEVERITIES = {
    "dropped",
    "approximated",
    "unsupported",
    "untranslated",
    "error",
}


def _yaml(path):
    # PyYAML is a validation dependency; avoid a product-import dependency.
    import yaml

    return yaml.safe_load(path.read_text())


def _inventory_ids(text):
    ids = set()
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-]*", cells[0]):
            if cells[0] == "ID":
                continue
            ids.add(cells[0])
    return ids


def structural_gaps(root=ROOT):
    gaps = []
    matrix = _yaml(root / "provenance/capability-matrix.yml")
    rows = matrix["rows"]
    by_id = {}
    for row in rows:
        if row["id"] in by_id:
            gaps.append(f"duplicate matrix row: {row['id']}")
        by_id[row["id"]] = row
        for field in ("behavior", "upstream", "bng3", "check", "oracle", "status"):
            if not str(row.get(field, "")).strip():
                gaps.append(f"{row['id']}: empty {field}")
    inventory = (root / "docs/CAPABILITY_UNION_INVENTORY.md").read_text()
    doc_ids = _inventory_ids(inventory)
    matrix_ids = set(by_id)
    if doc_ids != matrix_ids:
        gaps.append(
            "inventory/matrix ID mismatch: "
            f"doc-only={sorted(doc_ids - matrix_ids)[:5]} "
            f"matrix-only={sorted(matrix_ids - doc_ids)[:5]}"
        )
    if len(rows) != 997:
        gaps.append(f"matrix row count changed: {len(rows)} (expected 997)")

    mapping = json.loads(MAP_PATH.read_text())
    mapped = mapping["rows"]
    if set(mapped) != set(ROW_IDS):
        gaps.append("oracle map does not cover exactly the 16 #137 rows")
    lock = _yaml(root / "provenance/upstreams.lock.yml")
    for name, pin in mapping["pins"].items():
        actual = lock["sources"][name]["revision"]
        if actual != pin:
            gaps.append(f"{name}: oracle map pin {pin} != accepted lock {actual}")
    for row_id in ROW_IDS:
        row = by_id.get(row_id, {})
        entry = mapped.get(row_id, {})
        if row.get("oracle") == GENERIC_ORACLE:
            gaps.append(f"{row_id}: generic oracle declaration remains")
        if row.get("status") != "unassessed":
            gaps.append(f"{row_id}: status was changed without an exact-revision case")
        oracle, selector = entry.get("oracle", ""), entry.get("selector", "")
        if not oracle or GENERIC_ORACLE in oracle:
            gaps.append(f"{row_id}: no named independent oracle")
        if not selector or not (root / selector).is_file():
            gaps.append(f"{row_id}: selector {selector!r} does not exist")
        if entry.get("oracle_kind") not in {
            "external-source",
            "analytic",
            "structural-contract",
        }:
            gaps.append(f"{row_id}: oracle_kind is not an independent contract")
        for name, pin in mapping["pins"].items():
            if name in oracle and f"@{pin}" not in oracle:
                gaps.append(f"{row_id}: {name} oracle is not bound to the accepted pin")
    return gaps


def link_gaps(root=ROOT):
    gaps = []
    readme = (root / "README.md").read_text()
    inventory = (root / "docs/CAPABILITY_UNION_INVENTORY.md").read_text()
    progress = (root / "docs/CURRENT_PROGRESS.md").read_text()
    checklist = (root / "docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md").read_text()
    for target in (
        "docs/CAPABILITY_UNION_INVENTORY.md",
        "provenance/capability-matrix.yml",
    ):
        if target not in readme:
            gaps.append(f"README does not link {target}")
    if "capability-matrix.yml" not in checklist:
        gaps.append("convergence checklist does not resolve the capability matrix")
    if "provenance/capability-matrix.yml" not in inventory:
        gaps.append("inventory does not resolve to the machine-readable matrix")
    if "#137" not in progress:
        gaps.append("convergence/progress checklist does not resolve #137")
    return gaps


def coverage_gaps(reports, revision):
    """Consume genuine exact-revision case results; declarations never qualify."""
    observed = {}
    for report in reports:
        source = report.get("source", {})
        if source.get("revision") != revision or source.get("dirty") is not False:
            continue
        for result in report.get("results", []):
            check_id = result.get("id", "")
            row_id = check_id.removeprefix("release-capability[").removesuffix("]")
            if row_id not in ROW_IDS or check_id != f"release-capability[{row_id}]":
                continue
            if (
                result.get("status") != "PASS"
                or result.get("evidence_kind") != "supported-execution"
                or result.get("supported_execution") is not True
                or result.get("aggregate")
            ):
                observed.setdefault(row_id, set()).add("NOT_PASS")
                continue
            if any(
                isinstance(d, dict)
                and str(d.get("severity", "")).lower() in LOSS_SEVERITIES
                for d in result.get("diagnostics", [])
            ):
                observed.setdefault(row_id, set()).add("LOSS_DIAGNOSTIC")
                continue
            entry = json.loads(MAP_PATH.read_text())["rows"][row_id]
            kind = entry["oracle_kind"]
            references = report.get("references", {})
            if kind == "analytic":
                ref = references.get("analytic", {})
                if not isinstance(ref, dict) or not ref.get("law"):
                    observed.setdefault(row_id, set()).add("NO_ANALYTIC_LAW")
                    continue
            elif kind == "external-source":
                name = next(
                    (
                        n
                        for n in ("bionetgen", "nfsim", "pybionetgen")
                        if f"{n}@" in entry["oracle"]
                    ),
                    None,
                )
                ref = references.get(name or "", {})
                if not isinstance(ref, dict) or ref.get("revision") != json.loads(
                    MAP_PATH.read_text()
                )["pins"].get(name):
                    observed.setdefault(row_id, set()).add("NO_PIN_ORACLE")
                    continue
            else:
                ref = references.get("structural-contract", {})
                if not isinstance(ref, dict) or not ref.get("contract"):
                    observed.setdefault(row_id, set()).add("NO_STRUCTURAL_CONTRACT")
                    continue
            observed.setdefault(row_id, set()).add("PASS")
    gaps = []
    for row_id in ROW_IDS:
        states = observed.get(row_id, set())
        if states != {"PASS"}:
            gaps.append(
                f"{row_id}: no exact-revision independent case result "
                f"({','.join(sorted(states)) or 'missing'})"
            )
    return gaps


def _result(check_id, gaps, detail):
    return {
        "id": check_id,
        "status": "FAIL" if gaps else "PASS",
        "evidence_kind": "supported-execution",
        "supported_execution": not gaps,
        "related_issues": [137],
        "detail": detail if gaps else f"{check_id}: structural contract satisfied",
        "gaps": gaps,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", nargs="?", default="inventory", choices=["inventory"]
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--case-report", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.root, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=args.root, text=True
    )
    if head != args.revision or dirty:
        parser.error("inventory acceptance requires the requested clean revision")
    source = {"revision": args.revision, "dirty": False}
    structural = structural_gaps(args.root)
    links = link_gaps(args.root)
    reports = [json.loads(path.read_bytes()) for path in args.case_report]
    cases = coverage_gaps(reports, args.revision)
    report = {
        "schema_version": 1,
        "source": source,
        "check_id": "issue-137-inventory",
        "inputs": [
            {"file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in args.case_report
        ],
        "rows": list(ROW_IDS),
        "results": [
            _result("release-inventory", structural, "Inventory reconciliation gap(s)"),
            _result("release-inventory-links", links, "Inventory link gap(s)"),
            _result(
                "release-capability-coverage-137",
                cases,
                "Missing exact-revision independent case results",
            ),
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for result in report["results"]:
        print(f"{result['id']}: {result['status']} ({len(result['gaps'])} gaps)")
    return int(any(result["status"] == "FAIL" for result in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
