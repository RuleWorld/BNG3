"""Subprocess contracts for validation-suite package import selection."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]


def _sitecustomize(overlay: Path, body: str) -> None:
    (overlay / "sitecustomize.py").write_text(body, encoding="utf-8")


def _run_conftest(
    tmp_path: Path, mode: str, setup: str, probe: str
) -> subprocess.CompletedProcess[str]:
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    _sitecustomize(overlay, setup)
    env = os.environ.copy()
    env["BNG3_PYTHON_TEST_MODE"] = mode
    # sitecustomize runs before the current directory is added to sys.path for
    # ``python -c``, so expose the repository root while the startup hook imports
    # its BNG3 package-mode helper.
    env["PYTHONPATH"] = os.pathsep.join((str(overlay), str(REPO)))
    env["BNG3_TEST_REPO"] = str(REPO)
    return subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _fake_installed_site(tmp_path: Path) -> Path:
    fake_site = tmp_path / "site-packages"
    package = fake_site / "bionetgen"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '0.0'\n", encoding="utf-8")
    (package / "_bionetgen_cpp.py").write_text(
        "IDENTITY = 'fake-installed'\n", encoding="utf-8"
    )
    metadata = fake_site / "bionetgen-0.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: bionetgen\nVersion: 0.0\n",
        encoding="utf-8",
    )
    return fake_site


def _run_with_fake_installed_site(
    tmp_path: Path, probe: str
) -> subprocess.CompletedProcess[str]:
    fake_site = _fake_installed_site(tmp_path)
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    _sitecustomize(
        overlay,
        """
import os, sys
for finder in tuple(sys.meta_path):
    sources = getattr(finder, "known_source_files", {}) or {}
    if any(name == "bionetgen" or name.startswith("bionetgen.") for name in sources):
        sys.meta_path.remove(finder)
class UnrelatedEditableFinder:
    __module__ = "_editable_unrelated"
    known_source_files = {"other_package": "/tmp/other_package/__init__.py"}
    def find_spec(self, fullname, path=None, target=None):
        return None
sys.meta_path.insert(0, UnrelatedEditableFinder())
sys.path.insert(0, os.environ["BNG3_TEST_SITE"])
""",
    )
    env = os.environ.copy()
    env["BNG3_PYTHON_TEST_MODE"] = "installed"
    env["BNG3_TEST_REPO"] = str(REPO)
    env["BNG3_TEST_SITE"] = str(fake_site)
    env["PYTHONPATH"] = str(overlay)
    return subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_installed_mode_rejects_a_bng3_editable_finder(tmp_path):
    result = _run_conftest(
        tmp_path,
        "installed",
        """
import os, sys
from pathlib import Path
from scripts.ci.python_package_mode import editable_finders_for_package
for finder in editable_finders_for_package(tuple(sys.meta_path)):
    sys.meta_path.remove(finder)
class BNG3EditableFinder:
    __module__ = "_editable_bionetgen"
    known_source_files = {
        "bionetgen": str(Path(os.environ["BNG3_TEST_REPO"]) / "python/bionetgen/__init__.py")
    }
    def find_spec(self, fullname, path=None, target=None):
        return None
sys.meta_path.insert(0, BNG3EditableFinder())
class UnrelatedEditableFinder:
    __module__ = "_editable_unrelated"
    known_source_files = {"other_package": "/tmp/other_package/__init__.py"}
    def find_spec(self, fullname, path=None, target=None):
        return None
sys.meta_path.insert(0, UnrelatedEditableFinder())
""",
        "import runpy; runpy.run_path('tests/validation/conftest.py')",
    )

    assert result.returncode != 0
    assert (
        "installed package tests found a BNG3 editable import finder" in result.stderr
    )


@pytest.mark.parametrize(
    "conftest",
    ["tests/validation/conftest.py", "tests/python/conftest.py"],
)
def test_installed_mode_keeps_an_unrelated_editable_finder_and_package(
    tmp_path, conftest
):
    probe = """
import os, runpy, sys
from pathlib import Path
runpy.run_path(os.environ['BNG3_TEST_CONFTEXT'])
import bionetgen
import bionetgen._bionetgen_cpp as native
expected = Path(os.environ['BNG3_TEST_SITE']) / 'bionetgen'
assert Path(bionetgen.__file__).resolve().parent == expected.resolve(), bionetgen.__file__
assert Path(native.__file__).resolve().parent == expected.resolve(), native.__file__
assert any(type(f).__module__ == '_editable_unrelated' for f in sys.meta_path)
"""
    result = _run_with_fake_installed_site(
        tmp_path, probe.replace("os.environ['BNG3_TEST_CONFTEXT']", repr(conftest))
    )

    assert result.returncode == 0, result.stderr


def test_installed_identity_script_keeps_an_unrelated_editable_finder(tmp_path):
    result = _run_with_fake_installed_site(
        tmp_path,
        """
import os, sys
from scripts.ci.check_python_package_identity import inspect_installed_package
identity = inspect_installed_package()
assert identity['package_file'].startswith(os.environ['BNG3_TEST_SITE'])
assert identity['native_extension'].startswith(os.environ['BNG3_TEST_SITE'])
assert any(type(f).__module__ == '_editable_unrelated' for f in sys.meta_path)
""",
    )

    assert result.returncode == 0, result.stderr


def test_source_mode_keeps_an_unrelated_editable_finder(tmp_path):
    result = _run_conftest(
        tmp_path,
        "source",
        """
import sys
class UnrelatedEditableFinder:
    __module__ = "_editable_unrelated"
    known_source_files = {"other_package": "/tmp/other_package/__init__.py"}
    def find_spec(self, fullname, path=None, target=None):
        return None
sys.meta_path.insert(0, UnrelatedEditableFinder())
""",
        """
import os, runpy, sys
from pathlib import Path
runpy.run_path('tests/validation/conftest.py')
import bionetgen
import bionetgen._bionetgen_cpp as native
root = Path(os.environ['BNG3_TEST_REPO'])
assert Path(bionetgen.__file__).resolve().is_relative_to(root / 'python' / 'bionetgen')
assert Path(native.__file__).resolve().parent == (root / 'build' / 'cpp').resolve()
assert any(type(f).__module__ == '_editable_unrelated' for f in sys.meta_path)
""",
    )

    assert result.returncode == 0, result.stderr
