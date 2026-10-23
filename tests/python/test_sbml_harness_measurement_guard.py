"""The SBML corpus harnesses must measure this checkout, reproducibly.

Three properties are pinned here:

* the ``bionetgen`` package and the native extension a harness imports must
  be traceable to the checkout that owns the harness, so a stale installation
  cannot become the subject of a measurement;
* the harness must report which package and which extension it measured, in
  the summary line people read and quote;
* the generated text must be the same on every run, which requires a fixed
  interpreter hash seed in the processes that produce the artifacts.

The regression tests simulate a foreign installation instead of depending on
a stale copy being present on the machine.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
GUARD_PATH = REPO / "scripts" / "ci" / "imported_package_guard.py"
ENVIRONMENT_PATH = REPO / "scripts" / "ci" / "deterministic_environment.py"
SUITE_HARNESS = REPO / "scripts" / "ci" / "validate_sbml_test_suite.py"
BIOMODELS_HARNESS = REPO / "scripts" / "ci" / "validate_published_biomodels.py"

# A model whose re-imported BNGL depends on the interpreter's hash seed: the
# rate rule folds to zero only in one of the term orders the static
# evaluator can produce.
HASH_SEED_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="hashseed">
    <listOfCompartments>
      <compartment id="C1" spatialDimensions="3" size="0.5" constant="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C1" initialAmount="3"
        hasOnlySubstanceUnits="false" boundaryCondition="true" constant="false"/>
    </listOfSpecies>
    <listOfRules>
      <rateRule variable="S1">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <divide/>
            <apply>
              <times/>
              <cn> -0.2 </cn>
              <ci> S1 </ci>
            </apply>
            <ci> C1 </ci>
          </apply>
        </math>
      </rateRule>
      <rateRule variable="C1">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <cn> 0.2 </cn>
        </math>
      </rateRule>
    </listOfRules>
  </model>
</sbml>
"""


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _guard() -> ModuleType:
    return _load(GUARD_PATH, "imported_package_guard")


def _environment() -> ModuleType:
    return _load(ENVIRONMENT_PATH, "deterministic_environment")


@pytest.mark.parametrize("child_status", [0, 1])
def test_windows_hash_seed_reexec_propagates_child_status(
    tmp_path, monkeypatch, child_status
):
    environment = _environment()
    script = tmp_path / "validate_sbml_test_suite.py"
    script.write_text("# re-executable stand-in\n", encoding="utf-8")
    environment_keys = ("PYTHONHASHSEED", environment._REEXEC_MARKER)
    before = {key: os.environ.get(key) for key in environment_keys}
    with monkeypatch.context() as isolated:
        isolated.setattr(environment, "STARTUP_HASH_SEED", "1")
        isolated.setattr(environment.sys, "argv", [str(script)])
        isolated.setattr(environment.os, "name", "nt")
        isolated.setattr(environment, "_reexecutable", lambda: True)
        # ensure_fixed_hash_seed intentionally changes both values before the
        # Windows child exits. Keep those process-wide mutations inside this
        # test so later harness invocations exercise their own startup seed.
        isolated.setenv("PYTHONHASHSEED", "1")
        isolated.setenv(environment._REEXEC_MARKER, "")
        isolated.setattr(
            environment.subprocess,
            "run",
            lambda command, env, check: subprocess.CompletedProcess(
                command, child_status
            ),
        )

        with pytest.raises(SystemExit) as excinfo:
            environment.ensure_fixed_hash_seed()

        assert excinfo.value.code == child_status

    assert {key: os.environ.get(key) for key in environment_keys} == before


