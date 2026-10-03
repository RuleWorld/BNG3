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


def golden_ensemble(model_name: str) -> Path | None:
    """Return a committed directory of fixed-seed Perl trajectories, if any.

    Ensemble references are deliberately separate from the single-trajectory
    golden.  A directory named ``<model>.ens`` contains one ``.gdat`` per
    predeclared seed; callers must enforce the required member count.
    """
    p = GOLDEN / f"{Path(model_name).stem}.ens"
    return p if p.is_dir() else None


def _bng2_path() -> Path | None:
    p = Path(os.environ.get("BNG2_PERL", REPO / "legacy" / "perl" / "BNG2.pl"))
    return p if p.exists() else None


def perl_available() -> bool:
    return (
        _bng2_path() is not None
        and shutil.which(os.environ.get("PERL", "perl")) is not None
    )


def _select_artifact(work_dir: Path, model_stem: str, suffix: str) -> Path | None:
    """Select the exact model artifact, or a sole unambiguous phase output."""
    exact = work_dir / f"{model_stem}{suffix}"
    if exact.is_file():
        return exact
    candidates = sorted(work_dir.glob(f"*{suffix}"))
    return candidates[0] if len(candidates) == 1 else None


def _artifact_error(work_dir: Path, model_stem: str, suffix: str) -> str:
    candidates = sorted(work_dir.glob(f"*{suffix}"))
    if candidates:
        names = ", ".join(path.name for path in candidates)
        return (
            f"ambiguous BNG2 {suffix} outputs for {model_stem}: {names}; "
            f"expected {model_stem}{suffix}"
        )
    return f"BNG2 produced no {suffix} output for {model_stem}"


def run_perl(
    model_name: str,
    work_dir: Path,
    *,
    timeout: int = 300,
    skip_nfsim: bool = False,
    network_only: bool = False,
    source_path: Path | None = None,
):
    """Run Perl BNG2 on a model; return (net|None, gdat|None, stderr)."""
    bng2 = _bng2_path()
    if bng2 is None:
        return None, None, "BNG2.pl not found (set BNG2_PERL)"
    src = (
        Path(source_path).resolve()
        if source_path is not None
        else corpus.resolve(model_name)
    )
    if src is None:
        return None, None, f"model {model_name!r} not on disk"

    work_dir.mkdir(parents=True, exist_ok=True)
    src = Path(src).resolve()
    env = os.environ.copy()
    if not env.get("BNGPATH"):
        env["BNGPATH"] = str(bng2.parent)
    command = [
        os.environ.get("PERL", "perl"),
        str(bng2),
        "--outdir",
        str(work_dir),
    ]
    if network_only:
        # Parse source definitions, skip its simulation/action block, then ask
        # BNG2 to generate only the reaction network. This is the correct
        # oracle route for state-vector RHS checks and avoids running a model's
        # unrelated long SSA/NF equilibration actions.
        command.extend(["--check", "--netgen"])
    if skip_nfsim:
        command.append("--no-nfsim")
    command.append(str(src))
    try:
        proc = subprocess.run(
            command,
            cwd=str(src.parent),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return None, None, f"perl timeout after {timeout}s"
    if proc.returncode != 0:
        return None, None, proc.stderr or proc.stdout
    net = _select_artifact(work_dir, src.stem, ".net")
    gdat = _select_artifact(work_dir, src.stem, ".gdat")
    selection_errors = []
    if net is None:
        selection_errors.append(_artifact_error(work_dir, src.stem, ".net"))
    if gdat is None:
        selection_errors.append(_artifact_error(work_dir, src.stem, ".gdat"))
    message = proc.stderr.strip()
    if selection_errors:
        message = "\n".join(part for part in (message, *selection_errors) if part)
    return net, gdat, message


def net(
    model_name: str,
    work_dir: Path,
    *,
    network_only: bool = False,
    source_path: Path | None = None,
) -> tuple[Path | None, str]:
    """Reference .net: golden first, then live Perl, else (None, reason)."""
    g = golden_net(model_name)
    if g is not None:
        return g, "golden"
    if perl_available():
        p, _, err = run_perl(
            model_name,
            work_dir,
            skip_nfsim=True,
            network_only=network_only,
            source_path=source_path,
        )
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


def ensemble(
    model_name: str, *, min_runs: int = 200
) -> tuple[list[tuple[object, list[str]]], str]:
    """Load a committed fixed-seed Perl ensemble; never substitute one gdat.

    The returned arrays are intentionally typed loosely here to avoid making
    the oracle module depend on NumPy at import time; ``compare.parse_gdat``
    supplies the concrete arrays in the test process.
    """
    from .compare import parse_gdat

    directory = golden_ensemble(model_name)
    if directory is None:
        return [], "no committed ensemble directory"
    paths = sorted(directory.glob("*.gdat"))
    if len(paths) < min_runs:
        return paths_to_runs(paths), (
            f"ensemble has {len(paths)} member(s), requires at least {min_runs}"
        )
    runs = []
    for path in paths:
        data, columns = parse_gdat(path)
        if data is None or columns is None:
            return [], f"invalid ensemble member: {path.name}"
        runs.append((data, columns))
    return runs, f"golden ensemble ({len(runs)} members)"


def paths_to_runs(paths):
    """Parse best-effort members for useful diagnostics when the count is low."""
    from .compare import parse_gdat

    runs = []
    for path in paths:
        data, columns = parse_gdat(path)
        if data is not None and columns is not None:
            runs.append((data, columns))
    return runs
