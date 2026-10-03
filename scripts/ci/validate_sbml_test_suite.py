#!/usr/bin/env python3
"""Run BNG3's SBML round-trip gate over the official SBML Test Suite.

This checks the canonical semantic and stochastic SBML cases from a pinned
suite checkout.  It validates source and generated XML, imports each case
through the modern Atomizer and C++ network generator, writes SBML, reimports
that output, and checks the native C++ SBML reader's species/reaction counts.
It is an import/round-trip gate, not a claim of numerical SBML Test Suite
simulation conformance.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import importlib.metadata
import itertools
import json
import math
import platform
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import numpy as np

VERSION_PRIORITY = ("l3v2", "l3v1", "l2v5", "l2v4", "l2v3", "l2v2", "l2v1", "l1v2")
NUMERICAL_COMPARISON_ATOL_FLOOR = 5e-12
# BNG3 and libRoadRunner use separate CVODE wrappers and evaluate assignment
# rules/dense output at different points. Use one documented cross-engine
# relative floor instead of case-specific tolerances.
# libRoadRunner and BNG3 use independent CVODE builds and Jacobian paths;
# retain a small model-scale floor for cross-engine dense-output differences.
NUMERICAL_COMPARISON_RTOL_FLOOR = 1e-5
UNSUPPORTED_MARKERS = (
    "unsupported",
    "not representable",
    "not executable",
    "not implemented",
    "dropped",
    "cannot be represented",
    "not losslessly representable",
    "gcd(",
    "lcm(",
    "notanumber",
)
DEFAULT_SUITE_LOCK = (
    Path(__file__).resolve().parents[2] / "provenance" / "upstreams.lock.yml"
)
SUITE_LOCK_NAME = "sbml-test-suite"
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class SuiteLockError(ValueError):
    """Raised when the suite checkout does not match its immutable source lock."""


class OfficialReferenceUnsupported(ValueError):
    """Raised when a locked case has no deterministic time-course reference."""


def _suite_lock_entry(lock_path: Path = DEFAULT_SUITE_LOCK) -> dict[str, str]:
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SuiteLockError(
            f"cannot read suite source lock {lock_path}: {exc}"
        ) from exc
    sources = lock.get("sources") if isinstance(lock, dict) else None
    source = sources.get(SUITE_LOCK_NAME) if isinstance(sources, dict) else None
    if not isinstance(source, dict):
        raise SuiteLockError(
            f"sources.{SUITE_LOCK_NAME} is missing from the source lock"
        )
    repository = source.get("repository")
    revision = source.get("revision")
    if not isinstance(repository, str) or not re.fullmatch(
        r"https://github\.com/[^/]+/[^/]+\.git", repository
    ):
        raise SuiteLockError(
            f"sources.{SUITE_LOCK_NAME}.repository must be a canonical GitHub .git URL"
        )
    if not isinstance(revision, str) or not GIT_SHA_RE.fullmatch(revision):
        raise SuiteLockError(
            f"sources.{SUITE_LOCK_NAME}.revision must be a full lowercase Git SHA"
        )
    if source.get("status") not in {"observed", "accepted"}:
        raise SuiteLockError(
            f"sources.{SUITE_LOCK_NAME}.status must be observed or accepted"
        )
    return {
        "repository": repository,
        "revision": revision,
        "status": str(source["status"]),
    }


def _validate_suite_checkout(
    suite_dir: Path, lock_path: Path = DEFAULT_SUITE_LOCK
) -> dict[str, Any]:
    """Require the clean suite repository and HEAD to match the source lock."""

    lock_path = lock_path.expanduser().resolve()
    source = _suite_lock_entry(lock_path)
    suite_dir = suite_dir.expanduser().resolve()
    if not suite_dir.is_dir():
        raise SuiteLockError(f"suite directory does not exist: {suite_dir}")

    def git(*arguments: str) -> str:
        try:
            return subprocess.check_output(
                ["git", "-C", str(suite_dir), *arguments],
                text=True,
                stderr=subprocess.PIPE,
            ).strip()
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip()
            raise SuiteLockError(
                f"cannot inspect suite checkout {suite_dir}: {detail or exc}"
            ) from exc

    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    if root != suite_dir:
        raise SuiteLockError(
            f"suite directory must be repository root: {suite_dir} (root: {root})"
        )
    actual_revision = git("rev-parse", "HEAD")
    if actual_revision != source["revision"]:
        raise SuiteLockError(
            "suite revision mismatch: "
            f"checked out {actual_revision}, locked {source['revision']}"
        )
    try:
        repository = git("remote", "get-url", "origin")
    except SuiteLockError as exc:
        raise SuiteLockError("suite checkout has no origin remote") from exc
    if repository != source["repository"]:
        raise SuiteLockError(
            f"suite origin mismatch: found {repository}, locked {source['repository']}"
        )
    if git("status", "--porcelain", "--untracked-files=all"):
        raise SuiteLockError(f"suite checkout is dirty: {suite_dir}")
    return {
        "repository": repository,
        "revision": actual_revision,
        "source_lock_status": source["status"],
        "source_lock_path": str(lock_path),
        "source_lock_sha256": _sha256_file(lock_path),
        "clean": True,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_reference_case(case: dict[str, Any]) -> dict[str, Any]:
    """Read one deterministic SSTS settings/results pair without guessing."""

    if case.get("category") != "semantic":
        raise ValueError(
            "official deterministic reference reader requires a semantic case"
        )
    case_dir = Path(case["path"]).resolve().parent
    case_id = str(case["id"])
    settings_path = case_dir / f"{case_id}-settings.txt"
    results_path = case_dir / f"{case_id}-results.csv"
    try:
        settings_text = settings_path.read_text(encoding="utf-8-sig")
        results_text = results_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read official reference data: {exc}") from exc

    settings: dict[str, str] = {}
    for line_number, line in enumerate(settings_text.splitlines(), start=1):
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"settings line {line_number} has no ':' delimiter")
        key, value = (part.strip() for part in line.split(":", 1))
        if not key or key in settings:
            raise ValueError(
                f"settings line {line_number} has an empty or duplicate key"
            )
        settings[key] = value
    required = {
        "start",
        "duration",
        "steps",
        "variables",
        "absolute",
        "relative",
        "amount",
        "concentration",
    }
    missing = sorted(required - settings.keys())
    if missing:
        raise ValueError("settings are missing required keys: " + ", ".join(missing))
    time_fields = [settings[key] for key in ("start", "duration", "steps")]
    if all(not value for value in time_fields):
        raise OfficialReferenceUnsupported(
            "case does not define an official time-course reference"
        )
    if any(not value for value in time_fields):
        raise ValueError("settings must provide start, duration, and steps together")

    try:
        start = float(settings["start"])
        duration = float(settings["duration"])
        absolute = float(settings["absolute"])
        relative = float(settings["relative"])
        steps_text = settings["steps"]
        steps = int(steps_text)
    except ValueError as exc:
        raise ValueError(f"settings contain an invalid numeric value: {exc}") from exc
    if not all(math.isfinite(value) for value in (start, duration, absolute, relative)):
        raise ValueError("settings numeric values must be finite")
    if duration < 0 or steps <= 0:
        raise ValueError("settings duration must be non-negative and steps positive")
    if steps_text.strip() != str(steps):
        raise ValueError("settings steps must be a base-10 integer")
    if absolute < 0 or relative < 0:
        raise ValueError("settings tolerances must be non-negative")

    def parse_ids(key: str) -> list[str]:
        ids = [value.strip() for value in settings[key].split(",") if value.strip()]
        if len(ids) != len(set(ids)):
            raise ValueError(f"settings {key} list contains duplicate identifiers")
        return ids

    variables = parse_ids("variables")
    amount = parse_ids("amount")
    concentration = parse_ids("concentration")
    if not variables or len(variables) != len(set(variables)):
        raise ValueError("settings variables must contain unique identifiers")
    variable_set = set(variables)
    if not set(amount) <= variable_set or not set(concentration) <= variable_set:
        raise ValueError("amount and concentration IDs must appear in variables")
    if set(amount) & set(concentration):
        raise ValueError("an output variable cannot be both amount and concentration")

    rows = list(csv.reader(results_text.splitlines()))
    if not rows or any(not row for row in rows):
        raise ValueError("official results CSV is empty or contains a blank row")
    expected_header = ["time", *variables]
    first = [cell.strip() for cell in rows[0]]
    has_header = bool(first and first[0].lower() == "time")
    if has_header:
        normalized_header = [first[0].lower(), *first[1:]]
        if normalized_header != expected_header:
            raise ValueError(
                "official results header does not match settings variable order: "
                f"expected {expected_header}, found {first}"
            )
        data_rows = rows[1:]
        row_offset = 1
    else:
        data_rows = rows
        row_offset = 0
    if len(data_rows) != steps + 1:
        raise ValueError(
            f"official results row count {len(data_rows)} does not equal steps + 1 ({steps + 1})"
        )
    expected_grid = np.linspace(start, start + duration, steps + 1, dtype=float)
    values: list[list[float]] = []
    time_rounding_tolerances = []
    for row_number, row in enumerate(data_rows, start=row_offset + 1):
        if len(row) != len(expected_header):
            raise ValueError(
                f"official results row {row_number} has {len(row)} columns; "
                f"expected {len(expected_header)}"
            )
        try:
            values.append([float(cell.strip()) for cell in row])
        except ValueError as exc:
            raise ValueError(
                f"official results row {row_number} is not numeric"
            ) from exc
        try:
            decimal_time = Decimal(row[0].strip())
        except InvalidOperation as exc:
            raise ValueError(
                f"official results row {row_number} has invalid time"
            ) from exc
        if not decimal_time.is_finite():
            raise ValueError(f"official results row {row_number} has non-finite time")
        time_token = row[0].strip().lower()
        if "." not in time_token and "e" not in time_token:
            time_rounding_tolerances.append(1e-12)
        else:
            rounding_exponent = decimal_time.as_tuple().exponent
            time_rounding_tolerances.append(
                max(1e-12, float(Decimal(5).scaleb(rounding_exponent - 1)))
            )
    matrix = np.asarray(values, dtype=float)
    times = matrix[:, 0]
    grid_tolerances = np.asarray(time_rounding_tolerances, dtype=float)
    grid_tolerances = np.maximum(
        grid_tolerances, np.maximum(1e-12, np.abs(expected_grid) * 1e-14)
    )
    if not np.all(np.isfinite(times)) or not np.all(
        np.abs(times - expected_grid) <= grid_tolerances
    ):
        raise ValueError(
            "official results time grid does not match settings start/duration/steps"
        )
    return {
        "settings_path": str(settings_path),
        "results_path": str(results_path),
        "settings_sha256": _sha256_file(settings_path),
        "results_sha256": _sha256_file(results_path),
        "start": start,
        "duration": duration,
        "steps": steps,
        "times": times,
        "variables": variables,
        "amount": amount,
        "concentration": concentration,
        "absolute": absolute,
        "relative": relative,
        "expected": {
            variable: matrix[:, index + 1] for index, variable in enumerate(variables)
        },
    }


def _compare_reference_series(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    absolute: float,
    relative: float,
    sample_times: Any | None = None,
) -> dict[str, Any]:
    """Apply the official pointwise absolute-plus-relative error formula."""

    if not math.isfinite(absolute) or not math.isfinite(relative):
        raise ValueError("official tolerances must be finite")
    if absolute < 0 or relative < 0:
        raise ValueError("official tolerances must be non-negative")
    times = None if sample_times is None else np.asarray(sample_times, dtype=float)
    formula = "abs(expected-actual) <= absolute + relative*abs(expected)"
    comparisons: dict[str, dict[str, Any]] = {}
    failed_variables = []
    total_points = 0
    passed_points = 0
    for variable, expected_values in expected.items():
        left = np.asarray(expected_values, dtype=float)
        right_raw = actual.get(variable)
        if right_raw is None:
            failed_indices = list(range(int(left.size)))
            comparisons[variable] = {
                "passed": False,
                "reason": "actual output is missing",
                "sample_count": int(left.size),
                "passed_points": 0,
                "failed_points": int(left.size),
                "failed_sample_index_count": int(left.size),
                "failed_sample_indices": failed_indices[:25],
                "failed_sample_indices_truncated": len(failed_indices) > 25,
                "finite_points": int(np.isfinite(left).sum()),
                "nonfinite_points": int((~np.isfinite(left)).sum()),
                "max_abs_difference": None,
                "max_scaled_error": None,
            }
            failed_variables.append(variable)
            total_points += int(left.size)
            continue
        right = np.asarray(right_raw, dtype=float)
        if left.ndim != 1 or right.ndim != 1 or left.shape != right.shape:
            failed_indices = list(range(int(left.size)))
            comparisons[variable] = {
                "passed": False,
                "reason": f"actual shape {right.shape} does not match reference shape {left.shape}",
                "sample_count": int(left.size),
                "passed_points": 0,
                "failed_points": int(left.size),
                "failed_sample_index_count": int(left.size),
                "failed_sample_indices": failed_indices[:25],
                "failed_sample_indices_truncated": len(failed_indices) > 25,
                "finite_points": int(np.isfinite(left).sum()),
                "nonfinite_points": int((~np.isfinite(left)).sum()),
                "max_abs_difference": None,
                "max_scaled_error": None,
            }
            failed_variables.append(variable)
            total_points += int(left.size)
            continue
        if times is not None and (times.ndim != 1 or times.shape != left.shape):
            raise ValueError(
                f"sample time shape {times.shape} does not match reference shape {left.shape}"
            )

        left_finite = np.isfinite(left)
        right_finite = np.isfinite(right)
        finite_match = left_finite & right_finite
        nonfinite_match = (np.isnan(left) & np.isnan(right)) | (
            np.isinf(left) & np.isinf(right) & (left == right)
        )
        point_passed = nonfinite_match.copy()
        differences = np.abs(left[finite_match] - right[finite_match])
        tolerances = absolute + relative * np.abs(left[finite_match])
        finite_passed = differences <= tolerances
        point_passed[finite_match] = finite_passed
        max_scaled = 0.0
        if differences.size:
            scaled = np.divide(
                differences,
                tolerances,
                out=np.where(
                    differences == 0.0, 0.0, math.inf * np.ones_like(differences)
                ),
                where=tolerances != 0.0,
            )
            max_scaled = float(np.max(scaled))
        variable_passed = bool(np.all(point_passed))
        passed_count = int(point_passed.sum())
        failed_indices = np.flatnonzero(~point_passed).astype(int).tolist()
        total_points += int(left.size)
        passed_points += passed_count
        if not variable_passed:
            failed_variables.append(variable)
        failed_examples = []
        for index in failed_indices[:5]:
            expected_value = float(left[index])
            actual_value = float(right[index])
            expected_finite = math.isfinite(expected_value)
            actual_finite = math.isfinite(actual_value)
            example = {
                "index": index,
                "expected": expected_value if expected_finite else str(expected_value),
                "actual": actual_value if actual_finite else str(actual_value),
                "absolute_difference": (
                    abs(expected_value - actual_value)
                    if expected_finite and actual_finite
                    else None
                ),
                "tolerance": (
                    absolute + relative * abs(expected_value)
                    if expected_finite
                    else None
                ),
            }
            if times is not None:
                example["time"] = float(times[index])
            failed_examples.append(example)
        comparisons[variable] = {
            "passed": variable_passed,
            "sample_count": int(left.size),
            "passed_points": passed_count,
            "failed_points": int(left.size - passed_count),
            "failed_sample_index_count": len(failed_indices),
            "failed_sample_indices": failed_indices[:25],
            "failed_sample_indices_truncated": len(failed_indices) > 25,
            "failed_sample_examples": failed_examples,
            "finite_points": int(finite_match.sum()),
            "nonfinite_points": int((~left_finite).sum()),
            "max_abs_difference": (
                float(np.max(differences)) if differences.size else None
            ),
            "max_scaled_error": max_scaled,
        }
    return {
        "passed": not failed_variables,
        "tolerance_formula": formula,
        "absolute": absolute,
        "relative": relative,
        "sample_count": total_points,
        "passed_points": passed_points,
        "failed_points": total_points - passed_points,
        "failed_variables": failed_variables,
        "variables": comparisons,
    }


def _repository_provenance(repo_root: Path) -> dict[str, Any]:
    """Return commit identity and a digest of all non-coordination source edits."""

    repo_root = repo_root.resolve()
    commit = None
    tracked_worktree_clean = None
    changed_files: list[str] = []
    untracked_files: list[str] = []
    source_diff_sha256 = hashlib.sha256(b"").hexdigest()
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        pass
    if commit is not None:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), "diff", "--quiet", "HEAD"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode in (0, 1):
                tracked_worktree_clean = result.returncode == 0
        except Exception:
            pass
        try:
            changed_files = sorted(
                path
                for path in subprocess.check_output(
                    ["git", "-C", str(repo_root), "diff", "--name-only", "HEAD"],
                    text=True,
                ).splitlines()
                if path != "lane-status.json"
            )
            untracked_files = sorted(
                path
                for path in subprocess.check_output(
                    [
                        "git",
                        "-C",
                        str(repo_root),
                        "ls-files",
                        "--others",
                        "--exclude-standard",
                    ],
                    text=True,
                ).splitlines()
                if path != "lane-status.json"
            )
            digest = hashlib.sha256()
            digest.update(
                subprocess.check_output(
                    ["git", "-C", str(repo_root), "diff", "--binary", "HEAD"]
                )
            )
            for relative_path in untracked_files:
                digest.update(relative_path.encode("utf-8") + b"\0")
                digest.update((repo_root / relative_path).read_bytes())
            source_diff_sha256 = digest.hexdigest()
        except Exception:
            pass

    worktree_clean_for_report = (
        tracked_worktree_clean is True and not changed_files and not untracked_files
    )
    return {
        "bng3_commit": commit,
        "bng3_tracked_worktree_clean": tracked_worktree_clean,
        "bng3_worktree_clean_for_report": worktree_clean_for_report,
        "bng3_changed_files": changed_files,
        "bng3_untracked_files": untracked_files,
        "bng3_source_diff_sha256": source_diff_sha256,
        "excluded_coordination_files": ["lane-status.json"],
    }


def _runtime_provenance(cpp: Any) -> dict[str, Any]:
    """Record interpreter, Python package, native extension, and oracle versions."""

    import bionetgen

    extension_path = Path(cpp.__file__)
    resolved_extension_path = extension_path.resolve()
    try:
        import libsbml

        libsbml_version = libsbml.getLibSBMLDottedVersion()
    except ImportError:
        libsbml_version = None
    try:
        import roadrunner

        roadrunner_version = getattr(roadrunner, "__version__", None)
    except ImportError:
        roadrunner_version = None
    try:
        bionetgen_version = importlib.metadata.version("bionetgen")
    except importlib.metadata.PackageNotFoundError:
        bionetgen_version = getattr(bionetgen, "__version__", None)
    return {
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "bionetgen_version": bionetgen_version,
        "bionetgen_package_path": str(Path(bionetgen.__file__).resolve()),
        "native_extension_path": str(extension_path),
        "native_extension_resolved_path": str(resolved_extension_path),
        "native_extension_sha256": _sha256_file(resolved_extension_path),
        "numpy_version": np.__version__,
        "libsbml_version": libsbml_version,
        "roadrunner_version": roadrunner_version,
    }


def _validate_xml(text: str, label: str) -> dict[str, Any]:
    try:
        import libsbml
    except ImportError:
        ET.fromstring(text)
        return {"passed": True, "validator": "xml.etree"}
    document = libsbml.readSBMLFromString(text)
    errors = int(document.getNumErrors())
    if errors:
        messages = [
            document.getError(index).getMessage() for index in range(min(errors, 5))
        ]
        raise RuntimeError(f"{label} has {errors} libSBML error(s): {messages}")
    consistency_errors = int(document.checkInternalConsistency())
    if consistency_errors:
        raise RuntimeError(
            f"{label} has {consistency_errors} libSBML consistency error(s)"
        )
    return {"passed": True, "validator": "libsbml", "errors": errors}


def _max_finite_abs(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    return float(np.max(np.abs(finite))) if finite.size else 0.0


def _compare_observable_samples(
    left: np.ndarray, right: np.ndarray, tolerance: float
) -> dict[str, Any]:
    """Compare finite values and require exact agreement on nonfinite classes."""
    left = np.asarray(left, dtype=float)
    right = np.asarray(right, dtype=float)
    if left.shape != right.shape:
        raise RuntimeError("observable samples have mismatched shapes")
    left_finite = np.isfinite(left)
    right_finite = np.isfinite(right)
    nonfinite_equivalent = bool(
        np.array_equal(left_finite, right_finite)
        and np.array_equal(np.isnan(left), np.isnan(right))
        and np.array_equal(np.isposinf(left), np.isposinf(right))
        and np.array_equal(np.isneginf(left), np.isneginf(right))
    )
    finite_pairs = left_finite & right_finite
    differences = np.abs(left[finite_pairs] - right[finite_pairs])
    max_abs = float(np.max(differences)) if differences.size else 0.0
    scale = max(_max_finite_abs(left), _max_finite_abs(right))
    passed = nonfinite_equivalent and max_abs <= tolerance
    return {
        "finite": bool(left_finite.all() and right_finite.all()),
        "nonfinite_equivalent": nonfinite_equivalent,
        "finite_sample_count": int(finite_pairs.sum()),
        "nonfinite_sample_count": (
            int((~left_finite).sum()) if nonfinite_equivalent else None
        ),
        "max_abs_difference": max_abs,
        "tolerance": tolerance,
        "max_scaled_error": max_abs / tolerance if tolerance else math.inf,
        "passed": passed,
        "scale": scale,
    }


def _simulate_and_compare(
    cpp_model: Any,
    output_path: Path,
    *,
    t_end: float,
    n_steps: int,
    rtol: float,
    atol: float,
    function_names: set[str] | None = None,
) -> dict[str, Any]:
    """Compare BNG3/CVODE observables with libRoadRunner on one time grid."""

    try:
        import roadrunner
        from bionetgen import BioNetGenModel
    except ImportError as exc:
        raise RuntimeError(
            "libRoadRunner is required for direct numerical comparison"
        ) from exc
    bng_result = BioNetGenModel(cpp_model).simulate(
        method="ode",
        t_start=0.0,
        t_end=t_end,
        n_steps=n_steps,
        rtol=rtol,
        atol=atol,
    )
    series = dict(bng_result.observables)
    function_values = getattr(bng_result, "functions", {}) or {}
    if function_names is None:
        series.update(function_values)
    else:
        series.update(
            {
                name: values
                for name, values in function_values.items()
                if name in function_names
            }
        )
    names = list(series)
    bng_time = np.asarray(bng_result.time, dtype=float)
    bng_values = {name: np.asarray(series[name], dtype=float) for name in names}
    rr = roadrunner.RoadRunner(str(output_path))
    integrator = rr.integrator
    if integrator.hasValue("relative_tolerance"):
        integrator.setValue("relative_tolerance", rtol)
    if integrator.hasValue("absolute_tolerance"):
        integrator.setValue("absolute_tolerance", atol)
    available = set(rr.getAssignmentRuleIds())

    def sbml_id(name: str) -> str:
        valid = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
        if valid and valid[0].isdigit():
            valid = "_" + valid
        return valid or "species"

    selected_names = []
    missing = []
    for name in names:
        safe_name = sbml_id(name)
        # The C++ SBML writer prefixes a function when its source name
        # collides with a generated network species or parameter ID.
        candidates = [
            safe_name,
            "obs_" + safe_name,
            "func_" + safe_name,
            "param_" + safe_name,
        ]
        selected = next(
            (candidate for candidate in candidates if candidate in available), None
        )
        if selected is None:
            missing.append(name)
        else:
            selected_names.append(selected)
    if missing:
        raise RuntimeError(
            "written SBML is missing observable assignment rules: "
            + ", ".join(missing[:10])
        )
    rr.timeCourseSelections = ["time", *selected_names]
    rr_values = np.asarray(rr.simulate(0.0, t_end, n_steps + 1), dtype=float)
    expected_shape = (len(bng_time), len(names) + 1)
    if rr_values.ndim != 2 or rr_values.shape != expected_shape:
        raise RuntimeError(
            f"libRoadRunner returned shape {rr_values.shape}, expected {expected_shape}"
        )
    if not np.allclose(rr_values[:, 0], bng_time, rtol=0.0, atol=max(atol, 1e-12)):
        raise RuntimeError("BNG3 and libRoadRunner produced different time grids")
    comparison_scale = max(
        [
            *(_max_finite_abs(values) for values in bng_values.values() if values.size),
            *(
                _max_finite_abs(rr_values[:, index])
                for index in range(1, rr_values.shape[1])
                if rr_values.shape[0]
            ),
            0.0,
        ]
    )
    comparisons: dict[str, dict[str, Any]] = {}
    failed = []
    for index, name in enumerate(names, start=1):
        left = bng_values[name]
        right = rr_values[:, index]
        if left.shape != right.shape:
            raise RuntimeError(f"observable {name!r} returned mismatched shapes")
        scale = max(
            _max_finite_abs(left) if left.size else 0.0,
            _max_finite_abs(right) if right.size else 0.0,
        )
        # BNG3 and libRoadRunner both use CVODE, but their dense-output and
        # RHS evaluation paths differ. Keep a small global floor for
        # cross-engine round-trip comparison.
        # Use one model-wide reference scale. A small product/side species
        # inherits the same absolute CVODE error as its larger reactant, so a
        # per-observable relative tolerance would reject valid parity.
        tolerance = max(
            atol + rtol * scale,
            NUMERICAL_COMPARISON_ATOL_FLOOR
            + NUMERICAL_COMPARISON_RTOL_FLOOR * comparison_scale,
        )
        comparison = _compare_observable_samples(left, right, tolerance)
        if not comparison["passed"]:
            failed.append(name)
        comparison.pop("scale")
        comparisons[name] = comparison
    if failed:
        return {
            "passed": False,
            "error": (
                "BNG3 CVODE/libRoadRunner observable mismatch: "
                + ", ".join(failed[:10])
            ),
            "method_bngl": "BNG3 CVODE (simulate method='ode')",
            "method_sbml": "libRoadRunner CVODE",
            "roadrunner_version": getattr(roadrunner, "__version__", None),
            "t_start": 0.0,
            "t_end": t_end,
            "n_steps": n_steps,
            "rtol": rtol,
            "atol": atol,
            "comparison_atol_floor": NUMERICAL_COMPARISON_ATOL_FLOOR,
            "comparison_rtol_floor": NUMERICAL_COMPARISON_RTOL_FLOOR,
            "comparison_reference_scale": comparison_scale,
            "observable_count": len(names),
            "sbml_observable_ids": dict(zip(names, selected_names)),
            "failed_observables": failed,
            "observables": comparisons,
        }
    return {
        "passed": True,
        "method_bngl": "BNG3 CVODE (simulate method='ode')",
        "method_sbml": "libRoadRunner CVODE",
        "roadrunner_version": getattr(roadrunner, "__version__", None),
        "t_start": 0.0,
        "t_end": t_end,
        "n_steps": n_steps,
        "rtol": rtol,
        "atol": atol,
        "comparison_atol_floor": NUMERICAL_COMPARISON_ATOL_FLOOR,
        "comparison_rtol_floor": NUMERICAL_COMPARISON_RTOL_FLOOR,
        "comparison_reference_scale": comparison_scale,
        "observable_count": len(names),
        "sbml_observable_ids": dict(zip(names, selected_names)),
        "observables": comparisons,
    }


def _case_files(suite_dir: Path, categories: list[str]) -> list[dict[str, Any]]:
    cases = []
    for category in categories:
        root = suite_dir / "cases" / category
        if not root.is_dir():
            continue
        for case_dir in sorted(root.iterdir()):
            if not case_dir.is_dir() or not re.fullmatch(r"\d{5}", case_dir.name):
                continue
            source = next(
                (
                    case_dir / f"{case_dir.name}-sbml-{version}.xml"
                    for version in VERSION_PRIORITY
                    if (case_dir / f"{case_dir.name}-sbml-{version}.xml").exists()
                ),
                None,
            )
            if source is not None:
                cases.append(
                    {
                        "category": category,
                        "id": case_dir.name,
                        "version": source.stem.rsplit("-", 1)[-1],
                        "path": source,
                    }
                )
    return cases


def _is_partial_run(
    categories: list[str], max_cases: int, only_case: str | None
) -> bool:
    """Report a run as partial unless it covers both full suite categories."""

    return bool(max_cases or only_case or set(categories) != {"semantic", "stochastic"})


def _classify_error(message: str) -> str:
    lower = message.lower()
    return (
        "unsupported"
        if any(marker in lower for marker in UNSUPPORTED_MARKERS)
        else "failed"
    )


def _warning_limitations(warnings: list[dict[str, Any]]) -> list[str]:
    return [
        str(warning["message"])
        for warning in warnings
        if any(
            marker in str(warning["message"]).lower() for marker in UNSUPPORTED_MARKERS
        )
    ]


def _simulation_limitations(warnings: list[dict[str, Any]]) -> list[str]:
    """Return warnings that prevent an executable numerical claim.

    ``approximated`` is intentionally a hard boundary here.  The parser uses
    that severity for source constructs such as variable stoichiometry and
    lossy MathML that can be rendered into BNGL text but cannot be claimed
    equivalent by this numerical gate.  Informational unit-scale notes are
    retained because the parser deliberately preserves the source numeric
    scale in that case.
    """

    limitations = []
    for warning in warnings:
        message = str(warning["message"])
        if (
            warning["severity"] in {"dropped", "approximated"}
            and warning.get("category") != "units"
        ):
            limitations.append(message)
    return limitations


def _event_translation_limitations(bngl: str) -> list[str]:
    """Return explicit diagnostics for events the BNGL action lowering rejected."""

    marker = "# Events NOT simulated"
    if marker not in bngl:
        return []
    details = []
    in_notes = False
    for line in bngl.splitlines():
        # The writer appends a parenthetical to this header, so match on the
        # prefix; an equality test never fires and silently drops every
        # per-event refusal reason the lowering already reported.
        if line.strip().startswith(marker):
            in_notes = True
            continue
        if in_notes and line.startswith("# ============================"):
            break
        if in_notes and line.startswith("#") and line.strip() != "#":
            details.append(line.lstrip("# "))
    detail = " | ".join(details[:8])
    return [
        "Generated BNGL retained untranslated SBML event(s); "
        "state-dependent or dynamic event scheduling is outside the BNGL action engine."
        + (f" Details: {detail}" if detail else "")
    ]


def _reference_output_target(
    variable: str,
    reference: dict[str, Any],
    parsed: Any,
    observable_map: dict[str, str],
    standardize_name: Any,
) -> str | None:
    """Map an SBML result id to its exact generated BNGL output symbol."""

    if variable == "time":
        return "time"

    def compartment_volume(compartment_id: str) -> str | None:
        if not compartment_id:
            return None
        compartment_name = standardize_name(compartment_id)
        if any(
            rule.type == "rate" and rule.variable == compartment_id
            for rule in parsed.rules
        ):
            return f"{compartment_name}_amt"
        if any(
            rule.type == "assignment" and rule.variable == compartment_id
            for rule in parsed.rules
        ):
            return compartment_name
        return f"__compartment_{compartment_name}__"

    species = parsed.species.get(variable)
    if species is not None:
        observable = observable_map.get(variable)
        if observable is None:
            if not any(
                rule.type == "assignment" and rule.variable == variable
                for rule in parsed.rules
            ):
                return None
            observable = standardize_name(variable)
            amount_unit = variable in reference["amount"] or (
                variable not in reference["concentration"]
                and species.has_only_substance_units
            )
            volume = compartment_volume(species.compartment or "")
            if amount_unit:
                if species.has_only_substance_units:
                    return observable
                return f"{observable} * {volume}" if volume else None
            if not species.has_only_substance_units:
                return observable
            return f"{observable} / {volume}" if volume else None
        if variable in reference["amount"] or (
            variable not in reference["concentration"]
            and species.has_only_substance_units
        ):
            return f"{observable}_amt"
        volume = compartment_volume(species.compartment or "")
        return f"{observable}_amt / {volume}" if volume else None
    if any(rule.type == "rate" and rule.variable == variable for rule in parsed.rules):
        return f"{standardize_name(variable)}_amt"
    if variable in parsed.compartments:
        return compartment_volume(variable)
    if variable in parsed.parameters:
        return standardize_name(variable)
    if any(rule.variable == variable for rule in parsed.rules):
        return standardize_name(variable)
    return None


def _with_reference_output_functions(
    bngl: str, targets: dict[str, str], case_id: str
) -> tuple[str, dict[str, str]]:
    """Add named result aliases to a private BNGL copy for conformance output."""

    expressions: dict[str, str] = {}
    used_names = set(re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z_0-9]*)\s*\(", bngl))
    for index, (variable, target) in enumerate(targets.items()):
        base = f"SSTSREF_{case_id}_{index:04d}"
        alias = base
        suffix = 1
        while alias in used_names:
            alias = f"{base}_{suffix}"
            suffix += 1
        used_names.add(alias)
        expressions[variable] = alias
    additions = "".join(
        f"  {expressions[variable]}() = {target}\n"
        for variable, target in targets.items()
    )
    end_functions = re.search(r"(?im)^\s*end functions\s*$", bngl)
    if end_functions:
        bngl = bngl[: end_functions.start()] + additions + bngl[end_functions.start() :]
    else:
        end_model = re.search(r"(?im)^\s*end model\s*$", bngl)
        if not end_model:
            raise ValueError("generated BNGL has no end model marker")
        block = f"begin functions\n{additions}end functions\n\n"
        bngl = bngl[: end_model.start()] + block + bngl[end_model.start() :]
    return bngl, expressions


def _compare_case_to_reference(
    case: dict[str, Any],
    cpp_model: Any,
    bngl: str,
    parsed: Any,
    atomized: Any,
    reference: dict[str, Any],
    cpp: Any,
) -> dict[str, Any]:
    """Run BNG3 on the official grid and compare to the suite reference."""

    if cpp_model.actions:
        return {
            "status": "unsupported",
            "reason": (
                "generated BNGL contains scheduled actions; the in-memory CVODE "
                "reference runner cannot execute actions on the official output grid"
            ),
        }
    from bionetgen.atomizer.modern.types import standardize_name

    targets = {}
    unresolved = []
    for variable in reference["variables"]:
        target = _reference_output_target(
            variable,
            reference,
            parsed,
            dict(atomized.observable_map),
            standardize_name,
        )
        if target is None:
            unresolved.append(variable)
        else:
            targets[variable] = target
    if unresolved:
        return {
            "status": "unsupported",
            "reason": "no exact BNG3 result mapping for: " + ", ".join(unresolved),
        }

    try:
        reference_bngl, output_aliases = _with_reference_output_functions(
            bngl, targets, str(case["id"])
        )
        output_model = cpp.parse_string(reference_bngl)
        available = (
            {item.name for item in output_model.observables}
            | {item.name for item in output_model.functions}
            | {item.name for item in output_model.parameters}
        )
        target_symbols = {
            symbol
            for target in targets.values()
            if target != "time"
            for symbol in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", target)
            if symbol != "time"
        }
        missing_targets = sorted(target_symbols - available)
        if missing_targets:
            return {
                "status": "unsupported",
                "reason": "generated model does not expose exact result symbols: "
                + ", ".join(missing_targets),
            }
        from bionetgen import BioNetGenModel

        result = BioNetGenModel(output_model).simulate(
            method="ode",
            t_start=reference["start"],
            t_end=reference["start"] + reference["duration"],
            n_steps=0,
            sample_times=reference["times"].tolist(),
            rtol=1e-9,
            atol=1e-14,
        )
        if not np.array_equal(np.asarray(result.time, dtype=float), reference["times"]):
            return {
                "status": "failed",
                "reason": "BNG3 result time grid differs from official reference grid",
            }
        actual = {
            variable: result.functions.get(alias)
            for variable, alias in output_aliases.items()
        }
        comparison = _compare_reference_series(
            reference["expected"],
            actual,
            absolute=reference["absolute"],
            relative=reference["relative"],
            sample_times=reference["times"],
        )
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        status = (
            "unsupported" if _classify_error(message) == "unsupported" else "failed"
        )
        return {"status": status, "reason": message}

    return {
        "status": "passed" if comparison["passed"] else "failed",
        "reason": (
            ""
            if comparison["passed"]
            else _official_comparison_failure_reason(comparison)
        ),
        "method": "BNG3 native CVODE",
        "solver_rtol": 1e-9,
        "solver_atol": 1e-14,
        "start": reference["start"],
        "duration": reference["duration"],
        "steps": reference["steps"],
        "settings_sha256": reference["settings_sha256"],
        "results_sha256": reference["results_sha256"],
        "output_targets": targets,
        "output_aliases": output_aliases,
        "comparison": comparison,
    }


def _warnings(model: Any) -> list[dict[str, Any]]:
    return [
        {
            "category": warning.category,
            "message": warning.message,
            "severity": warning.severity,
        }
        for warning in model.import_warnings
    ]


def _merge_generated_warnings(
    source_warnings: list[dict[str, Any]], generated_warnings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge writer diagnostics, replacing parser-only event summaries."""

    if any(warning.get("category") == "event" for warning in generated_warnings):
        source_warnings = [
            warning for warning in source_warnings if warning.get("category") != "event"
        ]
    for warning in generated_warnings:
        if warning not in source_warnings:
            source_warnings.append(warning)
    return source_warnings


