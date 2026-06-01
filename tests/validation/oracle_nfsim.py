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

import os
import subprocess
from pathlib import Path

from . import corpus

REPO = corpus.REPO


def _nfsim_bin() -> Path | None:
    for cand in (
        Path(os.environ.get("NFSIM_BIN", "")),
        REPO / "build" / "NFsim",
        REPO / "build" / "NFsim.exe",
        REPO / "build" / "cpp" / "NFsim",
    ):
        if cand and cand.exists():
            return cand
    return None


def nfsim_available() -> bool:
    return _nfsim_bin() is not None


def write_model_xml(model_name: str, out_xml: Path) -> Path | None:
    """Use the engine-under-test to emit BNG-XML for the model."""
    import bionetgen

    src = corpus.resolve(model_name)
    if src is None:
        return None
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
        "-xml", str(xml_path),
        "-o", f"{out_prefix}.gdat",
        "-sim", str(t_end),
        "-oSteps", str(n_steps),
        "-seed", str(seed),
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


def ensemble(
    model_name: str,
    work_dir: Path,
    *,
    n_runs: int = 200,
    base_seed: int = 1,
    t_end: float = 100.0,
    n_steps: int = 100,
):
    """Native-NFsim ensemble for the model, in compare.compare_stochastic shape."""
    from .compare import parse_gdat

    xml = write_model_xml(model_name, work_dir / f"{Path(model_name).stem}.xml")
    if xml is None:
        return []
    runs = []
    for i in range(n_runs):
        gdat, _ = run_nfsim(
            xml, work_dir / f"run{i}", t_end=t_end, n_steps=n_steps, seed=base_seed + i
        )
        if gdat is None:
            continue
        data, cols = parse_gdat(gdat)
        if data is not None:
            runs.append((data, cols))
    return runs
