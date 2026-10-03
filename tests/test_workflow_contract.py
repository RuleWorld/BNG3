"""Whole-repo contracts on `.github/workflows/*.yml`.

Two classes of defect live here, and both are the same shape: an *instrument
that reports success while measuring something else*.

1. **Duplicate YAML mapping keys.** PyYAML resolves them last-wins and says
   nothing. A workflow that wires a parity gate under a key it already used
   parses cleanly, `grep` finds both the intended module and the module that
   actually runs, and the gate is off. This happened once already in
   `parity.yml`; `tests/validation/test_parity_workflow_wiring.py` covers that
   one file. This module covers *every* workflow, because a duplicate key is
   invisible to any tool that does not raise on it.

2. **Vacuous pytest selectors.** `pytest -k "..."` that matches nothing exits
   0. A step can therefore select a test that was renamed, deleted, or moved,
   and the job stays green having run nothing. Every `-k`/`-m` a workflow
   passes is collected here and must select at least one test.

Neither check is a text search. A duplicate key cannot be seen by grepping,
and a selector's reachability cannot be seen by reading it.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.workflow_yaml import (
    REPO,
    parse_workflow,
    parse_workflow_or_none,
    workflow_files,
)

VALIDATION_INI = "tests/validation/pytest.ini"

# --------------------------------------------------------------------------
# 1. Duplicate mapping keys
# --------------------------------------------------------------------------


def test_no_workflow_contains_duplicate_yaml_keys():
    """Every workflow must parse with no duplicate key at any depth.

    The failure this guards is silent by construction: the duplicate key is
    dropped by the loader, so a grep for the intended wiring still succeeds and
    the executed command belongs to the *other* module.
    """
    assert workflow_files(), "no workflows found; the check would be vacuous"
    offenders = []
    for path in workflow_files():
        try:
            parse_workflow(path)
        except yaml.constructor.ConstructorError as exc:
            offenders.append(
                f"{path.relative_to(REPO)}: {exc.problem} at {exc.problem_mark}"
            )
    assert not offenders, "duplicate YAML keys:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_workflow_parses_and_declares_jobs(path: Path):
    """Each workflow must parse under the strict loader and define jobs."""
    doc = parse_workflow_or_none(path)
    assert doc is not None, (
        f"{path.name} does not parse; the cause is reported by "
        "test_no_workflow_contains_duplicate_yaml_keys"
    )
    assert isinstance(doc, dict), f"{path.name} did not parse to a mapping"
    assert doc.get("jobs"), f"{path.name} defines no jobs"


# --------------------------------------------------------------------------
# 2. Vacuous pytest selectors
# --------------------------------------------------------------------------


def _logical_commands(run: str) -> list[str]:
    """Split a shell step into individual commands, joining `\\` continuations."""
    joined = run.replace("\\\n", " ")
    out = []
    for raw in joined.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _pytest_argv(command: str) -> list[str] | None:
    """Return the pytest argv if this command invokes pytest, else None.

    Handles `VAR=v pytest ...` prefixes and both `pytest` and
    `python -m pytest` spellings.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        return None
    if tokens[0] == "pytest":
        return tokens[1:]
    if tokens[:3] == ["python", "-m", "pytest"]:
        return tokens[3:]
    return None


def _selectors(argv: list[str]) -> list[tuple[str, str]]:
    out = []
    for i, tok in enumerate(argv):
        if tok in ("-k", "-m") and i + 1 < len(argv):
            out.append((tok, argv[i + 1]))
        elif tok.startswith("-k=") or tok.startswith("-m="):
            out.append((tok[:2], tok[2:]))
    return out


def workflow_pytest_invocations() -> list[dict]:
    """Every pytest command any workflow runs, parsed out of the YAML."""
    found = []
    for path in workflow_files():
        doc = parse_workflow_or_none(path)
        if not isinstance(doc, dict):
            continue
        for job_name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if not isinstance(step, dict) or "run" not in step:
                    continue
                for command in _logical_commands(step["run"]):
                    argv = _pytest_argv(command)
                    if argv is None:
                        continue
                    found.append(
                        {
                            "workflow": path.name,
                            "job": job_name,
                            "step": step.get("name") or "<unnamed>",
                            "argv": argv,
                            "selectors": _selectors(argv),
                        }
                    )
    return found


