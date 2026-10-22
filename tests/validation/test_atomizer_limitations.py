"""The Atomizer limitations document must not drift from the measurement.

The document is the scope record of BNG3's SBML Atomizer: what it refuses,
why, and whether the boundary is reducible.  It is generated from the
expectation manifest, so these tests keep it honest: a manifest that moves
must move the document, and a construct that appears in the manifest must
appear in the document.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import atomizer_limitations as generator

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "provenance" / "sbml-campaign" / "expectations.json"
NARRATIVE = REPO / "provenance" / "sbml-campaign" / "atomizer-limitations.json"
DOC = REPO / "docs" / "ATOMIZER_LIMITATIONS.md"


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _narrative() -> dict[str, Any]:
    return json.loads(NARRATIVE.read_text(encoding="utf-8"))


def _document() -> str:
    return DOC.read_text(encoding="utf-8")


def _render(manifest: dict[str, Any], narrative: dict[str, Any]) -> str:
    """Render the document exactly as the check does."""

    document = _document()
    return generator.render(
        manifest,
        narrative,
        generated_on=generator._document_generated_on(document),
        tool_version=generator._tool_version(),
    ).strip()


@pytest.mark.smoke
def test_the_committed_document_matches_the_committed_manifest():
    """The drift check itself: the document is current."""

    assert generator.read_region(_document()) == _render(_manifest(), _narrative())


@pytest.mark.smoke
def test_the_document_fails_the_check_when_the_manifest_moves():
    """A manifest that moves must move the document, or the check must fail."""

    manifest = _manifest()
    narrative = _narrative()
    identity = sorted(manifest["cases"])[0]
    entry = manifest["cases"][identity]
    entry["gap"] = {
        "conversion": {
            "construct": "events:untranslated",
            "causes": ["events"],
            "side": "atomizer",
        }
    }
    entry["conversion"] = "unsupported"

    drifted = _render(manifest, narrative)
    assert drifted != generator.read_region(_document())
    assert "events:untranslated" in drifted


@pytest.mark.smoke
def test_every_construct_in_the_manifest_appears_in_the_document():
    """A new limitation cannot appear without a line in the document."""

    manifest = _manifest()
    narrative = _narrative()
    document = generator.read_region(_document())
    constructs = narrative.get("constructs") or {}
    seen = set()
    for identity, entry in manifest["cases"].items():
        for gap in (entry.get("gap") or {}).values():
            construct = str(gap.get("construct"))
            seen.add(construct)
            assert (
                construct in constructs
            ), f"{construct} is in the manifest but has no narrative entry"
            assert f"`{construct}`" in document, construct
            assert constructs[construct].get("title"), construct
            assert constructs[construct].get("sbml_requires"), construct
            assert constructs[construct].get("citation"), construct
            assert constructs[construct].get("bng3_does"), construct
            assert constructs[construct].get("reducible"), construct
            assert constructs[construct].get("first_recorded"), construct
    assert seen


@pytest.mark.smoke
def test_the_harness_limits_are_kept_apart_from_the_atomizer_limitations():
    """A measurement limit must never be read as a limitation of the Atomizer."""

    document = generator.read_region(_document())
    harness_section = document.index("## The harness's measurement limits")
    atomizer_section = document.index("## The Atomizer's limitations")
    assert atomizer_section < harness_section
    harness_text = document[harness_section:]
    assert "**These are measurement limits, not limitations of the Atomizer.**" in (
        harness_text
    )
    # No harness-side construct may be described as an Atomizer limitation.
    manifest = _manifest()
    narrative = _narrative()
    for identity, entry in manifest["cases"].items():
        for gap in (entry.get("gap") or {}).values():
            if gap.get("side") != "harness":
                continue
            construct = str(gap.get("construct"))
            assert (
                f"`{construct}`" not in document[atomizer_section:harness_section]
            ), construct
            assert narrative["constructs"][construct].get("reducible"), construct


@pytest.mark.smoke
def test_historical_unknown_causes_have_specific_owners_without_verdict_changes():
    """Known MathML and comparator limits are not generic Atomizer gaps."""

    manifest = _manifest()
    infinity = manifest["cases"]["semantic/00950"]
    assert infinity["conversion"] == "unsupported"
    assert infinity["official_reference"] == "unsupported"
    assert infinity["gap"]["conversion"] == {
        "causes": ["mathml"],
        "construct": "mathml:infinity",
        "side": "atomizer",
    }

    nonfinite_parameter = manifest["cases"]["semantic/00951"]
    assert nonfinite_parameter["conversion"] == "unsupported"
    assert nonfinite_parameter["official_reference"] == "unsupported"
    assert nonfinite_parameter["gap"]["conversion"] == {
        "causes": ["mathml"],
        "construct": "mathml:non-finite-parameter-approximation",
        "side": "atomizer",
    }
    assert nonfinite_parameter["gap"]["official_reference"] == {
        "causes": ["mathml"],
        "construct": "mathml:non-finite-parameter-approximation",
        "side": "atomizer",
    }

    for identity in ("stochastic/00028", "stochastic/00032"):
        entry = manifest["cases"][identity]
        assert entry["conversion"] == "passed"
        assert entry["roundtrip_structure"] == "passed"
        assert entry["independent_comparison"] == "passed"
        assert entry["official_reference"] == "unsupported"
        assert entry["gap"]["official_reference"] == {
            "causes": ["events"],
            "construct": "harness:scheduled-action-phase-boundary",
            "side": "harness",
        }

    for identity in (
        "semantic/00950",
        "semantic/00951",
        "stochastic/00028",
        "stochastic/00032",
    ):
        assert all(
            "other" not in gap["causes"]
            for gap in manifest["cases"][identity].get("gap", {}).values()
        )


@pytest.mark.smoke
def test_a_closed_limitation_keeps_its_record():
    """A closed limitation moves to the resolved section; it does not vanish."""

    document = generator.read_region(_document())
    narrative = _narrative()
    resolved = document.index("## Resolved limitations")
    for construct, entry in (narrative.get("constructs") or {}).items():
        if entry.get("status") != "closed":
            continue
        assert f"`{construct}`" in document[resolved:], construct
        assert entry.get("closed"), construct
        assert entry.get("closed_by"), construct


@pytest.mark.smoke
def test_the_document_is_dated_and_names_its_measurement():
    document = generator.read_region(_document())
    manifest = _manifest()
    source_report = manifest.get("source_report") or {}
    assert "| Generated on |" in document
    assert source_report.get("bng3_commit", "") in document
    assert source_report.get("sha256", "") in document
    assert (manifest.get("suite") or {}).get("revision", "") in document
    # The three states the "how to read this" section has to distinguish.
    for state in ("passed", "failed", "unsupported"):
        assert f"| {state} |" in document
    assert "not a defect" in document


@pytest.mark.smoke
def test_the_check_command_fails_when_the_manifest_has_moved(tmp_path):
    """The drift check is exercised end to end, not only in memory."""

    manifest = _manifest()
    narrative = _narrative()
    identity = sorted(manifest["cases"])[0]
    manifest["cases"][identity]["gap"] = {
        "conversion": {
            "construct": "events:untranslated",
            "causes": ["events"],
            "side": "atomizer",
        }
    }
    manifest["cases"][identity]["conversion"] = "unsupported"

    manifest_path = tmp_path / "expectations.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    narrative_path = tmp_path / "atomizer-limitations.json"
    narrative_path.write_text(json.dumps(narrative), encoding="utf-8")
    document_path = tmp_path / "ATOMIZER_LIMITATIONS.md"
    document_path.write_text(_document(), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "ci" / "atomizer_limitations.py"),
            "--manifest",
            str(manifest_path),
            "--narrative",
            str(narrative_path),
            "--doc",
            str(document_path),
            "--check",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "does not match" in result.stderr


@pytest.mark.smoke
def test_the_document_is_linked_from_the_places_a_reader_looks():
    """A scope document nobody can find is the same as no document."""

    links = {
        "docs/index.md": "ATOMIZER_LIMITATIONS.md",
        "README.md": "docs/ATOMIZER_LIMITATIONS.md",
        "docs/CURRENT_PROGRESS.md": "ATOMIZER_LIMITATIONS.md",
        "docs/SBML_ATOMIZER_COVERAGE_CAMPAIGN.md": "ATOMIZER_LIMITATIONS.md",
    }
    for path, target in links.items():
        text = (REPO / path).read_text(encoding="utf-8")
        assert target in text, f"{path} does not link to {target}"
