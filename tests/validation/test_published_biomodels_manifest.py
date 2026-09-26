"""Unit checks for the complete curated BioModels validation manifest."""

from __future__ import annotations

import json
import sys
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


def test_curated_surface_gate_leaves_fixed_fractional_stoichiometry_to_writer():
    sys.path.insert(0, str(REPO / "scripts" / "ci"))
    from validate_published_biomodels import _sbml_surface_limitations

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model><listOfSpecies><species id="A"/><species id="B"/></listOfSpecies>
        <listOfReactions><reaction id="r">
          <listOfProducts>
            <speciesReference species="A" stoichiometry="0.5"/>
            <speciesReference species="A" stoichiometry="101"/>
            <speciesReference species="B">
              <stoichiometryMath><math xmlns="http://www.w3.org/1998/Math/MathML">
                <cn>0.5</cn>
              </math></stoichiometryMath>
            </speciesReference>
          </listOfProducts>
        </reaction></listOfReactions>
      </model>
    </sbml>"""

    _counts, limitations = _sbml_surface_limitations(xml)

    assert limitations == []