def _collection_args(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split a workflow argv into (test targets, passthrough config args)."""
    targets: list[str] = []
    passthrough: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in ("-c", "--rootdir", "-n", "-p"):
            passthrough += [tok, argv[i + 1]] if i + 1 < len(argv) else [tok]
            i += 2
            continue
        if tok.startswith("-"):
            # skip the selector and its value
            if tok in ("-k", "-m") and i + 1 < len(argv):
                i += 2
                continue
            if tok.startswith(("-k=", "-m=")):
                i += 1
                continue
            if tok in ("--bng-cpp", "--cov", "--cov-report", "--tb", "-q", "-v", "-s"):
                i += 2 if tok in ("--bng-cpp", "--cov", "--cov-report", "--tb") else 1
                continue
            if tok.startswith(("--ignore=", "--tb=", "--cov=")):
                i += 1
                continue
            i += 1
            continue
        targets.append(tok)
        i += 1
    return targets, passthrough


@pytest.mark.parametrize(
    "invocation",
    [
        pytest.param(
            inv,
            id=f"{inv['workflow']}-{inv['job']}-"
            + "_".join(f"{flag}{value}" for flag, value in inv["selectors"]),
        )
        for inv in workflow_pytest_invocations()
        if inv["selectors"]
    ],
)
def test_workflow_pytest_selector_collects_at_least_one_test(invocation):
    """A `-k`/`-m` in a workflow must select at least one test.

    `pytest -k "renamed_test"` selects nothing and exits 0, so the job passes
    green having run no test at all. This collects from the working tree --
    the tree the workflow itself checks out -- and fails on a zero count.

    Two failures are distinguished deliberately, because conflating them is
    how a check starts lying:

    * **VACUOUS** -- the selector is well-formed and selects nothing. This is
      the defect this exists to catch.
    * **COULD NOT VERIFY** -- collection itself failed, e.g. the job running
      this check lacks the dependency the test module imports. That is not
      evidence the selector is vacuous, and saying so would be a false
      positive; but it is also not a pass, so it fails loudly instead.
    """
    targets, passthrough = _collection_args(invocation["argv"])
    assert targets, f"selector with no test target: {invocation['argv']}"

    cmd = [sys.executable, "-m", "pytest", *passthrough, *targets]
    for flag, value in invocation["selectors"]:
        cmd += [flag, value]
    cmd += ["--collect-only", "-q"]

    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    collected = [
        line
        for line in proc.stdout.splitlines()
        if "::" in line and not line.startswith(("=", "-", " "))
    ]

    where = f"{invocation['workflow']}::{invocation['job']}::{invocation['step']}"

    if proc.returncode == 0 and collected:
        return

    # pytest exit 5 is "no tests collected" -- the one unambiguous signal that
    # a selector matched nothing. Every other non-zero code means collection
    # itself broke (2 interrupted, 3 internal, 4 usage), which is *not* evidence
    # of vacuity. Treating those as VACUOUS would be a check that invents the
    # defect it is meant to find.
    if proc.returncode == 5 or (proc.returncode == 0 and not collected):
        pytest.fail(
            f"VACUOUS SELECTOR: {where} selects zero tests with "
            f"{invocation['selectors']} over {targets} (pytest exit "
            f"{proc.returncode}). The job would pass without running anything.\n"
            f"$ {' '.join(cmd)}\n{proc.stdout[-1500:]}",
            pytrace=False,
        )

    pytest.fail(
        f"COULD NOT VERIFY {where}: pytest exited {proc.returncode} after "
        f"collecting {len(collected)} node id(s). This is a collection error, "
        f"not evidence that the selector is vacuous -- most often the job "
        f"running this check is missing a dependency the test module imports.\n"
        f"$ {' '.join(cmd)}\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}",
        pytrace=False,
    )


def test_the_selector_check_itself_is_not_vacuous():
    """The vacuity check must actually have selectors to check.

    Without this, deleting every `-k`/`-m` from every workflow would turn this
    module green rather than loud -- the same failure mode it exists to catch.
    """
    invocations = workflow_pytest_invocations()
    selected = [i for i in invocations if i["selectors"]]
    assert selected, "no workflow passes a -k/-m selector; the check below is inert"
    assert len(invocations) >= 5, (
        f"only {len(invocations)} pytest invocations found across all workflows; "
        "the extractor has probably stopped recognising the real spellings"
    )


# --------------------------------------------------------------------------
# 3. Retired runner labels
# --------------------------------------------------------------------------

# Runner labels GitHub documents for *public* repositories, from
# docs.github.com "GitHub-hosted runners reference". A label outside this set
# is not merely deprecated: GitHub never schedules it, so the job queues
# forever. `macos-13` cost this repo a run that sat 35/36-complete for two days.
PUBLIC_RUNNER_LABELS = frozenset(
    {
        "ubuntu-slim",
        "ubuntu-latest",
        "ubuntu-22.04",
        "ubuntu-24.04",
        "ubuntu-26.04",
        "ubuntu-22.04-arm",
        "ubuntu-24.04-arm",
        "ubuntu-26.04-arm",
        "windows-latest",
        "windows-2022",
        "windows-2025",
        "windows-11-arm",
        "windows-11-vs2026-arm64",
        "macos-latest",
        "macos-14",
        "macos-15",
        "macos-15-intel",
        "macos-26",
        "macos-26-intel",
        "macos-26-arm64",
    }
)


def _runner_labels() -> list[tuple[str, str]]:
    """Every concrete runner label a workflow asks for, with its job."""
    found = []
    for path in workflow_files():
        doc = parse_workflow_or_none(path)
        if not isinstance(doc, dict):
            continue
        for job_name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            runs_on = job.get("runs-on")
            if isinstance(runs_on, str):
                found.append((f"{path.name}:{job_name}", runs_on))
            elif isinstance(runs_on, list):
                for label in runs_on:
                    found.append((f"{path.name}:{job_name}", str(label)))
            matrix = (job.get("strategy") or {}).get("matrix") or {}
            for entry in matrix.get("include") or []:
                if isinstance(entry, dict) and isinstance(entry.get("os"), str):
                    found.append((f"{path.name}:{job_name}", entry["os"]))
    return found


def test_no_workflow_requests_a_retired_runner_label():
    """A job pinned to a retired image queues forever and never runs.

    Unlike most workflow mistakes this fails *open*: the run is created, the
    other jobs pass, and one job sits in `queued` indefinitely, so the run
    never reports a conclusion. That is precisely the 2026-09-29 stall.
    """
    offenders = [
        f"{where} -> {label!r}"
        for where, label in _runner_labels()
        # `${{ matrix.os }}` is indirect: its concrete values are collected from
        # `strategy.matrix.include[].os` above and checked there.
        if "${{" not in label and label not in PUBLIC_RUNNER_LABELS
    ]
    assert not offenders, (
        "retired or unknown runner labels; GitHub will never schedule these "
        "jobs and the containing run will never finish:\n  "
        + "\n  ".join(offenders)
        + "\nSee docs.github.com/en/actions/reference/runners/github-hosted-runners"
    )
