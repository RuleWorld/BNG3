"""Deterministic PR selection over official SBML Test Suite metadata."""

import pytest

from scripts.ci import validate_sbml_test_suite as runner


def make_case(root, category, case_id, metadata):
    case_dir = root / "cases" / category / case_id
    case_dir.mkdir(parents=True)
    model = case_dir / f"{case_id}-model.m"
    model.write_text(f'(*\n{metadata}\n*)\nnewcase[ "{case_id}" ];\n')
    return {
        "category": category,
        "id": case_id,
        "version": "l3v2",
        "path": case_dir / f"{case_id}-sbml-l3v2.xml",
    }


def metadata(components, tests, test_type="TimeCourse", packages=""):
    lines = [
        f"componentTags: {components}",
        f"testTags: {tests}",
        f"testType: {test_type}",
    ]
    if packages:
        lines.append(f"packagesPresent: {packages}")
    return "\n".join(lines)


def test_feature_cover_is_stable_covers_tags_and_fills_budget(tmp_path):
    cases = [
        make_case(tmp_path, "semantic", "00003", metadata("Species", "Amount")),
        make_case(
            tmp_path,
            "semantic",
            "00001",
            metadata("Compartment, Species", "Amount, BoundaryCondition"),
        ),
        make_case(tmp_path, "semantic", "00002", metadata("Reaction", "Rate")),
    ]

    selected, report = runner._select_feature_cover(cases, budget=3)
    permuted, permuted_report = runner._select_feature_cover(
        [cases[2], cases[0], cases[1]], budget=3
    )

    selected_ids = [(case["category"], case["id"]) for case in selected]
    assert selected_ids == [(case["category"], case["id"]) for case in permuted]
    assert selected_ids == [
        ("semantic", "00001"),
        ("semantic", "00002"),
        ("semantic", "00003"),
    ]
    assert report == permuted_report
    assert len(selected) == min(3, len(cases))
    assert report["unselected_feature_classes"] == []
    assert {item["id"] for item in report["selected_case_features"]} == {
        "00001",
        "00002",
        "00003",
    }
    assert "component:Compartment" in report["selected_feature_classes"]
    assert "testType:TimeCourse" in report["selected_feature_classes"]


def test_feature_cover_selects_greedy_cover_then_stable_fill(tmp_path):
    cases = [
        make_case(tmp_path, "semantic", "00001", metadata("Species", "Amount")),
        make_case(tmp_path, "semantic", "00002", metadata("Species", "Amount")),
        make_case(
            tmp_path,
            "semantic",
            "00003",
            metadata("Reaction, Rule, Event", "Rate", "TimeCourse", "fbc"),
        ),
        make_case(
            tmp_path,
            "semantic",
            "00004",
            metadata("Compartment", "Trigger, Delay", packages="comp"),
        ),
    ]

    selected, report = runner._select_feature_cover(cases, budget=3)

    assert [(case["id"]) for case in selected] == ["00003", "00004", "00001"]
    assert report["unselected_feature_classes"] == []
    assert len(selected) == 3
    assert report["budget"] == 3


def test_feature_cover_reports_unselected_classes_under_hard_budget(tmp_path):
    cases = [
        make_case(tmp_path, "semantic", "00001", metadata("Species", "Amount")),
        make_case(tmp_path, "semantic", "00002", metadata("Event", "Trigger")),
        make_case(tmp_path, "semantic", "00003", metadata("Reaction", "Rate")),
    ]

    selected, report = runner._select_feature_cover(cases, budget=1)

    assert len(selected) == 1
    assert report["unselected_feature_classes"]
    assert set(report["selected_feature_classes"]).isdisjoint(
        report["unselected_feature_classes"]
    )


@pytest.mark.parametrize(
    "invalid_metadata",
    [
        "testTags: Amount\ntestType: TimeCourse",
        "componentTags: Species\ncomponentTags: Reaction\ntestTags: Amount\ntestType: TimeCourse",
        "componentTags: Species,, Reaction\ntestTags: Amount\ntestType: TimeCourse",
        "componentTags: \ntestTags: Amount\ntestType: TimeCourse",
    ],
    ids=["missing-field", "duplicate-field", "empty-token", "empty-required-field"],
)
def test_feature_cover_rejects_malformed_metadata_without_fallback(
    tmp_path, invalid_metadata
):
    case = make_case(tmp_path, "semantic", "00001", invalid_metadata)

    with pytest.raises(runner.SuiteSelectionError):
        runner._select_feature_cover([case], budget=1)


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_feature_cover_rejects_unbounded_or_invalid_budget(tmp_path, budget):
    case = make_case(tmp_path, "semantic", "00001", metadata("Species", "Amount"))

    with pytest.raises(runner.SuiteSelectionError):
        runner._select_feature_cover([case], budget=budget)


def test_feature_cover_rejects_empty_or_duplicate_inventory(tmp_path):
    case = make_case(tmp_path, "semantic", "00001", metadata("Species", "Amount"))

    with pytest.raises(runner.SuiteSelectionError):
        runner._select_feature_cover([], budget=1)
    with pytest.raises(runner.SuiteSelectionError):
        runner._select_feature_cover([case, case], budget=1)


def test_feature_cover_uses_optional_package_classes(tmp_path):
    case = make_case(
        tmp_path,
        "semantic",
        "00001",
        metadata("Species", "Amount", packages="fbc, comp"),
    )

    selected, report = runner._select_feature_cover([case], budget=1)

    assert len(selected) == 1
    assert {"package:fbc", "package:comp"} <= set(report["selected_feature_classes"])


def test_feature_cover_normalizes_duplicate_official_tags(tmp_path):
    case = make_case(
        tmp_path,
        "semantic",
        "00001",
        metadata("Species", "Amount, Amount"),
    )

    selected, report = runner._select_feature_cover([case], budget=1)

    assert len(selected) == 1
    assert report["selected_feature_classes"].count("test:Amount") == 1


def test_feature_cover_accepts_official_empty_test_tag_list(tmp_path):
    case = make_case(tmp_path, "semantic", "00001", metadata("Parameter", ""))

    selected, report = runner._select_feature_cover([case], budget=1)

    assert len(selected) == 1
    assert report["selected_feature_classes"] == [
        "component:Parameter",
        "testType:TimeCourse",
    ]
