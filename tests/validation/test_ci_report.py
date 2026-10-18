"""CI cannot hide known failure, missing evidence, or a different candidate."""

import pytest

from tests.validation.ci_report import main, publish


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


def test_summary_replay_includes_recorded_repository_cwd(tmp_path):
    d = report()
    d["investigation_tasks"][0]["reproduce_cwd"] = "/workspace/BNG3 source"
    assert publish(d, tmp_path / "summary", strict=False, revision="abc") == 0
    text = (tmp_path / "summary").read_text()
    assert "cd '/workspace/BNG3 source'" in text


def test_annotation_shows_actual_failure_before_traceback_context(tmp_path, capsys):
    d = report()
    d["results"][0]["detail"] = "irrelevant setup context " * 200
    d["results"][0]["failure_summary"] = "initial amount: expected 200, actual 100"
    publish(d, tmp_path / "summary", strict=True, revision="abc")
    output = capsys.readouterr().out
    assert "expected 200" in output
    assert "irrelevant setup" not in output


def test_retained_ssts_report_creates_issue_linked_triage_artifacts(tmp_path):
    source = tmp_path / "ssts.json"
    source.write_text(
        __import__("json").dumps(
            {
                "schema_version": 6,
                "source_provenance": {"bng3_commit": "candidate"},
                "suite_source_lock": {"revision": "suite-rev"},
                "runtime_provenance": {"native_extension_sha256": "native-hash"},
                "records": [
                    {
                        "id": "00001",
                        "category": "semantic",
                        "status": "failed",
                        "generated_network": {"species": 1, "reactions": 1},
                        "roundtrip_passed": True,
                        "official_conformance": {"status": "passed"},
                        "simulation_comparison": {
                            "passed": False,
                            "error": "observable A differs",
                        },
                    }
                ],
            }
        )
    )
    issues = tmp_path / "issues.json"
    issues.write_text(
        __import__("json").dumps(
            [{"number": 144, "title": "ODE lifecycle", "state": "OPEN"}]
        )
    )
    output = tmp_path / "triage"
    summary = tmp_path / "summary.md"

    assert (
        main(
            [
                str(source),
                "--input-format",
                "ssts",
                "--summary",
                str(summary),
                "--output-dir",
                str(output),
                "--issues-json",
                str(issues),
                "--revision",
                "candidate",
                "--strict",
            ]
        )
        == 1
    )

    report = __import__("json").loads((output / "report.json").read_text())
    simulation = next(
        r for r in report["results"] if r["stage"] == "cross-engine-simulation"
    )
    assert simulation["status"] == "FAIL"
    assert report["failure_clusters"]
    assert report["investigation_tasks"][0]["related_issues"]
    assert (output / "investigation-tasks.json").is_file()
    assert "#144" in summary.read_text()


def test_retained_report_revision_mismatch_fails_before_writing(tmp_path, capsys):
    source = tmp_path / "biomodels.json"
    source.write_text(
        __import__("json").dumps(
            {"schema_version": 4, "manifest": "manifest.json", "records": []}
        )
    )
    output = tmp_path / "triage"
    assert (
        main(
            [
                str(source),
                "--input-format",
                "biomodels",
                "--summary",
                str(tmp_path / "summary.md"),
                "--output-dir",
                str(output),
                "--revision",
                "candidate",
            ]
        )
        == 1
    )
    assert not output.exists()
    assert "revision" in capsys.readouterr().out.lower()


def test_retained_report_output_cannot_overwrite_input(tmp_path, capsys):
    source = tmp_path / "input.json"
    source.write_text(__import__("json").dumps({"records": []}))
    with pytest.raises(SystemExit):
        main(
            [
                str(source),
                "--input-format",
                "ssts",
                "--summary",
                str(tmp_path / "summary.md"),
                "--output-dir",
                str(source.parent),
            ]
        )
    assert __import__("json").loads(source.read_text()) == {"records": []}


@pytest.mark.parametrize("summary_target", ["input", "normalized"])
def test_retained_report_summary_cannot_corrupt_evidence(tmp_path, summary_target):
    source = tmp_path / "input.json"
    source.write_text('{"records": []}')
    output = tmp_path / "triage"
    summary = source if summary_target == "input" else output / "report.json"
    with pytest.raises(SystemExit):
        main(
            [
                str(source),
                "--input-format",
                "ssts",
                "--summary",
                str(summary),
                "--output-dir",
                str(output),
            ]
        )
    assert source.read_text() == '{"records": []}'


def test_retained_ssts_failure_packet_records_single_case_scientific_replay(tmp_path):
    source = tmp_path / "input.json"
    document = {
        "source_provenance": {"bng3_commit": "candidate"},
        "suite_dir": "/locked/suite",
        "simulation": {"t_end": 2.0, "n_steps": 4, "rtol": 1e-7, "atol": 1e-12},
        "records": [
            {
                "id": "00001",
                "category": "semantic",
                "status": "failed",
                "official_conformance": {"status": "failed", "reason": "A differs"},
            }
        ],
    }
    source.write_text(__import__("json").dumps(document))
    output = tmp_path / "triage"
    main(
        [
            str(source),
            "--input-format",
            "ssts",
            "--summary",
            str(tmp_path / "summary.md"),
            "--output-dir",
            str(output),
        ]
    )
    report = __import__("json").loads((output / "report.json").read_text())
    task = report["investigation_tasks"][0]
    assert "--only-case" in task["reproduce_command"]
    assert "semantic/00001" in task["reproduce_command"]
    assert "--simulation-t-end" in task["reproduce_command"]
    assert task["replay_status"] == "PREPARED_NOT_EXECUTED"
    assert (output / "input-report.json").read_bytes() == source.read_bytes()


def test_annotation_budget_prioritizes_failures_over_unsupported_boundaries(
    tmp_path, capsys
):
    document = report()
    document["results"] = [
        {"id": f"unsupported-{index}", "stage": "conversion", "status": "UNSUPPORTED"}
        for index in range(60)
    ] + [
        {
            "id": "actual-failure",
            "stage": "simulation",
            "status": "FAIL",
            "detail": "wrong dynamics",
        }
    ]
    publish(document, tmp_path / "summary")
    annotations = capsys.readouterr().out.splitlines()
    assert "actual-failure" in annotations[0]


def test_external_non_object_report_is_a_diagnostic_error(tmp_path):
    source = tmp_path / "input.json"
    source.write_text("[]")
    assert (
        main(
            [
                str(source),
                "--input-format",
                "ssts",
                "--summary",
                str(tmp_path / "summary"),
                "--output-dir",
                str(tmp_path / "triage"),
            ]
        )
        == 1
    )
