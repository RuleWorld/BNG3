"""Acceptance contracts for the Python package CI installation path."""

from pathlib import Path
import re


REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"


def _python_test_job() -> str:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^  python-test:\n(?P<body>.*?)(?=^  [a-z0-9-]+:\n|\Z)",
        workflow,
    )
    assert match, "CI must define a python-test job"
    return match.group("body")


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
