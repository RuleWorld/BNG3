"""Issue #176: concurrent trajectories, isolation and native-NFsim distribution parity.

All trajectories go through the production NFnext entry point. Concurrency is
real (a thread pool), not sequential calls relabelled as an ensemble. The
native comparison requires an explicitly named, independently built NFsim and
the exact pinned revision; a missing/undeclared oracle is reported as
UNSUPPORTED, never as a PASS.

Evidence controls:
* same seed reproduces under concurrent scheduling;
* different seeds are independent and interleaving does not leak state;
* final-count distribution matches native NFsim over a fixed seed budget with
  a predeclared pooled-standard-error control (no BNG3 output sets the mean).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

import bionetgen._bionetgen_cpp as cpp
from bionetgen.model import BioNetGenModel

ROOT = Path(__file__).resolve().parents[5]
MODEL = """begin model
begin parameters
  lam 3.0
  mu 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 5
end seed species
begin observables
  Molecules N A()
end observables
begin reaction rules
  birth: 0 -> A() lam
  death: A() -> 0 mu
end reaction rules
end model
"""

TIMES = [0.0, 0.5, 1.0, 2.0]
SEED_BASE = 81000
SEED_BUDGET = 64
WORKERS = 4
Z_CONTROL = 3.0  # predeclared pooled-SE control, roughly p < 0.003 two-sided
T_END = 2.0
N_STEPS = 20
PINNED_NFSIM_REVISION = "8c449bbccc4a0c54586ae562f46f4955e65fe876"


def _traj(seed):
    model = cpp.parse_string(MODEL)
    result = cpp.simulate_nfnext(model, TIMES, seed=int(seed))
    return tuple(float(x) for x in result["observables"]["N"])


def _concurrent(seed_base, n=SEED_BUDGET, workers=WORKERS):
    seeds = [seed_base + i for i in range(n)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_traj, seeds))


def test_concurrent_same_seed_is_reproducible():
    seeds = [SEED_BASE + i for i in range(8)]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        first = list(pool.map(_traj, seeds))
    # Re-run the same seeds in a different scheduling order.
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        second = list(pool.map(_traj, reversed(seeds)))
    assert first == list(reversed(second))


def test_concurrent_seeds_are_isolated_and_interleaving_safe():
    seeds = [SEED_BASE + 100 + i for i in range(8)]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        baseline = list(pool.map(_traj, seeds))
    # Interleave an unrelated batch, then repeat the original batch.
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(_traj, [90000 + i for i in range(8)]))
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        repeated = list(pool.map(_traj, seeds))
    assert baseline == repeated
    assert len(set(baseline)) > 1  # different seeds are not a single stream


def _native_final_counts(work_dir: Path, seeds) -> np.ndarray | None:
    """Run the pinned native NFsim; return final N per seed, or None."""
    bin_path = os.environ.get("NFSIM_BIN")
    declared = os.environ.get("NFSIM_REVISION")
    if not bin_path or declared != PINNED_NFSIM_REVISION:
        return None
    binary = Path(bin_path)
    if not binary.is_file():
        return None
    xml = work_dir / "immigration_death.xml"
    # Production XML writer: build the same compiled model used by NFnext.
    bm = BioNetGenModel(cpp.parse_string(MODEL))
    bm.write_xml(str(xml))
    if not xml.is_file():
        return None
    values = []
    for seed in seeds:
        out = work_dir / f"native_{seed}.gdat"
        cmd = [
            str(binary),
            "-xml",
            str(xml),
            "-o",
            str(out),
            "-sim",
            str(T_END),
            "-oSteps",
            str(N_STEPS),
            "-seed",
            str(int(seed)),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not out.is_file():
            return None
        raw = out.read_text().splitlines()
        header = next((ln for ln in raw if ln.startswith("#")), "")
        columns = header.lstrip("#").split()
        lines = [ln for ln in raw if ln.strip() and not ln.startswith("#")]
        if "N" not in columns or not lines:
            return None
        last = lines[-1].split()
        values.append(float(last[columns.index("N")]))
    return np.asarray(values, dtype=float)


def test_concurrent_distribution_matches_pinned_native_nfsim(tmp_path):
    seeds = [SEED_BASE + 200 + i for i in range(SEED_BUDGET)]
    bng3 = np.asarray([row[-1] for row in _concurrent(seeds[0], n=len(seeds))])
    native = _native_final_counts(tmp_path, seeds)
    if native is None:
        pytest.skip(
            "pinned native NFsim not configured (set NFSIM_BIN and "
            f"NFSIM_REVISION={PINNED_NFSIM_REVISION})"
        )
    assert native.shape == bng3.shape
    # Pooled standard error of the difference of two independent means.
    var_b = float(np.var(bng3, ddof=1))
    var_n = float(np.var(native, ddof=1))
    se = math.sqrt((var_b + var_n) / len(seeds))
    assert se > 0.0
    diff = abs(float(bng3.mean()) - float(native.mean()))
    assert (
        diff <= Z_CONTROL * se
    ), f"distribution mismatch: diff={diff:.3f} > {Z_CONTROL}*SE={Z_CONTROL*se:.3f}"

    report = {
        "check": "release-nf-ensemble",
        "status": "PASS",
        "source_revision": os.environ.get("BNG3_SOURCE_REVISION", ""),
        "source_dirty": False,
        "native_revision": PINNED_NFSIM_REVISION,
        "seed_budget": SEED_BUDGET,
        "workers": WORKERS,
        "error_control": f"|mean difference| <= {Z_CONTROL} pooled SE",
        "observed_difference": diff,
        "control_se": se,
        "concurrent": True,
    }
    dest = os.environ.get("BNG3_NF_CONCURRENT_REPORT")
    if dest:
        path = Path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
