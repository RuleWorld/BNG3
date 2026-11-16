#!/usr/bin/env python3
"""Bounded native NET reaction correspondence for stable #166/#167-adjacent cases.

Compares stable production artifacts (native BNG3 generate_network/NET reactions)
to independently stated expectations for explicit finite models.

Assumptions/scope (exact):
- Cases use distinct species instances/patterns with no symmetric self-reaction
  statistical-factor ambiguity (no A+A->... rules).
- "Correspondence" checked here: reaction count, reactant/product species sets
  modulo independent graph-isomorphism oracle, and rate token/value equality to
  the declared parameter or numeric rate for each expected reaction instance.
- This does NOT claim full lowering/propensity-engine trajectory equivalence,
  stochastic semantics, MatchOnce/TotalRate statistical-factor behavior beyond
  these explicit artifacts, or NFnext-moving behavior.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tests.validation.compare import species_isomorphic


def parse_net(text: str):
    species: dict[int, str] = {}
    reactions = []
    in_species = in_reactions = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("begin species"):
            in_species = True
            continue
        if line.startswith("end species"):
            in_species = False
            continue
        if line.startswith("begin reactions"):
            in_reactions = True
            continue
        if line.startswith("end reactions"):
            in_reactions = False
            continue
        if in_species and not line.startswith("#"):
            # idx pattern count
            m = re.match(r"^(\d+)\s+(\S+)", line)
            if m:
                species[int(m.group(1))] = m.group(2)
        if in_reactions and not line.startswith("#"):
            # idx reactants products rate [#rule]
            # reactants/products comma-separated; may be 0
            parts = line.split()
            if len(parts) < 4:
                continue
            ridx = int(parts[0])

            def parse_side(tok):
                if tok == "0":
                    return []
                return [int(x) for x in tok.split(",") if x]

            reactants = parse_side(parts[1])
            products = parse_side(parts[2])
            rate = parts[3]
            reactions.append(
                {
                    "idx": ridx,
                    "reactants": reactants,
                    "products": products,
                    "rate": rate,
                    "raw": line,
                }
            )
    return species, reactions


def generate_net(bngl: str) -> str:
    try:
        import bionetgen  # type: ignore
    except Exception as e:
        raise RuntimeError(f"bionetgen unavailable: {e}")
    with tempfile.TemporaryDirectory() as td:
        model_path = Path(td) / "m.bngl"
        model_path.write_text(bngl, encoding="utf-8")
        try:
            model = bionetgen.load(str(model_path))
        except Exception:
            model = bionetgen.bngmodel(str(model_path))
        # prefer native API
        if hasattr(model, "generate_network"):
            try:
                model.generate_network(overwrite=True)
            except TypeError:
                model.generate_network()
        else:
            raise RuntimeError("no generate_network API")
        if hasattr(model, "write_net"):
            try:
                model.write_net(str(Path(td) / "out.net"))
            except Exception:
                pass
        for cand in [
            Path(td) / "out.net",
            Path(td) / "m.net",
            Path(str(model_path).replace(".bngl", ".net")),
        ]:
            if cand.exists() and "begin reactions" in cand.read_text(
                encoding="utf-8", errors="ignore"
            ):
                return cand.read_text(encoding="utf-8")
        # fallback: search
        for cand in Path(td).glob("*.net"):
            txt = cand.read_text(encoding="utf-8", errors="ignore")
            if "begin reactions" in txt:
                return txt
        raise RuntimeError("could not locate NET artifact")


def canon_reaction(r, species):
    def names(ids):
        return sorted(species[i] for i in ids)

    return (tuple(names(r["reactants"])), tuple(names(r["products"])), r["rate"])


def species_match_set(actual: list[str], expected: list[str]) -> bool:
    if len(actual) != len(expected):
        return False
    used = [False] * len(actual)
    for e in expected:
        found = False
        for i, a in enumerate(actual):
            if not used[i] and species_isomorphic(a, e):
                used[i] = True
                found = True
                break
        if not found:
            return False
    return True


CASES = [
    {
        "name": "simple_binding_distinct_species",
        "bngl": """begin model
