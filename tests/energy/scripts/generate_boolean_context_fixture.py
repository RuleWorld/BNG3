#!/usr/bin/env python3
"""Generate a binding-energy model with N independent occupancy predicates.

This is designed to expose exponential materialized expansion. A generalized
factorized implementation should keep the reaction-class count O(1) in N.
"""

from __future__ import annotations
import argparse
from pathlib import Path


def generate(n: int) -> str:
    if n < 1 or n > 40:
        raise ValueError("n must be in [1,40]")
    a_sites = ["x"] + [f"c{i}" for i in range(n)]
    params = "\n".join(f"  G{i} {0.1*(i+1):.6g}" for i in range(n))
    moltypes = [f"  A({','.join(a_sites)})", "  B(y)"] + [
        f"  C{i}(z)" for i in range(n)
    ]
    # Seed A already carries all context bonds, so all context predicates are present.
    a_seed_sites = ["x"] + [f"c{i}!{i+2}" for i in range(n)]
    seed_complex = [f"A({','.join(a_seed_sites)})"] + [
        f"C{i}(z!{i+2})" for i in range(n)
    ]
    energy = []
    for i in range(n):
        energy.append(f"  A(x!1,c{i}!2).B(y!1).C{i}(z!2) G{i}")
    return f"""begin model
begin parameters
  phi 0.5
  Ea 1
{params}
end parameters
begin molecule types
{chr(10).join(moltypes)}
end molecule types
begin seed species
  {'.'.join(seed_complex)} 100
  B(y) 100
end seed species
begin energy patterns
{chr(10).join(energy)}
end energy patterns
begin observables
  Molecules Bound A(x!1).B(y!1)
end observables
begin reaction rules
  A(x) + B(y) <-> A(x!1).B(y!1) Arrhenius(phi,Ea)
end reaction rules
end model
"""


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("n", type=int)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    a.output.write_text(generate(a.n), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
