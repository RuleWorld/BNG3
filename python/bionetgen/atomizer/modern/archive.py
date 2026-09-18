"""COMBINE/OMEX archive helpers for the modern SBML atomizer.

COMBINE archives are ZIP containers.  This module deliberately extracts only
the SBML document selected by the archive manifest (or the unique SBML member
when no manifest is present); SED-ML, RDF, and other archive resources are
not passed to the SBML parser.
"""

from __future__ import annotations

import io
import posixpath
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional, Union

ArchiveSource = Union[str, Path, bytes, bytearray, BinaryIO]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalise_member_name(name: str) -> str:
    value = urllib.parse.unquote(str(name).replace("\\", "/"))
    value = posixpath.normpath(value.lstrip("/"))
    return "" if value in {".", ".."} or value.startswith("../") else value


def _archive_bytes(source: ArchiveSource) -> bytes:
    if isinstance(source, bytes):
        return source
    if isinstance(source, bytearray):
        return bytes(source)
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    if hasattr(source, "read"):
        data = source.read()
        return data if isinstance(data, bytes) else bytes(data)
    raise TypeError("archive must be a path, bytes, or binary file-like object")


def _manifest_sbml_locations(
    archive: zipfile.ZipFile, members: dict[str, str]
) -> tuple[list[str], Optional[str], list[dict[str, str]]]:
    locations: list[str] = []
    manifest_member: Optional[str] = None
    entries: list[dict[str, str]] = []
    manifest_names = [
        name
        for name in members
        if name.lower().endswith(("manifest.xml", "omex-manifest.xml"))
    ]
    for manifest_name in manifest_names:
        try:
            root = ET.fromstring(archive.read(members[manifest_name]))
        except (ET.ParseError, KeyError, RuntimeError, zipfile.BadZipFile):
            continue
        base = posixpath.dirname(manifest_name)
        for content in root.iter():
            if _local_name(content.tag) != "content":
                continue
            format_value = " ".join(
                str(value).lower()
                for key, value in content.attrib.items()
                if key.rsplit("}", 1)[-1] == "format"
            )
            location = next(
                (
                    str(value)
                    for key, value in content.attrib.items()
                    if key.rsplit("}", 1)[-1] == "location"
                ),
                "",
            )
            normalised_location = _normalise_member_name(posixpath.join(base, location))
            entries.append(
                {
                    "location": normalised_location,
                    "format": format_value,
                    "master": str(
                        next(
                            (
                                value
                                for key, value in content.attrib.items()
                                if key.rsplit("}", 1)[-1] == "master"
                            ),
                            "",
                        )
                    ).lower(),
                }
            )
            if "sbml" not in format_value or not location:
                continue
            location = normalised_location
            if location in members and location not in locations:
                locations.append(location)
        if locations:
            manifest_member = manifest_name
            break
    return locations, manifest_member, entries


def _sbml_members(archive: zipfile.ZipFile, members: dict[str, str]) -> list[str]:
    candidates: list[str] = []
    for name, member in members.items():
        lower = name.lower()
        if lower.endswith(("manifest.xml", "omex-manifest.xml", ".sedml", ".rdf")):
            continue
        if not lower.endswith((".xml", ".sbml")):
            continue
        try:
            root = ET.fromstring(archive.read(member))
        except (ET.ParseError, KeyError, RuntimeError, UnicodeError):
            continue
        if _local_name(root.tag) == "sbml":
            candidates.append(name)
    return candidates


@dataclass(frozen=True)
class CombineArchiveExtraction:
    """The SBML member selected from a COMBINE/OMEX archive."""

    sbml: str
    member: str
    candidates: tuple[str, ...]
    manifest_member: Optional[str] = None
    manifest_entries: tuple[dict[str, str], ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def sbml_string(self) -> str:
        return self.sbml


def _extract_sbml_from_zip(
    source: ArchiveSource,
    member: Optional[str] = None,
    archive_label: str = "COMBINE/OMEX",
) -> CombineArchiveExtraction:
    """Extract one SBML document from a ZIP archive.

    ``member`` can explicitly select an archive path.  Otherwise a manifest
    SBML entry is preferred; without a manifest the archive must contain one
    unique SBML document.  Ambiguous archives fail closed instead of silently
    selecting the wrong model.
    """

    data = _archive_bytes(source)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data), "r")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"source is not a valid {archive_label} ZIP archive") from exc
    with archive:
        members: dict[str, str] = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            normalised = _normalise_member_name(info.filename)
            if normalised:
                members.setdefault(normalised, info.filename)
        if not members:
            raise ValueError(f"{archive_label} archive contains no files")

        candidates = _sbml_members(archive, members)
        if not candidates:
            raise ValueError(f"{archive_label} archive contains no SBML XML document")

        selected: Optional[str] = None
        manifest_member: Optional[str] = None
        warnings: list[str] = []
        manifest_entries: list[dict[str, str]] = []
        if member is not None:
            selected = _normalise_member_name(member)
            if selected not in candidates:
                raise ValueError(
                    f"requested archive member {member!r} is not an SBML document; "
                    f"candidates: {', '.join(candidates)}"
                )
        else:
            manifest_locations, manifest_member, manifest_entries = (
                _manifest_sbml_locations(archive, members)
            )
            if manifest_locations:
                selected = manifest_locations[0]
                if len(manifest_locations) > 1:
                    warnings.append(
                        f"{archive_label} manifest lists multiple SBML documents; "
                        f"selected first manifest entry {selected!r}."
                    )
            elif len(candidates) == 1:
                selected = candidates[0]
                warnings.append(
                    f"{archive_label} archive has no manifest SBML entry; selected its "
                    "unique SBML document."
                )
            else:
                raise ValueError(
                    f"{archive_label} archive contains multiple SBML documents without a "
                    "manifest selection: " + ", ".join(candidates)
                )

        assert selected is not None
        text = archive.read(members[selected]).decode("utf-8-sig")
        return CombineArchiveExtraction(
            sbml=text,
            member=selected,
            candidates=tuple(candidates),
            manifest_member=manifest_member,
            manifest_entries=tuple(manifest_entries),
            warnings=tuple(warnings),
        )


def extract_sbml_from_combine_archive(
    source: ArchiveSource, member: Optional[str] = None
) -> CombineArchiveExtraction:
    """Extract one SBML document from a COMBINE/OMEX ZIP archive."""

    return _extract_sbml_from_zip(source, member, "COMBINE/OMEX")


def extract_sbml_from_archive(
    source: ArchiveSource, member: Optional[str] = None
) -> CombineArchiveExtraction:
    """Extract one SBML document from any ZIP-based archive.

    This is intentionally format-agnostic: it can inspect non-OMEX ZIP
    submissions and only forwards a manifest-selected or uniquely detected
    SBML XML member to the atomizer.
    """

    return _extract_sbml_from_zip(source, member, "ZIP")


# Short alias for callers that use the OMEX spelling.
extract_sbml_from_omex = extract_sbml_from_combine_archive


__all__ = [
    "ArchiveSource",
    "CombineArchiveExtraction",
    "extract_sbml_from_archive",
    "extract_sbml_from_combine_archive",
    "extract_sbml_from_omex",
]
