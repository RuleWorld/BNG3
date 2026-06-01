"""Run the BNG3 engine under test, two ways.

CLI path  (bng_cpp MODEL.bngl): the engine executes the model's action block and
          writes MODEL.net / MODEL.gdat next to the copied input. Used for .net
          parity (the C++ CLI is what emits a .net file).

API path  (import bionetgen): the unified Python entry. load() + simulate(method)
          returns in-memory arrays. Used for trajectory and export parity, since
          that is the path WO-4 makes canonical.

Both write into a caller-supplied work dir so nothing touches the source tree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import corpus


# --------------------------------------------------------------------------- #
# CLI path
# --------------------------------------------------------------------------- #

def _cli_env(bng_cpp: Path) -> dict[str, str]:
    env = os.environ.copy()
    bindir = str(Path(bng_cpp).parent)
    extra = [bindir]
    for p in (r"C:\Strawberry\c\bin", r"C:\mingw64\bin", r"C:\msys64\mingw64\bin"):
        if os.path.isdir(p):
            extra.append(p)
    env["PATH"] = os.pathsep.join(extra) + os.pathsep + env.get("PATH", "")
    return env


def run_cli(bng_cpp: Path, model_name: str, work_dir: Path, *, timeout: int = 180):
    """Run bng_cpp on a model; return (net_path|None, gdat_path|None, stderr)."""
    src = corpus.resolve(model_name)
    if src is None:
        return None, None, f"model {model_name!r} not found on disk"

    work_dir.mkdir(parents=True, exist_ok=True)
    local = work_dir / src.name
    shutil.copy2(src, local)

    try:
        proc = subprocess.run(
            [str(bng_cpp), str(local)],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_cli_env(bng_cpp),
        )
    except subprocess.TimeoutExpired:
        return None, None, f"timeout after {timeout}s"
    if proc.returncode != 0:
        return None, None, proc.stderr or proc.stdout

    net = next(iter(work_dir.glob("*.net")), None)
    gdat = next(iter(work_dir.glob("*.gdat")), None)
    return net, gdat, proc.stderr


# --------------------------------------------------------------------------- #
# API path
# --------------------------------------------------------------------------- #

@dataclass
class Trajectory:
    data: np.ndarray          # (n_t, n_col), col 0 = time
    columns: list[str]        # ["time", obs1, obs2, ...]


def _result_to_trajectory(result) -> Trajectory:
    """Adapt a bionetgen.SimResult to the (data, columns) shape compare.py wants."""
    time = np.asarray(result.time, dtype=float)
    obs = result.observables  # dict[str, np.ndarray]
    names = list(obs.keys())
    cols = ["time"] + names
    data = np.column_stack([time] + [np.asarray(obs[n], dtype=float) for n in names])
    return Trajectory(data=data, columns=cols)


def run_api(
    model_name: str,
    *,
    method: str = "ode",
    t_end: float = 100.0,
    n_steps: int = 100,
    seed: int = 0,
    **kwargs,
) -> Trajectory:
    """load(model).simulate(method=...) via the unified Python API."""
    import bionetgen

    src = corpus.resolve(model_name)
    if src is None:
        raise FileNotFoundError(f"model {model_name!r} not found on disk")
    model = bionetgen.load(str(src))
    result = model.simulate(
        method=method, t_end=t_end, n_steps=n_steps, seed=seed, **kwargs
    )
    return _result_to_trajectory(result)


def run_api_ensemble(
    model_name: str,
    *,
    method: str = "ssa",
    n_runs: int = 200,
    base_seed: int = 1,
    **kwargs,
) -> list[tuple[np.ndarray, list[str]]]:
    """Run a seeded stochastic ensemble; returns runs in compare.py's shape."""
    runs = []
    for i in range(n_runs):
        traj = run_api(model_name, method=method, seed=base_seed + i, **kwargs)
        runs.append((traj.data, traj.columns))
    return runs


def export(model_name: str, fmt: str, out_path: Path) -> Path:
    """Export a model to a format via the unified writer methods (WO-5 path)."""
    import bionetgen

    src = corpus.resolve(model_name)
    model = bionetgen.load(str(src))
    method = {
        "xml": model.write_xml,
        "bngl": model.write_bngl,
        "sbml": model.write_sbml,
        "matlab": model.write_matlab,
        "latex": model.write_latex,
    }[fmt]
    method(str(out_path))
    return out_path
