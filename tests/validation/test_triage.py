"""Triage must never turn similar symptoms or missing evidence into known bugs."""

import copy
import json

import pytest

from tests.validation import triage


def report(status="FAIL", detail="expected 2, actual 3", run="one"):
    return {
        "source": {"revision": "a" * 40, "dirty": False},
        "configuration": {"seed": 7, "rtol": 1e-6},
        "subject": {"binary": "/engine", "sha256": "c" * 64},
        "references": {"oracle": {"revision": "b" * 40}},
        "inputs": {"fixture": "input-digest"},
        "generated_at": run,
        "results": [
            {
                "id": "case:rhs",
                "stage": "rhs",
                "check": "rhs",
                "status": status,
                "detail": detail,
                "related_issues": [143],
                "command": ["python", "check.py"],
            }
        ],
        "expected_contract_ids": ["case:rhs"],
    }


def test_changed_numeric_failure_is_never_silently_known():
    old = triage.analyze(report())
    current = triage.analyze(report(detail="expected 2, actual 4"), previous=old)
    assert current["findings"][0]["novelty"] == "CHANGED_FAILURE"
    assert current["findings"][0]["fingerprint"] != old["findings"][0]["fingerprint"]
    assert current["gate"] == "FAIL"


def test_paths_are_normalized_but_cases_and_contracts_stay_distinct(tmp_path):
    a = report(detail=f"bad artifact {tmp_path}/a.net; expected 2, actual 3")
    b = report(detail="bad artifact <REPORT>/a.net; expected 2, actual 3")
    assert (
        triage.analyze(a, report_root=tmp_path)["findings"][0]["fingerprint"]
        == triage.analyze(b)["findings"][0]["fingerprint"]
    )
    b["results"][0]["id"] = "other:rhs"
    b["expected_contract_ids"] = ["other:rhs"]
    assert (
        triage.analyze(b)["findings"][0]["fingerprint"]
        != triage.analyze(a, report_root=tmp_path)["findings"][0]["fingerprint"]
    )


def test_path_normalization_does_not_rewrite_a_longer_sibling_prefix(tmp_path):
    sibling = str(tmp_path) + "-archive/result.net"

    assert triage.normalize(sibling, tmp_path) == sibling


def test_regression_and_incompatible_history_are_separate():
    previous = triage.analyze(report("PASS"))
    assert (
        triage.analyze(report(), previous=previous)["findings"][0]["novelty"]
        == "REGRESSION"
    )
    changed = report()
    changed["configuration"]["rtol"] = 0.1
    current = triage.analyze(changed, previous=previous)
    assert current["history_comparable"] is False
    assert current["findings"][0]["novelty"] == "UNBASELINED"


def test_repeated_reports_need_same_revision_and_cannot_hide_first_failure():
    initial = report()
    repeated = report("PASS", run="two")
    current = triage.analyze(initial, replicates=[repeated])
    assert current["findings"][0]["reproduction"] == "NONDETERMINISTIC"
    assert current["gate"] == "FAIL"
    repeated["source"]["revision"] = "c" * 40
    with pytest.raises(ValueError, match="replicate"):
        triage.analyze(initial, replicates=[repeated])
    with pytest.raises(ValueError, match="duplicate.*report"):
        triage.analyze(initial, replicates=[initial])


def test_replicates_must_use_identical_candidate_artifact():
    initial = report()
    repeated = report(run="two")
    repeated["subject"]["sha256"] = "different-engine-digest"
    with pytest.raises(ValueError, match="replicate.*identity"):
        triage.analyze(initial, replicates=[repeated])


def test_per_case_reproduction_ignores_missing_unrelated_replicate_rows():
    initial = report()
    repeated = report(run="two")
    unrelated = report(run="three")
    unrelated["results"][0]["id"] = "other:rhs"
    unrelated["expected_contract_ids"] = ["other:rhs"]

    result = triage.analyze(initial, replicates=[repeated, unrelated])

    assert result["findings"][0]["reproduction"] == "REPRODUCED"
    assert len(result["findings"][0]["reproduction_evidence"]) == 2


def test_replicate_pass_remains_nondeterministic_even_with_two_matching_failures():
    initial = report()
    matching = report(run="two")
    passing = report("PASS", run="three")

    result = triage.analyze(initial, replicates=[matching, passing])

    assert result["findings"][0]["reproduction"] == "NONDETERMINISTIC"
    assert result["findings"][0]["repair_eligible"] is False


