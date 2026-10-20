"""Harness contract checks for the Atomizer reconstruction qualification."""

import json
from pathlib import Path

import pytest

from tests.validation import atomizer_reconstruction
from tests.validation import integrated_extensions as extensions

ROOT = Path(__file__).resolve().parents[2]


def test_check_identities_are_stable_and_unique():
    ids = atomizer_reconstruction.check_ids()
    assert len(ids) == len(set(ids))
    assert all(item.startswith("atomizer-reconstruction:") for item in ids)


def test_the_family_covers_every_named_feature():
    covered = set()
    for case in atomizer_reconstruction.cases():
        covered.update(case["features"])
    assert covered == set(atomizer_reconstruction.REQUIRED_FEATURES)


def test_the_family_generates_its_cases_rather_than_reading_fixtures():
    for case in atomizer_reconstruction.cases():
        assert case["source"].lstrip().startswith("<?xml")
        assert "<sbml" in case["source"]
        assert "<model" in case["source"]


def test_every_supported_case_has_an_independent_law():
    for case in atomizer_reconstruction.cases():
        if not case["representable"]:
            assert "law" not in case
            assert case["refusal_marker"]
            continue
        values = case["law"](atomizer_reconstruction.TIMES)
        assert set(values) >= set()
        for name, series in values.items():
            assert len(series) == len(atomizer_reconstruction.TIMES)
            assert min(series) >= -1e-9, name


def test_the_refusal_case_names_the_unrepresentable_construct():
    refusals = [
        case for case in atomizer_reconstruction.cases() if not case["representable"]
    ]
    assert refusals
    for case in refusals:
        assert case["refusal_category"]
        assert case["refusal_marker"] in case["source"] or case["refusal_marker"] in (
            "assignment rule targets species",
        )


def test_the_family_is_registered_in_the_existing_harness():
    assert "atomizer-reconstruction" in extensions.OPERATIONS
    assert (
        extensions.check_ids("atomizer-reconstruction")
        == atomizer_reconstruction.check_ids()
    )
    ids = extensions.expected_ids([])
    assert "campaign:atomizer-reconstruction" in ids
    assert set(atomizer_reconstruction.check_ids()).issubset(ids)
    assert len(ids) == len(set(ids))


def test_the_campaign_stage_imports_the_family_rows_and_links_issue_161(tmp_path):
    """The integrated report must carry the family's named rows."""

    import json
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
                "detail": "generated reconstruction observation",
                "related_issues": [161],
                "evidence_kind": "supported-execution",
                "supported_execution": True,
            }
            for check_id in extensions.check_ids("atomizer-reconstruction")
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
    parent = extensions.invoke("atomizer-reconstruction", args, rows, {}, worker)

    assert parent["status"] == "PASS"
    assert parent["qualification"] == "atomizer-reconstruction"
    assert [row["id"] for row in rows[1:]] == extensions.check_ids(
        "atomizer-reconstruction"
    )
    assert all(row["related_issues"] == [161] for row in rows[1:])
    assert all(row["stage"] == "atomizer-reconstruction" for row in rows[1:])


def test_the_obligation_catalog_names_the_new_checks():
    catalog = json.loads(
        (ROOT / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue = next(item for item in catalog["issues"] if item["number"] == 161)
    named = {
        check["id"]
        for obligation in issue["obligations"]
        for check in obligation["required_checks"]
    }
    assert set(atomizer_reconstruction.check_ids()).issubset(named)
    for obligation in issue["obligations"]:
        for check in obligation["required_checks"]:
            assert not check["id"].startswith("qualification:"), obligation["id"]


def test_the_comparison_rejects_a_disagreement():
    observed = [0.0, 1.0, 2.0]
    expected = [0.0, 1.0, 2.0]
    assert atomizer_reconstruction._difference(observed, expected, label="A") is None
    assert (
        atomizer_reconstruction._difference(observed, [0.0, 1.0, 3.0], label="A")
        is not None
    )


def test_a_law_that_leaves_the_admissible_region_is_refused():
    case = {
        "id": "inadmissible",
        "law": lambda t: {"A": -1.0 * t},
    }
    with pytest.raises(ValueError, match="not admissible"):
        atomizer_reconstruction._law_values(case)


@pytest.mark.slow
def test_the_generated_family_passes_end_to_end(tmp_path):
    rows = atomizer_reconstruction.run(tmp_path)
    assert [row["id"] for row in rows] == atomizer_reconstruction.check_ids()
    failures = [row["id"] for row in rows if row["status"] != "PASS"]
    assert not failures, [
        (row["id"], row["detail"], row.get("first_difference"))
        for row in rows
        if row["status"] != "PASS"
    ]
