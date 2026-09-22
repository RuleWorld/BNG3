"""Contracts for fail-closed SBML corpus classification."""

import importlib.util
from pathlib import Path


def _load_validator(name: str):
    path = Path(__file__).parents[2] / "scripts" / "ci" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sbml_test_suite_blocks_approximated_semantics_but_not_unit_notes():
    validator = _load_validator("validate_sbml_test_suite")
    warnings = [
        {
            "category": "stoichiometry",
            "message": "variable stoichiometry was fixed",
            "severity": "approximated",
        },
        {
            "category": "units",
            "message": "source numeric scale preserved",
            "severity": "info",
        },
    ]

    assert validator._simulation_limitations(warnings) == [
        "variable stoichiometry was fixed"
    ]


def test_curated_biomodel_gate_blocks_approximated_semantics():
    validator = _load_validator("validate_published_biomodels")
    warnings = [
        {
            "category": "fastReaction",
            "message": "fast equilibrium was approximated",
            "severity": "approximated",
        },
        {
            "category": "units",
            "message": "source numeric scale preserved",
            "severity": "info",
        },
    ]

    assert validator._simulation_limitations(warnings) == [
        "fast equilibrium was approximated"
    ]


def test_event_lowering_replaces_parser_only_event_warning():
    generated = {
        "category": "event",
        "message": "fixed-time event lowered",
        "severity": "info",
    }
    parser = {
        "category": "event",
        "message": "event was not executed",
        "severity": "dropped",
    }

    for name in ("validate_sbml_test_suite", "validate_published_biomodels"):
        validator = _load_validator(name)
        merged = validator._merge_generated_warnings([parser], [generated])
        assert merged == [generated]


def test_unsupported_summary_retains_exact_ids_and_causes():
    for name in ("validate_sbml_test_suite", "validate_published_biomodels"):
        validator = _load_validator(name)
        records = [
            {
                "id": "case-a",
                "status": "unsupported",
                "unsupported_reason": "event trigger and stoichiometry are unsupported",
            },
            {"id": "case-b", "status": "passed"},
        ]
        summary = validator._unsupported_summary(records)
        assert summary["record_count"] == 1
        assert summary["by_cause"]["events"]["ids"] == ["case-a"]
        assert summary["by_cause"]["stoichiometry"]["ids"] == ["case-a"]
        assert summary["by_cause"]["events"]["records"] == ["case-a"]
        assert records[0]["unsupported_causes"] == ["events", "stoichiometry"]
        assert records[0]["unsupported_subcauses"] == {
            "stoichiometry": ["unclassified_stoichiometry"]
        }
        assert summary["intersection_summary"]["cause_cardinality"] == {"2": 1}
        assert summary["intersection_summary"]["pairwise"]["events + stoichiometry"][
            "records"
        ] == ["case-a"]


def test_stoichiometry_summary_separates_dynamic_and_constant_boundaries():
    validator = _load_validator("validate_sbml_test_suite")
    records = [
        {
            "category": "semantic",
            "id": "dynamic",
            "status": "unsupported",
            "unsupported_reason": "variable stoichiometryMath was lowered",
        },
        {
            "category": "semantic",
            "id": "fractional",
            "status": "unsupported",
            "unsupported_reason": "unsupported stoichiometry 0.5",
        },
        {
            "category": "semantic",
            "id": "negative",
            "status": "unsupported",
            "unsupported_reason": "unsupported stoichiometry -1",
        },
    ]
    summary = validator._unsupported_summary(records)
    assert summary["stoichiometry_subsummary"]["by_subcause"] == {
        "constant_negative": {
            "count": 1,
            "records": ["semantic/negative"],
        },
        "constant_noninteger": {
            "count": 1,
            "records": ["semantic/fractional"],
        },
        "dynamic_or_stoichiometryMath": {
            "count": 1,
            "records": ["semantic/dynamic"],
        },
    }
    assert validator._stoichiometry_subcauses(
        "SBML contains non-integer reaction stoichiometry"
    ) == ["constant_noninteger"]
    assert validator._stoichiometry_subcauses(
        "stoichiometry above the BNGL expansion limit"
    ) == ["constant_integer_above_expansion_limit"]


def test_unsupported_summary_promotes_error_to_reason():
    validator = _load_validator("validate_sbml_test_suite")
    records = [
        {
            "category": "semantic",
            "id": "writer-error",
            "status": "unsupported",
            "error": "MathML writer rejected arcsin",
        }
    ]
    summary = validator._unsupported_summary(records)
    assert records[0]["unsupported_reason"] == "MathML writer rejected arcsin"
    assert summary["by_cause"]["mathml"]["records"] == ["semantic/writer-error"]
