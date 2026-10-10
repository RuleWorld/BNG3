"""Manual, strict all-point trajectory probe for the bounded deletion fixtures.

Run with installed BNG3, independent BNG2_PERL/NFSIM_BIN, and their source
checkouts BNG2_SOURCE_DIR/NFSIM_SOURCE_DIR at the existing upstream lock. This
probe records failed parity without changing controls or hiding the last point.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess

import bionetgen
import numpy as np

from scripts.ci.check_python_package_identity import inspect_installed_package
from tests.validation import compare, oracle_nfsim, runner
from tests.validation.test_parity_nfsim_deletion import CASES, model_source

T_END, N_STEPS, FIXED_SEED, N_RUNS, BASE_SEED = 2.0, 20, 7, 200, 1


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def oracle_source(environment: str, expected: str, artifact: Path) -> dict:
    source = Path(os.environ[environment]).resolve()
    artifact.relative_to(source)
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain"], text=True
    ).strip()
    if revision != expected or status:
        raise RuntimeError(f"oracle source is not clean and pinned: {source}")
    return {"checkout": str(source), "revision": revision, "clean": True}


def probe(output: Path) -> dict:
    output = output.resolve()
    identity = inspect_installed_package()
    if os.environ.get("BNG3_PYTHON_TEST_MODE") != "installed":
        raise RuntimeError("qualification requires BNG3_PYTHON_TEST_MODE=installed")
    if os.environ.get("BNG_NFSIM_FORCE_XML") or os.environ.get(
        "BNG_NFSIM_ALLOW_XML_FALLBACK"
    ):
        raise RuntimeError("qualification requires unset NFsim route overrides")
    bng2 = Path(os.environ["BNG2_PERL"]).resolve()
    native = Path(os.environ["NFSIM_BIN"]).resolve()
    lock_path = Path(__file__).resolve().parents[2] / "provenance/upstreams.lock.yml"
    lock = json.loads(lock_path.read_text())["sources"]
    report = {
        "identity": identity,
        "controls": {
            "t_end": T_END,
            "n_steps": N_STEPS,
            "fixed_seed": FIXED_SEED,
            "ensemble_runs": N_RUNS,
            "base_seed": BASE_SEED,
            "native_workers": 2,
            "columns": compare.COLUMNS_EXACT,
        },
        "oracles": {
            "source_lock_sha256": digest(lock_path),
            "bng2_perl": str(bng2),
            "bng2_perl_sha256": digest(bng2),
            "nfsim": str(native),
            "nfsim_sha256": digest(native),
            "bng2_source": oracle_source(
                "BNG2_SOURCE_DIR", lock["bionetgen"]["revision"], bng2
            ),
            "nfsim_source": oracle_source(
                "NFSIM_SOURCE_DIR", lock["nfsim"]["revision"], native
            ),
        },
        "probe_sha256": digest(Path(__file__)),
        "cases": {},
    }
    for name, rule in CASES.items():
        work = output.parent / name
        work.mkdir(parents=True, exist_ok=True)
        source = work / f"{name}.bngl"
        source.write_text(model_source(rule) + "writeXML();\n")
        process = subprocess.run(
            [os.environ.get("PERL", "perl"), str(bng2), str(source)],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        (work / "bng2.log").write_text(process.stdout + process.stderr)
        xml = work / f"{name}.xml"

        def run_native(seed):
            gdat, error = oracle_nfsim.run_nfsim(
                xml, work / f"native-{seed}", t_end=T_END, n_steps=N_STEPS, seed=seed
            )
            if gdat is None:
                raise RuntimeError(error)
            data, columns = compare.parse_gdat(gdat)
            if data is None or columns is None or len(data) != N_STEPS + 1:
                raise RuntimeError("missing or incomplete native trajectory")
            return data, columns

        def run_api(seed):
            result = runner._result_to_trajectory(
                bionetgen.load(source).simulate(
                    method="nf", t_end=T_END, n_steps=N_STEPS, seed=seed
                )
            )
            if result.construction_path != "direct":
                raise RuntimeError(f"unexpected API route: {result.construction_path}")
            return result.data, result.columns

        fixed_native = run_native(FIXED_SEED)
        fixed_direct = run_api(FIXED_SEED)
        fixed = compare.compare_trajectories(
            *fixed_native,
            *fixed_direct,
            rtol=0,
            atol=0,
            columns=compare.COLUMNS_EXACT,
        )
        # Keep every point, including the final output coordinate. Record raw
        # mismatching rows independently of the comparator's time alignment.
        rows = np.flatnonzero(
            np.any(
                fixed_native[0][:, 1:]
                != fixed_direct[0][
                    :, [fixed_direct[1].index(name) for name in fixed_native[1][1:]]
                ],
                axis=1,
            )
        ).tolist()
        seeds = range(BASE_SEED, BASE_SEED + N_RUNS)
        with ThreadPoolExecutor(max_workers=2) as pool:
            native_runs = list(pool.map(run_native, seeds))
        direct_runs = [run_api(seed) for seed in seeds]
        ensemble = compare.compare_stochastic(
            native_runs,
            direct_runs,
            min_ref_runs=N_RUNS,
            min_test_runs=N_RUNS,
            columns=compare.COLUMNS_EXACT,
        )
        report["cases"][name] = {
            "source_sha256": digest(source),
            "columns": fixed_native[1],
            "independent_xml_sha256": digest(xml),
            "fixed_seed": asdict(fixed),
            "fixed_seed_mismatching_rows": rows,
            "fixed_seed_native_final": fixed_native[0][-1].tolist(),
            "fixed_seed_direct_final": fixed_direct[0][-1].tolist(),
            "ensemble": asdict(ensemble),
            "native_runs": len(native_runs),
            "direct_runs": len(direct_runs),
        }
    report["all_parity_passed"] = all(
        case["fixed_seed"]["ok"] and case["ensemble"]["ok"]
        for case in report["cases"].values()
    )
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    return 0 if probe(args.output)["all_parity_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
