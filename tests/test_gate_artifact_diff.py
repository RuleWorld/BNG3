"""The artifact diff must distinguish a changed model from an unchanged one.

The gate's verdict says whether a case passed; it does not say whether the
model the gate produced changed.  A change to the Atomizer can rewrite the
generated BNGL for a case whose verdict stays exactly the same, and a verdict
comparison cannot see it.

The behaviour that matters most is the classification: a report that cannot
tell "the model changed" from "the model did not change" is not worth having.
The rest of the tests pin the properties that keep the report honest -- a
non-reproducible artifact is not reported as a difference, run-local
provenance is not a difference, and solver noise is not a verdict difference.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_tool():
    path = Path(__file__).parents[1] / "scripts" / "ci" / "diff_gate_artifacts.py"
    spec = importlib.util.spec_from_file_location("diff_gate_artifacts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diff = _load_tool()


def _write_case(root: Path, key: str, files: dict[str, str]) -> Path:
    """Write one case's artifacts under an artifacts root."""

    path = root / key
    path.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (path / name).write_text(content, encoding="utf-8")
    return path


def _record(case_id: str, **overrides: Any) -> dict[str, Any]:
    record = {
        "category": "semantic",
        "id": case_id,
        "status": "passed",
        "core_passed": True,
        "roundtrip_passed": True,
        "simulation_comparison": {
            "passed": True,
            "observables": {"S1": {"passed": True, "max_abs_difference": 1.0e-14}},
        },
        "official_conformance": {"status": "passed", "reason": ""},
        "worker_runtime_provenance": {
            "python_executable": "/usr/bin/python",
            "bionetgen_package_path": "/tmp/one/python/bionetgen/__init__.py",
        },
    }
    record.update(overrides)
    return record


