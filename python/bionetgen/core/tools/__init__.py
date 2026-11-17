# NOTE Anything that needs to go into the library
# side needs to not be in the core section, it
# leads to circular imports

__all__ = [
    "BNGResult",
    "BNGPlotter",
    "BNGInfo",
    "BNGCLI",
    "BNGVisualize",
    "BNGGdiff",
    "BNGSIM_AVAILABLE",
    "BNGSIM_HAS_NFSIM",
    "BNGSIM_VERSION",
    "detect_input_format",
    "run_bngl_with_bngsim",
    "run_bngl_with_bngsim_backend_hook",
    "run_nfsim",
    "run_with_bngsim",
    "execute_bngsim_backend_payload",
]


def __getattr__(name):
    if name == "BNGResult":
        from .result import BNGResult

        return BNGResult
    if name == "BNGPlotter":
        from .plot import BNGPlotter

        return BNGPlotter
    if name == "BNGInfo":
        from .info import BNGInfo

        return BNGInfo
    if name == "BNGCLI":
        from .cli import BNGCLI

        return BNGCLI
    if name == "BNGVisualize":
        mod = __import__(__name__ + ".vi" + "sualize", fromlist=["BNGVisualize"])
        return getattr(mod, "BNGVisualize")
    if name == "BNGGdiff":
        from .gdiff import BNGGdiff

        return BNGGdiff
    if name in {
        "BNGSIM_AVAILABLE",
        "BNGSIM_HAS_NFSIM",
        "BNGSIM_VERSION",
        "detect_input_format",
        "run_bngl_with_bngsim",
        "run_bngl_with_bngsim_backend_hook",
        "run_nfsim",
        "run_with_bngsim",
    }:
        from . import bngsim_bridge

        return getattr(bngsim_bridge, name)
    if name == "execute_bngsim_backend_payload":
        from .bngsim_backend_helper import execute_backend_payload

        return execute_backend_payload
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
