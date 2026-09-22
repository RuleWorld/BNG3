"""Legacy PyBioNetGen model API — LEGACY LAYER, STILL ON THE DEFAULT PATH.

Status verified 2026-09-17.

This package is the pre-BNG3 Python model API. The modern path is the native
backend reached through ``import bionetgen`` plus the pybind11 extension
(``bionetgen.Result``, ``bionetgen.run``), and new code should use that.

IMPORTANT, because it is widely assumed otherwise: this package is **not**
unused, and it cannot simply be deleted. As of this audit it is reachable from
the default import path and from two user-facing tools:

    python/bionetgen/__init__.py:93    from bionetgen.modelapi.model import bngmodel
    python/bionetgen/__init__.py:105   from bionetgen.modelapi.sympy_odes import ...
    python/bionetgen/core/tools/cli.py:44        import bionetgen.modelapi.model as mdl
    python/bionetgen/core/tools/visualize.py:143 bionetgen.modelapi.bngmodel(...)
    python/bionetgen/atomizer/utils/consoleCommands.py

and is exercised by tests/python/{test_bng_parsing,test_sympy_odes,
test_get_rule_mod,test_bngfile_compat,test_bionetgen,test_runner}.py.

The convergence checklist requires that a search prove **zero default-path
references** before any legacy Python module is removed. That precondition is
currently NOT met: ``bionetgen/__init__.py`` imports ``bngmodel`` from here, so
deleting this package would break ``import bionetgen`` outright.

To retire it, in order:
  1. reimplement ``bngmodel`` and ``sympy_odes`` on the native backend, or
     re-point those imports at an equivalent;
  2. migrate ``cli.py`` and ``visualize.py``;
  3. rewrite the six test modules above against the modern API;
  4. re-run the search, confirm zero references, then delete.

Until then this is compatibility surface, not dead code. Treat behavior here as
reference material rather than the preferred implementation (see AGENTS.md,
"Python and C++ boundaries").
"""

try:
    from .model import bngmodel
except ImportError:
    bngmodel = None

__all__ = ["bngmodel", "SympyOdes", "export_sympy_odes", "extract_odes_from_mexfile"]


def __getattr__(name):
    if name in {"SympyOdes", "export_sympy_odes", "extract_odes_from_mexfile"}:
        from .sympy_odes import SympyOdes, export_sympy_odes, extract_odes_from_mexfile

        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
