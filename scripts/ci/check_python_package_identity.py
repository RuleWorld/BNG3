"""Fail closed and report the installed BNG3 package and native extension."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

if __package__:
    from .python_package_mode import editable_finders_for_package
else:
    from python_package_mode import editable_finders_for_package


def inspect_installed_package(source_revision: str | None = None) -> dict[str, str]:
    """Verify package and extension come from one installed distribution."""

    editable_finders = editable_finders_for_package(sys.meta_path, "bionetgen")
    if editable_finders:
        raise RuntimeError(
            "installed-package identity check found a BNG3 editable import finder"
        )

    try:
        import packaging
    except ImportError as exc:
        raise RuntimeError(
            "the declared packaging runtime dependency is not importable"
        ) from exc

    try:
        distribution = importlib.metadata.distribution("bionetgen")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("bionetgen distribution is not installed") from exc

    import bionetgen
    import bionetgen._bionetgen_cpp as native
    import bionetgen.model as model

    distribution_package = Path(distribution.locate_file("bionetgen")).resolve()
    package_file = Path(bionetgen.__file__).resolve()
    extension_file = Path(native.__file__).resolve()
    model_file = Path(model.__file__).resolve()
    model_native = getattr(model, "_cpp", None)
    if model_native is None:
        raise RuntimeError("bionetgen.model did not bind a native extension")
    model_native_file = Path(model_native.__file__).resolve()
    if package_file.parent != distribution_package:
        raise RuntimeError(
            "bionetgen package was shadowed: "
            f"{package_file} (distribution package is {distribution_package})"
        )
    if extension_file.parent != distribution_package:
        raise RuntimeError(
            "bionetgen native extension was shadowed: "
            f"{extension_file} (expected under {distribution_package})"
        )
    if model_file.parent != distribution_package:
        raise RuntimeError(
            "bionetgen.model was shadowed: "
            f"{model_file} (expected under {distribution_package})"
        )
    if model_native_file != extension_file:
        raise RuntimeError(
            "bionetgen.model loaded a different native extension: "
            f"{model_native_file} (expected {extension_file})"
        )

    if source_revision is None:
        source_revision = os.environ.get("BNG3_SOURCE_REVISION", "")
    git_head = "unavailable"
    try:
        git_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except OSError, subprocess.CalledProcessError:
        pass

    digest = hashlib.sha256()
    with extension_file.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "python_executable": sys.executable,
        "python_prefix": sys.prefix,
        "source_revision": source_revision or git_head,
        "git_head": git_head,
        "pr_head_sha": os.environ.get("BNG3_PR_HEAD_SHA", ""),
        "distribution_version": distribution.version,
        "packaging_version": importlib.metadata.version("packaging"),
        "packaging_module": str(Path(packaging.__file__).resolve()),
        "distribution_package": str(distribution_package),
        "package_file": str(package_file),
        "native_extension": str(extension_file),
        "model_module": str(model_file),
        "model_native_extension": str(model_native_file),
        "native_extension_sha256": digest.hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision")
    args = parser.parse_args()
    try:
        identity = inspect_installed_package(args.source_revision)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(identity, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
