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

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SOURCE_PACKAGE = (_ROOT / "python" / "bionetgen").resolve()
_LOCAL_EXTENSION_DIR = (_ROOT / "build" / "cpp").resolve()
_MODE = os.environ.get("BNG3_PYTHON_TEST_MODE", "auto").lower()
if _MODE not in {"auto", "source", "installed"}:
    raise RuntimeError(
        "BNG3_PYTHON_TEST_MODE must be 'auto', 'source', or 'installed'; "
        f"received {_MODE!r}"
    )

_EDITABLE_FINDERS = [
    finder
    for finder in sys.meta_path
    if "editable" in type(finder).__module__.lower()
    or "editable" in getattr(finder, "__name__", "").lower()
]
_EDITABLE_SOURCES = set()
for _finder in _EDITABLE_FINDERS:
    _paths = getattr(_finder, "search_paths", None) or ()
    if isinstance(_paths, dict):
        _paths = _paths.values()
    for _path in _paths:
        _editable_path = pathlib.Path(_path).resolve()
        _EDITABLE_SOURCES.add(_editable_path)
        if _editable_path.name == "bionetgen":
            _EDITABLE_SOURCES.add(_editable_path.parent)
if _EDITABLE_FINDERS and not _EDITABLE_SOURCES:
    _EDITABLE_SOURCES = {
        pathlib.Path(p).resolve().parent
        for p in sys.path
        if "BioNetGen" in p and pathlib.Path(p or ".").resolve() != _ROOT
    }
_SOURCE_PATH_PRESENT = any(
    pathlib.Path(p or ".").resolve() == (_ROOT / "python").resolve() for p in sys.path
)
_LOADED_PACKAGE = sys.modules.get("bionetgen")
_LOADED_FROM_SOURCE = bool(
    _LOADED_PACKAGE
    and getattr(_LOADED_PACKAGE, "__file__", None)
    and pathlib.Path(_LOADED_PACKAGE.__file__).resolve().is_relative_to(_SOURCE_PACKAGE)
)
_USE_SOURCE = _MODE == "source" or (
    _MODE == "auto"
    and (_EDITABLE_FINDERS or _SOURCE_PATH_PRESENT or _LOADED_FROM_SOURCE)
)

if _MODE == "installed" and _EDITABLE_FINDERS:
    raise RuntimeError(
        "installed package tests found a scikit-build editable import finder; "
        "install a regular wheel before running this suite"
    )

if _USE_SOURCE:
    if not (_SOURCE_PACKAGE / "__init__.py").is_file():
        raise RuntimeError(f"source package is missing: {_SOURCE_PACKAGE}")

    # Remove only paths registered by the editable finder. Other PYTHONPATH
    # entries and shared build artifacts remain available.
    if _EDITABLE_FINDERS:
        sys.meta_path = [f for f in sys.meta_path if f not in _EDITABLE_FINDERS]
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

    if (
        _LOADED_PACKAGE
        and pathlib.Path(_LOADED_PACKAGE.__file__).resolve().parent != _DIST_PACKAGE
    ):
        raise RuntimeError(
            "bionetgen was imported from outside the installed distribution: "
            f"{getattr(_LOADED_PACKAGE, '__file__', None)} (expected under "
            f"{_DIST_PACKAGE})"
        )
    import bionetgen as _pkg

    _PACKAGE_FILE = pathlib.Path(_pkg.__file__).resolve()
    if _PACKAGE_FILE.parent != _DIST_PACKAGE:
        raise RuntimeError(
            "installed bionetgen package was shadowed: "
            f"{_PACKAGE_FILE} (distribution package is {_DIST_PACKAGE})"
        )

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
    if _EXTENSION_FILE.parent != _LOCAL_EXTENSION_DIR:
        raise RuntimeError(
            "source mode loaded the native extension from another build: "
            f"{_EXTENSION_FILE} (expected under {_LOCAL_EXTENSION_DIR})"
        )
elif _EXTENSION_FILE.parent != _DIST_PACKAGE:
    raise RuntimeError(
        "installed native extension was shadowed: "
        f"{_EXTENSION_FILE} (expected under {_DIST_PACKAGE})"
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
