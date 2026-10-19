"""Budgeted reduction of recorded bounded-network mismatches, opt-in only.

Only complete single-line reaction rules are removable. Both engines must
produce parseable networks with the same mismatch category on each accepted
reduction. This produces a smaller reproducer, never a root-cause assertion.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import campaign, inventory
from .compare import compare_net, parse_net

ROOT = Path(__file__).resolve().parents[2]


def verify_report_source(report, repository_root):
    """Require the report's exact clean checkout before reducing its evidence."""
    source = report.get("source")
    if not isinstance(source, dict) or source.get("dirty") is not False:
        raise ValueError("report source must explicitly record dirty=false")
    revision = source.get("revision")
    if (
        not isinstance(revision, str)
        or len(revision) != 40
        or any(char not in "0123456789abcdef" for char in revision.lower())
    ):
        raise ValueError("report source revision is missing or malformed")
    if report.get("input_changes_during_run") != []:
        raise ValueError("report has input changes during run or lacks clean evidence")
    current = campaign.git(repository_root, "rev-parse", "HEAD")
    if current != revision:
        raise ValueError(f"report source revision {revision} != current {current}")
    if campaign.git(
        repository_root, "status", "--porcelain", "--untracked-files=normal"
    ):
        raise ValueError("source checkout is dirty")
    return revision


def _resolve_receipt(receipt_path, report_dir):
    path = Path(receipt_path)
    candidates = [report_dir / path] if not path.is_absolute() else [path]
    if path.is_absolute():
        # Hosted reports preserve runner-absolute paths. The report tree stores
        # the corresponding artifact under the standard models/<case>/... path.
        parts = path.parts
        for index in range(len(parts) - 3):
            if parts[index] == "models":
                candidates.append(report_dir.joinpath(*parts[index:]))
                break
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def verify_recorded_input(row, report_dir, source, subject_binary=None):
    """Match the staged model bytes to the subject command's retained receipt."""
    receipts = row.get("receipts", [])
    if not isinstance(receipts, list):
        raise ValueError("failure row has no recorded subject receipt list")
    for receipt_path in receipts:
        if not isinstance(receipt_path, str):
            continue
        path = _resolve_receipt(receipt_path, report_dir)
        if path is None or "subject" not in path.parts:
            continue
        try:
            receipt = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot load recorded subject receipt: {exc}") from exc
        if not isinstance(receipt, dict) or receipt.get("status") != "PASS":
            raise ValueError("recorded subject command did not pass")
        command = receipt.get("command")
        artifacts = receipt.get("artifacts")
        if (
            not isinstance(command, list)
            or not command
            or not isinstance(artifacts, list)
        ):
            raise ValueError("recorded subject receipt lacks command artifacts")
        if subject_binary is not None and command[0] != subject_binary:
            raise ValueError("recorded subject receipt uses a different binary")
        input_arg = command[-1]
        if not isinstance(input_arg, str) or Path(input_arg).name != source.name:
            raise ValueError("recorded subject receipt names a different model input")
        matches = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, dict) and artifact.get("path") == input_arg
        ]
        if not matches:
            raise ValueError("recorded subject receipt has no recorded model digest")
        if len(matches) != 1:
            raise ValueError(
                "recorded subject receipt has no unique model input digest"
            )
        digest = matches[0].get("sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest.lower())
        ):
            raise ValueError("recorded subject receipt has no recorded model digest")
        if inventory.sha256(source) != digest.lower():
            raise ValueError("original model does not match recorded subject input")
        return digest.lower()
    raise ValueError("recorded subject input receipt is unavailable")


def minimization_hashes(original, candidate):
    return {
        "original_model_sha256": inventory.sha256(original),
        "candidate_model_sha256": inventory.sha256(candidate),
    }


def input_evidence_row(report, aggregate_row, case):
    """Use the failing named contract row, which retains the command receipts."""
    if aggregate_row.get("receipts"):
        return aggregate_row
    target = aggregate_row.get("first_observed_divergence")
    return next(
        (
            row
            for row in report.get("results", [])
            if row.get("id") == target
            and row.get("model") == case
            and row.get("status") == "FAIL"
            and row.get("receipts")
        ),
        aggregate_row,
    )


