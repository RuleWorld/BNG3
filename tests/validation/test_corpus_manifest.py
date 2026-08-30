"""Tests for the frozen validation-corpus selection."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.validation import corpus

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "provenance" / "corpus" / "selection.json"
VALIDATOR = REPO / "scripts" / "validate_corpus_manifest.py"
GENERATOR = REPO / "scripts" / "generate_corpus_manifest.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.smoke
def test_committed_selection_is_current_and_valid():
    generated = _run(GENERATOR, "--check")
    assert generated.returncode == 0, generated.stderr
    validated = _run(VALIDATOR)
    assert validated.returncode == 0, validated.stderr
    assert "100 model(s)" in validated.stdout


def test_harness_tiers_are_read_from_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert corpus.tier_s() == manifest["tiers"]["s"]
    assert corpus.tier_p() == manifest["tiers"]["p"]
    assert corpus.tier_nf() == manifest["tiers"]["nf"]
    assert corpus.tier_expr() == manifest["tiers"]["expr"]
    assert corpus.tier_x() == manifest["tiers"]["x"]
    assert corpus.tier_b() == manifest["tiers"]["b"]


def test_record_digests_match_selected_models():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for record in manifest["records"]:
        path = REPO / record["path"]
        actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == record["sha256"], record["id"]


def test_stale_manifest_is_rejected(tmp_path):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["records"][0]["sha256"] = "sha256:" + "0" * 64
    candidate = tmp_path / "selection.json"
    candidate.write_text(json.dumps(manifest), encoding="utf-8")
    result = _run(VALIDATOR, "--manifest", str(candidate))
    assert result.returncode == 1
    assert "does not match the model" in result.stderr
