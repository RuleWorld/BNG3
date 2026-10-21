"""The campaign document's result tables must come from a report, not by hand.

``docs/SBML_ATOMIZER_COVERAGE_CAMPAIGN.md`` carries its measured result in
three generated regions.  ``scripts/ci/sbml_campaign_tables.py`` renders those
regions from the harness reports and writes them into the marked regions of
the document, so a table cannot state a number the measured run does not
support.

These tests cover the *document* side of that contract: the document declares
the regions the generator writes into, and the generator's output is what the
document carries.  The generator itself is covered by its own tests.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
DOCUMENT = REPO_ROOT / "docs" / "SBML_ATOMIZER_COVERAGE_CAMPAIGN.md"
GENERATOR = REPO_ROOT / "scripts" / "ci" / "sbml_campaign_tables.py"


def _load_generator():
    if not GENERATOR.exists():
        pytest.skip("the campaign table generator is provided by a separate change")
    spec = importlib.util.spec_from_file_location("sbml_campaign_tables", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case(case_id: str, conversion: str, official: str) -> dict:
    """Build one harness record with the given stage verdicts."""

    return {
        "id": case_id,
        "category": "semantic",
        "status": conversion,
        "roundtrip_passed": conversion == "passed",
        "simulation_comparison": {"passed": conversion == "passed"},
        "official_conformance": {"status": official},
    }


def _report(cases: list[dict]) -> dict:
    return {"records": cases}


def _write(tmp_path: Path, name: str, report: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_campaign_document_declares_every_generated_region():
    generator = _load_generator()
    document = DOCUMENT.read_text(encoding="utf-8")

    for name in generator.REGIONS:
        assert f"<!-- BEGIN GENERATED: {name} -->" in document, name
        assert f"<!-- END GENERATED: {name} -->" in document, name


def test_generated_region_reports_the_numbers_of_its_report(tmp_path):
    generator = _load_generator()

    baseline_path = _write(
        tmp_path,
        "baseline.json",
        _report([_case("00001", "passed", "passed")]),
    )
    current_path = _write(
        tmp_path,
        "current.json",
        _report(
            [
                _case("00001", "passed", "passed"),
                _case("00002", "passed", "failed"),
                _case("00003", "unsupported", "unsupported"),
            ]
        ),
    )

    regions = generator.render(
        baseline_suite_report=baseline_path,
        suite_report=current_path,
        baseline_biomodels_report=None,
        biomodels_report=None,
        suite_dir=None,
        pytest_junit=None,
    )

    current_region = regions["sbml-campaign-current"]
    # The stage table states the report's own counts, not a hand-kept number.
    assert "| Conversion (SBML → BNGL) | 2 | 1 | 0 | 0 |" in current_region
    assert "| Official reference comparison | 1 | 1 | 1 | 0 |" in current_region
    # Every table states the report it came from, with its SHA-256.
    assert str(current_path) in current_region
    assert generator._digest(current_path) in current_region


def test_regenerating_a_region_replaces_exactly_that_region(tmp_path):
    generator = _load_generator()

    report_path = _write(
        tmp_path, "current.json", _report([_case("00001", "passed", "passed")])
    )
    regions = generator.render(
        baseline_suite_report=None,
        suite_report=report_path,
        baseline_biomodels_report=None,
        biomodels_report=None,
        suite_dir=None,
        pytest_junit=None,
    )

    document = "before\n"
    for name in generator.REGIONS:
        document += f"<!-- BEGIN GENERATED: {name} -->\nPLACEHOLDER-BLOCK\n"
        document += f"<!-- END GENERATED: {name} -->\n"

    rewritten = document
    for name, block in regions.items():
        rewritten = generator.replace_region(rewritten, name, block)

    assert "PLACEHOLDER-BLOCK" not in rewritten
    for name, block in regions.items():
        assert block.strip() in rewritten
    # The text outside the marked regions is untouched.
    assert rewritten.startswith("before\n")
