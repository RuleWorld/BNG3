#!/usr/bin/env python3
"""Run the predeclared source-to-native semantic/00966 acceptance campaign."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import scipy

from oracle_00966 import (
    BLOCK_SIZE,
    BLOCKS_PER_RUN,
    FLIPS_PER_RUN,
    SEEDS,
    SETTINGS_RELATIVE_PATH,
    SETTINGS_SHA256,
    SOURCE_RELATIVE_PATH,
    check_trajectory,
    validate_settings,
    validate_source,
)

SOURCE_SHA256 = "ca548837a5bd90def8861db03cc287849ce2b46084de438938d80e431bd28262"
CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "SSTS-semantic-00966-tie-order"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def add_output_functions(bngl: str) -> tuple[str, dict[str, str]]:
    """Add read-only functions so the API returns source parameter trajectories."""
    names = ("S", "Q", "R", *(f"chi{i}" for i in range(17)))
    exported = {name: f"check_{name}" for name in names}
    declarations = []
    for name, function in exported.items():
        expr = name if name == "S" else f"{name}_amt"
        declarations.append(f"  {function}() = {expr}")
    block = "\nbegin functions\n" + "\n".join(declarations) + "\nend functions\n"
    end_model = bngl.rfind("end model")
    if end_model < 0:
        raise RuntimeError("fresh Atomizer output has no 'end model'")
    return bngl[:end_model] + block + bngl[end_model:], exported


def get_product_identity(
    repo_root: Path, bng_cpp: Path, suite_identity_path: Path
) -> dict[str, Any]:
    import bionetgen

    extension = importlib.import_module("bionetgen._bionetgen_cpp")
    try:
        revision = (
            __import__("subprocess")
            .run(
                ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )
            .stdout.strip()
        )
        status = (
            __import__("subprocess")
            .run(
                ["git", "-C", str(repo_root), "status", "--porcelain=v1"],
                check=True,
                capture_output=True,
                text=True,
            )
            .stdout
        )
        product_diff = (
            __import__("subprocess")
            .run(
                ["git", "-C", str(repo_root), "diff", "--binary", "HEAD"],
                check=True,
                capture_output=True,
            )
            .stdout
        )
    except Exception as exc:
        raise RuntimeError(f"cannot establish product git identity: {exc}") from exc
    lock = repo_root / "provenance/upstreams.lock.yml"
    extension_path = Path(extension.__file__).resolve()
    expected_package = (repo_root / "python/bionetgen/__init__.py").resolve()
    if Path(bionetgen.__file__).resolve() != expected_package:
        raise RuntimeError(
            "imported bionetgen is not the exact --repo-root Python package"
        )
    try:
        bng_cpp.relative_to(repo_root)
    except ValueError as exc:
        raise RuntimeError("bng_cpp is outside --repo-root") from exc
    if extension_path.parent != bng_cpp.parent:
        raise RuntimeError(
            "bng_cpp and the imported native extension are from different build directories"
        )
    identity = json.loads(suite_identity_path.read_text(encoding="utf-8"))
    if identity.get("repository") != "https://github.com/sbmlteam/sbml-test-suite.git":
        raise RuntimeError("suite identity does not name the official SBML Test Suite")
    if identity.get("revision") != "cf38585fac5de8e0e90112febb62851ee2181816":
        raise RuntimeError(
            "suite identity revision differs from the pinned source lock"
        )
    if not identity.get("clean") or identity.get("status") != "passed":
        raise RuntimeError(
            "suite identity is not a clean, passed official-source validation"
        )
    if (
        not identity.get("validate_only")
        or identity.get("source_lock_status") != "accepted"
    ):
        raise RuntimeError(
            "suite identity lacks accepted validate-only source evidence"
        )
    if identity.get("source_lock_sha256") != sha256(lock):
        raise RuntimeError(
            "suite identity was validated against a different upstream lock"
        )
    package_path = Path(bionetgen.__file__).resolve()
    return {
        "product_revision": revision,
        "product_dirty_status": status.splitlines(),
        "tracked_product_diff_sha256": hashlib.sha256(product_diff).hexdigest(),
        "repository_root": str(repo_root),
        "bng_cpp": str(bng_cpp),
        "bng_cpp_sha256": sha256(bng_cpp),
        "python_package": str(package_path),
        "native_extension": str(extension_path),
        "native_extension_sha256": sha256(extension_path),
        "upstream_lock": str(lock),
        "upstream_lock_sha256": sha256(lock),
        "suite_identity_path": str(suite_identity_path),
        "suite_identity_sha256": sha256(suite_identity_path),
        "suite_identity": identity,
        "check_package_sha256": {
            path.name: sha256(path) for path in sorted(CASE_DIR.glob("*.py"))
        },
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }


def run_seed(
    *,
    seed: int,
    source: Path,
    work_dir: Path,
) -> dict[str, Any]:
    from bionetgen.atomizer.modern import Atomizer
    import bionetgen

    seed_dir = work_dir / f"seed-{seed:02d}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    source_text = source.read_text(encoding="utf-8")
    atomizer = Atomizer(atomize=False, quiet_mode=True, t_end=1000, n_steps=1000)
    translation = atomizer.atomize(source_text, source_path=source.resolve())
    if not translation.success:
        raise RuntimeError(f"Atomizer declined source: {translation.error}")
    translated, names = add_output_functions(translation.bngl)
    translated_path = seed_dir / "fresh-translation.bngl"
    translated_path.write_text(translated, encoding="utf-8")
    write_json(
        seed_dir / "translation.json",
        {
            "case_id": CASE_ID,
            "seed": seed,
            "source_path": str(source.resolve()),
            "source_sha256": sha256(source),
            "translation_stage": "fresh Atomizer translation from the original SBML input",
            "atomizer_success": translation.success,
            "atomizer_error": translation.error,
            "translation_sha256_before_output_functions": hashlib.sha256(
                translation.bngl.encode("utf-8")
            ).hexdigest(),
            "translation_sha256_with_output_functions": sha256(translated_path),
            "output_instrumentation": names,
        },
    )

    model = bionetgen.load(str(translated_path))
    result = model.simulate(
        method="ode",
        t_start=0,
        t_end=1000,
        n_steps=1000,
        seed=seed,
        sample_times=np.arange(0, 1001, dtype=float),
    )
    observations: dict[str, Any] = {"time": np.asarray(result.time, dtype=float)}
    for name, function in names.items():
        if function not in result.functions:
            raise RuntimeError(
                f"native result omits translated source parameter {name}"
            )
        observations[name] = np.asarray(result.functions[function], dtype=float)
    report = check_trajectory(observations, seed=seed)
    report.update(
        {
            "case_id": CASE_ID,
            "method": "ode",
            "backend": getattr(result, "backend", None),
            "fresh_translation_sha256": sha256(translated_path),
        }
    )
    observation_path = seed_dir / "observations.json"
    write_json(
        observation_path,
        {name: np.asarray(value).tolist() for name, value in observations.items()},
    )
    report["artifacts"] = {
        "translation": {
            "path": translated_path.name,
            "sha256": sha256(translated_path),
        },
        "translation_receipt": {
            "path": "translation.json",
            "sha256": sha256(seed_dir / "translation.json"),
        },
        "observations": {
            "path": observation_path.name,
            "sha256": sha256(observation_path),
        },
    }
    check_path = seed_dir / "check.json"
    write_json(check_path, report)
    report["artifacts"]["check_receipt"] = {
        "path": check_path.name,
        "sha256": sha256(check_path),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_RELATIVE_PATH)
    parser.add_argument("--suite-identity", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    repo_root = args.repo_root.resolve()
    suite_identity_path = args.suite_identity.resolve()
    bng_cpp = args.bng_cpp.resolve()
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    if not source.is_file() or sha256(source) != SOURCE_SHA256:
        raise SystemExit("source is not the pinned official semantic/00966 XML")
    settings = validate_settings(SETTINGS_RELATIVE_PATH)
    if settings["sha256"] != SETTINGS_SHA256:
        raise SystemExit("settings are not the pinned official semantic/00966 settings")
    if not bng_cpp.is_file():
        raise SystemExit(f"bng_cpp does not exist: {bng_cpp}")
    if not (repo_root / "provenance/upstreams.lock.yml").is_file():
        raise SystemExit(f"repository root lacks the upstream lock: {repo_root}")

    source_contract = validate_source(source)
    identity = get_product_identity(repo_root, bng_cpp, suite_identity_path)
    started = datetime.now(timezone.utc).isoformat()
    run = {
        "case_id": CASE_ID,
        "check_id": "release-event-stochastic",
        "status": "running",
        "started_utc": started,
        "source_sha256": sha256(source),
        "settings": settings,
        "source_contract": source_contract,
        "identity": identity,
        "predeclared_design": {
            "seeds": list(SEEDS),
            "duration": 1000,
            "output_times": "0, 1, ..., 1000",
            "flips_per_run": FLIPS_PER_RUN,
            "block_size": BLOCK_SIZE,
            "blocks_per_run": BLOCKS_PER_RUN,
            "tests_per_seed": 18,
            "familywise_alpha": 1e-6,
            "family_size": 16 * 18,
            "per_test_alpha": 1e-6 / (16 * 18),
            "random_expected_outputs": "analytic binomial laws; no pointwise reference trajectory",
        },
        "completed_seeds": [],
        "seed_artifacts": {},
    }
    write_json(work_dir / "run.json", run)

    reports = []
    for seed in SEEDS:
        try:
            report = run_seed(seed=seed, source=source, work_dir=work_dir)
            reports.append(report)
            run["completed_seeds"].append(seed)
            run["seed_artifacts"][str(seed)] = report["artifacts"]
            run["status"] = "running"
            write_json(work_dir / "run.json", run)
        except Exception as exc:
            seed_dir = work_dir / f"seed-{seed:02d}"
            seed_dir.mkdir(parents=True, exist_ok=True)
            (seed_dir / "failure.txt").write_text(
                f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}",
                encoding="utf-8",
            )
            run.update(
                {
                    "status": "harness_error",
                    "failed_seed": seed,
                    "failure": f"{type(exc).__name__}: {exc}",
                }
            )
            write_json(work_dir / "run.json", run)
            raise
    run.update(
        {
            "status": (
                "passed" if all(report["passed"] for report in reports) else "failed"
            ),
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "seeds_passed": sum(report["passed"] for report in reports),
                "seeds_total": len(reports),
                "failures": {
                    str(report["seed"]): report["failures"]
                    for report in reports
                    if not report["passed"]
                },
            },
            "limits": (
                "Pass applies only to this pinned source, product revision/build, 16 recorded seeds, "
                "the full 1000-unit horizon, and the checked total and 16-event histogram."
            ),
        }
    )
    write_json(work_dir / "run.json", run)
    print(json.dumps(run["summary"], indent=2, sort_keys=True))
    return 0 if run["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
