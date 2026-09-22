"""Unit checks for the complete curated BioModels validation manifest."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "provenance" / "published-biomodels.json"


def test_published_biomodel_manifest_is_pinned_and_well_formed():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["curation_query"] == "curationstatus:Manually curated"
    assert manifest["sbml_query"].endswith("modelformat:SBML")
    assert manifest["expected_total_records"] == 1096
    assert manifest["expected_sbml_records"] == 1075
    assert manifest["expected_non_sbml_records"] == 21
    assert "{id}" in manifest["record_api_url_template"]
    assert "{id}" in manifest["download_url_template"]
    assert "{filename}" in manifest["download_url_template"]
