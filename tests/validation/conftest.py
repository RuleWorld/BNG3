"""Fixtures and markers for the BNG3 validation harness.

Markers (also declared in pytest.ini):
  smoke       Tier-S; runs on every commit
  parity      Tier-P; full corpus, nightly / WO completion
  nf          network-free, vs native NFsim oracle
  stochastic  SSA/PLA/PSA ensemble checks
  expressions rate-law / local-function RHS checks
  export      export-format validity

Engine discovery:
  --bng-cpp PATH  or env BNG_CPP   path to the bng_cpp CLI (for .net emission)
  The Python API (import bionetgen) is discovered normally; tests needing it
  skip cleanly if the compiled extension is not importable.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.validation import corpus


def pytest_addoption(parser):
    parser.addoption("--bng-cpp", action="store", default=None,
                     help="Path to the bng_cpp CLI executable")


def _discover_bng_cpp(explicit: str | None) -> Path | None:
    candidates = [
        explicit,
        os.environ.get("BNG_CPP"),
        corpus.REPO / "build" / "bng_cpp",
        corpus.REPO / "build" / "bng_cpp.exe",
        corpus.REPO / "build" / "cpp" / "bng_cpp",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return Path(c)
    return None


@pytest.fixture(scope="session")
def bng_cpp(request) -> Path:
    p = _discover_bng_cpp(request.config.getoption("--bng-cpp"))
    if p is None:
        pytest.skip("bng_cpp CLI not found (build it, or pass --bng-cpp / set BNG_CPP)")
    return p


@pytest.fixture(scope="session")
def have_api() -> bool:
    try:
        import bionetgen  # noqa: F401
        import bionetgen.model  # the compiled path, not the Perl fallback
        return True
    except Exception:
        return False


@pytest.fixture
def api(have_api):
    if not have_api:
        pytest.skip("compiled bionetgen extension not importable")
    import bionetgen
    return bionetgen


@pytest.fixture
def work_dir(tmp_path) -> Path:
    return tmp_path
