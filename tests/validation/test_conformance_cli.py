import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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


def test_tfun_network_comparison_consumes_bng2_xml_sidecar(tmp_path, monkeypatch):
    from tests.validation import campaign, conformance

    source = tmp_path / "test_tfun.bngl"
    source.write_text(
        """begin functions
  mctr = dummy/1e4
  k1 = TFUN(mctr, 'DAT_validate/test.dat') / 10
end functions
begin actions
  generate_network({overwrite=>1})
end actions
""",
        encoding="utf-8",
    )
    support = tmp_path / "DAT_validate"
    support.mkdir()
    (support / "test.dat").write_text("0 1\n1 2\n", encoding="utf-8")
    wrong_subject_rate = False

    reference_net = """begin parameters
1 _rateLaw1 1e4
end parameters
begin functions
1 mctr() dum/1e4
2 k2() TFUN(mctr,'DAT_validate/test.dat')
end functions
begin species
1 A() 1000
2 dummy() 0
end species
begin reactions
1 0 2 _rateLaw1
2 1 0 k2
end reactions
begin groups
1 A 1
2 dum 2
end groups
"""
    xml = """<model>
  <Function id="k2" type="TFUN" file="DAT_validate/test.dat" ctrName="mctr">
    <Expression>__TFUN_VAL__/1e1</Expression>
  </Function>
</model>
"""

    def subject_net():
        divisor = 11 if wrong_subject_rate else 10
        return f"""begin functions
mctr()=dum/10000
k2()=tfun('DAT_validate/test.dat', mctr)/{divisor}
end functions
begin species
1 A() 1000
2 dummy() 0
end species
begin reactions
1 0 2 10000
2 1 0 k2
end reactions
begin groups
1 A 1
2 dum 2
end groups
"""

    def run_command(command, cwd, timeout, *, required=(), env=None):
        if "--check" not in command:
            model = Path(command[-1])
            text = model.read_text(encoding="utf-8")
            if command[0] == "perl":
                assert "writeXML({overwrite=>1})" in text
                assert "test_tfun.xml" in required
                (cwd / "test_tfun.xml").write_text(xml, encoding="utf-8")
                (cwd / "test_tfun.net").write_text(reference_net, encoding="utf-8")
            else:
                (cwd / "test_tfun.net").write_text(subject_net(), encoding="utf-8")
        return {"status": "PASS", "detail": ""}

    monkeypatch.setattr(campaign, "run_command", run_command)

    args = SimpleNamespace(
        bng_cpp=Path("bng_cpp"),
        network_iterations=10,
        max_aggregate=100,
        case_timeout=10,
    )

    def run_report(name):
        return conformance._model(
            "test_tfun",
            source,
            args,
            tmp_path / name,
            {"script": "BNG2.pl"},
            {},
        )

    rows = run_report("report")
    assert all(row["status"] == "PASS" for row in rows), [
        (row["id"], row["status"], row.get("detail"))
        for row in rows
        if row["status"] != "PASS"
    ]
    assert (tmp_path / "report/models/test_tfun/reference/test_tfun.xml").is_file()

    wrong_subject_rate = True
    negative_rows = run_report("negative-report")
    reaction_rate = next(
        row for row in negative_rows if row["id"] == "test_tfun:network:reaction-rates"
    )
    assert reaction_rate["status"] == "FAIL"


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
    issues = [{"number": 999, "title": "Unmapped example", "state": "CLOSED"}]
    snapshot = tmp_path / "issues.json"
    snapshot.write_text(json.dumps(issues))
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate.py"),
            "--inventory-only",
            "--issues-json",
            str(snapshot),
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
    issue = next(row for row in report["issue_coverage"] if row["number"] == 999)
    assert issue["state"] == "CLOSED"
    assert issue["coverage"] == "NOT_TESTED"
    assert issue["capabilities"] == []
    assert report["issue_inventory"]["scope"] == "provided-snapshot"
    assert (tmp_path / "report/issues-input.json").read_bytes() == snapshot.read_bytes()
    assert (
        json.loads((tmp_path / "report/issue-coverage.json").read_text())
        == report["issue_coverage"]
    )


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


def test_named_pytest_failure_retains_summary_and_does_not_create_duplicate_task(
    tmp_path,
):
    from argparse import Namespace
    from tests.validation.conformance import _suite

    test = tmp_path / "test_injected_rate.py"
    test.write_text(
        'def test_rate():\n    assert False, "expected rate 0.5, actual 1.0"\n'
    )
    rows = _suite(
        {
            "id": "harness",
            "kind": "pytest",
            "tests": [str(test)],
            "timeout": 15,
            "question": "harness-self-test",
        },
        Namespace(bng_cpp=Path(sys.executable)),
        tmp_path / "evidence",
        {},
        dict(os.environ),
    )
    failure = next(r for r in rows if r["stage"] == "test")
    process = next(r for r in rows if r["id"] == "harness:process")
    assert failure["status"] == "FAIL"
    assert "expected rate 0.5" in failure["failure_summary"]
    assert process["aggregate"] is True
