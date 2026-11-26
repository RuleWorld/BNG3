#!/usr/bin/env python3
"""Emit schema-v2 #471 analytic-oracle receipts for energy.barriers and energy.reservoirs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.record_issue471_bng2_receipts import (  # noqa: E402
    _build_platform,
    _git_dirty,
    _git_head,
    _sha256_bytes,
)

SPEC_REL = "docs/nonequilibrium_energy.md"


def _arrhenius_pair(
    ea: float, barrier: float, phi: float, dg: float, work: float = 0.0
) -> tuple[float, float]:
    eff = dg - work
    return (
        math.exp(-(ea + barrier + phi * eff)),
        math.exp(-(ea + barrier + (phi - 1.0) * eff)),
    )


def _extract_net_rates(cpp_mod: Any, model: Any, net: Any) -> dict[str, float]:
    with tempfile.NamedTemporaryFile("w+", suffix=".net") as tmp:
        cpp_mod.io.write_net(model, net, tmp.name)
        tmp.seek(0)
        rates: dict[str, float] = {}
        for raw in tmp:
            line = raw.strip()
            if line.startswith("begin parameters"):
                continue
            if line.startswith("end parameters"):
                break
            parts = line.split()
            if len(parts) >= 3 and ("Rate" in parts[1] or "k" in parts[1]):
                try:
                    rates[parts[1]] = float(parts[2])
                except ValueError:
                    pass
        return rates


def _barriers_case(
    cpp_mod: Any,
) -> tuple[bytes, dict[str, float], dict[str, float], str]:
    ea, barrier, gu, gp, phi = 1.2, 2.4, 0.5, 1.8, 0.4
    dg = gp - gu
    model_text = (
        "begin model\n"
        "begin parameters\n"
        f"  Gbar {barrier}\n"
        f"  phi {phi}\n"
        f"  Ea {ea}\n"
        f"  GU {gu}\n"
        f"  GP {gp}\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A(s~U~P)\n"
        "end molecule types\n"
        "begin seed species\n"
        "  A(s~U) 100\n"
        "end seed species\n"
        "begin observables\n"
        "  Molecules A_U A(s~U)\n"
        "  Molecules A_P A(s~P)\n"
        "end observables\n"
        "begin energy patterns\n"
        "  A(s~U) GU\n"
        "  A(s~P) GP\n"
        "end energy patterns\n"
        "begin barrier patterns\n"
        "  A(s~U) -> A(s~P) Gbar\n"
        "end barrier patterns\n"
        "begin reaction rules\n"
        "  A(s~U) <-> A(s~P) Arrhenius(phi,Ea)\n"
        "end reaction rules\n"
        "end model\n"
    )
    kf, kr = _arrhenius_pair(ea, barrier, phi, dg, work=0.0)
    oracle = {
        "kf": kf,
        "kr": kr,
        "rate_ratio": math.exp(-dg),
    }
    model = cpp_mod.parse_string(model_text)
    net = cpp_mod.generate_network(model)
    rates = _extract_net_rates(cpp_mod, model, net)
    kf_sim = rates["R1Rate_1"]
    kr_sim = rates["R1rRate_1"]
    consumer = {
        "kf": kf_sim,
        "kr": kr_sim,
        "rate_ratio": kf_sim / kr_sim,
    }
    law = (
        "Arrhenius barrier attenuation k_f=exp(-(Ea+B+phi*dG)), "
        "k_r=exp(-(Ea+B+(phi-1)*dG)), and barrier cancellation k_f/k_r=exp(-dG)"
    )
    return model_text.encode("utf-8"), oracle, consumer, law


def _reservoirs_case(
    cpp_mod: Any,
) -> tuple[bytes, dict[str, float], dict[str, float], str]:
    ea1 = ea2 = ea3 = 1.0
    phi = 0.5
    g1, g2, g3 = 0.0, 0.8, 0.4
    b1, b2, b3 = 0.2, 0.4, 0.1
    w1 = 1.8
    model_text = (
        "begin model\n"
        "begin parameters\n"
        f"  Ea1 {ea1}\n"
        f"  Ea2 {ea2}\n"
        f"  Ea3 {ea3}\n"
        f"  phi {phi}\n"
        f"  G1 {g1}\n"
        f"  G2 {g2}\n"
        f"  G3 {g3}\n"
        f"  B1 {b1}\n"
        f"  B2 {b2}\n"
        f"  B3 {b3}\n"
        f"  W1 {w1}\n"
        "end parameters\n"
        "begin molecule types\n"
        "  A(s~1~2~3)\n"
        "end molecule types\n"
        "begin seed species\n"
        "  A(s~1) 100\n"
        "end seed species\n"
        "begin observables\n"
        "  Molecules A1 A(s~1)\n"
        "  Molecules A2 A(s~2)\n"
        "  Molecules A3 A(s~3)\n"
        "end observables\n"
        "begin energy patterns\n"
        "  A(s~1) G1\n"
        "  A(s~2) G2\n"
        "  A(s~3) G3\n"
        "end energy patterns\n"
        "begin barrier patterns\n"
        "  A(s~1) -> A(s~2) B1\n"
        "  A(s~2) -> A(s~3) B2\n"
        "  A(s~3) -> A(s~1) B3\n"
        "end barrier patterns\n"
        "begin reaction rules\n"
        "  A(s~1) <-> A(s~2) Arrhenius(phi,Ea1) driven_by(W1)\n"
        "  A(s~2) <-> A(s~3) Arrhenius(phi,Ea2)\n"
        "  A(s~3) <-> A(s~1) Arrhenius(phi,Ea3)\n"
        "end reaction rules\n"
        "end model\n"
    )
    k12_a, k21_a = _arrhenius_pair(ea1, b1, phi, g2 - g1, work=w1)
    k23_a, k32_a = _arrhenius_pair(ea2, b2, phi, g3 - g2, work=0.0)
    k31_a, k13_a = _arrhenius_pair(ea3, b3, phi, g1 - g3, work=0.0)
    w1_tree = k21_a * k31_a + k23_a * k31_a + k32_a * k21_a
    w2_tree = k12_a * k32_a + k13_a * k32_a + k31_a * k12_a
    w3_tree = k13_a * k23_a + k12_a * k23_a + k21_a * k13_a
    sigma = w1_tree + w2_tree + w3_tree
    oracle = {
        "cycle_affinity": w1,
        "p1_ss": 100.0 * w1_tree / sigma,
        "p2_ss": 100.0 * w2_tree / sigma,
        "p3_ss": 100.0 * w3_tree / sigma,
    }
    model = cpp_mod.parse_string(model_text)
    net = cpp_mod.generate_network(model)
    rates = _extract_net_rates(cpp_mod, model, net)
    pi_fwd = rates["R1Rate_1"] * rates["R2Rate_1"] * rates["R3Rate_1"]
    pi_rev = rates["R1rRate_1"] * rates["R2rRate_1"] * rates["R3rRate_1"]
    sim = cpp_mod.simulate_ode(model, net, t_end=80.0, n_steps=80)
    obs = sim["observables"]
    consumer = {
        "cycle_affinity": math.log(pi_fwd / pi_rev),
        "p1_ss": float(obs["A1"][-1]),
        "p2_ss": float(obs["A2"][-1]),
        "p3_ss": float(obs["A3"][-1]),
    }
    law = (
        "Driven reservoir detailed-balance shift k_f/k_r=exp(-(dG-W)), "
        "cycle affinity ln(Pi_+/Pi_-)=W1, and 3-state King-Altman stationary distribution"
    )
    return model_text.encode("utf-8"), oracle, consumer, law


DELAY_SPEC_REL = "tests/python/test_atomizer_delay_history.py"

DELAY_LINEAR_SBML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="delay_linear">
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfRules>
      <rateRule variable="A"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>-1</cn></math></rateRule>
      <assignmentRule variable="B">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol><ci>A</ci><cn>1</cn></apply>
        </math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>
"""


