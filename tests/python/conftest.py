"""
PyTest Fixtures and markers.
"""

# ---------------------------------------------------------------------------
# Must stay the FIRST executable code in this file, above the `_has_perl_bng`
# call below. That call runs at module import time and imports `bionetgen`, so
# anything that has not run by then is already too late -- a `pytest_configure`
# hook registered further down does not help, because the import has already
# happened by the time the hook fires. Verified, not assumed: with the guard
# below moved into a pytest_configure hook, `import bionetgen` still resolved
# to the shared main worktree.
#
# The hazard: a scikit-build *editable* install registers a meta_path finder,
# and meta_path finders run BEFORE sys.path. In a git worktree, `import
# bionetgen` then resolves to whichever tree that editable install points at
# -- usually the shared main worktree -- so these tests pass while exercising
# someone else's code. PYTHONPATH does not fix it (it loses to the finder), and
# once sys.modules['bionetgen'] is bound the wrong module persists all session.
#
# Wheel and sdist CI set the mode explicitly. Developer runs infer source mode
# from an editable finder or this checkout's source path. Both modes verify the
# package and extension locations and fail loudly on shadowed or missing code.
# ---------------------------------------------------------------------------
import importlib.metadata
import os
import pathlib
import sys

# The pytest console script may not put the repository root on sys.path.
# Append it only to expose the in-tree CI helper without taking precedence over
# an installed bionetgen package from site-packages.
_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.append(str(_ROOT))

from scripts.ci.python_package_mode import (
    editable_finders_for_package,
    editable_source_roots,
    resolve_test_mode,
    verify_package_locations,
)

_SOURCE_PACKAGE = (_ROOT / "python" / "bionetgen").resolve()
_LOCAL_EXTENSION_DIR = (_ROOT / "build" / "cpp").resolve()
_MODE = os.environ.get("BNG3_PYTHON_TEST_MODE", "auto").lower()
if _MODE not in {"auto", "source", "installed"}:
    raise RuntimeError(
        "BNG3_PYTHON_TEST_MODE must be 'auto', 'source', or 'installed'; "
        f"received {_MODE!r}"
    )

_EDITABLE_FINDERS = editable_finders_for_package(sys.meta_path, "bionetgen")
_SOURCE_PATH_PRESENT = any(
    pathlib.Path(p or ".").resolve() == (_ROOT / "python").resolve() for p in sys.path
)
_LOADED_PACKAGE = sys.modules.get("bionetgen")
_LOADED_FROM_SOURCE = bool(
    _LOADED_PACKAGE
    and getattr(_LOADED_PACKAGE, "__file__", None)
    and pathlib.Path(_LOADED_PACKAGE.__file__).resolve().is_relative_to(_SOURCE_PACKAGE)
)
_RESOLVED_MODE, _EDITABLE_FINDERS = resolve_test_mode(
    _MODE,
    finders=sys.meta_path,
    source_path_present=_SOURCE_PATH_PRESENT,
    loaded_from_source=_LOADED_FROM_SOURCE,
    auto_default="installed",
)
if _RESOLVED_MODE is not None:
    # Spawned API workers reconstruct a fresh interpreter. Carry the mode that
    # this conftest resolved so workers cannot fall back to another checkout.
    os.environ["BNG3_PYTHON_TEST_MODE"] = _RESOLVED_MODE
_USE_SOURCE = _RESOLVED_MODE == "source"

if _USE_SOURCE:
    if not (_SOURCE_PACKAGE / "__init__.py").is_file():
        raise RuntimeError(f"source package is missing: {_SOURCE_PACKAGE}")

    # Remove only this package's editable finder and registered roots. Unrelated
    # editable packages remain available to the test environment.
    if _EDITABLE_FINDERS:
        sys.meta_path = [f for f in sys.meta_path if f not in _EDITABLE_FINDERS]
        _EDITABLE_SOURCES = editable_source_roots(_EDITABLE_FINDERS, "bionetgen")
        sys.path[:] = [
            p
            for p in sys.path
            if not any(
                pathlib.Path(p or ".").resolve() == src for src in _EDITABLE_SOURCES
            )
        ]
    if not _LOCAL_EXTENSION_DIR.is_dir():
        raise RuntimeError(
            f"source mode requires this worktree's native build directory: "
            f"{_LOCAL_EXTENSION_DIR}; build with "
            "`cmake -B build -DBUILD_PYTHON_BINDINGS=ON && "
            "cmake --build build --parallel 2`"
        )
    # model.py supports development builds through the top-level extension
    # import fallback. Put this worktree's binary first before importing the
    # package so its initial model import binds the correct native module.
    sys.path.insert(0, str(_LOCAL_EXTENSION_DIR))
    sys.path.insert(0, str(_ROOT / "python"))

    if _LOADED_PACKAGE and not _LOADED_FROM_SOURCE:
        raise RuntimeError(
            "bionetgen was imported before source mode could select this worktree: "
            f"{getattr(_LOADED_PACKAGE, '__file__', None)}"
        )
    import bionetgen as _pkg

    if str(_LOCAL_EXTENSION_DIR) not in _pkg.__path__:
        _pkg.__path__.insert(0, str(_LOCAL_EXTENSION_DIR))
else:
    try:
        _DIST_PACKAGE = pathlib.Path(
            importlib.metadata.distribution("bionetgen").locate_file("bionetgen")
        ).resolve()
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "installed package mode requires an installed bionetgen distribution"
        ) from exc

    import bionetgen as _pkg

try:
    import bionetgen._bionetgen_cpp as _cpp_probe  # noqa: F401
except ImportError as exc:
    if _USE_SOURCE:
        raise RuntimeError(
            "bionetgen._bionetgen_cpp is unimportable after selecting "
            f"{_pkg.__file__}.\n"
            f"  sys.path: {sys.path[:6]}\n"
            f"  underlying error: {exc}\n"
            "Build the extension in this worktree. Do not relax this check to "
            "make the suite pass."
        ) from exc
    raise RuntimeError(
        "installed bionetgen distribution has no importable native extension: "
        f"{_DIST_PACKAGE}; underlying error: {exc}"
    ) from exc

_EXTENSION_FILE = pathlib.Path(_cpp_probe.__file__).resolve()
if _USE_SOURCE:
    verify_package_locations(
        _pkg.__file__,
        _EXTENSION_FILE,
        package_dir=_SOURCE_PACKAGE,
        extension_dir=_LOCAL_EXTENSION_DIR,
        mode="source",
    )
elif _RESOLVED_MODE == "installed":
    verify_package_locations(
        _pkg.__file__,
        _EXTENSION_FILE,
        package_dir=_DIST_PACKAGE,
        extension_dir=_DIST_PACKAGE,
        mode="installed",
    )

import shutil
import tempfile

import pytest


def _has_perl_bng():
    """Check if BNG2.pl is available via the legacy path."""
    try:
        from bionetgen.compat.legacy_runner import _find_perl_bng

        return _find_perl_bng() is not None
    except Exception:
        return False


requires_perl = pytest.mark.skipif(
    not _has_perl_bng(),
    reason="BNG2.pl (Perl) not available",
)


@pytest.fixture(scope="function")
def tmp(request):
    """
    Create a `tmp` object that generates a unique temporary directory,
    and file for each test function that requires it
    """
    t = tempfile.mkdtemp()
    yield t
    shutil.rmtree(t, ignore_errors=True)
