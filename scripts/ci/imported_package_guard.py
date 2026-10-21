"""Fail closed when the imported BNG3 package is not the harness's checkout.

A validation harness that imports ``bionetgen`` from somewhere other than the
checkout that owns it measures that other copy while producing an entirely
normal-looking report.  The SBML Test Suite harness records the imported
package's path and source digest, but nothing checked them, so a stale
``site-packages`` installation could silently become the subject of a campaign
measurement.

This module turns that into a precondition.  The imported package must be
traceable to the checkout that owns the harness:

``same-checkout``
    the package is this checkout's own ``python/bionetgen``;
``same-source``
    the package's Python sources are byte-identical to this checkout's, which
    is what a distribution installed from this checkout looks like;
``sibling-checkout``
    the package is another working tree of the same repository, which the
    campaign uses to share one native extension across worktrees.

Anything else is refused.  In particular an installed copy that was not
derived from this checkout is an unrelated package, not another view of this
one, and measuring it would report a verdict about code nobody is looking at.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PACKAGE_NAME = "bionetgen"
SOURCE_PACKAGE_PARTS = ("python", PACKAGE_NAME)
TRACE_SAME_CHECKOUT = "same-checkout"
TRACE_SAME_SOURCE = "same-source"
TRACE_SIBLING_CHECKOUT = "sibling-checkout"
TRACE_NOT_IMPORTABLE = "not-importable"
TRACE_SAME_CHECKOUT_BUILD = "same-checkout-build"
TRACE_INSTALLED_DISTRIBUTION = "installed-distribution"
TRACE_SIBLING_CHECKOUT_BUILD = "sibling-checkout-build"


class ForeignPackageError(RuntimeError):
    """Raised when the imported package is not traceable to this checkout."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_source_digest(package_dir: Path) -> str:
    """Identify Python behaviour independently of package location and version."""

    digest = hashlib.sha256()
    for source in sorted(package_dir.rglob("*.py")):
        digest.update(source.relative_to(package_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(source).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _imported_package_file(package_module: Any, package_name: str) -> Path | None:
    """Return the resolved file of the package the interpreter will import.

    ``None`` means the package is not importable at all.  There is then
    nothing to trace, and the harness's own extension check reports the
    missing package.
    """

    if package_module is None:
        try:
            package_module = importlib.import_module(package_name)
        except Exception:
            return None
    file_name = getattr(package_module, "__file__", None)
    if not file_name:
        return None
    return Path(file_name).resolve()


def _git_output(path: Path, *arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *arguments],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


def _git_common_dir(path: Path) -> str | None:
    return _git_output(path, "rev-parse", "--path-format=absolute", "--git-common-dir")


def _git_origin_url(path: Path) -> str | None:
    return _git_output(path, "remote", "get-url", "origin")


def _normalised_remote(url: str) -> str:
    return url.strip().rstrip("/").removesuffix(".git").lower()


def _same_repository(left: Path, right: Path) -> bool:
    """Report whether two directories are working trees of one repository."""

    left_common = _git_common_dir(left)
    right_common = _git_common_dir(right)
    if left_common and right_common and left_common == right_common:
        return True
    left_origin = _git_origin_url(left)
    right_origin = _git_origin_url(right)
    if left_origin and right_origin:
        return _normalised_remote(left_origin) == _normalised_remote(right_origin)
    return False


def _safe_source_digest(package_dir: Path) -> str | None:
    """Return the package's source digest, or ``None`` when it cannot be read."""

    try:
        return package_source_digest(package_dir)
    except OSError:
        return None


def _sibling_checkout_root(package_dir: Path) -> Path | None:
    """Return the checkout root of a ``<root>/python/bionetgen`` package."""

    if package_dir.parent.name != "python":
        return None
    return package_dir.parent.parent


def _build_tree_root(directory: Path, leaf: str) -> Path | None:
    """Return the checkout root of a ``<root>/<leaf>`` build tree."""

    if directory.name != leaf:
        return None
    return directory.parent.parent


def _refusal_message(
    imported_file: Path,
    imported_digest: str | None,
    expected_dir: Path,
    expected_digest: str | None,
) -> str:
    return (
        "the imported 'bionetgen' package is not this checkout's\n"
        f"  imported: {imported_file}\n"
        f"            source sha256 {imported_digest or 'unavailable'}\n"
        f"  expected: {expected_dir}\n"
        f"            source sha256 {expected_digest or 'unavailable'}\n"
        "Measuring now would report a verdict about the imported package rather "
        "than about this checkout. Run the harness from the repository root with "
        "PYTHONPATH=python:build/cpp so 'bionetgen' resolves to "
        "<root>/python/bionetgen, or install this checkout's package "
        "(pip install .) and run again."
    )


def verify_imported_package(
    repository_root: Path | str,
    *,
    package_name: str = PACKAGE_NAME,
    package_module: Any | None = None,
) -> dict[str, Any]:
    """Return the trace of the imported package, or refuse to measure.

    ``package_module`` overrides the imported module for callers that already
    hold it; the default imports the package the interpreter would use.
    """

    root = Path(repository_root).resolve()
    expected_dir = root.joinpath(*SOURCE_PACKAGE_PARTS)
    imported_file = _imported_package_file(package_module, package_name)
    if imported_file is None:
        return {
            "rule": TRACE_NOT_IMPORTABLE,
            "package_file": None,
            "expected_package_dir": str(expected_dir),
        }
    imported_dir = imported_file.parent

    if imported_dir == expected_dir:
        return {
            "rule": TRACE_SAME_CHECKOUT,
            "package_file": str(imported_file),
            "expected_package_dir": str(expected_dir),
        }

    imported_digest = _safe_source_digest(imported_dir)
    expected_digest = (
        _safe_source_digest(expected_dir) if expected_dir.is_dir() else None
    )
    if expected_digest is not None and imported_digest == expected_digest:
        return {
            "rule": TRACE_SAME_SOURCE,
            "package_file": str(imported_file),
            "expected_package_dir": str(expected_dir),
            "source_sha256": imported_digest,
        }

    sibling_root = _sibling_checkout_root(imported_dir)
    if (
        sibling_root is not None
        and sibling_root != root
        and _same_repository(sibling_root, root)
    ):
        return {
            "rule": TRACE_SIBLING_CHECKOUT,
            "package_file": str(imported_file),
            "expected_package_dir": str(expected_dir),
            "sibling_checkout_root": str(sibling_root),
        }

    raise ForeignPackageError(
        _refusal_message(imported_file, imported_digest, expected_dir, expected_digest)
    )


def _extension_refusal_message(
    extension: Path, extension_dir: Path, build_tree: Path
) -> str:
    return (
        "the imported native extension is not this checkout's build\n"
        f"  imported: {extension}\n"
        f"  expected: {build_tree}/_bionetgen_cpp* (this checkout's build tree), "
        "or the extension installed beside the imported package, or a sibling "
        "checkout's build tree\n"
        "Measuring now would report a verdict about a native build this checkout "
        "did not produce. Build this checkout's extension "
        "(cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && "
        "cmake --build build) and run the harness with "
        "PYTHONPATH=python:build/cpp."
    )


def verify_native_extension(
    repository_root: Path | str,
    *,
    extension_file: Path | str,
    package_trace: dict[str, Any],
) -> dict[str, Any]:
    """Return the trace of the imported native extension, or refuse to measure.

    The extension is a build artefact rather than source, so it is identified
    by the tree that built it:

    ``same-checkout-build``
        the extension is this checkout's own ``build/cpp`` tree;
    ``installed-distribution``
        the extension sits beside the imported Python package, in the
        distribution that package was installed from;
    ``sibling-checkout-build``
        the extension is another working tree's ``build/cpp`` tree, which is
        how the campaign shares one native extension across worktrees.
    """

    root = Path(repository_root).resolve()
    extension = Path(extension_file).resolve()
    extension_dir = extension.parent
    build_tree = (root / "build" / "cpp").resolve()
    trace = {
        "extension_file": str(extension),
        "extension_dir": str(extension_dir),
        "expected_extension_dir": str(build_tree),
    }

    if extension_dir == build_tree:
        return {**trace, "rule": TRACE_SAME_CHECKOUT_BUILD}

    package_file = package_trace.get("package_file")
    package_rule = package_trace.get("rule")
    if package_file and package_rule in {TRACE_SAME_CHECKOUT, TRACE_SAME_SOURCE}:
        if extension_dir == Path(package_file).resolve().parent:
            return {**trace, "rule": TRACE_INSTALLED_DISTRIBUTION}

    sibling_root = _build_tree_root(extension_dir, "cpp")
    if (
        sibling_root is not None
        and sibling_root != root
        and _same_repository(sibling_root, root)
    ):
        return {
            **trace,
            "rule": TRACE_SIBLING_CHECKOUT_BUILD,
            "sibling_checkout_root": str(sibling_root),
        }

    raise ForeignPackageError(
        _extension_refusal_message(extension, extension_dir, build_tree)
    )


def main(argv: list[str] | None = None) -> int:
    """Report which package this checkout would import, or refuse it."""

    arguments = sys.argv[1:] if argv is None else argv
    root = Path(arguments[0]) if arguments else Path.cwd()
    try:
        trace = verify_imported_package(root)
    except ForeignPackageError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(trace, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
