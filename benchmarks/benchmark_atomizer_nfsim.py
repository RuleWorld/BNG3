#!/usr/bin/env python3
"""Compare Atomizer-generated BNGL NFsim ensembles with standalone NFsim.

The BNG3 leg uses its direct NFsim adapter. The independent leg uses an XML
file emitted by Perl BNG2 and a caller-specified standalone NFsim binary.
Each trajectory runs in a fresh process to avoid state leakage between
stochastic replicates. This is a bounded cross-engine benchmark; it does not
replace the full curated or SBML Test Suite CVODE/libRoadRunner gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_BNG2 = ROOT.parent / "bionetgen" / "bionetgen" / "bng2" / "BNG2.pl"
DIRECT_WORKER = r"""
import json, sys
import numpy as np
import bionetgen
source, t_end, n_steps, seed, output = sys.argv[1:6]
model = bionetgen.load(source)
result = model.simulate(method="nf", t_end=float(t_end), n_steps=int(n_steps), seed=int(seed))
data = np.column_stack([result.time] + [result.observables[name] for name in result.observables])
payload = {"columns": ["time"] + list(result.observables), "data": data.tolist(), "construction_path": result.construction_path}
with open(output, "w", encoding="utf-8") as stream:
    json.dump(payload, stream)
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def error_signature(message: str) -> str:
    undefined = re.search(r'Undefined token "[^"]+" found at position \d+\.', message)
    if undefined:
        return undefined.group(0)
    if "seed amount must resolve to a nonnegative integer" in message:
        return "seed amount must resolve to a nonnegative integer"
    return message.strip()


