#!/usr/bin/env python3
"""Validate one provenance-complete BNG3 golden-bundle manifest.

The manifest is deliberately JSON-compatible and the validator uses only the
Python standard library.  It verifies both the declared provenance links and
the bytes referenced by every model, selection manifest, and output entry.
Candidate bundles are useful while the source lock is pending; an approved
bundle must match an approved, fully locked source manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
METHODS = {"network", "ode", "ssa", "pla", "psa", "nf"}
STOCHASTIC_METHODS = {"ssa", "pla", "psa", "nf"}


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return value


def _relative_path(value: Any, repo_root: Path) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    candidate = (repo_root / value).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        return None
    return candidate


def _required(value: Any, fields: set[str], where: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{where} must be an object")
        return False
    for field in sorted(fields - value.keys()):
        errors.append(f"{where}.{field} is required")
    return True


def _digest_reference(
    value: Any, where: str, repo_root: Path, errors: list[str]
) -> Path | None:
    if not _required(value, {"path", "sha256"}, where, errors):
        return None
    path = _relative_path(value.get("path"), repo_root)
    if path is None:
        errors.append(f"{where}.path must name a repository-relative file")
    declared = value.get("sha256")
    if not DIGEST_RE.fullmatch(str(declared)):
        errors.append(f"{where}.sha256 must be a sha256 digest")
    elif path is not None and not path.is_file():
        errors.append(f"{where}.path does not exist")
    elif path is not None and digest(path) != declared:
        errors.append(f"{where}.sha256 does not match the file")
    return path


def _valid_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _valid_sha(value: Any) -> bool:
    return bool(SHA_RE.fullmatch(str(value)))


def _mapping(value: Any) -> dict[str, Any]:
    """Return a mapping or an empty mapping for malformed nested documents."""

    return value if isinstance(value, dict) else {}


def validate(document: dict[str, Any], *, repo_root: Path = REPO) -> list[str]:
    """Return all manifest errors; do not raise for malformed user data."""

    errors: list[str] = []
    repo_root = repo_root.resolve()
    if document.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not DIGEST_RE.fullmatch(str(document.get("bundle_id"))):
        errors.append("bundle_id must be a sha256 digest")
    if document.get("status") not in {"candidate", "approved"}:
        errors.append("status is invalid")
    if not _valid_datetime(document.get("generated_at")):
        errors.append("generated_at must be an ISO date-time")

    lock_ref = document.get("source_lock")
    lock_path = _digest_reference(lock_ref, "source_lock", repo_root, errors)
    lock: dict[str, Any] | None = None
    if lock_path is not None and lock_path.is_file():
        try:
            lock = load(lock_path)
        except ValueError as exc:
            errors.append(str(exc))

    models = document.get("models")
    model_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(models, list) or not models:
        errors.append("models must be a non-empty array")
        models = []
    for index, model in enumerate(models):
        where = f"models[{index}]"
        if not _required(model, {"id", "path", "sha256"}, where, errors):
            continue
        model_id = model.get("id")
        if not isinstance(model_id, str) or not model_id:
            errors.append(f"{where}.id must be non-empty")
        elif model_id in model_by_id:
            errors.append(f"{where}.id is duplicated")
        else:
            model_by_id[model_id] = model
        path = _relative_path(model.get("path"), repo_root)
        if path is None:
            errors.append(f"{where}.path must name a repository-relative file")
        elif not path.is_file():
            errors.append(f"{where}.path does not exist")
        declared = model.get("sha256")
        if not DIGEST_RE.fullmatch(str(declared)):
            errors.append(f"{where}.sha256 must be a sha256 digest")
        elif path is not None and path.is_file() and digest(path) != declared:
            errors.append(f"{where}.sha256 does not match the model")

    corpus = document.get("corpus")
    selection_path: Path | None = None
    selection: dict[str, Any] | None = None
    if _required(corpus, {"selection_manifest", "rulehub"}, "corpus", errors):
        selection_path = _digest_reference(
            corpus.get("selection_manifest"),
            "corpus.selection_manifest",
            repo_root,
            errors,
        )
        if selection_path is not None and selection_path.is_file():
            try:
                selection = load(selection_path)
            except ValueError as exc:
                errors.append(str(exc))
        rulehub = corpus.get("rulehub")
        if _required(rulehub, {"repository", "revision"}, "corpus.rulehub", errors):
            if not re.fullmatch(
                r"^https://github\.com/.+\.git$", str(rulehub.get("repository"))
            ):
                errors.append(
                    "corpus.rulehub.repository must be a canonical GitHub .git URL"
                )
            if not _valid_sha(rulehub.get("revision")):
                errors.append(
                    "corpus.rulehub.revision must be a full lowercase Git SHA"
                )
            if selection is not None:
                selected_rulehub = _mapping(selection.get("rulehub", {}))
                if rulehub.get("repository") != selected_rulehub.get("repository"):
                    errors.append(
                        "corpus.rulehub.repository disagrees with selection manifest"
                    )
                if rulehub.get("revision") != selected_rulehub.get("revision"):
                    errors.append(
                        "corpus.rulehub.revision disagrees with selection manifest"
                    )
            if lock is not None:
                locked_rulehub = _mapping(lock.get("sources", {})).get("rulehub", {})
                locked_rulehub = _mapping(locked_rulehub)
                if rulehub.get("repository") != locked_rulehub.get("repository"):
                    errors.append(
                        "corpus.rulehub.repository disagrees with source lock"
                    )
                if rulehub.get("revision") != locked_rulehub.get("revision"):
                    errors.append("corpus.rulehub.revision disagrees with source lock")

    if selection is not None:
        selection_records = (
            {
                record.get("id"): record
                for record in selection.get("records", [])
                if isinstance(record, dict) and isinstance(record.get("id"), str)
            }
            if isinstance(selection.get("records", []), list)
            else {}
        )
        for model_id, model in model_by_id.items():
            record = selection_records.get(model_id)
            if record is None:
                errors.append(f"models[{model_id!r}] is not in the selection manifest")
                continue
            if model.get("path") != record.get("path"):
                errors.append(
                    f"models[{model_id!r}].path disagrees with selection manifest"
                )
            if model.get("sha256") != record.get("sha256"):
                errors.append(
                    f"models[{model_id!r}].sha256 disagrees with selection manifest"
                )

    oracle = document.get("oracle")
    if _required(
        oracle,
        {
            "name",
            "source",
            "repository",
            "revision",
            "build_recipe",
            "artifact_digest",
        },
        "oracle",
        errors,
    ):
        if oracle.get("name") not in {"bng2", "nfsim"}:
            errors.append("oracle.name is invalid")
        if oracle.get("source") not in {"bionetgen", "nfsim"}:
            errors.append("oracle.source is invalid")
        if oracle.get("name") == "bng2" and oracle.get("source") != "bionetgen":
            errors.append("oracle.bng2 must use source=bionetgen")
        if oracle.get("name") == "nfsim" and oracle.get("source") != "nfsim":
            errors.append("oracle.nfsim must use source=nfsim")
        if not re.fullmatch(
            r"^https://github\.com/.+\.git$", str(oracle.get("repository"))
        ):
            errors.append("oracle.repository must be a canonical GitHub .git URL")
        if not _valid_sha(oracle.get("revision")):
            errors.append("oracle.revision must be a full lowercase Git SHA")
        if not isinstance(oracle.get("build_recipe"), str) or not oracle.get(
            "build_recipe"
        ):
            errors.append("oracle.build_recipe must be non-empty")
        if not DIGEST_RE.fullmatch(str(oracle.get("artifact_digest"))):
            errors.append("oracle.artifact_digest must be a sha256 digest")
        if lock is not None:
            source = _mapping(lock.get("sources", {})).get(oracle.get("source"), {})
            source = _mapping(source)
            if oracle.get("repository") != source.get("repository"):
                errors.append("oracle.repository disagrees with source lock")
            if oracle.get("revision") != source.get("revision"):
                errors.append("oracle.revision disagrees with source lock")
            locked_oracle = _mapping(lock.get("oracles", {})).get(
                oracle.get("name"), {}
            )
            locked_oracle = _mapping(locked_oracle)
            if locked_oracle.get("source") != oracle.get("source"):
                errors.append("oracle.source disagrees with source lock oracle")
            if document.get("status") == "approved":
                if locked_oracle.get("status") != "locked":
                    errors.append("approved bundle requires a locked oracle")
                if oracle.get("artifact_digest") != locked_oracle.get(
                    "artifact_digest"
                ):
                    errors.append("approved oracle artifact does not match source lock")

    build = document.get("build")
    if _required(
        build,
        {
            "compiler",
            "compiler_version",
            "flags",
            "dependencies",
            "platform",
            "container_image",
        },
        "build",
        errors,
    ):
        if not isinstance(build.get("flags"), list) or any(
            not isinstance(item, str) for item in build.get("flags", [])
        ):
            errors.append("build.flags must be an array of strings")
        if not isinstance(build.get("dependencies"), list) or any(
            not isinstance(item, str) for item in build.get("dependencies", [])
        ):
            errors.append("build.dependencies must be an array of strings")
        if not IMAGE_RE.search(str(build.get("container_image"))):
            errors.append("build.container_image must use an immutable @sha256 digest")

    execution = document.get("execution")
    if _required(
        execution,
        {
            "command",
            "method",
            "seeds",
            "time_grid",
            "tolerances",
            "comparator_version",
        },
        "execution",
        errors,
    ):
        method = execution.get("method")
        if method not in METHODS:
            errors.append("execution.method is invalid")
        command = execution.get("command")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(item, str) or not item for item in command)
        ):
            errors.append("execution.command must be a non-empty array of strings")
        seeds = execution.get("seeds")
        seed_values_valid = isinstance(seeds, list) and all(
            isinstance(seed, int) and not isinstance(seed, bool) and seed >= 0
            for seed in seeds
        )
        if not seed_values_valid or len(set(seeds)) != len(seeds):
            errors.append(
                "execution.seeds must be a unique array of non-negative integers"
            )
        elif method in STOCHASTIC_METHODS and not seeds:
            errors.append("stochastic execution requires at least one seed")
        time_grid = execution.get("time_grid")
        if (
            not isinstance(time_grid, list)
            or not time_grid
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                for value in time_grid
            )
        ):
            errors.append("execution.time_grid must contain finite numbers")
        elif any(left >= right for left, right in zip(time_grid, time_grid[1:])):
            errors.append("execution.time_grid must be strictly increasing")
        tolerances = execution.get("tolerances")
        if _required(
            tolerances,
            {"absolute", "relative"},
            "execution.tolerances",
            errors,
        ):
            for name in ("absolute", "relative"):
                value = tolerances.get(name)
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    errors.append(
                        f"execution.tolerances.{name} must be a finite non-negative number"
                    )

    outputs = document.get("outputs")
    output_paths: set[str] = set()
    output_models: dict[str, int] = {}
    if not isinstance(outputs, list) or not outputs:
        errors.append("outputs must be a non-empty array")
        outputs = []
    for index, output in enumerate(outputs):
        where = f"outputs[{index}]"
        if not _required(output, {"path", "model_id", "kind", "sha256"}, where, errors):
            continue
        path_value = output.get("path")
        path = _relative_path(path_value, repo_root)
        if path is None:
            errors.append(f"{where}.path must name a repository-relative file")
        elif not path.is_file():
            errors.append(f"{where}.path does not exist")
        if isinstance(path_value, str):
            if path_value in output_paths:
                errors.append(f"{where}.path is duplicated")
            output_paths.add(path_value)
        declared = output.get("sha256")
        if not DIGEST_RE.fullmatch(str(declared)):
            errors.append(f"{where}.sha256 must be a sha256 digest")
        elif path is not None and path.is_file() and digest(path) != declared:
            errors.append(f"{where}.sha256 does not match the output")
        model_id = output.get("model_id")
        if not isinstance(model_id, str) or model_id not in model_by_id:
            errors.append(f"{where}.model_id references an unknown model")
        else:
            output_models[model_id] = output_models.get(model_id, 0) + 1
    for model_id in model_by_id:
        if not output_models.get(model_id):
            errors.append(f"model {model_id!r} has no output")

    if document.get("status") == "approved" and lock is not None:
        baseline = _mapping(lock.get("baseline", {}))
        if baseline.get("status") != "approved":
            errors.append("approved bundle requires an approved source-lock baseline")
        dependencies = _mapping(lock.get("dependencies", {}))
        compiler_images = _mapping(dependencies.get("compiler_images", {}))
        if compiler_images.get("status") != "locked":
            errors.append("approved bundle requires locked compiler images")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO,
        help="root used to resolve repository-relative files (default: this repository)",
    )
    args = parser.parse_args()
    try:
        document = load(args.manifest)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    errors = validate(document, repo_root=args.repo_root)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(
            f"golden manifest validation failed ({len(errors)} error(s))",
            file=sys.stderr,
        )
        return 1
    print(
        "golden manifest validation passed: "
        f"{document['bundle_id']} ({len(document['models'])} model(s), "
        f"{len(document['outputs'])} output(s))"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
