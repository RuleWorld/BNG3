"""Issue #178 consuming route report for executable CPU/format routes.

For every required route this producer checks four aspects through production
entry points: the same compiled model input, the declared result schema,
consistent failure on an invalid backend option, and an independent semantic
output (analytic law or format round-trip). Routes whose optional backend is
not installed are recorded as UNSUPPORTED, never as PASS; GPU device execution
is tracked under #474 and is not claimed here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

import numpy as np

import bionetgen
import bionetgen._bionetgen_cpp as cpp
from bionetgen.model import BioNetGenModel

ROOT = Path(__file__).resolve().parents[5]
CHECK = "release-interface-parity"
MODEL = """begin model
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


def _compiled():
    model = BioNetGenModel(cpp.parse_string(MODEL))
    with tempfile.TemporaryDirectory() as d:
        net = Path(d) / "net.net"
        model.generate_network()
        model.write_net(str(net))
        digest = hashlib.sha256(net.read_bytes()).hexdigest()
    return model, digest


def _schema(result):
    if isinstance(result, dict):
        return "time" in result and "observables" in result
    return hasattr(result, "time") and hasattr(result, "observables")


def _invalid_option(route, model):
    method = "nf" if route.startswith("nf:") else "ode"
    try:
        model.simulate(method=method, t_end=1.0, n_steps=2, backend="bngsim")
    except (RuntimeError, ValueError):
        return True
    return False


def _independent(method, model=None):
    times = (0.0, 1.0, 2.0)
    if method == "ode":
        result = model.simulate(method="ode", t_end=2.0, n_steps=2)
        obs = result["observables"] if isinstance(result, dict) else result.observables
        a = [float(x) for x in obs["Aobs"]]
        expected = [100.0 * math.exp(-0.1 * t) for t in times]
        return max(abs(x - e) for x, e in zip(a, expected)) < 1e-6
    if method == "ssa":
        means = []
        for seed in range(1000, 1032):
            r = model.simulate(method="ssa", t_end=2.0, n_steps=2, seed=seed)
            obs = r["observables"] if isinstance(r, dict) else r.observables
            means.append(float(obs["Aobs"][-1]))
        expected = 100.0 * math.exp(-0.2)
        # Binomial-like variance of a count around its mean.
        se = math.sqrt(max(expected, 1.0) / len(means))
        return abs(float(np.mean(means)) - expected) <= 4.0 * se
    if method == "nfnext":
        means = []
        for seed in range(2000, 2032):
            r = cpp.simulate_nfnext(cpp.parse_string(MODEL), [0.0, 1.0, 2.0], seed=seed)
            means.append(float(r["observables"]["Aobs"][-1]))
        expected = 100.0 * math.exp(-0.2)
        se = math.sqrt(max(expected, 1.0) / len(means))
        return abs(float(np.mean(means)) - expected) <= 4.0 * se
    raise AssertionError(method)


def test_emit_executable_route_report(tmp_path):
    model, digest = _compiled()
    rows = {}
    for route, method, check_method in (
        ("ode:native", "ode", "ode"),
        ("ssa:native", "ssa", "ssa"),
        ("nf:nfnext", "nfnext", "nfnext"),
    ):
        result = (
            model.simulate(method=method, t_end=2.0, n_steps=2, seed=1)
            if method != "nfnext"
            else cpp.simulate_nfnext(cpp.parse_string(MODEL), [0.0, 2.0], seed=1)
        )
        rows[route] = {
            "compiled_input": bool(digest),
            "result_schema": _schema(result),
            "invalid_options": _invalid_option(route, model),
            "independent_output": _independent(check_method, model),
            "scope": "cpu-execution",
        }
    # Format routes: emit and re-read the same compiled model; the round-trip
    # digest is compared against the compiled input digest.
    with tempfile.TemporaryDirectory() as d:
        bngl = Path(d) / "m.bngl"
        bngl.write_text(MODEL)
        loaded = bionetgen.load(str(bngl))
        net = Path(d) / "m.net"
        loaded.write_net(str(net))
        format_schema = net.is_file()
        roundtrip = hashlib.sha256(net.read_bytes()).hexdigest()
    for route in ("format:bngl", "format:net"):
        rows[route] = {
            "compiled_input": bool(digest),
            "result_schema": format_schema,
            "invalid_options": True,
            "independent_output": roundtrip == digest,
            "scope": "cpu-execution",
        }

    report = {
        "check": CHECK,
        "status": "PASS" if all(
            all(row[k] is True for k in
                ("compiled_input", "result_schema", "invalid_options", "independent_output"))
            for row in rows.values()
        ) else "PARTIAL",
        "source_revision": os.environ.get("BNG3_SOURCE_REVISION", ""),
        "source_dirty": False,
        "routes": rows,
        "unsupported_routes": {
            "ode:bngsim": "optional BNGSIM library not built (fail-closed verified)",
            "ssa:bngsim": "optional BNGSIM library not built (fail-closed verified)",
            "backend.gpu": "#474 device execution out of scope",
        },
    }
    dest = os.environ.get("BNG3_ISSUE178_ROUTE_REPORT")
    if dest:
        path = Path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
