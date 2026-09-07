#!/usr/bin/env python3
"""Statistical equivalence gate for legacy vs generalized NF energy lowering.

The numerical comparison helpers are usable. Live ON/OFF execution is rejected
until the engine reports verified backend activation. It does NOT require byte-identical trajectories
when lowering changes reaction aggregation/RNG consumption. Instead it gates
observable distributions at every sampled time point.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class Thresholds:
    mean_z: float = 5.0
    variance_ratio_low: float = 0.80
    variance_ratio_high: float = 1.25
    tv: float = 0.075
    ks: float = 0.075
    max_tv_support: int = 32


@dataclass
class PointMetrics:
    observable: str
    time_index: int
    time: float
    n: int
    legacy_mean: float
    general_mean: float
    pooled_se_z: float
    paired_se_z: float
    variance_ratio: float
    tv: float | None
    ks: float
    support_size: int
    shape_metric: str
    passed: bool


@contextlib.contextmanager
def generalized_energy(enabled: bool):
    key = "BNG_NFSIM_GENERAL_ENERGY"
    old = os.environ.get(key)
    try:
        if enabled:
            os.environ[key] = "1"
        else:
            os.environ.pop(key, None)
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


def _variance_ratio(a: np.ndarray, b: np.ndarray) -> float:
    va = float(np.var(a, ddof=1)) if len(a) > 1 else 0.0
    vb = float(np.var(b, ddof=1)) if len(b) > 1 else 0.0
    if va == 0.0 and vb == 0.0:
        return 1.0
    if va == 0.0:
        return math.inf
    return vb / va


def _pooled_se_z(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) != len(b) or len(a) < 2:
        return math.inf
    va = float(np.var(a, ddof=1))
    vb = float(np.var(b, ddof=1))
    se = math.sqrt(va / len(a) + vb / len(b))
    diff = abs(float(np.mean(a) - np.mean(b)))
    if se == 0.0:
        return 0.0 if diff == 0.0 else math.inf
    return diff / se


def _paired_se_z(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) != len(b) or len(a) < 2:
        return math.inf
    d = b - a
    sd = float(np.std(d, ddof=1))
    diff = abs(float(np.mean(d)))
    if sd == 0.0:
        return 0.0 if diff == 0.0 else math.inf
    return diff / (sd / math.sqrt(len(d)))


def _empirical_tv(a: np.ndarray, b: np.ndarray) -> float:
    # Appropriate for the count-valued NFsim observables used by this gate.
    if len(a) == 0 or len(b) == 0:
        return math.inf
    values = np.union1d(a, b)
    pa = np.array([(a == x).mean() for x in values], dtype=float)
    pb = np.array([(b == x).mean() for x in values], dtype=float)
    return float(0.5 * np.abs(pa - pb).sum())


def _ks_distance(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) == 0 or len(b) == 0:
        return math.inf
    values = np.union1d(a, b)
    sa = np.sort(a)
    sb = np.sort(b)
    cdfa = np.searchsorted(sa, values, side="right") / len(sa)
    cdfb = np.searchsorted(sb, values, side="right") / len(sb)
    return float(np.max(np.abs(cdfa - cdfb)))


def compare_point(
    legacy: Sequence[float],
    general: Sequence[float],
    *,
    observable: str = "obs",
    time_index: int = 0,
    time: float = 0.0,
    thresholds: Thresholds = Thresholds(),
) -> PointMetrics:
    a = np.asarray(legacy, dtype=float)
    b = np.asarray(general, dtype=float)
    if a.shape != b.shape or a.ndim != 1:
        raise ValueError("legacy/general samples must be equal-length 1D arrays")
    if len(a) < 2:
        raise ValueError(
            "at least two seeds are required for a statistical parity point"
        )
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("statistical parity samples must be finite")
    z = _pooled_se_z(a, b)
    pz = _paired_se_z(a, b)
    vr = _variance_ratio(a, b)
    support_size = int(np.union1d(a, b).size)
    ks = _ks_distance(a, b)
    if support_size <= thresholds.max_tv_support:
        tv = _empirical_tv(a, b)
        shape_ok = tv <= thresholds.tv
        shape_metric = "tv"
    else:
        tv = None
        shape_ok = ks <= thresholds.ks
        shape_metric = "ks"
    passed = (
        z <= thresholds.mean_z
        and thresholds.variance_ratio_low <= vr <= thresholds.variance_ratio_high
        and shape_ok
    )
    return PointMetrics(
        observable=observable,
        time_index=time_index,
        time=float(time),
        n=len(a),
        legacy_mean=float(a.mean()),
        general_mean=float(b.mean()),
        pooled_se_z=z,
        paired_se_z=pz,
        variance_ratio=vr,
        tv=tv,
        ks=ks,
        support_size=support_size,
        shape_metric=shape_metric,
        passed=passed,
    )


def compare_trajectories(
    legacy: Mapping[str, np.ndarray],
    general: Mapping[str, np.ndarray],
    times: Sequence[float],
    thresholds: Thresholds = Thresholds(),
) -> list[PointMetrics]:
    if not legacy or len(times) == 0 or not np.isfinite(times).all():
        raise ValueError("nonempty observables and finite time points required")
    if set(legacy) != set(general):
        raise ValueError("observable sets differ")
    metrics: list[PointMetrics] = []
    for name in sorted(legacy):
        a = np.asarray(legacy[name], dtype=float)
        b = np.asarray(general[name], dtype=float)
        if a.shape != b.shape or a.ndim != 2:
            raise ValueError(f"{name}: expected equal [seed,time] matrices")
        if a.shape[1] != len(times):
            raise ValueError(f"{name}: time dimension mismatch")
        for j, t in enumerate(times):
            metrics.append(
                compare_point(
                    a[:, j],
                    b[:, j],
                    observable=name,
                    time_index=j,
                    time=float(t),
                    thresholds=thresholds,
                )
            )
    return metrics


def run_gate(
    model_path: Path,
    seeds: Sequence[int],
    t_end: float,
    n_steps: int,
    thresholds: Thresholds = Thresholds(),
) -> dict:
    # The current engine does not consume BNG_NFSIM_GENERAL_ENERGY. Merely
    # changing that environment variable compares the same backend twice.
    raise NotImplementedError(
        "generalized energy backend activation cannot yet be verified; "
        "use compare_trajectories for separately collected data, not a promotion claim"
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("model", type=Path)
    p.add_argument("--seeds", type=int, default=1024, help="Use seeds 1..N")
    p.add_argument("--t-end", type=float, default=20.0)
    p.add_argument("--n-steps", type=int, default=20)
    p.add_argument("--mean-z", type=float, default=5.0)
    p.add_argument("--variance-low", type=float, default=0.80)
    p.add_argument("--variance-high", type=float, default=1.25)
    p.add_argument("--tv", type=float, default=0.075)
    p.add_argument("--ks", type=float, default=0.075)
    p.add_argument("--max-tv-support", type=int, default=32)
    p.add_argument("--json", type=Path)
    args = p.parse_args()

    thresholds = Thresholds(
        args.mean_z,
        args.variance_low,
        args.variance_high,
        args.tv,
        args.ks,
        args.max_tv_support,
    )
    report = run_gate(
        args.model, list(range(1, args.seeds + 1)), args.t_end, args.n_steps, thresholds
    )
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
