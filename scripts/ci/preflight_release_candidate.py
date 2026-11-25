"""Repeatable, non-publishing release preflight CLI for BNG3 candidates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.qualify_release_candidate import (  # noqa: E402
    REQUIRED_WORKFLOWS,
    qualify_sbml_runs,
    qualify_workflow_runs,
)

REQUIRED_WHEEL_ARTIFACTS = (
    "wheels-ubuntu-22.04",
    "wheels-macos-15-intel",
    "wheels-macos-15",
    "wheels-windows-2022",
)
TRACKED_RELEASE_ISSUES = (137, 180, 181, 471, 184, 474)


def _load_cpu_release_checks(root: Path) -> Any:
    path = (
        root
        / "tests"
        / "validation"
        / "release"
        / "cases"
        / "issue-184"
        / "cpu_release_checks.py"
    )
    spec = importlib.util.spec_from_file_location("_bng3_cpu_release_checks", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_cmd(
    cmd: list[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _gh_api_json(endpoint: str, *, paginate: bool = False) -> Any:
    cmd = ["gh", "api"]
    if paginate:
        cmd.extend(["--paginate", "--slurp"])
    cmd.append(endpoint)
    proc = _run_cmd(cmd)
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh api failed for {endpoint}: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return json.loads(proc.stdout)


def _flatten_artifacts(payload: Any) -> list[dict[str, Any]]:
    pages = payload if isinstance(payload, list) else [payload]
    items: list[dict[str, Any]] = []
    for page in pages:
        if isinstance(page, dict) and isinstance(page.get("artifacts"), list):
            items.extend(a for a in page["artifacts"] if isinstance(a, dict))
    return items


def _download_artifact(
    repo: str, run_id: int, name: str, dest: Path
) -> tuple[bool, str]:
    dest.mkdir(parents=True, exist_ok=True)
    proc = _run_cmd(
        [
            "gh",
            "run",
            "download",
            str(run_id),
            "-R",
            repo,
            "-n",
            name,
            "--dir",
            str(dest),
        ]
    )
    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip()
    return True, ""


def _load_json_or_fetch(
    path: Path | None, endpoint: str, cache_path: Path, *, paginate: bool = True
) -> Any:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    data = _gh_api_json(endpoint, paginate=paginate)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def _load_explicit_runs(path: Path | None) -> dict[int, dict[str, Any]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, dict[str, Any]] = {}
    for key, value in raw.items():
        out[int(key)] = value
    return out


def _get_run_and_artifacts(
    repo: str,
    run_id: int,
    explicit_runs: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if run_id in explicit_runs:
        entry = explicit_runs[run_id]
        run_meta = entry["run"] if "run" in entry else entry
        artifacts = entry.get("artifacts", [])
        return run_meta, artifacts
    run_meta = _gh_api_json(f"repos/{repo}/actions/runs/{run_id}", paginate=False)
    artifacts = _flatten_artifacts(
        _gh_api_json(
            f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100", paginate=True
        )
    )
    return run_meta, artifacts


def _evaluate_run_record(
    label: str,
    expected_name: str,
    expected_sha: str,
    allowed_events: tuple[str, ...],
    run_meta: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    artifact_map = {
        a["name"]: {
            "id": a.get("id"),
            "size_in_bytes": a.get("size_in_bytes"),
            "digest": a.get("digest"),
        }
        for a in artifacts
        if "name" in a
    }
    issues: list[str] = []
    if run_meta.get("name") and run_meta.get("name") != expected_name:
        issues.append(
            f"{label} run {run_meta.get('id')} workflow is {run_meta.get('name')!r}, expected {expected_name!r}"
        )
    if run_meta.get("head_sha") != expected_sha:
        issues.append(
            f"{label} run {run_meta.get('id')} head_sha {run_meta.get('head_sha')} != {expected_sha}"
        )
    if run_meta.get("head_branch") not in (None, "main"):
        issues.append(
            f"{label} run {run_meta.get('id')} head_branch {run_meta.get('head_branch')!r} != 'main'"
        )
    if run_meta.get("event") not in allowed_events:
        issues.append(
            f"{label} run {run_meta.get('id')} event {run_meta.get('event')!r} not in {allowed_events}"
        )
    if run_meta.get("status") != "completed" or run_meta.get("conclusion") != "success":
        issues.append(
            f"{label} run {run_meta.get('id')} status={run_meta.get('status')!r} conclusion={run_meta.get('conclusion')!r}"
        )
    return {
        "run_id": run_meta.get("id"),
        "run_attempt": run_meta.get("run_attempt", 1),
        "workflow": run_meta.get("name", expected_name),
        "head_sha": run_meta.get("head_sha"),
        "head_branch": run_meta.get("head_branch"),
        "event": run_meta.get("event"),
        "status": run_meta.get("status"),
        "conclusion": run_meta.get("conclusion"),
        "html_url": run_meta.get("html_url"),
        "artifacts": artifact_map,
        "issues": issues,
        "passed": not issues,
    }


def _check_provenance(
    root: Path, sha: str, *, skip_git_ancestor: bool
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    detail: dict[str, Any] = {}
    if not skip_git_ancestor:
        anc = _run_cmd(
            ["git", "merge-base", "--is-ancestor", sha, "origin/main"], cwd=root
        )
        detail["origin_main_ancestor"] = anc.returncode == 0
        if anc.returncode != 0:
            blockers.append(
                f"candidate SHA {sha} is not an ancestor of origin/main: {anc.stderr.strip()}"
            )
    else:
        detail["origin_main_ancestor"] = "skipped"

    val = _run_cmd(
        [
            sys.executable,
            str(root / "scripts" / "validate_provenance.py"),
            "--require-approved",
        ],
        cwd=root,
    )
    rat = _run_cmd(
        [sys.executable, str(root / "scripts" / "check_provenance_ratchet.py")],
        cwd=root,
    )
    detail["validate_provenance_ok"] = val.returncode == 0
    detail["ratchet_ok"] = rat.returncode == 0
    detail["ratchet_output"] = (rat.stdout or rat.stderr).strip()
    if val.returncode != 0:
        blockers.append(
            f"validate_provenance --require-approved failed: {val.stderr.strip() or val.stdout.strip()}"
        )
    if rat.returncode != 0:
        blockers.append(
            f"check_provenance_ratchet failed: {rat.stderr.strip() or rat.stdout.strip()}"
        )
    return detail, blockers


def _verify_mutation_report(
    root: Path, sha: str, report_path: Path
) -> tuple[bool, str]:
    proc = _run_cmd(
        [
            sys.executable,
            str(root / "tests" / "validation" / "policy" / "run_antigaming.py"),
            "--root",
            str(root),
            "--check",
            "release-scheduled-mutation-ratchet",
            "--mutation-report",
            str(report_path),
            "--expected-mutation-revision",
            sha,
            "--mutation-baseline",
            str(root / "tests" / "validation" / "policy" / "mutation-baseline.json"),
        ],
        cwd=root,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def _fetch_issues(
    repo: str, issues_json: Path | None, numbers: tuple[int, ...]
) -> dict[str, Any]:
    if issues_json is not None:
        raw = json.loads(issues_json.read_text(encoding="utf-8"))
        by_num = {
            str(item["number"]): item
            for item in raw
            if isinstance(item, dict) and "number" in item
        }
        return {"source": str(issues_json), "issues": by_num}
    issues: dict[str, Any] = {}
    for num in numbers:
        proc = _run_cmd(
            [
                "gh",
                "issue",
                "view",
                str(num),
                "-R",
                repo,
                "--json",
                "number,state,closedAt,title,url",
            ]
        )
        if proc.returncode == 0:
            issues[str(num)] = json.loads(proc.stdout)
        else:
            issues[str(num)] = {
                "number": num,
                "state": "UNAVAILABLE",
                "error": proc.stderr.strip() or proc.stdout.strip(),
            }
    return {"source": "gh issue view", "issues": issues}


def _find_latest_run_id(
    payload: Any, workflow_name: str, sha: str, *, event: str | tuple[str, ...]
) -> int | None:
    allowed = (event,) if isinstance(event, str) else tuple(event)
    pages = payload if isinstance(payload, list) else [payload]
    matches = [
        run
        for page in pages
        if isinstance(page, dict)
        for run in (page.get("workflow_runs") or [])
        if isinstance(run, dict)
        and run.get("name") == workflow_name
        and run.get("head_sha") == sha
        and run.get("head_branch") == "main"
        and run.get("event") in allowed
    ]
    if not matches:
        return None
    latest = max(matches, key=lambda r: (r.get("run_number", 0), r.get("id", 0)))
    return int(latest["id"])


def run_preflight(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    root = args.root.resolve()
    out_dir = args.output_dir.resolve()
    if out_dir == root or root in out_dir.parents:
        raise ValueError(
            f"--output-dir ({out_dir}) must live outside repository root ({root})"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "inputs"

    sha = args.sha
    blockers: list[str] = []

    provenance_info, prov_blockers = _check_provenance(
        root, sha, skip_git_ancestor=args.skip_git_ancestor_check
    )
    blockers.extend(prov_blockers)

    push_payload = _load_json_or_fetch(
        args.runs_json,
        f"repos/{args.repo}/actions/runs?head_sha={sha}&branch=main&event=push&per_page=100",
        cache_dir / "push-workflow-runs.json",
    )
    sbml_payload = _load_json_or_fetch(
        args.sbml_runs_json,
        f"repos/{args.repo}/actions/runs?head_sha={sha}&branch=main&event=workflow_dispatch&per_page=100",
        cache_dir / "sbml-workflow-runs.json",
    )
    weekly_sched_payload = _load_json_or_fetch(
        args.weekly_schedule_runs_json,
        f"repos/{args.repo}/actions/workflows/weekly.yml/runs?head_sha={sha}&branch=main&per_page=100",
        cache_dir / "weekly-runs.json",
    )
    explicit_runs = _load_explicit_runs(args.explicit_runs_json)

    missing_push = qualify_workflow_runs(
        push_payload, sha, REQUIRED_WORKFLOWS, event="push"
    )
    if missing_push:
        blockers.append(
            f"missing successful exact-main push workflow(s): {', '.join(missing_push)}"
        )

    ci_id = args.ci_run_id or _find_latest_run_id(push_payload, "CI", sha, event="push")
    parity_id = args.parity_run_id or _find_latest_run_id(
        push_payload, "Cross-tool parity", sha, event="push"
    )
    sbml_id = args.sbml_run_id or _find_latest_run_id(
        sbml_payload, "Official SBML conformance subset", sha, event="workflow_dispatch"
    )
    combined_weekly_payload = (
        weekly_sched_payload
        if isinstance(weekly_sched_payload, list)
        else [weekly_sched_payload]
    ) + (sbml_payload if isinstance(sbml_payload, list) else [sbml_payload])
    weekly_manual_id = args.weekly_run_id or _find_latest_run_id(
        combined_weekly_payload, "Weekly Validation", sha, event="workflow_dispatch"
    )
    weekly_sched_id = (
        args.scheduled_weekly_run_id
        or _find_latest_run_id(
            combined_weekly_payload,
            "Weekly Validation",
            sha,
            event=("schedule", "workflow_dispatch"),
        )
        or weekly_manual_id
    )

    runs_report: dict[str, Any] = {}

    # CI run + package artifacts
    sdist_present = False
    wheels_status: dict[str, Any] = {
        name: {"present": False} for name in REQUIRED_WHEEL_ARTIFACTS
    }
    if ci_id is None:
        blockers.append("missing CI run id for candidate SHA")
        runs_report["ci"] = {"present": False}
    else:
        ci_meta, ci_artifacts = _get_run_and_artifacts(args.repo, ci_id, explicit_runs)
        ci_rec = _evaluate_run_record(
            "CI", "CI", sha, ("push", "workflow_dispatch"), ci_meta, ci_artifacts
        )
        runs_report["ci"] = ci_rec
        blockers.extend(ci_rec["issues"])
        sdist_art = ci_rec["artifacts"].get("sdist")
        sdist_present = sdist_art is not None
        if not sdist_present:
            blockers.append(f"CI run {ci_id} missing 'sdist' artifact")
        for wheel_name in REQUIRED_WHEEL_ARTIFACTS:
            art = ci_rec["artifacts"].get(wheel_name)
            wheels_status[wheel_name] = {"present": art is not None, **(art or {})}
            if art is None:
                blockers.append(f"CI run {ci_id} missing '{wheel_name}' artifact")

    # Cross-tool parity run
    parity_artifacts: dict[str, Any] = {}
    if parity_id is None:
        blockers.append("missing Cross-tool parity run id for candidate SHA")
        runs_report["parity"] = {"present": False}
    else:
        p_meta, p_artifacts = _get_run_and_artifacts(
            args.repo, parity_id, explicit_runs
        )
        p_rec = _evaluate_run_record(
            "Cross-tool parity",
            "Cross-tool parity",
            sha,
            ("push", "workflow_dispatch"),
            p_meta,
            p_artifacts,
        )
        runs_report["parity"] = p_rec
        parity_artifacts = p_rec["artifacts"]
        blockers.extend(p_rec["issues"])

    # Weekly manual (diagnostic/test evidence) vs scheduled (release.yml gate)
    weekly_distinction: dict[str, Any] = {}
    mutation_name = f"release-product-mutation-ratchet-{sha}"
    if weekly_manual_id is not None:
        wm_meta, wm_artifacts = _get_run_and_artifacts(
            args.repo, weekly_manual_id, explicit_runs
        )
        wm_rec = _evaluate_run_record(
            "Weekly manual",
            "Weekly Validation",
            sha,
            ("workflow_dispatch", "schedule"),
            wm_meta,
            wm_artifacts,
        )
        wm_has_mutation = mutation_name in wm_rec["artifacts"]
        wm_rec["has_mutation_artifact"] = wm_has_mutation
        wm_mut_ok = False
        wm_mut_detail = ""
        if wm_has_mutation and not args.explicit_runs_json:
            wm_mut_dir = out_dir / "manual-mutation-artifact"
            dl_ok, dl_err = _download_artifact(
                args.repo, weekly_manual_id, mutation_name, wm_mut_dir
            )
            if dl_ok and (wm_mut_dir / "mutation-report.json").is_file():
                wm_mut_ok, wm_mut_detail = _verify_mutation_report(
                    root, sha, wm_mut_dir / "mutation-report.json"
                )
            else:
                wm_mut_detail = dl_err or "missing mutation-report.json"
        elif wm_has_mutation:
            wm_mut_ok = True
            wm_mut_detail = "artifact present in explicit run metadata"
        wm_rec["mutation_ratchet_verified"] = wm_mut_ok
        wm_rec["mutation_ratchet_detail"] = wm_mut_detail
        runs_report["weekly_manual"] = wm_rec
        if wm_rec["passed"] and wm_has_mutation and wm_mut_ok:
            weekly_distinction["manual_test_evidence"] = {
                "status": "PASS",
                "run_id": weekly_manual_id,
                "event": wm_rec["event"],
                "mutation_ratchet_verified": True,
                "note": "Exact-main workflow_dispatch Weekly Validation passed with verified mutation ratchet (accepted by release.yml #1023).",
            }
        else:
            weekly_distinction["manual_test_evidence"] = {
                "status": "FAIL",
                "run_id": weekly_manual_id,
                "event": wm_rec["event"],
                "mutation_ratchet_verified": wm_mut_ok,
                "issues": wm_rec["issues"]
                + ([] if wm_has_mutation else [f"missing {mutation_name}"])
                + ([] if (not wm_has_mutation or wm_mut_ok) else [wm_mut_detail]),
            }
            blockers.extend(wm_rec["issues"])
    else:
        runs_report["weekly_manual"] = {"present": False}
        weekly_distinction["manual_test_evidence"] = {"status": "ABSENT"}

    if weekly_sched_id is None:
        runs_report["weekly_scheduled"] = {"present": False}
        weekly_distinction["scheduled_release_gate"] = {
            "status": "BLOCKED",
            "reason": f"no completed schedule/workflow_dispatch Weekly Validation run for exact main SHA {sha}",
        }
        blockers.append(
            f"release.yml weekly mutation gate missing: no completed schedule/workflow_dispatch weekly.yml run and {mutation_name} artifact for {sha}"
        )
    else:
        ws_meta, ws_artifacts = _get_run_and_artifacts(
            args.repo, weekly_sched_id, explicit_runs
        )
        ws_rec = _evaluate_run_record(
            "Weekly release gate",
            "Weekly Validation",
            sha,
            ("schedule", "workflow_dispatch"),
            ws_meta,
            ws_artifacts,
        )
        ws_has_mutation = mutation_name in ws_rec["artifacts"]
        ws_rec["has_mutation_artifact"] = ws_has_mutation
        mutation_ok = False
        mutation_detail = ""
        if ws_has_mutation:
            mut_dir = args.mutation_artifact_dir or (out_dir / "mutation-artifact")
            if args.mutation_artifact_dir is None:
                dl_ok, dl_err = _download_artifact(
                    args.repo, weekly_sched_id, mutation_name, mut_dir
                )
                if not dl_ok:
                    mutation_detail = dl_err
            mut_report = mut_dir / "mutation-report.json"
            if mut_report.is_file():
                mutation_ok, mutation_detail = _verify_mutation_report(
                    root, sha, mut_report
                )
            elif not mutation_detail:
                mutation_detail = f"missing {mut_report}"
        else:
            mutation_detail = (
                f"missing {mutation_name} artifact on run {weekly_sched_id}"
            )
        ws_rec["mutation_ratchet_verified"] = mutation_ok
        ws_rec["mutation_ratchet_detail"] = mutation_detail
        runs_report["weekly_scheduled"] = ws_rec
        if ws_rec["passed"] and mutation_ok:
            weekly_distinction["scheduled_release_gate"] = {
                "status": "PASS",
                "run_id": weekly_sched_id,
                "event": ws_rec["event"],
            }
        else:
            weekly_distinction["scheduled_release_gate"] = {
                "status": "FAIL",
                "run_id": weekly_sched_id,
                "issues": ws_rec["issues"] + ([] if mutation_ok else [mutation_detail]),
            }
            blockers.extend(ws_rec["issues"])
            if not mutation_ok:
                blockers.append(f"scheduled mutation ratchet failed: {mutation_detail}")

    # SBML conformance subset (both full lanes from same attempt)
    sbml_dir = args.sbml_evidence_dir or (out_dir / "release-sbml-evidence")
    sbml_status: dict[str, Any] = {"passed": False}
    if sbml_id is not None:
        sb_meta, sb_artifacts = _get_run_and_artifacts(
            args.repo, sbml_id, explicit_runs
        )
        sb_rec = _evaluate_run_record(
            "SBML conformance",
            "Official SBML conformance subset",
            sha,
            ("workflow_dispatch",),
            sb_meta,
            sb_artifacts,
        )
        attempt = sb_rec["run_attempt"]
        ssts_name = f"ssts-release-consumers-{sha}-{attempt}"
        bio_name = f"curated-biomodels-{sha}-{attempt}"
        sb_rec["has_ssts_artifact"] = ssts_name in sb_rec["artifacts"]
        sb_rec["has_biomodels_artifact"] = bio_name in sb_rec["artifacts"]
        runs_report["sbml"] = sb_rec
        blockers.extend(sb_rec["issues"])
        if args.sbml_evidence_dir is None and sb_rec["passed"]:
            dest = sbml_dir / str(sbml_id) / str(attempt)
            if sb_rec["has_ssts_artifact"]:
                _download_artifact(args.repo, sbml_id, ssts_name, dest / "ssts")
            if sb_rec["has_biomodels_artifact"]:
                _download_artifact(args.repo, sbml_id, bio_name, dest / "biomodels")
    else:
        runs_report["sbml"] = {"present": False}

    try:
        inv_path = (
            args.biomodels_inventory
            if args.biomodels_inventory.is_absolute()
            else (root / args.biomodels_inventory)
        )
        inventory = json.loads(inv_path.read_text(encoding="utf-8"))
        model_ids = {row["id"] for row in inventory["models"]}
        if (
            not model_ids
            or len(model_ids) != inventory["matches"]
            or len(model_ids) != len(inventory["models"])
        ):
            raise ValueError("invalid pinned BioModels membership")
        qualify_sbml_runs(sbml_payload, sbml_dir, sha, model_ids)
        sbml_status = {
            "passed": True,
            "detail": "both SSTS and BioModels lanes verified",
        }
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        sbml_status = {"passed": False, "detail": str(exc)}
        blockers.append(f"SBML qualification failed: {exc}")

    # Install receipts & #184 platform check
    cpu_mod = _load_cpu_release_checks(root)
    install_paths = list(args.install_receipt or [])
    if ci_id is not None and not args.explicit_runs_json and "ci" in runs_report:
        ci_arts = runs_report["ci"].get("artifacts", {})
        ci_rec_dir = out_dir / "ci-install-receipts"
        for art_name in sorted(ci_arts):
            if art_name.startswith("issue184-install-receipt-") and art_name.endswith(
                f"-{sha}"
            ):
                dl_ok, _ = _download_artifact(
                    args.repo, ci_id, art_name, ci_rec_dir / art_name
                )
                if dl_ok:
                    for rec_json in sorted((ci_rec_dir / art_name).rglob("*.json")):
                        if rec_json not in install_paths:
                            install_paths.append(rec_json)

    sci_paths: list[Path] = []
    issue184_art_name = f"issue184-cpu-release-{sha}"
    if (
        parity_id is not None
        and issue184_art_name in parity_artifacts
        and not args.explicit_runs_json
    ):
        rec184_dir = out_dir / "issue184-receipt"
        ok, _ = _download_artifact(args.repo, parity_id, issue184_art_name, rec184_dir)
        if ok:
            for candidate_json in sorted(rec184_dir.rglob("*.json")):
                data = json.loads(candidate_json.read_bytes())
                if data.get("check_id") == "issue-184-cpu-release":
                    sci_paths.append(candidate_json)

    installed_parsed, inst_rejected = cpu_mod._receipts(install_paths, sha)
    missing_platform_gaps = cpu_mod.installed_gaps(
        installed_parsed, inst_rejected, root
    )
    missing_platforms = [
        plat
        for plat in cpu_mod.PLATFORMS
        if any(f"install receipt for {plat}" in gap for gap in missing_platform_gaps)
    ]
    for gap in missing_platform_gaps:
        blockers.append(f"install-receipt gap: {gap}")

    live_issues = _fetch_issues(args.repo, args.issues_json, TRACKED_RELEASE_ISSUES)

    dedup_blockers = sorted(set(blockers))
    verdict = "GO" if not dedup_blockers else "NO-GO"
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_sha": sha,
        "no_publish": True,
        "verdict": verdict,
        "qualify_release_candidate": {
            "missing_push_workflows": missing_push,
            "sbml": sbml_status,
            "passed": (not missing_push) and bool(sbml_status["passed"]),
        },
        "provenance_ratchet": provenance_info,
        "runs": runs_report,
        "weekly_event_distinction": weekly_distinction,
        "packages_and_install_receipts": {
            "sdist_present": sdist_present,
            "wheels": wheels_status,
            "install_receipts_checked": [str(p) for p in install_paths],
            "install_receipt_gaps": missing_platform_gaps,
            "missing_install_platforms": missing_platforms,
            "issue184_hosted_receipts_consumed": [str(p) for p in sci_paths],
        },
        "live_github_issues": live_issues,
        "blockers": dedup_blockers,
    }

    report_path = args.json or (out_dir / "preflight-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(
        f"Release preflight verdict for {sha}: {verdict} ({len(dedup_blockers)} blocker(s))"
    )
    print(f"Report written to: {report_path}")
    for item in dedup_blockers:
        print(f"  - BLOCKED: {item}")
    return report, (0 if verdict == "GO" else 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True, help="40-char candidate Git commit SHA")
    parser.add_argument("--repo", default="RuleWorld/BNG3")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--ci-run-id", type=int, default=None)
    parser.add_argument("--parity-run-id", type=int, default=None)
    parser.add_argument("--weekly-run-id", type=int, default=None)
    parser.add_argument("--scheduled-weekly-run-id", type=int, default=None)
    parser.add_argument("--sbml-run-id", type=int, default=None)
    parser.add_argument("--runs-json", type=Path, default=None)
    parser.add_argument("--sbml-runs-json", type=Path, default=None)
    parser.add_argument("--weekly-schedule-runs-json", type=Path, default=None)
    parser.add_argument("--explicit-runs-json", type=Path, default=None)
    parser.add_argument("--sbml-evidence-dir", type=Path, default=None)
    parser.add_argument("--mutation-artifact-dir", type=Path, default=None)
    parser.add_argument(
        "--install-receipt",
        type=Path,
        action="append",
        default=[],
        help="Path to an exact-SHA platform install receipt JSON (linux/macos/windows).",
    )
    parser.add_argument(
        "--biomodels-inventory",
        type=Path,
        default=Path("provenance/curated-biomodels-query-inventory.json"),
    )
    parser.add_argument("--issues-json", type=Path, default=None)
    parser.add_argument("--skip-git-ancestor-check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error("--sha must be a full lowercase Git commit SHA")
    _, code = run_preflight(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
