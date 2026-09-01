"""Acceptance contracts for the Python package CI installation path."""

from pathlib import Path
import re


REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"


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