@pytest.mark.parametrize("child_status", [0, 1])
def test_windows_hash_seed_reexec_process_exit_status(tmp_path, child_status):
    script = tmp_path / "reexec_probe.py"
    script.write_text(
        "\n".join(
            [
                "import importlib.util",
                "import os",
                "import sys",
                "",
                "if os.environ.get('BNG3_HARNESS_FIXED_HASH_SEED'):",
                "    assert os.environ['PYTHONHASHSEED'] == '0'",
                "    raise SystemExit(int(os.environ['EXPECTED_CHILD_STATUS']))",
                f"environment_path = {str(ENVIRONMENT_PATH)!r}",
                "spec = importlib.util.spec_from_file_location(",
                "    'deterministic_environment', environment_path",
                ")",
                "environment = importlib.util.module_from_spec(spec)",
                "spec.loader.exec_module(environment)",
                "environment.STARTUP_HASH_SEED = 'random'",
                "environment._reexecutable = lambda: True",
                "if os.name != 'nt':",
                "    environment.os.name = 'nt'",
                "    environment.os.execv = lambda *args: (_ for _ in ()).throw(",
                "        OSError('execv does not replace the process on Windows')",
                "    )",
                "environment.ensure_fixed_hash_seed()",
                "raise AssertionError('re-exec did not exit the parent process')",
                "",
            ]
        ),
        encoding="utf-8",
    )
    process_environment = os.environ.copy()
    process_environment.pop("BNG3_HARNESS_FIXED_HASH_SEED", None)
    process_environment["PYTHONHASHSEED"] = "1"
    process_environment["EXPECTED_CHILD_STATUS"] = str(child_status)

    result = subprocess.run(
        [sys.executable, str(script)],
        env=process_environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == child_status
    assert result.stderr == ""


def _stand_in_package(directory: Path, marker: str) -> Path:
    """Write a stand-in for an unrelated installed BNG3 package."""

    package = directory / "bionetgen"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        f'__version__ = "{marker}"\n', encoding="utf-8"
    )
    # A stub native module keeps the unfixed harness on its measurement path
    # instead of stopping at the extension check, so the refusal below is the
    # only thing that separates the two behaviours.
    (package / "_bionetgen_cpp.py").write_text(
        '"""Stand-in for the compiled extension."""\n', encoding="utf-8"
    )
    return package


def _package_module(package_file: Path) -> ModuleType:
    module = ModuleType("bionetgen")
    module.__file__ = str(package_file)
    return module


def _locked_ssts_checkout(
    tmp_path: Path, case_xml: str | None = None
) -> tuple[Path, Path]:
    """Build the minimal locked suite checkout the harness preflight accepts."""

    suite = tmp_path / "suite"
    suite.mkdir()
    subprocess.run(["git", "-C", str(suite), "init"], check=True, capture_output=True)
    for category in ("semantic", "stochastic"):
        case_dir = suite / "cases" / category / "00001"
        case_dir.mkdir(parents=True)
        (case_dir / "00001-sbml-l3v2.xml").write_text(
            case_xml if case_xml is not None else "<sbml/>\n", encoding="utf-8"
        )
    subprocess.run(
        ["git", "-C", str(suite), "add", "cases"], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(suite),
            "-c",
            "user.name=SSTS test",
            "-c",
            "user.email=ssts@example.invalid",
            "commit",
            "-m",
            "initial",
        ],
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
    return suite, lock


def _harness_environment(seed: str | None = None) -> dict[str, str]:
    """Return an environment in which the harness measures this checkout."""

    environment = dict(os.environ)
    if seed is not None:
        environment["PYTHONHASHSEED"] = seed
    build_cpp = REPO / "build" / "cpp"
    if any(build_cpp.glob("_bionetgen_cpp*")):
        entries = [str(REPO / "python"), str(build_cpp)]
        existing = environment.get("PYTHONPATH")
        if existing:
            entries.append(existing)
        environment["PYTHONPATH"] = os.pathsep.join(entries)
    return environment


def _run_harness(
    suite: Path,
    lock: Path,
    report: Path,
    *,
    artifacts: Path | None = None,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    command = [
        sys.executable,
        str(SUITE_HARNESS),
        "--suite-dir",
        str(suite),
        "--lock",
        str(lock),
        "--json",
        str(report),
        "--categories",
        "semantic",
        "--isolate-cases",
    ]
    if artifacts is not None:
        command.extend(["--artifacts-dir", str(artifacts)])
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        env=environment if environment is not None else _harness_environment(),
    )


# ── the imported Python package ────────────────────────────────────────────


def test_guard_refuses_a_foreign_installed_package(tmp_path):
    guard = _guard()
    foreign = _stand_in_package(tmp_path / "site-packages", "0.0.0-foreign")

    with pytest.raises(guard.ForeignPackageError) as excinfo:
        guard.verify_imported_package(
            REPO, package_module=_package_module(foreign / "__init__.py")
        )

    message = str(excinfo.value)
    assert str(foreign / "__init__.py") in message
    assert str(REPO / "python" / "bionetgen") in message
    assert "PYTHONPATH=python:build/cpp" in message


def test_guard_refuses_a_stale_copy_of_this_checkout(tmp_path):
    """A copy of the package whose source drifted is not this checkout."""

    guard = _guard()
    stale = tmp_path / "site-packages" / "bionetgen"
    stale.mkdir(parents=True)
    for source in sorted((REPO / "python" / "bionetgen").rglob("*.py")):
        target = stale / source.relative_to(REPO / "python" / "bionetgen")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    (stale / "__init__.py").write_text("# drifted\n", encoding="utf-8")

    with pytest.raises(guard.ForeignPackageError):
        guard.verify_imported_package(
            REPO, package_module=_package_module(stale / "__init__.py")
        )