def _report(records: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    report = {"records": records}
    report.update(overrides)
    return report


def _compare(
    tmp_path: Path,
    first_files: dict[str, str],
    second_files: dict[str, str],
    *,
    first_record: dict[str, Any] | None = None,
    second_record: dict[str, Any] | None = None,
    probe_runner=None,
    numeric_rtol: float = 1e-6,
    numeric_atol: float = 0.0,
) -> dict[str, Any]:
    first = _write_case(tmp_path / "first", "semantic/00001", first_files)
    second = _write_case(tmp_path / "second", "semantic/00001", second_files)
    return diff.compare_case(
        "semantic/00001",
        first,
        second,
        first_record=first_record if first_record is not None else _record("00001"),
        second_record=(
            second_record if second_record is not None else _record("00001")
        ),
        numeric_rtol=numeric_rtol,
        numeric_atol=numeric_atol,
        probe_runner=probe_runner,
    )


MODEL_FILES = {
    "source.xml": "<sbml/>\n",
    "translated.bngl": "begin\n  k1 0.7\nend\n",
    "reimported.bngl": "begin\n  k1 0.7\nend\n",
    "semantic_00001.xml": "<sbml/>\n",
}


def test_a_changed_model_with_an_unchanged_verdict_is_reported_as_such(tmp_path):
    """The case this tool exists to surface must have its own outcome."""

    changed = dict(MODEL_FILES)
    changed["translated.bngl"] = "begin\n  k1 0.5\nend\n"

    case = _compare(tmp_path, MODEL_FILES, changed)

    assert case["outcome"] == diff.OUTCOME_CHANGED_UNCHANGED
    assert case["model_changed"] is True
    assert case["verdict_changed"] is False


def test_a_changed_model_with_a_changed_verdict_is_reported_as_such(tmp_path):
    """The ordinary case must be distinguishable from the interesting one."""

    changed = dict(MODEL_FILES)
    changed["translated.bngl"] = "begin\n  k1 0.5\nend\n"

    case = _compare(
        tmp_path,
        MODEL_FILES,
        changed,
        second_record=_record("00001", status="failed", core_passed=False),
    )

    assert case["outcome"] == diff.OUTCOME_CHANGED_CHANGED
    assert case["model_changed"] is True
    assert case["verdict_changed"] is True


def test_an_unchanged_model_is_a_positive_result(tmp_path):
    """The absence of a model difference must be stated, not left implicit."""

    case = _compare(tmp_path, MODEL_FILES, dict(MODEL_FILES))

    assert case["outcome"] == diff.OUTCOME_UNCHANGED
    assert case["model_changed"] is False
    assert case["verdict_changed"] is False


def test_the_three_outcomes_are_distinct(tmp_path):
    """The classification must not collapse any two of the three outcomes."""

    changed = dict(MODEL_FILES)
    changed["translated.bngl"] = "begin\n  k1 0.5\nend\n"

    unchanged = _compare(tmp_path / "a", MODEL_FILES, dict(MODEL_FILES))
    changed_only = _compare(tmp_path / "b", MODEL_FILES, changed)
    changed_both = _compare(
        tmp_path / "c",
        MODEL_FILES,
        changed,
        second_record=_record("00001", status="failed", core_passed=False),
    )

    outcomes = {
        unchanged["outcome"],
        changed_only["outcome"],
        changed_both["outcome"],
    }
    assert len(outcomes) == 3


def test_the_first_differing_line_is_reported(tmp_path):
    """A text difference must say where it is, not only that it exists."""

    changed = dict(MODEL_FILES)
    changed["translated.bngl"] = "begin\n  k1 0.5\nend\n"

    case = _compare(tmp_path, MODEL_FILES, changed)

    entry = case["artifacts"]["translated.bngl"]
    assert entry["status"] == "differs"
    assert entry["first_differing_line"]["line"] == 2
    assert entry["first_differing_line"]["first"] == "  k1 0.7"
    assert entry["first_differing_line"]["second"] == "  k1 0.5"
    assert entry["differing_lines"] == 1


def test_an_artifact_that_is_not_reproducible_is_not_reported_as_a_difference(
    tmp_path,
):
    """A difference that cannot be attributed to the change is not a difference."""

    changed = dict(MODEL_FILES)
    changed["translated.bngl"] = "begin\n  k1 0.5\nend\n"

    def probe_runner(case_key: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "reason": "",
            "reproducible": {"translated.bngl": False},
            "seed_sensitive": {"translated.bngl": False},
        }

    case = _compare(tmp_path, MODEL_FILES, changed, probe_runner=probe_runner)

    entry = case["artifacts"]["translated.bngl"]
    assert entry["status"] == "not-reproducible"
    assert "not reproducible under a pinned seed" in entry["reason"]
    # The model did not demonstrably change, so it must not be reported as a
    # change, and it must not be reported as unchanged either.
    assert case["model_changed"] is False
    assert case["outcome"] == diff.OUTCOME_UNRESOLVED


def test_a_reproducible_artifact_that_differs_is_a_real_difference(tmp_path):
    """The probe must not excuse a difference the generator reproduces."""

    changed = dict(MODEL_FILES)
    changed["translated.bngl"] = "begin\n  k1 0.5\nend\n"

    def probe_runner(case_key: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "reason": "",
            "reproducible": {"translated.bngl": True},
            "seed_sensitive": {"translated.bngl": False},
        }

    case = _compare(tmp_path, MODEL_FILES, changed, probe_runner=probe_runner)

    assert case["artifacts"]["translated.bngl"]["status"] == "differs"
    assert case["outcome"] == diff.OUTCOME_CHANGED_UNCHANGED


def test_an_artifact_that_changes_with_the_hash_seed_is_not_a_difference(tmp_path):
    """A seed effect is not a model change and must not be reported as one."""

    changed = dict(MODEL_FILES)
    changed["translated.bngl"] = "begin\n  k1 0.5\nend\n"

    def probe_runner(case_key: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "reason": "",
            "reproducible": {"translated.bngl": True},
            "seed_sensitive": {"translated.bngl": True},
        }

    case = _compare(tmp_path, MODEL_FILES, changed, probe_runner=probe_runner)

    entry = case["artifacts"]["translated.bngl"]
    assert entry["status"] == "seed-sensitive"
    assert "hash seed" in entry["reason"]
    assert case["model_changed"] is False
    assert case["outcome"] == diff.OUTCOME_UNRESOLVED


def test_run_local_provenance_is_not_a_difference(tmp_path):
    """Two runs that observed the same case under different builds agree."""

    first = _record(
        "00001",
        worker_runtime_provenance={
            "python_executable": "/opt/one/python",
            "bionetgen_package_path": "/tmp/one/python/bionetgen/__init__.py",
        },
    )
    second = _record(
        "00001",
        worker_runtime_provenance={
            "python_executable": "/opt/two/python",
            "bionetgen_package_path": "/tmp/two/python/bionetgen/__init__.py",
        },
    )

    case = _compare(
        tmp_path,
        MODEL_FILES,
        dict(MODEL_FILES),
        first_record=first,
        second_record=second,
    )

    assert case["verdict_changed"] is False
    assert case["outcome"] == diff.OUTCOME_UNCHANGED


def test_solver_noise_is_not_a_verdict_difference(tmp_path):
    """A comparison number that moved within tolerance is not a verdict."""

    second = _record("00001")
    second["simulation_comparison"]["observables"]["S1"]["max_abs_difference"] = (
        1.0e-14 + 1.0e-20
    )

    case = _compare(tmp_path, MODEL_FILES, dict(MODEL_FILES), second_record=second)

    assert case["numeric_changes"] == []
    assert case["verdict_changed"] is False
    assert case["outcome"] == diff.OUTCOME_UNCHANGED


def test_a_comparison_number_that_moved_is_reported_with_its_magnitude(tmp_path):
    """A moved comparison number is reported, but not as a verdict change."""

    second = _record("00001")
    second["simulation_comparison"]["observables"]["S1"]["max_abs_difference"] = 0.5

    case = _compare(tmp_path, MODEL_FILES, dict(MODEL_FILES), second_record=second)

    assert len(case["numeric_changes"]) == 1
    change = case["numeric_changes"][0]
    assert change["path"] == "simulation_comparison.observables.S1.max_abs_difference"
    assert change["absolute_delta"] == pytest.approx(0.5 - 1.0e-14)
    assert case["verdict_changed"] is False


def test_a_missing_artifact_is_reported(tmp_path):
    """An artifact that exists in only one run is a difference."""

    second = dict(MODEL_FILES)
    del second["reimported.bngl"]

    case = _compare(tmp_path, MODEL_FILES, second)

    assert case["artifacts"]["reimported.bngl"]["status"] == "missing-in-second"
    assert case["model_changed"] is True


def test_the_seed_condition_is_stated_when_no_run_recorded_a_seed():
    """The tool must not imply it verified a seed it never saw."""

    condition = diff._seed_condition(None, None)

    assert "neither run recorded a pinned hash seed" in condition
    assert "assumes" in condition


def test_the_seed_condition_is_stated_when_the_seeds_differ():
    """Two runs under different seeds are not a sound comparison."""

    condition = diff._seed_condition("0", "1")

    assert "different hash seeds" in condition
    assert "seed effects" in condition


def test_the_seed_condition_is_stated_when_both_runs_pinned_the_same_seed():
    """A shared pinned seed is what makes the comparison sound."""

    condition = diff._seed_condition("0", "0")

    assert "both runs pinned the hash seed at 0" in condition
    assert "sound" in condition


def test_the_seed_is_read_from_a_runs_recorded_provenance():
    """The seed the run recorded is the seed the tool reports."""

    payload = {"runtime_provenance": {"python_hash_seed": "0"}}

    assert diff._seed_from_payload(payload) == "0"
    assert diff._seed_from_payload({"runtime_provenance": {}}) is None


def test_a_case_can_be_compiled_on_its_own(tmp_path):
    """One case is how one investigates a single report."""

    root = tmp_path / "artifacts"
    _write_case(root, "semantic/00001", MODEL_FILES)
    _write_case(root, "semantic/00002", MODEL_FILES)

    cases = diff.discover_cases(root)

    assert sorted(cases) == ["semantic/00001", "semantic/00002"]


def test_the_corpus_layout_is_compared_by_the_same_tool(tmp_path):
    """The curated corpus keeps one directory per model, not per category."""

    first = _write_case(
        tmp_path / "first",
        "BIOMD0000000174",
        {
            "source.xml": "<sbml/>\n",
            "translated.flat.bngl": "begin\n  k1 0.7\nend\n",
            "record.json": json.dumps({"id": "BIOMD0000000174", "status": "passed"}),
        },
    )
    second = _write_case(
        tmp_path / "second",
        "BIOMD0000000174",
        {
            "source.xml": "<sbml/>\n",
            "translated.flat.bngl": "begin\n  k1 0.5\nend\n",
            "record.json": json.dumps({"id": "BIOMD0000000174", "status": "passed"}),
        },
    )

    case = diff.compare_case(
        "BIOMD0000000174",
        first,
        second,
        first_record={"id": "BIOMD0000000174", "status": "passed", "core_passed": True},
        second_record={
            "id": "BIOMD0000000174",
            "status": "passed",
            "core_passed": True,
        },
        numeric_rtol=1e-6,
        numeric_atol=0.0,
    )

    assert case["outcome"] == diff.OUTCOME_CHANGED_UNCHANGED
    assert (
        case["artifacts"]["translated.flat.bngl"]["first_differing_line"]["line"] == 2
    )


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).parents[1] / "scripts" / "ci" / "diff_gate_artifacts.py"
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def _cli_tree(tmp_path: Path, name: str, changed: bool) -> Path:
    root = tmp_path / name
    files = dict(MODEL_FILES)
    if changed:
        files["translated.bngl"] = "begin\n  k1 0.5\nend\n"
    _write_case(root, "semantic/00001", files)
    report = tmp_path / f"{name}-report.json"
    report.write_text(json.dumps(_report([_record("00001")])), encoding="utf-8")
    return root


