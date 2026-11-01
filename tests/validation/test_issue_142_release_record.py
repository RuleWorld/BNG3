"""The Issue 142 closure consumer rejects incomplete or conflicting evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import record_issue142_release as record


def _write_junit(path: Path, *, test_name="target", properties=None, skipped=False):
    properties = properties or {"acceptance_check": "release-graph-identity"}
    if isinstance(properties, list):
        props = "".join(
            f'<property name="{name}" value="{value}" />' for name, value in properties
        )
    else:
        props = "".join(
            f'<property name="{name}" value="{value}" />'
            for name, value in properties.items()
        )
    skip = "<skipped />" if skipped else ""
    path.write_text(
        f'<testsuites><testsuite><testcase name="{test_name}">'
        f"<properties>{props}</properties>{skip}</testcase></testsuite></testsuites>"
    )


def test_check_junit_accepts_one_named_passing_check(tmp_path):
    path = tmp_path / "check.xml"
    _write_junit(
        path,
        properties={
            "acceptance_check": "release-graph-identity",
            "bng3_revision": "a" * 40,
        },
    )
    properties = record.read_check_junit(path, "target", "release-graph-identity")
    assert properties["bng3_revision"] == "a" * 40


def test_check_junit_rejects_missing_case(tmp_path):
    path = tmp_path / "check.xml"
    _write_junit(path, test_name="other")
    with pytest.raises(ValueError, match="expected exactly one JUnit case"):
        record.read_check_junit(path, "target", "release-graph-identity")


def test_check_junit_rejects_missing_or_conflicting_check_identity(tmp_path):
    path = tmp_path / "check.xml"
    _write_junit(path, properties={"acceptance_check": "release-graph-observables"})
    with pytest.raises(ValueError, match="does not identify"):
        record.read_check_junit(path, "target", "release-graph-identity")


def test_check_junit_rejects_skipped_case(tmp_path):
    path = tmp_path / "check.xml"
    _write_junit(path, skipped=True)
    with pytest.raises(ValueError, match="skipped"):
        record.read_check_junit(path, "target", "release-graph-identity")


def test_check_junit_rejects_conflicting_duplicate_properties(tmp_path):
    path = tmp_path / "check.xml"
    _write_junit(
        path,
        properties=[
            ("acceptance_check", "release-graph-identity"),
            ("source.revision", "a" * 40),
            ("source.revision", "b" * 40),
        ],
    )
    with pytest.raises(ValueError, match="conflicting JUnit property"):
        record.read_check_junit(path, "target", "release-graph-identity")


def test_source_identity_rejects_stale_or_dirty_results():
    with pytest.raises(ValueError, match="stale"):
        record._check_source_identity(
            {"source_revision": "a" * 40, "source_dirty": False},
            "b" * 40,
            "synthetic stale check",
        )
    with pytest.raises(ValueError, match="not recorded clean"):
        record._check_source_identity(
            {"source_revision": "b" * 40, "source_dirty": True},
            "b" * 40,
            "synthetic dirty check",
        )


def test_manifest_requires_all_three_named_release_checks(tmp_path):
    path = tmp_path / "provenance/issue-obligations.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "number": 142,
                        "obligations": [
                            {
                                "required_checks": [
                                    {
                                        "id": "release-graph-identity",
                                        "identity_requirements": ["source.revision"],
                                        "test_references": [
                                            "tests/validation/test_graph_identity_contract.py"
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="manifest is missing required checks"):
        record.verify_manifest(tmp_path)


def test_manifest_rejects_duplicate_release_check_definitions(tmp_path):
    path = tmp_path / "provenance/issue-obligations.json"
    path.parent.mkdir()
    checks = [
        {
            "id": check_id,
            "identity_requirements": ["source.revision"],
            "test_references": [reference],
        }
        for check_id, reference in (
            (
                "release-graph-identity",
                "tests/validation/test_graph_identity_contract.py",
            ),
            (
                "release-graph-observables",
                "tests/validation/test_nfsim_physical_unimolecular.py",
            ),
            ("release-obligation-142", "scripts/ci/record_issue142_release.py"),
        )
    ]
    path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "number": 142,
                        "obligations": [
                            {"required_checks": checks},
                            {"required_checks": [checks[0]]},
                        ],
                    }
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="conflicting manifest definition"):
        record.verify_manifest(tmp_path)
