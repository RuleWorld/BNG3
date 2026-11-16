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
        from .visualize import BNGVisualize

        return BNGVisualize
    if name == "BNGGdiff":
        from .gdiff import BNGGdiff

        return BNGGdiff
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
