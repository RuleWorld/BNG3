"""CI cannot hide known failure, missing evidence, or a different candidate."""

import pytest

from tests.validation.ci_report import publish


def report():
    return {
        "source": {"revision": "abc"},
        "results": [
            {
                "id": "m:network:rates",
                "stage": "network.reaction-rates",
                "status": "FAIL",
                "detail": "rate doubled",
            }
        ],
        "investigation_tasks": [
            {
                "case_id": "m:network:rates",
                "id": "packet",
                "source_locations": ["cpp/network.cpp"],
                "observation": "rate doubled",
                "reproduce_command": ["python", "scripts/validate.py", "--models", "m"],
                "acceptance_criteria": ["pass rates"],
            }
        ],
    }


def test_failed_contract_is_annotated_and_strict_check_is_red(tmp_path, capsys):
    assert publish(report(), tmp_path / "summary.md", strict=True, revision="abc") == 1
    output = capsys.readouterr().out
    assert "::error" in output
    assert "m%3Anetwork%3Arates" in output
    text = (tmp_path / "summary.md").read_text()
    assert "packet" in text and "rate doubled" in text and "--models" in text


def test_reporting_mode_preserves_failure_but_does_not_gate(tmp_path, capsys):
    assert publish(report(), tmp_path / "summary.md", strict=False, revision="abc") == 0
    assert "::warning" in capsys.readouterr().out
    assert "FAIL" in (tmp_path / "summary.md").read_text()


def test_wrong_revision_or_missing_results_cannot_pass(tmp_path):
    good = report()
    good["results"][0]["status"] = "PASS"
    assert publish(good, tmp_path / "a", strict=True, revision="other") == 1
    good["results"] = []
    assert publish(good, tmp_path / "b", strict=True, revision="abc") == 1


def test_unexpected_not_tested_is_red_but_explicit_inapplicability_is_reported(
    tmp_path,
):
    d = report()
    d["results"] = [
        {"id": "x", "stage": "gdat", "status": "NOT_TESTED", "detail": "skipped"}
    ]
    assert publish(d, tmp_path / "a", strict=True, revision="abc") == 1
    d["results"][0]["applicability"] = "no-observables"
    assert publish(d, tmp_path / "b", strict=True, revision="abc") == 0


def test_unknown_status_cannot_pass(tmp_path):
    d = report()
    d["results"][0]["status"] = "GREEN"
    assert publish(d, tmp_path / "a", strict=True, revision="abc") == 1


@pytest.mark.parametrize("status", ["UNSUPPORTED", "INVALID_INPUT"])
def test_unqualified_selected_case_cannot_make_diagnostic_check_green(tmp_path, status):
    d = report()
    d["results"][0]["status"] = status
    assert publish(d, tmp_path / "a", strict=True, revision="abc") == 1


def test_missing_or_duplicate_contract_cannot_silently_pass(tmp_path):
    d = report()
    d["results"][0]["status"] = "PASS"
    d["expected_contract_ids"] = ["m:network:rates", "m:gdat.values"]
    assert publish(d, tmp_path / "a", strict=True, revision="abc") == 1
    d["expected_contract_ids"] = ["m:network:rates"]
    d["results"] *= 2
    assert publish(d, tmp_path / "b", strict=True, revision="abc") == 1
