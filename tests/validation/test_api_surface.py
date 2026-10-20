"""Harness contract checks for the generated public API/CLI surface family."""

import json
import math
from pathlib import Path

import pytest

from tests.validation import api_surface
from tests.validation import integrated_extensions as extensions

ROOT = Path(__file__).resolve().parents[2]


def _native_available():
    try:
        from bionetgen.model import _cpp
    except Exception:
        return False
    return _cpp is not None


def test_check_identities_are_stable_and_unique():
    ids = api_surface.check_ids()
    assert len(ids) == len(set(ids))
    assert ids == api_surface.surface_check_ids() + api_surface.method_check_ids()
    assert all(item.startswith("api-surface:") for item in ids)


def test_the_family_covers_the_documented_public_surface():
    assert api_surface.SURFACE_CHECKS == (
        "signatures-defaults",
        "positional-dispatch",
        "timeouts",
        "actions",
        "results-files",
        "exceptions",
        "optional-imports",
        "intentional-incompatibilities",
    )
    assert api_surface.METHODS == ("ode", "ssa", "nf", "pla", "psa")
    for method in api_surface.METHODS:
        for leg in api_surface.METHOD_CHECKS:
            assert f"api-surface:methods:{method}:{leg}" in api_surface.check_ids()


def test_every_declared_incompatibility_is_an_explicit_statement():
    ids = [item["id"] for item in api_surface.INTENTIONAL_INCOMPATIBILITIES]
    assert len(ids) == len(set(ids))
    assert set(ids) == {
        "result-container",
        "table-columns",
        "method-dispatch",
        "timeout",
        "actions",
        "exceptions",
        "optional-imports",
        "none-defaults",
    }
    for item in api_surface.INTENTIONAL_INCOMPATIBILITIES:
        assert item["summary"].strip()
        assert isinstance(item["observation"], dict) and item["observation"]


def test_the_closed_form_law_agrees_with_the_exact_binomial_law():
    case = api_surface.model_cases()[0]
    probability = math.exp(-case["k"] * case["t_end"])
    assert api_surface.binomial_cdf(case["n0"], probability, case["n0"]) == 1.0
    assert api_surface.binomial_cdf(case["n0"], probability, -1) == 0.0
    low, high = api_surface.binomial_range(case["n0"], probability, 1e-6)
    assert 0 <= low <= high <= case["n0"]
    mean = float(api_surface.law_mean([case["t_end"]], case)[0])
    variance = float(api_surface.law_variance([case["t_end"]], case)[0])
    # The exact binomial mean and variance of the decay count law.
    assert mean == pytest.approx(case["n0"] * probability)
    assert variance == pytest.approx(case["n0"] * probability * (1.0 - probability))
    # The central range must contain the analytic mean.
    assert low < mean < high


def test_the_ensemble_budget_and_error_budget_are_declared():
    assert api_surface.ENSEMBLE_RUNS >= 8
    assert api_surface.ENSEMBLE_SEED_BASE > 0
    assert 0 < api_surface.ALPHA < 1
    assert api_surface.LAW_MEAN_SIGMAS > 0
    low, high = api_surface.LAW_VARIANCE_BAND
    assert 0 < low < 1 < high
    assert api_surface.OPTIONAL_DISTRIBUTIONS


def test_the_family_is_registered_in_the_existing_harness():
    assert "api-surface" in extensions.OPERATIONS
    assert extensions.check_ids("api-surface") == api_surface.check_ids()
    ids = extensions.expected_ids([])
    assert "campaign:api-surface" in ids
    assert set(api_surface.check_ids()).issubset(ids)
    assert len(ids) == len(set(ids))


def test_the_campaign_stage_imports_the_family_rows_and_links_issue_171(tmp_path):
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
                "detail": "generated public surface observation",
                "related_issues": [171],
                "evidence_kind": "supported-execution",
                "supported_execution": True,
            }
            for check_id in extensions.check_ids("api-surface")
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
    parent = extensions.invoke("api-surface", args, rows, {}, worker)

    assert parent["status"] == "PASS"
    assert parent["qualification"] == "api-surface"
    assert [row["id"] for row in rows[1:]] == extensions.check_ids("api-surface")
    assert all(row["related_issues"] == [171] for row in rows[1:])
    assert all(row["stage"] == "api-surface" for row in rows[1:])


def test_the_obligation_catalog_names_the_new_checks():
    catalog = json.loads(
        (ROOT / "provenance/issue-obligations.json").read_text(encoding="utf-8")
    )
    issue = next(item for item in catalog["issues"] if item["number"] == 171)
    named = {
        check["id"]
        for obligation in issue["obligations"]
        for check in obligation["required_checks"]
    }
    assert set(api_surface.check_ids()).issubset(named)
    for obligation in issue["obligations"]:
        for check in obligation["required_checks"]:
            assert not check["id"].startswith("qualification:"), obligation["id"]


@pytest.mark.slow
@pytest.mark.skipif(
    not _native_available(), reason="the native extension is not importable"
)
def test_the_generated_family_passes_end_to_end(tmp_path):
    rows = api_surface.run(tmp_path)
    assert [row["id"] for row in rows] == api_surface.check_ids()
    failures = [row["id"] for row in rows if row["status"] != "PASS"]
    assert not failures, [
        (row["id"], row["detail"], row.get("first_difference"))
        for row in rows
        if row["status"] != "PASS"
    ]