begin parameters
k 1
end parameters
begin molecule types
A(x)
B(y)
end molecule types
begin seed species
A(x) 1
B(y) 1
end seed species
begin reaction rules
A(x)+B(y)->A(x!1).B(y!1) k
end reaction rules
end model
""",
        "expected_reaction_count": 1,
        "expected_reactions": [
            {"reactants": ["A(x)", "B(y)"], "products": ["A(x!1).B(y!1)"], "rate": "k"},
        ],
    },
    {
        "name": "unimolecular_dissociation_distinct",
        "bngl": """begin model
begin parameters
k 1
end parameters
begin molecule types
A(x)
B(y)
end molecule types
begin seed species
A(x!1).B(y!1) 1
end seed species
begin reaction rules
A(x!1).B(y!1)->A(x)+B(y) k
end reaction rules
end model
""",
        "expected_reaction_count": 1,
        "expected_reactions": [
            {"reactants": ["A(x!1).B(y!1)"], "products": ["A(x)", "B(y)"], "rate": "k"},
        ],
    },
    {
        "name": "reversible_binding_distinct_species",
        "bngl": """begin model
begin parameters
kon 1
koff 1
end parameters
begin molecule types
A(x)
B(y)
end molecule types
begin seed species
A(x) 1
B(y) 1
end seed species
begin reaction rules
A(x)+B(y)<->A(x!1).B(y!1) kon,koff
end reaction rules
end model
""",
        "expected_reaction_count": 2,
        "expected_reactions": [
            {
                "reactants": ["A(x)", "B(y)"],
                "products": ["A(x!1).B(y!1)"],
                "rate": "kon",
            },
            {
                "reactants": ["A(x!1).B(y!1)"],
                "products": ["A(x)", "B(y)"],
                "rate": "koff",
            },
        ],
    },
    {
        "name": "unimolecular_state_change_distinct",
        "bngl": """begin model
begin parameters
k 1
end parameters
begin molecule types
A(x~u~p)
end molecule types
begin seed species
A(x~u) 1
end seed species
begin reaction rules
A(x~u)->A(x~p) k
end reaction rules
end model
""",
        "expected_reaction_count": 1,
        "expected_reactions": [
            {"reactants": ["A(x~u)"], "products": ["A(x~p)"], "rate": "k"},
        ],
    },
    {
        "name": "unimolecular_degradation_distinct",
        "bngl": """begin model
begin parameters
k 1
end parameters
begin molecule types
A(x)
end molecule types
begin seed species
A(x) 1
end seed species
begin reaction rules
A(x)->0 k
end reaction rules
end model
""",
        "expected_reaction_count": 1,
        "expected_reactions": [
            {"reactants": ["A(x)"], "products": [], "rate": "k"},
        ],
    },
]


NEGATIVE_CASES = [
    {
        "name": "simple_binding_product_mutation_negative",
        "bngl": """begin model
begin parameters
k 1
end parameters
begin molecule types
A(x)
B(y)
end molecule types
begin seed species
A(x) 1
B(y) 1
end seed species
begin reaction rules
A(x)+B(y)->A(x)+B(y) k
end reaction rules
end model
""",
        "must_not_match_reactions": [
            {"reactants": ["A(x)", "B(y)"], "products": ["A(x!1).B(y!1)"], "rate": "k"},
        ],
    },
    {
        "name": "simple_binding_rate_token_negative",
        "bngl": """begin model
begin parameters
j 1
end parameters
begin molecule types
A(x)
B(y)
end molecule types
begin seed species
A(x) 1
B(y) 1
end seed species
begin reaction rules
A(x)+B(y)->A(x!1).B(y!1) j
end reaction rules
end model
""",
        "must_not_match_reactions": [
            {"reactants": ["A(x)", "B(y)"], "products": ["A(x!1).B(y!1)"], "rate": "k"},
        ],
    },
    {
        "name": "reversible_binding_missing_reverse_negative",
        "bngl": """begin model
