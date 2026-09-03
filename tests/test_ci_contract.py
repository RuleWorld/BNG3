"""Acceptance contracts for the Python package CI installation path."""

import json
from pathlib import Path
import re

from scripts.validate import load_skip_models, run_validation

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
WEEKLY_WORKFLOW = REPO / ".github" / "workflows" / "weekly.yml"
REFERENCE_EXCLUSIONS = REPO / "tests" / "validation" / "reference_exclusions.json"
VALIDATE_DIR = REPO / "tests" / "validation" / "Validate"


def test_pull_request_runs_keep_exact_head_evidence_available():
    """A later PR push must not cancel validation for the preceding SHA."""

    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.pull_request.head.sha" in workflow
    assert re.search(r"^\s+cancel-in-progress:\s+false\s*$", workflow, re.MULTILINE)


def _workflow_job(name: str) -> str:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [a-z0-9-]+:\n|\Z)",
        workflow,
    )
    assert match, f"CI must define a {name} job"
    return match.group("body")


def _python_test_job() -> str:
    return _workflow_job("python-test")


def _workflow_job_from(path: Path, name: str) -> str:
    workflow = path.read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [a-z0-9-]+:\n|\Z)",
        workflow,
    )
    assert match, f"{path.name} must define a {name} job"
    return match.group("body")


def test_pull_request_exercises_clean_source_distribution_install():
    """PRs must exercise the sdist install path, not only an in-tree wheel."""

    job = _workflow_job("package-smoke")
    assert "needs: [python-test]" in job
    assert not re.search(r"^\s+if:.*github\.event_name.*push", job, re.MULTILINE)
    assert "python -m build --sdist" in job
    assert "python -m venv" in job
    assert "pip install --no-deps dist/*.tar.gz" in job
    assert "import bionetgen" in job
    assert re.search(r"/bin/bionetgen\"?\s+--version", job)


def test_project_declares_click_as_runtime_dependency():
    project = PYPROJECT.read_text(encoding="utf-8")
    dependencies = re.search(
        r"(?ms)^dependencies\s*=\s*\[(?P<body>.*?)^\]", project
    )
    assert dependencies, "pyproject.toml must declare project dependencies"
    assert re.search(r"['\"]click(?:[<>=!~].*)?['\"]", dependencies.group("body"))


def test_python_matrix_installs_runtime_dependencies_before_no_deps_wheel():
    """No-deps wheel install must run after click is installed explicitly.

    The wheel job intentionally uses ``--no-deps``.  Therefore its test
    environment must install every runtime dependency required at collection
    time; otherwise ``tests/python/test_cli.py`` cannot import ``click``.
    """

    job = _python_test_job()
    assert "--no-deps" in job
    install_lines = [
        line
        for line in job.splitlines()
        if re.search(r"(?:pip|python\s+-m\s+pip)\s+install", line)
    ]
    assert install_lines, "python-test must install package/test dependencies"
    assert any(re.search(r"\bclick(?:[<>=!~].*)?\b", line) for line in install_lines), (
        "python-test no-deps wheel path must install declared click dependency"
    )


def test_python_tests_use_headless_isolated_matplotlib_cache():
    """The plotting test must not share a stale GUI/font cache on runners."""

    job = _python_test_job()
    assert "MPLBACKEND: Agg" in job
    assert "MPLCONFIGDIR: ${{ runner.temp }}/matplotlib" in job
    assert "scripts/prepare_matplotlib_cache.py" in job


def test_sbml_import_runs_as_a_real_isolated_ci_gate():
    """SBML coverage stays enabled while native XML libraries are isolated."""

    job = _python_test_job()
    assert "pytest tests/python/test_sbml_import.py -v --tb=short" in job
    assert "--ignore=tests/python/test_sbml_import.py" in job


def test_msvc_parser_headers_clear_windows_macros_before_antlr():
    """Windows SDK macros must not rewrite ANTLR enum members."""

    compat = (REPO / "cpp" / "parser" / "antlr_compat.hpp").read_text(
        encoding="utf-8"
    )
    assert re.search(r"#\s*undef\s+ERROR", compat)
    assert re.search(r"#\s*undef\s+TRUE", compat)
    assert re.search(r"#\s*undef\s+FALSE", compat)
    assert re.search(r"#\s*undef\s+constant", compat)

    source = (REPO / "cpp" / "nfsim" / "NFinput" / "NFinput_fromAst.cpp").read_text(
        encoding="utf-8"
    )
    parser_include = source.index('#include "PatternGraphBuilder.hpp"')
    prefix = source[:parser_include]
    assert '#include "parser/antlr_compat.hpp"' in prefix


