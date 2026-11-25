"""Focused contract tests for #471/#180 PyBioNetGen (including py.cli.*) receipts."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ci import record_issue471_pybionetgen_receipts as mod

ROOT = Path(__file__).resolve().parents[5]


def test_pybionetgen_matrix_cli_patterns_cover_all_py_cli_rows():
    matrix = json.loads(
        (ROOT / "provenance/capability-matrix.yml").read_text(encoding="utf-8")
    )
    cli_rows = [
        row
        for row in matrix.get("rows", [])
        if str(row.get("id", "")).startswith("py.cli.")
    ]
    assert len(cli_rows) == 52
    for row in cli_rows:
        upstream = str(row.get("upstream", ""))
        matched = bool(
            mod.CLI_CMD_RE.match(upstream)
            or upstream == mod.CLI_OPTION_UPSTREAM
            or upstream == mod.ATOMIZER_OPTION_UPSTREAM
        )
        assert matched, (
            f"unrecognized py.cli upstream format: {row['id']} -> {upstream}"
        )
