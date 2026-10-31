"""Acceptance contracts for the Python package CI installation path."""

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

from tests.workflow_yaml import (
    concurrency_of,
    job_matrix_values,
    job_subtree_text,
    parse_workflow,
)

from scripts.ci import validate_sbml_test_suite
from scripts.validate import (
    load_skip_models,
    load_validation_manifest,
    load_validation_molecule_name_aliases,
    run_validation,
    write_validation_summary,
)
from scripts.cross_validate import (
    compare_network_files,
    compare_structural_xml,
    diff_structural_xml,
    format_structural_xml_differences,
    _network_only_text,
    _stage_model,
    run_cross_validation,
    write_cross_validation_summary,
)
from scripts.ci.disable_unreachable_microsoft_apt_source import (
    disable_unreachable_sources,
)

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "release.yml"
WEEKLY_WORKFLOW = REPO / ".github" / "workflows" / "weekly.yml"
REFERENCE_EXCLUSIONS = REPO / "tests" / "validation" / "reference_exclusions.json"
VALIDATION_MANIFEST = REPO / "tests" / "validation" / "validation_manifest.json"
VALIDATE_DIR = REPO / "tests" / "validation" / "Validate"
PARITY_WORKFLOW = REPO / ".github" / "workflows" / "parity.yml"
FORMAL_WORKFLOW = REPO / ".github" / "workflows" / "formal.yml"
UPSTREAMS_LOCK = REPO / "provenance" / "upstreams.lock.yml"
SSA_ENSEMBLE_MANIFEST = (
    REPO / "tests" / "validation" / "evidence" / "bng2-ssa-ensembles" / "manifest.json"
)

CPP_CMAKE = REPO / "cpp" / "CMakeLists.txt"
TOP_LEVEL_CMAKE = REPO / "CMakeLists.txt"


@pytest.mark.parametrize("job_id", ["cpp-build", "python-test", "python-integration"])
def test_semantic_test_jobs_retain_reports_on_failure(job_id):
    steps = parse_workflow(CI_WORKFLOW)["jobs"][job_id]["steps"]
    report_tests = [
        step
        for step in steps
        if (
            "ctest " in step.get("run", "")
            or "pytest tests/python" in step.get("run", "")
        )
    ]
    assert report_tests, f"{job_id}: no semantic tests selected"
    for step in report_tests:
        command = step["run"]
        assert "--output-junit" in command or "--junitxml=" in command, step["name"]
    uploads = [
        step
        for step in steps
        if step.get("uses", "").startswith("actions/upload-artifact@")
        and "test-results" in step.get("with", {}).get("name", "")
    ]
    assert len(uploads) == 1, f"{job_id}: missing test result artifact"
    upload = uploads[0]
    assert upload.get("if") == "always()"
    paths = upload["with"]["path"].split()
    reports = []
    for step in report_tests:
        match = re.search(r"(?:--output-junit\s+|--junitxml=)(\S+)", step["run"])
        assert match, f"{step['name']}: no report destination"
        report = match.group(1)
        reports.append(report)
        expected_path = f"build/{report}" if job_id == "cpp-build" else report
        assert expected_path in paths, f"report {expected_path} is not retained"
    assert len(set(reports)) == len(reports), "test invocations overwrite their reports"
    assert steps.index(upload) > max(steps.index(step) for step in report_tests)
    if job_id == "cpp-build":
        assert "build/Testing/Temporary/" in paths


def _run_provenance_command(script, *arguments):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / script), *arguments],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def test_release_provenance_accepts_current_lock_and_ratchet():
    result = _run_provenance_command("validate_provenance.py", "--require-approved")
    assert result.returncode == 0, result.stderr

    result = _run_provenance_command("check_provenance_ratchet.py")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("pin", "sources.bng3.revision must be a full lowercase Git SHA"),
        ("hash", "python_lock.digest does not match the lock file bytes"),
        ("acceptance", "strict gate requires sources.bng3.status=accepted"),
    ],
    ids=["pin", "hash", "acceptance"],
)
def test_release_provenance_negative_rejects_mutated_lock(
    tmp_path, mutation, expected_error
):
    lock = json.loads(UPSTREAMS_LOCK.read_text(encoding="utf-8"))
    if mutation == "pin":
        lock["sources"]["bng3"]["revision"] = "bad"
    elif mutation == "hash":
        lock["dependencies"]["python_lock"]["digest"] = "sha256:" + "0" * 64
    else:
        lock["sources"]["bng3"]["status"] = "observed"

    candidate = tmp_path / f"upstreams-{mutation}.lock.yml"
    candidate.write_text(json.dumps(lock), encoding="utf-8")
    result = _run_provenance_command(
        "validate_provenance.py", "--lock", str(candidate), "--require-approved"
    )
    assert result.returncode == 1
    assert expected_error in result.stderr

    result = _run_provenance_command(
        "check_provenance_ratchet.py", "--lock", str(candidate)
    )
    assert result.returncode == 1
    assert expected_error in result.stderr


def test_release_provenance_negative_rejects_stale_ratchet(tmp_path):
    candidate = tmp_path / "stale-ratchet.json"
    ratchet = json.loads(
        (REPO / "provenance" / "strict-gate-ratchet.json").read_text(encoding="utf-8")
    )
    ratchet["errors"] = ["strict gate requires an approved baseline"]
    candidate.write_text(
        json.dumps(ratchet),
        encoding="utf-8",
    )
    result = _run_provenance_command(
        "check_provenance_ratchet.py", "--ratchet", str(candidate)
    )
    assert result.returncode == 1
    assert "recorded blocker(s) no longer raised" in result.stderr


def test_release_obligation_179_executes_strict_gate_before_release_evidence():
    release = parse_workflow(RELEASE_WORKFLOW)
    steps = release["jobs"]["qualify"]["steps"]
    provenance_step = next(
        (step for step in steps if step.get("id") == "provenance"), None
    )
    assert provenance_step is not None
    commands = [
        line.strip() for line in provenance_step["run"].splitlines() if line.strip()
    ]
    assert commands == [
        "python scripts/validate_provenance.py --require-approved",
        "python scripts/check_provenance_ratchet.py",
    ]
    assert steps.index(provenance_step) < next(
        index
        for index, step in enumerate(steps)
        if step.get("name")
        == "Require the exact-main weekly mutation artifact and ratchet"
    )

    result = subprocess.run(
        ["bash", "-e", "-c", provenance_step["run"]],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_issue141_lifecycle_exposes_repo_root_for_tests_package_import():
    job = job_subtree_text(CI_WORKFLOW, "python-native-lifecycle")
    steps = parse_workflow(CI_WORKFLOW)["jobs"]["python-native-lifecycle"]["steps"]
    reproduce = next(
        step
        for step in steps
        if "reproduce_issue141_lifecycle.py" in step.get("run", "")
    )
    assert reproduce.get("env", {}).get("PYTHONPATH") == "python:build/cpp:."
    assert "tests/validation/reproduce_issue141_lifecycle.py" in job
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(("python", "."))
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from tests.validation import integrated_cases, integrated_protocol",
        ],
        cwd=REPO,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_issue141_python_native_lifecycle_uses_stock_python_without_asan_runtime_mixing():
    job = job_subtree_text(CI_WORKFLOW, "python-native-lifecycle")
    steps = parse_workflow(CI_WORKFLOW)["jobs"]["python-native-lifecycle"]["steps"]
    reproduce = next(
        step
        for step in steps
        if "reproduce_issue141_lifecycle.py" in step.get("run", "")
    )
    assert "-fsanitize=address" not in job, (
        "the setup-python interpreter and NumPy wheels are not ASan-instrumented; "
        "keep Python lifecycle checks outside the native ASan process"
    )
    assert "ASAN_OPTIONS" not in reproduce.get("env", {})
    assert "LD_PRELOAD" not in reproduce.get("run", "")
    assert "python tests/validation/reproduce_issue141_lifecycle.py" in reproduce["run"]


# The flags that embed a second copy of the C++ runtime into a binary. They are
# correct for a CLI executable, which owns its process, and wrong for the
# Python extension, which is loaded into a process someone else owns.
STATIC_RUNTIME_LINK_FLAGS = ("-static-libstdc++", "-static-libgcc")


def _python_extension_target_block() -> str:
    """The cpp/CMakeLists.txt text that declares the `_bionetgen_cpp` module."""

    cmake = CPP_CMAKE.read_text(encoding="utf-8")
    start = cmake.index("pybind11_add_module(_bionetgen_cpp")
    end = cmake.index("\nendif()", start)
    return cmake[start:end]


def _link_flags_applied_to(target: str, cmake_text: str) -> list[str]:
    """Flags CMake would append to `target`'s own link command, in any form.

    Covers the four ways a target can acquire link flags: per-target
    target_link_options, per-target target_link_libraries, the LINK_FLAGS
    target property, and the directory-level *_LINKER_FLAGS variables that
    apply to that target's library kind.
    """

    flags: list[str] = []
    # target_link_options(<target> ...) / target_link_libraries(<target> ...)
    for command_name in ("target_link_options", "target_link_libraries"):
        for call in re.finditer(
            rf"(?ms)^[ \t]*{command_name}\(\s*{re.escape(target)}\b(.*?)\)",
            cmake_text,
        ):
            flags += re.findall(r"-static[-\w+]*", call.group(1))
    # set_target_properties(<target> ... LINK_FLAGS "...")
    for properties in re.finditer(
        rf"(?ms)^[ \t]*set_target_properties\(\s*{re.escape(target)}\b(.*?)(?:\n[ \t]*\)|\))",
        cmake_text,
    ):
        for value in re.findall(r"LINK_FLAGS\s+\"?([^\"\n]+)\"?", properties.group(1)):
            flags += re.findall(r"-static[-\w+]*", value)
    return flags


def test_python_extension_never_statically_links_the_cxx_runtime():
    """The extension must resolve libstdc++ from the process, not embed one.

    A statically linked C++ runtime inside `_bionetgen_cpp` coexists with the
    `libstdc++.so.6` that the host interpreter already has mapped -- SciPy's C++
    modules map it too. Two independent runtimes in one process means two
    independent sets of locale facet tables, so `std::ostream` dispatches a
    numeric format through the wrong facet and the process segfaults inside
    `Expression::toString()` on the first `ostringstream << double`. This
    shipped green through sixteen CI runs because the crash needs a co-loaded
    C++ extension, which the build job did not have.

    CLI executables are unaffected and may keep the static runtime: they own
    their process. That asymmetry is why the check has to be about the module
    target specifically, and not about the flags existing in the build.
    """

    block = _python_extension_target_block()
    static_flags = [
        flag
        for flag in _link_flags_applied_to("_bionetgen_cpp", block)
        if flag.startswith(STATIC_RUNTIME_LINK_FLAGS)
    ]
    assert not static_flags, (
        f"`_bionetgen_cpp` is given {static_flags} by cpp/CMakeLists.txt. The "
        "Python extension runs inside a host interpreter that may already have "
        "libstdc++.so.6 mapped (SciPy's C++ modules do), so a statically linked "
        "runtime puts two C++ runtimes in one process: duplicated locale facet "
        "tables, then a segfault in std::ostream numeric formatting. Link the "
        "runtime dynamically for the module and leave CMAKE_EXE_LINKER_FLAGS "
        "alone for the CLI executables, which own their process. See PR #30."
    )

    # A SHARED module would inherit CMAKE_SHARED_LINKER_FLAGS, which does carry
    # the static runtime at the top level. pybind11_add_module defaults to
    # MODULE, so this only trips if someone reaches for the SHARED variant.
    assert "SHARED" not in block, (
        "`pybind11_add_module(_bionetgen_cpp ... SHARED ...)` makes the "
        "extension a SHARED library, and SHARED targets inherit "
        "CMAKE_SHARED_LINKER_FLAGS, which carries -static-libstdc++ at the top "
        "level. Use the MODULE default (or pass MODULE explicitly) so the "
        "extension stays out of that path."
    )


def test_cli_executables_still_may_link_the_cxx_runtime_statically():
    """The module restriction must not tempt someone into a global reversal.

    The static runtime is load-bearing for the shipped `bng_cpp` and `NFsim`
    binaries, which run on machines where a system libstdc++ may be too old.
    A well-meaning "clean up the inconsistency" edit that moves the flags out
    of CMAKE_EXE_LINKER_FLAGS would trade a documented extension crash for an
    unmeasured portability regression, so the executable path is pinned too.
    """

    top_level = TOP_LEVEL_CMAKE.read_text(encoding="utf-8")
    for flag in STATIC_RUNTIME_LINK_FLAGS:
        assert re.search(
            rf"CMAKE_EXE_LINKER_FLAGS[^\n]*{re.escape(flag)}", top_level
        ), (
            f"{flag} is no longer applied through CMAKE_EXE_LINKER_FLAGS. The "
            "module contract in "
            "test_python_extension_never_statically_links_the_cxx_runtime is "
            "about the extension target only; if the executables genuinely need "
            "to give up their static runtime, that is a separate change to "
            "justify, not a silent consequence of this one."
        )