def _unsupported_causes(reason: str) -> list[str]:
    """Normalize an unsupported reason into auditable semantic cause labels."""

    lower = str(reason or "").lower()
    causes: list[str] = []
    for package in (
        "comp",
        "fbc",
        "qual",
        "spatial",
        "arrays",
        "distrib",
        "dyn",
        "multi",
    ):
        if f'"{package}" package' in lower or f"package:{package}" in lower:
            causes.append(f"package:{package}")
    if "event" in lower:
        causes.append("events")
    if "algebraic rule" in lower:
        causes.append("algebraic_rules")
    if "assignment rule targets species" in lower or "speciesassignmentrule" in lower:
        causes.append("species_assignment_rules")
    if "stoichiometr" in lower:
        causes.append("stoichiometry")
    if "fast-equilibrium" in lower or "marked fast" in lower:
        causes.append("fast_reactions")
    if "conversionfactor" in lower or "conversion factor" in lower:
        causes.append("conversion_factors")
    if "reaction-local" in lower or "no bngl-wide scope" in lower:
        causes.append("local_scope")
    if any(
        marker in lower
        for marker in (
            "mathml",
            "treated as rational",
            "gcd(",
            "lcm(",
            "rateof",
            "delay",
        )
    ):
        causes.append("mathml")
    if "constraint" in lower:
        causes.append("constraints")
    if "negative numeric rate" in lower or "nonnegative reaction rate" in lower:
        causes.append("negative_rates")
    if "no species" in lower or "no species or rate-rule" in lower:
        causes.append("no_state_variables")
    if "no reactants or products" in lower:
        causes.append("reaction_participants")
    if not causes:
        causes.append("other")
    return list(dict.fromkeys(causes))


