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
import time
from pathlib import Path

from . import campaign, inventory
from .compare import compare_net, parse_net


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
    deadline = time.monotonic() + args.seconds
    report = json.loads(args.report.read_text())
    row = next(
        (r for r in report["results"] if r["id"] == args.case + ":network"), None
    )
    if not row or row["status"] != "FAIL" or row["stage"] != "bounded-network":
        parser.error("case must be a recorded bounded-network mismatch")
    original = args.report.parent / "models" / args.case
    source_dir = original / "input"
    source = next(source_dir.glob("*.bngl"))
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
    (args.output / "minimization.json").write_text(
        json.dumps(
            {
                "parent_report_sha256": inventory.sha256(args.report),
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
