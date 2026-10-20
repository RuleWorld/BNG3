"""JAX backend measurement qualification (#174).

Issue #174 asks for representative speed and memory baselines on a fixed
revision, with independent semantic oracles, controlled A/A timing, the exact
environment and corpus, and retained no-win results.

``tests/validation/jax_backend_measurement.py`` measures that profile for the
JAX backend family on a fixed generated corpus. These tests keep the
measurement honest: the corpus must stay fixed, the independent closed-form
controls must hold, a wrong expectation must fail instead of passing quietly,
a noisy host must not produce a recorded timing, and a comparison that does
not show the candidate winning must be recorded as a no-win result.

The timings themselves are host-specific, so the tests assert the contract of
the measurement (which rows exist, what they may say, and when they are
refused) rather than a wall-clock number.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from tests.validation import campaign

jax = pytest.importorskip("jax")

from tests.validation import jax_backend_measurement as measurement  # noqa: E402

ISSUES = (174,)
REVISION = "a" * 40


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    directory = tmp_path_factory.mktemp("jax-backend-measurement")
    return measurement.run_worker(directory)


def _by_id(rows):
    return {row["id"]: row for row in rows}


def test_the_corpus_is_fixed_and_recorded():
    """The corpus must be the same generated cases on every run."""
    record = measurement.corpus_record()
    assert record["cases"], "the measurement needs a fixed corpus"
    assert measurement.corpus_digest() == measurement.corpus_digest()
    assert len(record["cases"]) == len(measurement.cases())
    for case in record["cases"]:
        assert (
            case["bngl_sha256"]
            == hashlib.sha256(measurement._source(case).encode()).hexdigest()
        )
        assert case["scan_rates"]
        assert case["species"]


def test_check_identities_are_stable_and_unique():
    ids = measurement.check_ids()
    assert len(ids) == len(set(ids))
    assert all(item.startswith("jax-backend-measurement:") for item in ids)
    assert "jax-backend-measurement:family:environment-record" in ids
    assert "jax-backend-measurement:family:jax-ssa-refusal" in ids
    for case in measurement.cases():
        assert f"jax-backend-measurement:{case['id']}:aa-control" in ids
        assert f"jax-backend-measurement:{case['id']}:correctness-control" in ids
        assert f"jax-backend-measurement:{case['id']}:ode-comparison" in ids


def test_every_named_check_reaches_an_observation(rows):
    assert {row["id"] for row in rows} == set(measurement.check_ids())
    for row in rows:
        assert row["status"] in campaign.STATUSES
        assert row["related_issues"] == list(ISSUES)
        assert row["detail"]
        if ":family:" in row["id"]:
            continue
        assert row["source_artifact"].endswith(".bngl")
        assert len(row["source_sha256"]) == 64


def test_the_independent_closed_form_controls_hold(rows):
    """The measured stages must reproduce the law of the case."""
    failures = [
        row
        for row in rows
        if row["id"].endswith(":correctness-control") and row["status"] != "PASS"
    ]
    assert not failures, json.dumps(failures, indent=2)


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


def test_a_noisy_host_does_not_produce_a_recorded_timing(rows):
    """The A/A control must decide whether a timing is a result."""
    for row in rows:
        if row["id"].endswith(":aa-control"):
            assert row["status"] in {"PASS", "FAIL"}, row
            if row["status"] == "FAIL":
                assert "host-noise observation" in row["detail"], row["detail"]
                assert "not recorded as results" in row["detail"], row["detail"]
            else:
                assert "A/A control measured the same arm" in row["detail"]


def test_the_environment_and_corpus_are_recorded_with_the_numbers(rows):
    row = _by_id(rows)["jax-backend-measurement:family:environment-record"]
    assert row["status"] == "PASS"
    assert "corpus " in row["detail"]
    assert "JAX " in row["detail"]
    assert "numbers are specific to this machine and revision" in row["detail"]


def test_the_no_win_result_is_recorded_as_measured(rows):
    """A comparison that does not win is a result, not a failure to hide."""
    for case in measurement.cases():
        row = _by_id(rows)[f"jax-backend-measurement:{case['id']}:ode-comparison"]
        assert row["status"] in {"PASS", "NOT_TESTED"}, row
        if row["status"] == "PASS":
            assert ("JAX-WIN" in row["detail"]) or ("NO-WIN" in row["detail"]), row
            assert "native/JAX ratio" in row["detail"], row
            if "NO-WIN" in row["detail"]:
                assert "not a failure to hide" in row["detail"], row


def test_the_jax_family_boundaries_are_recorded(rows):
    """The routes the JAX backend does not provide are explicit boundaries."""
    refusal = _by_id(rows)["jax-backend-measurement:family:jax-ssa-refusal"]
    assert refusal["status"] == "PASS"
    assert refusal["evidence_kind"] == "diagnostic-only"
    assert refusal["supported_execution"] is False
    route = _by_id(rows)["jax-backend-measurement:family:jax-public-api-route-absence"]
    assert route["status"] == "PASS"
    assert route["evidence_kind"] == "diagnostic-only"
    family = _by_id(rows)["jax-backend-measurement:family:jax-family-route-absence"]
    assert family["status"] == "PASS"
    assert "no NFsim or parameter-scan route" in family["detail"]


def _single_case(monkeypatch):
    """Limit the corpus to one case so a mutation run stays affordable."""
    original = measurement.cases
    monkeypatch.setattr(measurement, "cases", lambda: original()[:1])


def test_a_wrong_expectation_is_refused_instead_of_recorded(tmp_path, monkeypatch):
    """A wrong independent expectation must fail and void the timings."""
    original = measurement.case_law

    def broken(case, times):
        return original(case, times) * 1.5

    monkeypatch.setattr(measurement, "case_law", broken)
    _single_case(monkeypatch)
    broken_rows = _by_id(measurement.run_worker(tmp_path))
    control = broken_rows[
        "jax-backend-measurement:conversion-small:correctness-control"
    ]
    assert control["status"] == "FAIL"
    assert "closed-form control failed" in control["detail"]
    for case in measurement.cases():
        case_control = broken_rows[
            f"jax-backend-measurement:{case['id']}:correctness-control"
        ]
        assert case_control["status"] == "FAIL", case_control
        refused = 0
        for stage in measurement.LAW_CONTROLLED_STAGES:
            row = broken_rows[f"jax-backend-measurement:{case['id']}:{stage}-timing"]
            # No timing may be recorded as a result while the independent
            # expectation is wrong.
            assert row["status"] == "NOT_TESTED", row
            assert "correctness control failed" in row["detail"], row
            refused += 1
        assert refused, "the wrong expectation did not void any timing"


def test_a_noisy_measurement_is_not_recorded_as_a_result(tmp_path, monkeypatch):
    """When the A/A control fails, no timing is recorded as a result."""
    monkeypatch.setattr(measurement, "AA_RELATIVE_LIMIT", 0.0)
    monkeypatch.setattr(measurement, "AA_ABSOLUTE_LIMIT_SECONDS", 0.0)
    _single_case(monkeypatch)
    noisy_rows = _by_id(measurement.run_worker(tmp_path))
    control = noisy_rows["jax-backend-measurement:conversion-small:aa-control"]
    assert control["status"] == "FAIL"
    assert "host-noise observation" in control["detail"]
    for case in measurement.cases():
        for stage in measurement.TIMED_STAGES:
            row = noisy_rows[f"jax-backend-measurement:{case['id']}:{stage}-timing"]
            assert row["status"] == "NOT_TESTED", row
            assert "A/A control spread" in row["detail"], row


def test_the_campaign_import_emits_the_declared_identities(tmp_path, monkeypatch):
    """The campaign import must accept the rows the worker emits."""
    from argparse import Namespace

    from tests.validation import integrated_extensions as extensions

    _single_case(monkeypatch)
    monkeypatch.chdir(tmp_path)
    args = Namespace(report_dir=tmp_path, ensemble_runs=32)
    emitted = extensions.run_worker("jax-backend-measurement", args)
    assert [row["id"] for row in emitted] == extensions.check_ids(
        "jax-backend-measurement"
    )
    for row in emitted:
        assert row["check"] == row["id"].rsplit(":", 1)[-1]
        assert row["status"] in campaign.STATUSES
        assert isinstance(row["detail"], str) and row["detail"]
        assert row["related_issues"] and all(
            isinstance(number, int) and number >= 1 for number in row["related_issues"]
        )


def test_the_catalog_names_the_new_checks_for_issue_174(rows):
    """The #174 obligations must name the checks this family executes."""
    from tests.validation import issue_queue

    catalog = json.loads(
        (issue_queue.ROOT / "provenance/issue-obligations.json").read_text(
            encoding="utf-8"
        )
    )
    issue = next(row for row in catalog["issues"] if row["number"] == 174)
    named = {
        check["id"]
        for obligation in issue["obligations"]
        for check in obligation["required_checks"]
    }
    executed = {row["id"] for row in rows}
    assert executed <= named, sorted(executed - named)
    assert "jax-backend-measurement:conversion-small:aa-control" in named
    assert "jax-backend-measurement:conversion-small:correctness-control" in named
    assert "jax-backend-measurement:conversion-small:ode-comparison" in named
