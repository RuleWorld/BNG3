"""Opt-in LANL BNGsim backend introspection and optional Python package bridge.

Native BNG3 solvers remain the strict default (ADR 0003). BNGsim is strictly
opt-in via ``backend="bngsim"`` (or ``BIONETGEN_FINITE_BACKEND=bngsim``).

Execution order when ``backend="bngsim"`` is requested:
1. Compiled C++ adapter (``BUILD_BNGSIM_ADAPTER=ON``), in-memory with zero
   ``.net`` serialization.
2. Optional installed LANL Python ``bngsim`` package (``pip install bngsim``),
   validated by the exact same fail-closed semantic lowering check
   (``_cpp.check_bngsim_lowering``) and runtime option guards before
   constructing a temporary ``.net`` handoff.
3. Otherwise fail closed with an explicit ``RuntimeError`` — never silently
   fall back to native solvers.
"""

from __future__ import annotations

import importlib
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional

import numpy as np

_FINITE_AUTO_ALIASES = frozenset({"", "auto", "automatic"})
_FINITE_NATIVE_ALIASES = frozenset({"native", "bng3", "default"})
_FINITE_BNGSIM_ALIASES = frozenset({"bngsim", "bng_sim", "bng-sim"})
_NF_ALLOWED_ALIASES = frozenset(
    {
        "",
        "auto",
        "automatic",
        "native",
        "bng3",
        "default",
        "nf",
        "nfsim",
        "nfcore",
        "nfnext",
    }
)


def normalize_finite_backend(backend: Optional[str]) -> str:
    """Normalize a finite-network backend selector to 'auto', 'native', or 'bngsim'."""
    effective = backend
    if effective is None:
        effective = os.environ.get("BIONETGEN_FINITE_BACKEND", "auto")
    if not isinstance(effective, str):
        raise TypeError("backend must be a string")
    key = effective.strip().lower()
    if key in _FINITE_AUTO_ALIASES:
        return "auto"
    if key in _FINITE_NATIVE_ALIASES:
        return "native"
    if key in _FINITE_BNGSIM_ALIASES:
        return "bngsim"
    raise ValueError(
        f"Unknown backend: {effective!r}. Use 'auto', 'native', or 'bngsim'."
    )


def validate_nf_backend(backend: Optional[str], method: str) -> None:
    """Reject incompatible or unknown backend selectors for network-free methods."""
    if backend is None:
        return
    if not isinstance(backend, str):
        raise TypeError("backend must be a string")
    key = backend.strip().lower()
    if key in _FINITE_BNGSIM_ALIASES:
        raise ValueError(f"backend='bngsim' is not valid for method={method!r}")
    if key not in _NF_ALLOWED_ALIASES:
        raise ValueError(
            f"Unknown backend: {backend!r} for method={method!r}. "
            "Use 'auto' or 'native'."
        )


def _import_python_bngsim() -> Optional[Any]:
    """Return the optional installed LANL ``bngsim`` module if usable, else None."""
    try:
        mod = importlib.import_module("bngsim")
    except ImportError:
        return None
    model_cls = getattr(mod, "Model", None)
    sim_cls = getattr(mod, "Simulator", None)
    if model_cls is None or not hasattr(model_cls, "from_net") or sim_cls is None:
        return None
    return mod


def _cpp_module():
    from bionetgen.model import _cpp

    return _cpp


def bngsim_capabilities() -> dict[str, Any]:
    """Return structured capability metadata for the optional BNGsim backend."""
    cpp = _cpp_module()
    cpp_caps = (
        dict(cpp.bngsim_capabilities())
        if cpp is not None and hasattr(cpp, "bngsim_capabilities")
        else {
            "available": False,
            "version": "unavailable",
            "supports_ode": False,
            "supports_ssa": False,
            "supports_psa": False,
            "supports_pla": False,
        }
    )
    cpp_available = bool(cpp_caps.get("available", False))
    py_mod = _import_python_bngsim()
    py_available = py_mod is not None
    py_version = (
        str(getattr(py_mod, "__version__", "unknown")) if py_available else None
    )

    if cpp_available:
        return {
            "available": True,
            "provider": "cpp",
            "cpp_adapter": True,
            "python_package": py_available,
            "version": str(cpp_caps.get("version", "unknown")),
            "python_version": py_version,
            "supports_ode": bool(cpp_caps.get("supports_ode", False)),
            "supports_ssa": bool(cpp_caps.get("supports_ssa", False)),
            "supports_psa": bool(cpp_caps.get("supports_psa", False)),
            "supports_pla": bool(cpp_caps.get("supports_pla", False)),
        }
    if py_available:
        return {
            "available": True,
            "provider": "python",
            "cpp_adapter": False,
            "python_package": True,
            "version": py_version or "unknown",
            "python_version": py_version,
            "supports_ode": True,
            "supports_ssa": True,
            "supports_psa": True,
            "supports_pla": False,
        }
    return {
        "available": False,
        "provider": None,
        "cpp_adapter": False,
        "python_package": False,
        "version": "unavailable",
        "python_version": None,
        "supports_ode": False,
        "supports_ssa": False,
        "supports_psa": False,
        "supports_pla": False,
    }


