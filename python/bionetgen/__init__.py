"""BioNetGen: Rule-based modeling of biochemical systems.

This package provides a unified Python interface to the BioNetGen modeling
platform, backed by a compiled C++ engine for parsing, network generation,
and simulation.

Public names are resolved on first access rather than at import time, so
``import bionetgen`` does not pay for NumPy or for the optional SBML and
parameter-scan machinery that a given program never touches.
"""

import importlib as _importlib
import os as _os

_USE_LEGACY = _os.environ.get("BIONETGEN_USE_PERL", "").lower() in ("1", "true", "yes")

__version__ = "3.0.0a1"

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
    "to_bngir",
    "from_bngir",
    "semantic_equal",
    "__version__",
]

# Submodule -> attribute, for names that are always importable.  An
# ImportError out of any of these propagates, as it did when these imports
# were eager.
_LAZY_NAMES = {
    "BNGDefaults": "bionetgen.core.defaults",
    "BNGError": "bionetgen.core.exc",
    "ScanResult": "bionetgen.scan",
    "ScanResult2D": "bionetgen.scan",
    "SensitivityResult": "bionetgen.sensitivity",
    "SimResult": "bionetgen.result",
    "from_bngir": "bionetgen.bngir",
    "parameter_scan": "bionetgen.scan",
    "parameter_scan_2d": "bionetgen.scan",
    "sensitivity_analysis": "bionetgen.sensitivity",
    "semantic_equal": "bionetgen.bngir",
    "to_bngir": "bionetgen.bngir",
}

# The same, for names whose module is optional: a missing module leaves the
# name undefined rather than breaking ``import bionetgen``.
_OPTIONAL_NAMES = {
    "BioNetGenError": "bionetgen.sbml",
    "ModelBuilder": "bionetgen.builder",
    "from_sbml": "bionetgen.sbml",
    "sbml_to_bngl": "bionetgen.sbml",
}

# Submodules that ``import bionetgen`` used to pull in as a side effect.
_LAZY_SUBMODULES = frozenset(
    {
        "_bionetgen_cpp",
        "bngir",
        "builder",
        "core",
        "model",
        "result",
        "sbml",
        "scan",
        "sensitivity",
    }
)

if _USE_LEGACY:
    from bionetgen.compat.legacy_runner import load, run
    from bionetgen.compat.legacy_runner import LegacyModel as BioNetGenModel
else:
    _MODERN_METHODS = frozenset({"ode", "ssa", "nf", "pla", "psa"})
    _RUN_OUT_MISSING = object()
    _engine = None

    def _backend():
        """Return ``(load, run, BioNetGenModel)`` for the engine backing the package.

        The compiled model module is that engine; the legacy Perl runner stands
        in for it when the compiled one cannot be imported.
        """
        global _engine
        if _engine is None:
            try:
                from bionetgen.model import BioNetGenModel, load, run as _engine_run
            except ImportError:
                from bionetgen.compat.legacy_runner import (
                    LegacyModel as BioNetGenModel,
                    load,
                    run as _engine_run,
                )
            _engine = (load, _engine_run, BioNetGenModel)
        return _engine

    def run(path, method="ode", t_end=100.0, n_steps=100, **kwargs):
        """Run a model through the modern or PyBioNetGen-compatible API.

        The modern form is ``run(path, method="ode", ...)`` and returns a
        :class:`SimResult`.  A path-like second positional argument, or the
        legacy ``out=`` keyword, selects the PyBioNetGen file-runner contract
        and returns a :class:`BNGResult`.
        """
        engine_run = _backend()[1]
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

        return engine_run(path, method=method, t_end=t_end, n_steps=n_steps, **kwargs)

    # Resolved eagerly because a development build keeps the compiled
    # extension outside the package, and importing bionetgen.model is what
    # registers it under the name ``bionetgen._bionetgen_cpp``.
    _engine = _backend()


def __getattr__(name):
    """Resolve public names on first access so ``import bionetgen`` stays cheap."""
    if name == "bngmodel":
        from bionetgen.modelapi.model import bngmodel

        value = bngmodel
    elif name == "sim_getter":
        from bionetgen.simulator.simulators import sim_getter

        value = sim_getter
    elif name == "BNGResult":
        from bionetgen.core.tools.result import BNGResult

        value = BNGResult
    elif name in ("SympyOdes", "export_sympy_odes", "extract_odes_from_mexfile"):
        from bionetgen.modelapi.sympy_odes import (
            SympyOdes,
            export_sympy_odes,
            extract_odes_from_mexfile,
        )

        value = locals()[name]
    elif name == "defaults":
        from bionetgen.core.defaults import BNGDefaults

        value = BNGDefaults()
    elif not _USE_LEGACY and name == "load":
        value = _backend()[0]
    elif not _USE_LEGACY and name == "BioNetGenModel":
        value = _backend()[2]
    elif name in _LAZY_NAMES:
        value = getattr(_importlib.import_module(_LAZY_NAMES[name]), name)
    elif name in _OPTIONAL_NAMES:
        try:
            value = getattr(_importlib.import_module(_OPTIONAL_NAMES[name]), name)
        except ImportError:
            if name != "BioNetGenError":
                value = None
            else:
                return __getattr__("BNGError")
    elif name in _LAZY_SUBMODULES:
        try:
            value = _importlib.import_module(f"{__name__}.{name}")
        except ImportError:
            value = None
    else:
        value = None

    if value is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__():
    return sorted(
        set(globals())
        | set(__all__)
        | set(_LAZY_NAMES)
        | set(_OPTIONAL_NAMES)
        | {"defaults"}
        | _LAZY_SUBMODULES
    )
