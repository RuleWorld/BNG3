"""Classify a release tag with PEP 440 rules.

The GitHub Release ``prerelease`` flag must follow the tag's version, not a
substring search.  ``v3.0.0a1`` is an alpha even though it contains neither
"alpha" nor "beta" nor "rc".  Print ``prerelease=true|false`` so a workflow
step can forward the line to ``$GITHUB_OUTPUT`` unchanged.
"""

from __future__ import annotations

import argparse
import sys

from packaging.version import InvalidVersion, Version


def is_prerelease(tag: str) -> bool:
    """Return whether ``tag`` names a PEP 440 pre- or development release."""

    version = tag[1:] if tag[:1] in ("v", "V") else tag
    parsed = Version(version)
    return parsed.is_prerelease or parsed.is_devrelease


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="release tag, e.g. v3.0.0a1")
    args = parser.parse_args()
    try:
        prerelease = is_prerelease(args.tag)
    except InvalidVersion as exc:
        print(f"Invalid release tag {args.tag!r}: {exc}", file=sys.stderr)
        return 2
    print(f"prerelease={'true' if prerelease else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