def _record_ref(record: dict[str, Any]) -> str:
    category = str(record.get("category", "")).strip()
    identifier = str(record.get("id", "")).strip()
    return f"{category}/{identifier}" if category else identifier


def _official_comparison_failure_reason(comparison: dict[str, Any]) -> str:
    """Turn numeric mismatch metrics into a concise, reproducible case reason."""

    failed_variables = comparison.get("failed_variables", [])
    details = []
    for variable in failed_variables[:8]:
        metrics = comparison.get("variables", {}).get(variable, {})
        variable_reason = metrics.get("reason")
        if variable_reason:
            details.append(f"{variable}: {variable_reason}")
            continue
        detail = (
            f"{variable}: {metrics.get('failed_points', 0)}/"
            f"{metrics.get('sample_count', 0)} samples failed"
        )
        max_abs = metrics.get("max_abs_difference")
        max_scaled = metrics.get("max_scaled_error")
        if max_abs is not None:
            detail += f", max abs diff {float(max_abs):.6g}"
        if max_scaled is not None:
            detail += f", max scaled error {float(max_scaled):.6g}"
        indices = metrics.get("failed_sample_indices", [])
        if indices:
            detail += f", sample indices {indices[:8]}"
            if metrics.get("failed_sample_indices_truncated"):
                detail += "..."
        details.append(detail)
    if len(failed_variables) > 8:
        details.append(f"{len(failed_variables) - 8} more variables failed")
    summary = (
        f"reference mismatch: {comparison.get('failed_points', 0)}/"
        f"{comparison.get('sample_count', 0)} output points failed"
    )
    return summary + ("; " + "; ".join(details) if details else "")


