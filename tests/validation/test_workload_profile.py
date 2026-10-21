"""CPU work-plan reconciliation and workload profile (#176).

Issue #176 asks for the recorded plan to be reconciled with the CPU work that
is implemented and with the measured workload profiles, for the network-SSA
and network-free execution modes to be told apart, and for the retained
ensemble/isolation scope to be qualified with a fixed seed, a fixed run
budget and a stated statistical error control.

``tests/validation/workload_profile.py`` produces that evidence on a fixed
generated corpus. These tests keep it honest: the corpus must stay fixed,
every plan item must carry an explicit status, a wrong expectation must fail
instead of passing quietly, and a noisy host must not produce a recorded
timing.

The timings themselves are host-specific, so the tests assert the contract of
the measurement -- which rows exist, what they may say, and when they are
refused -- rather than a wall-clock number.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from tests.validation import campaign

from tests.validation import workload_profile as profile

ISSUES = (176,)


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    directory = tmp_path_factory.mktemp("workload-profile")
    return profile.run_worker(directory)


def _by_id(rows):
    return {row["id"]: row for row in rows}


def test_the_corpus_is_fixed_and_recorded():
    """The corpus must be the same generated cases on every run."""
    record = profile.corpus_record()
    assert record["cases"], "the profile needs a fixed corpus"
    assert profile.corpus_digest() == profile.corpus_digest()
    assert len(record["cases"]) == len(profile.cases())
    for case in record["cases"]:
        assert (
            case["bngl_sha256"]
            == hashlib.sha256(profile.case_source(case).encode()).hexdigest()
        )
        assert case["population"] > 0
    assert record["ensemble_runs"] >= 8
    assert record["seed_base"] > 0
    assert record["statistical_sigma"] > 0
    assert record["repetitions"] >= 3


def test_check_identities_are_stable_and_unique():
    ids = profile.check_ids()
    assert len(ids) == len(set(ids))
    assert all(item.startswith("workload-profile:") for item in ids)
    assert "workload-profile:family:environment-record" in ids
    assert "workload-profile:family:plan-reconciliation" in ids
    assert "workload-profile:family:execution-mode-distinction" in ids
    assert "workload-profile:family:ensemble-qualification" in ids
    assert "workload-profile:family:device-kernel-qualification" in ids
    for case in profile.cases():
        assert f"workload-profile:{case['id']}:aa-control" in ids
        assert f"workload-profile:{case['id']}:network-ssa-timing" in ids
        assert f"workload-profile:{case['id']}:network-free-timing" in ids
        assert f"workload-profile:{case['id']}:execution-mode-comparison" in ids


def test_every_named_check_reaches_an_observation(rows):
    assert {row["id"] for row in rows} == set(profile.check_ids())
    for row in rows:
        assert row["status"] in campaign.STATUSES
        assert row["related_issues"] == list(ISSUES)
        assert row["detail"]
        if ":family:" in row["id"]:
            continue
        assert row["source_artifact"].endswith(".bngl")
        assert len(row["source_sha256"]) == 64


def test_every_plan_item_carries_an_explicit_status(rows):
    """The reconciliation must name every item of the recorded plan."""
    row = _by_id(rows)["workload-profile:family:plan-reconciliation"]
    assert row["status"] == "PASS"
    for item in profile.PLAN_ITEMS:
        assert item["id"] in row["detail"], item["id"]
    assert "recorded plan" in row["detail"]
    assert "not as support" in row["detail"]


def test_the_plan_probe_reports_a_missing_mechanism_as_absent():
    """A plan item the build does not implement must be recorded as absent."""
    item = {
        "id": "probe",
        "track": "Track 0",
        "claim": "a harness that does not exist",
        "probe": "file",
        "target": "benchmark_nfsim_that_does_not_exist.py",
    }
    status, detail = profile._plan_probe(item)
    assert status == "ABSENT"
    assert "benchmark_nfsim_that_does_not_exist.py" in detail


def test_the_plan_probe_reports_a_present_mechanism(tmp_path):
    """A mechanism the build implements must be recorded as present."""
    item = {
        "id": "probe",
        "track": "Track 1",
        "claim": "a marker that exists",
        "probe": "source",
        "target": "cpp/nfsim/NFcore/moleculeType.cpp",
        "marker": "canSkipIndirectMembership",
    }
    status, detail = profile._plan_probe(item)
    assert status == "PRESENT"
    assert "canSkipIndirectMembership" in detail


def test_the_execution_modes_are_told_apart(rows):
    """The network-SSA and network-free surfaces must stay distinct."""
    row = _by_id(rows)["workload-profile:family:execution-mode-distinction"]
    assert row["status"] == "PASS"
    assert "batch_size" in row["detail"]
    assert "network-free" in row["detail"]


def test_the_ensemble_scope_is_pinned(rows):
    """The ensemble scope must name its seed, budget and error control."""
    row = _by_id(rows)["workload-profile:family:ensemble-qualification"]
    assert row["status"] == "PASS"
    assert str(profile.SEED_BASE) in row["detail"]
    assert str(profile.ENSEMBLE_RUNS) in row["detail"]
    assert f"{profile.STATISTICAL_SIGMA}-sigma" in row["detail"]
    assert "closed-form law" in row["detail"]
    assert "owns its own stream" in row["detail"]


def test_the_device_result_is_supplementary_and_names_its_device(rows):
    """A device result must name the device and stay supplementary."""
    row = _by_id(rows)["workload-profile:family:device-kernel-qualification"]
    assert row["status"] in {"PASS", "NOT_TESTED"}
    assert row["evidence_kind"] == "diagnostic-only"
    assert row["supported_execution"] is False
    assert "CPU-pinned contract remains the gated one" in row["detail"]


def test_the_environment_names_the_device_and_the_corpus(rows):
    """Every measurement records the device, the environment and the corpus."""
    row = _by_id(rows)["workload-profile:family:environment-record"]
    assert row["status"] == "PASS"
    assert "device:" in row["detail"]
    assert "accelerators:" in row["detail"]
    assert "corpus " in row["detail"]
    assert "specific to this machine and revision" in row["detail"]


def test_a_timing_is_never_recorded_as_a_failed_result(rows):
    """A measurement that cannot be interpreted is not a failure of the product."""
    for row in rows:
        if row["id"].endswith("-timing"):
            assert row["status"] in {"PASS", "NOT_TESTED"}, row
            if row["status"] == "NOT_TESTED":
                assert (
                    "correctness control failed" in row["detail"]
                    or "A/A control spread" in row["detail"]
                ), row["detail"]


def test_a_noisy_measurement_is_not_recorded_as_a_result(tmp_path, monkeypatch):
    """When the A/A control fails, no timing is recorded as a result."""
    monkeypatch.setattr(profile, "AA_RELATIVE_LIMIT", 0.0)
    monkeypatch.setattr(profile, "AA_ABSOLUTE_LIMIT_SECONDS", 0.0)
    noisy_rows = _by_id(profile.run_worker(tmp_path))
    for case in profile.cases():
        control = noisy_rows[f"workload-profile:{case['id']}:aa-control"]
        assert control["status"] == "FAIL"
        assert "host-noise observation" in control["detail"]
        for stage in profile.TIMED_STAGES:
            row = noisy_rows[f"workload-profile:{case['id']}:{stage}-timing"]
            assert row["status"] == "NOT_TESTED", row
            assert "A/A control spread" in row["detail"], row


def test_a_wrong_expectation_is_refused_instead_of_recorded(tmp_path, monkeypatch):
    """A wrong closed-form law must fail the ensemble control."""
    original = profile.case_law

    def broken(case, times):
        mean, variance = original(case, times)
        return mean * 1.5, variance

    monkeypatch.setattr(profile, "case_law", broken)
    broken_rows = _by_id(profile.run_worker(tmp_path))
    row = broken_rows["workload-profile:family:ensemble-qualification"]
    assert row["status"] == "FAIL"
    assert "closed-form law" in row["detail"]


def test_the_campaign_import_emits_the_declared_identities(tmp_path, monkeypatch):
    """The campaign import must accept the rows the worker emits."""
    from argparse import Namespace

    from tests.validation import integrated_extensions as extensions

    monkeypatch.chdir(tmp_path)
    args = Namespace(report_dir=tmp_path, ensemble_runs=32)
    emitted = extensions.run_worker("workload-profile", args)
    assert [row["id"] for row in emitted] == extensions.check_ids("workload-profile")
    for row in emitted:
        assert row["check"] == row["id"].rsplit(":", 1)[-1]
        assert row["status"] in campaign.STATUSES
        assert isinstance(row["detail"], str) and row["detail"]
        assert row["related_issues"] and all(
            isinstance(number, int) and number >= 1 for number in row["related_issues"]
        )


def test_the_catalog_names_the_new_checks_for_issue_176(rows):
    """The #176 obligations must name the checks this family executes."""
    from tests.validation import issue_queue

    catalog = json.loads(
        (issue_queue.ROOT / "provenance/issue-obligations.json").read_text(
            encoding="utf-8"
        )
    )
    issue = next(row for row in catalog["issues"] if row["number"] == 176)
    named = {
        check["id"]
        for obligation in issue["obligations"]
        for check in obligation["required_checks"]
    }
    executed = {row["id"] for row in rows}
    assert executed <= named, sorted(executed - named)
    assert "workload-profile:family:plan-reconciliation" in named
    assert "workload-profile:family:ensemble-qualification" in named
    assert "workload-profile:conversion:network-ssa-timing" in named
