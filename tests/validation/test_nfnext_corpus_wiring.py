"""Wiring checks for the issue-148 full-corpus NFnext native NFsim parity gate.

The gate is selected by path in `.github/workflows/parity.yml` (the
`nfsim-parity` job). Nothing fails in a Python suite when the step stops being
collected, loses an env var, or is silently reduced by a pytest filter, so this
file asserts on the PARSED workflow structure.

A new step must not be inserted between an existing `- name:` and its `run:`.
PyYAML keeps the last of duplicate keys silently, which can leave a step with
no run body or pointing at the wrong module. A strict loader refuses that.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PARITY_WORKFLOW = REPO / ".github" / "workflows" / "parity.yml"

MODULE = (
    "tests/validation/release/cases/issue-148/"
    "test_nfnext_full_corpus_native_parity.py"
)
STEP_NAME = "Check NFnext full-corpus native NFsim parity (issue-148)"
UPLOAD_NAME = "Upload NFnext full-corpus native parity report (issue-148)"
REPORT_SUFFIX = "bng3-nfnext-corpus-report.json"


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of dropping them."""


def _reject_duplicate_keys(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise AssertionError(
                f"duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}; "
                "PyYAML would silently keep only the last value"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _reject_duplicate_keys
)


def _parity_steps():
    text = PARITY_WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=_StrictLoader)
    return workflow["jobs"]["nfsim-parity"]["steps"]


def _find(steps, name):
    step = next((item for item in steps if item.get("name") == name), None)
    assert step is not None, f"missing parity.yml:nfsim-parity step {name!r}"
    return step


def test_no_duplicate_yaml_keys():
    """A duplicate key can silently drop the step's `run` body."""
    _parity_steps()


def test_full_corpus_parity_step_runs_the_exact_module():
    step = _find(_parity_steps(), STEP_NAME)
    assert "run" in step, "the gate step has no run body"
    command = step["run"].replace("\\\n", " ").strip()
    tokens = shlex.split(command)
    assert tokens[:3] == ["python", "-m", "pytest"]
    assert "--noconftest" in tokens
    assert "-q" in tokens
    assert MODULE in tokens
    # No filter may reduce the selected corpus. `-m` is allowed only as the
    # `python -m pytest` interpreter flag, never as a pytest marker filter.
    assert not {"-k", "--deselect", "--runxfail"} & set(tokens)
    assert tokens.count("-m") == 1, tokens
    # The step must fail outright; no masking of strict-oracle failures.
    assert step.get("continue-on-error", False) is False


def test_full_corpus_parity_step_sets_locked_oracles_and_report_path():
    step = _find(_parity_steps(), STEP_NAME)
    env = step.get("env", {})
    assert env.get("NFSIM_BIN", "").endswith("/oracle-nfsim/build/NFsim")
    assert env.get("BNG2_PERL", "").endswith("/oracle-bionetgen/bng2/BNG2.pl")
    report = env.get("BNG3_NFNEXT_CORPUS_REPORT", "")
    assert report.startswith("${{ runner.temp }}/"), report
    assert report.endswith(REPORT_SUFFIX), report


def test_full_corpus_report_is_uploaded_for_downstream_consumers():
    steps = _parity_steps()
    report = _find(steps, STEP_NAME)["env"]["BNG3_NFNEXT_CORPUS_REPORT"]
    upload = _find(steps, UPLOAD_NAME)
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == report
    assert upload["with"].get("if-no-files-found") == "error"


def test_wiring_test_is_collected_by_the_ci_contract_step():
    workflow = yaml.load(
        PARITY_WORKFLOW.read_text(encoding="utf-8"), Loader=_StrictLoader
    )
    contracts = next(
        step
        for step in workflow["jobs"]["oracle-lock"]["steps"]
        if step.get("name") == "Run CI contract tests"
    )
    assert Path(__file__).name in contracts["run"]