def bngsim_available() -> bool:
    """Return True if BNGsim is available via C++ adapter or optional Python package."""
    return bool(bngsim_capabilities()["available"])


def bngsim_version() -> str:
    """Return the active BNGsim revision/version or 'unavailable'."""
    return str(bngsim_capabilities()["version"])


def _validate_runtime_options(
    *,
    method: str,
    n_species: int,
    stop_if: str,
    sparse: bool,
    check_product_scale: float,
    steady_state: bool,
    steady_state_tol: float,
    sample_times: list[float],
    max_sim_steps: int,
    output_step_interval: int,
    batch_size: int,
    psa_poplevel: float = 100.0,
) -> None:
    """Mirror cpp/engine/BngsimBackend.cpp fail-closed runtime option checks."""
    if method == "ode":
        if stop_if:
            raise RuntimeError(
                "BNGsim adapter rejected stop_if: native stop expressions are not supported"
            )
        if sparse:
            raise RuntimeError(
                "BNGsim adapter rejected sparse: BNG3 GMRES selection is not equivalent to BNGsim KLU selection"
            )
        if check_product_scale > 0.0:
            raise RuntimeError(
                "BNGsim adapter rejected check_product_scale: native threshold warnings are not emitted by BNGsim"
            )
        if steady_state:
            if n_species == 0:
                raise RuntimeError(
                    "BNGsim adapter rejected steady_state: empty-state steady-state truncation differs; "
                    "native stops at the first non-initial output point while BNGsim returns the full algebraic-only grid"
                )
            if not math.isfinite(float(steady_state_tol)) or steady_state_tol <= 0.0:
                raise RuntimeError(
                    "BNGsim adapter rejected steady_state_tol: a finite positive tolerance is required to match native semantics"
                )
    elif method in ("ssa", "psa"):
        if method == "psa":
            if not math.isfinite(float(psa_poplevel)) or float(psa_poplevel) <= 1.0:
                raise RuntimeError(
                    "BNGsim adapter rejected poplevel: BNGsim PSA requires finite poplevel > 1 "
                    "(use method='ssa' for exact unscaled SSA)"
                )
        if batch_size > 0:
            raise RuntimeError(
                "BNGsim backend does not support batch_size; use backend='native' or 'auto'"
            )
        if stop_if:
            raise RuntimeError(
                "BNGsim adapter rejected stop_if: native event stop expressions are not supported"
            )
        if max_sim_steps > 0:
            label = "PSA" if method == "psa" else "SSA"
            raise RuntimeError(
                f"BNGsim adapter rejected max_sim_steps: BNGsim {label} has no reaction-event cap"
            )
        if output_step_interval > 0 and not sample_times:
            raise RuntimeError(
                "BNGsim adapter rejected output_step_interval: event-indexed output is not represented by TimeSpec"
            )
    else:
        raise RuntimeError(
            f"BNGsim backend does not yet support method='{method}'; native fallback required"
        )


def _convert_python_bngsim_result(
    bngsim_result: Any,
    *,
    expected_observable_names: list[str],
    expected_sample_times: list[float],
) -> dict[str, Any]:
    """Convert a LANL Python ``bngsim.Result`` into BNG3's SimResult raw dict."""
    time_arr = np.asarray(bngsim_result.time, dtype=float)
    if expected_sample_times and len(time_arr) != len(expected_sample_times):
        raise RuntimeError(
            "BNGsim adapter rejected sample_times: BNGsim result length did not match requested sample_times"
        )

    conc_arr = np.asarray(bngsim_result.species, dtype=float)
    if conc_arr.ndim == 1:
        conc_arr = conc_arr.reshape(len(time_arr), -1)

    observables: dict[str, np.ndarray] = {}
    raw_obs = getattr(bngsim_result, "observables", None)
    obs_names = list(
        getattr(bngsim_result, "observable_names", expected_observable_names)
    )
    if raw_obs is not None and obs_names:
        obs_arr = np.asarray(raw_obs, dtype=float)
        if obs_arr.ndim == 1:
            obs_arr = obs_arr.reshape(len(time_arr), -1)
        if obs_arr.shape[1] != len(obs_names):
            raise RuntimeError(
                "BNGsim result conversion failed: observable column count mismatch"
            )
        for idx, name in enumerate(obs_names):
            observables[str(name)] = np.array(obs_arr[:, idx], dtype=float, copy=True)

    return {
        "time": time_arr,
        "concentrations": conc_arr,
        "observables": observables,
        "backend": "bngsim",
        "construction_path": "python-bngsim",
    }


