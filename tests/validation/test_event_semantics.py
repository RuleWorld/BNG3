"""Harness contract checks for the generated event semantics family."""

import json
import math
from pathlib import Path

import pytest

from tests.validation import event_semantics
from tests.validation import integrated_extensions as extensions

ROOT = Path(__file__).resolve().parents[2]


def _native_available():
    try:
        from bionetgen.model import _cpp
    except Exception:
        return False
    return _cpp is not None


def test_check_identities_are_stable_and_unique():
    ids = event_semantics.check_ids()
    assert len(ids) == len(set(ids))
    assert ids == (
        event_semantics.native_check_ids()
        + event_semantics.atomizer_check_ids()
        + event_semantics.stochastic_check_ids()
        + event_semantics.refusal_check_ids()
    )
    assert all(item.startswith("event-semantics:") for item in ids)


def test_the_family_covers_the_documented_event_surface():
    assert {case["id"] for case in event_semantics.NATIVE_CASES} == {
        "decay-reset",
        "initial-edge",
        "recurrence",
    }
    assert {case["id"] for case in event_semantics.ATOMIZER_CASES} == {
        "state-trigger",
        "parameter-update",
        "compartment-update",
        "initial-edge",
    }
    assert {case["id"] for case in event_semantics.STOCHASTIC_CASES} == {
        "time-trigger",
        "equal-priority",
    }
    for case in event_semantics.NATIVE_CASES:
        assert case["aspects"]
        assert case["firing"] in {"crossing", "initial", "recurrence"}
    for case in event_semantics.ATOMIZER_CASES:
        assert case["aspects"]
    for case in event_semantics.STOCHASTIC_CASES:
        assert case["aspects"]


def test_every_declared_refusal_names_its_own_diagnostic():
    ids = [item["id"] for item in event_semantics.REFUSALS]
    assert len(ids) == len(set(ids))
    for item in event_semantics.REFUSALS:
        assert item["message"].strip()
        assert item["route"] in {"native", "atomizer"}
    assert "native-parameter-target" in ids
    assert "native-stochastic" in ids
    assert "atomizer-stochastic-state-trigger" in ids


def test_the_closed_form_law_places_the_event_at_the_analytic_crossing():
    case = event_semantics.NATIVE_CASES[0]
    crossing = event_semantics.crossing_time(case)
    assert crossing == pytest.approx(math.log(2.0), rel=1e-12)
    # The state reaches the threshold exactly at the crossing.
    reached = case["a0"] * math.exp(-case["k"] * crossing)
    assert reached == pytest.approx(case["threshold"], rel=1e-12)
    firings = event_semantics.firing_times(case)
    assert firings == [crossing]
    # The closed form restarts from the assigned value at the firing.
    times = [crossing - 0.1, crossing, crossing + 0.1]
    law = event_semantics.reset_decay_law(times, case, firings)
    assert law[0] == pytest.approx(case["a0"] * math.exp(-case["k"] * times[0]))
    assert law[1] == pytest.approx(case["reset"], rel=1e-12)
    assert law[2] == pytest.approx(case["reset"] * math.exp(-case["k"] * 0.1))


def test_the_recurrence_case_fires_on_a_fixed_period():
    case = next(
        item for item in event_semantics.NATIVE_CASES if item["id"] == "recurrence"
    )
    period = event_semantics.crossing_time(case)
    firings = event_semantics.firing_times(case)
    assert firings == [period, 2 * period]
    assert firings[-1] <= case["t_end"]
    assert firings[-1] + period > case["t_end"]


def test_the_initial_edge_case_fires_at_the_start_of_the_run():
    case = next(
        item for item in event_semantics.NATIVE_CASES if item["id"] == "initial-edge"
    )
    assert event_semantics.firing_times(case) == [0.0]
    law = event_semantics.reset_decay_law([0.0, 1.0], case)
    assert law[0] == pytest.approx(case["reset"])
    assert law[1] == pytest.approx(case["reset"] * math.exp(-case["k"]))


def test_the_rate_change_law_switches_at_the_event():
    case = next(
        item
        for item in event_semantics.ATOMIZER_CASES
        if item["id"] == "parameter-update"
    )
    law = event_semantics.piecewise_rate_law([0.5, 1.0, 1.5], case)
    assert law[0] == pytest.approx(case["a0"] * math.exp(-case["k"] * 0.5))
    assert law[1] == pytest.approx(case["a0"] * math.exp(-case["k"]))
    assert law[2] == pytest.approx(
        case["a0"] * math.exp(-case["k"]) * math.exp(-case["k_new"] * 0.5)
    )


