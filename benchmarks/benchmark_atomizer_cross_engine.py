#!/usr/bin/env python3
"""Benchmark modern/legacy SBML Atomizers through BNG3 and BNG2 networks.

This is a bounded interoperability benchmark, not a substitute for the full
SBML Test Suite or curated BioModels validation. It records Atomizer and
network-generation time separately, then compares graph/network structure and
rate expressions as separate gates. Every tool runs from the supplied source
checkouts; generated inputs and outputs stay in temporary directories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_BNG2 = ROOT.parent / "bionetgen" / "bionetgen" / "bng2" / "BNG2.pl"
DEFAULT_PYBIONETGEN = ROOT.parent / "PyBioNetGen"
MODERN_WORKER = r"""
import hashlib, json, sys, time
from pathlib import Path
from bionetgen.atomizer.modern import Atomizer
source, mode, output, metadata = sys.argv[1:5]
start = time.perf_counter()
result = Atomizer(atomize=(mode == "atomized"), quiet_mode=True).atomize(
    Path(source).read_text(encoding="utf-8")
)
elapsed = (time.perf_counter() - start) * 1000.0
if not result.success or not result.bngl:
    raise RuntimeError(result.error or "modern Atomizer returned no BNGL")
data = result.bngl.encode("utf-8")
Path(output).write_bytes(data)
Path(metadata).write_text(json.dumps({
    "elapsed_ms": elapsed,
    "output_bytes": len(data),
    "output_sha256": hashlib.sha256(data).hexdigest(),
}), encoding="utf-8")
"""
LEGACY_WORKER = r"""
import hashlib, json, sys, time
from pathlib import Path
from bionetgen.atomizer.atomizeTool import AtomizeTool
source, mode, output, metadata = sys.argv[1:5]
start = time.perf_counter()
tool = AtomizeTool(input_file=source, options_dict={
    "output": output,
    "bionetgen_analysis": None,
    "quiet_mode": True,
    "atomize": mode == "atomized",
    "pathwaycommons": False,
    "log_level": "CRITICAL",
})
result = tool.run()
elapsed = (time.perf_counter() - start) * 1000.0
path = Path(output)
if result is None or not path.is_file() or path.stat().st_size == 0:
    raise RuntimeError("legacy PyBioNetGen Atomizer returned no BNGL")
data = path.read_bytes()
Path(metadata).write_text(json.dumps({
    "elapsed_ms": elapsed,
    "output_bytes": len(data),
    "output_sha256": hashlib.sha256(data).hexdigest(),
}), encoding="utf-8")
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def git_state(path: Path) -> dict:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=path, capture_output=True, check=False
    )
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"], cwd=path, capture_output=True, check=False
    )
    status_bytes = status.stdout if status.returncode == 0 else b"unavailable"
    diff_bytes = diff.stdout if diff.returncode == 0 else b"unavailable"
    return {
        "status_available": status.returncode == 0,
        "dirty": bool(status_bytes.strip()) if status.returncode == 0 else None,
        "status_sha256": hashlib.sha256(status_bytes).hexdigest(),
        "tracked_diff_sha256": hashlib.sha256(diff_bytes).hexdigest(),
    }


