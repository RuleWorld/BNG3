"""Network-rule execution contract qualification (#139).

The qualification compares the compile-owned rule contract, the legacy
network-rule path and an independent expectation. These tests keep the
comparison honest: the case matrix must stay inside the declared slice, the
generated check identities must be stable, and a wrong expectation must fail
instead of passing quietly.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.validation import netrule_execution as netrule
from tests.validation import campaign

ISSUES = (139,)


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    directory = tmp_path_factory.mktemp("netrule-execution")
    return netrule.run_worker(directory)


def test_generated_case_matrix_stays_inside_the_declared_slice():
    cases = netrule.cases()
    assert cases, "the qualification needs generated cases"
    aspects = {aspect for case in cases for aspect in case["aspects"]}
    assert aspects == {"graph", "rate", "filter", "local-scope", "reversible"}
    for case in cases:
        assert case["bngl"].count("begin reaction rules") == 1
        assert case["contract"]["reactants"]
        assert case["contract"]["products"]
        assert case["oracle"] in {"required", "unavailable"}
        if case["oracle"] == "unavailable":
            assert case.get("oracle_reason")


def test_check_identities_are_stable_and_unique():
    ids = netrule.check_ids()
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids, key=netrule.check_ids().index)
    assert all(item.startswith("netrule-execution:") for item in ids)
    assert "netrule-execution:local-scope:local-scope" in ids


def test_every_case_reaches_a_named_observation(rows):
    assert {row["id"] for row in rows} == set(netrule.check_ids())
    for row in rows:
        assert row["status"] in campaign.STATUSES
        assert row["related_issues"] == list(ISSUES)
        assert row["detail"]
        assert row["source_artifact"].endswith(".bngl")
        assert len(row["source_sha256"]) == 64


def test_contract_legacy_and_closed_form_agree(rows):
    failures = [row for row in rows if row["status"] != "PASS"]
    assert not failures, json.dumps(failures, indent=2)


def test_a_wrong_expectation_is_reported_as_a_difference(tmp_path, monkeypatch):
    """The comparison must fail when the independent expectation is wrong."""
    original_cases = netrule.cases

    def broken_cases():
        cases = []
        for case in original_cases():
            case = dict(case)
            if case["id"] == "conversion-r0":
                case["reactions"] = [(("A(s~0)",), ("B()",), 0.5)]
            cases.append(case)
        return cases

    monkeypatch.setattr(netrule, "cases", broken_cases)
    broken = netrule.run_worker(tmp_path)
    graph = next(
        row for row in broken if row["id"] == "netrule-execution:conversion-r0:graph"
    )
    assert graph["status"] == "FAIL"
    assert graph["first_difference"]["field"] == "legacy.reactions"


def test_a_wrong_oracle_is_reported_as_a_difference(tmp_path, monkeypatch):
    """The canonical oracle must be able to contradict the engine."""

    original = netrule._oracle_view

    def broken_oracle_view(network):
        view = original(network)
        if view is not None:
            view["reactions"] = [("other",), ("edge",), 0.0]
        return view

    monkeypatch.setattr(netrule, "_oracle_view", broken_oracle_view)
    broken = netrule.run_worker(tmp_path)
    graph = next(
        row for row in broken if row["id"] == "netrule-execution:conversion-r0:graph"
    )
    assert graph["status"] == "FAIL"
    assert graph["first_difference"]["field"] == "oracle.reactions"


def test_an_unrenderable_pattern_is_reported_as_unsupported(tmp_path, monkeypatch):
    """A case outside the declared slice is refused, not silently skipped."""

    def broken_render(pattern):
        raise netrule.UnsupportedSlice("bonded sites are outside the supported slice")

    monkeypatch.setattr(netrule, "_render_pattern", broken_render)
    broken = netrule.run_worker(tmp_path)
    graph = next(
        row for row in broken if row["id"] == "netrule-execution:conversion-r0:graph"
    )
    assert graph["status"] == "UNSUPPORTED"
    assert graph["supported_execution"] is False
    assert "supported slice" in graph["detail"]


def test_an_oracle_refusal_is_reported_as_unsupported(tmp_path, monkeypatch):
    """A required oracle that cannot express the case must not pass quietly."""

    def refusing_oracle(directory, case, source):
        return None, "the canonical Perl BNG2 refused the case: no diagnostic"

    monkeypatch.setattr(netrule, "_oracle_network", refusing_oracle)
    broken = netrule.run_worker(tmp_path)
    graph = next(
        row for row in broken if row["id"] == "netrule-execution:conversion-r0:graph"
    )
    assert graph["status"] == "UNSUPPORTED"
    assert graph["supported_execution"] is False
    assert "independent oracle" in graph["detail"]


def test_the_retained_artifact_names_a_source_model(rows):
    for row in rows:
        artifact = Path(row["source_artifact"]).name
        assert artifact.endswith(".bngl")


def test_the_extension_registry_emits_the_declared_identities(tmp_path, monkeypatch):
    """The campaign import must accept the rows the worker emits."""
    from argparse import Namespace

    from tests.validation import integrated_extensions as extensions

    monkeypatch.chdir(tmp_path)
    args = Namespace(report_dir=tmp_path, ensemble_runs=32)
    emitted = extensions.run_worker("netrule-execution", args)
    assert [row["id"] for row in emitted] == extensions.check_ids("netrule-execution")
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
