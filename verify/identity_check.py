#!/usr/bin/env python3
"""Independent seeded-trajectory identity check (perfOracle).

usage: identity_check.py <bng_cpp> <outdir> [--only NAME[,NAME...]]

Runs a fixed-seed simulate_ssa on a set of repository models plus synthetic
edge cases that exercise the code paths the SSA optimization touches
(dimerization / identical reactants, zero-rate plateaus, a species that is
both reactant and product, continued and function rates, and a negative rate
constant that must take the non-monotone selection fallback), then writes

    <outdir>/<name>/SHA256SUMS
    <outdir>/identity_manifest.json

covering every .gdat/.net/.cdat artifact. A case is valid only when it emits a
nonempty .net file and numeric .gdat/.cdat data with every configured SSA
sample from t_start through t_end. The root manifest records per-case validity,
fresh output directories, sampling bounds, and required output lists. Run once
per binary and compare the output trees with compare_identity.py. Deliberately
independent of the originating agent's harness (different model set, different
edge cases, own model synthesis).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

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

# Keep model-specific generation bounds from source model action blocks when
# rebuilding their actions for this harness. In particular, unbounded BLBR
# expansion can generate an enormous network before SSA starts.
NETWORK_GENERATION: dict[str, str] = {
    "blbr": "generate_network({overwrite=>1,max_stoich=>{'R'=>5,'L'=>5}})",
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


class SamplingExpectation(TypedDict):
    t_start: float
    t_end: float
    n_steps: int
    expected_rows: int


class CaseOutputAudit(TypedDict):
    artifacts: list[Path]
    network_files: list[Path]
    trajectory_files: list[Path]
    usable_trajectory_files: list[Path]
    expected_sampling: SamplingExpectation
    issue: str | None


def expected_sampling(case_name: str) -> SamplingExpectation:
    """Derive the required time grid from this harness's fixed SSA action."""
    actions = REPO_ACTIONS.get(case_name) or SYNTH_ACTIONS.get(case_name)
    if actions is None:
        raise ValueError(f"no configured SSA action for case {case_name}")
    ssa_actions = [action for action in actions if "simulate_ssa(" in action]
    if len(ssa_actions) != 1:
        raise ValueError(f"case {case_name} must have exactly one simulate_ssa action")

    action = ssa_actions[0]

    def action_number(name: str) -> float:
        pattern = (
            rf"(?<![A-Za-z0-9_]){name}\s*=>\s*"
            r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
        )
        matches = re.findall(pattern, action)
        if len(matches) != 1:
            raise ValueError(f"case {case_name} has no unique {name} in its SSA action")
        value = float(matches[0])
        if not math.isfinite(value):
            raise ValueError(f"case {case_name} has a non-finite {name}")
        return value

    start = action_number("t_start")
    end = action_number("t_end")
    raw_steps = action_number("n_steps")
    if raw_steps <= 0 or not raw_steps.is_integer() or end <= start:
        raise ValueError(f"case {case_name} has invalid SSA sampling bounds")
    n_steps = int(raw_steps)
    return {
        "t_start": start,
        "t_end": end,
        "n_steps": n_steps,
        "expected_rows": n_steps + 1,
    }


def _is_usable_trajectory(path: Path, sampling: SamplingExpectation) -> bool:
    """Require every finite row on the configured inclusive SSA time grid."""
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeError):
        return False
    if not lines:
        return False
    columns = lines[0].strip().lstrip("#").split()
    if len(columns) < 2 or columns[0] != "time":
        return False

    data_rows = 0
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        values = line.split()
        if len(values) != len(columns):
            return False
        try:
            numbers = [float(value) for value in values]
        except ValueError:
            return False
        if not all(math.isfinite(value) for value in numbers):
            return False
        if data_rows >= sampling["expected_rows"]:
            return False
        expected_time = sampling["t_start"] + (
            sampling["t_end"] - sampling["t_start"]
        ) * data_rows / sampling["n_steps"]
        if not math.isclose(numbers[0], expected_time, rel_tol=1e-12, abs_tol=1e-9):
            return False
        data_rows += 1
    return data_rows == sampling["expected_rows"]


