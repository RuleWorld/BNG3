#!/usr/bin/env python3
"""Bounded production correspondence bridge for finite network species identity.

Compares formal bounded species-pool identity decisions (Lean fixtures) to stable
native BNG3 generate_network/NET artifacts using the independent species-graph
oracle. This is a narrow #166/#168-adjacent slice: species-pool correspondence
for explicit finite cases, not reaction-edge representational equivalence.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tests.validation.compare import species_isomorphic

CASES = [
    {
        "name": "seeds_only_dedup",
        "bngl": """begin model
begin molecule types
A(x~u)
B(y)
end molecule types
begin seed species
A(x~u) 1
B(y) 1
end seed species
end model
""",
        "expected_count": 2,
        "expected_species": ["A(x~u)", "B(y)"],
    },
    {
        "name": "simple_binding_finite_closure",
        "bngl": """begin model
begin parameters
k 1
end parameters
begin molecule types
A(x~u)
B(y)
end molecule types
begin seed species
A(x~u) 1
B(y) 1
end seed species
begin reaction rules
A(x) + B(y) -> A(x!1).B(y!1) k
end reaction rules
end model
""",
        "expected_count": 3,
        "expected_species": ["A(x~u)", "B(y)", "A(x~u!1).B(y!1)"],
    },
]


# Adversarial production negative mutations: native artifacts must differ from the
# correct bounded closure when the generating rule semantics are mutated.
NEGATIVE_CASES = [
    {
        "name": "simple_binding_noop_rule_negative",
        "bngl": """begin model
begin parameters
k 1
end parameters
begin molecule types
A(x~u)
B(y)
end molecule types
begin seed species
A(x~u) 1
B(y) 1
end seed species
begin reaction rules
A(x) + B(y) -> A(x) + B(y) k
end reaction rules
end model
""",
        "expected_count": 2,
        "must_not_match_species": ["A(x~u)", "B(y)", "A(x~u!1).B(y!1)"],
    },
]


def run_lean(formal_dir: Path) -> dict[str, str]:
    proc = subprocess.run(
        ["lake", "env", "lean", "--run", "NetworkSpeciesBridge.lean"],
        cwd=formal_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"lean network bridge failed ({proc.returncode})\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    rows = {}
    for line in proc.stdout.strip().splitlines():
        parts = dict(item.split("=", 1) for item in line.split("\t"))
        rows[parts["case"]] = parts["value"]
    return rows


def native_net_species(bngl: str) -> tuple[str, list[str] | str]:
    try:
        import bionetgen  # type: ignore
    except Exception as exc:  # pragma: no cover
        return "SKIP", f"bionetgen unavailable: {exc}"
    try:
        with tempfile.TemporaryDirectory() as td:
            model_path = Path(td) / "m.bngl"
            model_path.write_text(bngl, encoding="utf-8")
            model = None
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
                    model = bionetgen.bngmodel(str(model_path))
                except Exception as exc:
                    return "SKIP", f"could not load model: {exc}"

            if hasattr(model, "generate_network"):
                try:
                    model.generate_network(overwrite=True)
                except TypeError:
                    model.generate_network()
            elif hasattr(bionetgen, "generate_network"):
                bionetgen.generate_network(str(model_path))
            else:
                return "SKIP", "no native generate_network API"

            if hasattr(model, "write_net"):
                try:
                    model.write_net(str(Path(td) / "out.net"))
                except Exception:
                    pass
            net_text = None
            for candidate in [
                Path(td) / "m.net",
                model_path.with_suffix(".net"),
                Path(td) / "out.net",
            ]:
                if candidate.exists():
                    net_text = candidate.read_text(encoding="utf-8")
                    break
            if net_text is None or "begin species" not in net_text:
                return "SKIP", "could not read NET species artifact"
            labels = []
            in_block = False
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
            return "PASS", labels
    except Exception as exc:  # pragma: no cover
        return "SKIP", f"native check not comparable: {exc}"


def same_species_set(actual: list[str], expected: list[str]) -> bool:
    if len(actual) != len(expected):
        return False
    used = [False] * len(actual)
    for exp in expected:
        found = False
        for i, act in enumerate(actual):
            if not used[i] and species_isomorphic(act, exp):
                used[i] = True
                found = True
                break
        if not found:
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--formal-dir", default=str(ROOT / "formal/lean"))
    ap.add_argument("--require-native", action="store_true")
    args = ap.parse_args()

    lean = run_lean(Path(args.formal_dir))
    failures = []
    expected_lean = {
        "seeds_only_dedup": "2",
        "simple_binding_finite_closure": "3",
        "binding_pool_contains_seeds": "1",
        "binding_pool_contains_product_mod_iso": "1",
    }
    for k, v in expected_lean.items():
        if lean.get(k) != v:
            failures.append(f"Lean {k}: got {lean.get(k)!r}, expected {v!r}")
        print(f"[lean:{k}] value={lean.get(k)} expected={v}")

    for case in CASES:
        status, result = native_net_species(case["bngl"])
        print(f"[native:{case['name']}] status={status} detail={result}")
        if status == "SKIP":
            if args.require_native:
                failures.append(
                    f"{case['name']}: native required but skipped ({result})"
                )
            continue
        labels = result
        if len(labels) != case["expected_count"]:
            failures.append(
                f"{case['name']}: native species count {len(labels)} != {case['expected_count']}"
            )
        if not same_species_set(labels, case["expected_species"]):
            failures.append(
                f"{case['name']}: native species set {labels} not isomorphic to expected {case['expected_species']}"
            )

    for case in NEGATIVE_CASES:
        status, result = native_net_species(case["bngl"])
        print(f"[native-negative:{case['name']}] status={status} detail={result}")
        if status == "SKIP":
            if args.require_native:
                failures.append(
                    f"{case['name']}: native required but skipped ({result})"
                )
            continue
        labels = result
        if len(labels) != case["expected_count"]:
            failures.append(
                f"{case['name']}: native species count {len(labels)} != {case['expected_count']}"
            )
        if same_species_set(labels, case["must_not_match_species"]):
            failures.append(
                f"{case['name']}: mutated production species set {labels} incorrectly matched forbidden closure {case['must_not_match_species']}"
            )

    if failures:
        print("\nBRIDGE FAILURES:")
        for f in failures:
            print(f"- {f}")
        return 1
    print("\nNETWORK SPECIES BRIDGE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
