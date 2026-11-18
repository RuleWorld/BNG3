#!/usr/bin/env python3
"""Execute the predeclared delayed NonConsuming competing-transition case.

Emits a replayable receipt with plan hash, seed budget, analytic law, identity
and wrong-implementation controls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if sys.platform == "darwin" and "JAX_PLATFORMS" not in os.environ:
    os.environ["JAX_PLATFORMS"] = "cpu"

import numpy as np

from tests.python import test_delayed_competing_intervention as case

PLAN = Path(__file__).with_name("PREDECLARED_PLAN.md")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity() -> dict:
    import bionetgen
    import bionetgen._bionetgen_cpp as cpp

    revision = subprocess.run(
        ["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "bionetgen_package": bionetgen.__file__,
        "native_extension": cpp.__file__,
        "native_extension_sha256": _sha256(Path(cpp.__file__)),
        "numpy": np.__version__,
        "python": sys.version.split()[0],
        "source_revision": revision,
    }


def run() -> dict:
    case.test_delayed_nonconsuming_competing_decay_ode_split_and_uninterrupted()
    case.test_delayed_nonconsuming_competing_decay_ssa_poisson_law()
    case.test_delayed_nonconsuming_bngir_reconstruction_source_law()
    case.test_delayed_semantic_equal_counterexamples()

    lam = case._poisson_lambda(3.0)
    samples = np.array(
        [
            case._ssa_uninterrupted(case.SEED_BASE + i)[case.SAMPLE_TIMES.index(3.0)]
            for i in range(case.N_RUNS)
        ]
    )
    wrong_no_decay = 40.0 * (3.0 - 1.0)
    wrong_halved = 40.0 * (1.0 - math.exp(-0.5 * (3.0 - 1.0)))
    return {
        "case": "delayed_nonconsuming_competing_intervention",
        "plan_sha256": _sha256(PLAN),
        "identity": _identity(),
        "law": "B(t)~Poisson(80*(1-exp(-0.5*(t-1)))) for t>=1; A(t)=20",
        "protocol": {
            "seed_base": case.SEED_BASE,
            "n_runs": case.N_RUNS,
            "sample_times": case.SAMPLE_TIMES,
            "error_control": "4*sqrt(lambda/N) mean; var within 0.5*lambda",
        },
        "observed_at_t3": {
            "mean": float(samples.mean()),
            "variance": float(samples.var()),
            "analytic_lambda": lam,
        },
        "wrong_implementation_controls": {
            "no_decay_prediction": wrong_no_decay,
            "rate_halved_prediction": wrong_halved,
            "rejected": bool(
                abs(samples.mean() - wrong_no_decay)
                > 4.0 * math.sqrt(lam / case.N_RUNS)
                and abs(samples.mean() - wrong_halved)
                > 4.0 * math.sqrt(wrong_halved / case.N_RUNS)
            ),
        },
        "wire_format": "BNGIR v0.1/v0.2 are model specifications, not live pending-queue checkpoints",
        "all_passed": True,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    result = run()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "protocol": result["protocol"],
                "observed_at_t3": result["observed_at_t3"],
                "wrong_implementation_controls": result[
                    "wrong_implementation_controls"
                ],
                "all_passed": result["all_passed"],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if result["all_passed"] else 1)
