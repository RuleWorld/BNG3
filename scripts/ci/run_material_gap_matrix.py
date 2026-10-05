#!/usr/bin/env python3
"""Run the material-gap acceptance matrix with pinned provenance.

This is an evidence runner, not a release gate.  It records exact source
revisions, independent-oracle paths, commands, and bounded output tails in one
JSON artifact so a green local run cannot be confused with hosted CI or a
release qualification.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _revision(path: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _run(label: str, command: list[str], repo: Path, env: dict[str, str]) -> dict:
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        return {
            "label": label,
            "command": command,
            "returncode": completed.returncode,
            "passed": completed.returncode == 0,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "label": label,
            "command": command,
            "returncode": None,
            "passed": False,
            "timeout_s": 1800,
            "stdout_tail": (exc.stdout or "")[-4000:],
            "stderr_tail": (exc.stderr or "")[-4000:],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--bng-cpp", type=Path, required=True)
    parser.add_argument("--nfsim-bin", type=Path, required=True)
    parser.add_argument("--bng2", type=Path, required=True)
    parser.add_argument("--bng2-root", type=Path, required=True)
    parser.add_argument("--nfsim-root", type=Path, required=True)
    parser.add_argument("--pybionetgen-root", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument(
        "--installed-model", type=Path, default=Path("tests/python/test.bngl")
    )
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo.resolve()
    installed_model = args.installed_model
    if not installed_model.is_absolute():
        installed_model = repo / installed_model
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(repo),
            str(repo / "python"),
            str(repo / "build" / "cpp"),
            str(repo / "tests" / "energy"),
            env.get("PYTHONPATH", ""),
        ]
    )
    env["NFSIM_BIN"] = str(args.nfsim_bin.resolve())
    env["BNG_ENSEMBLE_WORKERS"] = "4"
    structural_env = env.copy()
    structural_env["PYTHONPATH"] = os.pathsep.join(
        [
            str(repo),
            str(repo / "python"),
            str(repo / "build" / "cpp"),
            os.environ.get("PYTHONPATH", ""),
        ]
    )

    results = [
        _run(
            "full-ctest",
            ["ctest", "--test-dir", "build", "--output-on-failure", "--no-tests=error"],
            repo,
            env,
        ),
        _run(
            "python-compatibility",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/python/test_compatibility_contract.py",
            ],
            repo,
            env,
        ),
        _run(
            "validation-comparator",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/validation/test_compare_net.py",
            ],
            repo,
            env,
        ),
        _run(
            "direct-native-nfsim",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/validation/test_parity_nfsim.py",
                "-k",
                "nf_vs_native or ast_direct_matches_xml or fixed_seed_direct_matches_native_at_final_endpoint",
            ],
            repo,
            env,
        ),
        _run(
            "direct-nf-protocol-contracts",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/python/test_cpp_backend.py",
                "-k",
                "simulate_protocol_supports_direct_nf or simulate_protocol_applies_concentration_before_nf",
            ],
            repo,
            env,
        ),
        _run(
            "bng2-structural-cross-validation",
            [
                sys.executable,
                "scripts/cross_validate.py",
                "--bng-cpp",
                str(args.bng_cpp.resolve()),
                "--bng-perl",
                str(args.bng2.resolve()),
                "--timeout",
                "120",
                "--model",
                "Haugh2b",
                "--model",
                "Motivating_example",
                "--model",
                "Repressilator",
                "--model",
                "egfr_net",
                "--model",
                "gene_expr_simple",
                "--model",
                "motor",
                "--model",
                "simple_system",
                "--model",
                "test_assignment",
                "--model",
                "test_compartment_XML",
            ],
            repo,
            structural_env,
        ),
        _run(
            "independent-energy-statistical-gate",
            [
                sys.executable,
                "tests/energy/scripts/nf_energy_statistical_parity.py",
                "tests/energy/fixtures/energy/constant_binding.bngl",
                "--seeds",
                "1024",
                "--t-end",
                "2",
                "--n-steps",
                "4",
                "--json",
                str(repo / "work" / "energy_statistical_parity.json"),
            ],
            repo,
            env,
        ),
        _run(
            "energy-cpu-benchmark",
            [
                sys.executable,
                "tests/energy/scripts/energy_cpu_benchmark.py",
                "tests/energy/fixtures/energy/symmetric_sites.bngl",
                "--bng-cpp",
                str(args.bng_cpp.resolve()),
                "--repeats",
                "5",
                "--json",
                str(repo / "work" / "energy_cpu_benchmark.json"),
            ],
            repo,
            env,
        ),
        _run(
            "installed-package-qualification",
            [
                sys.executable,
                "scripts/ci/qualify_installed_package.py",
                "--wheel",
                str(args.wheel.resolve()),
                "--model",
                str(installed_model.resolve()),
                "--json",
                str(repo / "work" / "installed_package_qualification.json"),
            ],
            repo,
            env,
        ),
    ]

    report = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "branch": subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "revisions": {
            "bng3": _revision(repo),
            "bng2": _revision(args.bng2_root.resolve()),
            "nfsim": _revision(args.nfsim_root.resolve()),
            "pybionetgen": _revision(args.pybionetgen_root.resolve()),
        },
        "independent_oracles": {
            "nfsim_binary": str(args.nfsim_bin.resolve()),
            "bng2": str(args.bng2.resolve()),
        },
        "results": results,
        "passed": all(result["passed"] for result in results),
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