def git_head(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def build_bng2_xml(bngl: Path, bng2_perl: Path, out_dir: Path, timeout: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    source = bngl.read_text(encoding="utf-8").rstrip()
    source += (
        "\n\nbegin actions\n"
        "generate_network({overwrite=>1});\n"
        "writeXML({overwrite=>1});\n"
        "end actions\n"
    )
    input_path = out_dir / bngl.name
    input_path.write_text(source, encoding="utf-8")
    env = os.environ.copy()
    env.setdefault("BNGPATH", str(bng2_perl.parent))
    result = subprocess.run(
        [
            os.environ.get("PERL", "perl"),
            str(bng2_perl),
            "--outdir",
            str(out_dir),
            str(input_path),
        ],
        cwd=out_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout)[-3000:])
    xml = out_dir / f"{input_path.stem}.xml"
    if not xml.is_file():
        raise RuntimeError("Perl BNG2 returned success without writing BNG-XML")
    return xml


def run_direct(
    *, bngl: Path, output: Path, seed: int, t_end: float, n_steps: int, timeout: int
) -> tuple[dict, float]:
    env = os.environ.copy()
    extra = [str(ROOT / "python"), str(ROOT / "build" / "cpp")]
    env["PYTHONPATH"] = os.pathsep.join(
        extra + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    start = time.perf_counter()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            DIRECT_WORKER,
            str(bngl),
            str(t_end),
            str(n_steps),
            str(seed),
            str(output),
        ],
        cwd=output.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = (time.perf_counter() - start) * 1000.0
    if result.returncode != 0:
        detail = (result.stderr or result.stdout)[-1000:]
        raise RuntimeError(f"BNG3 worker exited {result.returncode}: {detail}")
    return json.loads(output.read_text(encoding="utf-8")), elapsed


def run_native(
    *,
    binary: Path,
    xml: Path,
    output: Path,
    seed: int,
    t_end: float,
    n_steps: int,
    timeout: int,
) -> tuple[np.ndarray, list[str], float, str]:
    start = time.perf_counter()
    result = subprocess.run(
        [
            str(binary),
            "-xml",
            str(xml),
            "-o",
            str(output),
            "-sim",
            str(t_end),
            "-oSteps",
            str(n_steps),
            "-seed",
            str(seed),
            "-cb",
        ],
        cwd=output.parent,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = (time.perf_counter() - start) * 1000.0
    if result.returncode != 0 or not output.is_file():
        detail = (result.stderr or result.stdout)[-1000:]
        raise RuntimeError(f"standalone NFsim exited {result.returncode}: {detail}")
    from tests.validation.compare import parse_gdat

    data, columns = parse_gdat(output)
    if data is None or columns is None:
        raise RuntimeError("standalone NFsim output could not be parsed")
    return data, columns, elapsed, result.stdout


def benchmark_mode(
    *,
    source: Path,
    mode: str,
    bngl: Path,
    native_xml: Path,
    nfsim_binary: Path,
    runs: int,
    seed_start: int,
    t_end: float,
    n_steps: int,
    timeout: int,
    work_dir: Path,
) -> dict:
    from tests.validation.compare import compare_stochastic

    work_dir.mkdir(parents=True, exist_ok=True)
    direct_runs = []
    native_runs = []
    direct_ms = []
    native_ms = []
    native_event_count = 0
    errors = []
    for index in range(runs):
        seed = seed_start + index
        direct_path = work_dir / f"direct-{seed}.json"
        try:
            payload, elapsed = run_direct(
                bngl=bngl,
                output=direct_path,
                seed=seed,
                t_end=t_end,
                n_steps=n_steps,
                timeout=timeout,
            )
        except Exception as exc:
            errors.append(
                {"seed": seed, "engine": "bng3_direct", "error": str(exc)[-3000:]}
            )
            payload = None
        if payload is not None and payload.get("construction_path") != "direct":
            raise RuntimeError(
                "BNG3 NFsim used construction path "
                f"{payload.get('construction_path')!r}, expected 'direct'"
            )
        if payload is not None:
            direct_runs.append(
                (np.asarray(payload["data"], dtype=float), list(payload["columns"]))
            )
            direct_ms.append(elapsed)

        native_path = work_dir / f"native-{seed}.gdat"
        try:
            data, columns, elapsed, native_stdout = run_native(
                binary=nfsim_binary,
                xml=native_xml,
                output=native_path,
                seed=seed,
                t_end=t_end,
                n_steps=n_steps,
                timeout=timeout,
            )
        except Exception as exc:
            errors.append(
                {
                    "seed": seed,
                    "engine": "standalone_nfsim",
                    "error": str(exc)[-3000:],
                }
            )
        else:
            native_runs.append((data, columns))
            native_ms.append(elapsed)
            import re

            match = re.search(r"You just simulated (\d+) reactions", native_stdout)
            if match:
                native_event_count += int(match.group(1))
        if (index + 1) % 50 == 0:
            print(f"{source.name} {mode}: {index + 1}/{runs}", flush=True)

    # Do not compare only the surviving trajectories: excluding invalid runs
    # would censor the ensemble and can bias its mean. Keep the per-seed errors
    # in the report and fail the mode closed instead.
    comparison = None
    if not errors:
        comparison = compare_stochastic(
            native_runs,
            direct_runs,
            min_ref_runs=runs,
            min_test_runs=runs,
        )
    error_seeds: dict[tuple[str, str], list[int]] = {}
    error_examples: dict[tuple[str, str], str] = {}
    for error in errors:
        signature = error_signature(error["error"])
        key = (error["engine"], signature)
        error_seeds.setdefault(key, []).append(error["seed"])
        error_examples.setdefault(key, error["error"])
    grouped_errors = [
        {
            "engine": engine,
            "seeds": seeds,
            "count": len(seeds),
            "signature": signature,
            "example": error_examples[(engine, signature)],
        }
        for (engine, signature), seeds in error_seeds.items()
    ]
    return {
        "mode": mode,
        "status": (
            "invalid_ensemble" if errors else "pass" if comparison.ok else "fail"
        ),
        "runs_per_engine": runs,
        "valid_runs_per_engine": {
            "bng3_direct": len(direct_runs),
            "standalone_nfsim": len(native_runs),
        },
        "run_error_count": len(errors),
        "run_errors": grouped_errors,
        "seed_start": seed_start,
        "direct_construction": "direct",
        "native_total_reaction_events": native_event_count,
        "mean_comparison": (
            None
            if comparison is None
            else {
                "passed": comparison.ok,
                "violations": comparison.n_violations,
                "points_checked": comparison.n_points_checked,
                "worst_z": comparison.worst_z,
                "worst_observable": comparison.worst_col,
            }
        ),
        "median_direct_fresh_process_ms": (
            statistics.median(direct_ms) if direct_ms else None
        ),
        "median_native_process_ms": statistics.median(native_ms) if native_ms else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sbml", type=Path)
    parser.add_argument(
        "--nfsim-binary", type=Path, default=Path(os.environ.get("NFSIM_BIN", ""))
    )
    parser.add_argument("--nfsim-source-root", type=Path)
    parser.add_argument(
        "--bng2-perl",
        type=Path,
        default=Path(os.environ.get("BNG2_PERL", DEFAULT_BNG2)),
    )
    parser.add_argument(
        "--modes", nargs="+", choices=("flat", "atomized"), default=("flat", "atomized")
    )
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--t-end", type=float, default=0.1)
    parser.add_argument("--n-steps", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--json", required=True, type=Path, dest="json_path")
    args = parser.parse_args()
    source = args.sbml.resolve()
    binary = args.nfsim_binary.expanduser().resolve()
    nfsim_source_root = (
        args.nfsim_source_root.expanduser().resolve()
        if args.nfsim_source_root
        else binary.parent.parent
    )
    bng2_perl = args.bng2_perl.resolve()
    if not source.is_file():
        parser.error(f"SBML input is not a file: {source}")
    if not binary.is_file():
        parser.error(f"standalone NFsim binary not found: {binary}")
    if not bng2_perl.is_file():
        parser.error(f"BNG2.pl not found: {bng2_perl}")
    if args.runs < 2 or args.n_steps < 1 or args.t_end <= 0:
        parser.error("runs, n-steps, and t-end must be positive (runs >= 2)")

    from bionetgen.atomizer.modern import Atomizer

    report = {
        "schema_version": 1,
        "benchmark": "Atomizer-generated BNG3 direct vs standalone NFsim ensemble",
        "source": {"path": str(source), "sha256": sha256(source)},
        "environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "bng3_head": git_head(ROOT),
            "bng2_head": git_head(bng2_perl.parent),
            "nfsim_binary": str(binary),
            "nfsim_sha256": sha256(binary),
            "nfsim_source_head": git_head(nfsim_source_root),
            "bng2_perl": str(bng2_perl),
            "runs": args.runs,
            "seed_start": args.seed_start,
            "t_end": args.t_end,
            "n_steps": args.n_steps,
        },
        "modes": [],
        "scope_note": "Each trajectory ran in a fresh process. Native NFsim reads BNG-XML written by Perl BNG2 from the same Atomizer-generated BNGL. The ensemble comparator checks mean agreement at 3 pooled standard errors and is not a deterministic trajectory identity claim.",
    }
    with tempfile.TemporaryDirectory(prefix="bng3-atomizer-nfsim-") as temp:
        work = Path(temp)
        raw = source.read_text(encoding="utf-8")
        for mode in args.modes:
            atomized = Atomizer(atomize=(mode == "atomized"), quiet_mode=True).atomize(
                raw
            )
            if not atomized.success or not atomized.bngl:
                report["modes"].append(
                    {"mode": mode, "status": "atomizer_error", "error": atomized.error}
                )
                continue
            bngl = work / f"{source.stem}-{mode}.bngl"
            bngl.write_text(atomized.bngl, encoding="utf-8")
            bngl_hash = sha256(bngl)
            try:
                xml = build_bng2_xml(
                    bngl,
                    bng2_perl,
                    work / f"{mode}-bng2",
                    args.timeout,
                )
            except Exception as exc:
                report["modes"].append(
                    {
                        "mode": mode,
                        "status": "bng2_conversion_error",
                        "bngl_sha256": bngl_hash,
                        "error": str(exc)[-3000:],
                    }
                )
                continue
            mode_result = benchmark_mode(
                source=source,
                mode=mode,
                bngl=bngl,
                native_xml=xml,
                nfsim_binary=binary,
                runs=args.runs,
                seed_start=args.seed_start,
                t_end=args.t_end,
                n_steps=args.n_steps,
                timeout=args.timeout,
                work_dir=work / f"{mode}-ensembles",
            )
            mode_result["bngl_sha256"] = bngl_hash
            mode_result["native_xml_sha256"] = sha256(xml)
            report["modes"].append(mode_result)
    args.json_path.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"report={args.json_path.resolve()}")
    summaries = []
    for mode in report["modes"]:
        summaries.append(
            {
                "mode": mode.get("mode"),
                "status": mode.get("status"),
                "error": (mode.get("error") or "")[-700:] or None,
                "valid_runs_per_engine": mode.get("valid_runs_per_engine"),
                "run_error_count": mode.get("run_error_count", 0),
                "error_groups": [
                    {
                        "engine": error["engine"],
                        "count": error["count"],
                        "signature": error["signature"],
                    }
                    for error in mode.get("run_errors", [])
                ],
                "mean_comparison": mode.get("mean_comparison"),
            }
        )
    print(json.dumps(summaries, indent=2))
    return (
        0
        if report["modes"]
        and all(row.get("status") == "pass" for row in report["modes"])
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
