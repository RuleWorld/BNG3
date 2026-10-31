"""Cheap CI scheduling contracts: fail before paying for native builds.

These are framework checks, not scientific qualification. Controlled mutations
prove that a dangling dependency or bypassed gate cannot silently pass.
"""

from copy import deepcopy

import pytest

from tests.workflow_yaml import REPO, parse_workflow, workflow_files

PR_WORKFLOWS = (
    "ci.yml",
    "parity.yml",
    "formal.yml",
    "sbml-conformance.yml",
    "codeql.yml",
    "autofix.yml",
)
GROUP = "${{ github.workflow }}-${{ github.event_name }}-${{ github.event.pull_request.number || github.run_id }}"
PR_ONLY = "${{ github.event_name == 'pull_request' }}"


def ancestors(jobs, job_id, visiting=()):
    """Walk needs, rejecting unknown jobs and cycles with the offending path."""
    assert job_id in jobs, f"unknown job: {job_id}"
    assert (
        job_id not in visiting
    ), f"dependency cycle: {' -> '.join((*visiting, job_id))}"
    needs = jobs[job_id].get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    result = set(needs)
    for parent in needs:
        result.update(ancestors(jobs, parent, (*visiting, job_id)))
    return result


def assert_builds_are_gated(jobs):
    for job in (
        "cpp-build",
        "cpp-asan",
        "cpp-cuda",
        "batch-ssa-cpu-reference",
        "python-jax",
    ):
        assert {"lint", "harness"} <= ancestors(
            jobs, job
        ), f"{job} bypasses cheap gates"
        assert not jobs[job].get("if"), f"{job} must respect failed needs"


@pytest.mark.parametrize("name", PR_WORKFLOWS)
def test_only_superseded_pr_runs_are_cancelled(name):
    policy = parse_workflow(REPO / ".github/workflows" / name)["concurrency"]
    # PR number stays stable across pushes; event + run_id isolates dispatch,
    # scheduled and main evidence, even two dispatches of the same exact SHA.
    assert policy["group"] == GROUP
    assert policy["cancel-in-progress"] == PR_ONLY


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_every_workflow_dependency_exists_and_is_acyclic(path):
    jobs = parse_workflow(path)["jobs"]
    for job_id in jobs:
        ancestors(jobs, job_id)


@pytest.mark.parametrize(
    "jobs, message",
    [
        ({"build": {"needs": "typo"}}, "unknown job: typo"),
        ({"build": {"needs": "build"}}, "dependency cycle: build -> build"),
        ({"a": {"needs": "b"}, "b": {"needs": "a"}}, "dependency cycle: a -> b -> a"),
    ],
)
def test_dependency_guard_rejects_malformed_graphs(jobs, message):
    with pytest.raises(AssertionError, match=message):
        ancestors(jobs, next(iter(jobs)))


def test_expensive_ci_builds_wait_for_cheap_contracts():
    assert_builds_are_gated(parse_workflow(REPO / ".github/workflows/ci.yml")["jobs"])


@pytest.mark.parametrize("mutation", ["remove_lint", "remove_harness", "always"])
def test_build_gate_guard_detects_bypass_mutations(mutation):
    jobs = deepcopy(parse_workflow(REPO / ".github/workflows/ci.yml")["jobs"])
    # Start with a valid minimal gate, then remove one required condition.
    for name in (
        "cpp-build",
        "cpp-asan",
        "cpp-cuda",
        "batch-ssa-cpu-reference",
        "python-jax",
    ):
        jobs[name]["needs"] = ["lint", "harness"]
    if mutation == "always":
        jobs["cpp-build"]["if"] = "always()"
    else:
        jobs["cpp-build"]["needs"].remove(mutation.removeprefix("remove_"))
    with pytest.raises(
        AssertionError, match="bypasses cheap gates|respect failed needs"
    ):
        assert_builds_are_gated(jobs)


def test_integration_checks_precede_python_fanout_and_sdist():
    jobs = parse_workflow(REPO / ".github/workflows/ci.yml")["jobs"]
    assert "python-test" not in ancestors(jobs, "python-integration")
    assert "python-integration" in ancestors(jobs, "python-test")
    assert "python-integration" in ancestors(jobs, "package-smoke")
    assert "python-test" not in ancestors(jobs, "package-smoke")
    matrix = jobs["python-test"]["strategy"]["matrix"]
    assert set(matrix["os"]) == {"ubuntu-22.04", "macos-15", "windows-2022"}
    assert matrix["python-version"] == ["3.9", "3.10", "3.11", "3.12", "3.13", "3.14"]


@pytest.mark.parametrize("job_id", ["cpp-build", "python-test", "validation"])
def test_pr_matrices_stop_after_first_failure(job_id):
    jobs = parse_workflow(REPO / ".github/workflows/ci.yml")["jobs"]
    assert jobs[job_id]["strategy"]["fail-fast"] == PR_ONLY


@pytest.mark.parametrize("name", ["ci.yml", "codeql.yml", "formal.yml", "autofix.yml"])
def test_per_commit_jobs_have_explicit_time_budgets(name):
    jobs = parse_workflow(REPO / ".github/workflows" / name)["jobs"]
    for job_id, job in jobs.items():
        if "uses" in job:
            continue
        timeout = job.get("timeout-minutes")
        assert (
            isinstance(timeout, int) and 0 < timeout <= 90
        ), f"{name}:{job_id} has no bounded runtime"


def test_python39_uses_binary_libsbml_on_every_os():
    jobs = parse_workflow(REPO / ".github/workflows/ci.yml")["jobs"]
    installs = [
        s for s in jobs["python-test"]["steps"] if "python-libsbml" in s.get("run", "")
    ]
    assert len(installs) == 2
    old_python = next(s for s in installs if "== '3.9'" in s.get("if", ""))
    assert old_python["if"] == "matrix.python-version == '3.9'"
    assert "python-libsbml==5.21.1" in old_python["run"]
    assert all("--only-binary=:all:" in s["run"] for s in installs)


def test_native_test_steps_fail_on_an_empty_selection():
    jobs = parse_workflow(REPO / ".github/workflows/ci.yml")["jobs"]
    commands = [
        s["run"]
        for job in jobs.values()
        for s in job.get("steps", [])
        if "ctest " in s.get("run", "")
    ]
    assert commands
    assert all("--no-tests=error" in command for command in commands)
    assert all("--stop-on-failure" in command for command in commands)
