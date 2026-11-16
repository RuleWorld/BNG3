#!/usr/bin/env python3
"""Independently checked bridge for #168 graph identity (formal <-> production artifacts).

Runs the Lean formal oracle on named fixtures (permutations and negative mutations)
and compares decisions against the independent NET-species graph oracle from
tests.validation.compare. When bionetgen is importable, also validates that
native network generation deduplicates/retains the corresponding seed species.

This is a narrow bridge: it does not claim full semantic equality or production
correspondence beyond these explicit graph-identity cases.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tests.validation.compare import species_isomorphic

CASES = [
    {
        "name": "bonded_renamed_equal",
        "left": "A(x~u!1).B(y!1)",
        "right": "B(y!9).A(x~u!9)",
        "expect_iso": True,
    },
    {
        "name": "bonded_state_mutation_unequal",
        "left": "A(x~u!1).B(y!1)",
        "right": "A(x~p!1).B(y!1)",
        "expect_iso": False,
    },
    {
        "name": "bonded_topology_mutation_unequal",
        "left": "A(x~u!1).B(y!1)",
        "right": "A(x~u).B(y)",
        "expect_iso": False,
    },
    {
        "name": "bonded_attachment_mutation_unequal",
        "left": "A(x~u!1).B(y!1)",
        "right": "A(x~u!1).B(x~u!1)",
        "expect_iso": False,
    },
    {
        "name": "ring_permutation_equal",
        "left": "A(a!1,b!2).A(a!2,b!3).A(a!3,b!1)",
        "right": "A(b!30,a!10).A(b!20,a!30).A(b!10,a!20)",
        "expect_iso": True,
    },
    {
        "name": "ring_open_mutation_unequal",
        "left": "A(a!1,b!2).A(a!2,b!3).A(a!3,b!1)",
        "right": "A(a,b!2).A(a!2,b!3).A(a!3,b!1)",
        "expect_iso": False,
    },
    {
        "name": "dimer_state_permutation_equal",
        "left": "A(x~u!1).A(x~p!1)",
        "right": "A(x~p!1).A(x~u!1)",
        "expect_iso": True,
    },
    {
        "name": "dimer_state_mutation_unequal",
        "left": "A(x~u!1).A(x~p!1)",
        "right": "A(x~u!1).A(x~u!1)",
        "expect_iso": False,
    },
    {
        "name": "chain_permutation_equal",
        "left": "A(x~u!1).B(y!1,x~u!2).B(y!2)",
        "right": "B(y!5,x~u!4).B(y!4).A(x~u!5)",
        "expect_iso": True,
    },
    {
        "name": "chain_broken_end_unequal",
        "left": "A(x~u!1).B(y!1,x~u!2).B(y!2)",
        "right": "A(x~u!1).B(y!1,x~u).B(y)",
        "expect_iso": False,
    },
    {
        "name": "chain_wrong_type_unequal",
        "left": "A(x~u!1).B(y!1,x~u!2).B(y!2)",
        "right": "B(x~u!1).B(y!1,x~u!2).B(y!2)",
        "expect_iso": False,
    },
]


def run_lean(formal_dir: Path) -> dict[str, dict[str, str]]:
    proc = subprocess.run(
        ["lake", "env", "lean", "--run", "GraphIdentityBridge.lean"],
        cwd=formal_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"lean bridge runner failed ({proc.returncode})\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    rows = {}
    for line in proc.stdout.strip().splitlines():
        parts = dict(item.split("=", 1) for item in line.split("\t"))
        rows[parts["case"]] = parts
    return rows


def oracle_partition(seeds: list[str]) -> list[str]:
    reps: list[str] = []
    for seed in seeds:
        if not any(species_isomorphic(seed, rep) for rep in reps):
            reps.append(seed)
    return reps


def try_native(case: dict, expect_iso: bool) -> tuple[str, str | None]:
    """Best-effort validation against native BNG3 stable NET artifacts.

    Checks (when comparable): seed species count after network generation and
    whether NET species canonical labels identify the two seeds as the same
    production species artifact iff the case expects graph identity.
    Returns PASS on agreement, FAIL on a comparable disagreement, or SKIP when
    the native toolchain/API is unavailable or cannot produce a comparable
    artifact in this environment.
    """
    try:
        import bionetgen  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        return "SKIP", f"bionetgen unavailable: {exc}"

    try:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            model_path = Path(td) / "m.bngl"
            model_path.write_text(
                "begin model\n"
                "begin molecule types\nA(x~u~p,a,b)\nB(y,x~u~p)\nend molecule types\n"
                "begin seed species\n"
                f"{case['left']} 1\n{case['right']} 1\n"
                "end seed species\n"
                "end model\n",
                encoding="utf-8",
            )

            model = None
            # Prefer modern API object exposing generate_network/write_net.
            try:
                candidate = bionetgen.load(str(model_path))
                if hasattr(candidate, "generate_network") or hasattr(
                    candidate, "write_net"
                ):
                    model = candidate
            except Exception:
                model = None
            if model is None:
                try:
                    candidate = bionetgen.bngmodel(str(model_path))
                    model = candidate
                except Exception as exc:
                    return "SKIP", f"could not load model via bionetgen API: {exc}"

            if hasattr(model, "generate_network"):
                try:
                    model.generate_network(overwrite=True)
                except TypeError:
                    try:
                        model.generate_network()
                    except Exception as exc:
                        return "SKIP", f"native generate_network unavailable: {exc}"
                except Exception as exc:
                    return "SKIP", f"native generate_network unavailable: {exc}"
            elif hasattr(bionetgen, "generate_network"):
                try:
                    bionetgen.generate_network(str(model_path))
                except Exception as exc:
                    return "SKIP", f"native generate_network unavailable: {exc}"
            else:
                return "SKIP", "no native generate_network API"

            net_text = None
            net_candidates = [
                Path(td) / "m.net",
                Path(str(model_path).replace(".bngl", ".net")),
                Path(td) / "out.net",
            ]
            # Prefer explicit artifact export when available.
            if hasattr(model, "write_net"):
                try:
                    model.write_net(str(Path(td) / "out.net"))
                except Exception:
                    pass
            for candidate in net_candidates:
                try:
                    if candidate.exists():
                        net_text = candidate.read_text(encoding="utf-8")
                        break
                except Exception:
                    pass
            if net_text is None or "begin species" not in net_text:
                return "SKIP", "could not read native NET species artifact"

            in_block = False
            labels: list[str] = []
            for line in net_text.splitlines():
                sline = line.strip()
                if sline.startswith("begin species"):
                    in_block = True
                    continue
                if in_block and sline.startswith("end species"):
                    break
                if in_block and sline and not sline.startswith("#"):
                    parts = sline.split()
                    if len(parts) >= 2:
                        labels.append(parts[1])
            count = len(labels)
            expected = 1 if expect_iso else 2
            if count != expected:
                return "FAIL", f"native species count {count} != expected {expected}"
            if len(labels) >= 2:
                same_label = labels[0] == labels[1]
                if same_label != expect_iso:
                    return (
                        "FAIL",
                        f"native NET canonical label equality {same_label} != expected {expect_iso}",
                    )
            elif expect_iso and len(labels) != 1:
                return (
                    "FAIL",
                    f"native species labels {labels} != single merged species",
                )
            return "PASS", None
    except Exception as exc:  # pragma: no cover - environment dependent
        return "SKIP", f"native check not comparable in this environment: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--formal-dir", default=str(ROOT / "formal/lean"))
    ap.add_argument("--require-native", action="store_true")
    args = ap.parse_args()

    formal = run_lean(Path(args.formal_dir))
    failures = []
    for case in CASES:
        name = case["name"]
        expect_iso = case["expect_iso"]
        lean = formal.get(name)
        if lean is None:
            failures.append(f"{name}: missing from Lean bridge output")
            continue
        lean_iso = lean["iso"] == "true"
        lean_dedup = int(lean["dedup_pool"])
        oracle_iso = species_isomorphic(case["left"], case["right"])
        oracle_dedup = len(oracle_partition([case["left"], case["right"]]))
        expected_dedup = 1 if expect_iso else 2

        print(
            f"[{name}] expect_iso={expect_iso} lean_iso={lean_iso} lean_dedup={lean_dedup} oracle_iso={oracle_iso} oracle_dedup={oracle_dedup}"
        )
        if lean_iso != expect_iso:
            failures.append(f"{name}: Lean iso {lean_iso} != expected {expect_iso}")
        if lean_dedup != expected_dedup:
            failures.append(
                f"{name}: Lean dedup {lean_dedup} != expected {expected_dedup}"
            )
        if oracle_iso != expect_iso:
            failures.append(
                f"{name}: independent oracle iso {oracle_iso} != expected {expect_iso}"
            )
        if oracle_dedup != expected_dedup:
            failures.append(
                f"{name}: independent oracle dedup {oracle_dedup} != expected {expected_dedup}"
            )
        if lean_iso != oracle_iso:
            failures.append(
                f"{name}: Lean/oracle iso disagreement ({lean_iso} vs {oracle_iso})"
            )

        native_status, native_detail = try_native(case, expect_iso)
        print(
            f"[{name}] native={native_status}"
            + (f" detail={native_detail}" if native_detail else "")
        )
        if native_status == "FAIL":
            failures.append(f"{name}: native {native_detail}")
        if args.require_native and native_status != "PASS":
            failures.append(
                f"{name}: native required but got {native_status} ({native_detail})"
            )

    if failures:
        print("\nBRIDGE FAILURES:")
        for f in failures:
            print(f"- {f}")
        return 1
    print("\nGRAPH IDENTITY BRIDGE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
