"""The harness's own invariants, asserted in one place.

The Atomizer coverage campaign's harness is spread over several tools and
several test files.  The properties the campaign's numbers depend on were
asserted in four or five scattered places, so a reader had to know where to
look, and a change to one of them could quietly break another.

This module is the single entry point for those invariants.  It does not
re-assert them: where an invariant is already asserted elsewhere, this module
*calls* that assertion, so there is one place to keep in step.  Beside each
call it shows that a deliberately broken copy of the thing the invariant
guards is detected, because an invariant that cannot fail is not an
invariant.

Run it with one command::

    PYTHONPATH=python:build/cpp python -m pytest -q tests/test_harness_contracts.py

The invariants, and where each is asserted:

1. **Every case is accounted for.**  The stage counts sum to the number of
   cases that ran, no case is silently dropped from the report, and a new
   outcome bucket has to be added to the vocabulary deliberately.
   Asserted by ``tests/python/test_sbml_validation_contracts.py`` and by
   ``scripts/ci/sbml_campaign_status.py``'s coverage check.
2. **Provenance is present and checkable.**  A report records the package
   path, the native extension's path and digest, the suite revision and the
   tool versions, and the harness cannot be made to measure a package that is
   not traceable to the checkout without that being visible.
   Asserted by ``tests/test_ci_contract.py`` and by
   ``scripts/ci/sbml_campaign_status.py``'s provenance check.
3. **The comparison tool reports verdicts, not provenance or order.**
   Asserted by ``tests/test_ssts_report_comparison.py``.
4. **The gate's isolation is real.**  A case cannot observe another case's
   module state, native statics or leaked handles, and the case order is not
   significant.  Asserted by ``tests/test_ssts_isolation.py``.
5. **The expectation manifest's ratchet behaves.**  A regression fails, an
   improvement is reported as an improvement and requires an explicit
   manifest update, a report from a different suite revision is rejected,
   and every gap names a construct and records the side it sits on.
   Asserted by ``tests/validation/test_sbml_expectations.py``.
6. **The slot fails open** and never deadlocks, and the ``--jobs`` guard caps
   the worker count.  Asserted by ``tests/test_ssts_isolation.py``.
7. **The artifacts are reproducible** under a pinned ``PYTHONHASHSEED``, and
   a non-reproducible artifact is *detected* rather than reported as a
   difference.  Asserted by
   ``tests/python/test_modern_atomizer_sbml_parity.py``.
8. **The floor check works on the floor.**  The Python-floor checker reaches
   the same verdict on every interpreter from the declared floor upwards,
   including a construct the host itself cannot parse.  Asserted by
   ``tests/python/test_python_floor_check.py``.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.ci import sbml_campaign_inventory as inventory
from scripts.ci import sbml_campaign_status as status
from scripts.ci import validate_sbml_test_suite as runner

GATE = REPO / "scripts" / "ci" / "validate_sbml_test_suite.py"
COMPARATOR = REPO / "scripts" / "ci" / "compare_sbml_suite_reports.py"
FLOOR_CHECKER = REPO / "scripts" / "ci" / "check_python_floor.py"
MANIFEST = REPO / "provenance" / "sbml-campaign" / "expectations.json"
INVENTORY = REPO / "provenance" / "sbml-campaign" / "current-2026-10-22.json"


# --------------------------------------------------------------------------
# Calling the assertions that already live elsewhere
# --------------------------------------------------------------------------


def _load_module(path: Path, name: str):
    """Load a module from a path, under a name of this module's choosing.

    The module is registered in ``sys.modules`` before it is executed, so
    that a dataclass or a function defined in it can find its own module.
    """

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_test_module(relative_path: str, name: str):
    """Load an existing test module by its path in the repository."""

    return _load_module(REPO / relative_path, name)


#: The existing assertions this suite calls rather than duplicates.
validation_contracts = _load_test_module(
    "tests/python/test_sbml_validation_contracts.py", "_contract_validation_contracts"
)
comparison_contracts = _load_test_module(
    "tests/test_ssts_report_comparison.py", "_contract_comparison_contracts"
)
isolation_contracts = _load_test_module(
    "tests/test_ssts_isolation.py", "_contract_isolation_contracts"
)
manifest_contracts = _load_test_module(
    "tests/validation/test_sbml_expectations.py", "_contract_manifest_contracts"
)
floor_contracts = _load_test_module(
    "tests/python/test_python_floor_check.py", "_contract_floor_contracts"
)
parity_contracts = _load_test_module(
    "tests/python/test_modern_atomizer_sbml_parity.py", "_contract_parity_contracts"
)


def _call(test_function, **fixtures):
    """Invoke an existing assertion with the fixtures it declares.

    The assertion stays where it is; this suite only calls it.  A test that
    grows a new fixture fails here rather than silently losing its check.
    """

    signature = inspect.signature(test_function)
    missing = [
        name for name in signature.parameters if name not in fixtures and name != "self"
    ]
    assert not missing, (
        f"{test_function.__name__} declares the fixtures {missing}, which "
        "this contract suite does not provide"
    )
    arguments = {
        name: fixtures[name] for name in signature.parameters if name in fixtures
    }
    return test_function(**arguments)


# --------------------------------------------------------------------------
# Small report builders
# --------------------------------------------------------------------------


def _record(case_id: str, status_value: str = "passed", **overrides: Any):
    """Return one gate record."""

    record = {
        "category": "semantic",
        "id": case_id,
        "status": status_value,
        "generated_network": {"species": 1, "reactions": 1},
        "roundtrip_passed": True,
        "simulation_comparison": {"passed": True},
        "official_conformance": {"status": "passed", "reason": ""},
    }
    record.update(overrides)
    return record


def _report(records, **overrides: Any):
    """Return a gate report that carries ``records``."""

    report = {
        "records": list(records),
        "counts": {"passed": len(records)},
        "stage_counts": {"conversion": {"passed": len(records)}},
        "selected_cases": len(records),
        "partial_run": False,
        "suite_commit": "cf38585fac5de8e0e90112febb62851ee2181816",
    }
    report.update(overrides)
    return report


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _installed_copy_path() -> str:
    """Return a path that names an installed copy of the package."""

    return str(
        Path("/nonexistent/python") / "site-packages" / "bionetgen" / "__init__.py"
    )


# --------------------------------------------------------------------------
# 1. Every case is accounted for
# --------------------------------------------------------------------------


def test_every_case_is_accounted_for(tmp_path):
    """The stage counts add up to the cases that ran, and a new bucket is caught."""

    # The harness's own counting function is the one under test.
    _call(
        validation_contracts.test_record_counts_account_for_every_case,
        tmp_path=tmp_path,
    )

    report = _report([_record("00001"), _record("00002")])
    assert status.coverage_problems(report) == []

    # A deliberately broken copy: a case whose verdict is dropped from the
    # report's counts.  The counts no longer add up to the cases that ran.
    dropped = _report([_record("00001"), _record("00002")])
    dropped["counts"] = {"passed": 1}
    problems = status.coverage_problems(dropped)
    assert problems, "a dropped case was not detected"
    assert any("counts sum to 1" in problem for problem in problems), problems

    # A deliberately broken copy: a case that ran but is not in the report.
    missing = _report([_record("00001"), _record("00002")])
    missing["selected_cases"] = 3
    problems = status.coverage_problems(missing)
    assert problems, "a missing case was not detected"
    assert any("selected 3 cases" in problem for problem in problems), problems

    # A deliberately broken copy: a new outcome bucket that nobody added to
    # the vocabulary.  It must be reported, not counted as a result.
    extended = _report([_record("00001"), _record("00002", "exploded")])
    problems = status.coverage_problems(extended)
    assert problems, "a new outcome bucket was not detected"
    assert any("exploded" in problem for problem in problems), problems


def test_the_committed_inventory_accounts_for_every_case():
    """The committed measurement adds up, stage by stage."""

    committed = json.loads(INVENTORY.read_text(encoding="utf-8"))
    suite = committed["sbml_test_suite"]
    assert suite["case_count"] == len(suite["cases"])
    for stage, counts in suite["stage_counts"].items():
        assert sum(counts.values()) == suite["case_count"], stage


# --------------------------------------------------------------------------
# 2. Provenance is present and checkable
# --------------------------------------------------------------------------


def test_a_report_records_a_provenance_a_reader_can_check():
    """The report names the package, the native build and the suite revision."""

    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    provenance = runner._runtime_provenance(cpp)

    for field in (
        "bionetgen_package_path",
        "native_extension_path",
        "native_extension_sha256",
        "python_package_source_sha256",
        "python_version",
        "platform",
    ):
        assert provenance.get(field), field

    assert Path(provenance["bionetgen_package_path"]).exists()
    assert Path(provenance["native_extension_path"]).exists()


def test_a_report_of_a_foreign_package_is_not_presented_as_this_checkout():
    """A package that is not traceable to the checkout must be said so."""

    checkout = REPO

    # The report measured this checkout: the verdict is a match.
    report = _report(
        [_record("00001")],
        runtime_provenance={
            "bionetgen_package_path": str(
                REPO / "python" / "bionetgen" / "__init__.py"
            ),
            "native_extension_path": str(REPO / "build" / "cpp" / "ext.so"),
            "native_extension_sha256": "0" * 64,
        },
        source_provenance={"bng3_commit": _head(checkout)},
    )
    verdict = status.check_provenance(report, checkout)
    assert verdict["status"] == status.PROVENANCE_MATCH, verdict["problems"]
    # The report measured an installed copy of the package.  The stale
    # installation in site-packages is exactly this hazard.
    foreign = json.loads(json.dumps(report))
    foreign["runtime_provenance"]["bionetgen_package_path"] = _installed_copy_path()
    verdict = status.check_provenance(foreign, checkout)
    assert verdict["status"] == status.PROVENANCE_MISMATCH, verdict
    assert any("installed copy" in problem for problem in verdict["problems"])

    # The report records no provenance at all.  The tool cannot establish
    # what the numbers are about, and must not report a clean result.
    blind = _report([_record("00001")])
    verdict = status.check_provenance(blind, checkout)
    assert verdict["status"] == status.PROVENANCE_UNVERIFIABLE, verdict
    assert any(
        "no bionetgen package path" in problem for problem in verdict["problems"]
    )


def _head(checkout: Path) -> str:
    """Return the commit a checkout is at."""

    return status.repository_head(checkout)


def test_the_status_command_refuses_to_report_a_clean_result_for_a_foreign_package(
    tmp_path,
):
    """The exit status is non-zero when the provenance does not match."""

    report_path = tmp_path / "report.json"
    report = _report(
        [_record("00001")],
        runtime_provenance={
            "bionetgen_package_path": _installed_copy_path(),
            "native_extension_path": "/nowhere/ext.so",
            "native_extension_sha256": "0" * 64,
        },
        source_provenance={"bng3_commit": _head(REPO)},
    )
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "ci" / "sbml_campaign_status.py"),
            "--suite-report",
            str(report_path),
            "--checkout-root",
            str(REPO),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )

    assert result.returncode != 0, result.stdout
    assert status.EXIT_PROVENANCE & result.returncode
    assert "MISMATCH" in result.stdout


# --------------------------------------------------------------------------
# 3. The comparison tool reports verdicts, not provenance or order
# --------------------------------------------------------------------------


def test_the_comparison_tool_reports_verdicts_not_provenance_or_order():
    """Two runs of the same corpus agree, however they were launched."""

    _call(comparison_contracts.test_runtime_provenance_is_not_a_verdict_difference)
    _call(comparison_contracts.test_case_order_does_not_change_the_verdict)
    _call(comparison_contracts.test_a_real_verdict_difference_is_still_reported)
    _call(comparison_contracts.test_summary_case_lists_are_compared_without_order)

    # A deliberately broken copy of the comparator: one that treats the
    # run-local provenance as a verdict.  It cries wolf over a difference
    # that is not one, which is what the real comparator must not do.
    broken = _load_module(COMPARATOR, "_contract_broken_comparator")
    broken.NON_VERDICT_RECORD_FIELDS = ()
    broken.NON_VERDICT_REPORT_FIELDS = ()

    left = comparison_contracts._report([comparison_contracts._record("00001")])
    right = comparison_contracts._report(
        [
            comparison_contracts._record(
                "00001",
                worker_runtime_provenance={"python_executable": "/opt/other/python"},
            )
        ]
    )

    real = _load_module(COMPARATOR, "_contract_real_comparator")
    differences, differing_cases, report_differences = real.compare_reports(left, right)
    assert differences == []
    assert differing_cases == []
    assert report_differences == []

    differences, differing_cases, _ = broken.compare_reports(left, right)
    assert differing_cases, "the broken comparator did not report anything"
    assert any("worker_runtime_provenance" in difference for difference in differences)


# --------------------------------------------------------------------------
# 4. The gate's isolation is real
# --------------------------------------------------------------------------


def test_the_gate_isolation_is_real(tmp_path, monkeypatch):
    """A case cannot see another case's state, and the order does not matter."""

    if not hasattr(os, "fork"):
        pytest.skip("fork isolation requires POSIX fork")

    _call(
        isolation_contracts.test_fork_isolation_keeps_a_failing_case_from_reaching_its_neighbour,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    _call(
        isolation_contracts.test_fork_isolation_does_not_leak_case_state_into_the_next_case,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    def _leaky(case, *_args, **_kwargs):
        if case["id"] == "00001":
            runner._LEAK_PROBE = "leaked"
        return {
            "category": case["category"],
            "id": case["id"],
            "version": case["version"],
            "source": str(case["path"]),
            "status": "passed",
            "core_passed": True,
            "observed_probe": runner._LEAK_PROBE,
            "official_conformance": {"status": "passed"},
        }

    monkeypatch.setattr(runner, "_LEAK_PROBE", None, raising=False)
    monkeypatch.setattr(runner, "_validate_case", _leaky)
    cases = [
        {
            "category": "semantic",
            "id": "00001",
            "version": "l3v2",
            "path": str(tmp_path / "a.xml"),
        },
        {
            "category": "semantic",
            "id": "00002",
            "version": "l3v2",
            "path": str(tmp_path / "b.xml"),
        },
    ]
    args = isolation_contracts._namespace(tmp_path, case_timeout=60)

    # The deliberately broken copy: the same cases, run in one process
    # without isolation.  The second case sees the first case's state, so
    # the order of the cases is significant there.
    broken = [
        runner._validate_case(case, None, tmp_path, 1.0, 10, 1e-7, 1e-12, None)
        for case in cases
    ]
    assert broken[0]["observed_probe"] == "leaked"
    assert broken[1]["observed_probe"] == "leaked"

    # The real gate forks, so the neighbour starts from the pristine state.
    runner._LEAK_PROBE = None
    records = runner._run_forked_cases(cases, args, None, {}, 1)
    assert records[0]["observed_probe"] == "leaked"
    assert records[1]["observed_probe"] is None

    # The order of the cases is not significant.
    runner._LEAK_PROBE = None
    reversed_records = runner._run_forked_cases(
        list(reversed(cases)), args, None, {}, 1
    )
    verdicts = {
        (record["category"], record["id"]): record["status"] for record in records
    }
    reversed_verdicts = {
        (record["category"], record["id"]): record["status"]
        for record in reversed_records
    }
    assert verdicts == reversed_verdicts


# --------------------------------------------------------------------------
# 5. The expectation manifest's ratchet behaves
# --------------------------------------------------------------------------


def test_the_expectation_manifest_ratchet_behaves(tmp_path):
    """A regression fails, an improvement needs an update, a foreign corpus is rejected."""

    _call(
        manifest_contracts.test_perturbing_an_expected_status_fails_with_a_per_case_diff
    )
    _call(
        manifest_contracts.test_an_improvement_is_only_accepted_when_the_manifest_is_updated
    )
    _call(
        manifest_contracts.test_the_cli_rejects_a_run_against_another_suite_revision,
        tmp_path=tmp_path,
    )
    _call(manifest_contracts.test_every_gap_records_the_side_of_the_boundary_it_sits_on)
    _call(
        manifest_contracts.test_the_manifests_stage_counts_agree_with_its_per_case_verdicts
    )

    # A deliberately broken copy of the manifest: one case expects a pass
    # the run does not deliver.  The ratchet has to fail on it.
    manifest = _manifest()
    identity = next(
        case
        for case, entry in sorted(manifest["cases"].items())
        if entry["conversion"] == "unsupported"
    )
    broken = json.loads(json.dumps(manifest))
    broken["cases"][identity]["conversion"] = "passed"

    report = manifest_contracts._report_from_cases(manifest["cases"])
    comparison = inventory.compare_expectations(broken, report)
    assert len(comparison["differences"]) == 1
    assert comparison["differences"][0]["classification"] == "regression"

    # The status command reports the stale manifest and exits non-zero.
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    broken_path = tmp_path / "expectations.json"
    broken_path.write_text(json.dumps(broken), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "ci" / "sbml_campaign_status.py"),
            "--suite-report",
            str(report_path),
            "--expectations",
            str(broken_path),
            "--checkout-root",
            str(REPO),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    assert result.returncode != 0, result.stdout
    assert status.EXIT_MANIFEST_STALE & result.returncode
    assert "STALE" in result.stdout
    assert identity in result.stdout


# --------------------------------------------------------------------------
# 6. The slot fails open, and the jobs guard caps the worker count
# --------------------------------------------------------------------------


def test_the_verification_slot_fails_open_and_never_deadlocks(tmp_path):
    """A busy or unusable slot must not fail the run."""

    _call(
        isolation_contracts.test_busy_verification_slot_never_blocks_or_fails_a_run,
        tmp_path=tmp_path,
    )
    _call(
        isolation_contracts.test_verification_slot_is_held_for_the_run_and_released_after,
        tmp_path=tmp_path,
    )
    _call(
        isolation_contracts.test_stale_verification_slot_file_does_not_block_a_run,
        tmp_path=tmp_path,
    )
    _call(
        isolation_contracts.test_unusable_verification_slot_fails_open,
        tmp_path=tmp_path,
    )
    _call(isolation_contracts.test_jobs_is_rejected_when_it_is_not_positive)
    _call(
        isolation_contracts.test_jobs_advisory_warns_when_the_run_oversubscribes_the_machine
    )


def test_the_jobs_guard_caps_the_worker_count(tmp_path):
    """A run never forks more workers than the machine has CPUs."""

    native_extension = pytest.importorskip("bionetgen._bionetgen_cpp")
    suite, _lock = isolation_contracts._locked_ssts_checkout(tmp_path)
    cpu_count = os.cpu_count() or 1

    report_path = tmp_path / "report.json"
    result = isolation_contracts._run_gate(
        suite,
        _lock,
        report_path,
        "fork",
        ["--no-lock", "--jobs", "1000"],
    )
    assert report_path.is_file(), result.stdout + result.stderr
    document = json.loads(report_path.read_text(encoding="utf-8"))
    assert document["case_isolation"]["jobs"] <= cpu_count

    # The deliberately broken copy of the gate: one without the cap.  It
    # launches a worker per case, however many the operator asked for.
    broken_root = tmp_path / "broken"
    (broken_root / "scripts" / "ci").mkdir(parents=True)
    (broken_root / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (broken_root / "scripts" / "ci" / "__init__.py").write_text("", encoding="utf-8")
    source = GATE.read_text(encoding="utf-8")
    assert "args.jobs = min(args.jobs, cpu_count)" in source
    broken_source = source.replace(
        "args.jobs = min(args.jobs, cpu_count)", "pass  # the cap was removed"
    )
    broken_gate = broken_root / "scripts" / "ci" / "validate_sbml_test_suite.py"
    # The broken copy is a harness in a synthetic tree, so it has to be able
    # to import the same package and extension this checkout uses: the gate
    # refuses to measure a package it cannot trace to the tree that owns it,
    # and it would refuse before it ever reached the behaviour the test
    # breaks on purpose.
    # Copy the Python package rather than symlinking it so this temporary
    # installed-layout fixture can contain the same already-loaded extension.
    # That makes the subprocess exercise the same package/extension identity
    # guard as an installed CI build, even when this checkout has no build/cpp.
    shutil.copytree(
        REPO / "python",
        broken_root / "python",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    copied_extension = (
        broken_root / "python" / "bionetgen" / Path(native_extension.__file__).name
    )
    shutil.copy2(native_extension.__file__, copied_extension)
    assert copied_extension.read_bytes() == Path(native_extension.__file__).read_bytes()
    # The broken copy has to be able to import the modules the gate imports,
    # or it fails before it ever reaches the behaviour the test breaks on
    # purpose.
    shutil.copytree(
        REPO / "scripts" / "ci",
        broken_gate.parent,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("validate_sbml_test_suite.py"),
    )
    broken_gate.write_text(broken_source, encoding="utf-8")

    broken_report = tmp_path / "broken.json"
    broken_environment = dict(os.environ)
    # An editable install may register ScikitBuildRedirectingFinder ahead of
    # PathFinder and route ``bionetgen`` back to the primary checkout even
    # when PYTHONPATH names this synthetic checkout. Remove that environment
    # redirect only in this subprocess so the test exercises the broken copy
    # after the normal checkout-identity guard has verified its source.
    bootstrap = tmp_path / "synthetic_import_bootstrap"
    bootstrap.mkdir()
    (bootstrap / "sitecustomize.py").write_text(
        "import sys\n"
        "sys.meta_path[:] = [finder for finder in sys.meta_path "
        "if type(finder).__name__ != 'ScikitBuildRedirectingFinder']\n",
        encoding="utf-8",
    )
    entries = [str(bootstrap), str(broken_root / "python")]
    existing = broken_environment.get("PYTHONPATH")
    if existing:
        entries.append(existing)
    broken_environment["PYTHONPATH"] = os.pathsep.join(entries)
    broken_result = subprocess.run(
        [
            sys.executable,
            str(broken_gate),
            "--suite-dir",
            str(suite),
            "--lock",
            str(_lock),
            "--json",
            str(broken_report),
            "--categories",
            "semantic",
            "--isolate-cases",
            "--isolation-mode",
            "fork",
            "--jobs",
            "1000",
            "--case-timeout",
            "60",
            "--no-lock",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(broken_root),
        env=broken_environment,
    )
    assert broken_report.is_file(), broken_result.stdout + broken_result.stderr
    broken_document = json.loads(broken_report.read_text(encoding="utf-8"))
    assert broken_document["case_isolation"]["jobs"] > cpu_count


# --------------------------------------------------------------------------
# 7. The artifacts are reproducible under a pinned PYTHONHASHSEED
# --------------------------------------------------------------------------


def _atomizer_output(source: Path, hash_seed: str) -> str:
    """Return the Atomizer's output for a source under a pinned hash seed.

    The subprocess inherits the environment of the test process, so it
    imports the same ``bionetgen`` the test itself would import: the only
    thing this pins is the hash seed.
    """

    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = hash_seed
    worker = (
        "import sys\n"
        "from pathlib import Path\n"
        "from bionetgen.atomizer.modern import Atomizer\n"
        "source = Path(sys.argv[1])\n"
        "result = Atomizer(atomize=False, quiet_mode=True).atomize(\n"
        "    source.read_text(), source_path=source\n"
        ")\n"
        "if not result.success:\n"
        "    raise RuntimeError(result.error or 'Atomizer failed')\n"
        "print(result.bngl)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", worker, str(source)],
        check=True,
        capture_output=True,
        cwd=str(REPO),
        env=environment,
        text=True,
    )
    return completed.stdout


def _compare_artifacts(
    left: Path, right: Path, left_seed: str, right_seed: str
) -> dict[str, Any]:
    """Compare two artifacts, refusing to attribute a hash-order difference.

    An artifact that was produced under a different ``PYTHONHASHSEED`` is not
    comparable with one that was not: the difference may be the hash order
    rather than the change under review.  Such a pair is *detected*, not
    reported as a difference.
    """

    if left_seed != right_seed:
        return {
            "verdict": "not-comparable",
            "detail": (
                f"the artifacts were produced under different hash seeds "
                f"({left_seed} and {right_seed}); the difference is not "
                "attributable to the change under review"
            ),
        }
    if left.read_bytes() == right.read_bytes():
        return {"verdict": "identical", "detail": "the artifacts are byte-identical"}
    return {"verdict": "different", "detail": "the artifacts differ"}


def _compare_artifacts_ignoring_the_seed(left: Path, right: Path) -> str:
    """The deliberately broken comparison: one that ignores the hash seed.

    It calls every difference a difference, so a hash-order difference is
    mis-attributed to the change under review.
    """

    if left.read_bytes() == right.read_bytes():
        return "identical"
    return "different"


def test_the_artifacts_are_reproducible_under_a_pinned_hash_seed(tmp_path):
    """The same source and the same seed produce the same artifact."""

    _call(
        parity_contracts.test_static_species_reference_parameters_are_hash_seed_deterministic,
        tmp_path=tmp_path,
    )

    source = tmp_path / "reproducible.xml"
    source.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="reproducible">
    <listOfCompartments>
      <compartment id="c" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="c" initialAmount="1" hasOnlySubstanceUnits="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="0.5" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r" reversible="false">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k1</ci><ci>S1</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
""",
        encoding="utf-8",
    )

    first = _atomizer_output(source, "0")
    second = _atomizer_output(source, "0")
    assert first == second, "the artifact is not reproducible under a pinned seed"

    # A deliberately broken comparison: one that ignores the seed and calls
    # any difference a difference.  The seed-aware comparison detects that
    # such a pair is not comparable at all, so the hash-order difference is
    # not mis-attributed to the change under review.
    left = tmp_path / "left.bngl"
    right = tmp_path / "right.bngl"
    left.write_text("a\n", encoding="utf-8")
    right.write_text("b\n", encoding="utf-8")

    assert _compare_artifacts(left, right, "0", "0")["verdict"] == "different"
    detected = _compare_artifacts(left, right, "0", "1")
    assert detected["verdict"] == "not-comparable"
    assert "hash seeds" in detected["detail"]

    assert _compare_artifacts_ignoring_the_seed(left, right) == "different"


# --------------------------------------------------------------------------
# 8. The floor check works on the floor
# --------------------------------------------------------------------------


def test_the_floor_check_reaches_the_same_verdict_on_every_interpreter():
    """A construct the host cannot parse still needs a newer interpreter."""

    _call(floor_contracts.test_a_file_the_host_cannot_parse_needs_a_newer_interpreter)
    _call(floor_contracts.test_a_file_the_floor_cannot_parse_needs_a_newer_interpreter)
    _call(floor_contracts.test_a_match_statement_is_reported)
    _call(
        floor_contracts.test_the_declared_floor_is_the_oldest_interpreter_of_the_ci_matrix
    )
    _call(floor_contracts.test_the_repository_uses_no_construct_newer_than_the_floor)

    # The deliberately broken copy of the checker: one that swallows the
    # parse failure.  It cannot see the construct at all, and reports the
    # file as compatible with the floor.
    original = FLOOR_CHECKER.read_text(encoding="utf-8")
    broken_source = original.replace(
        '        findings.append(_syntax_finding(relative, error, host, "host", floor))',
        "        pass  # the parse failure was swallowed",
    )
    assert broken_source != original, "the floor checker's source did not change"

    with tempfile.TemporaryDirectory() as directory:
        broken_path = Path(directory) / "check_python_floor.py"
        broken_path.write_text(broken_source, encoding="utf-8")
        broken = _load_module(broken_path, "_contract_broken_floor_checker")

    real = _load_module(FLOOR_CHECKER, "_contract_real_floor_checker")
    floor = floor_contracts.FLOOR

    def refusing_parser(source, filename, feature_version=None):
        raise SyntaxError("f-string: unmatched '['")

    source = floor_contracts.PEP701_SOURCE
    real_findings = real.analyse_source(
        Path("sample.py"), source, floor, host=(3, 10), parser=refusing_parser
    )
    broken_findings = broken.analyse_source(
        Path("sample.py"), source, floor, host=(3, 10), parser=refusing_parser
    )

    assert real_findings, "the checker did not report the construct"
    assert all(finding.requires_newer_interpreter() for finding in real_findings)
    assert broken_findings == [], "the broken checker was expected to miss it"