def test_the_command_line_reports_no_difference_for_two_identical_runs(tmp_path):
    """Two runs that produced the same artifacts must report no difference."""

    first = _cli_tree(tmp_path, "first", changed=False)
    second = _cli_tree(tmp_path, "second", changed=False)

    result = _run_cli(
        "--first-artifacts",
        str(first),
        "--second-artifacts",
        str(second),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "model unchanged: 1" in result.stdout


def test_the_command_line_reports_a_changed_model_with_an_unchanged_verdict(
    tmp_path,
):
    """The headline case must be visible in the command-line report."""

    first = _cli_tree(tmp_path, "first", changed=False)
    second = _cli_tree(tmp_path, "second", changed=True)

    result = _run_cli(
        "--first-artifacts",
        str(first),
        "--second-artifacts",
        str(second),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "model changed, verdict unchanged: 1" in result.stdout
    assert "differs at line 2" in result.stdout


def test_the_command_line_can_compare_one_case(tmp_path):
    """One case is how a single report is investigated."""

    first = _cli_tree(tmp_path, "first", changed=False)
    second = _cli_tree(tmp_path, "second", changed=True)
    _write_case(first, "semantic/00002", dict(MODEL_FILES))
    _write_case(second, "semantic/00002", dict(MODEL_FILES))

    result = _run_cli(
        "--first-artifacts",
        str(first),
        "--second-artifacts",
        str(second),
        "--case",
        "semantic/00001",
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "cases: 1" in result.stdout
    assert "semantic/00002" not in result.stdout


def test_a_report_that_does_not_hold_the_case_yields_no_verdict():
    """An unrelated record must never stand in for the case under comparison."""

    payload = {
        "records": [
            _record("00001"),
            _record("00002", status="failed", core_passed=False),
        ]
    }

    assert diff._load_record(payload, "semantic/00003") is None
    assert diff._load_record(payload, "semantic/00002")["status"] == "failed"


def test_a_single_record_report_is_unambiguous():
    """The per-case worker report holds one record and names the case."""

    payload = {"records": [_record("00001")]}

    assert diff._load_record(payload, "semantic/00001")["status"] == "passed"


def test_the_command_line_writes_a_json_report(tmp_path):
    """The report must be machine-readable for a campaign that aggregates."""

    first = _cli_tree(tmp_path, "first", changed=False)
    second = _cli_tree(tmp_path, "second", changed=True)
    output = tmp_path / "diff.json"

    result = _run_cli(
        "--first-artifacts",
        str(first),
        "--second-artifacts",
        str(second),
        "--json",
        str(output),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["counts"][diff.OUTCOME_CHANGED_UNCHANGED] == 1
    assert report["seed_condition"]
    assert report["cases"][0]["case"] == "semantic/00001"


def test_the_runtime_identity_of_each_run_is_reported(tmp_path):
    """A reader must be able to see which package tree each run measured.

    A stale installed ``bionetgen`` in site-packages makes a bare run
    measure the wrong code, and the report is where that has to be visible.
    """

    first = _cli_tree(tmp_path, "first", changed=False)
    second = _cli_tree(tmp_path, "second", changed=True)
    first_report = tmp_path / "first-report.json"
    second_report = tmp_path / "second-report.json"
    first_report.write_text(
        json.dumps(
            _report(
                [_record("00001")],
                runtime_provenance={
                    "bionetgen_package_path": "/repo/python/bionetgen/__init__.py"
                },
            )
        ),
        encoding="utf-8",
    )
    second_report.write_text(
        json.dumps(
            _report(
                [_record("00001")],
                runtime_provenance={
                    "bionetgen_package_path": "/site-packages/bionetgen/__init__.py"
                },
            )
        ),
        encoding="utf-8",
    )

    result = _run_cli(
        "--first-artifacts",
        str(first),
        "--second-artifacts",
        str(second),
        "--first-report",
        str(first_report),
        "--second-report",
        str(second_report),
    )

    assert "/repo/python/bionetgen/__init__.py" in result.stdout
    assert "/site-packages/bionetgen/__init__.py" in result.stdout
    assert "different runtime identities" in result.stdout


def test_a_case_present_in_only_one_run_is_reported(tmp_path):
    """A case the two runs did not both cover is a coverage difference."""

    first = _cli_tree(tmp_path, "first", changed=False)
    second = _cli_tree(tmp_path, "second", changed=False)
    _write_case(first, "semantic/00002", dict(MODEL_FILES))

    result = _run_cli(
        "--first-artifacts",
        str(first),
        "--second-artifacts",
        str(second),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "cases present in only one run: 1" in result.stdout
    assert "missing-in-second" in result.stdout


def test_the_command_line_reports_a_non_reproducible_artifact_as_such(tmp_path):
    """The probe must excuse a difference the generator cannot reproduce."""

    gate = tmp_path / "gate.py"
    gate.write_text(
        "import pathlib, random, sys\n"
        "root = pathlib.Path(sys.argv[sys.argv.index('--artifacts-dir') + 1])\n"
        "case = root / sys.argv[sys.argv.index('--case') + 1]\n"
        "case.mkdir(parents=True, exist_ok=True)\n"
        "(case / 'translated.bngl').write_text('k1 %f\\n' % random.random())\n",
        encoding="utf-8",
    )
    first = _cli_tree(tmp_path, "first", changed=False)
    second = _cli_tree(tmp_path, "second", changed=True)

    result = _run_cli(
        "--first-artifacts",
        str(first),
        "--second-artifacts",
        str(second),
        "--probe-reproducibility",
        "--probe-command",
        "{python} {gate} --artifacts-dir {artifacts_dir} --case {case}",
        "--probe-gate",
        str(gate),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "not reproducible under a pinned seed" in result.stdout
    assert "model unresolved: 1" in result.stdout
    # The difference must not also be reported as a plain difference.
    assert "differs at line" not in result.stdout


def test_the_command_line_reports_a_seed_sensitive_artifact_as_such(tmp_path):
    """An artifact that changes with the hash seed is not a model change."""

    gate = tmp_path / "gate.py"
    gate.write_text(
        "import os, pathlib, sys\n"
        "root = pathlib.Path(sys.argv[sys.argv.index('--artifacts-dir') + 1])\n"
        "case = root / sys.argv[sys.argv.index('--case') + 1]\n"
        "case.mkdir(parents=True, exist_ok=True)\n"
        "(case / 'translated.bngl').write_text(\n"
        "    'k1 %s\\n' % os.environ.get('PYTHONHASHSEED', 'random')\n"
        ")\n",
        encoding="utf-8",
    )
    first = _cli_tree(tmp_path, "first", changed=False)
    second = _cli_tree(tmp_path, "second", changed=True)

    result = _run_cli(
        "--first-artifacts",
        str(first),
        "--second-artifacts",
        str(second),
        "--probe-reproducibility",
        "--probe-command",
        "{python} {gate} --artifacts-dir {artifacts_dir} --case {case}",
        "--probe-gate",
        str(gate),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "changes with the interpreter's hash seed" in result.stdout
    assert "model unresolved: 1" in result.stdout
    assert "differs at line" not in result.stdout
