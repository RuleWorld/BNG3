"""Disable only Microsoft apt entries for the CUDA CI runner."""

from __future__ import annotations

import argparse
from pathlib import Path
import re

MICROSOFT_URI = re.compile(r"^https?://packages\.microsoft\.com(?:/|$)")


def _disable_list_entries(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = 0
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        source_fields = stripped.split("#", 1)[0].split()
        if stripped.startswith(("deb ", "deb-src ")) and any(
            MICROSOFT_URI.match(token) for token in source_fields
        ):
            lines[index] = (
                f"# disabled for CUDA CI: unrelated Microsoft feed returned 403; {line}"
            )
            changed += 1
    if changed:
        path.write_text("".join(lines), encoding="utf-8")
    return changed


def _disable_sources_stanzas(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    paragraphs = re.split(r"(\n\s*\n)", text)
    changed = 0
    for index in range(0, len(paragraphs), 2):
        lines = paragraphs[index].splitlines()
        uri_start = next(
            (i for i, line in enumerate(lines) if line.lower().startswith("uris:")),
            None,
        )
        if uri_start is None:
            continue
        uri_end = uri_start + 1
        while uri_end < len(lines) and lines[uri_end][:1].isspace():
            uri_end += 1
        urls = lines[uri_start].split(":", 1)[1].split()
        for continuation in lines[uri_start + 1 : uri_end]:
            urls.extend(continuation.split())
        microsoft = [url for url in urls if MICROSOFT_URI.match(url)]
        if not microsoft:
            continue
        remaining = [url for url in urls if not MICROSOFT_URI.match(url)]
        replacement = ["URIs: " + " ".join(remaining)] if remaining else []
        lines[uri_start:uri_end] = replacement
        enabled_index = next(
            (i for i, line in enumerate(lines) if line.lower().startswith("enabled:")),
            None,
        )
        if not remaining:
            if enabled_index is None:
                lines.append("Enabled: no")
            else:
                lines[enabled_index] = "Enabled: no"
        paragraphs[index] = "\n".join(lines)
        changed += len(microsoft)
    if changed:
        path.write_text("".join(paragraphs), encoding="utf-8")
    return changed


def disable_unreachable_sources(root: Path) -> int:
    """Remove Microsoft URIs while preserving every other apt source."""
    count = 0
    for path in [
        root / "sources.list",
        *sorted((root / "sources.list.d").glob("*.list")),
    ]:
        if path.is_file():
            count += _disable_list_entries(path)
    for path in sorted((root / "sources.list.d").glob("*.sources")):
        count += _disable_sources_stanzas(path)
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/etc/apt"))
    args = parser.parse_args()
    count = disable_unreachable_sources(args.root)
    print(f"Disabled {count} unrelated Microsoft apt source URI(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