def _official_conformance_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize official-reference outcomes independently of the legacy gate."""

    groups: dict[tuple[str, str], list[str]] = {}
    non_passed = []
    for record in records:
        result = record.get("official_conformance", {})
        status = str(result.get("status", "missing"))
        reason = str(result.get("reason", ""))
        if status == "failed" and not reason and result.get("comparison"):
            reason = _official_comparison_failure_reason(result["comparison"])
        if status != "passed":
            non_passed.append(
                {"case": _record_ref(record), "status": status, "reason": reason}
            )
            groups.setdefault((status, reason), []).append(_record_ref(record))
    return {
        "non_passed_count": len(non_passed),
        "non_passed_records": non_passed,
        "by_status_and_reason": [
            {
                "status": status,
                "reason": reason,
                "count": len(cases),
                "cases": cases,
            }
            for (status, reason), cases in sorted(groups.items())
        ],
    }


def _stoichiometry_subcauses(reason: str) -> list[str]:
    """Split the broad stoichiometry boundary into semantic subcauses."""

    lower = str(reason or "").lower()
    subcauses: list[str] = []
    if "variable stoichiometry" in lower or "stoichiometrymath" in lower:
        subcauses.append("dynamic_or_stoichiometryMath")
    raw_values = re.findall(
        r"unsupported stoichiometry\s+(-?(?:\d+(?:\.\d*)?|\.\d+))", lower
    )
    if any(raw.startswith("-") for raw in raw_values):
        subcauses.append("constant_negative")
    if any(
        not raw.startswith("-") and abs(float(raw) - round(float(raw))) > 1e-12
        for raw in raw_values
    ):
        subcauses.append("constant_noninteger")
    if any(
        not raw.startswith("-") and abs(float(raw) - round(float(raw))) <= 1e-12
        for raw in raw_values
    ) and any(float(raw) > 100 for raw in raw_values):
        subcauses.append("constant_integer_above_expansion_limit")
    if "non-integer reaction stoichiometry" in lower:
        subcauses.append("constant_noninteger")
    if "above the bngl expansion limit" in lower:
        subcauses.append("constant_integer_above_expansion_limit")
    if "stoichiometr" in lower and not subcauses:
        subcauses.append("unclassified_stoichiometry")
    return list(dict.fromkeys(subcauses))


# Subcause taxonomy for the ``events`` cause.  Each marker is a distinctive
# fragment of one refusal reason the BNGL event lowering emits from
# python/bionetgen/atomizer/modern/events.py; the reasons are chosen so that no
# real reason string matches more than one marker, and every reason matches one.
_EVENT_REFUSAL_SUBCAUSES: tuple[tuple[str, str], ...] = (
    (
        "state_trigger_not_schedulable",
        "state-triggered sbml events require stochastic jump scheduling",
    ),
    (
        "state_trigger_not_schedulable",
        "trigger is not a simple time threshold",
    ),
    ("trigger_time_not_constant", "does not reduce to a constant"),
    (
        "trigger_outside_time_gate",
        "state threshold crosses outside its fixed time gate",
    ),
    (
        "trigger_reentry_within_horizon",
        "volume change can cause the state trigger to re-enter",
    ),
    ("exponential_self_reset", "exponential self-reset"),
    (
        "delayed_assignment_retrigger_edge",
        "delayed interval assignment can create another rising trigger edge",
    ),
    ("delay_not_constant", 'delay "'),
    ("time_scale_not_positive_constant", "is not a positive constant"),
    (
        "nonpersistent_cancellation_at_window_end",
        "nonpersistent delayed event may be canceled at the window end",
    ),
    (
        "simultaneous_cancellation_unresolved",
        "simultaneous nonpersistent event cancellation could not be resolved",
    ),
    (
        "simultaneous_dynamic_priority_unordered",
        "simultaneous dynamic-priority event group could not be ordered soundly",
    ),
    ("time_window_empty", "time-window bounds do not form a nonempty interval"),
    (
        "time_window_starts_at_or_before_zero",
        "time windows beginning at or before t=0 are not lowered",
    ),
    (
        "assignment_target_unknown",
        "is neither a known species nor a parameter",
    ),
    ("priority_not_constant", "is not compile-time constant"),
    (
        "assignment_not_constant",
        '" is not constant (depends on species/time',
    ),
    (
        "trigger_state_not_finite",
        "event state at execution time is not finite",
    ),
)


def _event_unsupported_subcauses(reason: str) -> list[str]:
    """Split an event refusal into the semantic boundary that refused it.

    ``scripts/ci/validate_sbml_test_suite.py`` carries the lowering's own
    refusal text into ``unsupported_reason``, so the precise boundary is already
    in the record; this only names it.  An event refusal whose reason text is
    not recognised is reported as ``unclassified_events`` rather than being
    silently absorbed into the coarse ``events`` cause.
    """

    lower = str(reason or "").lower()
    subcauses = [
        subcause for subcause, marker in _EVENT_REFUSAL_SUBCAUSES if marker in lower
    ]
    if not subcauses and "event" in lower:
        subcauses.append("unclassified_events")
    return list(dict.fromkeys(subcauses))


def _unsupported_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach cause labels and return counts, intersections, and exact IDs."""

    by_cause: dict[str, list[str]] = {}
    by_cause_records: dict[str, list[str]] = {}
    by_intersection: dict[tuple[str, ...], list[str]] = {}
    cardinality: dict[str, int] = {}
    stoichiometry_subcauses: dict[str, list[str]] = {}
    event_subcauses: dict[str, list[str]] = {}
    unsupported = []
    for record in records:
        if record.get("status") != "unsupported":
            continue
        reason = str(record.get("unsupported_reason") or record.get("error", ""))
        if reason and not record.get("unsupported_reason"):
            record["unsupported_reason"] = reason
        causes = _unsupported_causes(reason)
        record["unsupported_causes"] = causes
        reference = _record_ref(record)
        unsupported.append(record)
        record_subcauses: dict[str, list[str]] = {}
        if "stoichiometry" in causes:
            subcauses = _stoichiometry_subcauses(reason)
            record_subcauses["stoichiometry"] = subcauses
            for subcause in subcauses:
                stoichiometry_subcauses.setdefault(subcause, []).append(reference)
        if "events" in causes:
            event_labels = _event_unsupported_subcauses(reason)
            record_subcauses["events"] = event_labels
            for subcause in event_labels:
                event_subcauses.setdefault(subcause, []).append(reference)
        record["unsupported_subcauses"] = record_subcauses
        unique_causes = tuple(sorted(set(causes)))
        cardinality[str(len(unique_causes))] = (
            cardinality.get(str(len(unique_causes)), 0) + 1
        )
        by_intersection.setdefault(unique_causes, []).append(reference)
        for cause in causes:
            by_cause.setdefault(cause, []).append(str(record.get("id", "")))
            by_cause_records.setdefault(cause, []).append(reference)
    return {
        "record_count": len(unsupported),
        "by_cause": {
            cause: {
                "count": len(ids),
                "ids": ids,
                "records": by_cause_records[cause],
            }
            for cause, ids in sorted(by_cause.items())
        },
        "stoichiometry_subsummary": {
            "record_count": sum(
                "stoichiometry" in record.get("unsupported_causes", [])
                for record in unsupported
            ),
            "by_subcause": {
                subcause: {
                    "count": len(references),
                    "records": references,
                }
                for subcause, references in sorted(stoichiometry_subcauses.items())
            },
        },
        "events_subsummary": {
            "record_count": sum(
                "events" in record.get("unsupported_causes", [])
                for record in unsupported
            ),
            "by_subcause": {
                subcause: {
                    "count": len(references),
                    "records": references,
                }
                for subcause, references in sorted(event_subcauses.items())
            },
        },
        "intersection_summary": {
            "record_count": len(unsupported),
            "cause_cardinality": dict(
                sorted(cardinality.items(), key=lambda item: int(item[0]))
            ),
            "by_cause_set": {
                " + ".join(cause_set) if cause_set else "none": {
                    "count": len(references),
                    "records": references,
                }
                for cause_set, references in sorted(
                    by_intersection.items(), key=lambda item: (len(item[0]), item[0])
                )
            },
            "pairwise": {
                " + ".join(pair): {
                    "count": sum(
                        set(pair).issubset(set(record.get("unsupported_causes", [])))
                        for record in unsupported
                    ),
                    "records": [
                        _record_ref(record)
                        for record in unsupported
                        if set(pair).issubset(set(record.get("unsupported_causes", [])))
                    ],
                }
                for pair in sorted(
                    {
                        pair
                        for record in unsupported
                        for pair in itertools.combinations(
                            sorted(set(record.get("unsupported_causes", []))), 2
                        )
                    }
                )
            },
        },
    }


