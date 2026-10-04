"""Select and verify the BNG3 Python package used by test suites."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def _editable(finder: Any) -> bool:
    finder_type = type(finder)
    return (
        "editable" in finder_type.__module__.lower()
        or "editable" in getattr(finder, "__name__", "").lower()
    )


def _package_name_matches(name: object, package: str) -> bool:
    return isinstance(name, str) and (name == package or name.startswith(package + "."))


def editable_finders_for_package(
    finders: Iterable[Any], package: str = "bionetgen"
) -> list[Any]:
    """Return editable finders that advertise modules for ``package``.

    Unrelated editable finders are left alone. Import location checks still
    catch an opaque finder if it actually shadows the package.
    """
    result = []
    for finder in finders:
        if not _editable(finder):
            continue
        names: set[object] = set()
        for attribute in ("known_source_files", "search_paths"):
            entries = getattr(finder, attribute, None)
            if isinstance(entries, Mapping):
                names.update(entries)
        module = type(finder).__module__.lower()
        class_name = type(finder).__name__.lower()
        advertised_by_name = any(_package_name_matches(name, package) for name in names)
        advertised_by_finder_name = (
            package.lower() in module or package.lower() in class_name
        )
        if advertised_by_name or advertised_by_finder_name:
            result.append(finder)
    return result


def editable_source_roots(
    finders: Iterable[Any], package: str = "bionetgen"
) -> set[Path]:
    """Return sys.path roots registered by package-specific editable finders."""
    roots: set[Path] = set()
    for finder in finders:
        if finder not in editable_finders_for_package((finder,), package):
            continue
        known = getattr(finder, "known_source_files", None)
        if isinstance(known, Mapping):
            for name, value in known.items():
                if not _package_name_matches(name, package) or not isinstance(
                    value, (str, Path)
                ):
                    continue
                source = Path(value).resolve()
                if source.parent.name == package:
                    roots.add(source.parent.parent)
        search_paths = getattr(finder, "search_paths", None)
        if isinstance(search_paths, Mapping):
            values = [
                value
                for name, value in search_paths.items()
                if _package_name_matches(name, package)
            ]
        elif isinstance(search_paths, Iterable) and not isinstance(
            search_paths, (str, bytes)
        ):
            values = list(search_paths)
        else:
            values = []
        for value in values:
            if not isinstance(value, (str, Path)):
                continue
            source = Path(value).resolve()
            roots.add(source.parent if source.name == package else source)
    return roots


def resolve_test_mode(
    requested: str,
    *,
    finders: Iterable[Any],
    source_path_present: bool,
    loaded_from_source: bool,
    auto_default: str | None,
    package: str = "bionetgen",
) -> tuple[str | None, list[Any]]:
    """Resolve ``auto``, ``source`` or ``installed`` mode.

    ``auto_default=None`` preserves validation suites' optional local API
    behavior when neither this checkout nor an installed mode was requested.
    """
    requested = requested.lower()
    if requested not in {"auto", "source", "installed"}:
        raise RuntimeError(
            "BNG3_PYTHON_TEST_MODE must be 'auto', 'source', or 'installed'; "
            f"received {requested!r}"
        )
    relevant = editable_finders_for_package(finders, package)
    if requested == "installed":
        if relevant:
            raise RuntimeError(
                "installed package tests found a BNG3 editable import finder; "
                "install a regular wheel before running this suite"
            )
        return "installed", relevant
    if requested == "source":
        return "source", relevant
    if relevant or source_path_present or loaded_from_source:
        return "source", relevant
    return auto_default, relevant


def verify_package_locations(
    package_file: str | Path,
    extension_file: str | Path,
    *,
    package_dir: str | Path,
    extension_dir: str | Path,
    mode: str,
) -> None:
    """Raise when package Python files or the native module came from elsewhere."""
    package_path = Path(package_file).resolve()
    extension_path = Path(extension_file).resolve()
    expected_package = Path(package_dir).resolve()
    expected_extension = Path(extension_dir).resolve()
    if package_path.parent != expected_package:
        raise RuntimeError(
            f"{mode} bionetgen package was shadowed: {package_path} "
            f"(expected under {expected_package})"
        )
    if extension_path.parent != expected_extension:
        raise RuntimeError(
            f"{mode} native extension was shadowed: {extension_path} "
            f"(expected under {expected_extension})"
        )
