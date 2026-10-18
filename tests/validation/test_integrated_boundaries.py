"""Pure contract tests for structured Atomizer boundary evidence."""

import pytest

from tests.validation import integrated_boundaries as boundaries


def _warning(category, severity, message):
    return {
        "kind": "import_warning",
        "category": category,
        "severity": severity,
        "message": message,
    }


def test_expected_ids_are_independent_and_cover_variants():
    ids = boundaries.expected_check_ids()
    assert len(ids) == len(set(ids)) == len(boundaries.CASES)
    assert {case[1] for case in boundaries.CASES} == {
        "event",
        "delay",
        "algebraic",
        "stoichiometry",
    }
    assert all(check_id.endswith(":unsupported-boundary-contract") for check_id in ids)


@pytest.mark.parametrize(
    "feature,warning",
    [
        (
            "event",
            _warning("event", "dropped", "state-dependent event remains untranslated"),
        ),
        (
            "delay",
            _warning("mathml", "unsupported", "delay history is not representable"),
        ),
        (
            "algebraic",
            _warning(
                "algebraicRule", "untranslated", "algebraic constraint is not applied"
            ),
        ),
        (
            "stoichiometry",
            _warning(
                "stoichiometry",
                "dropped",
                "fast-reaction semantics prevent deterministic flux lowering",
            ),
        ),
    ],
)
def test_only_matching_structured_loss_diagnostics_qualify(feature, warning):
    assert boundaries.classify_boundary_evidence(feature, [warning]) == [warning]


@pytest.mark.parametrize(
    "feature,diagnostics",
    [
        (
            "event",
            [_warning("event", "info", "state-dependent event remains untranslated")],
        ),
        (
            "event",
            [
                {
                    "kind": "log",
                    "category": "event",
                    "severity": "ERROR",
                    "message": "event rejected",
                }
            ],
        ),
        ("delay", [_warning("units", "dropped", "delay history is not representable")]),
        (
            "algebraic",
            [_warning("algebraicRule", "info", "algebraic constraint is not applied")],
        ),
        (
            "stoichiometry",
            [
                _warning(
                    "stoichiometry",
                    "info",
                    "fast-reaction semantics prevent deterministic flux lowering",
                )
            ],
        ),
    ],
)
def test_info_logs_wrong_categories_and_nonloss_severities_do_not_qualify(
    feature, diagnostics
):
    assert boundaries.classify_boundary_evidence(feature, diagnostics) == []


def test_rejection_diagnostic_qualifies_only_when_atomizer_failed():
    rejection = {
        "kind": "rejection",
        "category": "atomizer",
        "severity": "error",
        "message": "delay history cannot be translated",
    }
    assert boundaries.classify_boundary_evidence("delay", [rejection]) == []
    assert boundaries.classify_boundary_evidence(
        "delay", [rejection], result_success=False
    ) == [rejection]


def test_diagnostic_only_rows_cannot_be_counted_as_rejection_or_support():
    case = boundaries.CASES[0]
    row = boundaries._row(
        case,
        "PASS",
        "structured diagnostic found",
        explicit=True,
    )
    assert row["id"] in boundaries.expected_check_ids()
    assert row["check"] == "explicit-loss-diagnostic"
    assert row["expected_behavior"] == "explicit-loss-diagnostic"
    assert row["evidence_kind"] == "diagnostic-only"
    assert row["supported_execution"] is False
    assert row["labels"]["rejected_feature"] is False
    assert row["labels"]["boundary_diagnostic"] is True


def test_mapping_warnings_preserve_category_and_severity_for_classification():
    from types import SimpleNamespace

    warning = dict(
        category="stoichiometry",
        severity="dropped",
        message="fast reaction semantics prevent deterministic flux lowering",
    )
    rows = boundaries._diagnostics(
        SimpleNamespace(success=True),
        SimpleNamespace(model=SimpleNamespace(import_warnings=[warning])),
    )
    assert rows[0]["category"] == "stoichiometry"
    assert rows[0]["severity"] == "dropped"
    assert boundaries.classify_boundary_evidence("stoichiometry", rows) == rows
