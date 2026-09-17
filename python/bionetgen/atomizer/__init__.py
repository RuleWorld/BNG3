"""Legacy SBML atomizer package — libSBML-dependent parts are optional.

Importing :mod:`bionetgen.atomizer` must not fail when ``python-libsbml``
is missing or has an incompatible binary (e.g. ``x86_64`` wheel on ``arm64``
Python 3.9 on macOS).  Pure-Python helpers under
``bionetgen.atomizer.*`` (annotation utils, writer helpers, modern
string-based atomizer) should remain importable.  The legacy
``AtomizeTool`` / ``libsbml2bngl`` path is exposed lazily via
PEP 562 ``__getattr__`` so collection of tests that do not need SBML
still succeeds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - for type checkers only
    from .atomizeTool import AtomizeTool

__all__ = ["AtomizeTool"]


def __getattr__(name: str) -> Any:
    if name == "AtomizeTool":
        try:
            from .atomizeTool import AtomizeTool as _AtomizeTool
        except ImportError as exc:  # pragma: no cover - optional dep missing
            raise ImportError(
                "bionetgen.atomizer.AtomizeTool requires 'python-libsbml' "
                "which is not available or not loadable in this environment: "
                f"{exc}. Install the 'full' extra or a working libsbml build "
                "for your Python/architecture."
            ) from exc
        globals()[name] = _AtomizeTool
        return _AtomizeTool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:  # pragma: no cover - trivial
    return sorted(__all__)