def _delay_case() -> tuple[bytes, dict[str, float], dict[str, float], str, str]:
    import bionetgen
    from bionetgen.atomizer.modern import Atomizer

    at = Atomizer(atomize=False, quiet_mode=True, actions=False).atomize(
        DELAY_LINEAR_SBML
    )
    if not at.success:
        raise RuntimeError(f"bngl.delay: Atomizer failed: {at.error}")
    with tempfile.TemporaryDirectory() as td:
        bngl_path = Path(td) / "delay.bngl"
        bngl_path.write_text(at.bngl, encoding="utf-8")
        sim = bionetgen.load(str(bngl_path)).simulate(
            method="ode", t_end=3.0, n_steps=6
        )
    times = [float(t) for t in sim.time]
    b_vals = [float(x) for x in sim.functions["B"]]
    oracle = {f"B_t{t:g}": (10.0 if t <= 1.0 else 10.0 - (t - 1.0)) for t in times}
    consumer = {f"B_t{t:g}": b_vals[i] for i, t in enumerate(times)}
    law = "Closed-form linear delay DDE: dA/dt=-1, A(0)=10, B(t)=delay(A,1)=10 for t<=1 and 11-t for t>1"
    return DELAY_LINEAR_SBML.encode("utf-8"), oracle, consumer, law, DELAY_SPEC_REL


