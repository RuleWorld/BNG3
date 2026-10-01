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
# This only fires when an editable finder is actually present. CI installs a
# real wheel and has none; prepending this checkout's `python/` there would
# shadow the installed wheel, which is the same class of quiet
# mismeasurement this guard exists to prevent.
# ---------------------------------------------------------------------------
import pathlib
import sys

_EDITABLE_FINDERS = [
    finder
    for finder in sys.meta_path
    if "editable" in type(finder).__module__.lower()
    or "editable" in getattr(finder, "__name__", "").lower()
]
if _EDITABLE_FINDERS:
    sys.meta_path = [f for f in sys.meta_path if f not in _EDITABLE_FINDERS]
    # Remove the editable install's own source path -- the thing this guard
    # guards -- and nothing else. A substring filter on "BioNetGen" also
    # strips this repository's build-artifact directory, leaving the
    # extension unimportable in any worktree without its own build (46
    # AttributeError failures, and every importorskip-guarded file
    # silently skipping instead of failing). Dropping "everything not
    # under the worktree root" is equally wrong: a legitimate PYTHONPATH
    # pointing at a shared artifact directory is not under this worktree
    # and must survive. Both were measured; see sciSignaling and
    # sciStochastic.
    _ROOT = pathlib.Path(__file__).resolve().parents[2]
    _EDITABLE_SOURCES = {
        pathlib.Path(p).resolve()
        for finder in _EDITABLE_FINDERS
        for p in getattr(finder, "search_paths", None) or ()
    }
    if not _EDITABLE_SOURCES:
        _EDITABLE_SOURCES = {
            pathlib.Path(p).resolve().parent
            for p in sys.path
            if "BioNetGen" in p and pathlib.Path(p or ".").resolve() != _ROOT
        }
    sys.path[:] = [
        p
        for p in sys.path
        if not any(pathlib.Path(p or ".").resolve() == src for src in _EDITABLE_SOURCES)
    ]
    # This worktree's own build artifacts take precedence over any shared
    # copy, but never displace a shared one that is all the caller has.
    _LOCAL_BUILD = _ROOT / "build" / "cpp"
    if _LOCAL_BUILD.is_dir():
        sys.path.insert(0, str(_LOCAL_BUILD))
    sys.path.insert(0, str(_ROOT / "python"))

    # A missing build must be loud. Without this, `importorskip` turns a
    # misconfigured environment into a suite that reports skips and exit 0,
    # which is the same quiet-pass failure this guard exists to prevent --
    # a guard that silences its own tests is passing quietly.
    try:
        import bionetgen._bionetgen_cpp as _cpp_probe  # noqa: F401
    except ImportError as _exc:
        raise RuntimeError(
            "bionetgen._bionetgen_cpp is unimportable after resolving bionetgen "
            f"to the tree under test ({_ROOT}).\n"
            f"  bionetgen resolved from: {getattr(bionetgen, '__file__', '?')}\n"
            f"  sys.path: {sys.path[:6]}\n"
            f"  underlying error: {_exc}\n"
            "This is a build/misconfiguration problem, not a code failure. Build "
            "the extension in this worktree "
            "(`cmake -B build -DBUILD_PYTHON_BINDINGS=ON && cmake --build build`) "
            "or add its directory to PYTHONPATH. Do not relax this check to make "
            "the suite pass."
        ) from _exc

import os
import tempfile
import shutil

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