def _atomizer_actions_for_category(
    category: str, simulation_t_end: float, simulation_n_steps: int
) -> str:
    """Use jump-based trigger semantics for stochastic suite cases."""
    if category != "stochastic":
        return ""
    end = format(float(simulation_t_end), ".15g")
    return (
        'simulate({method=>"ssa", t_start=>0, '
        f"t_end=>{end}, n_steps=>{int(simulation_n_steps)}}})"
    )


def _atomizer_horizon(
    category: str,
    reference: dict[str, Any] | None,
    *,
    simulation_t_end: float,
    simulation_n_steps: int,
) -> tuple[float, int]:
    """Use the official semantic interval when classifying event behavior."""

    if category == "semantic" and reference is not None:
        return reference["start"] + reference["duration"], reference["steps"]
    return simulation_t_end, simulation_n_steps


def _validate_case(
    case: dict[str, Any],
    cpp: Any,
    work_dir: Path,
    simulation_t_end: float,
    simulation_n_steps: int,
    simulation_rtol: float,
    simulation_atol: float,
) -> dict[str, Any]:
    from bionetgen.atomizer.modern import (
        Atomizer,
        SBMLParser,
        source_metadata_payload,
        source_metadata_summary,
    )
    from bionetgen.atomizer.modern.types import standardize_name

    source_path = Path(case["path"])
    record: dict[str, Any] = {
        "category": case["category"],
        "id": case["id"],
        "version": case["version"],
        "source": str(source_path),
    }
    case_dir = source_path.parent
    reference_settings = case_dir / f"{case['id']}-settings.txt"
    reference_results = case_dir / f"{case['id']}-results.csv"
    record["input_sha256"] = {
        "sbml": _sha256_file(source_path) if source_path.is_file() else None,
        "settings": (
            _sha256_file(reference_settings) if reference_settings.is_file() else None
        ),
        "results": (
            _sha256_file(reference_results) if reference_results.is_file() else None
        ),
    }
    reference = None
    if case["category"] == "stochastic":
        record["official_conformance"] = {
            "status": "unsupported",
            "reason": (
                "official stochastic conformance requires repeated-run mean and "
                "standard-deviation evaluation; one ODE or SSA trajectory is not conformance"
            ),
        }
    else:
        try:
            reference = _read_reference_case(case)
            record["official_conformance"] = {"status": "pending"}
        except OfficialReferenceUnsupported as exc:
            record["official_conformance"] = {
                "status": "unsupported",
                "reason": str(exc),
            }
        except Exception as exc:
            record["official_conformance"] = {
                "status": "invalid-source",
                "reason": f"{type(exc).__name__}: {exc}",
            }
    source_xml_valid = False
    try:
        sbml = source_path.read_text(encoding="utf-8-sig")
        record["source_xml"] = _validate_xml(sbml, "source SBML")
        source_xml_valid = True
        parsed = SBMLParser().parse(sbml, source_path=source_path)
        record["source_model"] = {
            "species": len(parsed.species),
            "reactions": len(parsed.reactions),
            "warnings": _warnings(parsed),
            "metadata": source_metadata_summary(parsed),
        }
        source_metadata = source_metadata_payload(parsed)
        atomizer_t_end, atomizer_n_steps = _atomizer_horizon(
            case["category"],
            reference,
            simulation_t_end=simulation_t_end,
            simulation_n_steps=simulation_n_steps,
        )
        atomizer = Atomizer(
            atomize=False,
            quiet_mode=True,
            actions=_atomizer_actions_for_category(
                case["category"], atomizer_t_end, atomizer_n_steps
            ),
            t_end=atomizer_t_end,
            n_steps=atomizer_n_steps,
        )
        atomized = atomizer.atomize(sbml, source_path=source_path)
        if not atomized.success:
            raise RuntimeError(atomized.error or "modern Atomizer returned failure")
        source_warnings = record["source_model"]["warnings"]
        source_warnings = _merge_generated_warnings(
            source_warnings, _warnings(atomizer.model)
        )
        record["source_model"]["warnings"] = source_warnings
        source_limitations = [
            *_simulation_limitations(source_warnings),
            *_warning_limitations(source_warnings),
            *_event_translation_limitations(atomized.bngl),
        ]
        if source_limitations:
            record["status"] = "unsupported"
            record["unsupported_reason"] = " ".join(source_limitations)
            if record["official_conformance"]["status"] == "pending":
                record["official_conformance"] = {
                    "status": "unsupported",
                    "reason": record["unsupported_reason"],
                }
            record["simulation_comparison"] = {
                "passed": False,
                "skipped": True,
                "reason": record["unsupported_reason"],
                "method_bngl": "BNG3 CVODE",
                "method_sbml": "libRoadRunner CVODE",
            }
            record["core_passed"] = False
            return record
        cpp_model = cpp.parse_string(atomized.bngl)
        network = cpp.generate_network(cpp_model, max_iter=100)
        record["generated_network"] = {
            "species": network.num_species,
            "reactions": network.num_reactions,
        }
        if record["official_conformance"]["status"] == "pending":
            record["official_conformance"] = _compare_case_to_reference(
                case, cpp_model, atomized.bngl, parsed, atomized, reference, cpp
            )

        output_path = work_dir / f"{case['category']}_{case['id']}.xml"
        cpp.io.write_sbml(
            cpp_model,
            network,
            str(output_path),
            source_metadata=source_metadata,
        )
        output_text = output_path.read_text(encoding="utf-8")
        record["written_xml"] = _validate_xml(output_text, "written SBML")
        reimport_model = SBMLParser().parse(output_text)
        record["reimport_model"] = {
            "species": len(reimport_model.species),
            "reactions": len(reimport_model.reactions),
            "warnings": _warnings(reimport_model),
            "metadata": source_metadata_summary(reimport_model),
        }
        record["metadata_roundtrip"] = {
            "source": record["source_model"].get("metadata", {}),
            "reimport": record["reimport_model"].get("metadata", {}),
            "status": (
                "not_present"
                if not source_metadata
                else (
                    "preserved"
                    if reimport_model.source_metadata_payload == source_metadata
                    else "dropped"
                )
            ),
            "payloadPresent": bool(reimport_model.source_metadata_payload),
            "payloadMatch": bool(
                source_metadata
                and reimport_model.source_metadata_payload == source_metadata
            ),
        }
        reimport = Atomizer(
            atomize=False,
            quiet_mode=True,
            t_end=simulation_t_end,
            n_steps=simulation_n_steps,
        ).atomize(output_text)
        if not reimport.success:
            raise RuntimeError(reimport.error or "round-trip Atomizer returned failure")
        reimport_network = cpp.generate_network(
            cpp.parse_string(reimport.bngl), max_iter=100
        )
        record["reimport_network"] = {
            "species": reimport_network.num_species,
            "reactions": reimport_network.num_reactions,
        }
        native = dict(cpp.io.read_sbml(str(output_path), False))
        record["native_reader"] = native
        if not native.get("success"):
            raise RuntimeError(
                native.get("error") or "native SBML reader returned failure"
            )
        if native["species_count"] != network.num_species:
            raise RuntimeError(
                f"native species count {native['species_count']} != {network.num_species}"
            )
        if native["reaction_count"] != network.num_reactions:
            raise RuntimeError(
                f"native reaction count {native['reaction_count']} != {network.num_reactions}"
            )

        warnings = record["source_model"]["warnings"]
        limitations = [
            *_simulation_limitations(warnings),
            *_warning_limitations(warnings),
        ]
        if limitations:
            record["status"] = "unsupported"
            record["unsupported_reason"] = " ".join(limitations)
        else:
            record["status"] = "passed"
        comparison = _simulate_and_compare(
            cpp_model,
            output_path,
            t_end=simulation_t_end,
            n_steps=simulation_n_steps,
            rtol=simulation_rtol,
            atol=simulation_atol,
            function_names={
                standardize_name(str(rule.variable))
                for rule in parsed.rules
                if rule.type == "assignment" and rule.variable
            }
            | {
                standardize_name(str(assignment.symbol))
                for assignment in parsed.initial_assignments
                if assignment.symbol
            },
        )
        record["simulation_comparison"] = comparison
        if not comparison.get("passed", False):
            record["status"] = "failed"
            record["error"] = comparison.get("error", "numerical comparison failed")
        record["core_passed"] = record["status"] == "passed"
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        warning_limitations = _warning_limitations(
            record.get("source_model", {}).get("warnings", [])
        )
        record["status"] = _classify_error(
            message + " " + " ".join(warning_limitations)
        )
        record["core_passed"] = False
        record["error"] = message
        if record["official_conformance"]["status"] == "pending":
            if not source_xml_valid:
                official_status = "invalid-source"
            else:
                official_status = (
                    "unsupported"
                    if _classify_error(message + " " + " ".join(warning_limitations))
                    == "unsupported"
                    else "failed"
                )
            record["official_conformance"] = {
                "status": official_status,
                "reason": message,
            }
        if record["status"] == "unsupported" and warning_limitations:
            record["unsupported_reason"] = " ".join(warning_limitations)
    return record