def test_the_exact_binomial_range_brackets_the_analytic_mean():
    population, probability = 60, math.exp(-1.0)
    low, high = event_semantics._binomial_range(population, probability, 1e-6)
    mean = population * probability
    assert low < mean < high
    assert event_semantics._binomial_cdf(population, probability, population) == 1.0
    assert event_semantics._binomial_cdf(population, probability, -1) == 0.0


def test_the_ensemble_budget_and_error_budget_are_declared():
    assert event_semantics.ENSEMBLE_RUNS >= 8
    assert event_semantics.ENSEMBLE_SEED_BASE > 0
    assert 0 < event_semantics.LAW_TAIL < 1
    assert event_semantics.LAW_MEAN_SIGMAS > 0
    low, high = event_semantics.LAW_VARIANCE_BAND
    assert 0 < low < 1 < high
    assert event_semantics.NATIVE_RTOL < event_semantics.ATOMIZER_RTOL
    assert event_semantics.NATIVE_EVENT_TIME_TOLERANCE < (
        event_semantics.ATOMIZER_EVENT_TIME_TOLERANCE
    )


def test_the_family_is_registered_in_the_existing_harness():
    assert "event-semantics" in extensions.OPERATIONS
    assert extensions.check_ids("event-semantics") == event_semantics.check_ids()
    assert extensions.FOCUS_FLAGS["event_semantics"] == "--event-semantics-only"
    ids = extensions.expected_ids([])
    assert "campaign:event-semantics" in ids
    assert set(event_semantics.check_ids()).issubset(ids)
    assert len(ids) == len(set(ids))


def test_the_campaign_stage_imports_the_family_rows_and_links_the_event_issues(
    tmp_path,
):
    """The integrated report must carry the family's named rows."""
    from argparse import Namespace

    rows = []

    def worker(case_id, operation, command, directory, results, **kwargs):
        directory.mkdir(parents=True)
        (directory / "identity.json").write_text("{}")
        checks = [
            {
                "id": check_id,
                "check": check_id.rsplit(":", 1)[-1],
                "status": "PASS",
                "detail": "generated event semantics observation",
                "related_issues": [157, 158],
                "evidence_kind": "supported-execution",
                "supported_execution": True,
            }
            for check_id in extensions.check_ids("event-semantics")
        ]
        (directory / "checks.json").write_text(json.dumps(checks))
        row = dict(
            id=f"{case_id}:{operation}",
            stage=operation,
            status="PASS",
            receipt="receipt",
        )
        results.append(row)
        return row

    args = Namespace(report_dir=tmp_path, nfsim_binary=Path("/native/NFsim"))
    parent = extensions.invoke("event-semantics", args, rows, {}, worker)

    assert parent["status"] == "PASS"
    assert parent["qualification"] == "event-semantics"
    assert [row["id"] for row in rows[1:]] == extensions.check_ids("event-semantics")
    assert all(row["related_issues"] == [157, 158] for row in rows[1:])
    assert all(row["stage"] == "event-semantics" for row in rows[1:])


def test_the_obligation_catalog_names_the_new_checks():
    catalog = json.loads(
        (ROOT / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    named = set()
    for issue in catalog["issues"]:
        if issue["number"] not in (157, 158):
            continue
        for obligation in issue["obligations"]:
            for check in obligation["required_checks"]:
                named.add(check["id"])
    assert set(event_semantics.check_ids()).issubset(named)
    for issue in catalog["issues"]:
        if issue["number"] not in (157, 158):
            continue
        for obligation in issue["obligations"]:
            for check in obligation["required_checks"]:
                assert not check["id"].startswith("qualification:"), obligation["id"]


@pytest.mark.slow
@pytest.mark.skipif(
    not _native_available(), reason="the native extension is not importable"
)
def test_the_generated_family_passes_end_to_end(tmp_path):
    rows = event_semantics.run(tmp_path)
    assert [row["id"] for row in rows] == event_semantics.check_ids()
    failures = [row["id"] for row in rows if row["status"] != "PASS"]
    assert not failures, [
        (row["id"], row["detail"], row.get("first_difference"))
        for row in rows
        if row["status"] != "PASS"
    ]
