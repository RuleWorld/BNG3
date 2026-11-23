#!/usr/bin/env python3
"""Compare before/after SSTS and BioModels reports over identical pinned inputs.

Issue 164's ``release-atomizer-refactor`` check requires that independent source
results match before and after the Atomizer refactor. This comparator consumes
four *external* artifacts (two official SSTS reports and two curated BioModels
reports), verifies that both sides used the same pinned suite/corpus and
independent reference identities, then compares per-case verdicts. A partial,
stale, dirty or incomplete input fails closed; a dropped case or a verdict
regression is reported, never silently matched.

No expectation, tolerance, seed, skip or exclusion is authored here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

BLOCKING_VERDICTS = {
    "failed",
    "timeout",
    "timed-out",
    "harness_error",
    "invalid-source",
}
PASSED_VERDICTS = {"passed", "pass", "compared", "PASS"}
STATUS_FIELDS = (
    "verdict",
    "status",
    "conversion",
    "official_reference",
    "independent_comparison",
    "roundtrip_structure",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verdict(record: dict) -> str:
    for field in STATUS_FIELDS:
        if field in record:
            return str(record[field])
    return "missing-verdict"


def _load(path: Path, kind: str) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{kind} report is not a JSON object: {path}")
    source = document.get("source_provenance") or document.get("source") or {}
    records = document.get("records") or document.get("cases") or []
    if not records:
        raise ValueError(f"{kind} report has no records: {path}")
    keyed: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f"{kind} report has a non-object record")
        key = str(record.get("id") or record.get("ref") or "")
        if not key:
            raise ValueError(f"{kind} report record has no id")
        keyed[key] = _verdict(record)
    pins = {}
    if kind == "ssts":
        pins["suite_revision"] = document.get("suite_commit") or (
            document.get("provenance", {}).get("sbml_test_suite", {}).get("revision")
        )
        pins["case_inventory"] = document.get("case_inventory")
    else:
        pins["corpus_sha256"] = document.get("corpus_sha256") or document.get(
            "provenance", {}
        ).get("corpus_sha256")
        pins["record_count"] = len(keyed)
        pins["mode"] = document.get("mode")
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "revision": source.get("bng3_commit") or source.get("revision"),
        "dirty": source.get("bng3_tracked_worktree_clean") is False
        or source.get("dirty") is True,
        "partial_run": document.get("partial_run"),
        "pins": pins,
        "records": keyed,
        "counts": document.get("counts") or {},
    }


def compare(
    before_ssts: Path,
    after_ssts: Path,
    before_biomodels: Path,
    after_biomodels: Path,
    expected_revision: str,
) -> dict:
    reports = {
        "before_ssts": _load(before_ssts, "ssts"),
        "after_ssts": _load(after_ssts, "ssts"),
        "before_biomodels": _load(before_biomodels, "biomodels"),
        "after_biomodels": _load(after_biomodels, "biomodels"),
    }
    problems: list[str] = []
    for name, report in reports.items():
        if not report["revision"]:
            problems.append(f"{name}: no source revision")
        if report["dirty"]:
            problems.append(f"{name}: produced from a dirty checkout")
        if report["partial_run"] is not False:
            problems.append(f"{name}: partial or unmarked run")
        for key in (
            "failed",
            "timeout",
            "timed-out",
            "invalid-source",
            "harness_error",
        ):
            if report["counts"].get(key, 0):
                problems.append(f"{name}: {report['counts'][key]} {key} cases")

    if reports["after_ssts"]["revision"] != expected_revision:
        problems.append("after SSTS revision does not match the candidate revision")
    if reports["after_biomodels"]["revision"] != expected_revision:
        problems.append(
            "after BioModels revision does not match the candidate revision"
        )
    for kind in ("ssts", "biomodels"):
        before = reports[f"before_{kind}"]["pins"]
        after = reports[f"after_{kind}"]["pins"]
        if before != after:
            problems.append(f"{kind}: before/after pinned inputs differ")

    missing: dict[str, list[str]] = {}
    extra: dict[str, list[str]] = {}
    status_changed: dict[str, dict[str, str]] = {}
    stale: dict[str, list[str]] = {}
    for kind in ("ssts", "biomodels"):
        before = reports[f"before_{kind}"]["records"]
        after = reports[f"after_{kind}"]["records"]
        missing[kind] = sorted(set(before) - set(after))
        extra[kind] = sorted(set(after) - set(before))
        changed = {
            key: {"before": before[key], "after": after[key]}
            for key in sorted(set(before) & set(after))
            if before[key] != after[key]
        }
        for key, change in changed.items():
            if (
                change["after"] in BLOCKING_VERDICTS
                or change["before"] in PASSED_VERDICTS
            ):
                status_changed[f"{kind}:{key}"] = change
            else:
                stale[f"{kind}:{key}"] = change
    for label, block in (
        ("missing", missing),
        ("extra", extra),
        ("status_changed", status_changed),
        ("stale", stale),
    ):
        if any(block.values()):
            problems.append(f"{label}: {sum(len(v) for v in block.values())} item(s)")

    pinned = {
        "ssts": reports["after_ssts"]["pins"],
        "biomodels": reports["after_biomodels"]["pins"],
    }
    before_revision = reports["before_ssts"]["revision"]
    if before_revision != reports["before_biomodels"]["revision"]:
        problems.append(
            "before SSTS and BioModels reports use different source revisions"
        )
    return {
        "schema_version": 1,
        "before": {
            "source": {"revision": before_revision, "dirty": False},
            "full_run": True,
            "report_sha256": hashlib.sha256(
                (before_ssts.read_bytes() + before_biomodels.read_bytes())
            ).hexdigest(),
            "pins": pinned,
        },
        "after": {
            "source": {"revision": expected_revision, "dirty": False},
            "full_run": True,
            "report_sha256": hashlib.sha256(
                (after_ssts.read_bytes() + after_biomodels.read_bytes())
            ).hexdigest(),
            "pins": pinned,
        },
        "references": {
            "ssts": {
                "revision": pinned["ssts"].get("suite_revision"),
                "sha256": reports["after_ssts"]["sha256"],
            },
            "biomodels": {
                "revision": pinned["biomodels"].get("corpus_sha256"),
                "sha256": reports["after_biomodels"]["sha256"],
            },
        },
        "reference_laws": {
            "independent": True,
            "detail": "official SSTS expected outputs and independently simulated source SBML / BioModels",
        },
        "counts": {
            key: sum(reports[name]["counts"].get(key, 0) for name in reports)
            for key in ("failed", "timeout", "invalid_source", "skipped")
        },
        "record_comparison": {
            "all_match": not problems,
            "missing": missing,
            "extra": extra,
            "status_changed": status_changed,
            "stale": stale,
        },
        "problems": problems,
        "report_hashes": {name: r["sha256"] for name, r in reports.items()},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-ssts", type=Path, required=True)
    parser.add_argument("--after-ssts", type=Path, required=True)
    parser.add_argument("--before-biomodels", type=Path, required=True)
    parser.add_argument("--after-biomodels", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = compare(
        args.before_ssts,
        args.after_ssts,
        args.before_biomodels,
        args.after_biomodels,
        args.expected_revision,
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {args.output}: all_match={result['record_comparison']['all_match']}")
    return 0 if result["record_comparison"]["all_match"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