def test_unexecuted_and_diagnostic_controls_never_become_repair_tasks():
    value = report("NOT_TESTED")
    value["expected_contract_ids"].append("absent")
    result = triage.analyze(value)
    assert result["findings"] == []
    assert result["gate"] == "FAIL"
    assert result["evidence_errors"] == ["missing contract: absent"]
    assert result["observations"]["case:rhs"]["category"] == "EVIDENCE_GAP"
    value = report()
    value["results"][0]["evidence_kind"] = "diagnostic-only"
    finding = triage.analyze(value)["findings"][0]
    assert finding["category"] == "DIAGNOSTIC_CONTRACT_FAILURE"
    assert finding["repair_eligible"] is False


def test_known_baseline_requires_review_and_reproduction_evidence():
    value = report()
    first = triage.analyze(value, replicates=[report(run="two")])
    finding = first["findings"][0]
    baseline = {
        "schema_version": 1,
        "entries": [
            {
                "fingerprint": finding["fingerprint"],
                "comparison_key": first["comparison_key"],
                "case_id": "case:rhs",
                "issue": 143,
                "reviewed_by": "maintainer",
                "reason": "Independent oracle mismatch reproduced twice",
                "evidence": finding["reproduction_evidence"],
            }
        ],
    }
    assert triage.analyze(value, baseline=baseline)["findings"][0]["novelty"] == "KNOWN"
    assert triage.analyze(value, baseline=baseline)["gate"] == "PASS"
    broken = copy.deepcopy(baseline)
    broken["entries"][0]["evidence"] = []
    with pytest.raises(ValueError, match="reproduction"):
        triage.analyze(value, baseline=broken)
    changed = report(detail="expected 2, actual 4")
    assert triage.analyze(changed, baseline=baseline)["gate"] == "FAIL"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda evidence: evidence[0].update(report_sha256="not-a-sha256"),
        lambda evidence: evidence[1].update(source_revision="different-revision"),
        lambda evidence: evidence[1].update(comparison_key="different-config"),
    ],
)
def test_known_baseline_requires_well_formed_same_revision_and_configuration_evidence(
    mutate,
):
    value = report()
    result = triage.analyze(value, replicates=[report(run="two")])
    finding = result["findings"][0]
    baseline = {
        "schema_version": 1,
        "entries": [
            {
                "fingerprint": finding["fingerprint"],
                "comparison_key": result["comparison_key"],
                "case_id": "case:rhs",
                "issue": 143,
                "reviewed_by": "maintainer",
                "reason": "Independent oracle mismatch reproduced twice",
                "evidence": copy.deepcopy(finding["reproduction_evidence"]),
            }
        ],
    }
    mutate(baseline["entries"][0]["evidence"])

    with pytest.raises(ValueError, match="baseline|evidence"):
        triage.analyze(value, baseline=baseline)


def test_known_baseline_cannot_erase_a_historical_pass_regression():
    value = report()
    result = triage.analyze(value, replicates=[report(run="two")])
    finding = result["findings"][0]
    baseline = {
        "schema_version": 1,
        "entries": [
            {
                "fingerprint": finding["fingerprint"],
                "comparison_key": result["comparison_key"],
                "case_id": "case:rhs",
                "issue": 143,
                "reviewed_by": "maintainer",
                "reason": "Confirmed existing mismatch",
                "evidence": finding["reproduction_evidence"],
            }
        ],
    }

    current = triage.analyze(
        value, previous=triage.analyze(report("PASS")), baseline=baseline
    )

    assert current["findings"][0]["novelty"] == "REGRESSION"
    assert current["gate"] == "FAIL"


def test_known_failure_does_not_clear_an_unresolved_neighbor():
    value = report()
    repeated = report(run="two")
    result = triage.analyze(value, replicates=[repeated])
    finding = result["findings"][0]
    baseline = {
        "schema_version": 1,
        "entries": [
            {
                "fingerprint": finding["fingerprint"],
                "comparison_key": result["comparison_key"],
                "case_id": "case:rhs",
                "issue": 143,
                "reviewed_by": "maintainer",
                "reason": "Confirmed existing mismatch",
                "evidence": finding["reproduction_evidence"],
            }
        ],
    }
    value["results"].append(
        {
            "id": "neighbor:compatibility",
            "stage": "compatibility",
            "status": "UNSUPPORTED",
            "detail": "not covered by this baseline",
        }
    )

    current = triage.analyze(value, baseline=baseline)

    assert current["findings"][0]["novelty"] == "KNOWN"
    assert current["gate"] == "FAIL"


