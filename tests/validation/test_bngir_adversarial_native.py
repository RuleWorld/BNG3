"""Native contract checks; run only in the installed-candidate CI worker."""

from tests.validation import bngir_adversarial as adversarial


def test_native_worker_consumes_independent_documents_and_analytic_controls(tmp_path):
    rows = adversarial.run_worker(tmp_path)
    assert [row["id"] for row in rows] == adversarial.check_ids()
    assert all(row["related_issues"] == [153, 154, 155, 156] for row in rows)
    assert all(row["status"] == "PASS" for row in rows[:-1])
    controls = [row for row in rows if row["evidence_kind"] != "diagnostic-only"]
    diagnostics = [row for row in rows if row["evidence_kind"] == "diagnostic-only"]
    assert len(controls) == 4
    assert len(diagnostics) == len(rows) - len(controls)
    assert all(row["status"] == "PASS" for row in rows)
