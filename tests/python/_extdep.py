"""Hard dependency on the compiled extension, resolved loudly.

`_bionetgen_cpp` is not an optional oracle like roadrunner or libsbml. In the
files that call `require_extension`, the extension's own output IS the subject
under test -- a snapshot document, a parse result, an SSA sample, an engine
refusal. `pytest.importorskip` there turned a hard dependency into a soft one:
with the extension unimportable the whole module was skipped and pytest still
exited 0, so a run that exercised nothing reported success. That has already
happened in this tree -- `test_ssa_closed_form_parity.py` records in its own
docstring that a draft of it was silently skipped this way.

Mirrors the in-tree precedent at
`python/bionetgen/modelapi/sympy_odes.py:51-53`, which raises rather than skips.
This module exists so the message is written once and stays actionable.
"""

_BUILD_HINT = (
    "Build the extension in this worktree:\n"
    "  cmake -B build -DBUILD_PYTHON_BINDINGS=ON && cmake --build build\n"
    "or add an existing build directory to PYTHONPATH. This is an environment\n"
    "problem, not a code failure -- do not relax the check to make the suite pass."
)


def require_extension():
    """Return `bionetgen._bionetgen_cpp`, or raise ImportError explaining why."""
    try:
        import bionetgen._bionetgen_cpp as extension
    except ImportError as exc:
        raise ImportError(
            "bionetgen._bionetgen_cpp is unimportable, but this file tests the "
            "extension's own output and cannot mean anything without it. "
            "Skipping would report a green run that exercised nothing.\n"
            f"{_BUILD_HINT}"
        ) from exc
    return extension