def test_packet_retains_inputs_prompt_hashes_and_missing_artifact_uncertainty(tmp_path):
    source = tmp_path / "evidence"
    source.mkdir()
    (source / "input.bngl").write_text("begin model\nend model\n")
    value = report()
    value["results"][0]["evidence"] = ["input.bngl", "absent.log"]
    value["results"][0]["source_locations"] = ["cpp/engine.cpp"]
    value["acceptance"] = {
        "obligations": [
            {
                "id": "issue-143.amount-preservation",
                "status": "FAIL",
                "required_checks": [
                    {
                        "id": "case:rhs",
                        "evidence_kind": "trajectory",
                        "expectation": "Match the independent source law.",
                        "identity_requirements": [
                            "source.revision",
                            "references.oracle.revision",
                        ],
                    },
                    {
                        "id": "consumer:reload",
                        "evidence_kind": "net-reload",
                        "expectation": "Consume the retained network.",
                        "identity_requirements": ["source.revision"],
                    },
                ],
                "checks": [
                    {
                        "id": "case:rhs",
                        "status": "FAIL",
                        "evidence_kind": "trajectory",
                        "expectation": "Match the independent source law.",
                        "identity_requirements": [
                            "source.revision",
                            "references.oracle.revision",
                        ],
                        "candidate_identity": {"revision": "a" * 40, "dirty": False},
                        "oracle_identities": {"oracle": {"revision": "b" * 40}},
                        "missing_evidence": [],
                        "observation": "expected 2, actual 3",
                        "first_observed_boundary": "rhs",
                    }
                ],
                "missing_evidence": ["consumer:reload"],
            }
        ]
    }
    path = source / "report.json"
    path.write_text(json.dumps(value))
    output = tmp_path / "packets"
    ledger = triage.write_bundle(path, output)
    task = ledger["findings"][0]["task_package"]
    packet = json.loads((output / task / "task.json").read_text())
    assert packet["source"]["dirty"] is False
    assert packet["confirmed_root_cause"] is None
    assert packet["affected_obligations"][0]["id"] == "issue-143.amount-preservation"
    assert packet["affected_obligations"][0]["missing_required_checks"] == [
        "consumer:reload"
    ]
    assert packet["affected_obligations"][0]["first_observed_boundary"] == "rhs"
    assert (
        packet["affected_obligations"][0]["retained_reproducer_status"]
        == "RETAINED_NOT_MINIMIZED"
    )
    assert packet["repair_eligible"] is False
    assert (
        packet["expected"]
        == "Pass the named contract case:rhs against its recorded oracle and configuration."
    )
    assert "absent.log" in packet["missing_evidence"]
    assert (output / task / "evidence/input.bngl").is_file()
    prompt = (output / task / "repair-prompt.md").read_text()
    assert "case:rhs" in prompt and "cpp/engine.cpp" in prompt
    assert "Do not change tolerances" in prompt
    assert (output / "coverage.json").is_file()
    assert json.loads((output / "coverage.json").read_text())[0]["number"] == 143
    assert (output / task / "manifest.json").is_file()


def test_diagnostic_refusal_failure_gets_investigation_packet_but_no_repair_task(
    tmp_path,
):
    value = report()
    value["results"][0].update(
        evidence_kind="diagnostic-only",
        supported_execution=False,
        detail="expected explicit refusal, received nominal success",
    )
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value))

    result = triage.write_bundle(path, tmp_path / "diagnostic-packet")

    finding = result["findings"][0]
    assert finding["task_package"]
    assert finding["category"] == "DIAGNOSTIC_CONTRACT_FAILURE"
    assert finding["repair_eligible"] is False
    assert (
        tmp_path / "diagnostic-packet" / finding["task_package"] / "task.json"
    ).is_file()