def test_guard_accepts_this_checkouts_own_package():
    guard = _guard()
    package_file = REPO / "python" / "bionetgen" / "__init__.py"

    trace = guard.verify_imported_package(
        REPO, package_module=_package_module(package_file)
    )

    assert trace["rule"] == guard.TRACE_SAME_CHECKOUT
    assert trace["package_file"] == str(package_file.resolve())


def test_guard_accepts_an_identical_copy_installed_elsewhere(tmp_path):
    """A distribution installed from this checkout measures this checkout."""

    guard = _guard()
    installed = tmp_path / "site-packages" / "bionetgen"
    installed.mkdir(parents=True)
    for source in sorted((REPO / "python" / "bionetgen").rglob("*.py")):
        target = installed / source.relative_to(REPO / "python" / "bionetgen")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    trace = guard.verify_imported_package(
        REPO, package_module=_package_module(installed / "__init__.py")
    )

    assert trace["rule"] == guard.TRACE_SAME_SOURCE


def test_guard_accepts_a_sibling_checkout_of_the_same_repository(tmp_path):
    guard = _guard()
    origin = guard._git_origin_url(REPO)
    if not origin:
        pytest.skip("this checkout has no origin remote to compare")
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    subprocess.run(["git", "-C", str(sibling), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(sibling), "remote", "add", "origin", origin], check=True
    )
    package = sibling / "python" / "bionetgen"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")

    trace = guard.verify_imported_package(
        REPO, package_module=_package_module(package / "__init__.py")
    )

    assert trace["rule"] == guard.TRACE_SIBLING_CHECKOUT
    assert trace["sibling_checkout_root"] == str(sibling)


def test_sbml_suite_harness_refuses_to_measure_a_foreign_package(tmp_path):
    suite, lock = _locked_ssts_checkout(tmp_path)
    foreign = _stand_in_package(tmp_path / "site-packages", "0.0.0-foreign")
    report = tmp_path / "report.json"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(foreign.parent)

    result = _run_harness(suite, lock, report, environment=environment)

    assert result.returncode == 1
    assert "package preflight failed" in result.stderr
    assert str(foreign / "__init__.py") in result.stderr
    assert "PYTHONPATH=python:build/cpp" in result.stderr
    assert (
        not report.exists()
    ), "the harness measured the foreign package instead of refusing it"


