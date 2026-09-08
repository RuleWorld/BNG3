"""BioNetGen: Rule-based modeling of biochemical systems.

This package provides a unified Python interface to the BioNetGen modeling
platform, backed by a compiled C++ engine for parsing, network generation,
and simulation.
"""

import os as _os

_USE_LEGACY = _os.environ.get("BIONETGEN_USE_PERL", "").lower() in ("1", "true", "yes")

if _USE_LEGACY:
    from bionetgen.compat.legacy_runner import load, run
    from bionetgen.compat.legacy_runner import LegacyModel as BioNetGenModel
else:
    try:
        from bionetgen.model import BioNetGenModel, load, run as _modern_run
    except ImportError:
        from bionetgen.compat.legacy_runner import load, run
        from bionetgen.compat.legacy_runner import LegacyModel as BioNetGenModel

    _MODERN_METHODS = frozenset({"ode", "ssa", "nf", "pla", "psa"})
    _RUN_OUT_MISSING = object()

    def run(path, method="ode", t_end=100.0, n_steps=100, **kwargs):
        """Run a model through the modern or PyBioNetGen-compatible API.

        The modern form is ``run(path, method="ode", ...)`` and returns a
        :class:`SimResult`.  A path-like second positional argument, or the
        legacy ``out=`` keyword, selects the PyBioNetGen file-runner contract
        and returns a :class:`BNGResult`.
        """
        legacy_out = kwargs.pop("out", _RUN_OUT_MISSING)
        legacy_requested = legacy_out is not _RUN_OUT_MISSING

        if isinstance(method, str):
            method_name = method.lower()
        else:
            method_name = None

        if method_name not in _MODERN_METHODS:
            legacy_requested = True
            if legacy_out is _RUN_OUT_MISSING:
                legacy_out = method
            method = None

        if legacy_requested:
            from bionetgen.compat.runner import run as _compat_run

            return _compat_run(
                path,
                out=None if legacy_out is _RUN_OUT_MISSING else legacy_out,
                method=None if method == "ode" else method,
                t_end=t_end,
                n_steps=n_steps,
                **kwargs,
            )

        return _modern_run(path, method=method, t_end=t_end, n_steps=n_steps, **kwargs)


from bionetgen.result import SimResult
from bionetgen.scan import ScanResult, ScanResult2D, parameter_scan, parameter_scan_2d
from bionetgen.sensitivity import SensitivityResult, sensitivity_analysis
from bionetgen.core.exc import BNGError

try:
    from bionetgen.sbml import BioNetGenError, from_sbml, sbml_to_bngl
except ImportError:
    BioNetGenError = BNGError
    from_sbml = None
    sbml_to_bngl = None

try:
    from bionetgen.builder import ModelBuilder
except ImportError:
    ModelBuilder = None

try:
    from bionetgen.core.defaults import BNGDefaults

    defaults = BNGDefaults()
except Exception:
    defaults = None

__version__ = "3.0.0a1"


def __getattr__(name):
    """Load legacy public names lazily to keep optional imports optional."""
    if name == "bngmodel":
        from bionetgen.modelapi.model import bngmodel

        return bngmodel
    if name == "sim_getter":
        from bionetgen.simulator.simulators import sim_getter

        return sim_getter
    if name == "BNGResult":
        from bionetgen.core.tools.result import BNGResult

        return BNGResult
    if name in {"SympyOdes", "export_sympy_odes", "extract_odes_from_mexfile"}:
        from bionetgen.modelapi.sympy_odes import (
            SympyOdes,
            export_sympy_odes,
            extract_odes_from_mexfile,
        )

        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "load",
    "run",
    "bngmodel",
    "sim_getter",
    "BNGResult",
    "SympyOdes",
    "export_sympy_odes",
    "extract_odes_from_mexfile",
    "BioNetGenModel",
    "SimResult",
    "ScanResult",
    "ScanResult2D",
    "parameter_scan",
    "parameter_scan_2d",
    "SensitivityResult",
    "sensitivity_analysis",
    "from_sbml",
    "sbml_to_bngl",
    "ModelBuilder",
    "BioNetGenError",
    "__version__",
]
