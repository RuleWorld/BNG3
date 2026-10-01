"""Force this worktree's python/ and build/ to win over the editable install.

`bionetgen` is installed here as a scikit-build EDITABLE install pointing at the
shared main worktree. Editable installs install a `__editable__` meta_path
finder, and meta_path finders run BEFORE sys.path, so PYTHONPATH does not fix
it. Without this guard a pytest run in any worktree silently imports MAIN's
`bionetgen` and tests that instead.

This is the per-run form of the guard contractTighten added to
tests/python/conftest.py. It lives here rather than in the repo because that
guard strips the build-artifact directory too, which makes a missing build
invisible rather than loud.
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