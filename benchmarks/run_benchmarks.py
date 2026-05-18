#!/usr/bin/env python3
"""Run simple performance benchmarks for the C++ backend."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

import bionetgen


MODELS = [
    ("simple_system", "tests/python/models/simple_system.bngl"),
    ("egfr_net", "tests/validation/Validate/egfr_net.bngl"),
    ("fceri_ji", "tests/validation/Validate/fceri_ji.bngl"),
    ("tlbr", "tests/validation/Validate/tlbr.bngl"),
    ("blbr", "tests/validation/Validate/blbr.bngl"),
]


def _measure(callable_obj):
    start = time.perf_counter()
    value = callable_obj()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return value, elapsed_ms


def _pick_scan_parameter(model):
    for parameter in model.parameters:
        value = getattr(parameter, "value", None)
        if value is not None:
            return parameter.name, float(value)
    return None, None


def _scan_values(nominal_value: float | None, n_points: int = 100) -> np.ndarray:
    if nominal_value is None or nominal_value <= 0:
        return np.linspace(0.1, 10.0, n_points)
    low = max(nominal_value * 0.1, 1e-6)
    high = max(nominal_value * 10.0, low * 10.0)
    return np.logspace(math.log10(low), math.log10(high), n_points)


def benchmark_model(model_name: str, model_path: Path) -> dict:
    record = {
        "model": model_name,
        "path": str(model_path),
        "n_species": None,
        "n_reactions": None,
        "parse_ms": None,
        "generate_ms": None,
        "simulate_ms": None,
        "scan_ms": None,
        "total_ms": None,
        "scan_parameter": None,
        "status": "ok",
    }

    try:
        model, parse_ms = _measure(lambda: bionetgen.load(str(model_path)))
        record["parse_ms"] = parse_ms

        network, generate_ms = _measure(model.generate_network)
        record["generate_ms"] = generate_ms
        record["n_species"] = network.num_species
        record["n_reactions"] = network.num_reactions

        _, simulate_ms = _measure(lambda: model.simulate(method="ode", t_end=50, n_steps=100))
        record["simulate_ms"] = simulate_ms

        scan_parameter, nominal_value = _pick_scan_parameter(model)
        if scan_parameter is not None:
            scan_values = _scan_values(nominal_value, n_points=100)
            _, scan_ms = _measure(
                lambda: model.parameter_scan(
                    parameter=scan_parameter,
                    values=scan_values,
                    method="ode",
                    t_end=50,
                    n_steps=100,
                )
            )
            record["scan_ms"] = scan_ms
            record["scan_parameter"] = scan_parameter

        record["total_ms"] = sum(
            value for value in [record["parse_ms"], record["generate_ms"], record["simulate_ms"]] if value is not None
        )
    except Exception as exc:  # pragma: no cover - benchmark environments vary
        record["status"] = "error"
        record["error"] = str(exc)

    return record


def _format_ms(value):
    if value is None:
        return "-"
    return f"{value:.1f}"


def _to_markdown(rows: list[dict]) -> str:
    headers = ["model", "n_species", "n_reactions", "parse_ms", "generate_ms", "simulate_ms", "scan_ms", "total_ms", "status"]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("model", "")),
                    str(row.get("n_species", "")),
                    str(row.get("n_reactions", "")),
                    _format_ms(row.get("parse_ms")),
                    _format_ms(row.get("generate_ms")),
                    _format_ms(row.get("simulate_ms")),
                    _format_ms(row.get("scan_ms")),
                    _format_ms(row.get("total_ms")),
                    str(row.get("status", "")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the BioNetGen C++ backend")
    parser.add_argument("--json", dest="json_path", type=Path, default=Path("benchmarks/results/latest.json"))
    parser.add_argument("--markdown", dest="markdown_path", type=Path, default=Path("benchmarks/results/latest.md"))
    args = parser.parse_args()

    rows = []
    for model_name, relative_path in MODELS:
        model_path = Path(relative_path)
        if model_path.exists():
            rows.append(benchmark_model(model_name, model_path))
        else:
            rows.append({"model": model_name, "path": str(model_path), "status": "missing"})

    args.json_path.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.write_text(json.dumps({"models": rows}, indent=2), encoding="utf-8")
    args.markdown_path.write_text(_to_markdown(rows) + "\n", encoding="utf-8")

    print(_to_markdown(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())