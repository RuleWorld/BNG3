"""Fail-closed consumers for issue #471 release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import yaml


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _artifact_bytes(
    artifact_root: Path, relative_path: Any
) -> tuple[bytes | None, str | None]:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        return None, "artifact path must be a nonempty POSIX relative path"
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        return (
            None,
            "artifact path must not be absolute or contain traversal components",
        )
    root = artifact_root.resolve()
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return None, "artifact path must not traverse symlinks"
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            return None, "artifact path escapes the artifact root"
        if not resolved.is_file():
            return None, "artifact path is not a regular file"
        return resolved.read_bytes(), None
    except OSError as exc:
        return None, f"artifact cannot be read: {exc}"


def _oracle_receipt_errors(
    row: dict[str, Any],
    receipt: dict[str, Any],
    revision: str,
    artifact_root: Path | None,
    root: Path,
) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    row_id = row.get("id", "<missing-id>")
    expected_check = f"release-capability[{row_id}]"
    if receipt.get("schema_version") != 2:
        errors.append(f"{row_id}: receipt schema_version must be 2")
    if receipt.get("kind") != "release-oracle-consumer-receipt":
        errors.append(f"{row_id}: consumer receipt kind is missing")
    if (
        receipt.get("capability_id") != row_id
        or receipt.get("check_id") != expected_check
    ):
        errors.append(f"{row_id}: receipt does not name its exact capability check")
    if (
        receipt.get("source_revision") != revision
        or receipt.get("product_revision") != revision
    ):
        errors.append(f"{row_id}: source and product revisions must equal {revision}")
    oracle = receipt.get("oracle")
    if not isinstance(oracle, dict):
        errors.append(f"{row_id}: named oracle identity is missing")
        oracle = {}
    for key in ("name", "revision", "command"):
        if not isinstance(oracle.get(key), str) or not oracle[key].strip():
            errors.append(f"{row_id}: oracle {key} is missing")
    oracle_execution = oracle.get("execution")
    if not isinstance(oracle_execution, dict):
        errors.append(f"{row_id}: pinned oracle execution record is missing")
        oracle_execution = {}
    for key in ("executable", "version", "command"):
        if not isinstance(oracle_execution.get(key), str) or not oracle_execution[key].strip():
            errors.append(f"{row_id}: oracle execution {key} is missing")
    if type(oracle_execution.get("exit_code")) is not int or oracle_execution.get("exit_code") != 0:
        errors.append(f"{row_id}: pinned oracle did not exit successfully")
    if not _sha256(oracle.get("artifact_sha256")):
        errors.append(f"{row_id}: oracle artifact SHA-256 is invalid")
    origin = oracle.get("expected_origin")
    if origin not in {
        "external-source",
        "analytic-derivation",
        "official-expected-data",
    }:
        errors.append(f"{row_id}: expected answer origin is not independently grounded")
    identity_text = " ".join(
        str(oracle.get(key, "")) for key in ("name", "command", "expected_origin")
    ).casefold()
    if any(
        term in identity_text
        for term in ("bng3-generated", "sut-generated", "self-oracle")
    ):
        errors.append(f"{row_id}: expected answer is identified as SUT-generated")
    errors.extend(_locked_oracle_errors(root, row, oracle))

    producer = receipt.get("producer")
    consumer = receipt.get("consumer")
    if not isinstance(producer, dict) or not isinstance(consumer, dict):
        errors.append(
            f"{row_id}: separate producer and downstream consumer records are required"
        )
        producer, consumer = {}, {}
    for obj, label in ((producer, "producer"), (consumer, "consumer")):
        if not isinstance(obj.get("path"), str) or not obj["path"]:
            errors.append(f"{row_id}: {label} artifact path is missing")
        if not _sha256(obj.get("output_sha256")):
            errors.append(f"{row_id}: {label} output SHA-256 is invalid")
    execution = consumer.get("execution")
    if not isinstance(execution, dict):
        errors.append(f"{row_id}: downstream consumer execution record is missing")
        execution = {}
    for key in ("executable", "version", "command"):
        if not isinstance(execution.get(key), str) or not execution[key].strip():
            errors.append(f"{row_id}: consumer execution {key} is missing")
    if type(execution.get("exit_code")) is not int or execution.get("exit_code") != 0:
        errors.append(f"{row_id}: downstream consumer did not exit successfully")
    if artifact_root is None:
        errors.append(
            f"{row_id}: byte artifacts unavailable; receipt is declaration-only"
        )
        return errors, None

    computed: dict[str, tuple[bytes | None, str | None]] = {}
    for obj, label in (
        (producer, "producer"),
        (oracle, "oracle"),
        (consumer, "consumer"),
    ):
        content, path_error = _artifact_bytes(artifact_root, obj.get("path"))
        computed[label] = (content, path_error)
        if path_error:
            errors.append(f"{row_id}: {label} {path_error}")
            continue
        actual_digest = hashlib.sha256(content).hexdigest()
        expected_digest = (
            oracle.get("artifact_sha256")
            if label == "oracle"
            else obj.get("output_sha256")
        )
        if actual_digest != expected_digest:
            errors.append(
                f"{row_id}: {label} artifact bytes do not match the receipt digest"
            )
    producer_bytes = computed["producer"][0]
    oracle_bytes = computed["oracle"][0]
    consumer_bytes = computed["consumer"][0]
    if producer_bytes is None or oracle_bytes is None or consumer_bytes is None:
        return errors, None
    producer_digest = hashlib.sha256(producer_bytes).hexdigest()
    oracle_digest = hashlib.sha256(oracle_bytes).hexdigest()
    consumer_digest = hashlib.sha256(consumer_bytes).hexdigest()
    if consumer.get("consumed_producer_sha256") != producer_digest:
        errors.append(
            f"{row_id}: consumer execution is not bound to the producer bytes"
        )
    # The owned comparator compares bytes read from the bounded artifact root;
    # the receipt's comparison/result fields are intentionally ignored.
    comparator = {
        "id": "release-oracle-byte-equality-v1",
        "implementation_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "producer_sha256": producer_digest,
        "oracle_sha256": oracle_digest,
        "consumer_sha256": consumer_digest,
        "consumer_equals_oracle": consumer_bytes == oracle_bytes,
    }
    if not comparator["consumer_equals_oracle"]:
        errors.append(
            f"{row_id}: owned byte comparator found consumer output differs from oracle"
        )
    return errors, comparator


def _locked_oracle_errors(
    root: Path, row: dict[str, Any], oracle: dict[str, Any]
) -> list[str]:
    row_id = row.get("id", "<missing-id>")
    try:
        lock = yaml.safe_load(
            (root / "provenance/upstreams.lock.yml").read_text(encoding="utf-8")
        )
    except (OSError, yaml.YAMLError) as exc:
        return [f"{row_id}: pinned upstream lock unavailable: {exc}"]
    if not isinstance(lock, dict) or not isinstance(lock.get("sources"), dict):
        return [f"{row_id}: pinned upstream lock has no sources mapping"]
    source_id = oracle.get("source_id")
    aliases = {
        "bng2": ("bng2",),
        "nfsim": ("nfsim",),
        "pybionetgen": ("pybionetgen",),
        "sbml-test-suite": ("ssts", "sbml test suite"),
        "bngsim": ("bngsim",),
        "bngplayground": ("playground",),
        "rulehub": ("rulehub",),
    }
    if source_id not in aliases:
        return [f"{row_id}: oracle source_id is not a supported pinned source"]
    declaration = str(row.get("oracle", "")).casefold()
    oracle_name = str(oracle.get("name", "")).casefold()
    matching_alias = next(
        (alias for alias in aliases[source_id] if alias in declaration), None
    )
    if matching_alias is None or matching_alias not in oracle_name:
        return [f"{row_id}: receipt oracle does not match the matrix source declaration"]

    oracle_lock = lock.get("oracles", {}).get(source_id)
    source_key = oracle_lock.get("source") if isinstance(oracle_lock, dict) else source_id
    source = lock["sources"].get(source_key)
    expected_revision = source.get("revision") if isinstance(source, dict) else None
    source_status = source.get("status") if isinstance(source, dict) else None
    if not isinstance(expected_revision, str) or not re.fullmatch(
        r"[0-9a-f]{40}", expected_revision
    ):
        return [f"{row_id}: pinned source {source_key} has no full revision"]
    if source_status != "accepted":
        return [f"{row_id}: pinned source {source_key} is not accepted"]
    if oracle.get("revision") != expected_revision:
        return [f"{row_id}: oracle revision does not match pinned source {source_key}"]
    if isinstance(oracle_lock, dict):
        if oracle_lock.get("status") != "locked":
            return [f"{row_id}: oracle {source_id} is not locked"]
        artifact_digest = str(oracle_lock.get("artifact_digest", ""))
        expected_executable = artifact_digest.removeprefix("sha256:")
        if not _sha256(expected_executable) or oracle.get("executable_sha256") != expected_executable:
            return [f"{row_id}: oracle executable digest does not match the pinned lock"]
    return []


def _has_named_oracle(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = value.casefold()
    if "as appropriate" in lowered or re.search(
        r"\b(?:tbd|unknown|none|n/a|oracle needed)\b", lowered
    ):
        return False
    if any(
        term in lowered for term in ("bng3-generated", "sut-generated", "self-oracle")
    ):
        return False
    names = (
        "bng2",
        "nfsim",
        "pybionetgen",
        "ssts",
        "roadrunner",
        "libsbml",
        "jsbml",
        "bngsim",
        "multi specification",
        "analytic",
        "hand-derived",
        "independently authored",
        "independent exact network enumerator",
    )
    return any(name in lowered for name in names)


def _inventory_ids(root: Path) -> list[str]:
    path = root / "docs/CAPABILITY_UNION_INVENTORY.md"
    if not path.is_file():
        raise ValueError("independent capability inventory is missing")
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*([A-Za-z][A-Za-z0-9_.-]*)\s*\|", line)
        if match and match.group(1) != "ID":
            ids.append(match.group(1))
    if not ids:
        raise ValueError("independent capability inventory contains no row IDs")
    return ids


def oracle_independence_report(
    root: Path, receipt_dir: Path, revision: str, artifact_root: Path | None = None
) -> dict[str, Any]:
    """Report declaration coverage separately from exact-revision execution evidence."""
    matrix_path = root / "provenance/capability-matrix.yml"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    rows = matrix.get("rows")
    if not isinstance(rows, list):
        raise ValueError("capability matrix rows must be a list")
    if not rows:
        raise ValueError("capability matrix rows must not be empty")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be a full 40-character commit SHA")
    duplicate_ids: set[str] = set()
    seen: set[str] = set()
    findings: list[str] = []
    comparisons: list[dict[str, Any]] = []
    named = 0
    grounded = 0
    status_counts: dict[str, int] = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or not row.get("id", "").strip()
        ):
            findings.append("matrix contains a row without a stable ID")
            continue
        row_id = row["id"]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", row_id):
            findings.append(f"matrix row ID is unsafe for receipt lookup: {row_id!r}")
            continue
        if row_id in seen:
            duplicate_ids.add(row_id)
        seen.add(row_id)
        status = str(row.get("status", "<missing>"))
        status_counts[status] = status_counts.get(status, 0) + 1
        oracle_decl = row.get("oracle")
        if _has_named_oracle(oracle_decl):
            named += 1
        else:
            findings.append(
                f"{row_id}: oracle declaration does not name an external or analytic source"
            )
        receipt_path = receipt_dir / f"{row_id}.json"
        if not receipt_path.is_file():
            findings.append(f"{row_id}: no exact-revision downstream consumer receipt")
            continue
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(f"{row_id}: consumer receipt cannot be read: {exc}")
            continue
        row_errors, comparator = _oracle_receipt_errors(
            row, receipt, revision, artifact_root, root
        )
        if status != "implemented":
            row_errors.append(
                f"{row_id}: matrix status is {status}; implementation is not qualified"
            )
        if comparator:
            comparisons.append(
                {
                    "capability_id": row_id,
                    "check_result": "pass" if not row_errors else "fail",
                    **comparator,
                }
            )
        if row_errors:
            findings.extend(row_errors)
        else:
            grounded += 1
    findings.extend(
        f"duplicate matrix row ID: {row_id}" for row_id in sorted(duplicate_ids)
    )
    try:
        inventory_id_list = _inventory_ids(root)
    except (OSError, ValueError) as exc:
        inventory_id_list = []
        findings.append(f"independent capability inventory invalid: {exc}")
    inventory_ids = set(inventory_id_list)
    inventory_duplicates = sorted(
        value for value in inventory_ids if inventory_id_list.count(value) > 1
    )
    findings.extend(
        f"duplicate independent inventory row ID: {row_id}"
        for row_id in inventory_duplicates
    )
    matrix_ids = seen
    if matrix_ids != inventory_ids:
        findings.append(
            "matrix/inventory ID coverage mismatch: "
            f"matrix-only={sorted(matrix_ids - inventory_ids)[:10]} "
            f"inventory-only={sorted(inventory_ids - matrix_ids)[:10]}"
        )
    return {
        "schema_version": 1,
        "check_id": "release-oracle-independence",
        "revision": revision,
        "row_count": len(rows),
        "evidence_scope": (
            "ARTIFACT_CHECKS_ENABLED" if artifact_root else "DECLARATION_ONLY"
        ),
        "named_oracle_rows": named,
        "grounded_execution_rows": grounded,
        "owned_comparisons": comparisons,
        "source_status_counts": status_counts,
        "findings": findings,
        "result": "pass" if not findings and grounded == len(rows) else "fail",
    }


def topology_errors(
    workflow: dict[str, Any], independent_groups: list[list[str]]
) -> list[str]:
    """Check declared parallel job groups and unconditional partial-artifact uploads."""
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return ["workflow has no jobs"]
    errors: list[str] = []
    for group in independent_groups:
        for job_name in group:
            if job_name not in jobs:
                errors.append(f"independent job is missing: {job_name}")
        for left_index, left in enumerate(group):
            if left not in jobs:
                continue
            for right in group[left_index + 1 :]:
                if right not in jobs:
                    continue
                for dependent, other in ((left, right), (right, left)):
                    needs = jobs[dependent].get("needs", [])
                    needs = [needs] if isinstance(needs, str) else needs
                    if other in needs:
                        errors.append(
                            f"independent jobs are serialized: {other} -> {dependent}"
                        )
    for job_name, job in jobs.items():
        for step in job.get("steps", []) if isinstance(job, dict) else []:
            if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                condition = str(step.get("if", ""))
                if "always()" not in condition:
                    errors.append(
                        f"{job_name}: artifact upload does not run after failure"
                    )
    return errors


def check_workflow_topology(path: Path) -> dict[str, Any]:
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    groups = [["bng2-parity", "nfsim-parity", "pybionetgen-compat"]]
    errors = topology_errors(workflow, groups)
    # These jobs share source-lock validation but their scientific checks are independent.
    expected_needs = {name: ["oracle-lock"] for name in groups[0]}
    for name, expected in expected_needs.items():
        needs = workflow["jobs"].get(name, {}).get("needs", [])
        observed = [needs] if isinstance(needs, str) else needs
        if observed != expected:
            errors.append(f"{name}: needs must be {expected}, observed {observed}")
    required_workflows = [
        "ci.yml",
        "parity.yml",
        "sbml-conformance.yml",
        "weekly.yml",
        "formal.yml",
        "codeql.yml",
        "autofix.yml",
        "release.yml",
        "issue-acceptance.yml",
        "issue-472-docs-acceptance.yml",
        "regenerate-bng2-ensembles.yml",
        "release-policy.yml",
    ]
    return {
        "schema_version": 1,
        "check_id": "release-ci-topology",
        "workflow": str(path),
        "independent_jobs": groups[0],
        "static_result": "pass" if not errors else "fail",
        "acceptance_result": "fail",
        "coverage": [path.name],
        "required_workflow_coverage": required_workflows,
        "acceptance_gaps": [
            "all maintained workflows and every job have not been audited",
            "no interrupted-run replay receipt was consumed",
        ],
        "errors": errors,
        "result": "fail",
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="check", required=True)
    oracle = sub.add_parser("oracle")
    oracle.add_argument("--root", type=Path, default=Path.cwd())
    oracle.add_argument("--receipts", type=Path, required=True)
    oracle.add_argument("--artifacts", type=Path)
    oracle.add_argument("--revision", required=True)
    oracle.add_argument("--report", type=Path, required=True)
    topology = sub.add_parser("topology")
    topology.add_argument(
        "--workflow", type=Path, default=Path(".github/workflows/parity.yml")
    )
    topology.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.check == "oracle":
        report = oracle_independence_report(
            args.root, args.receipts, args.revision, args.artifacts
        )
    else:
        report = check_workflow_topology(args.workflow)
    write_report(report, args.report)
    print(
        json.dumps(
            {
                key: report[key]
                for key in report
                if key
                in {
                    "check_id",
                    "result",
                    "row_count",
                    "grounded_execution_rows",
                    "static_result",
                    "acceptance_result",
                    "errors",
                }
            },
            sort_keys=True,
        )
    )
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