def file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run_atomizer(
    *,
    source: Path,
    mode: str,
    output: Path,
    metadata: Path,
    implementation: str,
    pybionetgen_root: Path,
) -> dict:
    source_root = (
        ROOT / "python" if implementation == "bng3_modern" else pybionetgen_root
    )
    worker = MODERN_WORKER if implementation == "bng3_modern" else LEGACY_WORKER
    env = os.environ.copy()
    extra_paths = [str(source_root)]
    if implementation == "bng3_modern":
        extra_paths.append(str(ROOT / "build" / "cpp"))
    env["PYTHONPATH"] = os.pathsep.join(
        extra_paths + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    start = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-c", worker, str(source), mode, str(output), str(metadata)],
        cwd=output.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    wall_ms = (time.perf_counter() - start) * 1000.0
    if result.returncode != 0:
        return {
            "status": "error",
            "wall_ms": wall_ms,
            "error": (result.stderr or result.stdout)[-3000:],
        }
    values = json.loads(metadata.read_text(encoding="utf-8"))
    values.update({"status": "ok", "wall_ms": wall_ms})
    return values


def run_network(
    *, bngl: Path, out_dir: Path, engine: str, bng2_perl: Path, timeout: int
) -> dict:
    from tests.validation.compare import compare_net, parse_net

    out_dir.mkdir(parents=True, exist_ok=True)
    executable_input = out_dir / bngl.name
    source = bngl.read_text(encoding="utf-8").rstrip()
    if "begin actions" not in source.lower():
        source += "\n\nbegin actions\ngenerate_network({overwrite=>1});\nend actions\n"
    executable_input.write_text(source + "\n", encoding="utf-8")
    if engine == "bng3":
        command = [str(ROOT / "build" / "cpp" / "bng_cpp"), str(executable_input)]
        cwd = out_dir
        env = os.environ.copy()
    else:
        command = [
            os.environ.get("PERL", "perl"),
            str(bng2_perl),
            "--outdir",
            str(out_dir),
            str(executable_input),
        ]
        cwd = out_dir
        env = os.environ.copy()
        env.setdefault("BNGPATH", str(bng2_perl.parent))
    start = time.perf_counter()
    try:
        result = subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "wall_ms": (time.perf_counter() - start) * 1000.0}
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    if result.returncode != 0:
        return {
            "status": "error",
            "wall_ms": elapsed_ms,
            "error": (result.stderr or result.stdout)[-3000:],
        }
    candidates = sorted(out_dir.glob("*.net"))
    net_path = out_dir / f"{executable_input.stem}.net"
    if not net_path.is_file():
        if len(candidates) != 1:
            return {
                "status": "error",
                "wall_ms": elapsed_ms,
                "error": "network output missing or ambiguous",
            }
        net_path = candidates[0]
    network = parse_net(net_path)
    if network is None:
        return {
            "status": "error",
            "wall_ms": elapsed_ms,
            "error": "network output could not be parsed",
        }
    return {
        "status": "ok",
        "wall_ms": elapsed_ms,
        "net_path": str(net_path),
        "net_sha256": sha256(net_path),
        "species": network.n_species,
        "reactions": network.n_reactions,
        "parsed_network": network,
        "compare_net": compare_net,
    }


