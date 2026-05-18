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
        from bionetgen.model import BioNetGenModel, load, run
    except ImportError:
        from bionetgen.compat.legacy_runner import load, run
        from bionetgen.compat.legacy_runner import LegacyModel as BioNetGenModel

from bionetgen.result import SimResult
from bionetgen.scan import ScanResult, ScanResult2D, parameter_scan, parameter_scan_2d
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

__all__ = [
    "load",
    "run",
    "BioNetGenModel",
    "SimResult",
    "ScanResult",
    "ScanResult2D",
    "parameter_scan",
    "parameter_scan_2d",
    "from_sbml",
    "sbml_to_bngl",
    "ModelBuilder",
    "BioNetGenError",
    "__version__",
]
