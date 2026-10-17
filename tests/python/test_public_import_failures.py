"""Required Python implementation failures must reach the caller unchanged."""

import os
import subprocess
import sys

import bionetgen
import pytest

from scripts.ci.python_package_mode import subprocess_import_setup


@pytest.mark.parametrize("module", ["model", "builder", "sbml", "_bionetgen_cpp"])
@pytest.mark.parametrize("kind", ["ImportError", "ModuleNotFoundError"])
def test_required_public_module_import_failure_is_not_hidden(module, kind, tmp_path):
    # Select the same package before installing the fault. Avoid another wheel
    # or editable checkout masking a defect in the package being tested.
    code = (
        subprocess_import_setup(bionetgen.__file__, bionetgen._bionetgen_cpp.__file__)
        + f"""
import importlib.abc
import sys

class SelectedPackage(importlib.abc.MetaPathFinder):
    injected = False
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'bionetgen.{module}' and not self.injected:
            self.injected = True
            raise {kind}('required implementation failed', name='internal_dependency')

sys.meta_path.insert(0, SelectedPackage())
try:
    import bionetgen
except {kind} as error:
    assert str(error) == 'required implementation failed', error
    assert error.name == 'internal_dependency', error
else:
    raise AssertionError('required module failure was hidden by fallback or None export')
"""
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_absent_native_modules_remain_distinct_from_broken_native_modules(tmp_path):
    code = (
        subprocess_import_setup(bionetgen.__file__, bionetgen._bionetgen_cpp.__file__)
        + """
class MissingNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('bionetgen._bionetgen_cpp', '_bionetgen_cpp'):
            raise ModuleNotFoundError('native module absent', name=fullname)

sys.meta_path.insert(0, MissingNative())
import bionetgen.model
import bionetgen.builder
import bionetgen.sbml
assert bionetgen.model._cpp is None
assert bionetgen.builder._cpp is None
assert bionetgen.sbml._cpp is None
assert callable(bionetgen.ModelBuilder)
assert callable(bionetgen.from_sbml)
"""
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
