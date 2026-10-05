#!/usr/bin/env python3
"""Compare complete, valid identity_check.py output trees.

Both runs must have matching case coverage, a valid root manifest, a fresh
output directory, a nonempty .net file, and the complete numeric .gdat/.cdat
sampling grid configured by each case's fixed SSA action.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

try:
    from .identity_check import inspect_case_outputs
except (
    ImportError
):  # Support direct execution as ``python verify/compare_identity.py``.
    from identity_check import inspect_case_outputs


def _case_dirs(root: Path) -> set[str]:
    if not root.is_dir():
        raise ValueError(f"run directory does not exist: {root}")
    try:
        return {path.name for path in root.iterdir() if path.is_dir()}
    except OSError as exc:
        raise ValueError(f"cannot list run directory: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_valid_run(root: Path, actual_cases: set[str]) -> dict[str, dict[str, str]]:
    manifest_path = root / "identity_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read identity manifest: {exc}") from exc
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != 1
    ):
        raise ValueError("unsupported or malformed identity manifest")
    if manifest.get("valid") is not True:
        raise ValueError("identity manifest marks the run invalid")

    selected = manifest.get("selected_cases")
    if (
        not isinstance(selected, list)
        or not selected
        or any(not isinstance(name, str) or not name for name in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("identity manifest has an empty or malformed case set")
    selected_cases = set(selected)
    if selected_cases != actual_cases:
        raise ValueError("manifest cases do not match the output directories")

    records = manifest.get("cases")
    if not isinstance(records, dict) or set(records) != selected_cases:
        raise ValueError("identity manifest has incomplete per-case results")

    run_hashes = {}
    for name in sorted(selected_cases):
        record = records[name]
        if (
            not isinstance(record, dict)
            or record.get("valid") is not True
            or record.get("status") != "pass"
            or type(record.get("exit_code")) is not int
            or record.get("exit_code") != 0
            or record.get("error") is not None
            or record.get("fresh_output_directory") is not True
        ):
            raise ValueError(f"case {name} is incomplete or invalid")

        file_lists = {}
        for field in (
            "network_files",
            "trajectory_files",
            "usable_trajectory_files",
            "artifact_files",
        ):
            filenames = record.get(field)
            if (
                not isinstance(filenames, list)
                or any(
                    not isinstance(filename, str) or not filename
                    for filename in filenames
                )
                or len(set(filenames)) != len(filenames)
            ):
                raise ValueError(f"case {name} has an invalid {field} list")
            file_lists[field] = filenames
        if not file_lists["network_files"]:
            raise ValueError(f"case {name} has no required .net network file")
        if not file_lists["trajectory_files"]:
            raise ValueError(f"case {name} has no required trajectory file")
        if not file_lists["usable_trajectory_files"]:
            raise ValueError(f"case {name} has no usable numeric trajectory data")
        if not file_lists["artifact_files"]:
            raise ValueError(f"case {name} has no artifact file list")

        case_dir = root / name
        sums_path = case_dir / "SHA256SUMS"
        try:
            lines = sums_path.read_text().splitlines()
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"case {name} has no readable SHA256SUMS: {exc}") from exc
        hashes = {}
        for line in lines:
            if not line.strip():
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
                raise ValueError(f"case {name} has a malformed SHA256SUMS entry")
            digest, filename = parts[0], parts[1].strip()
            if not filename or Path(filename).name != filename or filename in hashes:
                raise ValueError(f"case {name} has an invalid artifact name")
            artifact = case_dir / filename
            try:
                current_digest = _sha256(artifact) if artifact.is_file() else None
            except OSError as exc:
                raise ValueError(
                    f"case {name} artifact is unreadable: {filename}: {exc}"
                ) from exc
            if current_digest != digest:
                raise ValueError(
                    f"case {name} artifact hash is missing or stale: {filename}"
                )
            hashes[filename] = digest

        if set(hashes) != set(file_lists["artifact_files"]):
            raise ValueError(f"case {name} artifact manifest is incomplete")
        output_audit = inspect_case_outputs(case_dir, name)
        issue = output_audit["issue"]
        if issue is not None:
            raise ValueError(f"case {name} has incomplete required outputs: {issue}")
        expected_sampling = output_audit["expected_sampling"]
        recorded_sampling = record.get("expected_sampling")
        if (
            not isinstance(recorded_sampling, dict)
            or set(recorded_sampling) != set(expected_sampling)
            or any(
                type(recorded_sampling[field]) is not type(expected)
                or recorded_sampling[field] != expected
                for field, expected in expected_sampling.items()
            )
        ):
            raise ValueError(
                f"case {name} sampling metadata does not match its configured SSA action"
            )
        required_names = {
            "network_files": {path.name for path in output_audit["network_files"]},
            "trajectory_files": {
                path.name for path in output_audit["trajectory_files"]
            },
            "usable_trajectory_files": {
                path.name for path in output_audit["usable_trajectory_files"]
            },
            "artifact_files": {path.name for path in output_audit["artifacts"]},
        }
        for field, expected_names in required_names.items():
            if set(file_lists[field]) != expected_names:
                raise ValueError(f"case {name} {field} does not match its artifacts")
        if set(hashes) != required_names["artifact_files"]:
            raise ValueError(f"case {name} has unhashed or unlisted output artifacts")
        run_hashes[name] = hashes
    return run_hashes


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: compare_identity.py <base_dir> <changed_dir>", file=sys.stderr)
        return 2

    base, changed = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        base_cases = _case_dirs(base)
        changed_cases = _case_dirs(changed)
    except ValueError as exc:
        print(f"INCOMPLETE: {exc}", file=sys.stderr)
        return 1
    if not base_cases or not changed_cases:
        print("INCOMPLETE: empty case set", file=sys.stderr)
        return 1
    if base_cases != changed_cases:
        print(
            "INCOMPLETE: coverage mismatch: "
            f"base-only={sorted(base_cases - changed_cases)}; "
            f"candidate-only={sorted(changed_cases - base_cases)}",
            file=sys.stderr,
        )
        return 1

    try:
        base_hashes = _load_valid_run(base, base_cases)
        changed_hashes = _load_valid_run(changed, changed_cases)
    except ValueError as exc:
        print(f"INVALID identity run: {exc}", file=sys.stderr)
        return 1

    identical = 0
    for name in sorted(base_cases):
        before, after = base_hashes[name], changed_hashes[name]
        if before == after:
            print(f"{name:<24} IDENTICAL     {len(before)} artifacts")
            identical += 1
        else:
            differences = sorted(set(before) ^ set(after)) + sorted(
                filename
                for filename in set(before) & set(after)
                if before[filename] != after[filename]
            )
            print(f"{name:<24} DIFFERS       {', '.join(differences)}")
    print(
        f"\n{identical}/{len(base_cases)} models byte-identical "
        "(.gdat/.cdat/.net SHA-256) between the two binaries"
    )
    return 0 if identical == len(base_cases) else 1


if __name__ == "__main__":
    sys.exit(main())