def test_weekly_cross_validation_fails_closed_on_engine_or_output_errors():
    """The claimed C++/Perl gate must not turn failed models into skips."""

    job = _workflow_job_from(WEEKLY_WORKFLOW, "cross-validation")
    assert "set -euo pipefail" in job
    assert "SKIP" not in job
    assert "| Failed |" in job
    assert "[ \"$FAIL\" -gt 0 ]" in job
    assert job.count("FAIL=$((FAIL + 1))") >= 3


def test_reference_validation_can_fail_closed_on_missing_oracles(tmp_path):
    """A claimed reference gate must not turn a missing .net into a skip."""

    validate_dir = tmp_path / "Validate"
    (validate_dir / "DAT_validate").mkdir(parents=True)
    (validate_dir / "missing_oracle.bngl").write_text(
        "begin model\nend model\n", encoding="utf-8"
    )

    results, details = run_validation(
        "unused-bng-cpp",
        validate_dir,
        strict_references=True,
    )

    assert results == {"pass": 0, "fail": 0, "skip": 0, "error": 1}
    assert details == ["ERROR missing_oracle (no reference .net)"]


def test_reference_ci_jobs_enable_strict_reference_validation():
    """PR and weekly reference jobs must opt into the fail-closed contract."""

    assert "--strict-references" in _workflow_job("validation")
    weekly_job = _workflow_job_from(WEEKLY_WORKFLOW, "bng-validation")
    assert "--strict-references" in weekly_job


def test_reference_exclusion_manifest_is_explicit_and_corpus_backed():
    """Reference skips must be centralized, typed, and tied to corpus evidence."""

    manifest = json.loads(REFERENCE_EXCLUSIONS.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["status"] == "pending-maintainer-approval"
    assert set(manifest["profiles"]) == {"pull_request", "weekly"}
    assert set(manifest["reasons"]) == {
        "missing_reference_net",
        "unsupported_native_path",
    }

    pull_request = manifest["profiles"]["pull_request"]
    weekly = manifest["profiles"]["weekly"]
    assert len(pull_request) == len(set(pull_request))
    assert len(weekly) == len(set(weekly))
    assert set(weekly) == set(pull_request)

    missing_reference = set(manifest["reasons"]["missing_reference_net"])
    unsupported_native = set(manifest["reasons"]["unsupported_native_path"])
    assert missing_reference.isdisjoint(unsupported_native)
    assert set(pull_request) == missing_reference | unsupported_native

    for model in missing_reference | unsupported_native:
        assert isinstance(model, str) and model
        assert (VALIDATE_DIR / f"{model}.bngl").is_file(), model
    assert all(
        not (VALIDATE_DIR / "DAT_validate" / f"{model}.net").is_file()
        for model in missing_reference
    )
    assert all(
        (VALIDATE_DIR / "DAT_validate" / f"{model}.net").is_file()
        for model in unsupported_native
    )


def test_reference_ci_jobs_consume_profiled_exclusions():
    """CI must use the committed profile instead of duplicating skip strings."""

    validation_job = _workflow_job("validation")
    weekly_job = _workflow_job_from(WEEKLY_WORKFLOW, "bng-validation")
    assert "SKIP=" not in validation_job
    assert "SKIP=" not in weekly_job
    assert re.search(
        r"--skip-file tests/validation/reference_exclusions\.json\s*\\?\s+"
        r"--skip-profile pull_request",
        validation_job,
    )
    assert re.search(
        r"--skip-file tests/validation/reference_exclusions\.json\s*\\?\s+"
        r"--skip-profile weekly",
        weekly_job,
    )


def test_validate_loads_the_committed_reference_exclusion_profile():
    """The CLI loader must expose the same ordered models as the manifest."""

    manifest = json.loads(REFERENCE_EXCLUSIONS.read_text(encoding="utf-8"))
    assert (
        load_skip_models(REFERENCE_EXCLUSIONS, "pull_request")
        == manifest["profiles"]["pull_request"]
    )
    assert (
        load_skip_models(REFERENCE_EXCLUSIONS, "weekly")
        == manifest["profiles"]["weekly"]
    )
