"""NFnext slice qualification (#147).

The qualification states the approved NFnext slice executably: every
candidate family carries a representation check, an executor check and an
independent reference, and a family outside the approved slice must be
refused by name instead of being approximated. These tests keep that honest:
the check identities must be stable, a wrong expectation must fail instead of
passing quietly, and a family that stops being refused must be reported.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.validation import campaign
from tests.validation import nfnext_slices as slices

ISSUES = (147,)


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    directory = tmp_path_factory.mktemp("nfnext-slices")
    return slices.run_worker(directory)


def test_the_approved_slice_is_stated():
    assert slices.SLICES.strip()
    assert slices.REFERENCE.strip()
    assert slices.ENSEMBLE_RUNS >= 32
    assert slices.SIGMA_BUDGET > 0


def test_every_candidate_family_carries_the_three_checks():
    families = slices.families()
    assert families
    identifiers = {family["id"] for family in families}
    assert identifiers == {
        "unary-site-state",
        "dynamic-rates",
        "filters",
        "modifiers",
        "compartments",
        "population-maps",
        "energy",
    }
    assert sum(1 for family in families if family["supported"]) == 1
    for family in families:
        assert family["bngl"].count("begin reaction rules") == 1
        assert family["keyword"]


def test_check_identities_are_stable_and_unique():
    ids = slices.check_ids()
    assert len(ids) == len(set(ids))
    assert all(item.startswith("nfnext-slices:") for item in ids)
    assert "nfnext-slices:unary-site-state:representation" in ids
    assert "nfnext-slices:energy:independent-reference" in ids


def test_every_family_reaches_a_named_observation(rows):
    assert {row["id"] for row in rows} == set(slices.check_ids())
    for row in rows:
        assert row["status"] in campaign.STATUSES
        assert row["related_issues"] == list(ISSUES)
        assert row["detail"]
        assert row["source_artifact"].endswith(".bngl")
        assert len(row["source_sha256"]) == 64


def test_the_slices_agree_with_their_declared_boundaries(rows):
    failures = [row for row in rows if row["status"] != "PASS"]
    assert not failures, json.dumps(failures, indent=2)


def test_a_refused_family_must_stay_refused(tmp_path, monkeypatch):
    """A family that stopped being refused must be reported, not accepted."""
    from bionetgen import _bionetgen_cpp as cpp

    original = cpp._nfnext_execute

    def permissive(model, sample_times, seed=0, max_events=1, max_particles=1):
        result = original(model, sample_times, seed, max_events, max_particles)
        if result.get("refused"):
            return {
                "refused": False,
                "columns": ["time"],
                "rows": [[0.0]],
                "event_count": 0,
            }
        return result

    monkeypatch.setattr(cpp, "_nfnext_execute", permissive)
    broken = slices.run_worker(tmp_path)
    refused = [row for row in broken if row["id"] == "nfnext-slices:energy:executor"]
    assert refused
    assert all(row["status"] == "FAIL" for row in refused)
    assert refused[0]["first_difference"]["field"] == "execution.refused"


def test_a_wrong_representation_expectation_is_reported_as_a_difference(
    tmp_path, monkeypatch
):
    """The representation comparison must be able to contradict the product."""
    original = slices.families

    def broken_families():
        families = []
        for family in original():
            family = dict(family)
            if family["id"] == "unary-site-state":
                family["rate"] = 0.25
            families.append(family)
        return families

    monkeypatch.setattr(slices, "families", broken_families)
    broken = slices.run_worker(tmp_path)
    row = next(
        item
        for item in broken
        if item["id"] == "nfnext-slices:unary-site-state:representation"
    )
    assert row["status"] == "FAIL"
    assert row["first_difference"]["field"] == "rule.rate"


def test_the_extension_registry_emits_the_declared_identities(tmp_path, monkeypatch):
    """The campaign import must accept the rows the worker emits."""
    from argparse import Namespace

    from tests.validation import integrated_extensions as extensions

    monkeypatch.chdir(tmp_path)
    args = Namespace(report_dir=tmp_path, ensemble_runs=32)
    emitted = extensions.run_worker("nfnext-slices", args)
    assert [row["id"] for row in emitted] == extensions.check_ids("nfnext-slices")
    for row in emitted:
        assert row["check"] == row["id"].rsplit(":", 1)[-1]
        assert row["status"] in campaign.STATUSES
        assert isinstance(row["detail"], str) and row["detail"]
        assert row["related_issues"] and all(
            isinstance(number, int) and number >= 1 for number in row["related_issues"]
        )
        artifact = tmp_path / row["source_artifact"]
        assert artifact.is_file()
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == row["source_sha256"]
