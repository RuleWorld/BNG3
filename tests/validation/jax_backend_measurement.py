"""JAX backend performance and resource measurement qualification (#174).

Issue #174 ("G04: Publish current representative speed and memory baselines")
asks for representative speed and memory baselines on a fixed revision:
parse/compile/generate, ODE/SSA/NFsim, scans, cold/warm setup, peak memory and
allocations. It also requires independent semantic oracles, controlled A/A
timing, the exact environment and corpus, and retained no-win results.

This module measures that profile for the JAX backend family on a fixed,
generated corpus. The JAX backend is the candidate arm; the native engine is
the incumbent arm for the stages where the JAX backend has no route.

Rules that keep the numbers honest:

* Every timing carries an independent correctness control. The control is the
  closed-form law of the case, derived from the case parameters and not from
  anything the measured code produced. A timing whose correctness control
  failed is **not** recorded as a result.
* Every timed stage is measured by repeating the same arm (an A/A control).
  The spread of those repetitions is recorded. A stage whose spread exceeds
  the noise limit is not recorded as a result either, so a noisy host cannot
  be mistaken for a measurement.
* A comparison that does not show the candidate winning is recorded as
  ``NO-WIN``. It is a result, not a failure to hide.
* The environment, the corpus and the revision the measurement ran on are
  recorded with the numbers, so a reader can tell which machine produced
  them. The numbers themselves are machine-specific and are not a portable
  claim.
* Where the JAX backend provides no route (SSA, NFsim, parameter scans), the
  absence is recorded as an explicit boundary instead of being measured
  through a different backend and presented as a JAX capability.

The module is import-safe: it only touches ``bionetgen``, ``numpy`` and the
optional ``jax`` dependency when it runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np

from .campaign import STATUSES

try:  # The compiled extension is only required when the family actually runs.
    import bionetgen
except ImportError:  # pragma: no cover - exercised by the harness guard
    bionetgen = None

ISSUES = (174,)
ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- #
# Measurement policy
# --------------------------------------------------------------------------- #

# Repetitions of the same arm per timed stage. Their spread is the A/A
# control: one arm compared with itself, on the same host, in one session.
# Seven runs per arm is the repository's convention for an A/B measurement
# (tools/memory_allocs/README.md).
REPETITIONS = 7

# A timed stage is admissible only when the A/A spread stays inside the
# limit. The absolute floor keeps a sub-millisecond stage from failing on
# timer granularity alone.
AA_RELATIVE_LIMIT = 0.25
AA_ABSOLUTE_LIMIT_SECONDS = 0.001

# Iterations per timed repetition, chosen so that even the cheapest stage is
# measured over a window long enough to be meaningful.
INNER_ITERATIONS = {
    "parse": 100,
    "generate": 20,
    "native-ode": 10,
    "native-ssa": 20,
    "native-nfsim": 10,
    "native-scan": 2,
    "jax-compile": 1,
    "jax-compile-warm": 20,
    "jax-ode": 2,
    "setup-warm": 1,
}

# The stochastic stages are controlled by an ensemble against the closed-form
# law. The seed base, the run budget and the error band are recorded.
STOCHASTIC_RUNS = 32
STOCHASTIC_SEED_BASE = 20261020
STATISTICAL_SIGMA = 4.0

# The JAX backend runs in the configured JAX floating dtype (float32 unless
# JAX_ENABLE_X64 is set), so its comparisons use a float32-sized tolerance.
# The native engine integrates to its own solver tolerance.
JAX_RTOL = 2e-3
NATIVE_RTOL = 1e-6

# The corpus is fixed: the same generated cases, the same parameters and the
# same source text on every run. The digest of that description is recorded
# with the measurements.
CASE_SPECS = (
    {
        "id": "conversion-small",
        "model": "conversion",
        "rate": 0.2,
        "amount": 20.0,
        "t_end": 10.0,
        "n_steps": 100,
        "scan_rates": (0.1, 0.2, 0.4),
        # A first-order conversion is linear, so the mean of the stochastic
        # process is the closed-form law. The conserved quantity weights the
        # species so that the reaction conserves it.
        "linear": True,
        "conservation_weights": (1.0, 1.0),
    },
    {
        "id": "conversion-large",
        "model": "conversion",
        "rate": 0.05,
        "amount": 1000.0,
        "t_end": 20.0,
        "n_steps": 200,
        "scan_rates": (0.02, 0.05, 0.1),
        "linear": True,
        "conservation_weights": (1.0, 1.0),
    },
    {
        "id": "dimerization",
        "model": "dimerization",
        "rate": 0.01,
        "amount": 100.0,
        "t_end": 10.0,
        "n_steps": 100,
        "scan_rates": (0.005, 0.01, 0.02),
        # A dimerization has a nonlinear propensity, so the mean of the
        # stochastic process is not the closed-form law of the deterministic
        # system. Only the pathwise invariants are compared for this case.
        "linear": False,
        "conservation_weights": (1.0, 2.0),
    },
)

# The species of every corpus case, in network order. The law below is stated
# in the same order.
SPECIES = ("A()", "B()")

TIMED_STAGES = (
    "parse",
    "generate",
    "jax-compile",
    "jax-compile-warm",
    "jax-ode",
    "native-ode",
    "native-ssa",
    "native-nfsim",
    "native-scan",
    "setup-cold",
    "setup-warm",
)

# The allocation stage is a count, not a duration: it is measured once per
# repetition and recorded with its own identity.
ALLOCATION_STAGE = "allocations"

# The stages whose independent control is the closed-form law of the case.
# A wrong law voids the timing of exactly these stages.
LAW_CONTROLLED_STAGES = (
    "jax-ode",
    "native-ode",
    "native-scan",
    "setup-cold",
    "setup-warm",
)

CONVERSION_MODEL = """begin model
begin parameters
  k @RATE@
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() @AMOUNT@
  B() 0
end seed species
begin observables
  Molecules A A()
  Molecules B B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
"""

DIMERIZATION_MODEL = """begin model
begin parameters
  k @RATE@
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() @AMOUNT@
  B() 0
end seed species
begin observables
  Molecules A A()
  Molecules B B()
end observables
begin reaction rules
  A() + A() -> B() k
