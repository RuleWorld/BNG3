"""Bounded evidence must leave wider acceptance criteria untested."""

import json
import subprocess
import xml.etree.ElementTree as ET

import pytest

from scripts.ci import (
    record_issue161_release as multi,
    record_issue164_release as atomizer,
    record_issue178_release as shared,
)
from tests.validation import atomizer_characterization as characterization


@pytest.fixture
def revision():
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, cwd=multi.ROOT
    ).strip()


def test_issue161_lists_are_not_executed_coverage(tmp_path, monkeypatch, revision):
    junit = tmp_path / "multi.xml"
    suite = ET.Element("testsuite")
    for name in (
        "test_release_sbml_multi",
        "test_release_atomizer_structure",
        "test_release_capability_coverage_161",
    ):
        ET.SubElement(suite, "testcase", name=name)
    ET.ElementTree(suite).write(junit)
    output = tmp_path / "receipt.json"
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda argv, **kwargs: revision if "rev-parse" in argv else "",
    )
    multi.main(
        ["--junit", str(junit), "--source-revision", revision, "--output", str(output)]
    )
    rows = {row["id"]: row for row in json.loads(output.read_text())["results"]}
    assert all(rows[check]["status"] == "NOT_TESTED" for check in multi.CHECKS)
    assert all(not rows[check]["supported_execution"] for check in multi.CHECKS)


def test_issue161_refuses_mislabeled_checkout(tmp_path):
    output = tmp_path / "receipt.json"
    with pytest.raises(SystemExit, match="does not match checkout"):
        multi.main(
            [
                "--junit",
                str(tmp_path / "unused.xml"),
                "--source-revision",
                "0" * 40,
                "--output",
                str(output),
            ]
        )
    assert not output.exists()


def test_issue164_characterization_cannot_certify_corpora(
    tmp_path, monkeypatch, revision
):
    binary = tmp_path / "bng_cpp"
    binary.write_bytes(b"fixture")
    output = tmp_path / "receipt.json"
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda argv, **kwargs: revision if "rev-parse" in argv else "",
    )
    monkeypatch.setattr(
        characterization,
        "run_worker",
        lambda *_args, **_kwargs: [
            {"id": check, "status": "PASS"} for check in characterization.check_ids()
        ],
    )
    atomizer.main(
        [
            "--bng-cpp",
            str(binary),
            "--source-revision",
            revision,
            "--output",
            str(output),
        ]
    )
    rows = {row["id"]: row for row in json.loads(output.read_text())["results"]}
    assert all(
        rows[check]["status"] == "PASS" for check in characterization.check_ids()
    )
    assert all(rows[check]["status"] == "NOT_TESTED" for check in atomizer.LIVE_CHECKS)
    assert all(not rows[check]["supported_execution"] for check in atomizer.LIVE_CHECKS)


def test_issue178_single_owner_checks_cannot_certify_backend_parity(monkeypatch):
    monkeypatch.setattr(shared, "run_tests", lambda _root: None)
    receipt = shared.build_release_record(allow_dirty=True)
    assert {row["id"] for row in receipt["results"]} == set(shared.EXPECTED_CHECKS)
    assert all(row["status"] == "NOT_TESTED" for row in receipt["results"])
    assert all(not row["supported_execution"] for row in receipt["results"])
