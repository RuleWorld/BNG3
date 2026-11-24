"""Focused controls for the #184 release-candidate disposition recorder."""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SCRIPT = ROOT / "scripts/ci/record_issue184_candidate.py"
IDS = {
    "release-candidate:license-inventory",
    "release-candidate:notice-inventory",
    "release-candidate:memory-contract",
    "release-candidate:sanitizer-configuration",
    "release-candidate:platform-matrix-shape",
    "release-candidate:hosted-evidence",
    "qualification:issue:184:require-approved-provenance-corpora-scheduled-nfsim-results-clea",
    "qualification:issue:184:verify-final-candidate-platform-sanitizer-memory-licenses-notice",
    "qualification:issue:184:closure-record",
}


def _wheel(path: Path, *, license_entry: bool = True, notice: bool = False) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        if license_entry:
            zf.writestr("bionetgen-3.0.0a1.dist-info/licenses/LICENSE", "license text")
        if notice:
            zf.writestr("bionetgen-3.0.0a1.dist-info/NOTICE", "notice text")


def _runs(path: Path, *, good: bool = True, rev: str = "test") -> None:
    def run(name: str, conclusion: str | None) -> dict:
        return {"name": name, "head_sha": rev, "conclusion": conclusion}
    rows = [
        run("C++ ASan (Ubuntu)", "success" if good else None),
        run("C++ (ubuntu-22.04, gcc-12)", "success" if good else None),
        run("C++ (macos-15, clang-arm64)", "success" if good else None),
        run("C++ (windows-2022, msvc)", "success" if good else None),
        run("CI", "success" if good else None),
        run("Cross-tool parity", "success" if good else None),
    ]
    path.write_text(json.dumps({"workflow_runs": rows}) + "\n")


def _benchmark(path: Path, *, good: bool = True, rev: str = "test") -> None:
    path.write_text(json.dumps({
        "source": {"revision": rev},
        "results": [{"id": "release-benchmarks", "status": "PASS" if good else "FAIL"}],
    }) + "\n")


def test_dispositions_positive(tmp_path: Path) -> None:
    import subprocess as sp
    rev = sp.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    wd = tmp_path / "wheels"
    wd.mkdir()
    _wheel(wd / "a.whl")
    _wheel(wd / "b.whl")
    runs, bench, report = tmp_path / "runs.json", tmp_path / "bench.json", tmp_path / "report.json"
    _runs(runs, rev=rev)
    _benchmark(bench, rev=rev)
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(ROOT), "--revision", rev, "--allow-dirty",
         "--wheel-dir", str(wd), "--runs-json", str(runs),
         "--benchmark-report", str(bench), "--report", str(report)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(report.read_text())
    assert data["source"] == {"revision": rev, "dirty": False}
    assert {row["id"] for row in data["results"]} == IDS
    assert all(row["status"] == "PASS" for row in data["results"])
    assert all(row["evidence_kind"] == "disposition" for row in data["results"])


def test_negative_controls_fail(tmp_path: Path) -> None:
    import subprocess as sp
    rev = sp.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    wd = tmp_path / "wheels"
    wd.mkdir()
    _wheel(wd / "no-license.whl", license_entry=False)
    runs, bench, report = tmp_path / "runs.json", tmp_path / "bench.json", tmp_path / "report.json"
    _runs(runs, good=False)
    _benchmark(bench, good=False, rev=rev)
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(ROOT), "--revision", rev, "--allow-dirty",
         "--wheel-dir", str(wd), "--runs-json", str(runs),
         "--benchmark-report", str(bench), "--report", str(report)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    data = json.loads(report.read_text())
    failed = {row["id"] for row in data["results"] if row["status"] == "FAIL"}
    assert "release-candidate:license-inventory" in failed
    assert "release-candidate:memory-contract" in failed
    assert "release-candidate:sanitizer-configuration" in failed
    assert "release-candidate:hosted-evidence" in failed
