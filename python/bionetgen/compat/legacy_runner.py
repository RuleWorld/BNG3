"""Legacy subprocess-based runner using Perl BNG2.pl.

Activated by setting BIONETGEN_USE_PERL=1 environment variable.
This module provides backward compatibility during the transition period.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Union


def _find_perl_bng() -> str:
    bng_path = os.environ.get("BNGPATH")
    if bng_path:
        candidate = Path(bng_path) / "BNG2.pl"
        if candidate.exists():
            return str(candidate)

    legacy_dir = Path(__file__).parent.parent.parent.parent / "legacy" / "perl"
    candidate = legacy_dir / "BNG2.pl"
    if candidate.exists():
        return str(candidate)

    raise FileNotFoundError(
        "Cannot find BNG2.pl. Set BNGPATH environment variable or install legacy Perl BNG."
    )


class LegacyModel:
    """Thin wrapper that invokes BNG2.pl via subprocess."""

    def __init__(self, path: str):
        self._path = path
        self._bng_exec = _find_perl_bng()

    def simulate(self, **kwargs):
        raise NotImplementedError(
            "Legacy model simulation via subprocess is deprecated. "
            "Unset BIONETGEN_USE_PERL to use the C++ backend."
        )

    def execute(self, verbose: bool = False):
        cmd = ["perl", self._bng_exec, self._path]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(Path(self._path).parent),
        )
        if result.returncode != 0:
            raise RuntimeError(f"BNG2.pl failed:\n{result.stderr}")
        if verbose:
            print(result.stdout)


def load(path: Union[str, Path]) -> LegacyModel:
    return LegacyModel(str(Path(path).resolve()))


def run(path: Union[str, Path], **kwargs):
    model = load(path)
    model.execute()