def simulate_via_python_bngsim(
    cpp_model: Any,
    cpp_network: Any,
    *,
    method: str,
    t_start: float,
    t_end: float,
    n_steps: int,
    rtol: float,
    atol: float,
    seed: int,
    max_step: float,
    steady_state: bool,
    steady_state_tol: float,
    stop_if: str,
    sample_times: list[float],
    max_sim_steps: int,
    output_step_interval: int,
    sparse: bool,
    check_product_scale: float,
    batch_size: int,
    psa_poplevel: float = 100.0,
) -> dict[str, Any]:
    """Run ODE, SSA, or PSA via an installed LANL Python ``bngsim`` package.

    Caller must have already passed ``_cpp.check_bngsim_lowering``. Fails
    closed on any unsupported option or solver failure; never falls back.
    """
    bngsim_mod = _import_python_bngsim()
    if bngsim_mod is None:
        raise RuntimeError(
            "BNGsim backend unavailable: build without BUILD_BNGSIM_ADAPTER "
            "and optional Python 'bngsim' package is not installed"
        )

    cpp = _cpp_module()
    if cpp is None or not hasattr(cpp, "io") or not hasattr(cpp.io, "write_net"):
        raise RuntimeError(
            "BNGsim Python bridge unavailable: BNG3 native NET exporter is missing"
        )

    _validate_runtime_options(
        method=method,
        n_species=int(getattr(cpp_network, "num_species", 0)),
        stop_if=stop_if,
        sparse=sparse,
        check_product_scale=check_product_scale,
        steady_state=steady_state,
        steady_state_tol=steady_state_tol,
        sample_times=sample_times,
        max_sim_steps=max_sim_steps,
        output_step_interval=output_step_interval,
        batch_size=batch_size,
        psa_poplevel=psa_poplevel,
    )

    model_options = getattr(cpp_model, "options", {}) or {}
    if model_options.get("BNG3AbsoluteFluxRules"):
        raise RuntimeError(
            "BNGsim Python bridge rejected absolute-flux reactions: "
            "BNG3AbsoluteFluxRules require the compiled C++ BNGsim adapter"
        )

    with TemporaryDirectory(prefix="bng3-bngsim-py-") as tmpdir:
        net_path = str(Path(tmpdir) / "network.net")
        cpp.io.write_net(cpp_model, cpp_network, net_path)
        bngsim_model = bngsim_mod.Model.from_net(net_path)

    if method == "psa":
        sim = bngsim_mod.Simulator(
            bngsim_model, method="psa", poplevel=float(psa_poplevel)
        )
    else:
        sim = bngsim_mod.Simulator(bngsim_model, method=method)

    run_kwargs: dict[str, Any] = {}
    if sample_times:
        run_kwargs["sample_times"] = list(sample_times)
    else:
        run_kwargs["t_span"] = (float(t_start), float(t_end))
        run_kwargs["n_points"] = int(n_steps) + 1

    if method == "ode":
        run_kwargs["rtol"] = float(rtol)
        run_kwargs["atol"] = float(atol)
        if max_step > 0.0:
            run_kwargs["max_step_size"] = float(max_step)
        if steady_state:
            run_kwargs["steady_state"] = True
            run_kwargs["steady_state_tol"] = float(steady_state_tol)
    elif method in ("ssa", "psa"):
        if seed:
            run_kwargs["seed"] = int(seed)

    try:
        raw_result = sim.run(**run_kwargs)
    except Exception as exc:
        raise RuntimeError(f"BNGsim numerical failure ({method}): {exc}") from exc

    expected_obs = [obs.name for obs in getattr(cpp_model, "observables", [])]
    return _convert_python_bngsim_result(
        raw_result,
        expected_observable_names=expected_obs,
        expected_sample_times=sample_times,
    )


__all__ = [
    "bngsim_available",
    "bngsim_capabilities",
    "bngsim_version",
    "normalize_finite_backend",
    "simulate_via_python_bngsim",
    "validate_nf_backend",
]
