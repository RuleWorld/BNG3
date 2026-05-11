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

__version__ = "3.0.0a1"

__all__ = [
    "load",
    "run",
    "BioNetGenModel",
    "SimResult",
    "__version__",
]
