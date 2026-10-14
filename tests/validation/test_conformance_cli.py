import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_native_suite_rejects_another_source_tree(tmp_path):
    from argparse import Namespace
    from tests.validation.conformance import _suite

    build = tmp_path / "build"
    build.mkdir()
    (build / "CMakeCache.txt").write_text(
        "CMAKE_HOME_DIRECTORY:INTERNAL=/foreign/source\n"
    )
    args = Namespace(bng_cpp=Path(sys.executable), build_dir=build)
    rows = _suite({"id": "native", "kind": "ctest"}, args, tmp_path / "report", {}, {})
    assert rows[0]["status"] == "HARNESS_ERROR"
    assert "source" in rows[0]["detail"]


def test_python_suite_does_not_receive_validation_only_option(tmp_path):
    from argparse import Namespace
    from tests.validation.conformance import _suite_command

    command = _suite_command(
        {"kind": "pytest", "tests": ["tests/python"]},
        Namespace(bng_cpp=tmp_path / "engine"),
        tmp_path / "junit.xml",
    )
    assert "--bng-cpp" not in command
    assert "-c" not in command


def test_integration_selection_comes_from_capability_test_mappings():
    from tests.validation.conformance import mapped_suite

    suite = mapped_suite(
        {"id": "python", "selection": "capability-mapped"},
        [
            {"tests": ["tests/python/test_a.py", "tests/cpp/test_a.cpp"]},
            {"tests": ["tests/python/test_a.py", "tests/python/test_b.py"]},
        ],
    )
    assert suite["tests"] == ["tests/python/test_a.py", "tests/python/test_b.py"]


def test_integrated_cli_inventory_is_source_driven_and_nonqualifying(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate.py"),
            "--inventory-only",
            "--report-dir",
            str(tmp_path / "report"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads((tmp_path / "report/report.json").read_text())
    assert report["results"] == []
    assert len(report["capabilities"]) > 500
    assert len({r["id"] for r in report["capabilities"]}) == len(report["capabilities"])
    assert all(r["coverage"] == "NOT_TESTED" for r in report["capabilities"])
    assert {
        "atomizer.structures",
        "sbml.multi",
        "bngir.versions-serialization",
        "nfnext.lowering-execution",
    } <= {r["id"] for r in report["capabilities"]}
    assert (tmp_path / "report/report.md").is_file()


def test_existing_report_directory_cannot_supply_stale_success(tmp_path):
    p = tmp_path / "old"
    p.mkdir()
    (p / "report.json").write_text("{}")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate.py"),
            "--inventory-only",
            "--report-dir",
            str(p),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "empty" in result.stderr + result.stdout


def test_equals_options_and_relative_plan_work(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate.py"),
            "--inventory-only",
            f"--report-dir={tmp_path / 'report'}",
            "--plan",
            "provenance/validation-plan.json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_test_or_golden_changes_make_history_incomparable(tmp_path):
    from tests.validation.conformance import evidence_inputs

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    p = tmp_path / "tests/validation/golden/a.gdat"
    p.parent.mkdir(parents=True)
    p.write_text("original")
    a = evidence_inputs(tmp_path)
    p.write_text("changed")
    assert evidence_inputs(tmp_path) != a


def test_missing_subject_is_rejected_before_fixture_can_fallback(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate.py"),
            "--tier=performance",
            "--suite",
            "bng2-parity",
            "--bng-cpp",
            str(tmp_path / "missing"),
            "--report-dir",
            str(tmp_path / "report"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    report = json.loads((tmp_path / "report/report.json").read_text())
    assert any(
        r["stage"] == "subject-preflight" and r["status"] == "HARNESS_ERROR"
        for r in report["results"]
    )


def test_missing_full_tier_oracles_are_errors_with_a_report(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate.py"),
            "--tier",
            "full",
            "--suite",
            "bng2-parity",
            "--models",
            "simple_system",
            "--bng-cpp",
            sys.executable,
            "--report-dir",
            str(tmp_path / "report"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    report = json.loads((tmp_path / "report/report.json").read_text())
    assert any(
        r["status"] == "HARNESS_ERROR" and r["stage"] == "reference-preflight"
        for r in report["results"]
    )