def benchmark_model(
    source: Path,
    *,
    modes: list[str],
    repeats: int,
    bng2_perl: Path,
    pybionetgen_root: Path,
    timeout: int,
) -> dict:
    model = {"input": {"path": str(source), "sha256": sha256(source)}, "modes": {}}
    for mode in modes:
        mode_row = {"atomizers": {}}
        for implementation in ("bng3_modern", "pybionetgen_legacy"):
            samples = []
            for repeat in range(repeats):
                with tempfile.TemporaryDirectory(prefix="bng3-atomizer-cross-") as temp:
                    work = Path(temp)
                    bngl = work / f"{source.stem}-{implementation}-{mode}.bngl"
                    atomizer_meta = work / "atomizer.json"
                    atomizer = run_atomizer(
                        source=source,
                        mode=mode,
                        output=bngl,
                        metadata=atomizer_meta,
                        implementation=implementation,
                        pybionetgen_root=pybionetgen_root,
                    )
                    sample = {"repeat": repeat + 1, "atomizer": atomizer}
                    if atomizer["status"] == "ok":
                        # Each engine gets an isolated output directory and the
                        # same BNGL bytes; this isolates parser/network parity.
                        bng3 = run_network(
                            bngl=bngl,
                            out_dir=work / "bng3",
                            engine="bng3",
                            bng2_perl=bng2_perl,
                            timeout=timeout,
                        )
                        bng2 = run_network(
                            bngl=bngl,
                            out_dir=work / "bng2",
                            engine="bng2",
                            bng2_perl=bng2_perl,
                            timeout=timeout,
                        )
                        for result in (bng3, bng2):
                            result.pop("parsed_network", None)
                            result.pop("compare_net", None)
                        sample["bng3_network"] = bng3
                        sample["bng2_network"] = bng2
                        if bng3.get("status") == bng2.get("status") == "ok":
                            from tests.validation.compare import compare_net, parse_net

                            a = parse_net(Path(bng2["net_path"]))
                            b = parse_net(Path(bng3["net_path"]))
                            sample["network_comparison"] = {
                                "structure_passed": compare_net(
                                    a, b, compare_rates=False
                                ).ok,
                                "rates_passed": compare_net(
                                    a, b, compare_rates=True
                                ).ok,
                                "structure_summary": compare_net(
                                    a, b, compare_rates=False
                                ).summary(),
                                "rate_summary": compare_net(
                                    a, b, compare_rates=True
                                ).summary(),
                            }
                        bng3.pop("net_path", None)
                        bng2.pop("net_path", None)
                    samples.append(sample)
            atomizer_ok = [
                s["atomizer"] for s in samples if s["atomizer"]["status"] == "ok"
            ]
            times = [s["elapsed_ms"] for s in atomizer_ok]
            wall_times = [s["wall_ms"] for s in atomizer_ok]
            raw_hashes = {s["output_sha256"] for s in atomizer_ok}
            structural = [
                s["network_comparison"]["structure_passed"]
                for s in samples
                if "network_comparison" in s
            ]
            rates = [
                s["network_comparison"]["rates_passed"]
                for s in samples
                if "network_comparison" in s
            ]
            bng2_times = [
                s["bng2_network"]["wall_ms"]
                for s in samples
                if s.get("bng2_network", {}).get("status") == "ok"
            ]
            bng3_times = [
                s["bng3_network"]["wall_ms"]
                for s in samples
                if s.get("bng3_network", {}).get("status") == "ok"
            ]
            mode_row["atomizers"][implementation] = {
                "samples": samples,
                "median_atomizer_ms": statistics.median(times) if times else None,
                "stdev_atomizer_ms": (
                    statistics.stdev(times)
                    if len(times) > 1
                    else (0.0 if times else None)
                ),
                "median_atomizer_process_ms": (
                    statistics.median(wall_times) if wall_times else None
                ),
                "deterministic_raw_output": (
                    len(raw_hashes) == 1 if raw_hashes else None
                ),
                "unique_raw_output_hashes": sorted(raw_hashes),
                "network_comparison_repeats": len(structural),
                "structural_parity_passes": sum(structural),
                "rate_parity_passes": sum(rates),
                "median_bng3_network_ms": (
                    statistics.median(bng3_times) if bng3_times else None
                ),
                "median_bng2_network_ms": (
                    statistics.median(bng2_times) if bng2_times else None
                ),
            }
        model["modes"][mode] = mode_row
    return model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sbml", nargs="+", type=Path, help="SBML input files")
    parser.add_argument(
        "--modes", nargs="+", choices=("flat", "atomized"), default=("flat", "atomized")
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--bng2-perl",
        type=Path,
        default=Path(os.environ.get("BNG2_PERL", DEFAULT_BNG2)),
    )
    parser.add_argument(
        "--pybionetgen-root",
        type=Path,
        default=Path(os.environ.get("PYBIONETGEN_ROOT", DEFAULT_PYBIONETGEN)),
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json", required=True, type=Path, dest="json_path")
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error("--repeats must be at least 3")
    sources = [path.resolve() for path in args.sbml]
    for source in sources:
        if not source.is_file():
            parser.error(f"SBML input is not a file: {source}")
    bng2_perl = args.bng2_perl.resolve()
    pybionetgen_root = args.pybionetgen_root.resolve()
    bng3_binary = ROOT / "build" / "cpp" / "bng_cpp"
    if not bng3_binary.is_file():
        parser.error(f"BNG3 CLI not found: {bng3_binary}")
    if not bng2_perl.is_file():
        parser.error(f"BNG2.pl not found: {bng2_perl}")
    if not (pybionetgen_root / "bionetgen" / "atomizer" / "atomizeTool.py").is_file():
        parser.error(f"PyBioNetGen Atomizer not found under: {pybionetgen_root}")

    report = {
        "schema_version": 1,
        "benchmark": "SBML Atomizer cross-engine network interoperability",
        "environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "bng3_head": git_head(ROOT),
            "bng3_git_state": git_state(ROOT),
            "bng3_source_sha256": {
                name: file_sha256(ROOT / name)
                for name in (
                    "python/bionetgen/atomizer/modern/__init__.py",
                    "python/bionetgen/atomizer/modern/core.py",
                    "python/bionetgen/atomizer/modern/writer.py",
                    "cpp/parser/BNGAstVisitor.cpp",
                    "cpp/engine/OdeIntegrator.cpp",
                    "tests/validation/compare.py",
                )
            },
            "bng3_cli": str(bng3_binary),
            "bng3_cli_sha256": sha256(bng3_binary),
            "bng2_head": git_head(bng2_perl.parent),
            "bng2_git_state": git_state(bng2_perl.parent),
            "pybionetgen_head": git_head(pybionetgen_root),
            "pybionetgen_git_state": git_state(pybionetgen_root),
            "bng2_perl": str(bng2_perl),
            "pybionetgen_root": str(pybionetgen_root),
            "repeats": args.repeats,
            "modes": args.modes,
            "timeout_seconds": args.timeout,
        },
        "models": [
            benchmark_model(
                source,
                modes=list(args.modes),
                repeats=args.repeats,
                bng2_perl=bng2_perl,
                pybionetgen_root=pybionetgen_root,
                timeout=args.timeout,
            )
            for source in sources
        ],
        "scope_note": "Rate-expression parity is reported separately from structural parity. This benchmark does not claim trajectory parity or replace the full SBML validators.",
    }
    args.json_path.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"models={len(sources)} modes={len(args.modes)} repeats={args.repeats}")
    print(
        f"bng3={report['environment']['bng3_head']} bng2={report['environment']['bng2_head']} pybionetgen={report['environment']['pybionetgen_head']}"
    )
    print(f"report={args.json_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