def _run_isolated_case(
    case: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    """Run one suite case in a bounded child process."""

    worker_json = args.json.parent / (
        f".worker-sbml-{case['category']}-{case['id']}.json"
    )
    worker_json.unlink(missing_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--suite-dir",
        str(args.suite_dir.resolve()),
        "--lock",
        str(args.lock.resolve()),
        "--json",
        str(worker_json),
        "--categories",
        case["category"],
        "--only-case",
        f"{case['category']}/{case['id']}",
        "--worker",
        "--simulation-t-end",
        str(args.simulation_t_end),
        "--simulation-n-steps",
        str(args.simulation_n_steps),
        "--simulation-rtol",
        str(args.simulation_rtol),
        "--simulation-atol",
        str(args.simulation_atol),
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=args.case_timeout,
        )
        if not worker_json.exists():
            raise RuntimeError(
                f"worker exited {completed.returncode} without a report: "
                f"{completed.stderr[-500:]}"
            )
        return json.loads(worker_json.read_text(encoding="utf-8"))["records"][0]
    except subprocess.TimeoutExpired:
        return {
            "category": case["category"],
            "id": case["id"],
            "version": case["version"],
            "source": str(case["path"]),
            "status": "timeout",
            "core_passed": False,
            "error": f"per-case timeout after {args.case_timeout}s",
            "official_conformance": {
                "status": "timed-out",
                "reason": f"per-case timeout after {args.case_timeout}s",
            },
        }
    except Exception as exc:
        return {
            "category": case["category"],
            "id": case["id"],
            "version": case["version"],
            "source": str(case["path"]),
            "status": "failed",
            "core_passed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "official_conformance": {
                "status": "failed",
                "reason": f"{type(exc).__name__}: {exc}",
            },
        }
    finally:
        worker_json.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=DEFAULT_SUITE_LOCK)
    parser.add_argument("--json", type=Path)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="verify the clean suite checkout against the source lock and exit",
    )
    parser.add_argument("--categories", nargs="+", default=["semantic", "stochastic"])
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--only-case", help="validate one case as CATEGORY/ID")
    parser.add_argument(
        "--isolate-cases",
        action="store_true",
        help="run each case in a bounded child process",
    )
    parser.add_argument(
        "--case-timeout", type=int, default=60, help="per-case timeout in seconds"
    )
    parser.add_argument(
        "--jobs", type=int, default=8, help="parallel isolated case workers"
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--simulation-t-end", type=float, default=1.0)
    parser.add_argument("--simulation-n-steps", type=int, default=10)
    parser.add_argument("--simulation-rtol", type=float, default=1e-7)
    parser.add_argument("--simulation-atol", type=float, default=1e-12)
    args = parser.parse_args()

    try:
        suite_info = _validate_suite_checkout(args.suite_dir, args.lock)
    except SuiteLockError as exc:
        print(f"suite preflight failed: {exc}", file=sys.stderr)
        return 1
    if args.validate_only:
        print(
            json.dumps(
                {
                    "status": "passed",
                    "validate_only": True,
                    **suite_info,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.json is None:
        parser.error("--json is required unless --validate-only is set")

    cases = _case_files(args.suite_dir, args.categories)
    full_suite_cases = _case_files(args.suite_dir, ["semantic", "stochastic"])
    full_suite_inventory = {
        category: sum(case["category"] == category for case in full_suite_cases)
        for category in ("semantic", "stochastic")
    }
    full_suite_inventory["total"] = len(full_suite_cases)
    if args.only_case:
        try:
            only_category, only_id = args.only_case.split("/", 1)
        except ValueError as exc:
            raise SystemExit("--only-case must be CATEGORY/ID") from exc
        selected = [
            case
            for case in cases
            if case["category"] == only_category and case["id"] == only_id
        ]
        if not selected:
            raise SystemExit(f"case is not in the suite inventory: {args.only_case}")
    else:
        selected = cases[: args.max_cases] if args.max_cases else cases
    partial = _is_partial_run(args.categories, args.max_cases, args.only_case)
    try:
        import bionetgen._bionetgen_cpp as cpp
    except ImportError as exc:
        raise SystemExit(
            "BNG3 C++ extension is unavailable; set PYTHONPATH=python:build/cpp"
        ) from exc
    runtime_info = _runtime_provenance(cpp)

    records = []
    with tempfile.TemporaryDirectory(prefix="bng3-sbml-suite-") as temp:
        work_dir = Path(temp)
        if args.isolate_cases and not args.worker:
            if args.jobs < 1:
                raise SystemExit("--jobs must be at least one")
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
                records = list(
                    pool.map(lambda case: _run_isolated_case(case, args), selected)
                )
            for case, record in zip(selected, records):
                print(
                    f"{case['category']}/{case['id']}: {record['status'].upper()}",
                    flush=True,
                )
        else:
            for case in selected:
                record = _validate_case(
                    case,
                    cpp,
                    work_dir,
                    args.simulation_t_end,
                    args.simulation_n_steps,
                    args.simulation_rtol,
                    args.simulation_atol,
                )
                records.append(record)
                print(
                    f"{case['category']}/{case['id']}: {record['status'].upper()}",
                    flush=True,
                )

    unsupported_summary = _unsupported_summary(records)
    counts = {
        status: sum(record["status"] == status for record in records)
        for status in ("passed", "unsupported", "failed", "timeout")
    }
    by_category = {
        category: {
            status: sum(
                record["category"] == category and record["status"] == status
                for record in records
            )
            for status in ("passed", "unsupported", "failed", "timeout")
        }
        for category in args.categories
    }
    official_statuses = (
        "passed",
        "unsupported",
        "failed",
        "timed-out",
        "invalid-source",
        "pending",
        "missing",
    )
    official_counts = {
        status: sum(
            record.get("official_conformance", {}).get("status") == status
            for record in records
        )
        for status in official_statuses
    }
    official_by_category = {
        category: {
            status: sum(
                record["category"] == category
                and record.get("official_conformance", {}).get("status") == status
                for record in records
            )
            for status in official_statuses
        }
        for category in args.categories
    }
    official_summary = _official_conformance_summary(records)
    report = {
        "schema_version": 6,
        "suite_dir": str(args.suite_dir.resolve()),
        "suite_commit": suite_info["revision"],
        "suite_source_lock": suite_info,
        "command": {
            "executable": sys.executable,
            "arguments": [str(Path(__file__).resolve()), *sys.argv[1:]],
            "working_directory": str(Path.cwd()),
        },
        "source_provenance": _repository_provenance(
            Path(__file__).resolve().parents[2]
        ),
        "runtime_provenance": runtime_info,
        "writer_sbml_version": "L3V2",
        "categories": args.categories,
        "canonical_version_priority": list(VERSION_PRIORITY),
        "case_inventory": len(cases),
        "full_suite_inventory": full_suite_inventory,
        "selected_cases": len(selected),
        "partial_run": partial,
        "counts": counts,
        "by_category": by_category,
        "records": records,
        "official_conformance": {
            "reference": "official SBML Test Suite results CSV",
            "method": "BNG3 native CVODE on the official reference time grid",
            "comparison": "abs(expected-actual) <= absolute + relative*abs(expected)",
            "counts": official_counts,
            "by_category": official_by_category,
            "summary": official_summary,
            "passed": not partial and official_summary["non_passed_count"] == 0,
        },
        "unsupported_summary": unsupported_summary,
        "sbml_unsupported_summary": unsupported_summary,
        "roundtrip_gate": "SBML XML validation + modern Atomizer/C++ network generation + C++ SBML writer + modern reimport + native C++ reader count check + BNG3 CVODE/libRoadRunner all-observable comparison",
        "simulation": {
            "t_start": 0.0,
            "t_end": args.simulation_t_end,
            "n_steps": args.simulation_n_steps,
            "rtol": args.simulation_rtol,
            "atol": args.simulation_atol,
            "comparison": "all generated BNGL observables on the same time grid",
            "engines": ["BNG3 CVODE", "libRoadRunner CVODE"],
        },
        "numerical_conformance": (
            "official deterministic time-course reference conformance is reported "
            "separately from the BNG3/libRoadRunner round-trip comparison; stochastic "
            "ensemble statistics are unsupported in this runner"
        ),
        "core_passed": (
            not partial
            and counts["failed"] == 0
            and counts["unsupported"] == 0
            and counts["timeout"] == 0
        ),
        "supported_surface_passed": (
            not partial and counts["failed"] == 0 and counts["timeout"] == 0
        ),
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"cases={len(records)} passed={counts['passed']} "
        f"unsupported={counts['unsupported']} failed={counts['failed']} "
        f"timeouts={counts['timeout']} "
        f"official_passed={official_counts['passed']} "
        f"official_unsupported={official_counts['unsupported']} "
        f"official_failed={official_counts['failed']} "
        f"official_timeouts={official_counts['timed-out']} "
        f"core={'PASS' if report['core_passed'] else 'FAIL'}"
    )
    return 0 if report["core_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