def test_batch_ssa_cpu_reference_parity_gate_runs_in_ci():
    """The CPU batch-SSA reference gate must exist and run on every PR head.

    This is the job that would have caught the segfault: it loads the freshly
    built extension into the same interpreter that imported SciPy. It was
    never green, so the extension's runtime-linkage defect shipped behind it.
    The gate is hardware-independent by construction, which is what makes it a
    required check rather than an incidental one.
    """

    job = _workflow_job("batch-ssa-cpu-reference")
    assert "Batch SSA CPU reference parity" in job
    assert "tests/test_batch_ssa_statistical_parity.py --mode cpu" in job
    assert "-DBUILD_PYTHON_BINDINGS=ON" in job
    # The build must produce the module the gate imports; without this the job
    # would go green having tested nothing.
    assert "build/cpp/_bionetgen_cpp" in job
    assert "|| true" not in job
    assert "continue-on-error" not in job
    # --mode all would drag in the GPU comparison, which skips without a
    # backend; --mode cpu is the hardware-independent claim being made.
    assert "--mode cpu" in job
    assert "--mode all" not in job


def test_cmake_link_flag_scan_detects_each_way_a_target_can_acquire_flags():
    """Guard the guard: the static-flag scan must actually see a static flag.

    `_link_flags_applied_to` is the mechanism the extension contract rests on.
    If its extraction silently stopped matching -- a renamed command, a
    reformatted call -- it would report an empty flag list and the extension
    contract would pass no matter what the build did.
    """

    assert _link_flags_applied_to(
        "_probe_link_options",
        "target_link_options(_probe_link_options PRIVATE -static-libgcc)",
    ) == ["-static-libgcc"]
    assert _link_flags_applied_to(
        "_probe_link_flags",
        'set_target_properties(_probe_link_flags PROPERTIES LINK_FLAGS "-static-libstdc++")',
    ) == ["-static-libstdc++"]
    assert _link_flags_applied_to(
        "_probe_link_libraries",
        "target_link_libraries(_probe_link_libraries PRIVATE -static-libstdc++)",
    ) == ["-static-libstdc++"]
    # A multi-line call spanning several flags must be captured whole, not
    # just up to the first closing paren.
    assert _link_flags_applied_to(
        "_probe_multiline",
        "target_link_options(_probe_multiline PRIVATE\n    -static-libgcc\n"
        "    -static-libstdc++\n)",
    ) == ["-static-libgcc", "-static-libstdc++"]
    assert (
        _link_flags_applied_to(
            "_absent_target", TOP_LEVEL_CMAKE.read_text(encoding="utf-8")
        )
        == []
    )


