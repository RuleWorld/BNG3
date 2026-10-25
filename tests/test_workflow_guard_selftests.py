"""Adversarial inputs for the guards that run before native CI builds."""

import subprocess

import pytest
import yaml

from tests import test_workflow_contract as guard
from tests.workflow_yaml import parse_workflow


@pytest.mark.parametrize(
    "text",
    [
        "jobs:\n  check: {}\n  check: {}\n",
        "jobs:\n  check:\n    steps:\n      - run: pytest good.py\n        run: echo skipped\n",
        "concurrency:\n  cancel-in-progress: true\n  cancel-in-progress: false\n",
    ],
    ids=["duplicate-job", "overwritten-test-command", "overwritten-cancellation"],
)
def test_duplicate_key_guard_rejects_overwritten_execution(tmp_path, text):
    path = tmp_path / "workflow.yml"
    path.write_text(text)
    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key"):
        parse_workflow(path)


def invocation():
    return {
        "workflow": "probe.yml",
        "job": "probe",
        "step": "Select regression",
        "argv": ["tests/test_probe.py", "-k", "regression"],
        "selectors": [("-k", "regression")],
    }


@pytest.mark.parametrize(
    "code, stdout, diagnostic",
    [
        (5, "", "VACUOUS SELECTOR"),
        (0, "no node ids", "VACUOUS SELECTOR"),
        (2, "tests/test_probe.py::test_regression\n", "COULD NOT VERIFY"),
        (3, "internal error", "COULD NOT VERIFY"),
        (4, "usage error", "COULD NOT VERIFY"),
    ],
    ids=[
        "empty-selection",
        "empty-success",
        "partial-collection-error",
        "internal-error",
        "bad-arguments",
    ],
)
def test_selector_guard_distinguishes_empty_selection_from_broken_collection(
    monkeypatch, code, stdout, diagnostic
):
    monkeypatch.setattr(
        guard.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], code, stdout, "probe stderr"
        ),
    )
    with pytest.raises(pytest.fail.Exception, match=diagnostic):
        guard.test_workflow_pytest_selector_collects_at_least_one_test(invocation())


def test_selector_guard_accepts_successful_nonempty_collection(monkeypatch):
    monkeypatch.setattr(
        guard.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 0, "tests/test_probe.py::test_regression\n", ""
        ),
    )
    guard.test_workflow_pytest_selector_collects_at_least_one_test(invocation())


def test_selector_collection_has_a_time_budget(monkeypatch):
    def hung_collection(*args, **kwargs):
        assert kwargs.get("timeout") == 120
        raise subprocess.TimeoutExpired(args[0], 120, output="partial collection")

    monkeypatch.setattr(guard.subprocess, "run", hung_collection)
    with pytest.raises(pytest.fail.Exception, match="COULD NOT VERIFY.*timed out"):
        guard.test_workflow_pytest_selector_collects_at_least_one_test(invocation())