def _is_nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def inspect_case_outputs(case: Path, case_name: str) -> CaseOutputAudit:
    """List hashed outputs and identify whether required artifacts are usable."""
    sampling = expected_sampling(case_name)
    artifacts = sorted(
        path for pattern in ("*.gdat", "*.cdat", "*.net")
        for path in case.glob(pattern)
    )
    networks = [path for path in artifacts if path.suffix == ".net"]
    trajectories = [
        path for path in artifacts if path.suffix in {".gdat", ".cdat"}
    ]
    usable_trajectories = [
        path for path in trajectories if _is_usable_trajectory(path, sampling)
    ]

    if not networks or any(not _is_nonempty_file(path) for path in networks):
        issue = "missing_network"
    elif not trajectories:
        issue = "missing_trajectory"
    elif len(usable_trajectories) != len(trajectories):
        issue = "invalid_trajectory"
    else:
        issue = None
    return {
        "artifacts": artifacts,
        "network_files": networks,
        "trajectory_files": trajectories,
        "usable_trajectory_files": usable_trajectories,
        "expected_sampling": sampling,
        "issue": issue,
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
    generate = NETWORK_GENERATION.get(
        name, "generate_network({overwrite=>1})")
    body = (text.rstrip("\n") + "\n\n## actions ##\n" + generate + "\n"
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
    known = {name for name, _, _ in CASES}
    unknown = sorted((only or set()) - known)
    if unknown:
        ap.error(f"unknown case name(s): {', '.join(unknown)}")

    summary = []
    case_results = {}
    for name, src, _ in CASES:
        if only and name not in only:
            continue
        actions = REPO_ACTIONS.get(name) or SYNTH_ACTIONS[name]
        case = build_case(name, src, actions, out)
        launch_error = None
        try:
            done = subprocess.run([str(Path(args.binary).resolve()), "model.bngl"],
                                  cwd=case, capture_output=True, text=True,
                                  timeout=args.timeout)
            rc = done.returncode
        except subprocess.TimeoutExpired:
            rc = None
        except OSError as exc:
            rc = None
            launch_error = str(exc)
        output_audit = inspect_case_outputs(case, name)
        arts = output_audit["artifacts"]
        networks = output_audit["network_files"]
        trajectories = output_audit["trajectory_files"]
        usable_trajectories = output_audit["usable_trajectory_files"]
        lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in arts]
        (case / "SHA256SUMS").write_text("\n".join(lines) + ("\n" if lines else ""))
        if launch_error is not None:
            status = "launch_error"
            print(f"  [{name}] could not start simulator: {launch_error}")
        elif rc is None:
            status = "timeout"
            print(f"  [{name}] SKIPPED_SLOW (>{args.timeout:.0f}s wall)")
        elif rc != 0:
            status = "failed_exit"
            err = (done.stdout + done.stderr).strip().splitlines()
            print(f"  [{name}] exit={rc}: {err[-1] if err else 'no output'}")
        elif output_audit["issue"] is not None:
            status = output_audit["issue"]
            issue_messages = {
                "missing_network": "missing required nonempty .net network output",
                "missing_trajectory": "missing required .gdat/.cdat trajectory output",
                "invalid_trajectory": (
                    "trajectory output is not a complete numeric table on the "
                    "configured SSA time grid"
                ),
            }
            print(f"  [{name}] {issue_messages[status]}")
        else:
            status = "pass"
        case_results[name] = {
            "status": status,
            "valid": status == "pass",
            "exit_code": rc,
            "error": launch_error,
            "fresh_output_directory": True,
            "expected_sampling": output_audit["expected_sampling"],
            "network_files": [p.name for p in networks],
            "trajectory_files": [p.name for p in trajectories],
            "usable_trajectory_files": [p.name for p in usable_trajectories],
            "artifact_files": [p.name for p in arts],
        }
        summary.append((name, rc, len(arts), len(networks), len(trajectories), status))

    manifest = {
        "schema_version": 1,
        "selected_cases": [name for name, *_ in summary],
        "valid": bool(summary) and all(item["valid"] for item in case_results.values()),
        "cases": case_results,
    }
    manifest_path = out / "identity_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    if not summary:
        print("FAIL: no identity cases selected", file=sys.stderr)
        return 1
    width = max(len(n) for n, *_ in summary)
    for name, rc, nart, nnet, ntraj, status in summary:
        exit_text = "SKIPPED_SLOW" if status == "timeout" else (
            "NOT_STARTED" if rc is None else str(rc)
        )
        print(f"{name:<{width}}  exit={exit_text}  status={status}  "
              f"artifacts={nart}  networks={nnet}  trajectories={ntraj}")
    bad = [name for name, _, *_ in summary if not case_results[name]["valid"]]
    slow = [entry[0] for entry in summary if entry[-1] == "timeout"]
    if slow:
        print(f"SKIPPED_SLOW (excluded): {', '.join(slow)}")
        print(f"INCONCLUSIVE: {', '.join(bad)}", file=sys.stderr)
        return 2
    if bad:
        print(f"FAIL: incomplete or invalid identity cases: {', '.join(bad)}",
              file=sys.stderr)
        return 1
    print(f"identity manifest: {manifest_path} status=VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
