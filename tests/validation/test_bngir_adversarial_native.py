"""Executed only against the installed candidate in CI."""

import hashlib
import json

from tests.validation import bngir_adversarial as adversarial
from tests.validation import bngir_format_contracts as format_contracts


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
        "UNSUPPORTED",
        "PASS",
        "PASS",
        "PASS",
    ]
    assert "reproduces the frozen hand-reviewed v0.2 document" in rows[0]["detail"]
    assert "site-bearing molecule type" in rows[1]["detail"]
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
