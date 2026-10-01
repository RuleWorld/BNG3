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
    sys.path[:] = [p for p in sys.path if "BioNetGen" not in p]
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "python"))

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
