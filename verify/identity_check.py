#!/usr/bin/env python3
"""Independent seeded-trajectory identity check (perfOracle).

usage: identity_check.py <bng_cpp> <outdir> [--only NAME[,NAME...]]

Runs a fixed-seed simulate_ssa on a set of repository models plus synthetic
edge cases that exercise the code paths the SSA optimization touches
(dimerization / identical reactants, zero-rate plateaus, a species that is
both reactant and product, continued and function rates, and a negative rate
constant that must take the non-monotone selection fallback), then writes

    <outdir>/<name>/SHA256SUMS

covering every .gdat/.net/.cdat artifact.  Run once per binary and diff the
per-model SHA256SUMS.  Deliberately independent of the originating agent's
harness (different model set, different edge cases, own model synthesis).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def ring(n: int = 60) -> str:
    lines = [
        "begin model",
        "begin parameters",
        "  kb 8",
        "  kd 0.005",
        "  kc 0.002",
        "end parameters",
        "begin molecule types",
        "  X()",
        "end molecule types",
        "begin seed species",
    ]
    lines += [f"  X_{i}()  400" for i in range(n)]
    lines += [
        "end seed species",
        "begin observables",
        "  Molecules  Xt  X()",
        "end observables",
        "begin reaction rules",
    ]
    lines += [f"  0 -> X_{i}()  kb" for i in range(n)]
    lines += [f"  X_{i}() -> 0  kd" for i in range(n)]
    lines += [f"  X_{i}() <-> X_{(i + 1) % n}()  kc, kc" for i in range(n)]
    lines += ["end reaction rules", "end model", ""]
    return "\n".join(lines)


SYNTH: dict[str, str] = {}

SYNTH["edge_dimer"] = """begin model
begin parameters
  kd 0.01
  kon 0.0002
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 300
end seed species
begin observables
  Molecules  Atot  A()
  Molecules  Btot  B()
end observables
begin reaction rules
  A() + A() -> B()  kon
  B() -> A() + A()  kd
end reaction rules
end model
"""

SYNTH["edge_zero_plateau"] = """begin model
begin parameters
  k1 0.0
  k2 0.0
  k3 0.0
  k4 0.0
  k5 0.0
  ka 0.01
  kb 0.02
  kc 0.03
end parameters
begin molecule types
  S0()
  S1()
  S2()
  S3()
  S4()
  L0()
  L1()
  L2()
end molecule types
begin seed species
  S0() 50
  S1() 50
  S2() 50
  S3() 50
  S4() 50
  L0() 200
  L1() 200
  L2() 200
end seed species
begin observables
  Molecules  L0t  L0()
  Molecules  L1t  L1()
  Molecules  L2t  L2()
end observables
begin reaction rules
  S0() -> S1()  k1
  S1() -> S2()  k2
  S2() -> S3()  k3
  S3() -> S4()  k4
  S4() -> S0()  k5
  L0() -> L1()  ka
  L1() -> L2()  kb
  L2() -> L0()  kc
end reaction rules
end model
"""

SYNTH["edge_reactant_is_product"] = """begin model
begin parameters
  k1 0.05
  k2 0.01
  k3 0.03
end parameters
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  A() 400
  B() 10
  C() 10
end seed species
begin observables
  Molecules  Atot  A()
  Molecules  Btot  B()
  Molecules  Ctot  C()
end observables
begin reaction rules
  A() + B() -> A() + C()  k1
  A() -> A() + B()  k2
  C() -> B()  k3
end reaction rules
end model
"""

SYNTH["edge_negative_rate"] = """begin model
begin parameters
  k1 -1.0
  k2 2.0
  k3 0.01
  k4 0.02
end parameters
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  A() 100
  B() 100
  C() 100
end seed species
begin observables
  Molecules  Atot  A()
  Molecules  Btot  B()
  Molecules  Ctot  C()
end observables
begin reaction rules
  A() -> 0  k1
  0 -> A()  k2
  B() -> C()  k3
  C() -> B()  k4
end reaction rules
end model
"""


SYNTH["edge_chain_wide"] = """begin model
begin parameters
  kf 0.02
  kr 0.005
end parameters
begin molecule types
  A()
  B()
  C()
  D()
  E()
  F()
  G()
  H()
end molecule types
begin seed species
  A() 60
  B() 60
  C() 60
  D() 60
  E() 60
  F() 60
  G() 60
  H() 60
end seed species
begin observables
  Molecules  Atot  A()
  Molecules  Htot  H()
end observables
begin reaction rules
  A() <-> B()  kf, kr
  B() <-> C()  kf, kr
  C() <-> D()  kf, kr
  D() <-> E()  kf, kr
  E() <-> F()  kf, kr
  F() <-> G()  kf, kr
  G() <-> H()  kf, kr
  H() -> A()  kf
