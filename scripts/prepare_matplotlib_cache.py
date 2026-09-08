"""Seed Matplotlib with bundled fonts before CI imports pyplot.

Some Ubuntu runner images expose a system font that crashes older Matplotlib
FreeType wheels while the font manager scans every installed font.  The plot
tests only need Matplotlib's bundled DejaVu family, so keep the CI cache
portable and avoid the system-font scan entirely.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

_DEJAVU_FONTS = (
    ("DejaVuSans.ttf", "normal", 400),
    ("DejaVuSans-Bold.ttf", "normal", 700),
    ("DejaVuSans-Oblique.ttf", "italic", 400),
    ("DejaVuSans-BoldOblique.ttf", "italic", 700),
)


def _font_manager_version() -> int | str:
    source_path = Path(matplotlib.__file__).with_name("font_manager.py")
    source = source_path.read_text(encoding="utf-8")
    match = re.search(r"__version__\s*=\s*(['\"]?)([0-9][^'\"\s]*)\1", source)
    if match is None:
        raise RuntimeError(
            f"Could not determine Matplotlib font-cache version from {source_path}"
        )
    version = match.group(2)
    return int(version) if version.isdigit() else version


def _font_entries() -> list[dict[str, object]]:
    return [
        {
            "fname": f"fonts/ttf/{filename}",
            "name": "DejaVu Sans",
            "style": style,
            "variant": "normal",
            "weight": weight,
            "stretch": "normal",
            "size": "scalable",
            "__class__": "FontEntry",
        }
        for filename, style, weight in _DEJAVU_FONTS
    ]


def main() -> None:
    version = _font_manager_version()
    cache_path = Path(matplotlib.get_cachedir()) / f"fontlist-v{version}.json"
    cache = {
        "_version": version,
        "_FontManager__default_weight": "normal",
        "default_size": None,
        "defaultFamily": {"ttf": "DejaVu Sans", "afm": "Helvetica"},
        "afmlist": [],
        "ttflist": _font_entries(),
        "__class__": "FontManager",
    }
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    print(f"Seeded Matplotlib font cache: {cache_path}")


if __name__ == "__main__":
    main()
