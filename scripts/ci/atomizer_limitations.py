#!/usr/bin/env python3
"""Render the Atomizer's limitations document from the expectation manifest.

The document is a scope record: it states what BNG3's SBML Atomizer does not
support, why, and whether the boundary is reducible.  Its counts, its case
ids and the side of each boundary come from the expectation manifest, which
the campaign regenerates on every verdict-changing merge; its narrative comes
from ``provenance/sbml-campaign/atomizer-limitations.json``.  Neither half is
written by hand into the document, so the document cannot drift away from the
measurement it describes.

Usage:
    python scripts/ci/atomizer_limitations.py \
        --manifest provenance/sbml-campaign/expectations.json \
        --narrative provenance/sbml-campaign/atomizer-limitations.json \
        --doc docs/ATOMIZER_LIMITATIONS.md

    # verify the document against the manifest; exit non-zero on drift
    python scripts/ci/atomizer_limitations.py … --check
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO / "provenance" / "sbml-campaign" / "expectations.json"
DEFAULT_NARRATIVE = REPO / "provenance" / "sbml-campaign" / "atomizer-limitations.json"
DEFAULT_DOC = REPO / "docs" / "ATOMIZER_LIMITATIONS.md"

BEGIN_MARKER = "<!-- BEGIN GENERATED: atomizer-limitations -->"
END_MARKER = "<!-- END GENERATED: atomizer-limitations -->"

# The order the sections are rendered in.  A harness-side gap is a
# measurement limit and an Atomizer-side gap is a representational one; they
# are never mixed, because they are different kinds of work.
SIDE_ORDER = ("atomizer", "harness", "not-applicable")

SECTION_TITLES = {
    "atomizer": "The Atomizer's limitations",
    "harness": "The harness's measurement limits",
    "not-applicable": "Cases the official suite says do not apply",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _cases_by_construct(
    manifest: dict[str, Any],
) -> dict[tuple[str, str], set[str]]:
    """Return the cases each (side, construct) gap belongs to."""

    cases: dict[tuple[str, str], set[str]] = {}
    for identity, entry in (manifest.get("cases") or {}).items():
        for gap in (entry.get("gap") or {}).values():
            key = (str(gap.get("side", "atomizer")), str(gap.get("construct")))
            cases.setdefault(key, set()).add(identity)
    return cases


def _tool_version() -> str:
    """Return the version of the package this document describes."""

    try:
        result = subprocess.run(
            [sys.executable, "-c", "import bionetgen; print(bionetgen.__version__)"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    version = result.stdout.strip()
    return version or "unknown"


def _generated_on() -> str:
    """Return the date the document is generated on, in UTC."""

    return subprocess.run(
        ["date", "-u", "+%Y-%m-%d"], capture_output=True, text=True, check=False
    ).stdout.strip()


def _document_generated_on(document: str) -> str:
    """Return the generation date the committed document already carries.

    The generation date is the day the document was written, not a
    measurement, so a check must not fail because the calendar moved on.
    The check therefore re-renders with the date the document already has and
    compares everything else.
    """

    match = re.search(r"^\| Generated on \| (\d{4}-\d{2}-\d{2}) \|$", document, re.M)
    return match.group(1) if match else _generated_on()


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _case_ids(identities: set[str], limit: int = 24) -> str:
    ordered = sorted(identities)
    if len(ordered) <= limit:
        return " ".join(ordered)
    head = " ".join(ordered[:limit])
    return f"{head} … ({len(ordered) - limit} more)"


def render(
    manifest: dict[str, Any],
    narrative: dict[str, Any],
    *,
    generated_on: str,
    tool_version: str,
) -> str:
    """Render the whole document."""

    constructs = narrative.get("constructs") or {}
    by_construct = _cases_by_construct(manifest)

    source_report = manifest.get("source_report") or {}
    provenance = manifest.get("provenance") or {}
    environment = provenance.get("measurement_environment") or {}
    suite = manifest.get("suite") or {}

    lines: list[str] = []
    lines.append("# BNG3 SBML Atomizer limitations")
    lines.append("")
    lines.append(
        "This is the scope record of BNG3's SBML Atomizer: what it does not "
        "support, what the specification requires in those cases, what BNG3 "
        "does instead, and whether each boundary is reducible. It is "
        "generated from the campaign's expectation manifest, so it cannot "
        "drift away from the measurement it describes."
    )
    lines.append("")
    lines.append(
        "A limitation is **not** a defect. It is a case the Atomizer refuses, "
        "and a refusal is the honest outcome for a construct BNG3 cannot "
        "represent exactly. Defects are the other class: a case that BNG3 "
        "converts and then gets wrong. Those are tracked in the conformance "
        "findings backlog, not here."
    )
    lines.append("")
    lines.append("## Header")
    lines.append("")
    lines.extend(
        _table(
            ["Field", "Value"],
            [
                ["Generated on", generated_on],
                ["Tree described", f"`{source_report.get('bng3_commit', 'unknown')}`"],
                [
                    "Measured at commit",
                    f"`{source_report.get('measured_at_commit', 'unknown')}`",
                ],
                [
                    "Official suite revision",
                    f"`{suite.get('revision', 'unknown')}`"
                    f" ({suite.get('repository', 'unknown')})",
                ],
                [
                    "Report SHA-256",
                    f"`{source_report.get('sha256', 'unknown')}`",
                ],
                ["BNG3 version", tool_version],
                [
                    "Native extension SHA-256",
                    f"`{environment.get('native_extension_sha256', 'unknown')}`",
                ],
                [
                    "Source tree of the measurement",
                    f"`{environment.get('source_tree', 'unknown')}`",
                ],
            ],
        )
    )
    lines.append("")
    lines.append(
        "The measurement is a full run of the pinned official SBML Test "
        "Suite; its per-case verdicts are recorded in the expectation "
        "manifest, which the campaign regenerates whenever a merge changes a "
        "verdict."
    )
    lines.append("")

    lines.append("## How to read this document")
    lines.append("")
    lines.append(
        "A case's official reference ends in exactly one of three states, and "
        "the difference is the whole point:"
    )
    lines.append("")
    lines.extend(
        _table(
            ["State", "What it means"],
            [
                [
                    "passed",
                    "the case was compared against the official reference and "
                    "the two agree",
                ],
                [
                    "failed",
                    "the case was compared and the two **disagree** — a defect, "
                    "not a limitation",
                ],
                [
                    "unsupported",
                    "the case was **not compared**: the Atomizer refused it, "
                    "or the comparison could not be made",
                ],
            ],
        )
    )
    lines.append("")
    lines.append(
        "So a *limitation* is a case the Atomizer refuses, and it is a scope "
        "boundary rather than a defect. The manifest records which side of "
        "the boundary each refusal sits on, and the two sides are different "
        "kinds of work:"
    )
    lines.append("")
    lines.extend(
        _table(
            ["Side", "What it means", "What it asks for"],
            [
                [
                    "`atomizer`",
                    "a construct is not representable today; the case is " "refused",
                    "extending the Atomizer's semantics, or a documented "
                    "boundary that will not move",
                ],
                [
                    "`harness`",
                    "the model may be perfectly good, but the comparison "
                    "could not be made",
                    "a better measurement — these are the **reducible** ones, "
                    "and they are kept in their own section so that a "
                    "measurement limit is never mistaken for a limitation of "
                    "the Atomizer",
                ],
                [
                    "`not-applicable`",
                    "the official suite itself says the case defines no "
                    "time-course reference",
                    "nothing: there is no comparison to make and nobody "
                    "should go looking for a fix",
                ],
            ],
        )
    )
    lines.append("")
    lines.append(
        "Every limitation below carries the date it was recorded. A "
        "limitation that is closed does not vanish: it moves to "
        "[Resolved limitations](#resolved-limitations) with the date it was "
        "closed."
    )
    lines.append("")

    # ---------------------------------------------------------------- summary
    lines.append("## Summary")
    lines.append("")
    rows = []
    for side in SIDE_ORDER:
        for (entry_side, construct), identities in sorted(
            by_construct.items(), key=lambda item: (-len(item[1]), item[0][1])
        ):
            if entry_side != side:
                continue
            entry = constructs.get(construct)
            rows.append(
                [
                    f"`{construct}`",
                    side,
                    str(len(identities)),
                    (entry or {}).get("title", "**no narrative recorded**"),
                    (entry or {}).get("first_recorded", "—"),
                ]
            )
    lines.extend(
        _table(["Construct", "Side", "Cases", "What it is", "First recorded"], rows)
    )
    lines.append("")
    counted = Counter(
        side for (side, _), identities in by_construct.items() for _ in identities
    )
    lines.append(
        "Cases with a recorded gap: "
        + ", ".join(f"{counted.get(side, 0)} {side}-side" for side in SIDE_ORDER)
        + ". A case may carry a gap at more than one stage, so the counts "
        "above count distinct cases per construct."
    )
    lines.append("")

    # ----------------------------------------------------------------- detail
    for side in SIDE_ORDER:
        lines.append(f"## {SECTION_TITLES[side]}")
        lines.append("")
        if side == "atomizer":
            lines.append(
                "These are the constructs BNG3's SBML Atomizer cannot "
                "represent exactly today. Each one is refused explicitly, and "
                "the refusal names the condition."
            )
            lines.append("")
        elif side == "harness":
            lines.append(
                "**These are measurement limits, not limitations of the "
                "Atomizer.** The model converts and nothing is refused; the "
                "comparison against the official reference simply could not be "
                "made. They are the reducible ones, and they are kept apart "
                "so that a reader does not mistake a measurement limit for "
                "something BNG3 cannot do."
            )
            lines.append("")
        else:
            lines.append(
                "The official suite itself records that these cases define no "
                "time-course reference, so there is nothing to compare "
                "against. This is not a limitation of the Atomizer and not a "
                "defect; nobody should go looking for a fix."
            )
            lines.append("")
        for (entry_side, construct), identities in sorted(
            by_construct.items(), key=lambda item: (-len(item[1]), item[0][1])
        ):
            if entry_side != side:
                continue
            entry = constructs.get(construct)
            if entry is None:
                lines.append(f"### `{construct}`")
                lines.append("")
                lines.append(
                    "**No narrative is recorded for this construct.** The "
                    "narrative file must gain an entry for it; the generator "
                    "refuses to render a limitation it cannot explain."
                )
                lines.append("")
                continue
            lines.append(f"### {entry.get('title', construct)}")
            lines.append("")
            lines.append(f"- **Construct**: `{construct}`")
            lines.append(f"- **Cases**: {len(identities)} — {_case_ids(identities)}")
            lines.append(f"- **First recorded**: {entry.get('first_recorded', '—')}")
            lines.append(f"- **What SBML requires**: {entry.get('sbml_requires', '')}")
            lines.append(f"- **Citation**: {entry.get('citation', '')}")
            lines.append(f"- **What BNG3 does instead**: {entry.get('bng3_does', '')}")
            lines.append(f"- **Reducible?**: {entry.get('reducible', '')}")
            lines.append("")

    # --------------------------------------------------------------- resolved
    lines.append("## Resolved limitations")
    lines.append("")
    lines.append(
        "A limitation that is closed does not vanish from the record. This "
        "section names the constructs the campaign no longer refuses, and "
        'when it stopped refusing them. The "no longer exercised" entries '
        "are different: the Atomizer still refuses that construct, but the "
        "official suite no longer reaches the refusal."
    )
    lines.append("")
    resolved = [
        (construct, entry)
        for construct, entry in sorted((constructs or {}).items())
        if entry.get("status") in {"closed", "not-exercised"}
    ]
    if resolved:
        rows = []
        for construct, entry in resolved:
            rows.append(
                [
                    f"`{construct}`",
                    entry.get("title", ""),
                    entry.get("status", ""),
                    entry.get("closed") or entry.get("last_exercised") or "—",
                    entry.get("resolved_note", "")
                    or entry.get("closed_by", "")
                    or entry.get("reducible", ""),
                ]
            )
        lines.extend(
            _table(
                [
                    "Construct",
                    "What it is",
                    "Status",
                    "Date",
                    "What happened",
                ],
                rows,
            )
        )
    else:
        lines.append("No limitation has been closed yet.")
    lines.append("")

    # -------------------------------------------------------------- changelog
    lines.append("## What changed")
    lines.append("")
    lines.append(
        "The expectation manifest records one measurement, not a history, so "
        "this log is the one part of the document that is maintained by hand. "
        "It is a dated record of the limitations that were opened and closed."
    )
    lines.append("")
    for entry in sorted(
        narrative.get("changelog") or [], key=lambda item: str(item.get("date", ""))
    ):
        lines.append(f"- **{entry.get('date', '')}** — {entry.get('change', '')}")
    lines.append("")

    # ------------------------------------------------------------- regenerate
    lines.append("## How to regenerate")
    lines.append("")
    lines.append(
        "This document is generated. Do not edit it by hand: the generator "
        "overwrites the marked region below, and `--check` fails when the "
        "document no longer matches the manifest."
    )
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/ci/atomizer_limitations.py \\")
    lines.append("    --manifest provenance/sbml-campaign/expectations.json \\")
    lines.append(
        "    --narrative provenance/sbml-campaign/atomizer-limitations.json \\"
    )
    lines.append("    --doc docs/ATOMIZER_LIMITATIONS.md")
    lines.append("")
    lines.append("# verify the document against the manifest")
    lines.append("python scripts/ci/atomizer_limitations.py \\")
    lines.append("    --manifest provenance/sbml-campaign/expectations.json \\")
    lines.append(
        "    --narrative provenance/sbml-campaign/atomizer-limitations.json \\"
    )
    lines.append("    --doc docs/ATOMIZER_LIMITATIONS.md --check")
    lines.append("```")
    lines.append("")
    lines.append(
        "The counts, the case ids and the side of every boundary come from "
        "the expectation manifest. The narrative — what the specification "
        "requires, what BNG3 does instead, whether the boundary is reducible, "
        "and the dates — comes from "
        "`provenance/sbml-campaign/atomizer-limitations.json`, which is the "
        "one hand-maintained input this document has."
    )
    lines.append("")
    lines.append("## Related documents")
    lines.append("")
    lines.append(
        "- [SBML Atomizer coverage campaign](SBML_ATOMIZER_COVERAGE_CAMPAIGN.md) — "
        "how the coverage numbers were measured and how the campaign changed "
        "the Atomizer."
    )
    lines.append(
        "- [SBML conformance findings](SBML_CONFORMANCE_FINDINGS.md) — the "
        "**backlog** of open findings. A finding is a case that was compared "
        "and got wrong; a limitation is a case that was refused."
    )
    lines.append(
        "- [Curated BioModels corpus](CURATED_BIOMODELS_CORPUS.md) — the "
        "record of the published-model corpus."
    )
    lines.append(
        "- [Documentation index](index.md) — the rest of BNG3's " "documentation."
    )
    lines.append("")
    return "\n".join(lines)


def replace_region(document: str, body: str) -> str:
    start = document.find(BEGIN_MARKER)
    stop = document.find(END_MARKER)
    if start < 0 or stop < 0 or stop < start:
        raise ValueError(
            f"the document is missing the generated region ({BEGIN_MARKER} … "
            f"{END_MARKER})"
        )
    prefix = document[: start + len(BEGIN_MARKER)]
    suffix = document[stop:]
    return f"{prefix}\n\n{body}\n{suffix}"


def read_region(document: str) -> str:
    start = document.find(BEGIN_MARKER)
    stop = document.find(END_MARKER)
    if start < 0 or stop < 0 or stop < start:
        raise ValueError(
            f"the document is missing the generated region ({BEGIN_MARKER} … "
            f"{END_MARKER})"
        )
    return document[start + len(BEGIN_MARKER) : stop].strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--narrative", type=Path, default=DEFAULT_NARRATIVE)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the document against the manifest; exit non-zero on drift",
    )
    args = parser.parse_args()

    manifest = _load(args.manifest)
    narrative = _load(args.narrative)
    tool_version = _tool_version()
    body = render(
        manifest,
        narrative,
        generated_on=_generated_on(),
        tool_version=tool_version,
    )
    document = args.doc.read_text(encoding="utf-8") if args.doc.is_file() else ""

    if args.check:
        if not document:
            print(f"{args.doc} does not exist", file=sys.stderr)
            return 1
        body = render(
            manifest,
            narrative,
            generated_on=_document_generated_on(document),
            tool_version=tool_version,
        )
        if read_region(document) != body.strip():
            print(
                f"{args.doc} does not match {args.manifest}; regenerate it",
                file=sys.stderr,
            )
            return 1
        print(f"{args.doc} matches {args.manifest}")
        return 0

    args.doc.parent.mkdir(parents=True, exist_ok=True)
    args.doc.write_text(replace_region(document, body), encoding="utf-8")
    print(f"wrote {args.doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
