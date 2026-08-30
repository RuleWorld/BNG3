"""Oracle B — native NFsim binary.

Source of truth for network-free trajectories. This is the *pre-merge* NFsim
behavior; WO-2 (ast-direct System construction) must reproduce it. Built from
cpp/nfsim/NFsim.cpp via the optional CMake `NFsim` target.

NFsim consumes BNG-XML, not BNGL. We obtain the XML from the engine under test
(model.write_xml) so both sides start from the same model, then run NFsim on it.

Configuration (env):
  NFSIM_BIN   path to the native NFsim executable (default: <repo>/build/NFsim)
"""

from __future__ import annotations

import concurrent.futures
import os
import subprocess
from pathlib import Path

from . import corpus

REPO = corpus.REPO


def _nfsim_bin() -> Path | None:
    configured = os.environ.get("NFSIM_BIN")
    candidates = ((Path(configured),) if configured else ()) + (
        REPO / "build" / "NFsim",
        REPO / "build" / "NFsim.exe",
        REPO / "build" / "cpp" / "NFsim",
    )
    for cand in candidates:
        path = cand.expanduser()
        if path.exists():
            return path.resolve()
    return None


def nfsim_available() -> bool:
    return _nfsim_bin() is not None


def write_model_xml(model_name: str, out_xml: Path) -> Path | None:
    """Use the engine-under-test to emit BNG-XML for the model."""
    import bionetgen

    src = corpus.resolve(model_name)
    if src is None:
        return None
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    bionetgen.load(str(src)).write_xml(str(out_xml))
    return out_xml if out_xml.exists() else None


def run_nfsim(
    xml_path: Path,
    work_dir: Path,
    *,
    t_end: float = 100.0,
    n_steps: int = 100,
    seed: int = 1,
    timeout: int = 300,
) -> tuple[Path | None, str]:
    """Run native NFsim on a BNG-XML model; return (gdat|None, stderr)."""
    nfsim = _nfsim_bin()
    if nfsim is None:
        return None, "NFsim binary not found (set NFSIM_BIN)"
    work_dir.mkdir(parents=True, exist_ok=True)
    out_prefix = work_dir / xml_path.stem
    cmd = [
        str(nfsim),
        "-xml",
        str(xml_path),
        "-o",
        f"{out_prefix}.gdat",
        "-sim",
        str(t_end),
        "-oSteps",
        str(n_steps),
        "-seed",
        str(seed),
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(work_dir), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return None, f"nfsim timeout after {timeout}s"
    if proc.returncode != 0:
        return None, proc.stderr or proc.stdout
    gdat = Path(f"{out_prefix}.gdat")
    return (gdat, proc.stderr) if gdat.exists() else (None, "no .gdat produced")


def _resolve_ensemble_workers(requested: int | None, n_runs: int) -> int:
    """Resolve bounded native-oracle concurrency from the shared env knob."""
    if n_runs < 0:
        raise ValueError("n_runs must be non-negative")
    if requested is None:
        raw = os.environ.get("BNG_ENSEMBLE_WORKERS")
        requested = int(raw) if raw else 4
    if requested < 1:
        raise ValueError("ensemble workers must be at least one")
    return min(requested, n_runs) if n_runs else 1


def _run_nfsim_ensemble_item(payload):
    xml_path, work_dir, t_end, n_steps, seed = payload
    return run_nfsim(
        xml_path,
        work_dir,
        t_end=t_end,
        n_steps=n_steps,
        seed=seed,
    )


def ensemble(
    model_name: str,
    work_dir: Path,
    *,
    n_runs: int = 200,
    base_seed: int = 1,
    t_end: float = 100.0,
    n_steps: int = 100,
    workers: int | None = None,
):
    """Native-NFsim ensemble in compare.compare_stochastic shape."""
    from .compare import parse_gdat

    xml = write_model_xml(model_name, work_dir / f"{Path(model_name).stem}.xml")
    if xml is None:
        return []
    worker_count = _resolve_ensemble_workers(workers, n_runs)
    payloads = [
        (xml, work_dir / f"run{i}", t_end, n_steps, base_seed + i)
        for i in range(n_runs)
    ]
    if worker_count == 1:
        results = [_run_nfsim_ensemble_item(payload) for payload in payloads]
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count
        ) as pool:
            results = list(pool.map(_run_nfsim_ensemble_item, payloads))

    runs = []
    for gdat, _ in results:
        if gdat is None:
            continue
        data, cols = parse_gdat(gdat)
        if data is not None:
            runs.append((data, cols))
    return runs
