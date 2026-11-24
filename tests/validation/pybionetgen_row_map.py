"""Per-row py.* surface comparison against the pinned PyBioNetGen source.

This is the mapping layer requested for Issue #171: every ``py.*`` inventory
row is tied to its declared pinned-oracle source coordinate and to a BNG3
module that must actually resolve at runtime.  The report records the package
and oracle identities.  A row that cannot resolve on either side is FAIL, not
a silent omission.  Semantic/behavioral differential is a separate, stronger
claim and is labelled as such in the report.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UPSTREAM_RE = re.compile(r"^pybionetgen:(?P<path>[^:]+):(?P<loc>.+)$")


def oracle_identity(source_root: Path) -> dict:
    revision = subprocess.check_output(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True
    ).strip()
    lock = json.loads((ROOT / "provenance/upstreams.lock.yml").read_text())
    pinned = lock["sources"]["pybionetgen"]["revision"]
    return {
        "name": "PyBioNetGen",
        "pinned_revision": pinned,
        "source_revision": revision,
        "source_root": str(source_root),
        "matches_pin": revision == pinned,
    }


def package_identity() -> dict:
    import bionetgen
    from importlib.metadata import version

    return {
        "name": "bionetgen",
        "version": version("bionetgen"),
        "module": bionetgen.__file__,
        "source_revision": subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip(),
    }


def _bng3_target(row: dict) -> str | None:
    """Read the declared BNG3 replacement from the matrix behavior field."""
    match = re.search(r"→\s*([^\s(]+)", row.get("behavior", ""))
    return match.group(1) if match else None


def _resolves(target: str | None, row_id: str) -> bool:
    if not target:
        return _cli_option_present(row_id)
    if target.startswith("BioNetGenModel."):
        model = getattr(importlib.import_module("bionetgen"), "BioNetGenModel", None)
        return model is not None and hasattr(model, target.split(".", 1)[1])
    parts = target.split(".")
    for split in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:split]))
        except Exception:
            continue
        for attribute in parts[split:]:
            if not hasattr(obj, attribute):
                break
            obj = getattr(obj, attribute)
        else:
            return True
    return _cli_option_present(row_id)


def _cli_option_present(row_id: str) -> bool:
    if ".cli.option." not in row_id and not row_id.startswith("py.cli."):
        return False
    option = row_id.rsplit(".", 1)[-1]
    text = ""
    for path in (
        ROOT / "python/bionetgen/cli.py",
        ROOT / "python/bionetgen/core/main.py",
    ):
        if path.is_file():
            text += path.read_text(errors="ignore")
    for spelling in (f'"{option}"', f'"--{option}"', f'"--{option.replace("-", "_")}"'):
        if spelling in text:
            return True
    return False


# Documented BNG3 equivalents for pinned PyBioNetGen atomizer CLI options.
# A flag may be absent from the CLI while the capability exists in the legacy
# AtomizeTool configuration; these are recorded as dispositions, not as passes.
CLI_EQUIVALENTS = {
    "annotation": "AtomizeTool.config['annotation']",
    "bionetgen-analysis": "AtomizeTool.config['bionetgen_analysis']",
    "convention-file": "AtomizeTool.config['convention_file']",
    "convert-units": "atomize CLI --no-conversion (inverted default)",
    "ignore": "AtomizeTool.config['ignore']",
    "input-file": "atomize CLI --input",
    "isomorphism-check": "AtomizeTool.config['isomorphism_check']",
    "keep-local-parameters": "AtomizeTool.config['keep_local_parameters']",
    "log-level": "AtomizeTool.config['log_level']",
    "memoized-resolver": "AtomizeTool.config['memoized_resolver']",
    "molecule-id": "AtomizeTool.config['molecule_id']",
    "naming-conventions": "AtomizeTool.config['naming_conventions']",
    "obs-map-file": "AtomizeTool.config['obs_map_file']",
    "output-file": "atomize CLI --output",
    "pathwaycommons": "atomize CLI --no-pathwaycommons (inverted default)",
    "quiet-mode": "AtomizeTool.config['quiet_mode']",
    "user-structures": "AtomizeTool.config['user_structures']",
    "version": "click.version_option(package_name='bionetgen')",
}
_NO_CLI_EQUIVALENT = (
    "no BNG3 CLI flag or AtomizeTool config key; requires a product change"
)


def _disposition(row_id: str) -> tuple[str, str]:
    if row_id.endswith(".add_modifier") or row_id.endswith(".resolve_ratelaw"):
        return (
            "missing-product-entry-point",
            "pinned public method is not exposed by BNG3",
        )
    option = row_id.rsplit(".", 1)[-1]
    if option in CLI_EQUIVALENTS:
        return (
            "capability-without-cli-flag",
            f"capability exists as {CLI_EQUIVALENTS[option]}; PyBioNetGen CLI flag absent",
        )
    return "missing-cli-flag", _NO_CLI_EQUIVALENT


def run_row_map(source_root: Path) -> dict:
    import yaml

    matrix = yaml.safe_load((ROOT / "provenance/capability-matrix.yml").read_text())
    rows = [row for row in matrix["rows"] if row["id"].startswith("py.")]
    identity = oracle_identity(source_root)
    results = []
    cache: dict[str, bool] = {}
    for row in rows:
        row_id = row["id"]
        match = UPSTREAM_RE.match(row.get("upstream", ""))
        oracle_ok = False
        if match and identity["matches_pin"]:
            path = source_root / match.group("path")
            oracle_ok = path.is_file()
        target = _bng3_target(row)
        key = target or row_id
        if key not in cache:
            cache[key] = _resolves(target, row_id)
        passed = oracle_ok and cache[key]
        category, reason = ("resolved", "") if passed else _disposition(row_id)
        results.append(
            {
                "id": row_id,
                "status": "PASS" if passed else "FAIL",
                "disposition": category,
                "reason": reason,
                "oracle_coordinate": row.get("upstream", ""),
                "bng3_coordinate": row.get("bng3", ""),
                "bng3_target": target,
                "bng3_symbol_resolves": cache[key],
                "oracle_file_present": oracle_ok,
                "evidence_kind": "surface-differential",
            }
        )
    counts: dict[str, int] = {}
    for row in results:
        counts[row["disposition"]] = counts.get(row["disposition"], 0) + 1
    return {
        "schema_version": 1,
        "acceptance_check": "release-python-api",
        "case": "issue-171/py-row-map",
        "scope": "surface-presence and source-coordinate comparison for every py.* row; behavioral differential is a stronger separate claim",
        "package": package_identity(),
        "oracle": identity,
        "row_count": len(results),
        "disposition_counts": counts,
        "results": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_row_map(args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    passed = sum(row["status"] == "PASS" for row in report["results"])
    print(
        f"py.* row map: {passed}/{report['row_count']} surface comparisons pass "
        f"(oracle {report['oracle']['source_revision']}, package {report['package']['version']})"
    )
    return 0 if passed == report["row_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
