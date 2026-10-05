#!/usr/bin/env python3
"""Run a pytest target with the editable-install shadowing removed.

`bionetgen` is installed on this host as a scikit-build EDITABLE install, which
installs a meta_path finder. Meta-path finders run BEFORE sys.path, so a plain
`pytest` in any worktree silently imports `bionetgen` from the shared main
tree instead of the worktree under test. PYTHONPATH does not fix it.

This wrapper drops the editable finders, puts the worktree's own python/ and
build/cpp first, prints the paths that actually resolved, and only then hands
off to pytest. The printed lines are the evidence.
"""

import os
import subprocess
import sys


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    pkg_dir = os.path.join(root, "python")
    ext_dir = os.path.join(root, "build", "cpp")

    code = f"""
import sys
sys.meta_path = [f for f in sys.meta_path
                 if 'editable' not in type(f).__module__.lower()
                 and 'editable' not in getattr(f, '__name__', '').lower()]
sys.path[:] = [p for p in sys.path if 'BioNetGen' not in p or p in ({pkg_dir!r}, {ext_dir!r})]
sys.path.insert(0, {pkg_dir!r})
sys.path.insert(0, {ext_dir!r})
import bionetgen
import _bionetgen_cpp  # the route tests/test_batch_ssa_statistical_parity.py uses
mod = sys.modules.get('bionetgen._bionetgen_cpp')
print('UNDER TEST pkg:', bionetgen.__file__)
print('UNDER TEST ext (submodule):', mod and mod.__file__)
print('UNDER TEST ext (top-level):', _bionetgen_cpp.__file__)
assert mod is not None, 'bionetgen._bionetgen_cpp did not import'
import pytest
sys.exit(pytest.main(sys.argv[1:]))
"""
    return subprocess.call([sys.executable, "-c", code] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
