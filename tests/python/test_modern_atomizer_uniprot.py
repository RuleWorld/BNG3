"""Source-derived tests for the modern Atomizer UniProt service."""

from __future__ import annotations

import bionetgen.atomizer.modern.uniprot as uniprot
from bionetgen.atomizer.modern import (
    clear_uniprot_cache,
    fetch_uniprot_entry,
)


def test_fetch_uniprot_entry_parses_reference_fields(monkeypatch):
    sample = {
        "primaryAccession": "P12345",
        "proteinDescription": {"recommendedName": {"fullName": {"value": "Protein X"}}},
        "genes": [{"geneName": {"value": "GENEX"}}],
        "organism": {"scientificName": "Homo sapiens"},
        "comments": [
            {"type": "FUNCTION", "texts": [{"value": "Does X"}]},
            {
                "type": "SUBCELLULAR_LOCATION",
                "subcellularLocations": [
                    {"location": {"value": "Nucleus"}},
                    {"location": {"value": "Cytoplasm"}},
                ],
            },
        ],
        "keywords": [{"value": "Kinase"}],
    }

    def request_json(url, timeout):
        assert url.endswith("/uniprotkb/P12345.json")
        assert timeout > 0
        return True, sample

    monkeypatch.setattr(uniprot, "_request_json", request_json)
    clear_uniprot_cache()

    result = fetch_uniprot_entry("p12345")

    assert result is not None
    assert result.accession == "P12345"
    assert result.protein_name == "Protein X"
    assert result.gene_name == "GENEX"
    assert result.organism == "Homo sapiens"
    assert result.function == "Does X"
    assert result.subcellular_location == ["Nucleus", "Cytoplasm"]
    assert result.keywords == ["Kinase"]


def test_fetch_uniprot_entry_caches_failures_and_successes(monkeypatch):
    calls = []

    def request_json(url, timeout):
        calls.append(url)
        return False, None

    monkeypatch.setattr(uniprot, "_request_json", request_json)
    clear_uniprot_cache()

    assert fetch_uniprot_entry("NOPE") is None
    assert fetch_uniprot_entry("nope") is None
    assert len(calls) == 1

    clear_uniprot_cache()
    success_calls = []

    def successful_request(url, timeout):
        success_calls.append(url)
        return True, {"primaryAccession": "P11111"}

    monkeypatch.setattr(uniprot, "_request_json", successful_request)
    first = fetch_uniprot_entry("P11111")
    second = fetch_uniprot_entry("p11111")

    assert len(success_calls) == 1
    assert first == second
    assert first.accession == "P11111"
