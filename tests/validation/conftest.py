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
import sys
from pathlib import Path

import pytest
from scripts.ci.python_package_mode import (
    editable_source_roots,
    resolve_test_mode,
    verify_package_locations,
)

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_PACKAGE = (_ROOT / "python" / "bionetgen").resolve()
_LOCAL_EXTENSION_DIR = (_ROOT / "build" / "cpp").resolve()
_MODE = os.environ.get("BNG3_PYTHON_TEST_MODE", "auto")
_SOURCE_PATH_PRESENT = any(
    Path(path or ".").resolve() == (_ROOT / "python").resolve() for path in sys.path
)
_LOADED_PACKAGE = sys.modules.get("bionetgen")
_LOADED_FROM_SOURCE = bool(
    _LOADED_PACKAGE
    and getattr(_LOADED_PACKAGE, "__file__", None)
    and Path(_LOADED_PACKAGE.__file__).resolve().is_relative_to(_SOURCE_PACKAGE)
)
_TEST_MODE, _BNG3_EDITABLE_FINDERS = resolve_test_mode(
    _MODE,
    finders=sys.meta_path,
    source_path_present=_SOURCE_PATH_PRESENT,
    loaded_from_source=_LOADED_FROM_SOURCE,
    auto_default=None,
)
if _TEST_MODE is not None:
    # Spawned API workers reconstruct a fresh interpreter. Carry the mode that
    # this conftest resolved so workers cannot fall back to another checkout.
    os.environ["BNG3_PYTHON_TEST_MODE"] = _TEST_MODE

if _TEST_MODE == "source":
    if not (_SOURCE_PACKAGE / "__init__.py").is_file():
        raise RuntimeError(f"source package is missing: {_SOURCE_PACKAGE}")
    if _BNG3_EDITABLE_FINDERS:
        sys.meta_path = [
            finder for finder in sys.meta_path if finder not in _BNG3_EDITABLE_FINDERS
        ]
        _EDITABLE_SOURCES = editable_source_roots(_BNG3_EDITABLE_FINDERS, "bionetgen")
        sys.path[:] = [
            path
            for path in sys.path
            if Path(path or ".").resolve() not in _EDITABLE_SOURCES
        ]
    if not _LOCAL_EXTENSION_DIR.is_dir():
        raise RuntimeError(
            "source mode requires this worktree's native extension directory: "
            f"{_LOCAL_EXTENSION_DIR}"
        )
    if _LOADED_PACKAGE and not _LOADED_FROM_SOURCE:
        raise RuntimeError(
            "bionetgen was imported before source mode could select this worktree: "
            f"{getattr(_LOADED_PACKAGE, '__file__', None)}"
        )
    sys.path.insert(0, str(_LOCAL_EXTENSION_DIR))
    sys.path.insert(0, str(_ROOT / "python"))
    try:
        import bionetgen
        import bionetgen._bionetgen_cpp as _cpp_probe  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "source mode could not import this worktree's Python package and "
            f"native extension ({_SOURCE_PACKAGE}, {_LOCAL_EXTENSION_DIR}): {exc}"
        ) from exc
    verify_package_locations(
        bionetgen.__file__,
        _cpp_probe.__file__,
        package_dir=_SOURCE_PACKAGE,
        extension_dir=_LOCAL_EXTENSION_DIR,
        mode="source",
    )
elif _TEST_MODE == "installed":
    import importlib.metadata

    try:
        _DIST_PACKAGE = Path(
            importlib.metadata.distribution("bionetgen").locate_file("bionetgen")
        ).resolve()
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "installed package mode requires an installed bionetgen distribution"
        ) from exc
    try:
        import bionetgen
        import bionetgen._bionetgen_cpp as _cpp_probe  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "installed bionetgen distribution has no importable native extension: "
            f"{_DIST_PACKAGE}; underlying error: {exc}"
        ) from exc
    verify_package_locations(
        bionetgen.__file__,
        _cpp_probe.__file__,
        package_dir=_DIST_PACKAGE,
        extension_dir=_DIST_PACKAGE,
        mode="installed",
    )

from tests.validation import corpus, runner
from tests.validation.strict import require_oracle


def pytest_addoption(parser):
    parser.addoption(
        "--bng-cpp",
        action="store",
        default=None,
        help="Path to the bng_cpp CLI executable",
    )


def _discover_bng_cpp(explicit: str | None) -> Path | None:
    candidates = [
        explicit,
        os.environ.get("BNG_CPP"),
        corpus.REPO / "build" / "bng_cpp",
        corpus.REPO / "build" / "bng_cpp.exe",
        corpus.REPO / "build" / "cpp" / "bng_cpp",
    ]
    for c in candidates:
        if c:
            path = Path(c).expanduser()
            if path.exists():
                return path.resolve()
    return None


@pytest.fixture(scope="session")
def bng_cpp(request) -> Path:
    p = _discover_bng_cpp(request.config.getoption("--bng-cpp"))
    require_oracle(
        p is not None,
        "bng_cpp CLI not found (build it, or pass --bng-cpp / set BNG_CPP)",
    )
    assert p is not None
    return p


@pytest.fixture(scope="session")
def have_api() -> bool:
    return runner.api_available()


@pytest.fixture
def api(have_api):
    # Routed through require_oracle, exactly as the bng_cpp fixture above does.
    # A bare pytest.skip here meant that a checkout whose compiled extension was
    # not importable reported every test using this fixture as skipped and
    # exited 0 -- including under BNG3_CI_STRICT_ORACLES=1, which exists
    # precisely to turn a missing engine into a failure. Verified by calling this
    # branch directly: it raised pytest.skip, not pytest.fail.
    #
    # The trade is the same one bng_cpp already made: under the strict flag a
    # missing engine fails, and a local run without a build still skips.
    require_oracle(have_api, "compiled bionetgen extension not importable")
    import bionetgen

    return bionetgen


@pytest.fixture
def work_dir(tmp_path) -> Path:
    return tmp_path
