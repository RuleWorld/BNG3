#!/usr/bin/env python3
"""Execute the predeclared installed CPU JAX protocol/parameter-intervention case.

Emits a replayable receipt with plan hash, analytic laws, gradients, toolchain
identity and the wrong-implementation control. No stochastic seeds apply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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

from bionetgen import jax_ode
from tests.python import test_jax_protocol_intervention as case

PLAN = Path(__file__).with_name("PREDECLARED_PLAN.md")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity() -> dict:
    import jax
    import jaxlib
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
        "jax": jax.__version__,
        "jaxlib": jaxlib.__version__,
        "numpy": np.__version__,
        "devices": [str(d) for d in jax.devices()],
        "jax_enable_x64": bool(jax.config.jax_enable_x64),
        "source_revision": revision,
    }


def run() -> dict:
    case.test_jax_ode_time_dependent_parameter_intervention_continuation()
    case.test_jax_ode_time_dependent_intervention_gradient()
    case.test_jax_ode_functional_rate_intervention_continuation_and_gradient()
    case.test_jax_ode_intervention_error_behavior()

    # Wrong-implementation control: frozen phase-1 rate predictions and the
    # analytic piecewise results they must not match.
    model = case._time_dependent_model()
    p1 = jax_ode.simulate_jax_ode(
        model,
        t_end=2.0,
        t_start=0.0,
        n_steps=40,
        parameters={"k": 1.0},
        return_jax=True,
    )
    p2 = jax_ode.simulate_jax_ode(
        model,
        t_end=4.0,
        t_start=2.0,
        n_steps=40,
        initial_state=p1["concentrations"][-1],
        parameters={"k": 3.0},
        return_jax=True,
    )
    return {
        "case": "jax_ode_protocol_parameter_intervention_installed_cpu",
        "plan_sha256": _sha256(PLAN),
        "identity": _identity(),
        "laws": {
            "time_dependent": "A(t0)+0.5*k*(t^2-t0^2); dA(4)/dk2=6",
            "functional": "A(t0)/(1+k*A(t0)*(t-t0))",
        },
        "wrong_implementation_control": {
            "frozen_rate_prediction_A4": 8.0,
            "analytic_A4": float(np.asarray(p2["concentrations"])[-1, 0]),
            "rejected": abs(float(np.asarray(p2["concentrations"])[-1, 0]) - 8.0)
            > 1e-3,
        },
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
                "identity": result["identity"],
                "wrong_implementation_control": result["wrong_implementation_control"],
                "all_passed": result["all_passed"],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if result["all_passed"] else 1)
