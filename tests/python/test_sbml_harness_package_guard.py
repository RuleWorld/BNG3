"""The SBML corpus harnesses must refuse to measure a foreign BNG3 package.

A harness that imports ``bionetgen`` from a stale installation measures that
installation while producing an entirely normal-looking report.  The guards
below make the harness refuse instead, and these tests pin the refusal.
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
SUITE_HARNESS = REPO / "scripts" / "ci" / "validate_sbml_test_suite.py"


def _guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("imported_package_guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _locked_ssts_checkout(tmp_path: Path) -> tuple[Path, Path]:
    """Build the minimal locked suite checkout the harness preflight accepts."""

    suite = tmp_path / "suite"
    suite.mkdir()
    subprocess.run(["git", "-C", str(suite), "init"], check=True, capture_output=True)
    for category in ("semantic", "stochastic"):
        case_dir = suite / "cases" / category / "00001"
        case_dir.mkdir(parents=True)
        (case_dir / "00001-sbml-l3v2.xml").write_text("<sbml/>\n", encoding="utf-8")
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
    env = dict(os.environ)
    env["PYTHONPATH"] = str(foreign.parent)

    result = subprocess.run(
        [
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
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=env,
    )

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
    env = dict(os.environ)
    env["PYTHONPATH"] = str(foreign.parent)

    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "ci" / "validate_published_biomodels.py"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--json",
            str(report),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "package preflight failed" in result.stderr
    assert str(foreign / "__init__.py") in result.stderr
    assert not report.exists()
