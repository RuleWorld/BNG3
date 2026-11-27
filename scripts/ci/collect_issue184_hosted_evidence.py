"""Collect exact-revision hosted CI/Parity/SBML/Weekly artifacts for #184 evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci import record_issue184_candidate as cand_mod  # noqa: E402


def _gh_api(endpoint: str, *, paginate: bool = False) -> Any | None:
    cmd = ["gh", "api"]
    if paginate:
        cmd.extend(["--paginate", "--slurp"])
    cmd.append(endpoint)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _gh_download(repo: str, run_id: int, artifact_name: str, dest: Path) -> bool:
    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "gh",
            "run",
            "download",
            str(run_id),
            "-R",
            repo,
            "-n",
            artifact_name,
            "--dir",
            str(dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def _flatten_runs(payload: Any, sha: str) -> list[dict[str, Any]]:
    pages = payload if isinstance(payload, list) else ([payload] if payload else [])
    return [
        run
        for page in pages
        if isinstance(page, dict)
        for run in (page.get("workflow_runs") or [])
        if isinstance(run, dict) and run.get("head_sha") == sha
    ]


def _latest_run(
    runs: list[dict[str, Any]], name: str, events: tuple[str, ...]
) -> dict[str, Any] | None:
    matches = [
        r
        for r in runs
        if r.get("name") == name
        and r.get("event") in events
        and r.get("head_branch") in (None, "main")
        and r.get("status") == "completed"
        and r.get("conclusion") == "success"
    ]
    if not matches:
        return None
    return max(matches, key=lambda r: (r.get("run_number", 0), r.get("id", 0)))


def _resolve_issue137_receipt(
    root: Path,
    sha: str,
    release_records_dir: Path | None,
    out_dir: Path,
) -> Path | None:
    """Prefer the combined #137 inventory report over partial standalone receipts."""
    if not release_records_dir or not release_records_dir.is_dir():
        return None
    combined = release_records_dir / "issue137-inventory-combined" / "report.json"
    if combined.is_file():
        return combined
    case_reports: list[Path] = []
    for pattern in (
        "issue137-*/structural-cases.json",
        "issue137-*/bng2-cases.json",
        "issue137-*/nfsim-cases.json",
        "issue137-*/pybionetgen-cases.json",
    ):
        case_reports.extend(sorted(release_records_dir.glob(pattern)))
    if not case_reports:
        return None
    check_script = (
        root
        / "tests"
        / "validation"
        / "release"
        / "cases"
        / "issue-137"
        / "issue137_checks.py"
    )
    if not check_script.is_file():
        return None
    synthesized = out_dir / "issue137-combined-report.json"
    cmd = [
        sys.executable,
        str(check_script),
        "inventory",
        "--root",
        str(root),
        "--revision",
        sha,
        "--report",
        str(synthesized),
    ]
    for case_report in case_reports:
        cmd.extend(["--case-report", str(case_report)])
    subprocess.run(cmd, check=False)
    return synthesized if synthesized.is_file() else None


