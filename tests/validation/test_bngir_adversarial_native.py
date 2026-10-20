"""Executed only against the installed candidate in CI."""

import hashlib
import json

from tests.validation import bngir_adversarial as adversarial
from tests.validation import bngir_format_contracts as format_contracts
from tests.validation import bngir_reconstruction_contracts as reconstruction


def test_native_worker_consumes_independent_documents_and_analytic_controls(tmp_path):
    rows = adversarial.run_worker(tmp_path)
    assert [row["id"] for row in rows] == adversarial.check_ids()
    for case, row in zip(adversarial.CASES, rows):
        assert row["related_issues"] == adversarial.ISSUES
        if case["oracle"] == "unsupported":
            assert row["status"] == "UNSUPPORTED", row
        elif case["oracle"] == "accept-or-unsupported":
            assert row["status"] in {"PASS", "UNSUPPORTED"}, row
        else:
            assert row["status"] == "PASS", row
        if row["supported_execution"]:
            assert (tmp_path / f"{case['id']}.execution.json").is_file()


def test_native_bngir_export_equality_and_version_contracts(tmp_path):
    directory = tmp_path / "format-contracts"
    rows = format_contracts.run_worker(directory)
    assert [row["id"] for row in rows] == format_contracts.check_ids()
    assert [row["status"] for row in rows] == [
        "PASS",
        "PASS",
        "UNSUPPORTED",
        "PASS",
        "PASS",
        "PASS",
    ]
    assert "reproduces the frozen hand-reviewed v0.2 document" in rows[0]["detail"]
    assert "site-bearing v0.2 document" in rows[1]["detail"]
    assert "site-bearing molecule type" in rows[2]["detail"]
    for row in rows:
        assert row["related_issues"] == [155, 156]
        assert row["status"] in format_contracts.STATUSES
        artifact = directory / row["source_artifact"]
        assert artifact.is_file()
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == row["source_sha256"]
        assert row["first_difference"] is None or isinstance(
            row["first_difference"], dict
        )
    source = json.loads(
        (directory / "v02-site-free-version-bridge.json").read_text(encoding="utf-8")
    )
    assert source["format"] == "BNGIR"
    assert source["version"] == "0.2"


def test_native_bngir_export_contract_reports_a_perturbed_export_as_failure(
    tmp_path, monkeypatch
):
    import bionetgen

    original = bionetgen.to_bngir

    def perturbed(model, *args, **kwargs):
        document = json.loads(original(model, *args, **kwargs))
        document["model"]["metadata"]["name"] = "perturbed"
        return json.dumps(document)

    monkeypatch.setattr(bionetgen, "to_bngir", perturbed)
    rows = format_contracts.run_worker(tmp_path / "perturbed")
    assert rows[0]["status"] == "FAIL"
    assert rows[0]["first_difference"]["field"] == "document"
    assert (
        rows[0]["first_difference"]["expected"] != rows[0]["first_difference"]["actual"]
    )


def test_native_bngir_reconstruction_and_version_migration_contracts(tmp_path):
    directory = tmp_path / "reconstruction-contracts"
    rows = reconstruction.run_worker(directory)
    assert [row["id"] for row in rows] == reconstruction.check_ids()
    assert [row["status"] for row in rows] == [
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
    ]
    for row in rows:
        assert row["related_issues"] == [153, 154]
        assert row["supported_execution"] is True
        artifact = directory / row["source_artifact"]
        assert artifact.is_file()
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == row["source_sha256"]
    outcomes = json.loads(
        (directory / "v01-v02-feature-matrix.outcomes.json").read_text(encoding="utf-8")
    )
    assert {item["id"] for item in outcomes} == {
        cell["id"] for cell in reconstruction.MATRIX
    }
    assert all(
        item["outcome"] in {"PRESERVED", "UNSUPPORTED", "REJECTED_UNCLEAR", "LOST"}
        for item in outcomes
    ), outcomes
    for item in outcomes:
        assert item["owner"]
        assert (directory / item["evidence"]).is_file()
        if item["outcome"] in {"UNSUPPORTED", "REJECTED_UNCLEAR", "LOST"}:
            assert item["owner"] in reconstruction._catalog_owners(), item


def test_reconstruction_contract_reports_a_perturbed_document_as_failure(
    tmp_path, monkeypatch
):
    original = reconstruction.independent_document

    def perturbed():
        document = original()
        document["model"]["parameters"][0]["expression"]["value"] = 0.5
        return document

    monkeypatch.setattr(reconstruction, "independent_document", perturbed)
    rows = reconstruction.run_worker(tmp_path / "perturbed")
    assert rows[0]["status"] == "FAIL"
    assert rows[0]["first_difference"]["field"].startswith("rhs")


def test_version_matrix_contract_reports_a_silently_dropped_feature_as_failure(
    tmp_path, monkeypatch
):
    cells = [dict(cell) for cell in reconstruction.MATRIX]
    for cell in cells:
        if cell["id"] == "parameters":
            cell["present"] = lambda model: False
    monkeypatch.setattr(reconstruction, "MATRIX", cells)
    rows = reconstruction.run_worker(tmp_path / "dropped")
    matrix = next(row for row in rows if row["id"] == reconstruction._FEATURE_MATRIX)
    assert matrix["status"] == "FAIL"
    assert matrix["first_difference"]["cells"][0]["id"] == "parameters"


def test_version_matrix_fails_when_a_gap_is_not_recorded(tmp_path, monkeypatch):
    recorded = dict(reconstruction.KNOWN_GAPS)
    recorded.pop("rule-driving-work")
    monkeypatch.setattr(reconstruction, "KNOWN_GAPS", recorded)
    rows = reconstruction.run_worker(tmp_path / "unrecorded")
    matrix = next(row for row in rows if row["id"] == reconstruction._FEATURE_MATRIX)
    assert matrix["status"] == "FAIL"
    assert matrix["first_difference"]["cells"][0]["id"] == "rule-driving-work"


def test_version_matrix_fails_when_a_recorded_gap_no_longer_reproduces(
    tmp_path, monkeypatch
):
    cells = [dict(cell) for cell in reconstruction.MATRIX]
    for cell in cells:
        if cell["id"] == "rule-driving-work":
            cell["present"] = lambda model: True
    monkeypatch.setattr(reconstruction, "MATRIX", cells)
    rows = reconstruction.run_worker(tmp_path / "stale")
    matrix = next(row for row in rows if row["id"] == reconstruction._FEATURE_MATRIX)
    assert matrix["status"] == "FAIL"
    assert matrix["first_difference"]["cells"] == ["rule-driving-work"]


def test_refusal_ownership_fails_when_an_owner_is_not_in_the_catalog(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(reconstruction, "_catalog_owners", lambda: set(), raising=True)
    rows = reconstruction.run_worker(tmp_path / "unowned")
    ownership = next(
        row for row in rows if row["id"] == reconstruction._REFUSAL_OWNERSHIP
    )
    assert ownership["status"] == "FAIL"
    assert ownership["first_difference"]["cells"]
