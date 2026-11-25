"""Focused unit and negative controls for #184 artifact-derived candidate and install scripts."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[5]
CANDIDATE_SCRIPT = ROOT / "scripts/ci/record_issue184_candidate.py"
INSTALL_SCRIPT = ROOT / "scripts/ci/record_issue184_install_receipt.py"

sys.path.insert(0, str(ROOT))
from scripts.ci import (  # noqa: E402
    record_issue184_candidate as cand_mod,
    record_issue184_install_receipt as inst_mod,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_digest(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode(
        "ascii"
    ).rstrip("=")


def _make_wheel(
    path: Path,
    *,
    include_license: bool = True,
    include_notice: bool = False,
    tamper_record: bool = False,
) -> str:
    dist = "bionetgen-3.0.0a1.dist-info"
    entries: dict[str, bytes] = {
        "bionetgen/__init__.py": b'__version__ = "3.0.0a1"\n',
        "bionetgen/_bionetgen_cpp.so": b"native-placeholder",
        f"{dist}/METADATA": b"Metadata-Version: 2.1\nName: bionetgen\nVersion: 3.0.0a1\nLicense: MIT\n",
        f"{dist}/WHEEL": b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: false\n",
    }
    if include_license:
        entries[f"{dist}/licenses/LICENSE"] = b"MIT License\n"
    if include_notice:
        entries[f"{dist}/NOTICE"] = b"Notice text\n"
    record_lines = [
        f"{name},{_record_digest(raw)},{len(raw)}" for name, raw in entries.items()
    ]
    if tamper_record:
        record_lines[0] = "bionetgen/__init__.py,sha256=deadbeef,1"
    record_lines.append(f"{dist}/RECORD,,")
    entries[f"{dist}/RECORD"] = ("\n".join(record_lines) + "\n").encode("utf-8")

    with zipfile.ZipFile(path, "w") as zf:
        for name, raw in entries.items():
            zf.writestr(name, raw)
    return _sha256(path)


def _make_sdist(path: Path, *, include_license: bool = True) -> str:
    base = "bionetgen-3.0.0a1"
    entries: dict[str, bytes] = {
        f"{base}/PKG-INFO": b"Metadata-Version: 2.1\nName: bionetgen\nVersion: 3.0.0a1\nLicense: MIT\n",
        f"{base}/pyproject.toml": b'[project]\nname = "bionetgen"\nversion = "3.0.0a1"\n',
    }
    if include_license:
        entries[f"{base}/LICENSE"] = b"MIT License\n"
    with tarfile.open(path, "w:gz") as tf:
        for name, raw in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(raw)
            tf.addfile(info, io.BytesIO(raw))
    return _sha256(path)


def _write_runs(path: Path, rev: str, *, missing_sbml: bool = False) -> None:
    runs = [
        {
            "name": wf,
            "head_sha": rev,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        for wf in cand_mod.REQUIRED_PUSH_WORKFLOWS
    ]
    if not missing_sbml:
        runs.append(
            {
                "name": "Official SBML conformance subset",
                "head_sha": rev,
                "head_branch": "main",
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "success",
            }
        )
    runs.append(
        {
            "name": "Weekly Validation",
            "head_sha": rev,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
        }
    )
    path.write_text(json.dumps({"workflow_runs": runs}) + "\n")


def _write_ci_jobs(path: Path, *, failed_job: str | None = None) -> None:
    jobs = [
        {
            "name": name,
            "status": "completed",
            "conclusion": "failure" if name == failed_job else "success",
        }
        for name in cand_mod.REQUIRED_CI_JOBS
    ]
    path.write_text(json.dumps({"jobs": jobs}) + "\n")


def _write_junit(
    path: Path, *, tests: int = 10, failures: int = 0, skipped: int = 0
) -> str:
    path.write_text(
        f'<testsuite name="CTest" tests="{tests}" failures="{failures}" errors="0" skipped="{skipped}"/>\n'
    )
    return _sha256(path)


def _write_install_receipt(
    path: Path, *, rev: str, plat: str, art_name: str, art_sha: str
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "check_id": "issue184-install-receipt",
                "source": {"revision": rev, "dirty": False},
                "references": {
                    "platform": plat,
                    "artifact_kind": (
                        "sdist" if art_name.endswith(".tar.gz") else "wheel"
                    ),
                    "artifact_name": art_name,
                    "artifact_sha256": art_sha,
                    "gpu_scope_deferred_to": "#474",
                    "gpu_qualified_by_this_receipt": False,
                },
                "results": [
                    {
                        "id": "clean_install",
                        "status": "PASS",
                        "supported_execution": True,
                    }
                ],
            }
        )
        + "\n"
    )


def _build_all_candidate_inputs(tmp_path: Path, rev: str) -> dict[str, Path]:
    wd = tmp_path / "wheels"
    wd.mkdir()
    w_lin = wd / "bionetgen-3.0.0a1-cp312-cp312-manylinux_2_28_x86_64.whl"
    w_mac_arm = wd / "bionetgen-3.0.0a1-cp312-cp312-macosx_11_0_arm64.whl"
    w_mac_x64 = wd / "bionetgen-3.0.0a1-cp312-cp312-macosx_11_0_x86_64.whl"
    w_win = wd / "bionetgen-3.0.0a1-cp312-cp312-win_amd64.whl"
    sdist = tmp_path / "bionetgen-3.0.0a1.tar.gz"

    shas = {
        w_lin.name: _make_wheel(w_lin),
        w_mac_arm.name: _make_wheel(w_mac_arm),
        w_mac_x64.name: _make_wheel(w_mac_x64),
        w_win.name: _make_wheel(w_win),
        sdist.name: _make_sdist(sdist),
    }

    bench = tmp_path / "bench.json"
    bench.write_text(
        json.dumps(
            {
                "source": {"revision": rev, "dirty": False},
                "results": [
                    {
                        "id": cid,
                        "status": "PASS",
                        "supported_execution": True,
                    }
                    for cid in (
                        "release-benchmarks",
                        "release-benchmark-correctness",
                        "release-obligation-174",
                    )
                ],
            }
        )
    )
    junit = tmp_path / "asan-ctest.xml"
    jsha = _write_junit(junit, tests=42, failures=0, skipped=0)
    asan_rec = tmp_path / "asan-receipt.json"
    asan_rec.write_text(
        json.dumps(
            {
                "source": {"revision": rev, "dirty": False},
                "sanitize_address": True,
                "detect_leaks_1_late_stop_passed": True,
                "junit_sha256": {"ctest": jsha},
            }
        )
    )
    runs = tmp_path / "runs.json"
    _write_runs(runs, rev)
    ci_jobs = tmp_path / "ci-jobs.json"
    _write_ci_jobs(ci_jobs)
    mut = tmp_path / "mutation.json"
    mut.write_text(
        json.dumps(
            {
                "schema": 1,
                "revision": rev,
                "caught": 3,
                "denominator": 3,
                "status_counts": {"survived": 0, "infrastructure_error": 0},
            }
        )
    )
    inst_lin = tmp_path / "inst-linux.json"
    _write_install_receipt(
        inst_lin, rev=rev, plat="linux", art_name=w_lin.name, art_sha=shas[w_lin.name]
    )
    return {
        "wheel_dir": wd,
        "sdist": sdist,
        "bench": bench,
        "junit": junit,
        "asan_rec": asan_rec,
        "runs": runs,
        "ci_jobs": ci_jobs,
        "mut": mut,
        "inst": inst_lin,
        "w_lin": w_lin,
    }


def test_candidate_evidence_passes_from_real_artifacts(tmp_path: Path) -> None:
    rev = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    inp = _build_all_candidate_inputs(tmp_path, rev)
    report = tmp_path / "cand-report.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(CANDIDATE_SCRIPT),
            "--root",
            str(ROOT),
            "--revision",
            rev,
            "--allow-dirty",
            "--wheel-dir",
            str(inp["wheel_dir"]),
            "--sdist",
            str(inp["sdist"]),
            "--benchmark-report",
            str(inp["bench"]),
            "--asan-junit",
            str(inp["junit"]),
            "--asan-receipt",
            str(inp["asan_rec"]),
            "--ci-jobs-json",
            str(inp["ci_jobs"]),
            "--runs-json",
            str(inp["runs"]),
            "--mutation-report",
            str(inp["mut"]),
            "--install-receipt",
            str(inp["inst"]),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(report.read_text())
    assert {r["id"] for r in data["results"]} == set(cand_mod.CANDIDATE_CHECK_IDS)
    assert all(
        r["status"] == "PASS" and r["supported_execution"] is True
        for r in data["results"]
    )


def test_candidate_evidence_fails_on_real_defects(tmp_path: Path) -> None:
    rev = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    inp = _build_all_candidate_inputs(tmp_path, rev)
    _make_wheel(inp["w_lin"], include_license=False, tamper_record=True)
    _write_junit(inp["junit"], tests=10, failures=1)
    _write_ci_jobs(inp["ci_jobs"], failed_job="C++ (windows-2022, msvc)")
    _write_runs(inp["runs"], rev, missing_sbml=True)
    report = tmp_path / "cand-fail.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(CANDIDATE_SCRIPT),
            "--root",
            str(ROOT),
            "--revision",
            rev,
            "--allow-dirty",
            "--wheel-dir",
            str(inp["wheel_dir"]),
            "--sdist",
            str(inp["sdist"]),
            "--asan-junit",
            str(inp["junit"]),
            "--ci-jobs-json",
            str(inp["ci_jobs"]),
            "--runs-json",
            str(inp["runs"]),
            "--mutation-report",
            str(inp["mut"]),
            "--install-receipt",
            str(inp["inst"]),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    failed = {
        r["id"]
        for r in json.loads(report.read_text())["results"]
        if r["status"] == "FAIL"
    }
    assert {
        "release-candidate:license-inventory",
        "release-candidate:memory-contract",
        "release-candidate:sanitizer-configuration",
        "release-candidate:platform-matrix-shape",
        "release-candidate:hosted-evidence",
        "release-candidate:reproducible-build-digests",
    } <= failed


def test_truthful_gpu_metadata_validation() -> None:
    ok_cpu, _ = inst_mod.validate_truthful_gpu_metadata(
        {
            "gpu_backend_capabilities": [
                {
                    "name": "cuda",
                    "compiled": False,
                    "available": False,
                    "implemented_routes": [],
                },
                {
                    "name": "metal",
                    "compiled": False,
                    "available": False,
                    "implemented_routes": [],
                },
            ],
            "gpu_backends": [{"name": "cuda"}, {"name": "metal"}],
            "default_gpu_backend": "none",
            "gpu_qualified_by_this_receipt": False,
            "gpu_scope_deferred_to": "#474",
        }
    )
    assert ok_cpu
    ok_metal, _ = inst_mod.validate_truthful_gpu_metadata(
        {
            "gpu_backend_capabilities": [
                {
                    "name": "cuda",
                    "compiled": False,
                    "available": False,
                    "implemented_routes": [],
                },
                {
                    "name": "metal",
                    "compiled": True,
                    "available": True,
                    "implemented_routes": [
                        "finite_batch_ssa",
                        "nfnext_unary_state_change",
                    ],
                },
            ],
            "gpu_backends": [{"name": "cuda"}, {"name": "metal"}],
            "default_gpu_backend": "metal",
            "gpu_qualified_by_this_receipt": False,
            "gpu_scope_deferred_to": "#474",
        }
    )
    assert ok_metal
    bad_claim, _ = inst_mod.validate_truthful_gpu_metadata(
        {
            "gpu_backend_capabilities": [
                {
                    "name": "cuda",
                    "compiled": False,
                    "available": True,
                    "implemented_routes": [],
                },
                {
                    "name": "metal",
                    "compiled": False,
                    "available": False,
                    "implemented_routes": [],
                },
            ],
            "gpu_backends": [{"name": "cuda"}, {"name": "metal"}],
            "default_gpu_backend": "cuda",
            "gpu_qualified_by_this_receipt": True,
            "gpu_scope_deferred_to": "#474",
        }
    )
    assert not bad_claim
