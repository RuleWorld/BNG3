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
            "tests/CMakeLists.txt",
            "bracket_commented_target",
            "#[[ add_test(NAME bracket_commented_target COMMAND fake) ]]\n",
            "CTest target does not exist",
        ),
        (
            "tests/CMakeLists.txt",
            "equal_bracket_commented_target",
            "#[=[ add_test(NAME equal_bracket_commented_target COMMAND fake) ]=]\n",
            "CTest target does not exist",
        ),
        (
            "tests/CMakeLists.txt",
            "bracket_quoted_target",
            "set(DOC [=[ add_test(NAME bracket_quoted_target COMMAND fake) ]=])\n",
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


def _git(checkout, *args):
    from subprocess import check_output

    return check_output(["git", "-C", str(checkout), *args], text=True).strip()


@pytest.fixture
def pinned_history(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Reconciliation test")
    _git(source, "config", "user.email", "reconciliation@example.invalid")
    _git(source, "commit", "--allow-empty", "-qm", "represented revision")
    represented = _git(source, "rev-parse", "HEAD")
    fixture = source / "fixture.txt"
    fixture.write_text("reference data\n", encoding="utf-8")
    _git(source, "add", "fixture.txt")
    _git(source, "commit", "-qm", "add canonical fixture")
    cutoff = _git(source, "rev-parse", "HEAD")
    return source, represented, cutoff


def test_upstream_history_detects_an_omitted_ledger_commit(pinned_history):
    from scripts.validate_reconciliation_tests import audit_upstream_history

    source, represented, cutoff = pinned_history
    ledger = {
        "represented_revision": represented,
        "cutoff_revision": cutoff,
        "entries": [],
    }
    report = audit_upstream_history(source, ledger, cutoff)
    assert report["missing_commits"] == [cutoff]
    assert report["errors"] == []
    ledger["entries"] = [{"source_revision": cutoff}]
    assert audit_upstream_history(source, ledger, cutoff)["missing_commits"] == []


def test_upstream_history_rejects_dirty_and_wrong_pins(pinned_history):
    from scripts.validate_reconciliation_tests import audit_upstream_history

    source, represented, cutoff = pinned_history
    ledger = {
        "represented_revision": represented,
        "cutoff_revision": cutoff,
        "entries": [{"source_revision": cutoff}],
    }
    report = audit_upstream_history(source, ledger, represented)
    assert "ledger cutoff does not match the accepted revision" in report["errors"]
    assert "checkout HEAD does not match the accepted revision" in report["errors"]
    (source / "fixture.txt").write_text("altered data\n", encoding="utf-8")
    report = audit_upstream_history(source, ledger, cutoff)
    assert "checkout has local changes" in report["errors"]


def test_upstream_history_detects_out_of_range_ledger_commit(pinned_history):
    from scripts.validate_reconciliation_tests import audit_upstream_history

    source, represented, cutoff = pinned_history
    ledger = {
        "represented_revision": represented,
        "cutoff_revision": cutoff,
        "entries": [{"source_revision": cutoff}, {"source_revision": represented}],
    }
    report = audit_upstream_history(source, ledger, cutoff)
    assert report["unexpected_commits"] == [represented]


def test_upstream_history_reads_fixture_bytes_despite_git_index_flags(pinned_history):
    import hashlib

    from scripts.validate_reconciliation_tests import audit_upstream_history

    source, represented, cutoff = pinned_history
    _git(source, "mv", "fixture.txt", "fixture.bngl")
    _git(source, "commit", "-qm", "rename canonical fixture")
    pin = _git(source, "rev-parse", "HEAD")
    ledger = {
        "represented_revision": represented,
        "cutoff_revision": pin,
        "entries": [{"source_revision": cutoff}, {"source_revision": pin}],
    }
    report = audit_upstream_history(source, ledger, pin)
    digest = hashlib.sha256(b"reference data\n").hexdigest()
    assert report["fixture_sha256"] == {"fixture.bngl": digest}
    _git(source, "update-index", "--assume-unchanged", "fixture.bngl")
    (source / "fixture.bngl").write_bytes(b"substitute data\n")
    assert _git(source, "status", "--porcelain") == ""
    assert "fixture differs from the accepted revision: fixture.bngl" in (
        audit_upstream_history(source, ledger, pin)["errors"]
    )


@pytest.mark.parametrize(
    "installed",
    [[], ["packaging; extra == 'dev'"], ["packaging>=24"]],
)
def test_packaging_is_a_default_installed_requirement(tmp_path, monkeypatch, installed):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts/ci"))
    from check_pybionetgen_compat import check_packaging_requirement

    (tmp_path / "setup.py").write_text(
        "setup(install_requires=['packaging'])\n", encoding="utf-8"
    )
    if installed == ["packaging>=24"]:
        check_packaging_requirement(tmp_path, installed)
    else:
        with pytest.raises(ValueError, match="BNG3 installed metadata"):
            check_packaging_requirement(tmp_path, installed)