def test_duplicate_statuses_dirty_provenance_and_symlink_escape_fail_closed(tmp_path):
    value = report()
    value["results"].append(copy.deepcopy(value["results"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        triage.analyze(value)
    value = report()
    value["source"]["dirty"] = True
    assert triage.analyze(value)["findings"][0]["repair_eligible"] is False
    source = tmp_path / "source"
    source.mkdir()
    secret = tmp_path / "outside"
    secret.write_text("must not copy")
    (source / "escape").symlink_to(secret)
    value["results"][0]["evidence"] = ["escape"]
    path = source / "report.json"
    path.write_text(json.dumps(value))
    output = tmp_path / "out"
    result = triage.write_bundle(path, output)
    packet = json.loads(
        (output / result["findings"][0]["task_package"] / "task.json").read_text()
    )
    assert packet["missing_evidence"] == ["escape"]
    assert not list(output.rglob("escape"))


def test_artifact_collection_caps_file_count_and_report_size(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.txt").write_text("one")
    (source / "two.txt").write_text("two")
    value = report()
    value["results"][0]["evidence"] = ["one.txt", "two.txt"]
    path = source / "report.json"
    path.write_text(json.dumps(value))
    output = tmp_path / "bounded"

    result = triage.write_bundle(path, output, max_artifacts=1)

    packet_dir = output / result["findings"][0]["task_package"]
    packet = json.loads((packet_dir / "task.json").read_text())
    assert len(packet["retained_evidence"]) == 1
    assert packet["missing_evidence"] == ["two.txt"]
    with pytest.raises(ValueError, match="report exceeds"):
        triage.write_bundle(path, tmp_path / "too-large", max_report_bytes=1)


def test_task_package_count_is_bounded_and_omitted_cases_are_not_repair_eligible(
    tmp_path,
):
    value = report()
    second = copy.deepcopy(value["results"][0])
    second["id"] = "other:rhs"
    value["results"].append(second)
    value["expected_contract_ids"].append("other:rhs")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value))

    result = triage.write_bundle(path, tmp_path / "bounded", max_tasks=1)

    assert sum(bool(finding.get("task_package")) for finding in result["findings"]) == 1
    omitted = next(
        finding for finding in result["findings"] if not finding.get("task_package")
    )
    assert omitted["repair_eligible"] is False
    assert any("task package limit" in error for error in result["evidence_errors"])


def test_downloaded_artifact_root_is_explicit_and_retains_original_paths(tmp_path):
    source = tmp_path / "download"
    source.mkdir()
    (source / "input.bngl").write_text("begin model\nend model\n")
    receipt = {
        "command": ["engine", "input.bngl"],
        "artifacts": [
            {
                "path": "/ci/run/report/input.bngl",
                "sha256": __import__("hashlib")
                .sha256((source / "input.bngl").read_bytes())
                .hexdigest(),
            }
        ],
    }
    (source / "command.json").write_text(json.dumps(receipt))
    value = report()
    row = value["results"][0]
    row["evidence"] = ["/ci/run/report/input.bngl"]
    row["receipt"] = "/ci/run/report/command.json"
    path = source / "report.json"
    path.write_text(json.dumps(value))
    output = tmp_path / "packaged"
    ledger = triage.write_bundle(path, output, recorded_root="/ci/run/report")
    packet = json.loads(
        (output / ledger["findings"][0]["task_package"] / "task.json").read_text()
    )
    assert packet["recorded_commands"][0]["command"] == ["engine", "input.bngl"]
    assert packet["missing_evidence"] == []
    assert packet["evidence_relocation"]["recorded_root"] == "/ci/run/report"
    assert any(
        x["original"] == "/ci/run/report/input.bngl"
        for x in packet["retained_evidence"]
    )


def test_packet_detects_tampered_receipt_artifact(tmp_path):
    import hashlib

    original = b"original model"
    (tmp_path / "input.bngl").write_bytes(b"changed model")
    (tmp_path / "command.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "path": str(tmp_path / "input.bngl"),
                        "sha256": hashlib.sha256(original).hexdigest(),
                    }
                ]
            }
        )
    )
    value = report()
    value["results"][0]["receipt"] = str(tmp_path / "command.json")
    (tmp_path / "report.json").write_text(json.dumps(value))
    output = tmp_path / "out"
    ledger = triage.write_bundle(tmp_path / "report.json", output)
    packet = json.loads(
        (output / ledger["findings"][0]["task_package"] / "task.json").read_text()
    )
    assert packet["artifact_errors"][0]["reason"] == "recorded digest differs"
    assert packet["repair_eligible"] is False
    assert not list(output.rglob("input.bngl"))


def test_packet_retains_consumed_models_and_original_generated_source(tmp_path):
    case = tmp_path / "cases" / "generated"
    (case / "atomizer").mkdir(parents=True)
    (case / "source.xml").write_text("<sbml/>")
    (case / "atomizer/model.bngl").write_text("begin model\nend model\n")
    receipt = {"command": ["worker", "--input", str(case / "atomizer/model.bngl")]}
    (case / "command.json").write_text(json.dumps(receipt))
    value = report()
    value["results"][0].update(
        integration_case="generated", receipt=str(case / "command.json")
    )
    (tmp_path / "report.json").write_text(json.dumps(value))
    output = tmp_path / "out"
    ledger = triage.write_bundle(tmp_path / "report.json", output)
    directory = output / ledger["findings"][0]["task_package"]
    assert (directory / "evidence/cases/generated/atomizer/model.bngl").is_file()
    assert (directory / "evidence/cases/generated/source.xml").is_file()