def test_ssts_report_source_provenance_records_revision_and_tracked_changes(
    tmp_path: Path,
):
    repo = tmp_path / "source"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "SSTS provenance test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "config",
            "user.email",
            "ssts-provenance@example.invalid",
        ],
        check=True,
    )
    source = repo / "model.py"
    source.write_text("model = True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "model.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()

    clean = validate_sbml_test_suite._repository_provenance(repo)

    assert clean["bng3_commit"] == revision
    assert clean["bng3_tracked_worktree_clean"] is True
    assert clean["bng3_worktree_clean_for_report"] is True
    assert clean["bng3_changed_files"] == []
    assert clean["bng3_source_diff_sha256"]
    clean_digest = clean["bng3_source_diff_sha256"]

    source.write_text("model = False\n", encoding="utf-8")
    dirty = validate_sbml_test_suite._repository_provenance(repo)

    assert dirty["bng3_commit"] == revision
    assert dirty["bng3_tracked_worktree_clean"] is False
    assert dirty["bng3_worktree_clean_for_report"] is False
    assert dirty["bng3_changed_files"] == ["model.py"]
    assert dirty["bng3_source_diff_sha256"] != clean_digest


def test_reconciliation_ledger_test_references_stay_live():
    """The upstream map must not retain stale pytest/CTest/Catch2 evidence."""
    from scripts.validate_reconciliation_tests import (
        load_ledgers,
        validate_test_references,
    )

    ledgers = load_ledgers()
    assert {ledger["source"] for _, ledger in ledgers} == {
        "bionetgen",
        "nfsim",
        "pybionetgen",
    }, "all locked upstream reconciliation ledgers must be checked"
    assert validate_test_references(ledgers) == []


def _locked_ssts_checkout(tmp_path: Path) -> tuple[Path, Path, str]:
    suite = tmp_path / "suite"
    suite.mkdir()
    subprocess.run(["git", "-C", str(suite), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(suite), "config", "user.name", "SSTS test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(suite), "config", "user.email", "ssts@example.invalid"],
        check=True,
    )
    (suite / "README.md").write_text("locked suite\n", encoding="utf-8")
    for category in ("semantic", "stochastic"):
        case_dir = suite / "cases" / category / "00001"
        case_dir.mkdir(parents=True)
        (case_dir / "00001-sbml-l3v2.xml").write_text("<sbml/>\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(suite), "add", "README.md", "cases"], check=True)
    subprocess.run(
        ["git", "-C", str(suite), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(suite), "rev-parse", "HEAD"], text=True
    ).strip()
    repository = "https://github.com/sbmlteam/sbml-test-suite.git"
    subprocess.run(
        ["git", "-C", str(suite), "remote", "add", "origin", repository],
        check=True,
    )
    lock = tmp_path / "upstreams.lock.yml"
    lock.write_text(
        json.dumps(
            {
                "sources": {
                    "sbml-test-suite": {
                        "repository": repository,
                        "branch": "3.5.0",
                        "revision": revision,
                        "role": "official-validation-corpus-not-oracle",
                        "status": "observed",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return suite, lock, revision


def test_ssts_validate_only_accepts_the_clean_locked_checkout(tmp_path: Path):
    suite, lock, revision = _locked_ssts_checkout(tmp_path)
    command = [
        sys.executable,
        str(REPO / "scripts" / "ci" / "validate_sbml_test_suite.py"),
        "--suite-dir",
        str(suite),
        "--lock",
        str(lock),
        "--validate-only",
    ]

    result = subprocess.run(command, cwd=REPO, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "status": "passed",
        "validate_only": True,
        "repository": "https://github.com/sbmlteam/sbml-test-suite.git",
        "revision": revision,
        "source_lock_status": "observed",
        "source_lock_path": str(lock.resolve()),
        "source_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "clean": True,
    }


def test_pytest_tree_does_not_depend_on_an_external_sbml_suite_checkout():
    """A pytest skip must not stand in for semantic coverage in the CI job.

    The ``pytest tests/python -k atomizer`` job neither clones the official
    SBML Test Suite nor sets a suite directory, so a test that reads the
    suite and skips when it is absent would pass vacuously in the job most
    contributors run.  The suite itself is exercised by
    ``scripts/ci/validate_sbml_test_suite.py`` in the ``sbml-conformance``
    workflow; the pytest tree stays independent of it.
    """

    markers = ("SBML_TEST_SUITE_DIR", "bng3-ssts", "cases/semantic", "cases/stochastic")
    offenders = []
    for path in sorted((REPO / "tests" / "python").rglob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in markers):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, (
        "tests/python must not read the official SBML Test Suite checkout: "
        f"{offenders}"
    )


def test_ssts_runner_rejects_revision_mismatch_before_case_execution(tmp_path: Path):
    suite, lock, _revision = _locked_ssts_checkout(tmp_path)
    document = json.loads(lock.read_text(encoding="utf-8"))
    document["sources"]["sbml-test-suite"]["revision"] = "a" * 40
    lock.write_text(json.dumps(document), encoding="utf-8")
    report = tmp_path / "report.json"
    command = [
        sys.executable,
        str(REPO / "scripts" / "ci" / "validate_sbml_test_suite.py"),
        "--suite-dir",
        str(suite),
        "--lock",
        str(lock),
        "--json",
        str(report),
        "--categories",
        "semantic",
    ]

    result = subprocess.run(command, cwd=REPO, capture_output=True, text=True)

    assert result.returncode == 1
    assert "suite revision mismatch" in result.stderr
    assert not report.exists()


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (("dirty", "dirty"), ("origin", "origin mismatch")),
)
def test_ssts_checkout_preflight_rejects_dirty_or_wrong_origin(
    tmp_path: Path, mutation: str, expected_error: str
):
    suite, lock, _revision = _locked_ssts_checkout(tmp_path)
    if mutation == "dirty":
        (suite / "untracked.txt").write_text(
            "not a locked checkout\n", encoding="utf-8"
        )
    else:
        subprocess.run(
            [
                "git",
                "-C",
                str(suite),
                "remote",
                "set-url",
                "origin",
                "https://example.com/other.git",
            ],
            check=True,
        )

    with pytest.raises(validate_sbml_test_suite.SuiteLockError, match=expected_error):
        validate_sbml_test_suite._validate_suite_checkout(suite, lock)


def test_ssts_checkout_preflight_rejects_missing_locked_case_tree(tmp_path: Path):
    suite, lock, _revision = _locked_ssts_checkout(tmp_path)
    missing_case_file = "cases/stochastic/00001/00001-sbml-l3v2.xml"
    subprocess.run(
        ["git", "-C", str(suite), "update-index", "--skip-worktree", missing_case_file],
        check=True,
    )
    (suite / missing_case_file).unlink()

    assert (
        subprocess.check_output(
            ["git", "-C", str(suite), "status", "--porcelain"], text=True
        ).strip()
        == ""
    )
    with pytest.raises(validate_sbml_test_suite.SuiteLockError, match="case tree"):
        validate_sbml_test_suite._validate_suite_checkout(suite, lock)


@pytest.mark.parametrize("index_flag", ("--skip-worktree", "--assume-unchanged"))
def test_ssts_checkout_preflight_rejects_case_edits_hidden_by_git_flags(
    tmp_path: Path, index_flag: str
):
    suite, lock, _revision = _locked_ssts_checkout(tmp_path)
    case_file = "cases/semantic/00001/00001-sbml-l3v2.xml"
    subprocess.run(
        ["git", "-C", str(suite), "update-index", index_flag, case_file],
        check=True,
    )
    (suite / case_file).write_text(
        "<sbml>modified after locked commit</sbml>\n", encoding="utf-8"
    )

    assert (
        subprocess.check_output(
            ["git", "-C", str(suite), "status", "--porcelain"], text=True
        ).strip()
        == ""
    )
    with pytest.raises(validate_sbml_test_suite.SuiteLockError, match="index flags"):
        validate_sbml_test_suite._validate_suite_checkout(suite, lock)


def test_ssts_missing_case_tree_writes_incomplete_report(tmp_path: Path):
    suite, lock, _revision = _locked_ssts_checkout(tmp_path)
    missing_case_file = "cases/stochastic/00001/00001-sbml-l3v2.xml"
    subprocess.run(
        ["git", "-C", str(suite), "update-index", "--skip-worktree", missing_case_file],
        check=True,
    )
    (suite / missing_case_file).unlink()
    report = tmp_path / "incomplete-report.json"
    command = [
        sys.executable,
        str(REPO / "scripts" / "ci" / "validate_sbml_test_suite.py"),
        "--suite-dir",
        str(suite),
        "--lock",
        str(lock),
        "--json",
        str(report),
        "--categories",
        "semantic",
    ]

    result = subprocess.run(command, cwd=REPO, capture_output=True, text=True)

    assert result.returncode == 1
    assert "case tree" in result.stderr
    incomplete = json.loads(report.read_text(encoding="utf-8"))
    assert incomplete["status"] == "incomplete"
    assert incomplete["preflight_status"] == "failed"
    assert incomplete["partial_run"] is True
    assert incomplete["selected_cases"] is None
    assert incomplete["core_passed"] is False
    assert incomplete["official_conformance"]["status"] == "incomplete"
    assert incomplete["official_conformance"]["passed"] is False


def test_ssts_incomplete_report_preserves_existing_output(tmp_path: Path):
    report = tmp_path / "existing-report.json"
    report.write_text('{"preserve": true}\n', encoding="utf-8")

    with pytest.raises(FileExistsError):
        validate_sbml_test_suite._write_incomplete_report(
            report, tmp_path, ["semantic", "stochastic"], "missing case data"
        )

    assert report.read_text(encoding="utf-8") == '{"preserve": true}\n'


def test_ssts_run_scope_marks_category_cohorts_partial():
    assert (
        validate_sbml_test_suite._is_partial_run(
            ["semantic", "stochastic"], max_cases=0, only_case=None
        )
        is False
    )
    assert (
        validate_sbml_test_suite._is_partial_run(
            ["semantic"], max_cases=0, only_case=None
        )
        is True
    )
    assert (
        validate_sbml_test_suite._is_partial_run(
            ["semantic", "stochastic"], max_cases=10, only_case=None
        )
        is True
    )


def test_pull_request_runs_replace_superseded_work():
    """A later PR push cancels superseded work; manual evidence stays isolated."""

    _assert_pr_concurrency(CI_WORKFLOW, "ci.yml")


def test_wheel_workflows_use_supported_platform_targets_and_test_dependencies():
    """Wheel builds must use toolchains compatible with current dependencies."""

    for workflow_path, job_name in (
        (CI_WORKFLOW, "wheels"),
        (RELEASE_WORKFLOW, "build-wheels"),
    ):
        job = _workflow_job_from(workflow_path, job_name)
        assert "pip install cibuildwheel==4.2.1" in job
        assert "CIBW_MANYLINUX_X86_64_IMAGE: manylinux_2_28" in job
        assert "CIBW_ARCHS_MACOS: ${{ matrix.macos_arch }}" in job
        assert "MACOSX_DEPLOYMENT_TARGET=${{ matrix.macos_deployment_target }}" in job
        assert (
            "DCMAKE_OSX_DEPLOYMENT_TARGET=${{ matrix.macos_deployment_target }}" in job
        )
        targets = job_matrix_values(workflow_path, job_name, "macos_deployment_target")
        # libc++ annotates every <filesystem> entry point with
        # availability(macos, introduced = 10.15), so a lower target turns
        # std::filesystem::path into a hard compile error rather than a
        # warning. That is what broke the x86_64 macOS wheel lane; a target
        # below the floor must not come back.
        below_floor = [t for t in targets if float(t) < 10.15]
        assert (
            not below_floor
        ), f"{job_name} below the <filesystem> floor: {sorted(below_floor)}"
        assert "11.0" in targets, f"{job_name} must retain its 11.0 target: {targets}"
        assert "CIBW_TEST_REQUIRES: pytest numpy click" in job
        assert "cp314-*" in job

    ci_doc = parse_workflow(CI_WORKFLOW)
    assert "workflow_dispatch" in (ci_doc.get("on") or ci_doc.get(True) or {})
    wheels = _workflow_job_from(CI_WORKFLOW, "wheels")
    assert "github.event_name == 'workflow_dispatch'" in wheels


def test_wheel_tests_smoke_the_installed_console_script():
    """The built wheel must expose a working user-facing CLI entry point."""

    for workflow_path, job_name in (
        (CI_WORKFLOW, "wheels"),
        (RELEASE_WORKFLOW, "build-wheels"),
    ):
        job = _workflow_job_from(workflow_path, job_name)
        assert "CIBW_TEST_COMMAND:" in job
        assert "bionetgen --version" in job
        assert "bionetgen --help" in job


def _workflow_job(name: str) -> str:
    return job_subtree_text(CI_WORKFLOW, name)


def _python_test_job() -> str:
    return _workflow_job("python-test")


def _workflow_job_from(path: Path, name: str) -> str:
    return job_subtree_text(path, name)


def test_lint_job_installs_ci_contract_dependencies():
    """The lint job must install dependencies required during test collection."""

    lint_job = _workflow_job_from(CI_WORKFLOW, "lint")
    for package in ("black", "ruff", "pytest", "numpy", "pyyaml"):
        assert package in lint_job
    # Linter installs must be version-pinned: an unpinned float (black
    # 26.5.1 -> 26.10.0 overnight) red-lit every open PR branch at once.
    for package in ("black", "ruff"):
        assert re.search(rf'["\']?{package}==[^ "\']+["\']?', lint_job)


def test_external_parity_workflow_is_present_and_keeps_exact_head_evidence():
    """Cross-tool checks must be independently reproducible per PR head."""

    _assert_pr_concurrency(PARITY_WORKFLOW, "parity.yml")
    parity_doc = parse_workflow(PARITY_WORKFLOW)
    assert parity_doc["env"]["BNG3_CI_STRICT_ORACLES"] == "1"
    parity_jobs = parity_doc.get("jobs") or {}
    for job in ("oracle-lock", "bng2-parity", "nfsim-parity", "pybionetgen-compat"):
        assert job in parity_jobs, f"parity.yml must define a {job} job"
    oracle_lock_doc = parity_jobs["oracle-lock"]
    oracle_lock = _workflow_job_from(PARITY_WORKFLOW, "oracle-lock")
    assert "python -m pip install pytest numpy pyyaml" in oracle_lock
    assert "scripts/ci/checkout_oracle.py --validate-only" in oracle_lock
    assert (
        "tests/validation/test_harness_paths.py::test_required_oracle_fails_in_strict_ci"
        in oracle_lock
    )
    assert (
        "tests/validation/test_harness_paths.py::test_api_fixture_fails_in_strict_ci_and_skips_locally"
        in oracle_lock
    )
    lock_step_names = [step.get("name", "") for step in oracle_lock_doc["steps"]]
    assert lock_step_names.index("Validate locked sources") < lock_step_names.index(
        "Run CI contract tests"
    )
    assert parity_jobs["bng2-parity"]["needs"] == "oracle-lock"


def _assert_pr_concurrency(path: Path, label: str) -> None:
    """Read the scheduling policy separately from source identity checks."""

    concurrency = concurrency_of(path)
    assert concurrency.get("group") == (
        "${{ github.workflow }}-${{ github.event_name }}-"
        "${{ github.event.pull_request.number || github.run_id }}"
    ), f"{label} must replace PR work and isolate non-PR evidence"
    assert concurrency.get("cancel-in-progress") == (
        "${{ github.event_name == 'pull_request' }}"
    ), f"{label} must only cancel superseded PR work"


def test_external_parity_jobs_use_pinned_oracle_checkouts_and_fail_closed():
    """No parity job may silently substitute a branch head or embedded engine."""

    workflow = PARITY_WORKFLOW.read_text(encoding="utf-8")
    for source in ("bionetgen", "nfsim", "pybionetgen"):
        assert f"--name {source}" in workflow
        assert "scripts/ci/checkout_oracle.py" in workflow
    bng2 = _workflow_job_from(PARITY_WORKFLOW, "bng2-parity")
    assert "--bng-perl" in bng2
    assert "--bng-cpp" in bng2
    assert '--summary-file "$GITHUB_STEP_SUMMARY"' in bng2
    nfsim = _workflow_job_from(PARITY_WORKFLOW, "nfsim-parity")
    assert "NFSIM_BIN" in nfsim
    assert "build/NFsim" in nfsim
    assert "tests/validation/test_parity_nfsim.py" in nfsim
    assert "build/cpp/NFsim" not in nfsim


def test_nfsim_parity_uses_regular_installed_api_and_pinned_native_oracle():
    """NFsim parity uses installed BNG3 API and the independently built oracle."""

    job_doc = parse_workflow(PARITY_WORKFLOW)["jobs"]["nfsim-parity"]
    job = _workflow_job_from(PARITY_WORKFLOW, "nfsim-parity")

    assert (job_doc.get("env") or {}).get("BNG3_PYTHON_TEST_MODE") == "installed"
    assert 'python -m pip install ".[full,dev]"' in job
    assert "pip install -e" not in job
    assert "check_python_package_identity.py" in job
    assert "test_worker_package_identity.py" in job
    assert 'PYTHONPATH="python:build/cpp"' not in job
    assert "--bng-cpp build/cpp/bng_cpp" not in job
    assert "NFSIM_BIN" in job
    assert "$RUNNER_TEMP/oracle-nfsim/build/NFsim" in job


def test_numerical_expression_export_parity_uses_one_installed_native_build():
    """Parity steps share pinned BNG2 and BNG3 identities with valid contexts."""

    job_doc = parse_workflow(PARITY_WORKFLOW)["jobs"]["bng2-parity"]
    job = _workflow_job_from(PARITY_WORKFLOW, "bng2-parity")
    steps = {step.get("id"): step for step in job_doc["steps"] if step.get("id")}

    job_env = job_doc.get("env") or {}
    compare_step = next(
        step
        for step in job_doc["steps"]
        if step.get("name") == "Compare graph-aware networks against BNG2"
    )
    compare_run = compare_step["run"]
    assert "--models-dir tests/validation/Validate" in compare_run
    for fixture in ("ANx", "hybrid_test", "test_write_sbml_multi"):
        assert f"--model {fixture}" in compare_run
    assert '--artifact-dir "$RUNNER_TEMP/bng3-authored-xml"' in compare_run
    assert any(
        step.get("uses", "").startswith("actions/upload-artifact@")
        and "bng3-authored-xml" in step.get("with", {}).get("name", "")
        for step in job_doc["steps"]
    )
    required = steps["numerical_expression_export_parity"]

    assert job_doc["timeout-minutes"] == 120
    assert job_env.get("BNG3_PYTHON_TEST_MODE") == "installed"
    assert "BNG2_PERL" not in job_env
    assert "BNGPATH" not in job_env
    for step in (compare_step, required):
        step_env = step.get("env") or {}
        assert step_env.get("BNG2_PERL") == (
            "${{ runner.temp }}/oracle-bionetgen/bng2/BNG2.pl"
        )
        assert step_env.get("BNGPATH") == "${{ runner.temp }}/oracle-bionetgen/bng2"

    assert "--name bionetgen" in job
    assert 'make -C "$network3" -f Makefile.cmake' in job
    assert "bng2/bin/run_network" in job
    assert 'sha256sum "$run_network"' in job
    assert "python -m venv .venv" in job
    assert (
        ".venv/bin/python -m pip install scikit-build-core pybind11 pytest numpy" in job
    )
    assert "--no-build-isolation" in job
    assert "--config-settings=build-dir=build" in job
    assert "--config-settings=cmake.define.BUILD_CLI=ON" in job
    assert '".[full,dev]"' in job
    assert "-DBUILD_CLI=ON" in job
    assert "-DBUILD_NFSIM_CLI=OFF" in job
    assert "-DBUILD_TESTS=OFF" in job
    assert "test -x build/cpp/bng_cpp" in job
    assert "scripts/ci/check_python_package_identity.py" in job
    assert "tests/validation/test_worker_package_identity.py" in job
    assert ".venv/bin/python -m pytest" in job
    assert "cmake --build build" not in job
    assert "PYTHONPATH=python:build/cpp" not in job

    required_run = required["run"]
    for module in (
        "tests/validation/test_parity_rhs.py",
        "tests/validation/test_parity_ode.py",
        "tests/validation/test_parity_stochastic.py",
        "tests/validation/test_export_formats.py",
    ):
        assert module in required_run
    assert '-m "not slow"' in required_run
    assert "--bng-cpp build/cpp/bng_cpp" in required_run
    assert "-q -ra" in required_run
    assert '--junitxml="$RUNNER_TEMP/issue182-required-parity.xml"' in required_run

    slow = steps["ssa_ensemble_parity"]
    assert slow["if"] == (
        "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
    )
    assert "test_parity_stochastic.py" in slow["run"]
    assert '-m "stochastic and slow"' in slow["run"]
    assert '--junitxml="$RUNNER_TEMP/issue182-ssa-ensemble.xml"' in slow["run"]
    assert slow.get("env", {}).get("BNG_ENSEMBLE_WORKERS") == "2"
    assert "continue-on-error" not in job

    report = steps["report_issue182_scope"]
    assert report["if"] == "always()"
    assert (
        "steps.numerical_expression_export_parity.outcome"
        in report["env"]["REQUIRED_OUTCOME"]
    )
    assert "steps.ssa_ensemble_parity.outcome" in report["env"]["ENSEMBLE_OUTCOME"]
    report_script = report["run"]
    assert "ElementTree.parse(path).getroot()" in report_script
    assert 'root.iter("testcase")' in report_script
    for count in ('"failures"', '"errors"', '"skipped"'):
        assert count in report_script
    assert (
        'Per-PR required modules: RHS, ODE, SSA determinism, and export (`-m "not slow"`).'
        in report_script
    )
    assert "No additional model-name filter is applied" in report_script
    assert "Scheduled/manual-only:" in report_script
    assert any(
        step.get("uses", "").startswith("actions/upload-artifact@")
        and "issue182-*.xml" in str(step.get("with", {}).get("path"))
        for step in job_doc["steps"]
    )


def test_package_identity_preflight_rejects_a_wrong_declared_source_head():
    """The strict identity gate must fail before package inspection on mismatch."""
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    wrong = "0" * 40 if actual != "0" * 40 else "1" * 40
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "ci" / "check_python_package_identity.py"),
            "--source-revision",
            wrong,
            "--require-source-head",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "does not match checked-out Git HEAD" in result.stderr
    assert wrong in result.stderr


def test_package_identity_preflight_rejects_a_wrong_product_checkout_revision():
    """The package identity record must bind to the separately checked-out product."""
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
    ).strip()
    wrong = "0" * 40 if actual != "0" * 40 else "1" * 40
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "ci" / "check_python_package_identity.py"),
            "--source-revision",
            wrong,
            "--product-checkout",
            str(REPO),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "does not match product checkout HEAD" in result.stderr
    assert wrong in result.stderr


def test_issue182_frozen_ssa_ensemble_inputs_match_the_bng2_lock():
    """The scheduled statistical lane consumes the unchanged, hashed BNG2 fixtures."""

    lock = json.loads(UPSTREAMS_LOCK.read_text(encoding="utf-8"))
    manifest = json.loads(SSA_ENSEMBLE_MANIFEST.read_text(encoding="utf-8"))
    stochastic_path = REPO / "tests" / "validation" / "test_parity_stochastic.py"
    stochastic_module = ast.parse(stochastic_path.read_text(encoding="utf-8"))
    model_assignment = next(
        node
        for node in ast.walk(stochastic_module)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "STOCH_MODELS"
            for target in node.targets
        )
    )
    assert isinstance(model_assignment.value, ast.ListComp)
    assert tuple(ast.literal_eval(model_assignment.value.generators[0].iter)) == (
        "gene_expr",
        "michment",
        "simple_system",
    )
    assert manifest["oracle"]["revision"] == lock["sources"]["bionetgen"]["revision"]
    assert manifest["generation"]["method"] == "ssa"
    assert manifest["generation"]["seed_range"] == [1, 200]
    assert manifest["generation"]["t_start"] == 0
    assert manifest["generation"]["t_end"] == 10
    assert manifest["generation"]["n_steps"] == 50
    assert manifest["generation"]["reset_before_each_member"] is True

    assert set(manifest["models"]) == {"gene_expr", "michment", "simple_system"}
    for model_name, record in manifest["models"].items():
        assert record["member_count"] == 200
        assert [member["seed"] for member in record["members"]] == list(range(1, 201))
        source = REPO / record["source_path"]
        assert (
            hashlib.sha256(source.read_bytes()).hexdigest() == record["source_sha256"]
        )

        aggregate = hashlib.sha256()
        ensemble = REPO / "tests" / "validation" / "golden" / f"{model_name}.ens"
        for member in record["members"]:
            path = ensemble / member["path"]
            contents = path.read_bytes()
            assert len(contents) == member["bytes"]
            digest = hashlib.sha256(contents).hexdigest()
            assert digest == member["sha256"]
            aggregate.update(f"{member['path']}\t{digest}\n".encode("utf-8"))
        assert aggregate.hexdigest() == record["aggregate_sha256"]


def test_formal_workflow_runs_pinned_kernel_and_nfnext_contracts():
    """The Lean reference must be kernel-checked on every PR head."""

    _assert_pr_concurrency(FORMAL_WORKFLOW, "formal.yml")
    formal = yaml.safe_dump(
        parse_workflow(FORMAL_WORKFLOW), sort_keys=False, default_flow_style=False
    )
    assert "leanprover/lean-action@38fbc41a8c28c4cbaec22d7f7de508ec2e7c0dd9" in formal
    assert "lake-package-directory: formal/lean" in formal
    assert "auto-config: false" in formal
    assert (REPO / "formal" / "lean" / "lean-toolchain").read_text(
        encoding="utf-8"
    ).strip() == ("leanprover/lean4:v4.33.1")
    assert "scripts/static_validate.py" in formal
    assert "scripts/run_nfnext_contract.sh" in formal
    assert "lake build" in formal
    assert "lake env lean tests/Smoke.lean" in formal


def test_formal_harness_mutation_selftest_is_scheduled_and_bounded():
    """Run the meta-gate periodically without slowing every PR check."""

    workflow = parse_workflow(FORMAL_WORKFLOW)
    # PyYAML's YAML 1.1 resolver exposes the unquoted `on` key as True.
    triggers = workflow[True]
    assert triggers["schedule"] == [{"cron": "23 6 * * 1"}]

    job = workflow["jobs"]["lean-kernel"]
    steps = [
        step
        for step in job["steps"]
        if step.get("name") == "Harness mutation self-test"
    ]
    assert len(steps) == 1
    assert steps[0]["if"] == (
        "github.event_name == 'schedule' || " "github.event_name == 'workflow_dispatch'"
    )
    assert steps[0]["working-directory"] == "formal/lean"
    assert steps[0]["timeout-minutes"] == 20
    assert steps[0]["run"] == "./scripts/check_harness_itself.sh"


def test_release_workflow_requires_exact_main_sha_qualification():
    """A version tag cannot publish unless all required main push gates passed."""

    qualify = _workflow_job_from(RELEASE_WORKFLOW, "qualify")
    for job_name in ("build-binaries", "build-wheels", "build-sdist"):
        assert "qualify" in _workflow_job_from(RELEASE_WORKFLOW, job_name)
    release = _workflow_job_from(RELEASE_WORKFLOW, "release")
    assert "qualify" in release
    assert "actions: read" in qualify
    assert "fetch-depth: 0" in qualify
    assert "git merge-base --is-ancestor" in qualify
    assert "gh api" in qualify
    assert "event=workflow_dispatch" in qualify
    assert "--sbml-runs-json" in qualify

    qualification_script = (
        REPO / "scripts" / "ci" / "qualify_release_candidate.py"
    ).read_text(encoding="utf-8")
    for workflow_name in ("CI", "Cross-tool parity", "Lean semantic kernel", "CodeQL"):
        assert f'"{workflow_name}"' in qualification_script
    assert '"Official SBML conformance subset"' in qualification_script


def test_release_binaries_smoke_before_packaging():
    """Release archives must contain executables that start on their runner."""

    job = _workflow_job_from(RELEASE_WORKFLOW, "build-binaries")
    smoke = job.index("Smoke test release executables")
    package = job.index("Package binaries")
    assert smoke < package
    assert "bng_cpp${{ matrix.binary_ext }} --version" in job
    assert "NFsim${{ matrix.binary_ext }} -help" in job


def test_release_run_qualification_requires_success_for_each_exact_main_push():
    from scripts.ci.qualify_release_candidate import qualify_workflow_runs

    sha = "a" * 40
    names = ["CI", "Cross-tool parity", "Lean semantic kernel", "CodeQL"]
    runs = [
        {
            "name": name,
            "head_sha": sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        for name in names
    ]

    assert qualify_workflow_runs({"workflow_runs": runs}, sha, names) == []
    assert qualify_workflow_runs({"workflow_runs": runs[:-1]}, sha, names) == ["CodeQL"]

    wrong_sha = [dict(run, head_sha="b" * 40) for run in runs]
    assert qualify_workflow_runs({"workflow_runs": wrong_sha}, sha, names) == names

    wrong_branch = [dict(run, head_branch="feature") for run in runs]
    assert qualify_workflow_runs({"workflow_runs": wrong_branch}, sha, names) == names

    pending = [dict(run, status="in_progress", conclusion=None) for run in runs]
    assert qualify_workflow_runs({"workflow_runs": pending}, sha, names) == names

    failed = [dict(run, conclusion="failure") for run in runs]
    assert qualify_workflow_runs({"workflow_runs": failed}, sha, names) == names


@pytest.mark.parametrize(
    "overrides, expected",
    [
        (None, ["Official SBML conformance subset"]),
        (
            {"status": "in_progress", "conclusion": None},
            ["Official SBML conformance subset"],
        ),
        ({"conclusion": "failure"}, ["Official SBML conformance subset"]),
        ({"head_sha": "b" * 40}, ["Official SBML conformance subset"]),
        ({"head_branch": "release"}, ["Official SBML conformance subset"]),
        ({"event": "push"}, ["Official SBML conformance subset"]),
        ({}, []),
    ],
)
def test_release_run_qualification_requires_official_sbml_manual_run(
    overrides, expected
):
    from scripts.ci.qualify_release_candidate import qualify_workflow_runs

    run = {
        "name": "Official SBML conformance subset",
        "head_sha": "a" * 40,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
    }
    if overrides is not None:
        run.update(overrides)
    payload = {"workflow_runs": [] if overrides is None else [run]}
    assert (
        qualify_workflow_runs(
            payload,
            "a" * 40,
            ["Official SBML conformance subset"],
            event="workflow_dispatch",
        )
        == expected
    )


def test_release_qualification_cli_consumes_both_workflow_payloads(tmp_path):
    sha = "a" * 40
    push_runs = [
        {
            "name": name,
            "head_sha": sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        for name in ("CI", "Cross-tool parity", "Lean semantic kernel", "CodeQL")
    ]
    push_path = tmp_path / "push.json"
    sbml_path = tmp_path / "sbml.json"
    push_path.write_text(json.dumps({"workflow_runs": push_runs}), encoding="utf-8")
    sbml_path.write_text(json.dumps({"workflow_runs": []}), encoding="utf-8")
    command = [
        sys.executable,
        str(REPO / "scripts" / "ci" / "qualify_release_candidate.py"),
        "--runs-json",
        str(push_path),
        "--sbml-runs-json",
        str(sbml_path),
        "--sha",
        sha,
    ]

    missing = subprocess.run(command, capture_output=True, text=True, check=False)
    assert missing.returncode == 1
    assert "Official SBML conformance subset" in missing.stderr

    sbml_path.write_text(
        json.dumps(
            {
                "workflow_runs": [
                    {
                        "name": "Official SBML conformance subset",
                        "head_sha": sha,
                        "head_branch": "main",
                        "event": "workflow_dispatch",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    accepted = subprocess.run(command, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0
    assert "official SBML manual evidence" in accepted.stdout
    assert "bounded" not in accepted.stdout


def test_oracle_source_loader_requires_full_locked_revisions(tmp_path):
    """The checkout helper must reject floating or malformed source refs."""

    from scripts.ci.oracle_sources import OracleSourceError, load_oracle_source

    lock = {
        "sources": {
            "nfsim": {
                "repository": "https://github.com/RuleWorld/NFsim.git",
                "revision": "a" * 40,
            }
        }
    }
    assert load_oracle_source(lock, "nfsim")["revision"] == "a" * 40
    with pytest.raises(OracleSourceError, match="full lowercase Git SHA"):
        load_oracle_source(
            {"sources": {"nfsim": {"repository": "x", "revision": "main"}}},
            "nfsim",
        )


def test_pull_request_exercises_clean_source_distribution_install():
    """PRs must exercise the sdist install path, not only an in-tree wheel."""

    job = _workflow_job("package-smoke")
    assert "needs: [python-integration]" in job
    assert not re.search(r"^\s+if:.*github\.event_name.*push", job, re.MULTILINE)
    assert "python -m build --sdist" in job
    assert "python -m venv" in job
    assert "pip install --no-deps dist/*.tar.gz" in job
    assert "check_python_package_identity.py" in job
    assert "test_thermodynamic_parse_path.py" in job
    assert re.search(r"/bin/bionetgen\"?\s+--version", job)


def test_project_declares_click_and_packaging_as_runtime_dependencies():
    project = PYPROJECT.read_text(encoding="utf-8")
    dependencies = re.search(r"(?ms)^dependencies\s*=\s*\[(?P<body>.*?)^\]", project)
    assert dependencies, "pyproject.toml must declare project dependencies"
    for package in ("click", "packaging"):
        assert re.search(
            rf"['\"]{package}(?:[<>=!~].*)?['\"]", dependencies.group("body")
        ), f"pyproject.toml must declare {package} as a runtime dependency"

    python_job = _python_test_job()
    install_lines = [
        line
        for line in python_job.splitlines()
        if re.search(r"(?:pip|python\s+-m\s+pip)\s+install", line)
    ]
    assert any(re.search(r"\bpackaging\b", line) for line in install_lines)
    package_smoke = _workflow_job("package-smoke")
    assert re.search(r"pip install numpy click packaging pytest", package_smoke)


def test_python_matrix_installs_runtime_dependencies_before_no_deps_wheel():
    """No-deps wheel install must include runtime and exercised test dependencies.

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
    assert any(
        re.search(r"\bclick(?:[<>=!~].*)?\b", line) for line in install_lines
    ), "python-test no-deps wheel path must install declared click dependency"
    assert any(re.search(r"\bscipy(?:[<>=!~].*)?\b", line) for line in install_lines)
    assert any(
        re.search(r"\blibroadrunner(?:[<>=!~].*)?\b", line) for line in install_lines
    )


def test_wheel_and_sdist_python_tests_prove_installed_package_identity():
    """Package tests must prove they load their installed native extension."""

    python_job = _python_test_job()
    assert "BNG3_PYTHON_TEST_MODE: installed" in python_job
    assert "scripts/ci/check_python_package_identity.py" in python_job
    assert "BNG3_SOURCE_REVISION" in python_job
    assert "BNG3_PR_HEAD_SHA" in python_job
    for workflow_path, job_name, step_name in (
        (CI_WORKFLOW, "python-test", "Verify installed package identity"),
        (CI_WORKFLOW, "python-integration", "Verify installed package identity"),
        (CI_WORKFLOW, "package-smoke", "Verify sdist package identity"),
    ):
        job = parse_workflow(workflow_path)["jobs"][job_name]
        job_env = job.get("env") or {}
        assert "BNG3_SOURCE_REVISION" not in job_env
        assert "BNG3_PR_HEAD_SHA" not in job_env
        step = next(s for s in job["steps"] if s.get("name") == step_name)
        step_env = step.get("env") or {}
        assert "BNG3_SOURCE_REVISION" in step_env
        assert "BNG3_PR_HEAD_SHA" in step_env

    smoke_job = _workflow_job("package-smoke")
    assert "BNG3_PYTHON_TEST_MODE: installed" in smoke_job
    assert "check_python_package_identity.py" in smoke_job
    assert "test_thermodynamic_parse_path.py" in smoke_job

    integration_job = _workflow_job("python-integration")
    assert "BNG3_PYTHON_TEST_MODE: installed" in integration_job
    assert 'pip install ".[full]"' in integration_job
    assert "pip install -e" not in integration_job
    assert "check_python_package_identity.py" in integration_job
    assert "pytest tests/test_workflow_contract.py" in integration_job


def test_python_integration_installs_jsonschema_for_bridge_test_collection():
    """The integration job must collect tests with their direct imports.

    ``test_bngir_version_bridge.py`` imports jsonschema at module scope, so
    pytest needs it even when a ``-k`` selector would exclude that test's
    functions. The package's ``full`` extra intentionally does not include
    test-only dependencies.
    """

    integration_job = _workflow_job("python-integration")
    install_lines = [
        line
        for line in integration_job.splitlines()
        if re.search(r"(?:pip|python\s+-m\s+pip)\s+install", line)
    ]
    assert any(
        re.search(r"\bjsonschema(?:[<>=!~].*)?\b", line)
        or '".[dev]"' in line
        or "'.[dev]'" in line
        for line in install_lines
    ), (
        "python-integration must install jsonschema (or the dev extra that "
        "provides it) before pytest collects tests/python/test_bngir_version_bridge.py"
    )


def test_python_test_jobs_download_the_matching_native_cli_artifact():
    """CLI-backed Python contracts must use the same-head OS binary."""

    ci = parse_workflow(CI_WORKFLOW)
    matrix_job = ci["jobs"]["python-test"]
    integration_job = ci["jobs"]["python-integration"]

    assert "cpp-build" in matrix_job["needs"]
    assert "${{ matrix.cpp_artifact }}" in _workflow_job("python-test")
    artifacts = {
        entry["os"]: entry["cpp_artifact"]
        for entry in matrix_job["strategy"]["matrix"]["include"]
    }
    assert artifacts == {
        "ubuntu-22.04": "bng_cpp-ubuntu-22.04-gcc-12",
        "macos-15": "bng_cpp-macos-15-clang-arm64",
        "windows-2022": "bng_cpp-windows-2022-msvc",
    }
    assert "${{ github.workspace }}/build/cpp/bng_cpp" in matrix_job["env"]["BNG_CPP"]
    assert "windows" in matrix_job["env"]["BNG_CPP"]

    assert "python-test" not in integration_job["needs"]
    assert "python-integration" in matrix_job["needs"]
    assert "cpp-build" in integration_job["needs"]
    assert "bng_cpp-ubuntu-22.04-gcc-12" in _workflow_job("python-integration")
    assert (
        integration_job["env"]["BNG_CPP"] == "${{ github.workspace }}/build/cpp/bng_cpp"
    )

    checker = (REPO / "scripts" / "ci" / "check_python_package_identity.py").read_text(
        encoding="utf-8"
    )
    for identity in (
        "import packaging",
        "packaging_module",
        "distribution_package",
        "package_file",
        "native_extension",
        "model_module",
        "native_extension_sha256",
        "model_native_extension",
        "source_revision",
    ):
        assert identity in checker

    thermo_test = (
        REPO / "tests" / "python" / "test_thermodynamic_parse_path.py"
    ).read_text(encoding="utf-8")
    assert "import bionetgen._bionetgen_cpp as _cpp" in thermo_test
    assert "import _bionetgen_cpp" not in thermo_test
    assert "sys.path.insert" not in thermo_test


def test_pybionetgen_compatibility_runs_against_a_regular_installed_package():
    """Editable finders and inherited source paths must not mask wheel code."""

    job = _workflow_job_from(PARITY_WORKFLOW, "pybionetgen-compat")
    assert 'python -m pip install ".[full,dev]"' in job
    assert "pip install -e" not in job
    assert "BNG3_PYTHON_TEST_MODE: installed" in job
    job_doc = parse_workflow(PARITY_WORKFLOW)["jobs"]["pybionetgen-compat"]
    assert "BNG3_SOURCE_REVISION" not in (job_doc.get("env") or {})
    compatibility_step = next(
        step
        for step in job_doc["steps"]
        if step.get("name") == "Run source-derived compatibility contracts"
    )
    checkout_step = next(
        step
        for step in job_doc["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    )
    candidate_revision = "${{ github.event.pull_request.head.sha || github.sha }}"
    assert checkout_step["with"]["ref"] == candidate_revision
    assert compatibility_step["env"]["BNG3_SOURCE_REVISION"] == candidate_revision
    assert compatibility_step["env"]["BNG3_PR_HEAD_SHA"] == candidate_revision

    checker = (REPO / "scripts" / "ci" / "check_pybionetgen_compat.py").read_text(
        encoding="utf-8"
    )
    assert "inspect_installed_package()" in checker
    assert 'env.pop("PYTHONPATH", None)' in checker
    assert 'env.pop("BNG3_SOURCE_REVISION", None)' in checker
    assert 'env.pop("BNG3_PR_HEAD_SHA", None)' in checker


def test_gdat_output_test_claims_a_cross_process_unique_temp_directory():
    """Concurrent test processes cannot overwrite each other's output files."""

    source = (REPO / "tests" / "cpp" / "test_gdat_output_format.cpp").read_text(
        encoding="utf-8"
    )
    assert "std::filesystem::create_directory(candidate, ec)" in source
    assert "TempDirectoryGuard" in source
    assert "remove_all(path, ec)" in source


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

    compat = (REPO / "cpp" / "parser" / "antlr_compat.hpp").read_text(encoding="utf-8")
    assert re.search(r"#\s*undef\s+ERROR", compat)
    assert re.search(r"#\s*undef\s+TRUE", compat)
    assert re.search(r"#\s*undef\s+FALSE", compat)
    assert re.search(r"#\s*undef\s+constant", compat)

    generated_dir = REPO / "cpp" / "parser" / "generated"
    generated_headers = sorted(generated_dir.glob("*.h"))
    assert generated_headers
    for header in generated_headers:
        source = header.read_text(encoding="utf-8")
        if '#include "antlr4-runtime.h"' not in source:
            continue
        compat_include = source.index('#include "../antlr_compat.hpp"')
        runtime_include = source.index('#include "antlr4-runtime.h"')
        assert compat_include < runtime_include, header.name


def test_corpus_parse_inventory_emits_source_and_binary_provenance():
    """Parser inventory summaries must identify the tested source and binary."""

    job = _workflow_job("corpus-parse")
    assert "set -euo pipefail" in job
    assert "BNG3_SOURCE_REVISION" in job
    assert "bng_cpp SHA-256" in job
    assert "GITHUB_STEP_SUMMARY" in job


def test_weekly_nfsim_smoke_emits_source_and_binary_provenance():
    """NFsim smoke summaries must identify the tested source and executable."""

    job = _workflow_job_from(WEEKLY_WORKFLOW, "nfsim-execution-smoke")
    assert "set -euo pipefail" in job
    assert "BNG3_SOURCE_REVISION" in job
    assert "NFsim SHA-256" in job
    assert "GITHUB_STEP_SUMMARY" in job


def test_weekly_cross_validation_fails_closed_on_engine_or_output_errors():
    """The claimed C++/Perl gate must fail through the runner, not skip."""

    job = _workflow_job_from(WEEKLY_WORKFLOW, "cross-validation")
    assert "set -euo pipefail" in job
    assert "SKIP" not in job
    assert "python scripts/cross_validate.py" in job
    assert "--bng-cpp build/cpp/bng_cpp" in job
    assert '--bng-perl "$RUNNER_TEMP/oracle-bionetgen/bng2/BNG2.pl"' in job
    assert "pip install numpy" in job
    assert "|| true" not in job


def test_cross_validation_rejects_same_count_different_networks(tmp_path):
    """The independent oracle comparison must inspect reaction topology."""

    reference = tmp_path / "reference.net"
    test = tmp_path / "test.net"
    reference.write_text(
        """begin species
1 A() 1
2 B() 0
end species
begin reactions
0 1 2 k
end reactions
""",
        encoding="utf-8",
    )
    test.write_text(
        """begin species
1 A() 1
2 C() 0
end species
begin reactions
0 1 2 k
end reactions
""",
        encoding="utf-8",
    )

    diff = compare_network_files(reference, test)

    assert diff is not None
    assert diff.ok is False
    assert diff.n_species_ref == diff.n_species_test == 2
    assert diff.n_reactions_ref == diff.n_reactions_test == 1


def test_cross_validation_missing_engine_output_is_an_error(tmp_path):
    """A successful engine exit without a network cannot become a pass."""

    models = tmp_path / "Validate"
    models.mkdir()
    (models / "model.bngl").write_text("begin model\nend model\n", encoding="utf-8")
    no_output = tmp_path / "no_output.sh"
    no_output.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    no_output.chmod(0o755)

    results, details = run_cross_validation(
        no_output,
        no_output,
        models,
        model_names=["model"],
    )

    assert results == {"pass": 0, "fail": 0, "error": 1}
    assert details == ["ERROR model (missing C++ .net)"]


def test_structural_xml_comparator_checks_bng_model_sections(tmp_path):
    reference = tmp_path / "reference.xml"
    generated = tmp_path / "generated.xml"
    reference.write_text(
        """<sbml xmlns="urn:bng"><model>
<ListOfSpecies><Species id="A" pattern="A()"/></ListOfSpecies>
<ListOfReactionRules><ReactionRule id="r1"><Rate value="2"/></ReactionRule></ListOfReactionRules>
<ListOfObservables><Observable id="obs" pattern="A()"/></ListOfObservables>
<ListOfFunctions><Function id="f"><Expression>k * x</Expression></Function></ListOfFunctions>
</model></sbml>""",
        encoding="utf-8",
    )
    generated.write_text(
        """<sbml xmlns="another-bng-namespace"><model>
<ListOfFunctions><Function id="f"><Expression>k * x</Expression></Function></ListOfFunctions>
<ListOfObservables><Observable pattern="A()" id="obs"/></ListOfObservables>
<ListOfReactionRules><ReactionRule id="r1"><Rate value="2"/></ReactionRule></ListOfReactionRules>
<ListOfSpecies><Species pattern="A()" id="A"/></ListOfSpecies>
</model></sbml>""",
        encoding="utf-8",
    )

    equal, differences = compare_structural_xml(
        reference,
        generated,
        sections=(
            "ListOfSpecies",
            "ListOfReactionRules",
            "ListOfObservables",
            "ListOfFunctions",
        ),
    )

    assert equal is True
    assert differences == []

    generated.write_text(
        generated.read_text(encoding="utf-8").replace('value="2"', 'value="3"'),
        encoding="utf-8",
    )
    equal, differences = compare_structural_xml(
        reference,
        generated,
        sections=(
            "ListOfSpecies",
            "ListOfReactionRules",
            "ListOfObservables",
            "ListOfFunctions",
        ),
    )
    assert equal is False
    assert differences == ["ListOfReactionRules"]


def test_structural_xml_comparator_normalizes_export_defaults_and_expression_text(
    tmp_path,
):
    reference = tmp_path / "reference-defaults.xml"
    generated = tmp_path / "generated-defaults.xml"
    reference.write_text(
        """<sbml><model><ListOfReactionRules>
<ReactionRule id="RR1" name="_R1" symmetry_factor="1"><Expression> ( 1 + (k) ) </Expression></ReactionRule>
<ReactionRule id="RR2" name="_R2_v1" symmetry_factor="1"><Expression>k</Expression></ReactionRule>
</ListOfReactionRules></model></sbml>""",
        encoding="utf-8",
    )
    generated.write_text(
        """<sbml><model><ListOfReactionRules>
<ReactionRule id="RR1" name="R1"><Expression>1+(k)</Expression></ReactionRule>
<ReactionRule id="RR2" name="R2_v1"><Expression>k</Expression></ReactionRule>
</ListOfReactionRules></model></sbml>""",
        encoding="utf-8",
    )

    equal, differences = compare_structural_xml(
        reference,
        generated,
        sections=("ListOfReactionRules",),
    )

    assert equal is True
    assert differences == []


def test_structural_xml_comparator_uses_reaction_maps_not_pattern_aliases(
    tmp_path,
):
    reference = tmp_path / "reference-pattern-aliases.xml"
    generated = tmp_path / "generated-pattern-aliases.xml"
    reference.write_text(
        """<sbml><model><ListOfReactionRules><ReactionRule id="r1">
<ListOfReactantPatterns><ReactantPattern id="r1_rp"><ListOfMolecules>
<Molecule id="r1_rp_m1" name="A" label="authored"/><Component id="r1_rp_m1_c1" name="x" label="authored_site"/>
</ListOfMolecules></ReactantPattern></ListOfReactantPatterns>
<ListOfProductPatterns><ProductPattern id="r1_pp"><ListOfMolecules>
<Molecule id="r1_pp_m1" name="A" label="generated"/><Component id="r1_pp_m1_c1" name="x" label="generated_site"/>
</ListOfMolecules></ProductPattern></ListOfProductPatterns>
<Map><MapItem sourceID="r1_rp_m1" targetID="r1_pp_m1"/><MapItem sourceID="r1_rp_m1_c1" targetID="r1_pp_m1_c1"/></Map>
</ReactionRule></ListOfReactionRules></model></sbml>""",
        encoding="utf-8",
    )
    generated.write_text(
        reference.read_text(encoding="utf-8")
        .replace('label="authored"', 'label="t0"')
        .replace('label="authored_site"', 'label="t1"')
        .replace('label="generated"', 'label="t0"')
        .replace('label="generated_site"', 'label="t1"'),
        encoding="utf-8",
    )

    equal, differences = compare_structural_xml(
        reference, generated, sections=("ListOfReactionRules",)
    )

    assert equal is True
    assert differences == []

    generated.write_text(
        generated.read_text(encoding="utf-8").replace(
            'targetID="r1_pp_m1_c1"', 'targetID="r1_pp_m1"'
        ),
        encoding="utf-8",
    )
    equal, differences = compare_structural_xml(
        reference, generated, sections=("ListOfReactionRules",)
    )
    assert equal is False
    assert differences == ["ListOfReactionRules"]

    generated.write_text(
        generated.read_text(encoding="utf-8").replace(
            '<MapItem sourceID="r1_rp_m1" targetID="r1_pp_m1"/>', ""
        ),
        encoding="utf-8",
    )
    equal, differences = compare_structural_xml(
        reference, generated, sections=("ListOfReactionRules",)
    )
    assert equal is False
    assert differences == ["ListOfReactionRules"]


def test_structural_xml_comparator_treats_omitted_empty_sections_as_empty(
    tmp_path,
):
    reference = tmp_path / "reference-empty-section.xml"
    generated = tmp_path / "generated-empty-section.xml"
    reference.write_text(
        "<sbml><model><ListOfSpecies/><ListOfFunctions/></model></sbml>",
        encoding="utf-8",
    )
    generated.write_text(
        "<sbml><model><ListOfSpecies/></model></sbml>", encoding="utf-8"
    )

    equal, differences = compare_structural_xml(
        reference,
        generated,
        sections=("ListOfSpecies", "ListOfFunctions"),
    )

    assert equal is True
    assert differences == []

    reference.write_text(
        '<sbml><model><ListOfSpecies/><ListOfFunctions><Function id="f"/></ListOfFunctions></model></sbml>',
        encoding="utf-8",
    )
    equal, differences = compare_structural_xml(
        reference,
        generated,
        sections=("ListOfSpecies", "ListOfFunctions"),
    )
    assert equal is False
    assert differences == ["ListOfFunctions"]


def test_structural_xml_comparator_normalizes_ids_and_references(tmp_path):
    reference = tmp_path / "reference-ids.xml"
    generated = tmp_path / "generated-ids.xml"
    reference.write_text(
        """<sbml><model>
<ListOfSpecies><Species id="sA" name="A"/><Species id="sB" name="B"/></ListOfSpecies>
<ListOfReactionRules><ReactionRule id="rA" name="bind"><Reactant species="sA"/><Product species="sB"/></ReactionRule></ListOfReactionRules>
</model></sbml>""",
        encoding="utf-8",
    )
    generated.write_text(
        """<sbml><model>
<ListOfSpecies><Species id="species_2" name="B"/><Species id="species_1" name="A"/></ListOfSpecies>
<ListOfReactionRules><ReactionRule id="rule_9" name="bind"><Reactant species="species_1"/><Product species="species_2"/></ReactionRule></ListOfReactionRules>
</model></sbml>""",
        encoding="utf-8",
    )

    equal, differences = compare_structural_xml(
        reference,
        generated,
        sections=("ListOfSpecies", "ListOfReactionRules"),
    )

    assert equal is True
    assert differences == []

    generated.write_text(
        generated.read_text(encoding="utf-8").replace(
            'species="species_1"', 'species="species_2"'
        ),
        encoding="utf-8",
    )
    equal, differences = compare_structural_xml(
        reference,
        generated,
        sections=("ListOfSpecies", "ListOfReactionRules"),
    )
    assert equal is False
    assert differences == ["ListOfReactionRules"]


def test_structural_xml_comparator_checks_multi_species_types_and_reactions(
    tmp_path,
):
    reference = tmp_path / "reference-multi.xml"
    generated = tmp_path / "generated-multi.xml"
    reference.write_text(
        """<sbml xmlns:multi="urn:multi"><model>
<multi:listOfSpeciesTypes><multi:speciesType multi:id="st_R" multi:name="R"><multi:listOfSpeciesFeatureTypes><multi:speciesFeatureType multi:id="state" multi:name="state"/></multi:listOfSpeciesFeatureTypes></multi:speciesType></multi:listOfSpeciesTypes>
<listOfSpecies><species id="S1" multi:speciesType="st_R"/></listOfSpecies>
<listOfReactions><reaction id="RR1"><listOfReactants><speciesReference species="RR1_R1"/></listOfReactants><listOfProducts><speciesReference species="RR1_P1"/></listOfProducts></reaction></listOfReactions>
</model></sbml>""",
        encoding="utf-8",
    )
    generated.write_text(
        """<sbml xmlns:multi="urn:multi"><model>
<multi:listOfSpeciesTypes><multi:speciesType multi:id="st_other" multi:name="R"><multi:listOfSpeciesFeatureTypes><multi:speciesFeatureType multi:id="state_other" multi:name="state"/></multi:listOfSpeciesFeatureTypes></multi:speciesType></multi:listOfSpeciesTypes>
<listOfSpecies><species id="S1" multi:speciesType="st_other"/></listOfSpecies>
<listOfReactions><reaction id="RR1"><listOfReactants><speciesReference species="RR1_R1"/></listOfReactants><listOfProducts><speciesReference species="RR1_P1"/></listOfProducts></reaction></listOfReactions>
</model></sbml>""",
        encoding="utf-8",
    )

    equal, differences = compare_structural_xml(
        reference,
        generated,
        sections=("listOfSpeciesTypes", "listOfSpecies", "listOfReactions"),
    )

    assert equal is True
    assert differences == []

    generated.write_text(
        generated.read_text(encoding="utf-8").replace('name="R"', 'name="L"'),
        encoding="utf-8",
    )
    equal, differences = compare_structural_xml(
        reference,
        generated,
        sections=("listOfSpeciesTypes", "listOfSpecies", "listOfReactions"),
    )
    assert equal is False
    assert "listOfSpeciesTypes" in differences

    generated.write_text(
        generated.read_text(encoding="utf-8").replace(
            'multi:name="state"', 'multi:name="other-state"'
        ),
        encoding="utf-8",
    )
    equal, differences = compare_structural_xml(
        reference,
        generated,
        sections=("listOfSpeciesTypes", "listOfSpecies", "listOfReactions"),
    )
    assert equal is False
    assert "listOfSpeciesTypes" in differences


def test_structural_xml_comparator_reports_categorized_element_differences(tmp_path):
    reference = tmp_path / "reference-details.xml"
    generated = tmp_path / "generated-details.xml"
    reference.write_text(
        """<sbml><model>
<ListOfSpecies>
  <Species id="sA" name="A"/>
  <Species id="sB" name="B"/>
</ListOfSpecies>
<ListOfReactionRules>
  <ReactionRule id="rA" name="bind">
    <RateLaw type="Ele"><ListOfRateConstants><RateConstant value="1"/></ListOfRateConstants></RateLaw>
    <Map><MapItem sourceID="sA" targetID="sB"/></Map>
  </ReactionRule>
  <ReactionRule id="rB" name="release"/>
</ListOfReactionRules>
</model></sbml>""",
        encoding="utf-8",
    )
    generated.write_text(
        """<sbml><model>
<ListOfSpecies>
  <Species id="species_1" name="A"/>
  <Species id="species_2" name="C"/>
</ListOfSpecies>
<ListOfReactionRules>
  <ReactionRule id="rule_1" name="bind">
    <RateLaw type="Ele"><ListOfRateConstants><RateConstant value="2"/></ListOfRateConstants></RateLaw>
    <Map><MapItem sourceID="species_1" targetID="species_1"/></Map>
  </ReactionRule>
  <ReactionRule id="rule_2" name="extra"/>
</ListOfReactionRules>
</model></sbml>""",
        encoding="utf-8",
    )

    comparison = diff_structural_xml(
        reference,
        generated,
        sections=("ListOfSpecies", "ListOfReactionRules"),
    )

    assert comparison.equal is False
    assert comparison.sections == ("ListOfSpecies", "ListOfReactionRules")
    counts = comparison.counts()
    assert counts["species"] == {"missing": 1, "extra": 1}
    assert counts["reaction rule"] == {"missing": 1, "extra": 1}
    assert counts["rate law"] == {"value": 1}
    # The sourceID aliases resolve to the same named species (A); only the
    # targetID changes from B to A.
    assert counts["component mapping"] == {"value": 1}

    missing = [
        difference
        for difference in comparison.differences
        if difference.kind == "missing"
    ]
    extra = [
        difference
        for difference in comparison.differences
        if difference.kind == "extra"
    ]
    assert any("Species[name='B']" in difference.path for difference in missing)
    assert any("Species[name='C']" in difference.path for difference in extra)
    assert any(
        "ReactionRule[name='release']" in difference.path for difference in missing
    )
    assert any("ReactionRule[name='extra']" in difference.path for difference in extra)

    formatted = format_structural_xml_differences(comparison)
    assert formatted
    assert any("RateConstant/@value" in line for line in formatted)
    assert any(
        "MapItem[sourceID=" in line and "/@targetID" in line for line in formatted
    )
    assert all("BNG2=" in line and "C++=" in line for line in formatted)


def test_structural_xml_comparator_separates_representation_only_sections(tmp_path):
    reference = tmp_path / "reference-representation.xml"
    generated = tmp_path / "generated-representation.xml"
    reference.write_text(
        """<sbml xmlns="urn:bng"><model>
<ListOfSpecies><Species id="A" pattern="A()"/></ListOfSpecies>
<ListOfReactionRules><ReactionRule id="r1"><Rate value="2"/></ReactionRule></ListOfReactionRules>
</model></sbml>""",
        encoding="utf-8",
    )
    generated.write_text(
        """<sbml xmlns="another-bng-namespace"><model>
<ListOfReactionRules><ReactionRule id="r1"><Rate value="2"/></ReactionRule></ListOfReactionRules>
<ListOfSpecies><Species pattern="A()" id="A"/></ListOfSpecies>
</model></sbml>""",
        encoding="utf-8",
    )

    comparison = diff_structural_xml(
        reference,
        generated,
        sections=("ListOfSpecies", "ListOfReactionRules"),
    )

    assert comparison.equal is True
    assert comparison.sections == ()
    assert comparison.differences == ()
    assert comparison.representation_only == (
        "ListOfSpecies",
        "ListOfReactionRules",
    )


@pytest.mark.parametrize(
    "model_name,source,cpp_output,perl_output,xml,action_label",
    [
        (
            "ANx",
            "begin model\nend model\nwriteXML()\n",
            "ANx.xml",
            "ANx.xml",
            """<sbml><model><ListOfMoleculeTypes><MoleculeType id="A"/></ListOfMoleculeTypes>
<ListOfSpecies><Species id="S1"/></ListOfSpecies>
<ListOfReactionRules><ReactionRule id="r1"/></ListOfReactionRules>
<ListOfObservables><Observable id="obs"/></ListOfObservables>
<ListOfFunctions><Function id="f"/></ListOfFunctions></model></sbml>""",
            "molecule types, species, rules, observables, functions",
        ),
        (
            "hybrid_test",
            'begin model\nend model\ngenerate_hybrid_model({actions=>["writeXML()"]})\n',
            "hybrid_test_hpp.xml",
            "hybrid_test_hpp.xml",
            """<sbml><model><ListOfMoleculeTypes><MoleculeType id="A"/></ListOfMoleculeTypes>
<ListOfSpecies><Species id="S1"/></ListOfSpecies>
<ListOfReactionRules><ReactionRule id="r1"/></ListOfReactionRules>
<ListOfObservables><Observable id="obs"/></ListOfObservables>
<ListOfFunctions><Function id="f"/></ListOfFunctions></model></sbml>""",
            "molecule types, species, rules, observables, functions",
        ),
        (
            "test_write_sbml_multi",
            "begin model\nend model\nwriteSBMLMulti();\n",
            "test_write_sbml_multi_sbml_multi.xml",
            "test_write_sbml_multi_sbml_sbmlmulti.xml",
            """<sbml xmlns:multi="urn:multi"><model>
<multi:listOfSpeciesTypes><multi:speciesType id="st_R"/></multi:listOfSpeciesTypes>
<listOfSpecies><species id="S1" multi:speciesType="st_R"/></listOfSpecies>
<listOfReactions><reaction id="RR1"/></listOfReactions>
</model></sbml>""",
            "Multi species types, species, reactions",
        ),
    ],
)
def test_cross_validation_runs_authored_export_actions_without_network_generation(
    tmp_path,
    monkeypatch,
    model_name,
    source,
    cpp_output,
    perl_output,
    xml,
    action_label,
):
    models = tmp_path / "Validate"
    models.mkdir()
    model = models / f"{model_name}.bngl"
    model.write_text(source, encoding="utf-8")
    cpp = tmp_path / "bng_cpp"
    perl = tmp_path / "BNG2.pl"
    cpp.touch()
    perl.touch()
    calls = []

    def run_engine(command, work_dir, timeout, environment=None):
        del timeout, environment
        staged = Path(command[-1])
        source_text = staged.read_text(encoding="utf-8")
        assert model_name in staged.name
        assert "writeXML()" in source_text or "writeSBMLMulti()" in source_text
        assert "generate_network" not in source_text
        output_name = cpp_output if command[0] == str(cpp) else perl_output
        (work_dir / output_name).write_text(xml, encoding="utf-8")
        calls.append(command[0])
        return subprocess.CompletedProcess(command, 0, "", ""), None

    monkeypatch.setattr("scripts.cross_validate._run_engine", run_engine)
    if model_name == "test_write_sbml_multi":
        # These tiny files exercise cross-validation orchestration only; the
        # real Issue 161 acceptance uses libSBML on its hash-pinned fixtures.
        monkeypatch.setattr(
            "scripts.issue161_multi_contract.sbml_validity",
            lambda _path: {
                "status": "valid",
                "severity_error_count": 0,
                "diagnostics": [],
            },
        )

    results, details = run_cross_validation(
        cpp,
        perl,
        models,
        model_names=[model_name],
    )

    assert results == {"pass": 1, "fail": 0, "error": 0}
    assert details == [f"PASS  {model_name} (authored export: {action_label})"]
    assert len(calls) == 2


def test_multi_authored_export_fails_closed_when_libsbml_is_unavailable(
    tmp_path, monkeypatch
):
    import builtins

    models = tmp_path / "Validate"
    models.mkdir()
    model = models / "test_write_sbml_multi.bngl"
    model.write_text("begin model\nend model\nwriteSBMLMulti();\n", encoding="utf-8")
    cpp = tmp_path / "bng_cpp"
    perl = tmp_path / "BNG2.pl"
    cpp.touch()
    perl.touch()
    xml = "<sbml xmlns:multi='urn:multi'><model/></sbml>"

    def run_engine(command, work_dir, timeout, environment=None):
        del timeout, environment
        output_name = (
            "test_write_sbml_multi_sbml_multi.xml"
            if command[0] == str(cpp)
            else "test_write_sbml_multi_sbml_sbmlmulti.xml"
        )
        (work_dir / output_name).write_text(xml, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", ""), None

    original_import = builtins.__import__

    def import_without_libsbml(name, *args, **kwargs):
        if name == "libsbml":
            raise ModuleNotFoundError("No module named 'libsbml'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("scripts.cross_validate._run_engine", run_engine)
    monkeypatch.setattr(builtins, "__import__", import_without_libsbml)

    results, details = run_cross_validation(
        cpp, perl, models, model_names=["test_write_sbml_multi"]
    )

    assert results == {"pass": 0, "fail": 0, "error": 1}
    assert "libSBML validity checks unavailable" in details[0]


def test_authored_export_reports_perl_when_cpp_times_out(tmp_path, monkeypatch):
    from scripts.cross_validate import _run_authored_export_comparison

    models = tmp_path / "Validate"
    models.mkdir()
    model = models / "ANx.bngl"
    model.write_text("begin model\nend model\nwriteXML()\n", encoding="utf-8")
    calls = []

    def run_engine(command, work_dir, timeout, environment=None):
        del work_dir, timeout, environment
        engine = "C++" if command[0] == "/fake/bng_cpp" else "BNG2"
        calls.append(engine)
        if engine == "C++":
            return None, "timeout after 5s"
        return subprocess.CompletedProcess(command, 0, "", ""), None

    monkeypatch.setattr("scripts.cross_validate._run_engine", run_engine)
    status, detail = _run_authored_export_comparison(
        model,
        Path("/fake/bng_cpp"),
        Path("/fake/BNG2.pl"),
        models,
        "perl",
        5,
    )

    assert status == "error"
    assert "C++: timeout after 5s" in detail
    assert "BNG2: action completed" in detail
    assert calls == ["C++", "BNG2"]


def test_authored_export_preserves_both_xml_files_on_failure(tmp_path, monkeypatch):
    from scripts.cross_validate import _run_authored_export_comparison

    models = tmp_path / "Validate"
    models.mkdir()
    model = models / "ANx.bngl"
    model.write_text("begin model\nend model\nwriteXML()\n", encoding="utf-8")
    cpp = tmp_path / "bng_cpp"
    perl = tmp_path / "BNG2.pl"
    cpp.touch()
    perl.touch()
    reference = """<sbml><model>
<ListOfSpecies><Species id="A" name="A"/></ListOfSpecies>
<ListOfReactionRules><ReactionRule id="r" name="bind"/></ListOfReactionRules>
</model></sbml>"""
    generated = """<sbml><model>
<ListOfSpecies><Species id="B" name="B"/></ListOfSpecies>
<ListOfReactionRules><ReactionRule id="s" name="release"/></ListOfReactionRules>
</model></sbml>"""

    def run_engine(command, work_dir, timeout, environment=None):
        del timeout, environment
        text = reference if command[0] == "perl" else generated
        (work_dir / "ANx.xml").write_text(text, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", ""), None

    monkeypatch.setattr("scripts.cross_validate._run_engine", run_engine)
    artifact_dir = tmp_path / "artifacts"
    status, detail = _run_authored_export_comparison(
        model,
        cpp,
        perl,
        models,
        "perl",
        5,
        artifact_dir=artifact_dir,
    )

    assert status == "fail"
    assert "canonical structural differences" in detail
    assert "semantic impact unclassified" in detail
    assert "ListOfSpecies/Species[name='A']" in detail
    assert "ListOfReactionRules/ReactionRule[name='bind']" in detail
    assert (artifact_dir / "ANx.bng2.xml").read_text(encoding="utf-8") == reference
    assert (artifact_dir / "ANx.cpp.xml").read_text(encoding="utf-8") == generated
    assert "preserved artifacts" in detail


def test_cross_validation_stages_generation_without_simulation_actions():
    """Network parity must not accidentally execute a model's simulations."""

    staged = _network_only_text("""begin parameters
k 1
end parameters
begin actions
setParameter(\"k\", 2)
generate_network({overwrite=>1})
simulate_ode({t_end=>10,n_steps=>10})
end actions
""")

    assert 'setParameter("k", 2)' in staged
    assert "simulate_ode" not in staged
    assert staged.endswith(
        'begin actions\n  setParameter("k", 2)\n'
        "  generate_network({overwrite=>1})\nend actions\n"
    )


def test_cross_validation_can_preserve_network_writer_for_continuations(tmp_path):
    source = tmp_path / "continuation.bngl"
    source.write_text(
        "begin model\nend model\n"
        "begin actions\n"
        "generate_network({overwrite=>1})\n"
        'setConcentration("A()", 2)\n'
        'addConcentration("A()", 1)\n'
        "resetConcentrations()\n"
        'writeNetwork({suffix=>"cont",overwrite=>1})\n'
        "end actions\n",
        encoding="utf-8",
    )

    staged = _stage_model(
        source,
        tmp_path,
        tmp_path / "staged",
        preserve_network_writer=True,
    )
    text = staged.read_text(encoding="utf-8")
    assert "generate_network({overwrite=>1})" in text
    assert 'setConcentration("A()", 2)' in text
    assert 'addConcentration("A()", 1)' in text
    assert "resetConcentrations()" in text
    assert 'writeNetwork({suffix=>"cont",overwrite=>1})' in text
    assert text.index("generate_network") < text.index("setConcentration")
    assert text.index("setConcentration") < text.index("addConcentration")
    assert text.index("addConcentration") < text.index("resetConcentrations")
    assert text.index("resetConcentrations") < text.index("writeNetwork")
    assert "simulate" not in text


def test_cross_validation_preserves_network_generation_bounds():
    """Network-only staging must retain source max_iter and max_stoich."""

    staged = _network_only_text("""begin model
end model
begin actions
generate_network({overwrite=>1,max_iter=>3})
setParameter("k", 2)
generate_network({overwrite=>1,max_stoich=>{'R'=>5,'L'=>5}})
simulate_ode({t_end=>10,n_steps=>10})
end actions
""")

    assert "generate_network({overwrite=>1,max_iter=>3})" in staged
    assert "generate_network({overwrite=>1,max_stoich=>{'R'=>5,'L'=>5}})" in staged
    assert staged.count("generate_network(") == 2
    assert "simulate_ode" not in staged
    assert staged.index("max_iter=>3") < staged.index('setParameter("k", 2)')
    assert staged.index('setParameter("k", 2)') < staged.index("max_stoich")


def test_cross_validation_retains_top_level_option_declarations():
    staged = _network_only_text(
        'setOption("SpeciesLabel","HNauty")\nbegin model\nend model\n'
    )
    assert staged.startswith('setOption("SpeciesLabel","HNauty")\n')
    assert staged.count("setOption") == 1
    assert staged.index("setOption") < staged.index("begin actions")


def test_cross_validation_collects_top_level_runtime_setup_in_actions():
    staged = _network_only_text('begin model\nend model\nsetConcentration("A()",2)\n')
    assert staged.index("setConcentration") > staged.index("begin actions")


def test_cross_validation_drops_runtime_and_continuation_actions():
    """Network-only staging must not retain simulations or state resets."""

    staged = _network_only_text("""begin model
end model
begin actions
simulate_ps({t_end=>10})
simulate_rm({t_end=>10})
parameter_scan({method=>"protocol"})
saveConcentrations("post2")
resetConcentrations("post2")
end actions
""")

    assert "generate_network({overwrite=>1})" in staged
    for action in (
        "simulate_ps",
        "simulate_rm",
        "parameter_scan",
        "saveConcentrations",
        "resetConcentrations",
    ):
        assert action not in staged


def test_weekly_cross_validation_uses_structural_oracle_runner():
    """C++/Perl validation must compare typed networks, not section counts."""

    job = _workflow_job_from(WEEKLY_WORKFLOW, "cross-validation")
    assert "python scripts/cross_validate.py" in job
    assert '--bng-perl "$RUNNER_TEMP/oracle-bionetgen/bng2/BNG2.pl"' in job
    assert '--summary-file "$GITHUB_STEP_SUMMARY"' in job
    assert "grep -c" not in job
    assert "species counts" not in job


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


def test_reference_ci_jobs_emit_terminal_validation_summaries():
    """PR and weekly reference jobs must publish their result table."""

    assert '--summary-file "$GITHUB_STEP_SUMMARY"' in _workflow_job("validation")
    assert '--summary-file "$GITHUB_STEP_SUMMARY"' in _workflow_job_from(
        WEEKLY_WORKFLOW, "bng-validation"
    )


def test_validation_summary_records_counts_source_and_binary_digest(
    tmp_path, monkeypatch
):
    """The reusable validation summary must preserve provenance and outcomes."""

    bng_cpp = tmp_path / "bng_cpp"
    bng_cpp.write_bytes(b"bng3-test-binary")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_SHA", "source-sha-123")

    write_validation_summary(
        summary,
        {
            "pass": 4,
            "fail": 1,
            "skip": 2,
            "error": 3,
        },
        bng_cpp,
        tmp_path / "Validate",
        strict_references=True,
    )

    text = summary.read_text(encoding="utf-8")
    assert "source-sha-123" in text
    assert "bng_cpp SHA-256" in text
    assert "| 10 | 4 | 1 | 3 | 2 |" in text
    assert "explicit exclusions only" in text
    assert text.count("| ---: | ---: | ---: | ---: | ---: |") == 1


def test_cross_validation_summary_records_both_engines_without_duplicate_header(
    tmp_path, monkeypatch
):
    """The structural cross-check summary must be auditable and well formed."""

    bng_cpp = tmp_path / "bng_cpp"
    bng_cpp.write_bytes(b"bng3-test-binary")
    bng_perl = tmp_path / "BNG2.pl"
    bng_perl.write_text("#!/usr/bin/perl\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_SHA", "source-sha-456")
    # CI may supply this higher-priority exact-source identity. Own it in the
    # fixture as well so an inherited candidate SHA cannot override the input.
    monkeypatch.setenv("BNG3_SOURCE_REVISION", "source-sha-456")

    write_cross_validation_summary(
        summary,
        {"pass": 3, "fail": 1, "error": 2},
        bng_cpp,
        bng_perl,
        tmp_path / "Validate",
        ["FAIL model (C++/BNG2 structural XML differs: species)"],
    )

    text = summary.read_text(encoding="utf-8")
    assert "source-sha-456" in text
    assert "BNG2 oracle SHA-256" in text
    assert "bng_cpp SHA-256" in text
    assert "| 6 | 3 | 1 | 2 |" in text
    assert text.count("| ---: | ---: | ---: | ---: |") == 1
    assert "Per-model results" in text
    assert "FAIL model" in text


def test_reference_exclusion_manifest_is_explicit_and_corpus_backed():
    """The former exclusion ledger is closed and contains no skipped models."""

    manifest = json.loads(REFERENCE_EXCLUSIONS.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["status"] == "closed"
    assert set(manifest["profiles"]) == {"pull_request", "weekly"}
    assert manifest["profiles"] == {"pull_request": [], "weekly": []}
    assert manifest["reasons"] == {}

    action_models = load_validation_manifest(VALIDATION_MANIFEST)
    assert action_models
    assert len(action_models) == len(set(action_models))
    assert all((VALIDATE_DIR / f"{model}.bngl").is_file() for model in action_models)

    aliases = load_validation_molecule_name_aliases(VALIDATION_MANIFEST)
    assert aliases == {
        "test_sbml_flat": {
            "A____": "A",
            "AA____": "AA",
            "B____": "B",
            "C____": "C",
            "D____": "D",
        }
    }
    assert (VALIDATE_DIR / "test_sbml_flat.bngl").is_file()


def test_reference_ci_jobs_run_the_full_corpus_without_exclusions():
    """CI must run both network and action-output fixtures without skips."""

    validation_job = _workflow_job("validation")
    weekly_job = _workflow_job_from(WEEKLY_WORKFLOW, "bng-validation")
    assert "SKIP=" not in validation_job
    assert "SKIP=" not in weekly_job
    assert "--skip-file" not in validation_job
    assert "--skip-profile" not in validation_job
    assert "--skip-file" not in weekly_job
    assert "--skip-profile" not in weekly_job
    assert (
        "--validation-manifest tests/validation/validation_manifest.json"
        in validation_job
    )
    assert (
        "--validation-manifest tests/validation/validation_manifest.json" in weekly_job
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


def test_batch_ssa_parity_script_fails_closed_when_it_cannot_reach_its_models():
    """The gate must go red, not pass or skip, when the extension is absent.

    `main` turns the CPU gate's boolean into an exit status. Run from a
    directory where `models/*.bngl` does not resolve, the gate has to fail --
    otherwise deleting or misconfiguring the build step would green the job
    having tested nothing. This runs the real script, so it needs no compiled
    extension: it fails before it gets that far, which is the property.
    """

    script = REPO / "tests" / "test_batch_ssa_statistical_parity.py"
    assert script.is_file()
    completed = subprocess.run(
        [sys.executable, str(script), "--mode", "cpu"],
        cwd=REPO / "scripts",
        capture_output=True,
        text=True,
        timeout=600,
        env={
            "PATH": os.environ["PATH"],
            "HOME": os.environ["HOME"],
            "PYTHONPATH": "",
        },
    )
    assert completed.returncode != 0, (
        "the batch-SSA CPU gate exited 0 from a directory where its model "
        "fixtures do not resolve, so a missing build would pass the job"
    )


def test_parity_script_cpu_mode_translates_a_failed_gate_into_a_nonzero_exit():
    """A failed parity comparison must reach the runner as a nonzero status.

    Asserting this on the source keeps the contract hermetic: this suite cannot
    build the extension, so it cannot make the gate fail for real. What it can
    pin is the wiring the CI job depends on -- gate result to exit status, exit
    status to process status -- and that the CPU mode reports on the CPU gate
    rather than on a GPU comparison that skips without a backend.
    """

    source = (REPO / "tests" / "test_batch_ssa_statistical_parity.py").read_text(
        encoding="utf-8"
    )
    assert "return 0 if ok else 1" in source, (
        "the CPU gate's result is no longer translated into an exit status; a "
        "failed parity comparison would exit 0 and the CI job would go green"
    )
    assert re.search(
        r"if\s+__name__\s*==\s*[\"']__main__[\"']:\s*\n\s*sys\.exit\(main\(\)\)", source
    ), "the parity script must propagate main()'s status via sys.exit under __main__"
    assert re.search(r"if\s+args\.mode\s*==\s*\"gpu\":", source), (
        "--mode gpu must be dispatched before the CPU gate; the CI job runs "
        "--mode cpu, so the two modes have to stay distinguishable"
    )
    assert source.count("run_cpu_reference_gate()") >= 2, (
        "the CPU gate must be invoked from main() and tested independently of "
        "the GPU comparison"
    )


def test_issue141_cleanup_probe_enables_leaks_and_requires_a_selected_test():
    workflow = parse_workflow(CI_WORKFLOW)
    steps = [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == "Qualify issue 141 late CVODE exception cleanup"
    ]
    assert len(steps) == 1
    step = steps[0]
    assert step["env"]["ASAN_OPTIONS"] == "detect_leaks=1"
    assert "--no-tests=error" in step["run"]
    assert (
        "-R '^OdeIntegrator recovers after late stop condition failure$'" in step["run"]
    )
    assert not step.get("continue-on-error", False)
    source = (REPO / "tests/cpp/test_ode_options.cpp").read_text()
    assert (
        'TEST_CASE("OdeIntegrator recovers after late stop condition failure"' in source
    )
    assert 'options.stopIf = "if(time > 0, missing_name, 0)"' in source


def test_cuda_job_disables_only_unreachable_microsoft_apt_entries(tmp_path):
    (tmp_path / "sources.list.d").mkdir()
    legacy = tmp_path / "sources.list.d" / "microsoft.list"
    legacy.write_text(
        "deb [signed-by=/usr/share/keyrings/microsoft.gpg] "
        "https://packages.microsoft.com/ubuntu/22.04/prod jammy main\n"
        "deb http://archive.ubuntu.com/ubuntu jammy main\n",
        encoding="utf-8",
    )
    deb822 = tmp_path / "sources.list.d" / "mixed.sources"
    deb822.write_text(
        "Types: deb\nURIs: https://packages.microsoft.com/ubuntu/22.04/prod\n"
        " https://example.test/ubuntu\nSuites: jammy\nComponents: main\n\n"
        "Types: deb\nURIs: https://packages.microsoft.com/ubuntu/22.04/prod\n"
        "Suites: jammy\nComponents: main\n",
        encoding="utf-8",
    )

    assert disable_unreachable_sources(tmp_path) == 3
    legacy_text = legacy.read_text(encoding="utf-8")
    assert "# disabled for CUDA CI" in legacy_text
    assert "deb http://archive.ubuntu.com/ubuntu jammy main" in legacy_text
    deb822_text = deb822.read_text(encoding="utf-8")
    assert "URIs: https://example.test/ubuntu" in deb822_text
    assert "Enabled: no" in deb822_text
    assert deb822_text.count("https://packages.microsoft.com") == 0

    cuda_steps = parse_workflow(CI_WORKFLOW)["jobs"]["cpp-cuda"]["steps"]
    filter_step = next(
        step
        for step in cuda_steps
        if step.get("name") == "Disable unrelated Microsoft apt feed"
    )
    install_step = next(
        step for step in cuda_steps if step.get("name") == "Install dependencies"
    )
    assert filter_step["run"] == (
        "sudo python3 scripts/ci/disable_unreachable_microsoft_apt_source.py"
    )
    assert cuda_steps.index(filter_step) < cuda_steps.index(install_step)


def test_parity_revision_declarations_match_the_product_checkout():
    """A PR merge SHA must never be attributed to a PR-head product build."""
    workflow = parse_workflow(PARITY_WORKFLOW)
    declarations = 0
    for job_id, job in workflow["jobs"].items():
        checkout = next(
            step
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
            and not step.get("with", {}).get("path")
        )
        source_ref = checkout["with"]["ref"]
        for step in job["steps"]:
            env = {
                **workflow.get("env", {}),
                **job.get("env", {}),
                **step.get("env", {}),
            }
            for key in ("BNG3_SOURCE_REVISION", "BNG3_PR_HEAD_SHA"):
                if key in env:
                    declarations += 1
                    assert env[key] == source_ref, (
                        f"{job_id}: {step.get('name')}: {key}={env[key]!r} "
                        f"does not match product checkout {source_ref!r}"
                    )
    assert declarations, "no product revision declarations checked"


def test_structural_xml_comparator_preserves_rates_under_export_spelling_changes(
    tmp_path,
):
    reference = tmp_path / "reference.xml"
    generated = tmp_path / "generated.xml"
    reference.write_text("""<sbml><model>
<ListOfParameters><Parameter id="_rateLaw1" type="Constant" value="1000"/></ListOfParameters>
<ListOfReactionRules><ReactionRule id="RR1" name="r">
<RateLaw type="Function" name="_rateLaw2"/>
<Map><MapItem sourceID="a" targetID="b"/><MapItem sourceID="c" targetID="d"/></Map>
<ListOfOperations><AddBond site1="a" site2="c"/></ListOfOperations>
</ReactionRule><ReactionRule id="RR2" name="s"><RateLaw type="Ele"><ListOfRateConstants><RateConstant value="_rateLaw1"/></ListOfRateConstants></RateLaw></ReactionRule></ListOfReactionRules>
<ListOfObservables><Observable id="O1" name="X" output="1"><ListOfPatterns><Pattern id="P1" automorphisms="1"/></ListOfPatterns></Observable></ListOfObservables>
<ListOfFunctions><Function id="_rateLaw2"><Expression> 1.0 / (1.0 + x) </Expression></Function></ListOfFunctions>
</model></sbml>""")
    text = """<sbml><model>
<ListOfReactionRules><ReactionRule id="RR1" name="r">
<RateLaw type="Function" name="__bng3_reaction_rate_RR1"/>
<Map><MapItem sourceID="c" targetID="d"/><MapItem sourceID="a" targetID="b"/></Map>
<ListOfOperations><AddBond site1="c" site2="a"/></ListOfOperations>
</ReactionRule><ReactionRule id="RR2" name="s"><RateLaw type="Ele"><ListOfRateConstants><RateConstant value="1000"/></ListOfRateConstants></RateLaw></ReactionRule></ListOfReactionRules>
<ListOfObservables><Observable id="O1" name="X"><ListOfPatterns><Pattern id="P1"/></ListOfPatterns></Observable></ListOfObservables>
<ListOfFunctions><Function id="__bng3_reaction_rate_RR1"><Expression>(1 / (1 + x))</Expression></Function></ListOfFunctions>
</model></sbml>"""
    sections = ("ListOfReactionRules", "ListOfFunctions", "ListOfObservables")
    generated.write_text(text)
    assert compare_structural_xml(reference, generated, sections=sections) == (True, [])
    for before, after in [
        ('value="1000"', 'value="999"'),
        ("1 + x", "2 + x"),
        ('site2="a"', 'site2="b"'),
        ('sourceID="a" targetID="b"', 'sourceID="a" targetID="d"'),
        ('<Pattern id="P1"/>', '<Pattern id="P1" automorphisms="2"/>'),
        ('name="X"', 'name="X" output="0"'),
    ]:
        generated.write_text(text.replace(before, after))
        equal, _ = compare_structural_xml(reference, generated, sections=sections)
        assert not equal, (before, after)
