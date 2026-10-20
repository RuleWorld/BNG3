"""CPU work-plan reconciliation and workload profile (#176).

Issue #176 ("G06: Refresh the NFsim CPU, ensemble and GPU roadmap from
measurements") asks for the recorded plan to be reconciled with the CPU work
that is actually implemented and with the measured workload profiles, for the
network-SSA and the network-free execution modes to be told apart, and for the
retained ensemble/isolation scope to be qualified with a fixed seed, a fixed
run budget and a stated statistical error control. Device kernels are pursued
only for the classes that measure as supported, and then only with
independent parity.

This module does that against the plan the repository records
(``docs/NFSIM_GPU_PERF_PLAN.md``) and a fixed, generated corpus.

Rules that keep the numbers honest:

* **The plan is a document, not a claim.** Every item of the recorded plan is
  reconciled against a named probe -- a file the plan names, a mechanism the
  plan names, or an observation of the built surface. An item the build does
  not implement is recorded as such; it is not quietly dropped, and it is
  not presented as a failure of the product.
* **Every timing carries an independent correctness control.** The control is
  the closed-form law of the case, derived from the case parameters and not
  from anything the measured code produced. A timing whose correctness
  control failed is **not** recorded as a result.
* **Every timed stage is measured by repeating the same arm** (an A/A
  control). The spread of those repetitions is recorded, and a stage whose
  spread exceeds the noise limit is not recorded as a result either, so a
  noisy host cannot be mistaken for a measurement.
* **The ensemble scope is pinned.** The seed, the run budget and the
  statistical error control are declared, and the isolation properties (seed
  reproducibility and per-trajectory stream independence) are executed, not
  assumed.
* **The device is recorded, not assumed.** The accelerator inventory, the
  host and the corpus are recorded with the numbers, and the CPU-pinned
  contract stays the gated one; a device result is supplementary evidence on
  the host that produced it.

The module is import-safe: it only touches ``bionetgen`` and ``numpy`` when
it runs.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from .campaign import STATUSES

try:  # The compiled extension is only required when the family actually runs.
    import bionetgen
except ImportError:  # pragma: no cover - exercised by the harness guard
    bionetgen = None

ISSUES = (176,)
ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- #
# The recorded plan
# --------------------------------------------------------------------------- #

# The plan the repository records. The reconciliation reads this document, so
# a changed plan changes the reconciliation instead of leaving a stale one.
PLAN_DOCUMENT = ROOT / "docs" / "NFSIM_GPU_PERF_PLAN.md"

# The plan items that are reconciled by a probe. Each probe is either a file
# the plan names, a mechanism the plan names in the source, or an
# observation of the built surface.
#
#   "file"    the named file exists in the repository
#   "source"  the named mechanism is present in the named source file
#   "runtime" the built surface is observed through the public API
PLAN_ITEMS = (
    {
        "id": "track-0-measurement-harness",
        "track": "Track 0",
        "claim": "a benchmark_nfsim.py harness with NFsim event counters",
        "probe": "file",
        "target": "benchmark_nfsim.py",
    },
    {
        "id": "track-1-membership-rematch",
        "track": "Track 1",
        "claim": "scope membership re-match to the affected rules, driven by "
        "canSkipIndirectMembership",
        "probe": "source",
        "target": "cpp/nfsim/NFcore/moleculeType.cpp",
        "marker": "canSkipIndirectMembership",
    },
    {
        "id": "track-1-zero-allocation",
        "track": "Track 1",
        "claim": "pooled molecule arrays and mappings with high-water free "
        "lists instead of per-event allocation",
        "probe": "source-any",
        "target": "cpp/nfsim/NFcore",
        "markers": ("freeList", "free_list", "MoleculePool", "moleculePool"),
    },
    {
        "id": "track-1-skip-bfs-and-relabel",
        "track": "Track 1",
        "claim": "skip the bonded-neighbourhood BFS and the observable "
        "relabel for state-only firings",
        "probe": "source-any",
        "target": "cpp/nfsim/NFcore",
        "markers": ("stateOnly", "StateOnly", "topologyUnchanged", "skipBFS"),
    },
    {
        "id": "track-1-faster-selection",
        "track": "Track 1",
        "claim": "a hierarchical or Fenwick selection in place of the "
        "DirectSelector linear scan",
        "probe": "source-any",
        "target": "cpp/nfsim/NFcore",
        "markers": ("Fenwick", "fenwick"),
    },
    {
        "id": "track-1-faster-rng",
        "track": "Track 1",
        "claim": "a faster random stream (PCG32 or xoshiro) in place of "
        "MT19937, keeping the two streams separate",
        "probe": "source-any",
        "target": "cpp/nfsim/NFcore",
        "markers": ("pcg32", "PCG32", "xoshiro", "Xoshiro", "splitmix"),
    },
    {
        "id": "track-1-tdf-dependency-tracking",
        "track": "Track 1",
        "claim": "dependency tracking so a time-dependent function is not "
        "recomputed for every rule",
        "probe": "source-any",
        "target": "cpp/nfsim/NFcore",
        "markers": ("TDF", "timeDependentFunction", "tdfDependency"),
    },
    {
        "id": "track-2-nf-ensemble-api",
        "track": "Track 2",
        "claim": "a batch_size on the NFsim action path, cloning the system "
        "per worker over a thread pool",
        "probe": "runtime",
        "target": "network-free-ensemble-api",
    },
    {
        "id": "track-2-network-ssa-ensemble-api",
        "track": "Track 2",
        "claim": "the ensemble API the device backend has to honour",
        "probe": "runtime",
        "target": "network-ssa-ensemble-api",
    },
    {
        "id": "track-3-device-kernels",
        "track": "Track 3",
        "claim": "device kernels for the network-free NFsim event loop",
        "probe": "runtime",
        "target": "device-kernel-inventory",
    },
)

# --------------------------------------------------------------------------- #
# Measurement policy
# --------------------------------------------------------------------------- #

# Repetitions of the same arm per timed stage. Their spread is the A/A
# control: one arm compared with itself, on the same host, in one session.
REPETITIONS = 7

# A timed stage is admissible only when the A/A spread stays inside the
# limit. The absolute floor keeps a sub-millisecond stage from failing on
# timer granularity alone.
AA_RELATIVE_LIMIT = 0.25
AA_ABSOLUTE_LIMIT_SECONDS = 0.001

# The trajectories per timed repetition of the network-SSA arm. The
# network-free arm runs a single trajectory per repetition, so the profile
# reports the cost of one trajectory on both arms.
TIMING_BATCH = 32

# The iterations per timed repetition. Each repetition has to be long enough
# for the timer to measure something other than its own granularity, so the
# cheap stages are repeated inside one repetition.
INNER_ITERATIONS = {"network-ssa": 20, "network-free": 40}

# The trajectories the correctness control of the network-free arm runs. The
# control is a distributional one, because a single stochastic trajectory
# does not follow the law of the deterministic system.
CONTROL_RUNS = 32

# The retained ensemble scope: a fixed seed, a fixed run budget and a stated
# statistical error control. The band is four standard errors of the
# binomial law the case follows.
ENSEMBLE_RUNS = 256
SEED_BASE = 20261020
STATISTICAL_SIGMA = 4.0

# The two batch sizes the isolation control compares. Per-trajectory seeds
# are base_seed + trajectory, so the first members of a smaller batch must
# equal the first members of a larger one.
ISOLATION_BATCHES = (8, 32)

# The corpus. Two bounded generated model classes: a first-order conversion
# (a linear propensity, so the mean of the stochastic process is the law of
# the deterministic system) and a dimerization (a nonlinear propensity, so
# only the pathwise invariants apply).
CASE_SPECS = (
    {
        "id": "conversion",
        "kind": "conversion",
        "rate": 0.5,
        "population": 500,
        "t_end": 1.0,
        "n_steps": 20,
        "linear": True,
    },
    {
        "id": "dimerization",
        "kind": "dimerization",
        "rate": 0.002,
        "population": 500,
        "t_end": 1.0,
        "n_steps": 20,
        "linear": False,
    },
)

TIMED_STAGES = ("network-ssa", "network-free")


# --------------------------------------------------------------------------- #
# Corpus
# --------------------------------------------------------------------------- #


def case_source(case):
    """Return the BNGL source of a corpus case."""
    if case["kind"] == "conversion":
        rules = "  convert: A() -> B() k\n"
    else:
        rules = "  dimerize: A() + A() -> B() k\n"
    return (
        "begin model\n"
        "begin parameters\n"
        f"  k {float(case['rate'])!r}\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A()\n"
        "  B()\n"
        "end molecule types\n"
        "begin seed species\n"
        f"  A() {case['population']}\n"
        "  B() 0\n"
        "end seed species\n"
        "begin observables\n"
        "  Molecules A A()\n"
        "  Molecules B B()\n"
        "end observables\n"
        "begin reaction rules\n"
        f"{rules}"
        "end reaction rules\n"
        "end model\n"
    )


def cases():
    """Return the fixed, generated corpus of workload cases."""
    result = []
    for spec in CASE_SPECS:
        case = dict(spec)
        case["bngl"] = case_source(case)
        result.append(case)
    return result


def corpus_record():
    """Return the description of the corpus the profile used."""
    return {
        "cases": [
            {
                "id": case["id"],
                "kind": case["kind"],
                "rate": case["rate"],
                "population": case["population"],
                "t_end": case["t_end"],
                "n_steps": case["n_steps"],
                "linear": case["linear"],
                "bngl_sha256": hashlib.sha256(case["bngl"].encode()).hexdigest(),
            }
            for case in cases()
        ],
        "timing_batch": TIMING_BATCH,
        "repetitions": REPETITIONS,
        "ensemble_runs": ENSEMBLE_RUNS,
        "seed_base": SEED_BASE,
        "statistical_sigma": STATISTICAL_SIGMA,
        "isolation_batches": list(ISOLATION_BATCHES),
        "aa_relative_limit": AA_RELATIVE_LIMIT,
        "aa_absolute_limit_seconds": AA_ABSOLUTE_LIMIT_SECONDS,
    }


def corpus_digest():
    """Return the digest of the corpus description."""
    return hashlib.sha256(
        json.dumps(corpus_record(), sort_keys=True).encode()
    ).hexdigest()


def case_law(case, times):
    """Return the analytic mean and variance of the reactant count.

    A first-order conversion is a linear propensity, so every molecule
    converts independently and the reactant count is Binomial(N, exp(-k t)).
    A dimerization has a nonlinear propensity, so the mean of the stochastic
    process is not the law of the deterministic system; that case is
    controlled by its pathwise invariants instead.
    """
    times = np.asarray(times, dtype=float)
    population = float(case["population"])
    if case["kind"] == "conversion":
        probability = np.exp(-float(case["rate"]) * times)
        mean = population * probability
        variance = population * probability * (1.0 - probability)
        return mean, variance
    raise ValueError(f"case {case['id']!r} has no closed-form marginal")


# --------------------------------------------------------------------------- #
# Check identities
# --------------------------------------------------------------------------- #


def check_ids():
    """Declare the expected evidence identities independently of execution."""
    ids = [
        "workload-profile:family:environment-record",
        "workload-profile:family:plan-reconciliation",
        "workload-profile:family:execution-mode-distinction",
        "workload-profile:family:ensemble-qualification",
        "workload-profile:family:device-kernel-qualification",
    ]
    for case in cases():
        ids.append(f"workload-profile:{case['id']}:aa-control")
        ids.append(f"workload-profile:{case['id']}:network-ssa-timing")
        ids.append(f"workload-profile:{case['id']}:network-free-timing")
        ids.append(f"workload-profile:{case['id']}:execution-mode-comparison")
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


def _failed(check, detail, difference=None, artifact=None):
    return _row(check, "FAIL", detail, first_difference=difference, artifact=artifact)


def _correctness(ok, detail, difference=None):
    return {"ok": bool(ok), "detail": detail, "difference": difference}


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


def _describe(measurement):
    """Return the human-readable description of a measurement."""
    return (
        f"{len(measurement['samples'])} repetitions of "
        f"{measurement['inner']} iteration(s); median "
        f"{measurement['median'] * 1000.0:.3f} ms per repetition "
        f"({measurement['per_operation'] * 1000.0:.4f} ms per operation); "
        f"A/A spread (interquartile range) {measurement['spread'] * 100.0:.1f}% "
        f"of the median ({measurement['absolute_spread'] * 1000.0:.3f} ms), "
        f"full range {measurement['range_spread'] * 100.0:.1f}%"
    )


# --------------------------------------------------------------------------- #
# The built surface
# --------------------------------------------------------------------------- #


def _signature(function):
    """Return the parameter names a bound function declares."""
    doc = getattr(function, "__doc__", "") or ""
    header = doc.splitlines()[0] if doc else ""
    if "(" not in header or ")" not in header:
        return []
    body = header[header.index("(") + 1 : header.rindex(")")]
    names = []
    for part in body.split(","):
        name = part.split(":")[0].split("=")[0].strip()
        if name and name != "self":
            names.append(name)
    return names


def device_inventory():
    """Return the accelerator inventory of the built surface."""
    if bionetgen is None:
        return []
    from bionetgen import _bionetgen_cpp as cpp

    return list(cpp.gpu_backends())


def _plan_probe(item):
    """Run one plan probe and return (status, detail)."""
    kind = item["probe"]
    if kind == "file":
        matches = [
            path
            for path in ROOT.rglob(item["target"])
            if "build" not in path.parts and ".git" not in path.parts
        ]
        if matches:
            return (
                "PRESENT",
                f"{item['target']} exists at {matches[0].relative_to(ROOT)}",
            )
        return "ABSENT", f"{item['target']} is not in the repository"
    if kind in {"source", "source-any"}:
        target = ROOT / item["target"]
        if target.is_dir():
            markers = item.get("markers", (item.get("marker", ""),))
            found = []
            for path in sorted(target.rglob("*")):
                if not path.is_file() or path.suffix not in {".cpp", ".hh", ".hpp"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for marker in markers:
                    if marker and marker in text:
                        found.append(f"{marker} in {path.relative_to(ROOT)}")
            if found:
                return "PRESENT", "; ".join(found)
            return "ABSENT", (f"none of {list(markers)} appears under {item['target']}")
        text = target.read_text(encoding="utf-8", errors="ignore")
        if item.get("marker", "") in text:
            return "PRESENT", f"{item['marker']} appears in {item['target']}"
        return "ABSENT", f"{item['marker']} does not appear in {item['target']}"
    if kind == "runtime":
        return _runtime_probe(item["target"])
    raise ValueError(f"unknown probe kind: {kind!r}")


def _runtime_probe(target):
    """Observe the built surface for a plan item."""
    if bionetgen is None:
        return "UNVERIFIABLE", "the bionetgen package is unavailable"
    from bionetgen import _bionetgen_cpp as cpp

    if target == "network-free-ensemble-api":
        names = _signature(cpp.simulate_nf)
        if "batch_size" in names:
            return "PRESENT", "the network-free NFsim entry point declares batch_size"
        return (
            "ABSENT",
            "the network-free NFsim entry point declares no batch_size "
            f"(parameters: {', '.join(names)})",
        )
    if target == "network-ssa-ensemble-api":
        names = _signature(cpp.simulate_batch_ssa_cpu)
        if "batch_size" in names:
            return (
                "PRESENT",
                "the network-SSA batch entry point declares batch_size, so the "
                "ensemble API exists for the network SSA path",
            )
        return "ABSENT", "the network-SSA batch entry point declares no batch_size"
    if target == "device-kernel-inventory":
        inventory = device_inventory()
        if not inventory:
            return "ABSENT", "the build reports no accelerator backend"
        usable = [entry for entry in inventory if entry.get("compiled")]
        if not usable:
            return (
                "ABSENT",
                "the build compiles no accelerator backend "
                f"({[entry['name'] for entry in inventory]})",
            )
        return (
            "PRESENT",
            "the build compiles the accelerator backend(s) "
            + ", ".join(
                f"{entry['name']} (available: {entry.get('available')}, "
                f"{entry.get('detail')})"
                for entry in usable
            )
            + " for the batched network-SSA kernel; there is no device kernel "
            "for the network-free NFsim event loop",
        )
    raise ValueError(f"unknown runtime probe: {target!r}")


def _plan_document_state():
    """Return whether the recorded plan is present and readable."""
    if not PLAN_DOCUMENT.is_file():
        return None
    text = PLAN_DOCUMENT.read_text(encoding="utf-8")
    return {
        "path": str(PLAN_DOCUMENT.relative_to(ROOT)),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "bytes": len(text.encode()),
    }


# --------------------------------------------------------------------------- #
# The plan reconciliation
# --------------------------------------------------------------------------- #


def check_plan_reconciliation():
    """Reconcile the recorded plan with the implemented surface."""
    document = _plan_document_state()
    if document is None:
        return _correctness(
            False,
            "the recorded plan at "
            f"{PLAN_DOCUMENT} is missing, so the reconciliation cannot be "
            "produced",
            {"field": "plan-document"},
        )
    statuses = []
    for item in PLAN_ITEMS:
        status, detail = _plan_probe(item)
        statuses.append((item, status, detail))
    unresolved = [
        item["id"] for item, status, _ in statuses if status == "UNVERIFIABLE"
    ]
    if unresolved:
        return _correctness(
            False,
            "the plan items "
            + ", ".join(unresolved)
            + " could not be probed, so the reconciliation is incomplete",
            {"field": "plan-items", "unresolved": unresolved},
        )
    summary = "; ".join(
        f"{item['track']} {item['id']}={status}" for item, status, _ in statuses
    )
    implemented = [item["id"] for item, status, _ in statuses if status == "PRESENT"]
    absent = [item["id"] for item, status, _ in statuses if status == "ABSENT"]
    detail = (
        f"the recorded plan {document['path']} (sha256 {document['sha256']}) is "
        f"reconciled against the implemented surface: {summary}. "
        f"{len(implemented)} of {len(statuses)} probed items are present in the "
        f"build ({', '.join(implemented) or 'none'}) and {len(absent)} are not "
        f"({', '.join(absent) or 'none'}). An item the build does not implement "
        "is recorded as absent, not as a product failure and not as support."
    )
    return _correctness(True, detail)


# --------------------------------------------------------------------------- #
# The execution modes
# --------------------------------------------------------------------------- #


def _build(case):
    """Return the parsed model and the generated network of a case."""
    from bionetgen import _bionetgen_cpp as cpp

    model = cpp.parse_string(case["bngl"])
    network = cpp.generate_network(model)
    return model, network


def check_execution_mode_distinction(case):
    """The two execution modes must be distinguishable surfaces."""
    from bionetgen import _bionetgen_cpp as cpp

    model, network = _build(case)
    names = _signature(cpp.simulate_nf)
    batch_names = _signature(cpp.simulate_batch_ssa_cpu)
    if "batch_size" in names:
        return _correctness(
            False,
            "the network-free NFsim entry point now declares batch_size, so "
            "the two execution modes are no longer told apart by their "
            "surface",
            {"field": "network-free-signature"},
        )
    if "batch_size" not in batch_names:
        return _correctness(
            False,
            "the network-SSA batch entry point no longer declares batch_size, "
            "so the retained ensemble scope has no route",
            {"field": "network-ssa-signature"},
        )
    network_free = cpp.simulate_nf(
        model, t_end=case["t_end"], n_steps=2, seed=SEED_BASE
    )
    path = network_free.get("construction_path")
    if path not in {"direct", "in-memory-xml", "on-disk-xml"}:
        return _correctness(
            False,
            f"the network-free route did not report a construction path: {path!r}",
            {"field": "construction-path"},
        )
    batch = cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=4,
        t_end=case["t_end"],
        n_steps=2,
        base_seed=SEED_BASE,
        threads=0,
    )
    if "final_observables" not in batch:
        return _correctness(
            False,
            "the network-SSA batch route did not return per-trajectory final " "states",
            {"field": "network-ssa-result"},
        )
    if "observables" not in network_free:
        return _correctness(
            False,
            "the network-free route did not return an observable trajectory",
            {"field": "network-free-result"},
        )
    return _correctness(
        True,
        "the two execution modes are distinct surfaces: the network-free "
        f"NFsim route runs the event loop directly (construction path "
        f"{path!r}) and declares no batch_size (parameters: "
        f"{', '.join(names)}), while the network-SSA route runs a generated "
        "network through the batched direct-SSA kernel and declares "
        f"batch_size (parameters: {', '.join(batch_names)}) and returns "
        "per-trajectory final states",
    )


# --------------------------------------------------------------------------- #
# The measured profile
# --------------------------------------------------------------------------- #


def _network_ssa_arm(case):
    from bionetgen import _bionetgen_cpp as cpp

    model, network = _build(case)
    return lambda: cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=TIMING_BATCH,
        t_end=case["t_end"],
        n_steps=case["n_steps"],
        base_seed=SEED_BASE,
        threads=0,
    )


def _network_free_arm(case):
    from bionetgen import _bionetgen_cpp as cpp

    model, _ = _build(case)
    return lambda: cpp.simulate_nf(
        model, t_end=case["t_end"], n_steps=case["n_steps"], seed=SEED_BASE
    )


def _control_for(case, stage):
    """Return the independent correctness control of a timed stage.

    The control is the closed-form law of the case for the arm whose law is
    known, and the pathwise invariants for the arm whose mean is not the law
    of the deterministic system. A stochastic arm is controlled by an
    ensemble, because one trajectory does not follow the deterministic law.
    """
    from bionetgen import _bionetgen_cpp as cpp

    model, network = _build(case)
    times = np.linspace(0.0, case["t_end"], case["n_steps"] + 1)
    if case["linear"]:
        mean, variance = case_law(case, times)
        expected = float(mean[-1])
        if stage == "network-ssa":
            batch = cpp.simulate_batch_ssa_cpu(
                model,
                network,
                batch_size=CONTROL_RUNS,
                t_end=case["t_end"],
                n_steps=case["n_steps"],
                base_seed=SEED_BASE,
                threads=0,
            )
            names = list(batch["observable_names"])
            table = np.asarray(batch["final_observables"], dtype=float)
            column = table[:, names.index("A")]
            observed = float(column.mean())
            band = STATISTICAL_SIGMA * math.sqrt(
                float(variance[-1]) / max(1, column.size)
            )
            if abs(observed - expected) > band:
                return _correctness(
                    False,
                    "the network-SSA ensemble mean "
                    f"{observed:.6g} differs from the closed-form law "
                    f"{expected:.6g} by more than the {STATISTICAL_SIGMA}-sigma "
                    f"band {band:.6g}",
                    {
                        "field": "ensemble-mean",
                        "expected": expected,
                        "observed": observed,
                        "band": band,
                    },
                )
            return _correctness(
                True,
                "the network-SSA ensemble mean reproduces the closed-form law "
                f"of the case ({observed:.6g} against {expected:.6g}, inside "
                f"the {STATISTICAL_SIGMA}-sigma band {band:.6g})",
            )
        samples = []
        for index in range(CONTROL_RUNS):
            result = cpp.simulate_nf(
                model,
                t_end=case["t_end"],
                n_steps=case["n_steps"],
                seed=SEED_BASE + index,
            )
            samples.append(np.asarray(result["observables"]["A"], dtype=float))
        ensemble = np.vstack(samples)
        observed = ensemble.mean(axis=0)
        band = STATISTICAL_SIGMA * np.sqrt(variance / CONTROL_RUNS)
        difference = observed - mean
        worst = int(np.argmax(np.abs(difference) - band))
        if band[worst] > 0.0 and np.abs(difference[worst]) > band[worst]:
            return _correctness(
                False,
                "the network-free ensemble mean departs from the closed-form "
                f"law: at t={times[worst]:.6g} the mean was "
                f"{observed[worst]:.6g} against {mean[worst]:.6g}, outside the "
                f"{STATISTICAL_SIGMA}-sigma band {band[worst]:.6g}",
                {
                    "field": "network-free-mean",
                    "time": float(times[worst]),
                    "expected": float(mean[worst]),
                    "observed": float(observed[worst]),
                    "band": float(band[worst]),
                },
            )
        return _correctness(
            True,
            "the network-free ensemble of "
            f"{CONTROL_RUNS} trajectories reproduces the closed-form law of "
            "the case at every recorded time, inside the "
            f"{STATISTICAL_SIGMA}-sigma band",
        )
    # A nonlinear propensity: the mean of the stochastic process is not the
    # law of the deterministic system, so the control is the pathwise
    # invariant.
    expected = float(case["population"])
    if stage == "network-ssa":
        batch = cpp.simulate_batch_ssa_cpu(
            model,
            network,
            batch_size=CONTROL_RUNS,
            t_end=case["t_end"],
            n_steps=case["n_steps"],
            base_seed=SEED_BASE,
            threads=0,
        )
        names = list(batch["observable_names"])
        table = np.asarray(batch["final_observables"], dtype=float)
        totals = table[:, names.index("A")] + 2.0 * table[:, names.index("B")]
    else:
        result = cpp.simulate_nf(
            model, t_end=case["t_end"], n_steps=case["n_steps"], seed=SEED_BASE
        )
        observed = np.asarray(result["observables"]["A"], dtype=float)
        product = np.asarray(result["observables"]["B"], dtype=float)
        totals = observed + 2.0 * product
    worst = float(np.max(np.abs(totals - expected))) if totals.size else 0.0
    if worst > 1e-9 * max(1.0, expected):
        return _correctness(
            False,
            "a run did not conserve the weighted total amount: the largest "
            f"deviation was {worst:.6g}",
            {"field": "conservation", "deviation": worst},
        )
    return _correctness(
        True,
        "every run conserved the weighted total amount "
        f"{expected:.6g}; the case has a nonlinear propensity, so its mean is "
        "not the law of the deterministic system and the pathwise invariant "
        "is the control",
    )


# --------------------------------------------------------------------------- #
# The ensemble scope
# --------------------------------------------------------------------------- #


def check_ensemble_qualification(case):
    """Qualify the retained ensemble and isolation scope.

    The claim is narrow and pinned: a fixed seed, a fixed run budget, a
    stated statistical error control against the closed-form law, and the
    isolation properties the ensemble API has to hold -- the same seed
    reproduces the batch, and a member does not depend on how many members
    the batch has.
    """
    from bionetgen import _bionetgen_cpp as cpp

    model, network = _build(case)
    if not case["linear"]:
        return _correctness(
            False,
            "the ensemble scope is qualified on a case whose mean is not the "
            "law of the deterministic system",
            {"field": "ensemble-case"},
        )
    batch = cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=ENSEMBLE_RUNS,
        t_end=case["t_end"],
        n_steps=case["n_steps"],
        base_seed=SEED_BASE,
        threads=0,
    )
    names = list(batch["observable_names"])
    table = np.asarray(batch["final_observables"], dtype=float)
    column = table[:, names.index("A")]
    times = np.linspace(0.0, case["t_end"], case["n_steps"] + 1)
    mean, variance = case_law(case, times)
    expected = float(mean[-1])
    observed = float(column.mean())
    deviation = float(column.std(ddof=1)) if column.size > 1 else 0.0
    band = STATISTICAL_SIGMA * (
        deviation / np.sqrt(column.size) if column.size else 0.0
    )
    if band <= 0.0 or abs(observed - expected) > band:
        return _correctness(
            False,
            f"the ensemble mean {observed:.6g} differs from the closed-form "
            f"law {expected:.6g} by more than the {STATISTICAL_SIGMA}-sigma "
            f"band {band:.6g}",
            {
                "field": "ensemble-mean",
                "expected": expected,
                "observed": observed,
                "band": band,
                "runs": int(column.size),
            },
        )
    # Seed reproducibility: the same base seed reproduces the batch.
    repeat = cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=ENSEMBLE_RUNS,
        t_end=case["t_end"],
        n_steps=case["n_steps"],
        base_seed=SEED_BASE,
        threads=0,
    )
    repeated = np.asarray(repeat["final_observables"], dtype=float)
    if not np.array_equal(table, repeated):
        return _correctness(
            False,
            "re-running the ensemble with the same base seed did not "
            "reproduce the batch",
            {"field": "seed-reproducibility"},
        )
    # Isolation: the first members of a smaller batch equal the first
    # members of the larger one, because every trajectory owns its own
    # stream.
    small = min(ISOLATION_BATCHES)
    smaller = cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=small,
        t_end=case["t_end"],
        n_steps=case["n_steps"],
        base_seed=SEED_BASE,
        threads=0,
    )
    smaller_table = np.asarray(smaller["final_observables"], dtype=float)
    if not np.array_equal(smaller_table, table[:small]):
        return _correctness(
            False,
            "the first members of a "
            f"{small}-trajectory batch differ from the first members of the "
            f"{ENSEMBLE_RUNS}-trajectory batch, so a trajectory's result "
            "depends on the size of the batch it belongs to",
            {"field": "member-isolation"},
        )
    return _correctness(
        True,
        f"the retained ensemble scope is qualified with seed {SEED_BASE}, a "
        f"run budget of {ENSEMBLE_RUNS} trajectories and a "
        f"{STATISTICAL_SIGMA}-sigma band of {band:.6g}: the ensemble mean "
        f"{observed:.6g} reproduces the closed-form law {expected:.6g}; the "
        "same seed reproduces the batch bit for bit; and the first "
        f"{small} members of a {small}-trajectory batch equal the first "
        f"{small} members of the {ENSEMBLE_RUNS}-trajectory batch, so every "
        "trajectory owns its own stream",
    )


# --------------------------------------------------------------------------- #
# The device kernel
# --------------------------------------------------------------------------- #


def check_device_kernel_qualification(case):
    """Qualify the device kernel for the class that measures as supported.

    The plan's device track is about the network-free NFsim event loop. The
    device kernel this build ships is the batched network-SSA kernel, so the
    class that measures as supported is the network-SSA batch class, and
    that is the only class the device result is claimed for.
    """
    from bionetgen import _bionetgen_cpp as cpp

    inventory = device_inventory()
    usable = [
        entry for entry in inventory if entry.get("compiled") and entry.get("available")
    ]
    if not usable:
        return _correctness(
            False,
            "no accelerator backend is available on this host, so the device "
            "kernel is not qualified here: "
            + ", ".join(
                f"{entry['name']} (compiled: {entry.get('compiled')}, "
                f"{entry.get('detail')})"
                for entry in inventory
            ),
            {"field": "device-inventory"},
        )
    if not case["linear"]:
        return _correctness(
            False,
            "the device kernel is qualified on a case whose mean is not the "
            "law of the deterministic system",
            {"field": "device-case"},
        )
    model, network = _build(case)
    device = usable[0]["name"]
    result = cpp.simulate_batch_ssa_gpu(
        model,
        network,
        batch_size=ENSEMBLE_RUNS,
        t_end=case["t_end"],
        n_steps=case["n_steps"],
        base_seed=SEED_BASE,
        backend=device,
    )
    if result.get("backend") != device:
        return _correctness(
            False,
            f"the device run reported backend {result.get('backend')!r} "
            f"instead of {device!r}, so the result did not come from the "
            "device",
            {"field": "device-backend"},
        )
    names = list(result["observable_names"])
    table = np.asarray(result["final_observables"], dtype=float)
    column = table[:, names.index("A")]
    times = np.linspace(0.0, case["t_end"], case["n_steps"] + 1)
    mean, _ = case_law(case, times)
    expected = float(mean[-1])
    observed = float(column.mean())
    deviation = float(column.std(ddof=1)) if column.size > 1 else 0.0
    band = STATISTICAL_SIGMA * (
        deviation / np.sqrt(column.size) if column.size else 0.0
    )
    if band <= 0.0 or abs(observed - expected) > band:
        return _correctness(
            False,
            f"the device ensemble mean {observed:.6g} differs from the "
            f"closed-form law {expected:.6g} by more than the "
            f"{STATISTICAL_SIGMA}-sigma band {band:.6g}",
            {
                "field": "device-mean",
                "expected": expected,
                "observed": observed,
                "band": band,
            },
        )
    return _correctness(
        True,
        f"the device kernel {device} "
        f"({usable[0].get('detail')}) reproduces the closed-form law of the "
        f"network-SSA batch class: the ensemble mean {observed:.6g} against "
        f"{expected:.6g}, inside the {STATISTICAL_SIGMA}-sigma band "
        f"{band:.6g} over {ENSEMBLE_RUNS} trajectories with seed {SEED_BASE}. "
        "The device result is supplementary evidence on this host; the "
        "CPU-pinned contract remains the gated one, and the device kernel is "
        "claimed only for the network-SSA batch class, which is the class "
        "this build ships a kernel for",
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
    """Return the environment, corpus and revision the profile ran on."""
    package = Path(bionetgen.__file__).resolve() if bionetgen is not None else None
    try:
        load_average = [round(value, 2) for value in os.getloadavg()]
    except (AttributeError, OSError):  # pragma: no cover - platform specific
        load_average = None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version.split()[0],
        "package": str(package) if package else None,
        "package_sha256": (
            hashlib.sha256(package.read_bytes()).hexdigest() if package else None
        ),
        "devices": device_inventory(),
        "load_average": load_average,
        "corpus_sha256": corpus_digest(),
        "plan": _plan_document_state(),
    }


# --------------------------------------------------------------------------- #
# Worker entry point
# --------------------------------------------------------------------------- #


def run_worker(directory):
    """Run the workload profile and return its evidence rows."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if bionetgen is None:
        return [
            _not_tested(check, "the bionetgen package is unavailable")
            for check in check_ids()
        ]
    rows = []
    environment = environment_record()
    environment["revision"] = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    environment["dirty"] = bool(status) if status is not None else None
    (directory / "environment.json").write_text(
        json.dumps(environment, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "corpus.json").write_text(
        json.dumps(corpus_record(), indent=2) + "\n", encoding="utf-8"
    )

    environment_check = "workload-profile:family:environment-record"
    if not environment["revision"]:
        rows.append(
            _not_tested(
                environment_check,
                "the revision the profile ran on could not be determined",
            )
        )
    else:
        devices = (
            ", ".join(
                f"{entry['name']} (compiled: {entry.get('compiled')}, "
                f"available: {entry.get('available')}, {entry.get('detail')})"
                for entry in environment["devices"]
            )
            or "none reported"
        )
        plan = environment["plan"]
        rows.append(
            _row(
                environment_check,
                "PASS",
                "measured on revision "
                f"{environment['revision']} (dirty: {environment['dirty']}) with "
                f"corpus {environment['corpus_sha256']}; device: CPU on "
                f"{environment['platform']} / {environment['machine']}, "
                f"accelerators: {devices}; environment: Python "
                f"{environment['python']}, host load average "
                f"{environment['load_average']}; recorded plan "
                f"{plan['path'] if plan else 'absent'} "
                f"(sha256 {plan['sha256'] if plan else 'unavailable'}). The "
                "measured numbers are specific to this machine and revision",
            )
        )

    def family_row(name, correctness, *, boundary=False):
        check = f"workload-profile:family:{name}"
        if correctness["ok"]:
            row = _row(check, "PASS", correctness["detail"])
            if boundary:
                row["evidence_kind"] = "diagnostic-only"
                row["supported_execution"] = False
            return row
        return _row(
            check,
            "FAIL",
            correctness["detail"],
            first_difference=correctness["difference"],
        )

    rows.append(family_row("plan-reconciliation", check_plan_reconciliation()))
    rows.append(
        family_row(
            "execution-mode-distinction",
            check_execution_mode_distinction(cases()[0]),
        )
    )
    rows.append(
        family_row(
            "ensemble-qualification",
            check_ensemble_qualification(cases()[0]),
        )
    )
    device = check_device_kernel_qualification(cases()[0])
    if device["ok"]:
        rows.append(
            _boundary_row(
                "workload-profile:family:device-kernel-qualification",
                "PASS",
                device["detail"],
            )
        )
    elif "no accelerator backend is available" in device["detail"]:
        rows.append(
            _boundary_row(
                "workload-profile:family:device-kernel-qualification",
                "NOT_TESTED",
                device["detail"],
            )
        )
    else:
        rows.append(family_row("device-kernel-qualification", device))

    for case in cases():
        source = directory / f"{case['id']}.bngl"
        source.write_text(case["bngl"], encoding="utf-8")
        stages = {}
        try:
            for stage in TIMED_STAGES:
                arm = (
                    _network_ssa_arm(case)
                    if stage == "network-ssa"
                    else _network_free_arm(case)
                )
                stages[stage] = {
                    "measurement": _measure(arm, stage),
                    "correctness": _control_for(case, stage),
                }
        except Exception as exc:  # noqa: BLE001 - the failure is the claim
            for name in ("aa-control", "execution-mode-comparison"):
                rows.append(
                    _failed(
                        f"workload-profile:{case['id']}:{name}",
                        "the measured arm could not be executed: "
                        f"{type(exc).__name__}: {exc}",
                        artifact=source,
                    )
                )
            for stage in TIMED_STAGES:
                rows.append(
                    _not_tested(
                        f"workload-profile:{case['id']}:{stage}-timing",
                        "the measured arm could not be executed: "
                        f"{type(exc).__name__}: {exc}",
                        artifact=source,
                    )
                )
            continue

        rows.append(_aa_row(case, stages, source))
        for stage in TIMED_STAGES:
            rows.append(_timing_row(case, stage, stages[stage], source))
        rows.append(_comparison_row(case, stages, source))

    produced = {row["id"] for row in rows}
    for check in check_ids():
        if check not in produced:
            rows.append(_not_tested(check, "the profile did not reach this check"))

    for row in rows:
        if row["status"] not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="the profile produced an unknown status",
                supported_execution=False,
            )
    return rows