begin parameters
kon 1
end parameters
begin molecule types
A(x)
B(y)
end molecule types
begin seed species
A(x) 1
B(y) 1
end seed species
begin reaction rules
A(x)+B(y)->A(x!1).B(y!1) kon
end reaction rules
end model
""",
        "must_not_match_reactions": [
            {
                "reactants": ["A(x)", "B(y)"],
                "products": ["A(x!1).B(y!1)"],
                "rate": "kon",
            },
            {
                "reactants": ["A(x!1).B(y!1)"],
                "products": ["A(x)", "B(y)"],
                "rate": "koff",
            },
        ],
    },
    {
        "name": "unimolecular_state_change_wrong_product_negative",
        "bngl": """begin model
begin parameters
k 1
end parameters
begin molecule types
A(x~u~p)
end molecule types
begin seed species
A(x~u) 1
end seed species
begin reaction rules
A(x~u)->A(x~u) k
end reaction rules
end model
""",
        "must_not_match_reactions": [
            {"reactants": ["A(x~u)"], "products": ["A(x~p)"], "rate": "k"},
        ],
    },
    {
        "name": "unimolecular_degradation_wrong_product_negative",
        "bngl": """begin model
begin parameters
k 1
end parameters
begin molecule types
A(x)
B(y)
end molecule types
begin seed species
A(x) 1
end seed species
begin reaction rules
A(x)->B(y) k
end reaction rules
end model
""",
        "must_not_match_reactions": [
            {"reactants": ["A(x)"], "products": [], "rate": "k"},
        ],
    },
]


def reactions_match(actual, species, expected_list):
    if len(actual) != len(expected_list):
        return False, f"count {len(actual)} != {len(expected_list)}"
    used = [False] * len(actual)
    for exp in expected_list:
        found = False
        for i, r in enumerate(actual):
            if used[i]:
                continue
            rnames = sorted(species[j] for j in r["reactants"])
            pnames = sorted(species[j] for j in r["products"])
            if (
                species_match_set(rnames, sorted(exp["reactants"]))
                and species_match_set(pnames, sorted(exp["products"]))
                and r["rate"] == exp["rate"]
            ):
                used[i] = True
                found = True
                break
        if not found:
            return False, f"missing expected reaction {exp}"
    return True, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--require-native", action="store_true")
    args = ap.parse_args()

    failures = []
    for case in CASES:
        name = case["name"]
        try:
            net = generate_net(case["bngl"])
            species, reactions = parse_net(net)
            ok, detail = reactions_match(reactions, species, case["expected_reactions"])
            print(
                f'[native:{name}] reactions={len(reactions)} detail={[{k:v for k,v in r.items() if k!="raw"} for r in reactions]}'
            )
            if len(reactions) != case["expected_reaction_count"]:
                failures.append(
                    f'{name}: reaction count {len(reactions)} != {case["expected_reaction_count"]}'
                )
            if not ok:
                failures.append(f"{name}: {detail}")
            else:
                print(f"[native:{name}] status=PASS")
        except Exception as e:
            msg = f"{name}: native unavailable/error: {e}"
            print(f"[native:{name}] status=SKIP detail={e}")
            if args.require_native:
                failures.append(msg)

    for case in NEGATIVE_CASES:
        name = case["name"]
        try:
            net = generate_net(case["bngl"])
            species, reactions = parse_net(net)
            ok, _ = reactions_match(
                reactions, species, case["must_not_match_reactions"]
            )
            print(
                f"[native-negative:{name}] reactions={len(reactions)} matches_correct={ok}"
            )
            if ok:
                failures.append(
                    f"{name}: mutated artifact incorrectly matched correct expected reactions"
                )
            else:
                print(f"[native-negative:{name}] status=PASS")
        except Exception as e:
            print(f"[native-negative:{name}] status=SKIP detail={e}")
            if args.require_native:
                failures.append(f"{name}: native unavailable/error: {e}")

    if failures:
        print("\nNETWORK REACTION BRIDGE FAILURES:")
        for f in failures:
            print(f"- {f}")
        return 1
    print("\nNETWORK REACTION BRIDGE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