end reaction rules
end model
"""

# The cold-setup child measures the JAX backend's first-run cost in a fresh
# interpreter: the import, the parse, the network generation, the RHS
# compilation and the first integration.
COLD_SETUP_SCRIPT = '''"""Measure the JAX backend's cold setup in a fresh interpreter."""

import json
import sys
import time

start = time.perf_counter()
import jax
import jax.numpy as jnp

from bionetgen import _bionetgen_cpp as cpp
from bionetgen import jax_ode

import_seconds = time.perf_counter() - start

source, output, t_end, n_steps = sys.argv[1:5]
parse_start = time.perf_counter()
model = cpp.parse_file(source)
parse_seconds = time.perf_counter() - parse_start

generate_start = time.perf_counter()
network = cpp.generate_network(model)
generate_seconds = time.perf_counter() - generate_start

data = cpp.jax_ode_flatten(model, network)
state = jnp.asarray(data["initial_state"])

compile_start = time.perf_counter()
rhs = jax_ode.compile_rhs(model)
rhs(0.0, state)
compile_seconds = time.perf_counter() - compile_start

integrate_start = time.perf_counter()
result = jax_ode.simulate_jax_ode(model, t_end=float(t_end), n_steps=int(n_steps))
integrate_seconds = time.perf_counter() - integrate_start

