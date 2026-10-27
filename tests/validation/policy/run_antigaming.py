"""Command line entry point used by PR and scheduled CI policy jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from antigaming import CHECK_IDS, fresh_seed, generate_seeded_case, run_pr_checks, run_product_mutations, verify_mutation_ratchet, verify_seed_manifest, write_seed_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("BASE_REVISION", ""))
    parser.add_argument("--head", default=os.environ.get("HEAD_REVISION", "HEAD"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--seed-manifest", type=Path)
    parser.add_argument("--mutation-output", type=Path)
    parser.add_argument("--mutation-report", type=Path)
    parser.add_argument("--mutation-baseline", type=Path)
    parser.add_argument("--expected-mutation-revision")
    parser.add_argument("--check", action="append", choices=CHECK_IDS)
    args = parser.parse_args()
    root = args.root.resolve()
    checks = set(args.check or CHECK_IDS)
    errors: dict[str, list[str]] = {}
    if "release-protected-expectations" in checks or "release-no-product-fixture-names" in checks:
        result = run_pr_checks(root, args.base, args.head)
        errors.update({key: value for key, value in result.items() if key in checks and value})
    if "release-independent-seeds" in checks:
        if args.seed_manifest is None:
            errors["release-independent-seeds"] = ["--seed-manifest is required; generated-case seeds must be recorded"]
        else:
            revision = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=root, text=True).strip()
            seed = fresh_seed()
            case_id, source = generate_seeded_case(seed)
            case_path = args.seed_manifest.with_suffix(".bngl")
            case_path.parent.mkdir(parents=True, exist_ok=True)
            case_path.write_text(source)
            write_seed_manifest(args.seed_manifest, seed=seed, revision=revision, case_ids=[case_id], case_sha256=hashlib.sha256(source.encode()).hexdigest())
            try:
                verify_seed_manifest(args.seed_manifest, revision)
                import importlib.util
                extension = importlib.util.find_spec("bionetgen._bionetgen_cpp")
                default_engine = Path(extension.origin).parent / "bng_cpp" if extension and extension.origin else root / "build/cpp/bng_cpp"
                engine = Path(os.environ.get("BNG_CPP", default_engine)).resolve()
                if not engine.is_file():
                    raise FileNotFoundError(f"native BNG3 CLI is unavailable: {engine}")
                proc = subprocess.run((str(engine), str(case_path)), cwd=case_path.parent, capture_output=True, text=True, timeout=120)
                if proc.returncode != 0 or not list(case_path.parent.glob("*.gdat")):
                    raise RuntimeError(f"generated source execution failed (exit={proc.returncode}): {(proc.stdout + proc.stderr)[-2000:]}")
            except Exception as exc:
                errors["release-independent-seeds"] = [f"seeded generated source case did not execute: {type(exc).__name__}: {exc}"]
            print(f"seed manifest: {args.seed_manifest}")
    if "release-scheduled-mutation-ratchet" in checks:
        try:
            if args.mutation_report is not None:
                report_path = args.mutation_report
            elif args.mutation_output is not None:
                report = run_product_mutations(root, args.mutation_output)
                report_path = args.mutation_output
            else:
                raise ValueError("--mutation-output or --mutation-report is required")
            baseline_path = args.mutation_baseline or (root / "tests/validation/policy/mutation-baseline.json")
            expected_revision = args.expected_mutation_revision or subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=root, text=True).strip()
            mutation_errors = verify_mutation_ratchet(report_path, baseline_path, expected_revision)
            if mutation_errors:
                errors["release-scheduled-mutation-ratchet"] = mutation_errors
            report = json.loads(report_path.read_text())
            print(f"mutation score: {report.get('caught', 0)}/{report.get('denominator', 0)}")
        except Exception as exc:
            errors["release-scheduled-mutation-ratchet"] = [f"mutation campaign/ratchet infrastructure error: {type(exc).__name__}: {exc}"]
    for check in sorted(checks):
        if errors.get(check):
            print(f"FAIL {check}: {'; '.join(errors[check])}")
        else:
            label = "BOOTSTRAP SETUP (not base-revision PASS)" if os.environ.get("ANTIGAMING_BOOTSTRAP") == "1" else "PASS"
            print(f"{label} {check}")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
