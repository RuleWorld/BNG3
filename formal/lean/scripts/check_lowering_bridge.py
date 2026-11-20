#!/usr/bin/env python3
"""Bounded production lowering correspondence bridge for Issue #166.

Connects a real production CompiledModel -> NFIR artifact to the formal Lean
reference evaluator for a bounded state-change rule with a non-unit rate, an
unchanged contextual site, and state-sensitive observables.

Model:
  begin model
  begin parameters
    k 0.5
  end parameters
  begin molecule types
    A(x~u~p, c~off~on)
  end molecule types
  begin seed species
    A(x~u, c~off) 1
  end seed species
  begin observables
    Molecules U A(x~u, c~off)
    Molecules P A(x~p, c~off)
  end observables
  begin reaction rules
    state_change_context: A(x~u, c~off) -> A(x~p, c~off) k
  end reaction rules
  end model

Scope/assumptions:
- Bounded unimolecular state change with an explicit contextual site constraint.
- Non-unit elementary rate (k = 0.5).
- State-sensitive observables U and P track the transition before and after firing.
- The comparator detects divergence when target state is mutated or wrong site
  is left unchanged, even when species and rule counts agree.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FORMAL_DIR = ROOT / "formal" / "lean"

# Independent reference facts (derived from biological rule semantics without Lean/C++):
INDEPENDENT_REFERENCE = {
    "rule_count": 1,
    "molecule_type": "A",
    "target_site": "x",
    "context_site": "c",
    "target_state_before": "u",
    "target_state_after": "p",
    "context_state_before": "off",
    "context_state_after": "off",
    "rate": 0.5,
    "multiplicity": 1,
    "enabled": True,
    "obs_u_before": 1,
    "obs_p_before": 0,
    "obs_u_after": 0,
    "obs_p_after": 1,
    "context_preserved": True,
    "target_updated": True,
}


def run_lean_bridge(formal_dir: Path) -> dict[str, dict[str, str]]:
    proc = subprocess.run(
        ["lake", "env", "lean", "--run", "LoweringBridge.lean"],
        cwd=formal_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Lean lowering bridge failed ({proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    rows: dict[str, dict[str, str]] = {}
    for line in proc.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = dict(item.split("=", 1) for item in line.split("\t") if "=" in item)
        if "case" in parts:
            rows[parts["case"]] = parts
    return rows


def find_native_bridge_executable() -> Path | None:
    env_dir = os.environ.get("BNG3_ARCH_TESTS_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir) / "bng3_nfnext_bng_lowering_bridge")
    candidates.extend(
        [
            ROOT
            / "build"
            / "tests"
            / "architecture_contracts"
            / "bng3_nfnext_bng_lowering_bridge",
            ROOT.parent
            / "build"
            / "tests"
            / "architecture_contracts"
            / "bng3_nfnext_bng_lowering_bridge",
        ]
    )
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


def run_native_bridge(exe_path: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [str(exe_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return (
            False,
            f"Process exited with {proc.returncode}:\n{proc.stdout}\n{proc.stderr}",
        )
    if "BNG -> NFnext lowering bridge: PASS" not in proc.stdout:
        return False, f"Pass banner missing from stdout:\n{proc.stdout}"
    return True, proc.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal-dir", default=str(FORMAL_DIR))
    parser.add_argument("--require-native", action="store_true", default=True)
    args = parser.parse_args()

    formal_dir = Path(args.formal_dir)
    failures: list[str] = []

    print("=== Step 1: Evaluating Lean formal correspondence ===")
    lean_results = run_lean_bridge(formal_dir)
    canonical = lean_results.get("state_change_context")
    if not canonical:
        print("FAIL: state_change_context missing from Lean bridge output")
        return 1

    # Verify canonical case in Lean
    mult = int(canonical.get("multiplicity", -1))
    enabled = canonical.get("enabled") == "true"
    rate = float(canonical.get("rate", 0.0))
    u_before = int(canonical.get("obs_u_before", -1))
    p_before = int(canonical.get("obs_p_before", -1))
    u_after = int(canonical.get("obs_u_after", -1))
    p_after = int(canonical.get("obs_p_after", -1))
    ctx_pres = canonical.get("context_preserved") == "true"
    tgt_upd = canonical.get("target_updated") == "true"
    low_eq_sem = canonical.get("lowered_equals_semantic") == "true"

    print(
        f"[formal] multiplicity={mult} enabled={enabled} rate={rate} "
        f"U({u_before}->{u_after}) P({p_before}->{p_after}) "
        f"ctx_preserved={ctx_pres} target_updated={tgt_upd} lowered==sem={low_eq_sem}"
    )

    if mult != INDEPENDENT_REFERENCE["multiplicity"]:
        failures.append(
            f"multiplicity: formal {mult} != ref {INDEPENDENT_REFERENCE['multiplicity']}"
        )
    if enabled != INDEPENDENT_REFERENCE["enabled"]:
        failures.append(
            f"enabled: formal {enabled} != ref {INDEPENDENT_REFERENCE['enabled']}"
        )
    if abs(rate - INDEPENDENT_REFERENCE["rate"]) > 1e-9:
        failures.append(f"rate: formal {rate} != ref {INDEPENDENT_REFERENCE['rate']}")
    if (
        u_before != INDEPENDENT_REFERENCE["obs_u_before"]
        or p_before != INDEPENDENT_REFERENCE["obs_p_before"]
    ):
        failures.append(
            f"initial observables mismatch: formal U={u_before}, P={p_before}"
        )
    if (
        u_after != INDEPENDENT_REFERENCE["obs_u_after"]
        or p_after != INDEPENDENT_REFERENCE["obs_p_after"]
    ):
        failures.append(f"final observables mismatch: formal U={u_after}, P={p_after}")
    if not ctx_pres:
        failures.append("formal evaluator reports contextual site was not preserved")
    if not tgt_upd:
        failures.append("formal evaluator reports target site was not updated")
    if not low_eq_sem:
        failures.append("formal lowered execution does not equal semantic execution")

    # Verify negative cases in Lean
    neg_target = lean_results.get("negative_mutated_target_state")
    if not neg_target or neg_target.get("divergence_detected") != "true":
        failures.append(
            "negative case (mutated target state) failed to detect divergence"
        )
    else:
        print(
            f"[formal:negative] mutated_target_state: divergence detected (P after = {neg_target.get('obs_p_after')})"
        )

    neg_wrong_site = lean_results.get("negative_wrong_site_unchanged")
    if not neg_wrong_site or neg_wrong_site.get("divergence_detected") != "true":
        failures.append(
            "negative case (wrong site unchanged) failed to detect divergence"
        )
    else:
        print(
            f"[formal:negative] wrong_site_unchanged: divergence detected (P after = {neg_wrong_site.get('obs_p_after')})"
        )

    print("\n=== Step 2: Evaluating Production Lowering Artifact ===")
    exe = find_native_bridge_executable()
    if not exe:
        if args.require_native:
            failures.append(
                "Native bng3_nfnext_bng_lowering_bridge executable not found"
            )
        else:
            print("Native bridge executable not found, skipping native execution.")
    else:
        print(f"Executing production contract: {exe}")
        ok, detail = run_native_bridge(exe)
        if not ok:
            failures.append(f"Production lowering bridge failed: {detail}")
        else:
            print(f"[production] {detail}")

    if failures:
        print("\nLOWERING CORRESPONDENCE BRIDGE FAILURES:")
        for f in failures:
            print(f"- {f}")
        return 1

    print("\nLOWERING CORRESPONDENCE BRIDGE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