payload = {
    "import_seconds": import_seconds,
    "parse_seconds": parse_seconds,
    "generate_seconds": generate_seconds,
    "compile_seconds": compile_seconds,
    "integrate_seconds": integrate_seconds,
    "total_seconds": time.perf_counter() - start,
    "final_state": [float(value) for value in result["concentrations"][-1]],
    "backend": jax.default_backend(),
    "package": __import__("bionetgen").__file__,
}
with open(output, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
'''


# --------------------------------------------------------------------------- #
# Corpus
# --------------------------------------------------------------------------- #


def _source(case):
    """Return the BNGL source of a corpus case."""
    template = CONVERSION_MODEL if case["model"] == "conversion" else DIMERIZATION_MODEL
    return template.replace("@RATE@", repr(float(case["rate"]))).replace(
        "@AMOUNT@", repr(float(case["amount"]))
    )


def cases():
    """Return the fixed, generated corpus of measurement cases."""
    result = []
    for spec in CASE_SPECS:
        case = dict(spec)
        case["scan_rates"] = list(spec["scan_rates"])
        case["bngl"] = _source(case)
        case["species"] = list(SPECIES)
        case["reactions"] = 1
        result.append(case)
    return result


def corpus_record():
    """Return the description of the corpus the measurements used."""
    return {
        "cases": [
            {
                "id": case["id"],
                "model": case["model"],
                "rate": case["rate"],
                "amount": case["amount"],
                "t_end": case["t_end"],
                "n_steps": case["n_steps"],
                "scan_rates": case["scan_rates"],
                "species": case["species"],
                "reactions": case["reactions"],
                "bngl_sha256": hashlib.sha256(case["bngl"].encode()).hexdigest(),
            }
            for case in cases()
        ],
        "repetitions": REPETITIONS,
        "inner_iterations": dict(INNER_ITERATIONS),
        "stochastic_runs": STOCHASTIC_RUNS,
        "stochastic_seed_base": STOCHASTIC_SEED_BASE,
        "statistical_sigma": STATISTICAL_SIGMA,
        "aa_relative_limit": AA_RELATIVE_LIMIT,
        "aa_absolute_limit_seconds": AA_ABSOLUTE_LIMIT_SECONDS,
    }


def corpus_digest():
    """Return the digest of the corpus description."""
    payload = json.dumps(corpus_record(), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def case_law(case, times):
    """Return the closed-form species amounts of a case, in network order.

    This is the independent expectation: it is derived from the case
    parameters, not from anything a measured route produced.
    """
    times = np.asarray(times, dtype=float)
    amount = float(case["amount"])
    rate = float(case["rate"])
    if case["model"] == "conversion":
        a = amount * np.exp(-rate * times)
        b = amount - a
    elif case["model"] == "dimerization":
        # The compiled coefficient of A() + A() carries the identical-reactant
        # factor 1/2, so dA/dt = -k A^2 and dB/dt = +k A^2 / 2.
        a = amount / (1.0 + rate * amount * times)
        b = 0.5 * (amount - a)
    else:  # pragma: no cover - protected by the static case table
        raise ValueError(f"unknown corpus model: {case['model']!r}")
    return np.column_stack([a, b])


def case_derivative(case, state):
    """Return the analytic derivative of a case at a state, in network order."""
    state = np.asarray(state, dtype=float)
    amount = float(case["amount"])
    rate = float(case["rate"])
    a = float(state[0])
    if case["model"] == "conversion":
        return np.array([-rate * a, rate * a], dtype=float)
    if case["model"] == "dimerization":
        return np.array([-rate * a * a, 0.5 * rate * a * a], dtype=float)
    raise ValueError(f"unknown corpus model: {case['model']!r}")  # pragma: no cover


# --------------------------------------------------------------------------- #
# Check identities
# --------------------------------------------------------------------------- #


def check_ids():
    """Declare the expected evidence identities independently of execution."""
    ids = [
        "jax-backend-measurement:family:environment-record",
        "jax-backend-measurement:family:jax-ssa-refusal",
        "jax-backend-measurement:family:jax-public-api-route-absence",
        "jax-backend-measurement:family:jax-family-route-absence",
    ]
    for case in cases():
        ids.append(f"jax-backend-measurement:{case['id']}:correctness-control")
        ids.append(f"jax-backend-measurement:{case['id']}:aa-control")
        ids.append(f"jax-backend-measurement:{case['id']}:ode-comparison")
        ids.append(f"jax-backend-measurement:{case['id']}:allocations-measurement")
        for stage in TIMED_STAGES:
            ids.append(f"jax-backend-measurement:{case['id']}:{stage}-timing")
    return ids


# --------------------------------------------------------------------------- #
# Row helpers
# --------------------------------------------------------------------------- #


def _row(check, status, detail, *, first_difference=None, artifact=None, kind=None):
    if kind is None:
        kind = {
            "PASS": "supported-execution",
            "FAIL": "supported-execution",
        }.get(status, "diagnostic-only")
    row = {
        "id": check,
        "check": check.rsplit(":", 1)[-1],
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "related_issues": list(ISSUES),
        "evidence_kind": kind,
        "supported_execution": status == "PASS" and kind == "supported-execution",
    }
    if artifact is not None:
        row["source_artifact"] = artifact.name
        row["source_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return row


def _boundary_row(check, status, detail, *, first_difference=None):
    """A recorded refusal proves a boundary, so it is never support evidence."""
    row = _row(check, status, detail, first_difference=first_difference)
    row["evidence_kind"] = "diagnostic-only"
    row["supported_execution"] = False
    return row


def _not_tested(check, detail, *, artifact=None):
    return _row(check, "NOT_TESTED", detail, artifact=artifact)


# --------------------------------------------------------------------------- #
# Measurement helpers
# --------------------------------------------------------------------------- #


def _within_limit(median, spread):
    """Decide whether a stage's A/A spread is inside the noise limit."""
    limit = max(AA_ABSOLUTE_LIMIT_SECONDS, AA_RELATIVE_LIMIT * median)
    return spread * median <= limit


def _measure(operation, stage):
    """Time one arm of a stage and return its A/A control."""
    inner = INNER_ITERATIONS[stage]
    samples = []
    for _ in range(REPETITIONS):
        start = time.perf_counter()
        for _ in range(inner):
            operation()
        samples.append(time.perf_counter() - start)
    median = statistics.median(samples)
    # The interquartile spread is the repeatability statistic: the median and
    # the IQR are the numbers a reader can compare, and a single preempted
    # repetition does not turn a repeatable stage into an unusable one. The
    # full range is recorded next to it.
    lower, upper = np.percentile(samples, [25.0, 75.0])
    spread = ((upper - lower) / median) if median > 0 else float("inf")
    return {
        "samples": samples,
        "inner": inner,
        "median": median,
        "per_operation": median / inner,
        "spread": spread,
        "absolute_spread": float(upper - lower),
        "range_spread": (
            ((max(samples) - min(samples)) / median) if median > 0 else float("inf")
        ),
        "admissible": _within_limit(median, spread),
    }


def _compare(observed, expected, *, rtol, atol):
    """Compare two arrays; return (ok, first difference)."""
    observed = np.asarray(observed, dtype=float)
    expected = np.asarray(expected, dtype=float)
    if observed.shape != expected.shape:
        return False, {
            "field": "shape",
            "expected": list(expected.shape),
            "observed": list(observed.shape),
        }
    if not np.all(np.isfinite(observed)):
        index = int(np.argmax(~np.isfinite(observed)))
        return False, {"field": "finite", "index": index}
    deviation = np.abs(observed - expected)
    tolerance = atol + rtol * np.abs(expected)
    excess = (deviation - tolerance).ravel()
    worst = int(np.argmax(excess))
    if excess[worst] > 0:
        return False, {
            "field": "values",
            "index": [int(value) for value in np.unravel_index(worst, observed.shape)],
            "expected": float(expected.ravel()[worst]),
            "observed": float(observed.ravel()[worst]),
            "deviation": float(deviation.ravel()[worst]),
            "tolerance": float(tolerance.ravel()[worst]),
        }
    return True, None


def _correctness(ok, detail, difference=None):
    return {"ok": bool(ok), "detail": detail, "difference": difference}


def _describe(measurement):
    """Return the human-readable description of a measurement."""
    return (
        f"{len(measurement['samples'])} repetitions of "
        f"{measurement['inner']} iteration(s); "
        f"median {measurement['median'] * 1000.0:.3f} ms per repetition "
        f"({measurement['per_operation'] * 1000.0:.4f} ms per operation); "
        f"A/A spread (interquartile range) {measurement['spread'] * 100.0:.1f}% "
        f"of the median ({measurement['absolute_spread'] * 1000.0:.3f} ms), "
        f"full range {measurement['range_spread'] * 100.0:.1f}%"
    )


# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #


def _git(*args):
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def environment_record():
    """Return the environment, corpus and revision the measurement ran on."""
    import jax

    try:
        import jaxlib

        jaxlib_version = jaxlib.__version__
    except ImportError:  # pragma: no cover - jaxlib ships with jax
        jaxlib_version = None
    package = Path(bionetgen.__file__).resolve() if bionetgen is not None else None
    status = _git("status", "--porcelain")
    try:
        load_average = [round(value, 2) for value in os.getloadavg()]
    except (AttributeError, OSError):  # pragma: no cover - platform specific
        load_average = None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "jax": jax.__version__,
        "jaxlib": jaxlib_version,
        "backend": jax.default_backend(),
        "devices": [str(device) for device in jax.devices()],
        "x64": bool(jax.config.read("jax_enable_x64")),
        "jax_platforms": os.environ.get("JAX_PLATFORMS"),
        "load_average": load_average,
        "package": str(package) if package else None,
        "package_sha256": (
            hashlib.sha256(package.read_bytes()).hexdigest() if package else None
        ),
        "revision": _git("rev-parse", "HEAD"),
        "dirty": bool(status) if status is not None else None,
        "corpus_sha256": corpus_digest(),
    }


# --------------------------------------------------------------------------- #
# Correctness controls
# --------------------------------------------------------------------------- #


def _amount_value(seed):
    """Return a seed species' amount as a number when it is a literal."""
    try:
        return float(str(seed.amount))
    except (TypeError, ValueError):
        return str(seed.amount)


def _check_parsed_model(model, case):
    """The parsed model must carry the case's declared semantics."""
    expected = {
        "parameters": {"k": float(case["rate"])},
        "molecule_types": ["A", "B"],
        "seed_species": [("A()", case["amount"]), ("B()", 0.0)],
        "reaction_rules": 1,
    }
    parameters = {p.name: p.value for p in model.parameters}
    if parameters != expected["parameters"]:
        return _correctness(
            False,
            f"the parsed parameters {parameters} differ from {expected['parameters']}",
            {"field": "parameters", "observed": parameters},
        )
    molecule_types = [m.name for m in model.molecule_types]
    if molecule_types != expected["molecule_types"]:
        return _correctness(
            False,
            f"the parsed molecule types {molecule_types} differ from "
            f"{expected['molecule_types']}",
            {"field": "molecule_types", "observed": molecule_types},
        )
    seeds = [(s.pattern, _amount_value(s)) for s in model.seed_species]
    if seeds != expected["seed_species"]:
        return _correctness(
            False,
            f"the parsed seed species {seeds} differ from {expected['seed_species']}",
            {"field": "seed_species", "observed": seeds},
        )
    rules = len(model.reaction_rules)
    if rules != expected["reaction_rules"]:
        return _correctness(
            False,
            f"the parsed reaction rule count {rules} differs from "
            f"{expected['reaction_rules']}",
            {"field": "reaction_rules", "observed": rules},
        )
    return _correctness(
        True,
        "the parsed model carries the case's parameters, molecule types, seed "
        "species and reaction rule",
    )


def _check_network(network, case):
    """The generated network must be the network the law describes."""
    species = list(network.species_names)
    if species != case["species"]:
        return _correctness(
            False,
            f"the generated species {species} differ from {case['species']}",
            {"field": "species", "observed": species},
        )
    reactions = int(network.num_reactions)
    if reactions != case["reactions"]:
        return _correctness(
            False,
            f"the generated reaction count {reactions} differs from "
            f"{case['reactions']}",
            {"field": "reactions", "observed": reactions},
        )
    return _correctness(
        True,
        f"the generated network carries {len(species)} species and "
        f"{reactions} reaction(s), as the case declares",
    )


def _check_trajectory(observed, case, times, *, rtol, label):
    """A trajectory must reproduce the closed-form law of the case."""
    expected = case_law(case, times)
    ok, difference = _compare(
        observed, expected, rtol=rtol, atol=rtol * float(case["amount"])
    )
    if ok:
        return _correctness(
            True,
            f"the {label} trajectory reproduces the closed-form law of the case "
            f"(rtol {rtol})",
        )
    return _correctness(
        False,
        f"the {label} trajectory does not reproduce the closed-form law of the "
        f"case (rtol {rtol})",
        difference,
    )


def _check_derivative(observed, case, state):
    """A compiled right-hand side must equal the analytic derivative."""
    expected = case_derivative(case, state)
    ok, difference = _compare(
        observed, expected, rtol=NATIVE_RTOL, atol=NATIVE_RTOL * float(case["amount"])
    )
    if ok:
        return _correctness(
            True,
            "the compiled right-hand side equals the analytic derivative of the "
            "case",
        )
    return _correctness(
        False,
        "the compiled right-hand side differs from the analytic derivative of "
        "the case",
        difference,
    )


def _check_ensemble(samples, case, *, label):
    """Check a stochastic ensemble against the closed-form law of the case.

    The claim is limited to the marginal mean of the recorded observable: the
    ensemble mean must fall inside the recorded error band around the
    closed-form law. A case with a nonlinear propensity is excluded, because
    the mean of the stochastic process is then not the law of the
    deterministic system; such a case is controlled by its pathwise
    invariants instead.
    """
    values = np.asarray(samples, dtype=float)
    expected = float(case_law(case, [case["t_end"]])[0][0])
    mean = float(values.mean())
    deviation = float(values.std(ddof=1)) if values.size > 1 else 0.0
    standard_error = deviation / np.sqrt(values.size) if values.size else 0.0
    band = STATISTICAL_SIGMA * standard_error
    difference = mean - expected
    if band > 0 and abs(difference) > band:
        return _correctness(
            False,
            f"the {label} ensemble mean {mean:.6g} differs from the closed-form "
            f"law {expected:.6g} by more than the {STATISTICAL_SIGMA}-sigma band "
            f"{band:.6g}",
            {
                "field": "ensemble-mean",
                "expected": expected,
                "observed": mean,
                "band": band,
                "runs": int(values.size),
            },
        )
    return _correctness(
        True,
        f"the {label} ensemble mean {mean:.6g} is inside the "
        f"{STATISTICAL_SIGMA}-sigma band {band:.6g} around the closed-form law "
        f"{expected:.6g} ({int(values.size)} recorded runs)",
    )


def _check_nonlinear_ensemble(samples, case, *, label):
    """Record why a nonlinear case is not compared with the deterministic law."""
    values = np.asarray(samples, dtype=float)
    expected = float(case_law(case, [case["t_end"]])[0][0])
    mean = float(values.mean())
    return _correctness(
        True,
        f"the {label} ensemble mean {mean:.6g} is not compared with the "
        f"closed-form law {expected:.6g}: the case has a nonlinear propensity, "
        "so the mean of the stochastic process is not the law of the "
        "deterministic system; this stage is controlled by its pathwise "
        "invariants instead",
    )


def _check_conservation(final_states, case):
    """Every stochastic run must conserve the case's weighted total."""
    weights = np.asarray(case["conservation_weights"], dtype=float)
    totals = np.asarray(final_states, dtype=float) @ weights
    expected = float(case["amount"])
    worst = float(np.max(np.abs(totals - expected))) if totals.size else 0.0
    if worst > 1e-9 * max(1.0, expected):
        return _correctness(
            False,
            f"a stochastic run did not conserve the weighted total amount: the "
            f"largest deviation was {worst:.6g}",
            {"field": "conservation", "deviation": worst},
        )
    return _correctness(
        True,
        "every stochastic run conserved the weighted total amount "
        f"{expected:.6g} (weights {list(weights)})",
    )


def _check_monotonicity(trajectories, case):
    """The reactant must not increase and the product must not decrease."""
    reactant = []
    product = []
    for trajectory in trajectories:
        values = np.asarray(trajectory, dtype=float)
        reactant.append(float(np.max(np.diff(values[:, 0]))))
        product.append(float(np.min(np.diff(values[:, 1]))))
    worst_reactant = max(reactant) if reactant else 0.0
    worst_product = min(product) if product else 0.0
    if worst_reactant > 1e-9 or worst_product < -1e-9:
        return _correctness(
            False,
            "a stochastic run was not monotone: the reactant rose by "
            f"{worst_reactant:.6g} and the product fell by {abs(worst_product):.6g}",
            {
                "field": "monotonicity",
                "reactant_increase": worst_reactant,
                "product_decrease": abs(worst_product),
            },
        )
    return _correctness(
        True, "every stochastic run was monotone in the reactant and the product"
    )


# --------------------------------------------------------------------------- #
# The stages
# --------------------------------------------------------------------------- #


def _cold_setup_samples(case, source, directory, count=3):
    """Measure the JAX backend's cold setup in fresh interpreters."""
    script = directory / "cold_setup_child.py"
    script.write_text(COLD_SETUP_SCRIPT, encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(path for path in sys.path if path)
    samples = []
    for index in range(count):
        output = directory / f"cold-setup-{case['id']}-{index}.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                str(source),
                str(output),
                str(case["t_end"]),
                str(case["n_steps"]),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            env=environment,
        )
        if completed.returncode != 0 or not output.is_file():
            raise RuntimeError(
                "the cold-setup child failed: "
                + (completed.stderr.strip()[-2000:] or f"exit {completed.returncode}")
            )
        samples.append(json.loads(output.read_text(encoding="utf-8")))
    return samples


def _measure_case(case, directory):
    """Measure every stage of one corpus case."""
    import jax.numpy as jnp

    from bionetgen import _bionetgen_cpp as cpp
    from bionetgen import jax_ode
    from bionetgen.model import BioNetGenModel
    from bionetgen.scan import parameter_scan

    source = directory / f"{case['id']}.bngl"
    source.write_text(case["bngl"], encoding="utf-8")

    model = cpp.parse_string(case["bngl"])
    network = cpp.generate_network(model)
    times = np.linspace(0.0, case["t_end"], case["n_steps"] + 1)
    data = cpp.jax_ode_flatten(model, network)
    state = data["initial_state"]
    stages = {}

    # --- parse ---------------------------------------------------------- #
    stages["parse"] = {
        "measurement": _measure(lambda: cpp.parse_file(str(source)), "parse"),
        "correctness": _check_parsed_model(cpp.parse_string(case["bngl"]), case),
    }

    # --- generate ------------------------------------------------------- #
    stages["generate"] = {
        "measurement": _measure(lambda: cpp.generate_network(model), "generate"),
        "correctness": _check_network(network, case),
    }

    # --- JAX compilation ------------------------------------------------ #
    def compile_once():
        rhs = jax_ode.compile_rhs(model)
        rhs(0.0, jnp.asarray(state))

    stages["jax-compile"] = {
        "measurement": _measure(compile_once, "jax-compile"),
        "correctness": _check_derivative(
            np.asarray(jax_ode.compile_rhs(model)(0.0, jnp.asarray(state))),
            case,
            state,
        ),
    }

    compiled = jax_ode.compile_rhs(model)
    compiled_state = jnp.asarray(state)
    compiled(0.0, compiled_state)

    def compile_warm():
        compiled(0.0, compiled_state)

    stages["jax-compile-warm"] = {
        "measurement": _measure(compile_warm, "jax-compile-warm"),
        "correctness": _check_derivative(
            np.asarray(compiled(0.0, compiled_state)), case, state
        ),
    }

    # --- JAX ODE -------------------------------------------------------- #
    def jax_ode_once():
        jax_ode.simulate_jax_ode(model, t_end=case["t_end"], n_steps=case["n_steps"])

    stages["jax-ode"] = {
        "measurement": _measure(jax_ode_once, "jax-ode"),
        "correctness": _check_trajectory(
            np.asarray(
                jax_ode.simulate_jax_ode(
                    model, t_end=case["t_end"], n_steps=case["n_steps"]
                )["concentrations"]
            ),
            case,
            times,
            rtol=JAX_RTOL,
            label="JAX ODE",
        ),
    }

    # --- native ODE ----------------------------------------------------- #
    def native_ode_once():
        cpp.simulate_ode(model, network, t_end=case["t_end"], n_steps=case["n_steps"])

    stages["native-ode"] = {
        "measurement": _measure(native_ode_once, "native-ode"),
        "correctness": _check_trajectory(
            np.asarray(
                cpp.simulate_ode(
                    model, network, t_end=case["t_end"], n_steps=case["n_steps"]
                )["concentrations"]
            ),
            case,
            times,
            rtol=NATIVE_RTOL,
            label="native ODE",
        ),
    }

    # --- native SSA ----------------------------------------------------- #
    def native_ssa_once():
        cpp.simulate_ssa(
            model,
            network,
            t_end=case["t_end"],
            n_steps=case["n_steps"],
            seed=STOCHASTIC_SEED_BASE,
        )

    ssa_final = []
    ssa_totals = []
    ssa_trajectories = []
    for index in range(STOCHASTIC_RUNS):
        result = cpp.simulate_ssa(
            model,
            network,
            t_end=case["t_end"],
            n_steps=case["n_steps"],
            seed=STOCHASTIC_SEED_BASE + index,
        )
        concentrations = np.asarray(result["concentrations"])
        ssa_final.append(float(concentrations[-1][0]))
        ssa_totals.append(concentrations[-1].tolist())
        ssa_trajectories.append(concentrations)
    mean_control = (
        _check_ensemble(ssa_final, case, label="native SSA")
        if case["linear"]
        else _check_nonlinear_ensemble(ssa_final, case, label="native SSA")
    )
    stages["native-ssa"] = {
        "measurement": _measure(native_ssa_once, "native-ssa"),
        "correctness": _combine(
            mean_control,
            _combine(
                _check_conservation(ssa_totals, case),
                _check_monotonicity(ssa_trajectories, case),
            ),
        ),
    }

    # --- native NFsim --------------------------------------------------- #
    def native_nfsim_once():
        cpp.simulate_nf(
            model,
            t_end=case["t_end"],
            n_steps=case["n_steps"],
            seed=STOCHASTIC_SEED_BASE,
        )

    nf_final = []
    nf_totals = []
    nf_trajectories = []
    nf_path = None
    for index in range(STOCHASTIC_RUNS):
        result = cpp.simulate_nf(
            model,
            t_end=case["t_end"],
            n_steps=case["n_steps"],
            seed=STOCHASTIC_SEED_BASE + index,
        )
        nf_path = result.get("construction_path", nf_path)
        observable_a = np.asarray(result["observables"]["A"], dtype=float)
        observable_b = np.asarray(result["observables"]["B"], dtype=float)
        nf_final.append(float(observable_a[-1]))
        nf_totals.append([float(observable_a[-1]), float(observable_b[-1])])
        nf_trajectories.append(np.column_stack([observable_a, observable_b]))
    mean_control = (
        _check_ensemble(nf_final, case, label="native NFsim")
        if case["linear"]
        else _check_nonlinear_ensemble(nf_final, case, label="native NFsim")
    )
    stages["native-nfsim"] = {
        "measurement": _measure(native_nfsim_once, "native-nfsim"),
        "correctness": _combine(
            mean_control,
            _combine(
                _check_conservation(nf_totals, case),
                _check_monotonicity(nf_trajectories, case),
            ),
        ),
        "detail": f"the NFsim stage ran through the {nf_path!r} construction path",
    }

    # --- native parameter scan ------------------------------------------ #
    public_model = BioNetGenModel(model)
    scan_rates = list(case["scan_rates"])

    def native_scan_once():
        parameter_scan(
            public_model,
            "k",
            values=scan_rates,
            method="ode",
            t_end=case["t_end"],
            n_steps=case["n_steps"],
        )

    scan_result = parameter_scan(
        public_model,
        "k",
        values=scan_rates,
        method="ode",
        t_end=case["t_end"],
        n_steps=case["n_steps"],
    )
    scan_observed = np.asarray(scan_result.final("A"), dtype=float)
    scan_expected = np.asarray(
        [
            float(case_law(dict(case, rate=rate), [case["t_end"]])[0][0])
            for rate in scan_rates
        ],
        dtype=float,
    )
    scan_ok, scan_difference = _compare(
        scan_observed,
        scan_expected,
        rtol=NATIVE_RTOL,
        atol=NATIVE_RTOL * float(case["amount"]),
    )
    stages["native-scan"] = {
        "measurement": _measure(native_scan_once, "native-scan"),
        "correctness": _correctness(
            scan_ok,
            (
                "the scanned observable reproduces the closed-form law at every "
                "scanned rate"
                if scan_ok
                else "the scanned observable does not reproduce the closed-form law "
                "at every scanned rate"
            ),
            scan_difference,
        ),
    }

    # --- cold and warm setup -------------------------------------------- #
    cold_samples = _cold_setup_samples(case, source, directory)
    cold_totals = [float(sample["total_seconds"]) for sample in cold_samples]
    cold_median = statistics.median(cold_totals)
    cold_lower, cold_upper = np.percentile(cold_totals, [25.0, 75.0])
    cold_spread = (
        (cold_upper - cold_lower) / cold_median if cold_median else float("inf")
    )
    stages["setup-cold"] = {
        "measurement": {
            "samples": cold_totals,
            "inner": 1,
            "median": cold_median,
            "per_operation": cold_median,
            "spread": cold_spread,
            "absolute_spread": float(cold_upper - cold_lower),
            "range_spread": (
                (max(cold_totals) - min(cold_totals)) / cold_median
                if cold_median
                else float("inf")
            ),
            "admissible": _within_limit(cold_median, cold_spread),
        },
        "correctness": _check_trajectory(
            np.asarray([cold_samples[-1]["final_state"]], dtype=float),
            case,
            [case["t_end"]],
            rtol=JAX_RTOL,
            label="cold-setup",
        ),
        "detail": "the fresh interpreter imported the backend in "
        f"{cold_samples[-1]['import_seconds'] * 1000.0:.1f} ms, parsed in "
        f"{cold_samples[-1]['parse_seconds'] * 1000.0:.1f} ms, generated the "
        f"network in {cold_samples[-1]['generate_seconds'] * 1000.0:.1f} ms, "
        f"compiled in {cold_samples[-1]['compile_seconds'] * 1000.0:.1f} ms and "
        f"integrated in {cold_samples[-1]['integrate_seconds'] * 1000.0:.1f} ms",
    }

    def setup_warm_once():
        rhs = jax_ode.compile_rhs(model)
        rhs(0.0, jax_ode.jnp.asarray(state))
        jax_ode.simulate_jax_ode(model, t_end=case["t_end"], n_steps=case["n_steps"])

    stages["setup-warm"] = {
        "measurement": _measure(setup_warm_once, "setup-warm"),
        "correctness": _check_trajectory(
            np.asarray(
                jax_ode.simulate_jax_ode(
                    model, t_end=case["t_end"], n_steps=case["n_steps"]
                )["concentrations"]
            ),
            case,
            times,
            rtol=JAX_RTOL,
            label="warm-setup",
        ),
    }

    # --- allocations ----------------------------------------------------- #
    tracemalloc.start()
    allocation_start = tracemalloc.get_traced_memory()
    allocation_result = jax_ode.simulate_jax_ode(
        model, t_end=case["t_end"], n_steps=case["n_steps"]
    )
    allocation_peak, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    device_memory = _device_memory()
    stages[ALLOCATION_STAGE] = {
        "measurement": {
            "samples": [float(allocation_peak - allocation_start[0])],
            "inner": 1,
            "median": float(allocation_peak - allocation_start[0]),
            "per_operation": float(allocation_peak - allocation_start[0]),
            "spread": 0.0,
            "absolute_spread": 0.0,
            "range_spread": 0.0,
            "admissible": True,
        },
        "correctness": _check_trajectory(
            np.asarray(allocation_result["concentrations"]),
            case,
            times,
            rtol=JAX_RTOL,
            label="allocation-measured",
        ),
        "detail": "the JAX ODE stage peaked at "
        f"{allocation_peak} Python-traced bytes (baseline "
        f"{allocation_start[0]} bytes) with a process peak resident set of "
        f"{_peak_resident_bytes()} bytes; the device reported {device_memory}",
    }

    return stages, source


def _combine(first, second):
    """Combine two correctness controls; both must hold."""
    if first["ok"] and second["ok"]:
        return _correctness(True, f"{first['detail']}; {second['detail']}")
    failed = first if not first["ok"] else second
    return _correctness(
        False, f"{first['detail']}; {second['detail']}", failed["difference"]
    )


def _peak_resident_bytes():
    """Return the process' peak resident set size in bytes, when available."""
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:  # pragma: no cover - the limit is platform specific
        return "unavailable"
    # Linux reports kilobytes, the BSDs and macOS report bytes.
    return int(usage) if sys.platform == "darwin" else int(usage) * 1024


def _device_memory():
    """Return the accelerator memory statistics, when the device reports them."""
    try:
        import jax

        for device in jax.devices():
            reported = device.memory_stats()
            if reported:
                return {
                    "device": str(device),
                    "peak_bytes_in_use": reported.get("peak_bytes_in_use"),
                    "bytes_in_use": reported.get("bytes_in_use"),
                }
    except Exception:  # pragma: no cover - device statistics are optional
        pass
    return "unavailable"


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #


def _timing_row(case, stage, stage_result, artifact):
    check = f"jax-backend-measurement:{case['id']}:{stage}-timing"
    measurement = stage_result["measurement"]
    correctness = stage_result["correctness"]
    if not correctness["ok"]:
        row = _not_tested(
            check,
            "the independent correctness control failed, so this timing is not "
            f"recorded as a result: {correctness['detail']}",
            artifact=artifact,
        )
        row["first_difference"] = correctness["difference"]
        return row
    if not measurement["admissible"]:
        return _not_tested(
            check,
            "the A/A control spread "
            f"({measurement['spread'] * 100.0:.1f}% of the median) exceeds the "
            f"{AA_RELATIVE_LIMIT * 100.0:.0f}% noise limit of this host, so this "
            "timing is not recorded as a result",
            artifact=artifact,
        )
    detail = f"{stage}: {_describe(measurement)}; correctness: {correctness['detail']}"
    if stage_result.get("detail"):
        detail = f"{detail}; {stage_result['detail']}"
    return _row(check, "PASS", detail, artifact=artifact)


def _allocation_row(case, stage_result, artifact):
    """The allocation stage is a count, not a duration."""
    check = f"jax-backend-measurement:{case['id']}:allocations-measurement"
    correctness = stage_result["correctness"]
    if not correctness["ok"]:
        row = _not_tested(
            check,
            "the independent correctness control failed, so this measurement is "
            f"not recorded as a result: {correctness['detail']}",
            artifact=artifact,
        )
        row["first_difference"] = correctness["difference"]
        return row
    measurement = stage_result["measurement"]
    detail = (
        f"allocations: {measurement['median']:.0f} Python-traced bytes at the "
        f"peak of the JAX ODE stage; {stage_result.get('detail', '')}; "
        f"correctness: {correctness['detail']}"
    )
    return _row(check, "PASS", detail, artifact=artifact)


def _correctness_row(case, stages, artifact=None):
    check = f"jax-backend-measurement:{case['id']}:correctness-control"
    failed = [
        (name, stage["correctness"])
        for name, stage in stages.items()
        if not stage["correctness"]["ok"]
    ]
    if failed:
        name, correctness = failed[0]
        return _row(
            check,
            "FAIL",
            "the independent closed-form control failed for "
            f"{len(failed)} of {len(stages)} timed stages; the first failure is "
            f"{name}: {correctness['detail']}",
            first_difference=correctness["difference"],
            artifact=artifact,
        )
    detail = "; ".join(
        f"{name}: {stage['correctness']['detail']}" for name, stage in stages.items()
    )
    return _row(
        check,
        "PASS",
        "the independent closed-form control holds for every timed stage "
        f"({detail})",
        artifact=artifact,
    )


def _aa_row(case, stages, artifact=None):
    check = f"jax-backend-measurement:{case['id']}:aa-control"
    spreads = {
        name: stages[name]["measurement"]["spread"]
        for name in TIMED_STAGES
        if name in stages
    }
    worst = max(spreads, key=lambda name: spreads[name])
    noisy = [
        name
        for name in TIMED_STAGES
        if name in stages and not stages[name]["measurement"]["admissible"]
    ]
    summary = ", ".join(
        f"{name} {spreads[name] * 100.0:.1f}%" for name in sorted(spreads)
    )
    if noisy:
        return _row(
            check,
            "FAIL",
            "the A/A control measured the same arm "
            f"{REPETITIONS} times per stage and found a spread above the "
            f"{AA_RELATIVE_LIMIT * 100.0:.0f}% limit for {', '.join(sorted(noisy))} "
            f"(worst: {worst} {spreads[worst] * 100.0:.1f}%); the affected "
            "timings are not recorded as results. This is a host-noise "
            f"observation, not a product failure. Spreads: {summary}",
            artifact=artifact,
        )
    return _row(
        check,
        "PASS",
        "the A/A control measured the same arm "
        f"{REPETITIONS} times per stage; every spread is inside the "
        f"{AA_RELATIVE_LIMIT * 100.0:.0f}% limit (worst: {worst} "
        f"{spreads[worst] * 100.0:.1f}%). Spreads: {summary}",
        artifact=artifact,
    )


def _comparison_row(case, stages, artifact=None):
    check = f"jax-backend-measurement:{case['id']}:ode-comparison"
    jax_stage = stages.get("jax-ode")
    native_stage = stages.get("native-ode")
    cold_stage = stages.get("setup-cold")
    for name, stage in (("jax-ode", jax_stage), ("native-ode", native_stage)):
        if stage is None or not stage["measurement"]["admissible"]:
            return _not_tested(
                check,
                f"the {name} stage is not an admissible measurement, so no "
                "comparison is recorded",
                artifact=artifact,
            )
        if not stage["correctness"]["ok"]:
            return _not_tested(
                check,
                f"the {name} stage failed its independent correctness control, "
                "so no comparison is recorded",
                artifact=artifact,
            )
    jax_seconds = jax_stage["measurement"]["median"]
    native_seconds = native_stage["measurement"]["median"]
    ratio = native_seconds / jax_seconds if jax_seconds else float("inf")
    verdict = "JAX-WIN" if jax_seconds < native_seconds else "NO-WIN"
    detail = (
        f"{verdict}: on this corpus the JAX backend's ODE stage took "
        f"{jax_seconds * 1000.0:.3f} ms and the native engine's took "
        f"{native_seconds * 1000.0:.3f} ms (native/JAX ratio {ratio:.3f})"
    )
    if cold_stage is not None and cold_stage["measurement"]["admissible"]:
        detail += (
            "; including the cold setup "
            f"({cold_stage['measurement']['median'] * 1000.0:.1f} ms in a "
            "fresh interpreter) the JAX backend's first-run cost is "
            f"{cold_stage['measurement']['median'] * 1000.0:.1f} ms against "
            f"{native_seconds * 1000.0:.3f} ms"
        )
    if verdict == "NO-WIN":
        detail += (
            "; the no-win result is recorded as measured and is not a failure "
            "to hide"
        )
    return _row(check, "PASS", detail, artifact=artifact)


def _boundary_rows(model, network):
    """Record the routes the JAX backend does not provide."""
    rows = []
    from bionetgen import jax_ode, jax_ssa

    refusal = "jax-backend-measurement:family:jax-ssa-refusal"
    try:
        jax_ssa.simulate(model, network, batch_size=1, t_end=1.0, base_seed=1)
    except NotImplementedError as exc:
        rows.append(
            _boundary_row(
                refusal,
                "PASS",
                "the JAX SSA entry point refuses explicitly, so no JAX SSA "
                f"timing is claimed: {exc}",
            )
        )
    except Exception as exc:
        rows.append(
            _boundary_row(
                refusal,
                "FAIL",
                "the JAX SSA entry point failed with an unexpected error "
                f"instead of refusing: {type(exc).__name__}: {exc}",
                first_difference={"field": "jax-ssa", "exception": type(exc).__name__},
            )
        )
    else:
        rows.append(
            _boundary_row(
                refusal,
                "FAIL",
                "the JAX SSA entry point returned without refusing; the JAX "
                "backend now provides an SSA route and this boundary check "
                "must be updated",
                first_difference={"field": "jax-ssa"},
            )
        )

    public_route = "jax-backend-measurement:family:jax-public-api-route-absence"
    from bionetgen.model import BioNetGenModel

    try:
        BioNetGenModel(model).simulate(method="jax", t_end=1.0, n_steps=1)
    except ValueError as exc:
        rows.append(
            _boundary_row(
                public_route,
                "PASS",
                "the public simulate() API rejects method='jax', so the JAX "
                f"backend is not reachable through it: {exc}",
            )
        )
    except Exception as exc:
        rows.append(
            _boundary_row(
                public_route,
                "FAIL",
                "the public simulate() API failed with an unexpected error "
                f"instead of rejecting method='jax': {type(exc).__name__}: {exc}",
                first_difference={
                    "field": "jax-method",
                    "exception": type(exc).__name__,
                },
            )
        )
    else:
        rows.append(
            _boundary_row(
                public_route,
                "FAIL",
                "the public simulate() API accepted method='jax'; the JAX "
                "backend is now reachable through the public API and this "
                "boundary check must be updated",
                first_difference={"field": "jax-method"},
            )
        )

    family_route = "jax-backend-measurement:family:jax-family-route-absence"
    public_names = sorted(set(jax_ode.__all__) | set(jax_ssa.__all__))
    unwanted = [
        name for name in public_names if "nf" in name.lower() or "scan" in name.lower()
    ]
    if unwanted:
        rows.append(
            _boundary_row(
                family_route,
                "FAIL",
                "the JAX family's public API now declares "
                f"{unwanted}; the measured stages would no longer describe the "
                "whole JAX surface",
                first_difference={"field": "jax-public-api", "observed": unwanted},
            )
        )
    else:
        rows.append(
            _boundary_row(
                family_route,
                "PASS",
                "the JAX family's public API declares "
                f"{public_names} and no NFsim or parameter-scan route, so the "
                "measured NFsim and scan stages belong to the native engine "
                "arm and are recorded as such",
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Worker entry points
# --------------------------------------------------------------------------- #


def run_worker(directory):
    """Run the measurement family and return its evidence rows."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if bionetgen is None:
        return [
            _not_tested(check, "the bionetgen package is unavailable")
            for check in check_ids()
        ]
    try:
        import jax  # noqa: F401
    except ImportError as exc:
        return [
            _not_tested(
                check,
                "the JAX backend is unavailable in this environment: " f"{exc}",
            )
            for check in check_ids()
        ]

    rows = []
    environment = environment_record()
    (directory / "environment.json").write_text(
        json.dumps(environment, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "corpus.json").write_text(
        json.dumps(corpus_record(), indent=2) + "\n", encoding="utf-8"
    )

    environment_check = "jax-backend-measurement:family:environment-record"
    if not environment["revision"]:
        rows.append(
            _not_tested(
                environment_check,
                "the revision the measurement ran on could not be determined",
            )
        )
    else:
        rows.append(
            _row(
                environment_check,
                "PASS",
                "measured on revision "
                f"{environment['revision']} (dirty: {environment['dirty']}) with "
                f"corpus {environment['corpus_sha256']}; environment: "
                f"{environment['platform']} / {environment['machine']}, Python "
                f"{environment['python']}, JAX {environment['jax']} "
                f"(jaxlib {environment['jaxlib']}) on backend "
                f"{environment['backend']} with devices "
                f"{environment['devices']}, x64={environment['x64']}, "
                f"JAX_PLATFORMS={environment['jax_platforms']!r}, host load "
                f"average {environment['load_average']}; the measured "
                "numbers are specific to this machine and revision",
            )
        )

    from bionetgen import _bionetgen_cpp as cpp

    model = cpp.parse_string(cases()[0]["bngl"])
    network = cpp.generate_network(model)
    rows.extend(_boundary_rows(model, network))

    _warm_up_jax()

    for case in cases():
        stages, source = _measure_case(case, directory)
        rows.append(_correctness_row(case, stages, source))
        rows.append(_aa_row(case, stages, source))
        rows.append(_comparison_row(case, stages, source))
        rows.append(_allocation_row(case, stages[ALLOCATION_STAGE], source))
        for stage in TIMED_STAGES:
            rows.append(_timing_row(case, stage, stages[stage], source))

    produced = {row["id"] for row in rows}
    for check in check_ids():
        if check not in produced:
            rows.append(_not_tested(check, "the measurement did not reach this check"))

    for row in rows:
        if row["status"] not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="the measurement produced an unknown status",
                supported_execution=False,
            )
    return rows


def _warm_up_jax():
    """Initialize the JAX backend outside the measured windows.

    The first JAX call in a process pays a one-time backend initialization
    cost. It belongs to the cold-setup stage, which is measured in a fresh
    interpreter, not to the compilation stage.
    """
    import jax

    jax.jit(lambda value: value + 1.0)(jax.numpy.asarray(1.0))


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = run_worker(args.report_dir)
    (args.report_dir / "checks.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(rows, indent=2))
    return 1 if any(row["status"] in {"FAIL", "HARNESS_ERROR"} for row in rows) else 0


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI contract
    raise SystemExit(main())
