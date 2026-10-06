"""Locate and import the engine extension module, without guessing.

Benchmark code that hard-codes a path and falls back silently is how a
"GPU" measurement ends up being a host measurement with a misleading label. This
module resolves the extension once, prints exactly what it resolved to, and
refuses to invent a module that is not there.
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from typing import Any

_MODULE_NAME = "_bionetgen_cpp"


@dataclass(frozen=True)
class ResolvedEngine:
    """Where the engine module came from, for the record in every report."""

    module: Any
    path: str
    source: str  # "explicit", "env", "build/cpp", "python package", ...
    #: Meta-path finders removed because they could redirect imports away from
    #: this checkout. Non-empty means the plain interpreter default was not in
    #: effect, which is worth knowing and is reported in every run.
    neutralised_finders: tuple[str, ...] = ()

    def describe(self) -> str:
        text = f"{self.module.__name__} from {self.path} (via {self.source})"
        if self.neutralised_finders:
            text += (
                f" [neutralised import redirectors: "
                f"{', '.join(self.neutralised_finders)}]"
            )
        return text


_CANDIDATE_RELATIVE = (
    os.path.join("build", "cpp"),
    "build",
    os.path.join("python", "bionetgen"),
)

_cache: ResolvedEngine | None = None


def repo_root(start: str | None = None) -> str:
    """Walk upward looking for the repository marker files."""
    here = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(here, "pyproject.toml")) and os.path.isdir(
            os.path.join(here, "cpp")
        ):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            # Fall back to the package location when run outside a checkout.
            return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        here = parent


#: Substrings identifying meta-path finders installed by editable/scikit-build
#: packaging that resolve project imports to an installed checkout rather than
#: to the tree on disk. Matched case-insensitively against the finder class name.
_REDIRECTOR_TOKENS = ("editable", "redirect", "scifkitbuild", "distutilsmeta")


def editable_finders() -> list[str]:
    """Names of meta-path finders that can redirect imports away from a worktree.

    An editable install puts a finder on `sys.meta_path` that outranks
    `sys.path` and resolves a package name to whichever checkout was installed.
    A benchmark run from a worktree then silently measures a DIFFERENT tree's
    code: no error, entirely plausible numbers. This is the most dangerous
    failure mode in this module precisely because nothing announces it, so the
    finders are detected, named, and reported beside the resolved module path.
    """
    return [
        name
        for name in (type(f).__name__ for f in sys.meta_path)
        if any(t in name.lower() for t in _REDIRECTOR_TOKENS)
    ]


def neutralise_editable_finders() -> list[str]:
    """Remove redirecting finders from `sys.meta_path`; return what was removed.

    Afterwards `sys.path` is authoritative again, which is what a benchmark run
    from a checkout wants. This must happen BEFORE any project import: a module
    already resolved through a redirecting finder sits in `sys.modules` and
    cannot be un-resolved afterwards, so calling this late would be theatre
    rather than a fix.
    """
    removed = editable_finders()
    if removed:
        sys.meta_path[:] = [f for f in sys.meta_path if type(f).__name__ not in removed]
    return removed


def load_engine(explicit: str | None = None, refresh: bool = False) -> ResolvedEngine:
    """Import the engine module, preferring an explicit path.

    Resolution order, all recorded in the returned object so a report can state
    it rather than assume it:
      1. `explicit` — a directory or a direct path to the .so/.pyd;
      2. `BIONETGEN_CPP_DIR` from the environment;
      3. `<repo>/build/cpp` and `<repo>/build`, in the current repo;
      4. the installed `bionetgen` package.

    Redirecting meta-path finders are neutralised before any project import, so
    the module that gets loaded is the one this checkout asks for. Doing this
    after the fact would not help: a module already resolved through a
    redirecting finder is cached and cannot be un-resolved.

    Raises RuntimeError with the paths that were tried when nothing imports.
    """
    global _cache
    if _cache is not None and explicit is None and not refresh:
        return _cache

    neutralised = tuple(neutralise_editable_finders())
    tried: list[str] = []

    def record(module: Any, path: str, source: str) -> ResolvedEngine:
        return ResolvedEngine(module, path, source, neutralised)

    if explicit:
        module = _load_from_path(explicit, tried)
        if module is None:
            raise RuntimeError(
                f"could not import the engine from {explicit!r}. Tried:\n  "
                + "\n  ".join(tried)
            )
        out = record(module, getattr(module, "__file__", str(explicit)), "explicit")
        if neutralised:
            _cache = out
        return out

    env_dir = os.environ.get("BIONETGEN_CPP_DIR")
    if env_dir:
        module = _load_from_path(env_dir, tried)
        if module is None:
            raise RuntimeError(
                f"BIONETGEN_CPP_DIR={env_dir!r} did not yield an importable "
                f"engine module. Tried:\n  " + "\n  ".join(tried)
            )
        out = record(module, getattr(module, "__file__", env_dir), "env")
        _cache = out
        return out

    root = repo_root()
    for rel in _CANDIDATE_RELATIVE:
        candidate = os.path.join(root, rel)
        if os.path.isdir(candidate):
            module = _load_from_path(candidate, tried)
            if module is not None:
                out = record(module, getattr(module, "__file__", candidate), rel)
                _cache = out
                return out

    try:
        module = importlib.import_module("bionetgen._bionetgen_cpp")
    except Exception as exc:  # noqa: BLE001 - report every attempt
        tried.append(f"bionetgen._bionetgen_cpp ({type(exc).__name__}: {exc})")
        raise RuntimeError(
            "could not import the engine extension. Tried:\n  "
            + "\n  ".join(tried)
            + "\nBuild it with: cmake -S . -B build -DCMAKE_BUILD_TYPE=Release "
            "&& cmake --build build -j 2\n"
            "or point BIONETGEN_CPP_DIR at the directory holding the module."
        ) from exc

    out = record(
        module,
        getattr(module, "__file__", "bionetgen._bionetgen_cpp"),
        "python package",
    )
    _cache = out
    return out


def _load_from_path(spec: str, tried: list[str]) -> Any:
    """Import the engine module from a directory or a direct module path."""
    path = os.path.abspath(spec)
    if os.path.isfile(path):
        directory, filename = os.path.split(path)
        stem = os.path.splitext(filename)[0]
        if directory not in sys.path:
            sys.path.insert(0, directory)
        try:
            return importlib.import_module(stem)
        except Exception as exc:  # noqa: BLE001
            tried.append(f"{path} ({type(exc).__name__}: {exc})")
            return None
    if os.path.isdir(path):
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            return importlib.import_module(_MODULE_NAME)
        except Exception as exc:  # noqa: BLE001
            tried.append(f"{path}/{_MODULE_NAME} ({type(exc).__name__}: {exc})")
            return None
    tried.append(f"{path} (does not exist)")
    return None


def backend_inventory(cpp: Any) -> list[dict[str, Any]]:
    """The engine's own view of which GPU backends exist and work."""
    return [dict(entry) for entry in cpp.gpu_backends()]


def usable_backend(
    cpp: Any, requested: str = "auto"
) -> tuple[str, list[dict[str, Any]]]:
    """Resolve which backend a run would actually use, and report the inventory.

    Returns the backend name the engine would select plus the full inventory, so
    a report can print both what it used and what it could have used.
    """
    inventory = backend_inventory(cpp)
    if requested != "auto":
        for entry in inventory:
            if entry["name"] == requested:
                if not entry["available"]:
                    raise RuntimeError(
                        f"requested GPU backend {requested!r} is not usable: "
                        f"{entry['detail']!r}"
                    )
                return requested, inventory
        raise RuntimeError(
            f"requested GPU backend {requested!r} is not compiled into this "
            f"binary; known backends: {[e['name'] for e in inventory]}"
        )
    name = str(cpp.default_gpu_backend())
    if name == "none":
        details = "; ".join(f"{e['name']}: {e['detail']}" for e in inventory)
        raise RuntimeError(f"no GPU backend is usable on this host ({details})")
    return name, inventory