def ddmin(items, reproduces, *, max_attempts=24):
    if max_attempts < 1:
        raise ValueError("attempt budget must be positive")
    if not reproduces(items):
        raise ValueError("original case does not reproduce")
    attempts, partitions = 1, 2
    kept = list(items)
    while kept and attempts < max_attempts:
        size = max(1, (len(kept) + partitions - 1) // partitions)
        reduced = False
        for start in range(0, len(kept), size):
            candidate = kept[:start] + kept[start + size :]
            attempts += 1
            if reproduces(candidate):
                kept, partitions, reduced = candidate, max(2, partitions - 1), True
                break
            if attempts >= max_attempts:
                break
        if not reduced:
            if partitions >= len(kept):
                break
            partitions = min(len(kept), partitions * 2)
    return kept


def reduce_verified(items, reproduces, *, max_attempts=24):
    """Reserve a fresh final confirmation; never label an intermittent candidate minimal."""
    if max_attempts < 3:
        raise ValueError("verified reduction needs at least three attempts")
    attempts = 0

    def predicate(candidate):
        nonlocal attempts
        attempts += 1
        return reproduces(candidate)

    kept = ddmin(items, predicate, max_attempts=max_attempts - 1)
    verified = predicate(kept)
    return {"kept": kept, "verified": verified, "attempts": attempts}


def _signature(diff):
    """Preserve actual divergent identities/rates, not just a count category.

    Removing an unrelated rule may alter total counts, so retain deltas alongside
    exact differing species/reactions/groups. This conservative identity can
    reject useful reductions; that is preferable to changing the failure.
    """
    if diff.ok:
        return "equal"
    return json.dumps(
        {
            "species_delta": diff.n_species_test - diff.n_species_ref,
            "reaction_delta": diff.n_reactions_test - diff.n_reactions_ref,
            "species_only_ref": sorted(diff.species_only_ref),
            "species_only_test": sorted(diff.species_only_test),
            "reactions_only_ref": sorted(diff.reactions_only_ref),
            "reactions_only_test": sorted(diff.reactions_only_test),
            "groups_only_ref": sorted(diff.groups_only_ref),
            "groups_only_test": sorted(diff.groups_only_test),
            "groups_changed": sorted(diff.groups_changed),
            "groups_renamed": sorted(diff.groups_renamed),
            "initial_amounts_changed": sorted(diff.initial_amounts_changed),
        },
        sort_keys=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--case", required=True, help="model stem of a recorded network mismatch"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=24)
    parser.add_argument("--seconds", type=float, default=120)
    args = parser.parse_args()
    if not (3 <= args.attempts <= 96 and 0 < args.seconds <= 300):
        parser.error("minimization requires 3..96 attempts and 0..300 seconds")
    if Path(args.case).name != args.case or args.case in {".", ".."}:
        parser.error("case must be a model stem")
    deadline = time.monotonic() + args.seconds
    report = json.loads(args.report.read_text())
    row = next(
        (r for r in report["results"] if r["id"] == args.case + ":network"), None
    )
    if not row or row["status"] != "FAIL" or row["stage"] != "bounded-network":
        parser.error("case must be a recorded bounded-network mismatch")
    try:
        verify_report_source(report, ROOT)
    except (KeyError, ValueError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    original = args.report.parent / "models" / args.case
    source_dir = original / "input"
    source_files = sorted(source_dir.glob("*.bngl"))
    if len(source_files) != 1:
        parser.error("case must contain exactly one staged BNGL source")
    source = source_files[0]
    try:
        evidence_row = input_evidence_row(report, row, args.case)
        recorded_input_sha256 = verify_recorded_input(
            evidence_row, args.report.parent, source, report["subject"]["binary"]
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    subject = Path(report["subject"]["binary"])
    campaign.verify_digest(subject, report["subject"]["sha256"])
    reference = report["references"]["bionetgen"]
    campaign.verify_source(Path(reference["path"]), reference)
    campaign.verify_digest(Path(reference["script"]), reference["script_sha256"])
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output directory must be empty")
    args.output.mkdir(parents=True, exist_ok=True)
    lines = source.read_text().splitlines(keepends=True)
    removable, in_rules = [], False
    for index, line in enumerate(lines):
        text = line.strip().lower()
        if text.startswith("begin reaction rules"):
            in_rules = True
        elif text.startswith("end reaction rules"):
            in_rules = False
        elif in_rules and "->" in line and not line.rstrip().endswith("\\"):
            removable.append(index)
    attempts, expected_signature = [], None
    env = os.environ.copy()
    env["BNGPATH"] = str(Path(reference["script"]).parent)

    def reproduces(kept):
        nonlocal expected_signature
        if time.monotonic() >= deadline:
            return False
        attempt_dir = args.output / f"attempt-{len(attempts):03}"
        text = "".join(
            line for i, line in enumerate(lines) if i not in removable or i in kept
        )
        networks = []
        attempt = {"kept_rule_lines": kept, "accepted": False}
        attempts.append(attempt)
        for label in ("reference", "subject"):
            work = attempt_dir / label
            shutil.copytree(source_dir, work)
            model = work / source.name
            model.write_text(text)
            command = (
                [
                    "perl",
                    reference["script"],
                    "--outdir",
                    str(work.resolve()),
                    str(model.resolve()),
                ]
                if label == "reference"
                else [str(subject), str(model.resolve())]
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                attempt["budget_exhausted"] = True
                return False
            receipt = campaign.run_command(
                command,
                work,
                min(report["configuration"]["case_timeout"], remaining),
                required=[source.stem + ".net"],
                env=env,
            )
            if receipt["status"] != "PASS":
                return False
            network = parse_net(work / (source.stem + ".net"))
            if network is None:
                return False
            networks.append(network)
        signature = _signature(compare_net(*networks, compare_initial_amounts=True))
        if expected_signature is None:
            expected_signature = signature
        attempt["signature"] = signature
        attempt["accepted"] = signature != "equal" and signature == expected_signature
        return attempt["accepted"]

    reduction = reduce_verified(removable, reproduces, max_attempts=args.attempts)
    kept = reduction["kept"]
    name = "reproducer.bngl" if reduction["verified"] else "unverified-candidate.bngl"
    (args.output / name).write_text(
        "".join(line for i, line in enumerate(lines) if i not in removable or i in kept)
    )
    hashes = minimization_hashes(source, args.output / name)
    (args.output / "minimization.json").write_text(
        json.dumps(
            {
                "parent_report_sha256": inventory.sha256(args.report),
                **hashes,
                "recorded_subject_input_sha256": recorded_input_sha256,
                "attempts": attempts,
                "verified": reduction["verified"],
                "signature": expected_signature,
                "seconds_budget": args.seconds,
                "claim": "same detailed observed mismatch; root cause unconfirmed; final replay required; reduction bounded by rule-line, attempt and time limits",
            },
            indent=2,
        )
        + "\n"
    )
    return 0 if reduction["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
