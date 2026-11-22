"""Issue #149: settled NF default decision must stay synchronized in docs.

PR #832 promoted ``method="nf"`` to NFnext after the full corpus parity passed
(DECISIONS item 4). Active user-facing and reporting documents must not keep
claiming NFcore is the default. Historical plan/archive records are allowed to
keep their original statements, but must carry a status note when they do.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ACTIVE_DOCS = (
    "docs/migration_guide.md",
    "docs/CURRENT_PROGRESS.md",
    "docs/CAPABILITY_UNION_INVENTORY.md",
)
STALE_CLAIMS = (
    "NFcore remains the default",
    "NFcore remains the default NF backend",
    'NFcore remains method="nf" default',
)


def _active_default_claims():
    claims = []
    for rel in ACTIVE_DOCS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for stale in STALE_CLAIMS:
            if stale in text:
                claims.append(f"{rel}: {stale!r}")
        # The migration table must not label the NFcore row as the default.
        for line in text.splitlines():
            if line.startswith("| NFcore |") and "default for" in line:
                claims.append(f"{rel}: NFcore row labelled default")
    return claims


def test_active_docs_do_not_claim_nfcore_is_the_default():
    assert _active_default_claims() == []


def test_migration_guide_records_the_promotion_and_nfcore_selection():
    text = (ROOT / "docs" / "migration_guide.md").read_text(encoding="utf-8")
    assert 'method="nf"' in text
    assert 'The default for `method="nf"`' in text and "| NFnext |" in text
    assert 'method="nfcore"' in text