def _timing_row(case, stage, stage_result, artifact):
    check = f"workload-profile:{case['id']}:{stage}-timing"
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
    detail = (
        f"{stage}: {_describe(measurement)}; correctness: "
        f"{correctness['detail']}; the numbers are specific to this machine "
        "and revision"
    )
    return _row(check, "PASS", detail, artifact=artifact)


def _aa_row(case, stages, artifact=None):
    check = f"workload-profile:{case['id']}:aa-control"
    spreads = {name: stages[name]["measurement"]["spread"] for name in TIMED_STAGES}
    worst = max(spreads, key=lambda name: spreads[name])
    noisy = [
        name for name in TIMED_STAGES if not stages[name]["measurement"]["admissible"]
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
    check = f"workload-profile:{case['id']}:execution-mode-comparison"
    network_ssa = stages.get("network-ssa")
    network_free = stages.get("network-free")
    for name, stage in (("network-ssa", network_ssa), ("network-free", network_free)):
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
    ssa_seconds = network_ssa["measurement"]["per_operation"] / TIMING_BATCH
    free_seconds = network_free["measurement"]["per_operation"]
    ratio = ssa_seconds / free_seconds if free_seconds else float("inf")
    verdict = "SSA-WIN" if ssa_seconds < free_seconds else "NO-WIN"
    detail = (
        f"{verdict}: on this corpus the network-SSA path cost "
        f"{ssa_seconds * 1000.0:.3f} ms per trajectory and the network-free "
        f"NFsim path cost {free_seconds * 1000.0:.3f} ms per trajectory "
        f"(network-SSA/network-free ratio {ratio:.3f})"
    )
    if verdict == "NO-WIN":
        detail += (
            "; the no-win result is recorded as measured and is not a failure "
            "to hide"
        )
    return _row(check, "PASS", detail, artifact=artifact)


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
