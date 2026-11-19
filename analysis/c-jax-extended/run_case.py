#!/usr/bin/env python3
"""Execute the predeclared extended installed CPU JAX qualification for #473.

Emits a bounded receipt with identities, predeclared laws and observed values.
Independent analytic laws and the native batch-SSA reference are the oracles.
Run with JAX_PLATFORMS=cpu and an installed (non-editable-shadowed) package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

if sys.platform == "darwin" and "JAX_PLATFORMS" not in os.environ:
    os.environ["JAX_PLATFORMS"] = "cpu"

import numpy as np

from bionetgen import _bionetgen_cpp as cpp
from bionetgen import jax_ode, jax_ssa

ROOT = Path(__file__).resolve().parents[2]
N0, K1, K2, T_END = 30, 0.3, 0.1, 3.0
BATCH, SEED, ALPHA = 8192, 20261119, 0.001
ALPHA_M = ALPHA / 3.0
DKW_ONE = math.sqrt(math.log(2.0 / ALPHA_M) / (2.0 * BATCH))
DKW_TWO = math.sqrt(2.0 * math.log(2.0 / ALPHA_M) / BATCH)
AVOGADRO = 6.02214076e23

MODEL = f"""begin model
begin parameters
k1 {K1}
k2 {K2}
end parameters
begin molecule types
A()
B()
C()
end molecule types
begin seed species
A() {N0}
B() 0
C() 0
end seed species
begin observables
Molecules CountA A()
Molecules CountB B()
Molecules CountC C()
end observables
begin reaction rules
A() -> B() k1
A() -> C() k2
end reaction rules
end model
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _law(k1, k2):
    total = k1 + k2
    p_a = math.exp(-total * T_END)
    return np.array([p_a, (k1 / total) * (1.0 - p_a), (k2 / total) * (1.0 - p_a)])


def _bcdf(p, grid):
    return np.array(
        [
            sum(
                math.comb(N0, i) * p**i * (1 - p) ** (N0 - i) for i in range(int(v) + 1)
            )
            for v in grid
        ]
    )


def _ecdf(samples, grid):
    return np.array([(samples <= v).mean() for v in grid])


def _revision() -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run() -> dict:
    import jax
    import jaxlib

    model = cpp.parse_string(MODEL)
    network = cpp.generate_network(model)
    flat = cpp.jax_ssa_flatten(model, network)

    jax_res = jax_ssa.simulate(
        model, network, batch_size=BATCH, t_end=T_END, n_steps=1, base_seed=SEED
    )
    jax_samples = np.asarray(jax_res["final_species"])
    native = cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=BATCH,
        t_end=T_END,
        n_steps=1,
        threads=1,
        base_seed=SEED,
    )
    native_samples = np.asarray(native["final_species"])

    p = _law(K1, K2)
    grid = np.arange(0, N0 + 1)
    marginals = {}
    all_ok = True
    for i, name in enumerate(("A", "B", "C")):
        exact = _bcdf(p[i], grid)
        empirical = _ecdf(jax_samples[:, i], grid)
        ks = float(np.max(np.abs(empirical - exact)))
        mean = float(jax_samples[:, i].mean())
        bound = 3.0 * math.sqrt(N0 * p[i] * (1 - p[i]) / BATCH)
        native_ks = float(np.max(np.abs(empirical - _ecdf(native_samples[:, i], grid))))
        ok = ks <= DKW_ONE and abs(mean - N0 * p[i]) <= bound and native_ks <= DKW_TWO
        all_ok = all_ok and bool(ok)
        marginals[name] = {
            "p": float(p[i]),
            "ks_analytic": ks,
            "dkw_one": DKW_ONE,
            "mean": mean,
            "expected_mean": float(N0 * p[i]),
            "mean_bound": bound,
            "ks_native": native_ks,
            "dkw_two": DKW_TWO,
            "passed": bool(ok),
        }

    wrong = _law(K2, K1)
    ks_wrong = float(
        np.max(np.abs(_ecdf(jax_samples[:, 1], grid) - _bcdf(wrong[1], grid)))
    )
    wrong_rejected = bool(ks_wrong > DKW_ONE)
    invariant = bool(np.all(jax_samples.sum(axis=1) == N0))

    # ODE units: analytic first-order decay of a declared-concentration seed.
    unit_model = cpp.parse_string(f"""begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", {AVOGADRO!r})
  begin units
    timeUnits = second
    substanceUnits = item
    volumeUnits = fL
    unit per_s = second^-1
  end units
  begin parameters
    k 0.5 [per_s]
  end parameters
  begin compartments
    cell 3 2 [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 1.0 [M]
  end seed species
  begin observables
    Molecules nA A()
  end observables
  begin reaction rules
    A() -> 0 k
  end reaction rules
end model
""")
    unit_net = cpp.generate_network(unit_model)
    unit_flat = cpp.jax_ode_flatten(unit_model, unit_net)
    unit_res = jax_ode.simulate_jax_ode(unit_model, t_end=2.0, n_steps=20)
    a0 = 1.0 * 2.0 * 1e-15 * AVOGADRO
    expected = a0 * np.exp(-0.5 * np.asarray(unit_res["time"]))
    unit_err = float(
        np.max(np.abs(np.asarray(unit_res["concentrations"])[:, 0] - expected))
    )
    unit_ok = bool(
        unit_err <= 5e-3 * a0
        and np.allclose(np.asarray(unit_flat["rate_constants"]), [0.5])
    )
    all_ok = all_ok and wrong_rejected and invariant and unit_ok

    return {
        "case": "jax_extended_installed_cpu",
        "revision": _revision(),
        "jax_version": jax.__version__,
        "jaxlib_version": jaxlib.__version__,
        "devices": [str(d) for d in jax.devices()],
        "native_extension_sha256": _sha256(Path(cpp.__file__)),
        "jax_ode_sha256": _sha256(ROOT / "python/bionetgen/jax_ode.py"),
        "jax_ssa_sha256": _sha256(ROOT / "python/bionetgen/jax_ssa.py"),
        "plan_sha256": _sha256(Path(__file__).with_name("PREDECLARED_PLAN.md")),
        "law": {
            "model": "A->B k1; A->C k2 (N0=30)",
            "seed": SEED,
            "batch_size": BATCH,
            "t_end": T_END,
            "alpha": ALPHA,
            "dkw_one": DKW_ONE,
            "dkw_two": DKW_TWO,
        },
        "flatten": {
            "num_species": flat["num_species"],
            "num_reactions": flat["num_reactions"],
            "rate_constants": [float(x) for x in flat["rate_constants"]],
        },
        "marginals": marginals,
        "wrong_law_control": {
            "law": "swapped k1/k2",
            "ks": ks_wrong,
            "rejected": wrong_rejected,
        },
        "invariants": {"count_conserved": invariant},
        "units": {
            "A0": a0,
            "max_abs_error": unit_err,
            "rate_constant": [float(x) for x in unit_flat["rate_constants"]],
            "passed": unit_ok,
        },
        "all_passed": bool(all_ok),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    result = run()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["all_passed"] else 1)
