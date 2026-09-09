"""Resolve and checkout the exact external sources used by parity CI.

The provenance lock is JSON-compatible YAML, so this helper deliberately uses
only the standard library.  A parity job must name a full immutable revision;
floating branches and the embedded BNG3 NFsim target are not valid oracles.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = REPO / "provenance" / "upstreams.lock.yml"
ORACLE_NAMES = ("bionetgen", "nfsim", "pybionetgen")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^https://github\.com/[^/]+/[^/]+\.git$")


class OracleSourceError(ValueError):
    """Raised when the source lock cannot define a reproducible oracle."""


def load_lock(path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    """Load the JSON-compatible provenance lock and require a source table."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OracleSourceError(f"cannot read oracle lock {path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("sources"), dict):
        raise OracleSourceError(f"oracle lock {path} must contain a sources object")
    return document


def load_oracle_source(lock: dict[str, Any], name: str) -> dict[str, str]:
    """Return and validate one external source entry from a loaded lock."""

    if name not in ORACLE_NAMES:
        raise OracleSourceError(
            f"unknown oracle {name!r}; expected one of {', '.join(ORACLE_NAMES)}"
        )
    source = lock.get("sources", {}).get(name)
    if not isinstance(source, dict):
        raise OracleSourceError(f"sources.{name} is missing from the oracle lock")

    repository = source.get("repository")
    revision = source.get("revision")
    if not SHA_RE.fullmatch(str(revision)):
        raise OracleSourceError(
            f"sources.{name}.revision must be a full lowercase Git SHA"
        )
    if not REPOSITORY_RE.fullmatch(str(repository)):
        raise OracleSourceError(
            f"sources.{name}.repository must be a canonical GitHub .git URL"
        )
    return {"repository": str(repository), "revision": str(revision)}


def _run_git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def checkout_oracle(
    name: str,
    destination: Path,
    *,
    lock_path: Path = DEFAULT_LOCK,
) -> dict[str, str]:
    """Clone one locked source, detach at its revision, and verify its head."""

    source = load_oracle_source(load_lock(lock_path), name)
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise OracleSourceError(f"oracle destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    _run_git(
        "clone",
        "--no-tags",
        "--filter=blob:none",
        "--no-checkout",
        source["repository"],
        str(destination),
    )
    _run_git("-C", str(destination), "checkout", "--detach", source["revision"])
    actual = _run_git("-C", str(destination), "rev-parse", "HEAD")
    if actual != source["revision"]:
        raise OracleSourceError(
            f"oracle {name} checked out {actual}, expected {source['revision']}"
        )
    if _run_git("-C", str(destination), "status", "--porcelain"):
        raise OracleSourceError(f"oracle {name} checkout is dirty: {destination}")

    return {
        "name": name,
        "repository": source["repository"],
        "revision": source["revision"],
        "path": str(destination),
    }


def write_summary(path: Path, metadata: dict[str, str]) -> None:
    """Append a small provenance table to a GitHub step summary."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"### External oracle: {metadata['name']}",
        "",
        "| Repository | Locked revision | Checkout |",
        "| --- | --- | --- |",
        f"| `{metadata['repository']}` | `{metadata['revision']}` | `{metadata['path']}` |",
        "",
    ]
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", choices=ORACLE_NAMES)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--summary-file", type=Path)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the locked source entries without cloning them",
    )
    args = parser.parse_args()

    try:
        lock = load_lock(args.lock)
        names = (args.name,) if args.name else ORACLE_NAMES
        sources = {name: load_oracle_source(lock, name) for name in names}
        if args.validate_only:
            for name, source in sources.items():
                print(f"{name}: {source['repository']}@{source['revision']}")
            return 0
        if not args.name or args.destination is None:
            parser.error(
                "--name and --destination are required unless --validate-only is used"
            )
        metadata = checkout_oracle(args.name, args.destination, lock_path=args.lock)
    except (OracleSourceError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"{metadata['name']}: {metadata['repository']}@{metadata['revision']}")
    if args.summary_file:
        write_summary(args.summary_file, metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
