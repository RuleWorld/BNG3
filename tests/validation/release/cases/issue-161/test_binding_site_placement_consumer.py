"""Audit evidence: retained binding-site placement has a release consumer.

``MultiParseResult.binding_site_placements`` is not dead representation state:
``test_sbml_multi_release.validate_multi_feature_row`` consumes it for the
``sbml.multi.SpeciesTypeInstance.compartmentReference`` row, and
``test_compartment_reference_structure`` uses it to distinguish two libSBML-valid
sources that lower to byte-identical BNGL. This module proves the row consumer
is load-bearing by removing the retained placement in a negative control. No
product code or expectation is changed here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import test_sbml_multi_release as release
from bionetgen.atomizer.modern import parse_multi_package as real_parse_multi_package

ROW = "sbml.multi.SpeciesTypeInstance.compartmentReference"
EXPECTED_PLACEMENT = {"reference": "inside", "compartment": "c2"}


def test_release_row_consumes_retained_placement(tmp_path: Path):
    result = release.validate_multi_feature_row(ROW, tmp_path)
    assert result["status"] == "PASS"
    assert result["libsbml_valid"] is True
    parsed = real_parse_multi_package(release.MULTI_COMP_INSTANCE_XML)
    assert parsed.binding_site_placements["AType"]["x"] == EXPECTED_PLACEMENT


def test_release_row_fails_closed_when_placement_is_dropped(tmp_path, monkeypatch):
    def without_placement(xml):
        parsed = real_parse_multi_package(xml)
        parsed.binding_site_placements = {}
        return parsed

    monkeypatch.setattr(release, "parse_multi_package", without_placement)
    with pytest.raises(AssertionError) as caught:
        release.validate_multi_feature_row(ROW, tmp_path)
    assert "c2" in str(caught.value)