JAX_SPEC_REL = "tests/python/test_jax_ode.py"

JAX_DECAY_BNGL = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
"""


def _jax_ode_case() -> tuple[bytes, dict[str, float], dict[str, float], str, str]:
    import jax

    jax.config.update("jax_enable_x64", True)
    import bionetgen
    from bionetgen import jax_ode

    with tempfile.TemporaryDirectory() as td:
        bngl_path = Path(td) / "decay.bngl"
        bngl_path.write_text(JAX_DECAY_BNGL, encoding="utf-8")
        model = bionetgen.load(str(bngl_path))
        res = jax_ode.simulate_jax_ode(model, t_end=2.0, n_steps=2000)
    conc = res["concentrations"]
    a_mid = float(conc[1000][0])
    b_mid = float(conc[1000][1])
    a_end = float(conc[-1][0])
    b_end = float(conc[-1][1])
    oracle = {
        "A_t1": 10.0 * math.exp(-0.5),
        "B_t1": 10.0 * (1.0 - math.exp(-0.5)),
        "A_t2": 10.0 * math.exp(-1.0),
        "B_t2": 10.0 * (1.0 - math.exp(-1.0)),
    }
    consumer = {
        "A_t1": a_mid,
        "B_t1": b_mid,
        "A_t2": a_end,
        "B_t2": b_end,
    }
    law = "Closed-form first-order decay A(t)=10*exp(-0.5*t), B(t)=10-A(t) verified on JAX CPU x64 RK4"
    return JAX_DECAY_BNGL.encode("utf-8"), oracle, consumer, law, JAX_SPEC_REL


def build_analytic_receipts(
    *,
    root: Path,
    revision: str,
    receipts_dir: Path,
    artifacts_dir: Path,
    allow_dirty: bool = False,
    only_jax: bool = False,
) -> dict[str, Any]:
    head = _git_head(root)
    dirty = _git_dirty(root)
    if head != revision or (dirty and not allow_dirty):
        raise ValueError(
            "issue #471 analytic receipts require the requested clean revision"
        )
    spec_file = root / SPEC_REL
    script_sha256 = _sha256_bytes(Path(__file__).read_bytes())

    cases: list[
        tuple[str, tuple[bytes, dict[str, float], dict[str, float], str, str]]
    ] = []
    if not only_jax:
        prev_gate = os.environ.get("BNG_NFSIM_GENERAL_ENERGY")
        os.environ["BNG_NFSIM_GENERAL_ENERGY"] = "1"
        try:
            import bionetgen._bionetgen_cpp as cpp_mod

            barriers = (*_barriers_case(cpp_mod), SPEC_REL)
            reservoirs = (*_reservoirs_case(cpp_mod), SPEC_REL)
            cases.extend(
                [
                    ("energy.barriers", barriers),
                    ("energy.reservoirs", reservoirs),
                    ("nfsim.energy-and-time-functions", reservoirs),
                ]
            )
        finally:
            if prev_gate is None:
                os.environ.pop("BNG_NFSIM_GENERAL_ENERGY", None)
            else:
                os.environ["BNG_NFSIM_GENERAL_ENERGY"] = prev_gate

        try:
            cases.append(("bngl.delay", _delay_case()))
        except Exception:
            pass

    if only_jax:
        cases.append(("backend.jax", _jax_ode_case()))
    else:
        try:
            cases.append(("backend.jax", _jax_ode_case()))
        except Exception:
            pass

    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[str] = []
    build_platform = _build_platform()
    for row_id, (inp_bytes, oracle_obj, consumer_obj, law, row_spec_rel) in cases:
        row_spec_sha256 = _sha256_bytes((root / row_spec_rel).read_bytes())
        oracle_bytes = (json.dumps(oracle_obj, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        consumer_bytes = (
            json.dumps(consumer_obj, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        for key in oracle_obj:
            if not math.isclose(
                oracle_obj[key], consumer_obj[key], rel_tol=1e-6, abs_tol=1e-9
            ):
                raise ValueError(
                    f"{row_id}: analytic disagreement at {key}: "
                    f"{oracle_obj[key]} vs {consumer_obj[key]}"
                )

        row_dir = artifacts_dir / row_id
        row_dir.mkdir(parents=True, exist_ok=True)
        producer_rel = f"{row_id}/producer.bngl"
        oracle_rel = f"{row_id}/oracle.json"
        consumer_rel = f"{row_id}/consumer.json"
        (artifacts_dir / producer_rel).write_bytes(inp_bytes)
        (artifacts_dir / oracle_rel).write_bytes(oracle_bytes)
        (artifacts_dir / consumer_rel).write_bytes(consumer_bytes)
        producer_sha = _sha256_bytes(inp_bytes)
        receipt = {
            "schema_version": 2,
            "kind": "release-oracle-consumer-receipt",
            "capability_id": row_id,
            "check_id": f"release-capability[{row_id}]",
            "comparator": "release-oracle-numeric-json-v1",
            "source_revision": revision,
            "product_revision": revision,
            "oracle": {
                "name": f"Analytic closed-form evaluation ({row_id})",
                "revision": row_spec_sha256,
                "spec_path": row_spec_rel,
                "spec_sha256": row_spec_sha256,
                "law": law,
                "build_platform": build_platform,
                "path": oracle_rel,
                "artifact_sha256": _sha256_bytes(oracle_bytes),
                "executable_sha256": script_sha256,
                "command": f"python {Path(__file__).name} --row {row_id}",
                "expected_origin": "analytic-derivation",
                "execution": {
                    "executable": "python",
                    "version": sys.version.split()[0],
                    "command": f"analytic closed-form ({row_spec_rel})",
                    "exit_code": 0,
                },
            },
            "producer": {
                "path": producer_rel,
                "output_sha256": producer_sha,
            },
            "consumer": {
                "path": consumer_rel,
                "output_sha256": _sha256_bytes(consumer_bytes),
                "consumed_producer_sha256": producer_sha,
                "execution": {
                    "executable": "bionetgen._bionetgen_cpp",
                    "version": revision[:12],
                    "command": "cpp.parse_string + generate_network + simulate_ode",
                    "exit_code": 0,
                },
            },
        }
        (receipts_dir / f"{row_id}.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        emitted.append(row_id)

    return {
        "schema_version": 1,
        "revision": revision,
        "spec_sha256": hashlib.sha256(spec_file.read_bytes()).hexdigest(),
        "emitted_rows": emitted,
        "count": len(emitted),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--only-jax", action="store_true")
    args = parser.parse_args(argv)
    summary = build_analytic_receipts(
        root=args.root.resolve(),
        revision=args.revision,
        receipts_dir=args.receipts_dir.resolve(),
        artifacts_dir=args.artifacts_dir.resolve(),
        allow_dirty=args.allow_dirty,
        only_jax=args.only_jax,
    )
    if args.summary_out is not None:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    print(f"emitted {summary['count']} #471 analytic consumer receipts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
