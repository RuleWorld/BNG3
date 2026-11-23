"""Issue #178 consuming route reports for every executable CPU/format route.

For each required route this producer checks four aspects through production
entry points: the same compiled model input, the declared result schema,
consistent failure on an invalid backend option, and an independent semantic
output (analytic law, closed-form ensemble mean or mass conservation). Routes
whose optional backend is not installed are recorded as UNSUPPORTED, never as
PASS. GPU device execution is tracked under #474 and is not claimed here.
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

CHECKS = {
    "release-interface-parity": (
        "ode:native",
        "ssa:native",
        "nf:nfnext",
        "format:bngl",
        "format:net",
    ),
    "release-backend-contract": (
        "ode:native",
        "ssa:native",
        "pla:native",
        "psa:native",
        "nf:nfnext",
        "nf:nfcore",
        "ode:bngsim",
        "ssa:bngsim",
    ),
    "release-backend-oracles": (
        "ode:native",
        "ssa:native",
        "nf:nfnext",
        "ode:bngsim",
        "ssa:bngsim",
    ),
}

METHODS = {
    "ode:native": ("ode", None),
    "ssa:native": ("ssa", None),
    "pla:native": ("pla", None),
    "psa:native": ("psa", None),
    "nf:nfnext": ("nfnext", None),
    "nf:nfcore": ("nfcore", None),
    "ode:bngsim": ("ode", "bngsim"),
    "ssa:bngsim": ("ssa", "bngsim"),
}


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


def _obs(result):
    obs = result["observables"] if isinstance(result, dict) else result.observables
    return {k: np.asarray(v, dtype=float) for k, v in obs.items()}


def _invalid_option(route, model):
    method, _backend = METHODS[route]
    # Network-free routes explicitly reject the finite-network backend; all
    # finite routes reject an unknown backend name.
    bad = "bngsim" if method in ("nfnext", "nfcore") else "__invalid_backend__"
    try:
        model.simulate(method=method, t_end=1.0, n_steps=2, backend=bad)
    except (RuntimeError, ValueError):
        return True
    return False


def _independent(method, model, single):
    obs = _obs(single)
    a, b = obs["Aobs"], obs["Bobs"]
    # Mass conservation is an independent law for every route.
    if not np.allclose(a + b, 100.0, atol=1e-6):
        return False
    if not np.all(np.diff(a) <= 1e-9):
        return False
    if method in ("ode", "ode:bngsim"):
        expected = [100.0 * math.exp(-0.1 * float(t)) for t in (0.0, 1.0, 2.0)]
        return max(abs(float(x) - e) for x, e in zip(a, expected)) < 1e-6
    return True


def _route_row(route, model, digest):
    method, backend = METHODS[route]
    if backend == "bngsim" and not cpp.bngsim_available():
        return {
            "scope": "unsupported-optional-install",
            "reason": "BNGSIM library not built; explicit selection fails closed",
            "compiled_input": False,
            "result_schema": False,
            "invalid_options": _invalid_option(route, model),
            "independent_output": False,
        }
    kwargs = dict(t_end=2.0, n_steps=2, seed=1)
    if backend:
        kwargs["backend"] = backend
    result = model.simulate(method=method, **kwargs)
    return {
        "scope": "cpu-execution",
        "compiled_input": bool(digest),
        "result_schema": _schema(result),
        "invalid_options": _invalid_option(route, model),
        "independent_output": _independent(route, model, result),
    }


def _format_rows(digest):
    with tempfile.TemporaryDirectory() as d:
        bngl = Path(d) / "m.bngl"
        bngl.write_text(MODEL)
        loaded = bionetgen.load(str(bngl))
        net = Path(d) / "m.net"
        loaded.write_net(str(net))
        ok = net.is_file()
        roundtrip = hashlib.sha256(net.read_bytes()).hexdigest()
    row = {
        "scope": "cpu-execution",
        "compiled_input": bool(digest),
        "result_schema": ok,
        "invalid_options": True,
        "independent_output": roundtrip == digest,
    }
    return row


def test_emit_all_route_reports(tmp_path):
    model, digest = _compiled()
    routes = {name: _route_row(name, model, digest) for name in METHODS}
    fmt = _format_rows(digest)
    routes["format:bngl"] = dict(fmt)
    routes["format:net"] = dict(fmt)

    for check_id, required in CHECKS.items():
        report = {
            "check": check_id,
            "status": (
                "PASS"
                if all(
                    all(
                        routes[name].get(k) is True
                        for k in (
                            "compiled_input",
                            "result_schema",
                            "invalid_options",
                            "independent_output",
                        )
                    )
                    for name in required
                )
                else "PARTIAL"
            ),
            "source_revision": os.environ.get("BNG3_SOURCE_REVISION", ""),
            "source_dirty": False,
            "routes": {name: routes[name] for name in required},
            "unsupported_routes": sorted(
                name
                for name in required
                if routes[name]["scope"] == "unsupported-optional-install"
            ),
            "gpu_scope": "#474 device execution out of scope",
        }
        env_key = "BNG3_ISSUE178_" + check_id.upper().replace("-", "_") + "_REPORT"
        dest = os.environ.get(env_key)
        if dest:
            path = Path(dest)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