def _discover_scientific_receipts(
    release_records_dir: Path | None,
    extra_receipts: list[Path],
    sbml_dir: Path,
    *,
    issue137_combined_receipt: Path | None = None,
) -> list[Path]:
    found: list[Path] = []
    if issue137_combined_receipt is not None and issue137_combined_receipt.is_file():
        found.append(issue137_combined_receipt)
    if release_records_dir and release_records_dir.is_dir():
        patterns = [
            "issue171-release-record-*/issue-171.json",
            "issue172-release-record-*/issue-172.json",
            "issue174-cpu-benchmark-*/issue174-benchmark-record.json",
            "issue176-cpu-ensemble-*/issue-176-release-report.json",
            "issue178-shared-decisions-release-*/issue-178-release-report.json",
            "issue181-corpus-*/report.json",
            "issue181-corpus-*/issue181-corpus/report.json",
            "issue186-release-record-*/issue-186.json",
            "issue471-acceptance-*/report.json",
            "issue471-acceptance-*/issue471-acceptance/report.json",
            "issue142-release-obligation-142-*/release-obligation-142.json",
            "issue152-energy-protocol-release-*/issue-152-release-report.json",
            "eq-catalogue-*/report.json",
        ]
        if issue137_combined_receipt is None:
            patterns.insert(0, "issue137-inventory-*/report.json")
        for pattern in patterns:
            found.extend(sorted(release_records_dir.glob(pattern)))
    for p in extra_receipts:
        if p.is_file():
            found.append(p)
    for p in sorted(sbml_dir.rglob("issue*-release-receipt.json")):
        found.append(p)
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in found:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(rp)
    return unique


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--repo", default="RuleWorld/BNG3")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--release-records", type=Path, default=None)
    parser.add_argument(
        "--extra-scientific-receipt", type=Path, action="append", default=[]
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    sha = args.revision

    push_raw = _gh_api(
        f"repos/{args.repo}/actions/runs?head_sha={sha}&branch=main&event=push&per_page=100",
        paginate=True,
    )
    disp_raw = _gh_api(
        f"repos/{args.repo}/actions/runs?head_sha={sha}&branch=main&event=workflow_dispatch&per_page=100",
        paginate=True,
    )
    weekly_raw = _gh_api(
        f"repos/{args.repo}/actions/workflows/weekly.yml/runs?head_sha={sha}&branch=main&per_page=100",
        paginate=True,
    )

    all_runs = (
        _flatten_runs(push_raw, sha)
        + _flatten_runs(disp_raw, sha)
        + _flatten_runs(weekly_raw, sha)
    )
    runs_json = out_dir / "hosted-runs.json"
    runs_json.write_text(
        json.dumps({"workflow_runs": all_runs}, indent=2) + "\n", encoding="utf-8"
    )

    ci_run = _latest_run(all_runs, "CI", ("push", "workflow_dispatch"))
    sbml_run = _latest_run(
        all_runs, "Official SBML conformance subset", ("workflow_dispatch",)
    )
    weekly_run = _latest_run(
        all_runs, "Weekly Validation", ("schedule", "workflow_dispatch")
    )

    ci_jobs_json = out_dir / "ci-jobs.json"
    wheel_dirs: list[Path] = []
    sdist_path: Path | None = None
    asan_junits: list[Path] = []
    asan_receipt: Path | None = None
    install_receipts: list[Path] = []

    if ci_run is not None:
        ci_id = int(ci_run["id"])
        jobs_raw = _gh_api(
            f"repos/{args.repo}/actions/runs/{ci_id}/jobs?per_page=100", paginate=True
        )
        jobs_list = [
            j
            for page in (
                jobs_raw
                if isinstance(jobs_raw, list)
                else ([jobs_raw] if jobs_raw else [])
            )
            if isinstance(page, dict)
            for j in (page.get("jobs") or [])
            if isinstance(j, dict)
        ]
        ci_jobs_json.write_text(
            json.dumps({"jobs": jobs_list}, indent=2) + "\n", encoding="utf-8"
        )
        ci_arts_dir = out_dir / "ci-artifacts"
        for wheel_art in (
            "wheels-ubuntu-22.04",
            "wheels-ubuntu-24.04-arm",
            "wheels-macos-15-intel",
            "wheels-macos-15",
            "wheels-windows-2022",
        ):
            dest = ci_arts_dir / wheel_art
            if _gh_download(args.repo, ci_id, wheel_art, dest):
                wheel_dirs.append(dest)
        sdist_dir = ci_arts_dir / "sdist"
        if _gh_download(args.repo, ci_id, "sdist", sdist_dir):
            found_sdist = sorted(sdist_dir.glob("*.tar.gz"))
            if found_sdist:
                sdist_path = found_sdist[0]
        asan_dir = ci_arts_dir / f"asan-results-{sha}"
        if _gh_download(args.repo, ci_id, f"asan-results-{sha}", asan_dir):
            asan_junits = sorted(asan_dir.glob("*.xml"))
            cand_rec = asan_dir / "asan-receipt.json"
            if cand_rec.is_file():
                asan_receipt = cand_rec
        for plat_art in (
            f"issue184-install-receipt-ubuntu-22.04-{sha}",
            f"issue184-install-receipt-ubuntu-24.04-arm-{sha}",
            f"issue184-install-receipt-macos-15-{sha}",
            f"issue184-install-receipt-windows-2022-{sha}",
            f"issue184-install-receipt-sdist-{sha}",
            f"issue184-install-receipt-macos-15-intel-{sha}",
        ):
            dest = ci_arts_dir / plat_art
            if _gh_download(args.repo, ci_id, plat_art, dest):
                install_receipts.extend(sorted(dest.glob("*.json")))

    sbml_dir = out_dir / "sbml-artifacts"
    if sbml_run is not None:
        sbml_id = int(sbml_run["id"])
        attempt = int(sbml_run.get("run_attempt", 1))
        _gh_download(
            args.repo,
            sbml_id,
            f"ssts-release-consumers-{sha}-{attempt}",
            sbml_dir / "ssts",
        )
        _gh_download(
            args.repo,
            sbml_id,
            f"curated-biomodels-{sha}-{attempt}",
            sbml_dir / "biomodels",
        )

    mutation_report: Path | None = None
    if weekly_run is not None:
        w_id = int(weekly_run["id"])
        mut_dir = out_dir / "weekly-mutation"
        if _gh_download(
            args.repo, w_id, f"release-product-mutation-ratchet-{sha}", mut_dir
        ):
            cand_mut = mut_dir / "mutation-report.json"
            if cand_mut.is_file():
                mutation_report = cand_mut

    issue137_combined = _resolve_issue137_receipt(
        root, sha, args.release_records, out_dir
    )
    sci_receipts = _discover_scientific_receipts(
        args.release_records,
        args.extra_scientific_receipt,
        sbml_dir,
        issue137_combined_receipt=issue137_combined,
    )
    bench_report = next(
        (p for p in sci_receipts if p.name == "issue174-benchmark-record.json"), None
    )
    cur_bench = (
        bench_report.parent / "issue174-current-benchmark.json"
        if bench_report is not None
        and (bench_report.parent / "issue174-current-benchmark.json").is_file()
        else None
    )

    cand_report = out_dir / "candidate-report.json"
    cand_argv = [
        "--root",
        str(root),
        "--revision",
        sha,
        "--runs-json",
        str(runs_json),
        "--report",
        str(cand_report),
    ]
    for wd in wheel_dirs:
        cand_argv.extend(["--wheel-dir", str(wd)])
    if sdist_path is not None:
        cand_argv.extend(["--sdist", str(sdist_path)])
    if bench_report is not None:
        cand_argv.extend(["--benchmark-report", str(bench_report)])
    if cur_bench is not None:
        cand_argv.extend(["--current-benchmark-report", str(cur_bench)])
    for jp in asan_junits:
        cand_argv.extend(["--asan-junit", str(jp)])
    if asan_receipt is not None:
        cand_argv.extend(["--asan-receipt", str(asan_receipt)])
    if ci_jobs_json.is_file():
        cand_argv.extend(["--ci-jobs-json", str(ci_jobs_json)])
    if mutation_report is not None:
        cand_argv.extend(["--mutation-report", str(mutation_report)])
    for ir in install_receipts:
        cand_argv.extend(["--install-receipt", str(ir)])
    cand_mod.main(cand_argv)

    cpu_script = (
        root
        / "tests"
        / "validation"
        / "release"
        / "cases"
        / "issue-184"
        / "cpu_release_checks.py"
    )
    final_report = out_dir / "report.json"
    cpu_cmd = [
        sys.executable,
        str(cpu_script),
        "--root",
        str(root),
        "--revision",
        sha,
        "--candidate-report",
        str(cand_report),
        "--report",
        str(final_report),
    ]
    for sr in sci_receipts:
        cpu_cmd.extend(["--scientific-receipt", str(sr)])
    for ir in install_receipts:
        cpu_cmd.extend(["--install-receipt", str(ir)])
    proc = subprocess.run(cpu_cmd, check=False)

    if args.release_records and final_report.is_file():
        for stale in args.release_records.glob("issue184-cpu-release-*/report.json"):
            stale.unlink(missing_ok=True)
        dest_dir = args.release_records / "issue184-cpu-release-combined"
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final_report, dest_dir / "report.json")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