def test_biomodels_harness_refuses_to_measure_a_foreign_package(tmp_path):
    foreign = _stand_in_package(tmp_path / "site-packages", "0.0.0-foreign")
    report = tmp_path / "report.json"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(foreign.parent)

    result = subprocess.run(
        [
            sys.executable,
            str(BIOMODELS_HARNESS),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--json",
            str(report),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 1
    assert "package preflight failed" in result.stderr
    assert str(foreign / "__init__.py") in result.stderr
    assert not report.exists()


# ── the imported native extension ──────────────────────────────────────────


def test_guard_accepts_the_checkouts_own_native_extension(tmp_path):
    guard = _guard()
    build_cpp = tmp_path / "build" / "cpp"
    build_cpp.mkdir(parents=True)
    extension = build_cpp / "_bionetgen_cpp.so"
    extension.write_bytes(b"\x7fELF stub")
    package_trace = {
        "rule": guard.TRACE_SAME_CHECKOUT,
        "package_file": str(tmp_path / "python" / "bionetgen" / "__init__.py"),
    }

    trace = guard.verify_native_extension(
        tmp_path, extension_file=extension, package_trace=package_trace
    )

    assert trace["rule"] == guard.TRACE_SAME_CHECKOUT_BUILD


def test_guard_accepts_the_installed_distributions_native_extension(tmp_path):
    guard = _guard()
    installed = tmp_path / "site-packages" / "bionetgen"
    installed.mkdir(parents=True)
    extension = installed / "_bionetgen_cpp.so"
    extension.write_bytes(b"\x7fELF stub")
    package_trace = {
        "rule": guard.TRACE_SAME_SOURCE,
        "package_file": str(installed / "__init__.py"),
    }

    trace = guard.verify_native_extension(
        tmp_path, extension_file=extension, package_trace=package_trace
    )

    assert trace["rule"] == guard.TRACE_INSTALLED_DISTRIBUTION


def test_guard_accepts_a_sibling_checkouts_native_extension(tmp_path):
    guard = _guard()
    origin = guard._git_origin_url(REPO)
    if not origin:
        pytest.skip("this checkout has no origin remote to compare")
    sibling = tmp_path / "sibling"
    (sibling / "build" / "cpp").mkdir(parents=True)
    subprocess.run(["git", "-C", str(sibling), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(sibling), "remote", "add", "origin", origin], check=True
    )
    extension = sibling / "build" / "cpp" / "_bionetgen_cpp.so"
    extension.write_bytes(b"\x7fELF stub")
    package_trace = {
        "rule": guard.TRACE_SIBLING_CHECKOUT,
        "package_file": str(sibling / "python" / "bionetgen" / "__init__.py"),
    }

    trace = guard.verify_native_extension(
        REPO, extension_file=extension, package_trace=package_trace
    )

    assert trace["rule"] == guard.TRACE_SIBLING_CHECKOUT_BUILD


def test_guard_refuses_a_foreign_native_extension(tmp_path):
    guard = _guard()
    foreign = tmp_path / "somewhere" / "_bionetgen_cpp.so"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"\x7fELF stub")
    package_trace = {
        "rule": guard.TRACE_SAME_CHECKOUT,
        "package_file": str(REPO / "python" / "bionetgen" / "__init__.py"),
    }

    with pytest.raises(guard.ForeignPackageError) as excinfo:
        guard.verify_native_extension(
            REPO, extension_file=foreign, package_trace=package_trace
        )

    message = str(excinfo.value)
    assert str(foreign) in message
    assert "PYTHONPATH=python:build/cpp" in message


# ── the provenance the report and the summary carry ────────────────────────


def test_harness_summary_names_the_measured_package_and_extension(tmp_path):
    suite, lock = _locked_ssts_checkout(tmp_path)
    report = tmp_path / "report.json"

    result = _run_harness(suite, lock, report)

    if "package preflight failed" in result.stderr:
        pytest.skip("this environment cannot run the harness on its own package")
    assert result.returncode in (0, 1)
    summary = [line for line in result.stdout.splitlines() if line.startswith("cases=")]
    assert summary, result.stdout
    assert " package=" in summary[-1]
    assert " extension_sha256=" in summary[-1]
    provenance = json.loads(report.read_text(encoding="utf-8"))["runtime_provenance"]
    assert provenance["imported_package_trace"]["package_file"] in summary[-1]
    assert provenance["native_extension_sha256"] in summary[-1]


def test_harness_records_the_fixed_hash_seed(tmp_path):
    suite, lock = _locked_ssts_checkout(tmp_path)
    report = tmp_path / "report.json"

    result = _run_harness(
        suite, lock, report, environment=_harness_environment(seed="2")
    )

    if "package preflight failed" in result.stderr:
        pytest.skip("this environment cannot run the harness on its own package")
    provenance = json.loads(report.read_text(encoding="utf-8"))["runtime_provenance"]
    assert provenance["python_hash_seed"] == "0"


def test_child_environment_pins_the_hash_seed():
    environment = _environment()

    pinned = environment.fixed_hash_seed_environment({"OTHER": "value"})

    assert pinned["PYTHONHASHSEED"] == environment.FIXED_HASH_SEED
    assert pinned["OTHER"] == "value"


# ── the generated text is reproducible ─────────────────────────────────────


def test_harness_artifacts_are_byte_identical_across_processes(tmp_path):
    """The same case must produce the same text in two separate processes.

    The model re-imports into BNGL whose rate expression depends on the
    interpreter's hash seed, so an unpinned harness produces two different
    files for one case.
    """

    suite, lock = _locked_ssts_checkout(tmp_path, case_xml=HASH_SEED_MODEL)
    artifacts = []
    for index, seed in enumerate(("1", "2")):
        directory = tmp_path / f"artifacts-{index}"
        report = tmp_path / f"report-{index}.json"
        result = _run_harness(
            suite,
            lock,
            report,
            artifacts=directory,
            environment=_harness_environment(seed=seed),
        )
        if "package preflight failed" in result.stderr:
            pytest.skip("this environment cannot run the harness on its own package")
        artifacts.append(directory / "semantic" / "00001" / "reimported.bngl")

    assert artifacts[0].is_file(), "the harness produced no re-imported BNGL"
    assert artifacts[1].is_file(), "the harness produced no re-imported BNGL"
    assert artifacts[0].read_bytes() == artifacts[1].read_bytes()
