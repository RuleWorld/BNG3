"""Oracle A — Perl BNG2.pl.

Source of truth for network generation (.net) and ODE/SSA trajectories
(.gdat/.cdat). To keep the Perl runtime off the hot path, every test first looks
for a committed golden file; Perl is only invoked when no golden exists and a
Perl runtime is configured (scripts/regen_golden.py is the sanctioned way to
populate golden/).

Configuration (env):
  BNG2_PERL   path to legacy/perl/BNG2.pl  (default: <repo>/legacy/perl/BNG2.pl)
  PERL        perl interpreter             (default: "perl")
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import corpus

REPO = corpus.REPO
GOLDEN = REPO / "tests" / "validation" / "golden"


def golden_net(model_name: str) -> Path | None:
    p = GOLDEN / f"{Path(model_name).stem}.net"
    return p if p.exists() else None


def golden_gdat(model_name: str) -> Path | None:
    p = GOLDEN / f"{Path(model_name).stem}.gdat"
    return p if p.exists() else None


def _bng2_path() -> Path | None:
    p = Path(os.environ.get("BNG2_PERL", REPO / "legacy" / "perl" / "BNG2.pl"))
    return p if p.exists() else None


def perl_available() -> bool:
    return _bng2_path() is not None and shutil.which(os.environ.get("PERL", "perl")) is not None


def run_perl(model_name: str, work_dir: Path, *, timeout: int = 300):
    """Run Perl BNG2 on a model; return (net|None, gdat|None, stderr)."""
    bng2 = _bng2_path()
    if bng2 is None:
        return None, None, "BNG2.pl not found (set BNG2_PERL)"
    src = corpus.resolve(model_name)
    if src is None:
        return None, None, f"model {model_name!r} not on disk"

    work_dir.mkdir(parents=True, exist_ok=True)
    local = work_dir / src.name
    shutil.copy2(src, local)
    try:
        proc = subprocess.run(
            [os.environ.get("PERL", "perl"), str(bng2), str(local)],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, None, f"perl timeout after {timeout}s"
    if proc.returncode != 0:
        return None, None, proc.stderr or proc.stdout
    net = next(iter(work_dir.glob("*.net")), None)
    gdat = next(iter(work_dir.glob("*.gdat")), None)
    return net, gdat, proc.stderr


def net(model_name: str, work_dir: Path) -> tuple[Path | None, str]:
    """Reference .net: golden first, then live Perl, else (None, reason)."""
    g = golden_net(model_name)
    if g is not None:
        return g, "golden"
    if perl_available():
        p, _, err = run_perl(model_name, work_dir)
        return (p, "perl") if p else (None, f"perl failed: {err}")
    return None, "no golden and no perl"


def gdat(model_name: str, work_dir: Path) -> tuple[Path | None, str]:
    g = golden_gdat(model_name)
    if g is not None:
        return g, "golden"
    if perl_available():
        _, p, err = run_perl(model_name, work_dir)
        return (p, "perl") if p else (None, f"perl failed: {err}")
    return None, "no golden and no perl"
