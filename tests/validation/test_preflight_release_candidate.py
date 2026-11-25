"""Tests for scripts/ci/preflight_release_candidate.py."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.ci import preflight_release_candidate as preflight

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_SHA = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
).strip()
STALE_SHA = "0" * 40


def _write_json(path: Path, data: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(data, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _build_sbml_fixtures(base: Path, sha: str, sbml_run_id: int) -> tuple[Path, Path]:
    inv_path = base / "biomodels-inventory.json"
    _write_json(
        inv_path,
        {"matches": 1, "models": [{"id": "BIOMD0000000001"}]},
    )

    ev_dir = base / "sbml-evidence"
    attempt_dir = ev_dir / str(sbml_run_id) / "1"
    ssts_dir = attempt_dir / "ssts"
    bio_dir = attempt_dir / "biomodels"

    suite_hash = _write_json(
        ssts_dir / "report.json",
        {
            "source_provenance": {
                "bng3_commit": sha,
                "bng3_tracked_worktree_clean": True,
            },
            "validation_harness_provenance": {
                "bng3_commit": sha,
                "bng3_tracked_worktree_clean": True,
            },
            "partial_run": False,
            "case_selection": {"strategy": "full-inventory"},
            "stochastic_seed_base": 1000000,
            "full_suite_inventory": {"total": 2, "semantic": 1, "stochastic": 1},
            "selected_cases": 2,
            "records": [
                {"category": "semantic", "id": "00001"},
                {"category": "stochastic", "id": "00001"},
            ],
        },
    )
    for issue, checks in (
        (159, ("release-ssts", "release-ssts-coverage", "release-obligation-159")),
        (
            160,
            (
                "release-sbml-core-comp",
                "release-sbml-source-fidelity",
                "release-capability-coverage-160",
            ),
        ),
    ):
        _write_json(
            ssts_dir / f"issue{issue}-release-receipt.json",
            {
                "source": {"revision": sha, "dirty": False},
                "results": [
                    {
                        "id": cid,
                        "status": "PASS",
                        "supported_execution": True,
                        "receipt": {"report_sha256": suite_hash},
                    }
                    for cid in checks
                ],
            },
        )

    flat_hash = _write_json(
        bio_dir / "flat-report.json",
        {
            "mode": "flat",
            "simulation_comparison_is_required": True,
            "completeness": {
                "counts_match": True,
                "partial_run": False,
                "expected_records": 1,
            },
            "summary": {"harness_error_records": 0, "not_comparable_records": 0},
            "records": [{"id": "BIOMD0000000001"}],
        },
    )
    atom_hash = _write_json(
        bio_dir / "atomized-report.json",
        {
            "mode": "atomized",
            "simulation_comparison_is_required": True,
            "completeness": {
                "counts_match": True,
                "partial_run": False,
                "expected_records": 1,
            },
            "summary": {"harness_error_records": 0, "not_comparable_records": 0},
            "records": [{"id": "BIOMD0000000001"}],
        },
    )
    _write_json(
        bio_dir / "corpus-inventory.json",
        {
            "measurement": {
                "base_commit": sha,
                "reports": {
                    "flat": {"sha256": flat_hash},
                    "atomized": {"sha256": atom_hash},
                },
            },
            "corpus": {"expected_total_records": 1},
        },
    )
    _write_json(
        bio_dir / "issue162-release-receipt.json",
        {
            "source": {"revision": sha, "dirty": False},
            "results": [
                {"id": cid, "status": "PASS", "supported_execution": True}
                for cid in (
                    "release-biomodels",
                    "release-biomodels-triage",
                    "release-obligation-162",
                )
            ],
            "disposition_receipt": {
                "agreement": {"flat_atomized_match": True, "report_receipt_match": True}
            },
            "modes": {
                "flat": {
                    "report_sha256": flat_hash,
                    "unresolved": [],
                    "counts": {"compared": 1},
                },
                "atomized": {
                    "report_sha256": atom_hash,
                    "unresolved": [],
                    "counts": {"compared": 1},
                },
            },
        },
    )
    return inv_path, ev_dir


def _build_fixture_bundle(
    tmp_path: Path,
    sha: str,
    *,
    include_scheduled_weekly: bool = True,
    include_manual_weekly: bool = True,
    ci_head_sha: str | None = None,
    missing_wheels: tuple[str, ...] = (),
    install_platforms: tuple[str, ...] = ("linux", "macos", "windows"),
) -> dict[str, object]:
    fix_dir = tmp_path / "fixtures"
    inv_path, ev_dir = _build_sbml_fixtures(fix_dir, sha, sbml_run_id=400)

    push_sha = ci_head_sha or sha
    push_runs = [
        {
            "id": 100,
            "name": "CI",
            "head_sha": push_sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
        },
        {
            "id": 200,
            "name": "Cross-tool parity",
            "head_sha": sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
        },
        {
            "id": 201,
            "name": "Lean semantic kernel",
            "head_sha": sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
        },
        {
            "id": 202,
            "name": "CodeQL",
            "head_sha": sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
        },
    ]
    sbml_runs = [
        {
            "id": 400,
            "name": "Official SBML conformance subset",
            "head_sha": sha,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
        }
    ]
    if include_manual_weekly:
        sbml_runs.append(
            {
                "id": 301,
                "name": "Weekly Validation",
                "head_sha": sha,
                "head_branch": "main",
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
            }
        )
    sched_runs = (
        [
            {
                "id": 300,
                "name": "Weekly Validation",
                "head_sha": sha,
                "head_branch": "main",
                "event": "schedule",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
            }
        ]
        if include_scheduled_weekly
        else []
    )

    ci_artifacts = [
        {"name": "sdist", "id": 1, "size_in_bytes": 100, "digest": "sha256:aa"}
    ]
    for idx, wheel_name in enumerate(preflight.REQUIRED_WHEEL_ARTIFACTS, start=2):
        if wheel_name not in missing_wheels:
            ci_artifacts.append(
                {
                    "name": wheel_name,
                    "id": idx,
                    "size_in_bytes": 200,
                    "digest": f"sha256:0{idx}",
                }
            )

    mut_name = f"release-product-mutation-ratchet-{sha}"
    explicit_runs = {
        "100": {"run": push_runs[0], "artifacts": ci_artifacts},
        "200": {
            "run": push_runs[1],
            "artifacts": [
                {
                    "name": f"issue184-cpu-release-{sha}",
                    "id": 20,
                    "size_in_bytes": 500,
                    "digest": "sha256:bb",
                }
            ],
        },
        "400": {
            "run": sbml_runs[0],
            "artifacts": [
                {"name": f"ssts-release-consumers-{sha}-1", "id": 40},
                {"name": f"curated-biomodels-{sha}-1", "id": 41},
            ],
        },
    }
    if include_manual_weekly:
        explicit_runs["301"] = {
            "run": sbml_runs[1],
            "artifacts": [{"name": mut_name, "id": 31}],
        }
    if include_scheduled_weekly:
        explicit_runs["300"] = {
            "run": sched_runs[0],
            "artifacts": [{"name": mut_name, "id": 30}],
        }

    mut_dir = fix_dir / "mutation-artifact"
    _write_json(
        mut_dir / "mutation-report.json",
        {
            "schema": 1,
            "revision": sha,
            "caught": 1,
            "denominator": 1,
            "classification_counts": {"equivalent": 0, "non_equivalent": 1},
            "status_counts": {
                "equivalent": 0,
                "infrastructure_error": 0,
                "invalid": 0,
                "killed": 1,
                "survived": 0,
            },
            "mutants": [
                {
                    "id": "python.set-parameter-scale",
                    "file": "python/bionetgen/model.py",
                    "classification": "non_equivalent",
                    "status": "killed",
                    "exit_code": 1,
                }
            ],
        },
    )

    install_receipts: list[Path] = []
    for plat in install_platforms:
        rpath = fix_dir / f"install-{plat}.json"
        _write_json(
            rpath,
            {
                "source": {"revision": sha, "dirty": False},
                "references": {"platform": plat},
                "results": [
                    {
                        "id": f"install-{plat}",
                        "status": "PASS",
                        "supported_execution": True,
                    }
                ],
            },
        )
        install_receipts.append(rpath)

    runs_json = fix_dir / "push-runs.json"
    sbml_runs_json = fix_dir / "sbml-runs.json"
    sched_json = fix_dir / "sched-runs.json"
    explicit_json = fix_dir / "explicit-runs.json"
    issues_json = fix_dir / "issues.json"

    _write_json(runs_json, [{"workflow_runs": push_runs}])
    _write_json(sbml_runs_json, [{"workflow_runs": sbml_runs}])
    _write_json(sched_json, [{"workflow_runs": sched_runs}])
    _write_json(explicit_json, explicit_runs)
    _write_json(
        issues_json,
        [
            {"number": 137, "state": "CLOSED"},
            {"number": 180, "state": "OPEN"},
            {"number": 181, "state": "OPEN"},
            {"number": 471, "state": "OPEN"},
            {"number": 184, "state": "OPEN"},
            {"number": 474, "state": "OPEN"},
        ],
    )

    return {
        "runs_json": runs_json,
        "sbml_runs_json": sbml_runs_json,
        "sched_json": sched_json,
        "explicit_json": explicit_json,
        "inv_path": inv_path,
        "ev_dir": ev_dir,
        "mut_dir": mut_dir,
        "install_receipts": install_receipts,
        "issues_json": issues_json,
    }


def _invoke(
    tmp_path: Path,
    sha: str,
    bundle: dict[str, object],
    *,
    weekly_run_id: int | None = 301,
    scheduled_weekly_run_id: int | None = 300,
    skip_ancestor: bool = True,
) -> tuple[int, dict]:
    out_dir = tmp_path / "preflight-out"
    argv = [
        "--sha",
        sha,
        "--root",
        str(ROOT),
        "--output-dir",
        str(out_dir),
        "--ci-run-id",
        "100",
        "--parity-run-id",
        "200",
        "--sbml-run-id",
        "400",
        "--runs-json",
        str(bundle["runs_json"]),
        "--sbml-runs-json",
        str(bundle["sbml_runs_json"]),
        "--weekly-schedule-runs-json",
        str(bundle["sched_json"]),
        "--explicit-runs-json",
        str(bundle["explicit_json"]),
        "--biomodels-inventory",
        str(bundle["inv_path"]),
        "--sbml-evidence-dir",
        str(bundle["ev_dir"]),
        "--mutation-artifact-dir",
        str(bundle["mut_dir"]),
        "--issues-json",
        str(bundle["issues_json"]),
    ]
    if weekly_run_id is not None:
        argv.extend(["--weekly-run-id", str(weekly_run_id)])
    if scheduled_weekly_run_id is not None:
        argv.extend(["--scheduled-weekly-run-id", str(scheduled_weekly_run_id)])
    for rpath in bundle["install_receipts"]:  # type: ignore[attr-defined]
        argv.extend(["--install-receipt", str(rpath)])
    if skip_ancestor:
        argv.append("--skip-git-ancestor-check")

    code = preflight.main(argv)
    report = json.loads((out_dir / "preflight-report.json").read_text(encoding="utf-8"))
    return code, report


def test_preflight_passes_with_complete_scheduled_and_install_evidence(tmp_path: Path):
    bundle = _build_fixture_bundle(tmp_path, CANDIDATE_SHA)
    code, report = _invoke(tmp_path, CANDIDATE_SHA, bundle)

    assert code == 0
    assert report["verdict"] == "GO"
    assert report["no_publish"] is True
    assert report["qualify_release_candidate"]["passed"] is True
    assert (
        report["weekly_event_distinction"]["scheduled_release_gate"]["status"] == "PASS"
    )
    assert (
        report["weekly_event_distinction"]["manual_test_evidence"]["status"] == "PASS"
    )
    assert report["packages_and_install_receipts"]["missing_install_platforms"] == []
    assert report["live_github_issues"]["issues"]["137"]["state"] == "CLOSED"
    assert report["blockers"] == []


def test_preflight_rejects_stale_sha(tmp_path: Path):
    bundle = _build_fixture_bundle(tmp_path, CANDIDATE_SHA, ci_head_sha=STALE_SHA)
    code, report = _invoke(tmp_path, CANDIDATE_SHA, bundle)

    assert code == 1
    assert report["verdict"] == "NO-GO"
    assert report["qualify_release_candidate"]["missing_push_workflows"] == ["CI"]
    assert any(
        "head_sha" in b or "missing successful exact-main" in b
        for b in report["blockers"]
    )


def test_preflight_distinguishes_manual_weekly_from_scheduled_gate(tmp_path: Path):
    bundle = _build_fixture_bundle(
        tmp_path,
        CANDIDATE_SHA,
        include_scheduled_weekly=False,
        include_manual_weekly=True,
    )
    code, report = _invoke(
        tmp_path, CANDIDATE_SHA, bundle, weekly_run_id=301, scheduled_weekly_run_id=None
    )

    assert code == 0
    assert report["verdict"] == "GO"
    assert (
        report["weekly_event_distinction"]["manual_test_evidence"]["status"] == "PASS"
    )
    assert (
        report["weekly_event_distinction"]["scheduled_release_gate"]["status"] == "PASS"
    )
    assert (
        report["weekly_event_distinction"]["scheduled_release_gate"]["event"]
        == "workflow_dispatch"
    )


def test_preflight_rejects_missing_weekly_mutation_gate(tmp_path: Path):
    bundle = _build_fixture_bundle(
        tmp_path,
        CANDIDATE_SHA,
        include_scheduled_weekly=False,
        include_manual_weekly=False,
    )
    code, report = _invoke(
        tmp_path,
        CANDIDATE_SHA,
        bundle,
        weekly_run_id=None,
        scheduled_weekly_run_id=None,
    )

    assert code == 1
    assert report["verdict"] == "NO-GO"
    assert (
        report["weekly_event_distinction"]["scheduled_release_gate"]["status"]
        == "BLOCKED"
    )
    assert any("weekly mutation gate missing" in b for b in report["blockers"])


def test_preflight_flags_missing_install_receipts_and_wheels(tmp_path: Path):
    bundle = _build_fixture_bundle(
        tmp_path,
        CANDIDATE_SHA,
        missing_wheels=("wheels-windows-2022",),
        install_platforms=("linux", "macos"),
    )
    code, report = _invoke(tmp_path, CANDIDATE_SHA, bundle)

    assert code == 1
    assert report["verdict"] == "NO-GO"
    pkg = report["packages_and_install_receipts"]
    assert pkg["missing_install_platforms"] == ["windows"]
    assert pkg["wheels"]["wheels-windows-2022"]["present"] is False
    assert any("wheels-windows-2022" in b for b in report["blockers"])
    assert any("install receipt for windows" in b for b in report["blockers"])


def test_preflight_refuses_output_dir_inside_repo(tmp_path: Path):
    bundle = _build_fixture_bundle(tmp_path, CANDIDATE_SHA)
    args = preflight.build_parser().parse_args(
        [
            "--sha",
            CANDIDATE_SHA,
            "--root",
            str(ROOT),
            "--output-dir",
            str(ROOT / "tmp-bad-out"),
            "--runs-json",
            str(bundle["runs_json"]),
            "--sbml-runs-json",
            str(bundle["sbml_runs_json"]),
            "--weekly-schedule-runs-json",
            str(bundle["sched_json"]),
        ]
    )
    with pytest.raises(ValueError, match="outside repository root"):
        preflight.run_preflight(args)
