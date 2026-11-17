"""Retained modelapi modules must import in a fresh interpreter."""

import os
from pathlib import Path
import subprocess
import sys

import bionetgen
from bionetgen.model import _cpp

import pytest


@pytest.mark.parametrize("module", ["runner", "blocks", "pattern"])
def test_modelapi_submodule_import_is_not_swallowed(tmp_path, module):
    code = (
        "from bionetgen.modelapi import " + module + "\n"
        f"assert {module} is not None\n"
        f"assert {module}.__name__ == 'bionetgen.modelapi.{module}'\n"
    )
    environment = os.environ.copy()
    paths = [
        str(Path(bionetgen.__file__).resolve().parent.parent),
        str(Path(_cpp.__file__).resolve().parent),
    ]
    if environment.get("PYTHONPATH"):
        paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    process = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
