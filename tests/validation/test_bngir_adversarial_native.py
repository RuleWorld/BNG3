"""Executed only against the installed candidate in CI."""

from tests.validation import bngir_adversarial as adversarial


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
