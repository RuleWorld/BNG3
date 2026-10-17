"""Offline contracts for exact test references in upstream reconciliation."""

from pathlib import Path

import pytest

from scripts.validate_reconciliation_tests import (
    evidence_inventory,
    load_ledgers,
    resolve_test_reference,
    validate_test_references,
)


@pytest.mark.parametrize(
    ("relative_path", "node", "contents"),
    [
        (
            "tests/test_sample.py",
            "TestExample::test_behavior",
            "class TestExample:\n    def test_behavior(self): pass\n",
        ),
        (
            "tests/test_sample.cpp",
            "descriptive behavior",
            'TEST_CASE("descriptive behavior", "[tag]") {}\n',
        ),
        (
            "tests/CMakeLists.txt",
            "sample_target",
            "add_test(NAME sample_target COMMAND test_sample)\n",
        ),
    ],
)
def test_supported_test_reference_forms_resolve(
    tmp_path, relative_path, node, contents
):
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    assert resolve_test_reference(f"{relative_path}::{node}", tmp_path) is None


@pytest.mark.parametrize(
    ("relative_path", "node", "contents", "diagnostic"),
    [
        (
            "tests/test_sample.py",
            "test_missing",
            "def test_present(): pass\n",
            "Python test node does not exist",
        ),
        (
            "tests/test_sample.cpp",
            "missing behavior",
            'TEST_CASE("present", "[tag]") {}\n',
            "Catch2 test case does not exist",
        ),
        (
            "tests/CMakeLists.txt",
            "missing_target",
            "add_test(NAME present COMMAND test_sample)\n",
            "CTest target does not exist",
        ),
        (
            "tests/test_sample.py",
            "helper",
            "def helper(): pass\n",
            "Python test node does not exist",
        ),
        (
            "tests/test_sample.cpp",
            "commented behavior",
            '// TEST_CASE("commented behavior", "[tag]") {}\n',
            "Catch2 test case does not exist",
        ),
        (
            "tests/test_sample.cpp",
            "block commented behavior",
            '/* TEST_CASE("block commented behavior", "[tag]") {} */\n',
            "Catch2 test case does not exist",
        ),
        (
            "tests/CMakeLists.txt",
            "commented_target",
            "# add_test(NAME commented_target COMMAND test_sample)\n",
            "CTest target does not exist",
        ),
        (
            "tests/CMakeLists.txt",
            "quoted_target",
            'set(DOC "add_test(NAME quoted_target COMMAND fake)")\n',
            "CTest target does not exist",
        ),
        (
            "tests/test_sample.py",
            "test_present",
            "def test_present(): pass\n",
            "escapes the repository root",
        ),
    ],
)
def test_stale_or_escaping_test_references_are_rejected(
    tmp_path, relative_path, node, contents, diagnostic
):
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    reference = f"{relative_path}::{node}"
    if diagnostic == "escapes the repository root":
        reference = "../outside.py::test_present"
    assert diagnostic in resolve_test_reference(reference, tmp_path)


def test_absolute_path_inside_repository_is_rejected(tmp_path):
    path = tmp_path / "tests/test_sample.py"
    path.parent.mkdir(parents=True)
    path.write_text("def test_present(): pass\n", encoding="utf-8")
    assert "must be repository-relative" in resolve_test_reference(
        f"{path}::test_present", tmp_path
    )


def test_committed_reconciliation_test_refs_resolve_offline():
    ledgers = load_ledgers()
    assert {ledger["source"] for _, ledger in ledgers} == {
        "bionetgen",
        "nfsim",
        "pybionetgen",
    }
    assert validate_test_references(ledgers) == []


def test_inventory_reports_empty_claim_evidence_without_promoting_it():
    ledgers = [
        (
            Path("example.yml"),
            {
                "source": "example",
                "entries": [
                    {"classification": "incorporated-equivalently", "tests": []},
                    {"classification": "not-applicable", "tests": []},
                    {"classification": "superseded-by-bng3", "tests": ["x"]},
                ],
            },
        )
    ]
    assert evidence_inventory(ledgers) == {
        "example": {
            "claims": 2,
            "claims_with_test_refs": 1,
            "claims_without_test_refs": 1,
            "test_references": 1,
        }
    }