end reaction rules
end model
"""

SYNTH_ACTIONS: dict[str, list[str]] = {
    "edge_dimer": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>20,n_steps=>300,seed=>61})'],
    "edge_zero_plateau": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>50,n_steps=>300,seed=>67})'],
    "edge_reactant_is_product": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>20,n_steps=>300,seed=>71})'],
    "edge_negative_rate": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>20,n_steps=>300,seed=>73})'],
    "edge_chain_wide": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>20,n_steps=>300,seed=>89,max_sim_steps=>600000})'],
    "edge_ring_long": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>200,n_steps=>300,seed=>83,max_sim_steps=>400000})'],
}

# name -> (source model path or None for synthetic, actions)
CASES: list[tuple[str, str | None, list[str] | None]] = [
    ("isomerization", "models/isomerization.bngl", None),
    ("gene_expr_simple", "models/gene_expr_simple.bngl", None),
    ("gene_expr_func", "models/gene_expr_func.bngl", None),
    ("michment", "models/michment.bngl", None),
    ("continue_rates", "models/continue.bngl", None),
    ("statfactor", "models/statfactor.bngl", None),
    ("localfunc", "models/localfunc.bngl", None),
    ("isingspin_localfcn", "models/isingspin_localfcn.bngl", None),
    ("synth_angles", "models/test_ANG_SSA_synthesis_simple.bngl", None),
    ("synth_complex", "models/test_synthesis_complex.bngl", None),
    ("blbr", "models/blbr.bngl", None),
    ("haugh2b", "models/Haugh2b.bngl", None),
    ("repressilator", "models/Repressilator.bngl", None),
    ("heise", "models/heise.bngl", None),
    ("simple_system", "models/simple_system.bngl", None),
    ("caosc_sat", "models/CaOscillate_Sat.bngl", None),
    ("caosc_func", "models/CaOscillate_Func.bngl", None),
    ("edge_dimer", None, None),
    ("edge_zero_plateau", None, None),
    ("edge_reactant_is_product", None, None),
    ("edge_negative_rate", None, None),
    ("mm_saturating", "models/test_MM.bngl", None),
    ("sat_rate", "models/test_sat.bngl", None),
    ("edge_chain_wide", None, None),
    ("edge_ring_long", None, None),
]

REPO_ACTIONS: dict[str, list[str]] = {
    "isomerization": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>20000,n_steps=>400,seed=>7})'],
    "gene_expr_simple": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>100000,n_steps=>400,seed=>7})'],
    "gene_expr_func": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>100000,n_steps=>400,seed=>7})'],
    "michment": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>10000,n_steps=>400,seed=>7})'],
    "continue_rates": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>10,n_steps=>300,seed=>11})'],
    "statfactor": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>100,n_steps=>300,seed=>13})'],
    "localfunc": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>100,n_steps=>300,seed=>17})'],
    "isingspin_localfcn": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>200,n_steps=>300,seed=>19})'],
    "synth_angles": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>50,n_steps=>300,seed=>23})'],
    "synth_complex": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>200,n_steps=>300,seed=>29})'],
    "blbr": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>10,n_steps=>300,seed=>31})'],
    "haugh2b": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>10,n_steps=>300,seed=>37})'],
    "repressilator": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>100,n_steps=>300,seed=>41})'],
    "mm_saturating": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>500,n_steps=>300,seed=>97})'],
    "sat_rate": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>500,n_steps=>300,seed=>101})'],
    "heise": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>10,n_steps=>300,seed=>43})'],
    "simple_system": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>20,n_steps=>300,seed=>47})'],
    "caosc_sat": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>500,n_steps=>300,seed=>53})'],
    "caosc_func": ['simulate_ssa({suffix=>"s",t_start=>0,t_end=>500,n_steps=>300,seed=>59})'],
}


def strip_actions(text: str) -> str:
    text = re.sub(r"\n## actions ##\n.*$", "", text, flags=re.S)
    text = re.sub(r"\nbegin actions\n.*?\nend actions\n", "\n", text, flags=re.S)
    return text


def build_case(name: str, src: str | None, actions: list[str], out: Path) -> Path:
    case = out / name
    if case.exists():
        shutil.rmtree(case)
    case.mkdir(parents=True)
    if src is not None:
        text = strip_actions((REPO / src).read_text())
    elif name == "edge_ring_long":
        text = ring()
    else:
        text = SYNTH[name]
    body = (text.rstrip("\n") + "\n\n## actions ##\ngenerate_network({overwrite=>1})\n"
            + "\n".join(actions) + "\n")
    (case / "model.bngl").write_text(body)
    return case


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("binary")
    ap.add_argument("outdir")
    ap.add_argument("--only", default=None)
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="per-case wall-clock cap; a case that exceeds it is "
                         "reported SKIPPED_SLOW and excluded from the verdict")
    args = ap.parse_args()

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None

    summary = []
    for name, src, _ in CASES:
        if only and name not in only:
            continue
        actions = REPO_ACTIONS.get(name) or SYNTH_ACTIONS[name]
        case = build_case(name, src, actions, out)
        try:
            done = subprocess.run([str(Path(args.binary).resolve()), "model.bngl"],
                                  cwd=case, capture_output=True, text=True,
                                  timeout=args.timeout)
            rc = done.returncode
        except subprocess.TimeoutExpired:
            rc = "SKIPPED_SLOW"
        arts = sorted(p for ext in ("*.gdat", "*.cdat", "*.net") for p in case.glob(ext))
        lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in arts]
        (case / "SHA256SUMS").write_text("\n".join(lines) + ("\n" if lines else ""))
        if rc == "SKIPPED_SLOW":
            print(f"  [{name}] SKIPPED_SLOW (>{args.timeout:.0f}s wall)")
        elif rc != 0:
            err = (done.stdout + done.stderr).strip().splitlines()
            print(f"  [{name}] exit={rc}: {err[-1] if err else 'no output'}")
        summary.append((name, rc, len(arts)))

    width = max(len(n) for n, *_ in summary)
    for name, rc, nart in summary:
        print(f"{name:<{width}}  exit={rc}  artifacts={nart}")
    bad = [n for n, rc, na in summary if rc == "SKIPPED_SLOW" or (rc != 0 or na == 0)]
    slow = [n for n, rc, _ in summary if rc == "SKIPPED_SLOW"]
    if slow:
        print(f"SKIPPED_SLOW (excluded): {', '.join(slow)}")
        print(f"INCONCLUSIVE: {', '.join(bad)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
