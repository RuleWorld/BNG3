"""PROBE / harness for confirming which tree a Python suite run exercised.

Not needed to run the suite as of PR #53 (1c78a72), which fixed the conftest
path filter so `PYTHONPATH=python:build/cpp python3 -m pytest tests/python`
resolves both the package and the extension to the worktree under test. Kept
because the check costs two seconds and its absence is invisible.

THE MEASUREMENT CONTEXT MATTERS. Extension reachability is decided by
tests/python/conftest.py, which only loads under pytest, so probing from a
bare `python -c` gives the wrong answer in both directions. Run this under
pytest:

    PYTHONPATH=python:build/cpp python3 -m pytest tests/python/test_bngir_snapshot_emitter.py -q -s

`bionetgen._cpp` is NOT a valid probe -- it is a package attribute that does
not exist and reads None on every run, healthy or not. Use the sys.modules
form, which works on both the direct-import route and the build/cpp fallback
(python/bionetgen/model.py:24-25 re-registers the fallback under the
canonical name).
"""

import sys


def _force_worktree():
    sys.meta_path = [
        finder
        for finder in sys.meta_path
        if "editable" not in type(finder).__module__.lower()
        and "editable" not in getattr(finder, "__name__", "").lower()
    ]
    for path in list(sys.path):
        if "BioNetGen" in path:
            sys.path.remove(path)
    root = "/Users/akutuva/Documents/BioNetGen/BNG3-ir-snapshot"
    sys.path.insert(0, f"{root}/python")
    sys.path.insert(0, f"{root}/build/cpp")


_force_worktree()

import bionetgen  # noqa: E402
import bionetgen._bionetgen_cpp as _cpp  # noqa: E402

print("UNDER TEST pkg :", bionetgen.__file__)
print("UNDER TEST ext :", _cpp.__file__)
assert "BNG3-ir-snapshot" in bionetgen.__file__, "python resolved to the wrong tree"
assert "BNG3-ir-snapshot" in _cpp.__file__, "extension resolved to the wrong tree"
