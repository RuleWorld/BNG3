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

MAX_ARCHIVE_MEMBERS = 4096
MAX_MEMBER_BYTES = 64 * 1024 * 1024  # 64 MiB per member
MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024  # 256 MiB total
MAX_COMPRESSION_RATIO = 200.0
_RATIO_CHECK_MIN_BYTES = 1024 * 1024  # 1 MiB
_READ_CHUNK_BYTES = 65536


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _validate_zip_member_path(name: str, archive_label: str = "COMBINE/OMEX") -> str:
    """Validate and normalize a ZIP member path, rejecting traversal or absolute paths."""

    raw = urllib.parse.unquote(str(name)).replace("\\", "/")
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha()):
        raise ValueError(
            f"{archive_label} archive member {name!r} uses a forbidden absolute path"
        )
    parts = raw.split("/")
    if any(part == ".." for part in parts):
        raise ValueError(
            f"{archive_label} archive member {name!r} contains forbidden '..' traversal"
        )
    normalised = posixpath.normpath(raw)
    if normalised in {".", ".."} or normalised.startswith("../"):
        return ""
    return normalised


def _normalise_member_name(name: str) -> str:
    value = urllib.parse.unquote(str(name).replace("\\", "/"))
    value = posixpath.normpath(value.lstrip("/"))
    return "" if value in {".", ".."} or value.startswith("../") else value


def _read_member_bounded(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    budget: list[int],
    archive_label: str = "COMBINE/OMEX",
) -> bytes:
    """Read a ZIP member with strict per-member, total, and compression-ratio bounds."""

    if info.file_size > MAX_MEMBER_BYTES:
        raise ValueError(
            f"{archive_label} archive member {info.filename!r} exceeds maximum "
            f"uncompressed size ({info.file_size} > {MAX_MEMBER_BYTES} bytes)"
        )
    if (
        info.file_size >= _RATIO_CHECK_MIN_BYTES
        and info.compress_size > 0
        and (info.file_size / info.compress_size) > MAX_COMPRESSION_RATIO
    ):
        raise ValueError(
            f"{archive_label} archive member {info.filename!r} exceeds maximum "
            f"decompression ratio ({info.file_size / info.compress_size:.1f}x > "
            f"{MAX_COMPRESSION_RATIO:.0f}x)"
        )
    chunks: list[bytes] = []
    member_bytes = 0
    with archive.open(info, "r") as handle:
        while True:
            chunk = handle.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            member_bytes += len(chunk)
            budget[0] += len(chunk)
            if member_bytes > MAX_MEMBER_BYTES:
                raise ValueError(
                    f"{archive_label} archive member {info.filename!r} exceeds maximum "
                    f"uncompressed size ({MAX_MEMBER_BYTES} bytes)"
                )
            if budget[0] > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise ValueError(
                    f"{archive_label} archive exceeds maximum total uncompressed size "
                    f"({MAX_TOTAL_UNCOMPRESSED_BYTES} bytes)"
                )
            if (
                member_bytes >= _RATIO_CHECK_MIN_BYTES
                and info.compress_size > 0
                and (member_bytes / info.compress_size) > MAX_COMPRESSION_RATIO
            ):
                raise ValueError(
                    f"{archive_label} archive member {info.filename!r} exceeds maximum "
                    f"decompression ratio ({MAX_COMPRESSION_RATIO:.0f}x)"
                )
            chunks.append(chunk)
    return b"".join(chunks)


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
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    budget: list[int],
    archive_label: str = "COMBINE/OMEX",
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
        raw_manifest = _read_member_bounded(
            archive, members[manifest_name], budget, archive_label
        )
        try:
            root = ET.fromstring(raw_manifest)
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


def _sbml_members(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    budget: list[int],
    archive_label: str = "COMBINE/OMEX",
) -> tuple[list[str], dict[str, bytes]]:
    candidates: list[str] = []
    cached_bytes: dict[str, bytes] = {}
    for name, info in members.items():
        lower = name.lower()
        if lower.endswith(("manifest.xml", "omex-manifest.xml", ".sedml", ".rdf")):
            continue
        if not lower.endswith((".xml", ".sbml")):
            continue
        raw = _read_member_bounded(archive, info, budget, archive_label)
        try:
            root = ET.fromstring(raw)
        except (ET.ParseError, KeyError, RuntimeError, UnicodeError):
            continue
        if _local_name(root.tag) == "sbml":
            candidates.append(name)
            cached_bytes[name] = raw
    return candidates, cached_bytes


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
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            raise ValueError(
                f"{archive_label} archive contains too many entries "
                f"({len(infos)} > {MAX_ARCHIVE_MEMBERS})"
            )
        declared_total = sum(
            max(0, int(info.file_size)) for info in infos if not info.is_dir()
        )
        if declared_total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError(
                f"{archive_label} archive declared uncompressed size exceeds limit "
                f"({declared_total} > {MAX_TOTAL_UNCOMPRESSED_BYTES} bytes)"
            )
        members: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            if info.is_dir():
                continue
            normalised = _validate_zip_member_path(info.filename, archive_label)
            if normalised:
                members.setdefault(normalised, info)
        if not members:
            raise ValueError(f"{archive_label} archive contains no files")

        budget = [0]
        candidates, cached_bytes = _sbml_members(
            archive, members, budget, archive_label
        )
        if not candidates:
            raise ValueError(f"{archive_label} archive contains no SBML XML document")

        selected: Optional[str] = None
        manifest_member: Optional[str] = None
        warnings: list[str] = []
        manifest_entries: list[dict[str, str]] = []
        if member is not None:
            selected = _validate_zip_member_path(member, archive_label)
            if selected not in candidates:
                raise ValueError(
                    f"requested archive member {member!r} is not an SBML document; "
                    f"candidates: {', '.join(candidates)}"
                )
        else:
            manifest_locations, manifest_member, manifest_entries = (
                _manifest_sbml_locations(archive, members, budget, archive_label)
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
        raw_sbml = cached_bytes.get(selected)
        if raw_sbml is None:
            raw_sbml = _read_member_bounded(
                archive, members[selected], budget, archive_label
            )
        text = raw_sbml.decode("utf-8-sig")
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
