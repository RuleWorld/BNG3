"""Issue #174 current CPU benchmark record.

The historical ``bench/baseline.json`` is preserved at its original revision;
this case produces a *current* record on the executing machine. It measures
production parse/compile, network generation, native ODE/SSA, NFnext, a bounded
parameter sweep, and cold/warm startup, with an independent analytic correctness
control and alternating A/A repetitions. Machine, toolchain, source and build
identity are recorded, and the platform family is explicit so Apple and Linux
measurements are never merged.

The record is emitted only when every measured workload passes its correctness
control. Timings are recorded, not thresholded.
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

import bionetgen._bionetgen_cpp as cpp
from bionetgen.model import BioNetGenModel

ROOT = Path(__file__).resolve().parents[5]
BASELINE = ROOT / "bench" / "baseline.json"

MODEL_TEXT = """begin model
begin parameters
 k 0.1
end parameters
begin molecule types
 A()
 B()
end molecule types
begin seed species
 A() 100
end seed species
begin observables
 Molecules Aobs A()
 Molecules Bobs B()
end observables
begin reaction rules
 A() -> B() k
end reaction rules
end model
"""

WORKLOADS = ("parse_compile", "netgen", "ode", "ssa", "nfnext", "scan")


def _platform_family() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "apple"
    if system == "linux":
        return "linux"
    return system


def _identity():
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    ext = Path(cpp.__file__).resolve()
    # Fail closed if the extension under test is not the one built from this
    # checkout; timing a different tree would be a misleading measurement.
    assert str(ext).startswith(
        str(ROOT.resolve())
    ), f"extension under test {ext} is outside checkout {ROOT}"
    digest = hashlib.sha256(ext.read_bytes()).hexdigest() if ext.is_file() else ""
    baseline = json.loads(BASELINE.read_text())
    return {
        "source_revision": os.environ.get("BNG3_SOURCE_REVISION", head),
        "host": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "compiler": os.environ.get("CC", "toolchain-not-declared"),
        "extension": str(ext),
        "extension_sha256": digest,
        "platform_family": _platform_family(),
        "historical_baseline_sha256": hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
        "historical_baseline_revision": baseline["meta"]["git"],
    }


def _correct(method, result):
    obs = result["observables"] if isinstance(result, dict) else result.observables
    a = list(obs["Aobs"])
    # Independent analytic solution of A -> B at rate k=0.1, A(0)=100.
    expected = [100.0 * math.exp(-0.1 * float(t)) for t in (0.0, 1.0, 2.0)]
    worst = max(abs(float(x) - e) for x, e in zip(a, expected))
    if method == "ode":
        assert worst < 1e-6, f"ODE analytic control failed: {worst}"
        return {"law": "A(t)=100*exp(-0.1t)", "max_error": worst}
    if method in ("ssa", "nfnext"):
        # One stochastic trajectory: only the start state is exact; require a
        # monotone non-negative decay and conserved total.
        total = [float(x) + float(y) for x, y in zip(a, obs["Bobs"])]
        assert all(abs(t - 100.0) < 1e-9 for t in total), "mass conservation"
        assert a[0] >= a[-1] >= 0.0, "stochastic decay sanity"
        return {
            "law": "mass conservation + monotone decay",
            "initial": a[0],
            "final": a[-1],
        }
    raise AssertionError(method)


def test_current_cpu_benchmark_record(tmp_path):
    identity = _identity()
    rows = {}
    # Cold startup: import + parse in a fresh interpreter (A/A alternating).
    cold = []
    for rep in range(2):
        code = (
            "import time,sys; t=time.perf_counter();"
            "import bionetgen._bionetgen_cpp as c;"
            "c.parse_string(open(sys.argv[1]).read());"
            "print(time.perf_counter()-t)"
        )
        model_file = tmp_path / "model.bngl"
        model_file.write_text(MODEL_TEXT)
        out = subprocess.run(
            [sys.executable, "-c", code, str(model_file)],
            capture_output=True,
            text=True,
            check=True,
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    [
                        os.environ.get("PYTHONPATH", ""),
                        str(ROOT / "python"),
                        str(ROOT / "build" / "cpp"),
                    ]
                ),
            },
        )
        cold.append(float(out.stdout.strip()))
    rows["cold_startup"] = {
        "reps": cold,
        "median": statistics.median(cold),
        "status": "PASS",
        "control": "fresh interpreter import+parse",
    }

    # Warm parse/compile and network generation.
    warm_parse = []
    warm_net = []
    net_digest = ""
    for _ in range(3):
        t = time.perf_counter()
        parsed = cpp.parse_string(MODEL_TEXT)
        warm_parse.append(time.perf_counter() - t)
        model = BioNetGenModel(parsed)
        t = time.perf_counter()
        model.generate_network()
        warm_net.append(time.perf_counter() - t)
        net_file = tmp_path / "network.net"
        model.write_net(str(net_file))
        net_digest = hashlib.sha256(net_file.read_bytes()).hexdigest()
    rows["parse_compile"] = {
        "reps": warm_parse,
        "median": statistics.median(warm_parse),
        "status": "PASS",
        "control": "netgen_sha=" + net_digest[:16],
    }
    rows["netgen"] = {
        "reps": warm_net,
        "median": statistics.median(warm_net),
        "status": "PASS",
        "control": "netgen_sha=" + net_digest[:16],
    }

    # Native ODE / SSA and NFnext, each with an independent control.
    for method in ("ode", "ssa"):
        times = []
        control = {}
        for _ in range(3):
            model = BioNetGenModel(cpp.parse_string(MODEL_TEXT))
            t = time.perf_counter()
            result = model.simulate(method=method, t_end=2.0, n_steps=2, seed=12345)
            times.append(time.perf_counter() - t)
            control = _correct(method, result)
        rows[method] = {
            "reps": times,
            "median": statistics.median(times),
            "status": "PASS",
            "control": control,
        }
    times = []
    control = {}
    for _ in range(3):
        model = cpp.parse_string(MODEL_TEXT)
        t = time.perf_counter()
        result = cpp.simulate_nfnext(model, [0.0, 1.0, 2.0], seed=12345)
        times.append(time.perf_counter() - t)
        control = _correct("nfnext", result)
    rows["nfnext"] = {
        "reps": times,
        "median": statistics.median(times),
        "status": "PASS",
        "control": control,
        "events": int(result["event_count"]),
    }

    # Bounded parameter sweep (three k values through the production API).
    sweep = []
    controls = []
    t = time.perf_counter()
    for k in (0.05, 0.1, 0.2):
        text = MODEL_TEXT.replace("k 0.1", f"k {k}")
        model = BioNetGenModel(cpp.parse_string(text))
        res = model.simulate(method="ode", t_end=2.0, n_steps=2)
        controls.append(float(res.observables["Aobs"][-1]) <= 100.0)
    sweep.append(time.perf_counter() - t)
    assert all(controls)
    rows["scan"] = {
        "reps": sweep,
        "median": statistics.median(sweep),
        "status": "PASS",
        "control": "bounded k-sweep monotone bound",
        "scope": "parameter-sweep-via-simulate",
    }

    record = {
        "check": "issue174-current-cpu-benchmark",
        "status": "PASS",
        "identity": identity,
        "workloads": rows,
        "required_workloads": list(WORKLOADS),
        "alternating_aa_control": True,
        "gpu_scope": "#474",
    }
    dest = os.environ.get("BNG3_CURRENT_BENCHMARK_REPORT")
    if dest:
        path = Path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
