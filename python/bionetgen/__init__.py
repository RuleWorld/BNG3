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

    class _OmittedRunArgument:
        def __repr__(self):
            return "<omitted>"

    _RUN_ARGUMENT_MISSING = _OmittedRunArgument()

    def run(
        path,
        *args,
        method=_RUN_ARGUMENT_MISSING,
        t_end=_RUN_ARGUMENT_MISSING,
        n_steps=_RUN_ARGUMENT_MISSING,
        **kwargs,
    ):
        """Run a model through the modern or PyBioNetGen-compatible API.

        Modern calls return a :class:`SimResult`; the second positional
        argument may be a supported simulation method, followed by positional
        ``t_end`` and ``n_steps`` values. A non-method path-like second
        positional argument, or the legacy ``out=`` keyword, selects the
        PyBioNetGen file-runner contract and returns a :class:`BNGResult`.
        Use ``out=`` when an output directory's name matches a method.
        """
        legacy_out = kwargs.pop("out", _RUN_OUT_MISSING)
        legacy_requested = legacy_out is not _RUN_OUT_MISSING
        method_was_provided = method is not _RUN_ARGUMENT_MISSING
        end_was_provided = t_end is not _RUN_ARGUMENT_MISSING
        steps_were_provided = n_steps is not _RUN_ARGUMENT_MISSING

        if args:
            second = args[0]
            if isinstance(second, str) and second.lower() in _MODERN_METHODS:
                if method_was_provided:
                    raise TypeError("run() got multiple values for argument 'method'")
                method = second
                method_was_provided = True
                remaining = args[1:]
            elif isinstance(second, (str, _os.PathLike)):
                if legacy_requested:
                    raise TypeError("run() got multiple values for argument 'out'")
                legacy_out = second
                legacy_requested = True
                remaining = args[1:]
            else:
                raise TypeError(
                    "the second positional argument must be a simulation method "
                    "or output path"
                )

            if len(remaining) > 2:
                raise TypeError("run() accepts at most four positional arguments")
            if remaining:
                if end_was_provided:
                    raise TypeError("run() got multiple values for argument 't_end'")
                t_end = remaining[0]
                end_was_provided = True
            if len(remaining) > 1:
                if steps_were_provided:
                    raise TypeError("run() got multiple values for argument 'n_steps'")
                n_steps = remaining[1]
                steps_were_provided = True

        if method is _RUN_ARGUMENT_MISSING or method is None:
            method_name = "ode"
            method_override = None
        elif isinstance(method, str) and method.lower() in _MODERN_METHODS:
            method_name = method.lower()
            method_override = method_name
        else:
            raise ValueError(
                f"unsupported simulation method {method!r}; use "
                "ode, ssa, nf, pla, or psa"
            )

        if t_end is _RUN_ARGUMENT_MISSING:
            t_end = 100.0
        if n_steps is _RUN_ARGUMENT_MISSING:
            n_steps = 100

        if legacy_requested:
            from bionetgen.compat.runner import run as _compat_run

            options = dict(kwargs)
            options["method"] = method_override
            if end_was_provided:
                options["t_end"] = t_end
            if steps_were_provided:
                options["n_steps"] = n_steps
            return _compat_run(
                path,
                out=None if legacy_out is _RUN_OUT_MISSING else legacy_out,
                **options,
            )

        return _modern_run(
            path, method=method_name, t_end=t_end, n_steps=n_steps, **kwargs
        )


from bionetgen.result import SimResult
from bionetgen.bngir import from_bngir, semantic_equal, to_bngir
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

__version__ = "3.0.0a1"


def __getattr__(name):
    """Load legacy public names lazily to keep optional imports optional."""
    if name == "defaults":
        # Defer legacy defaults setup until first access. The defaults module
        # supports the optional Cement dependency; other import failures must
        # remain visible instead of turning this public export into None.
        from bionetgen.core.defaults import defaults as _defaults

        globals()["defaults"] = _defaults
        return _defaults
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
    "to_bngir",
    "from_bngir",
    "semantic_equal",
    "__version__",
]
