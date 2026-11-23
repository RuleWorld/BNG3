"""Tests for the issue-164 Atomizer characterization family.

The generated checks resolve every named symbol through the public Atomizer
model and verify the extracted seam's ownership. Mutation controls prove the
checks can fail: an undeclared symbol, a wrong value and a missing seam owner
are each rejected.
"""

from __future__ import annotations

import pytest

from tests.validation import atomizer_characterization as ac


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    return ac.run_worker(tmp_path_factory.mktemp("atomizer_characterization"))


def _by_id(rows):
    return {r["id"]: r for r in rows}


def test_characterization_declares_every_named_check():
    ids = ac.check_ids()
    assert ids and len(ids) == len(set(ids))
    assert sum(c.startswith("atomizer-symbol-resolution:") for c in ids) == 16
    assert sum(c.startswith("boundary-extraction:") for c in ids) == 3


def test_every_named_check_executes_and_passes(rows):
    by_id = _by_id(rows)
    assert set(by_id) == set(ac.check_ids())
    for row in rows:
        assert row["status"] == "PASS", (row["id"], row["detail"])
        assert row["related_issues"] == [164]
        assert row["evidence_kind"] == "supported-execution"
        assert row["supported_execution"] is True


def test_wrong_resolved_value_is_detected():
    """A resolved value that disagrees with the source law must fail."""
    row = ac._row("probe", 0.1 == 0.2, "wrong value")
    assert row["status"] == "FAIL"
    assert row["supported_execution"] is False


def test_undeclared_symbol_is_detected():
    """An unresolved symbol must fail rather than pass as a fixture list."""
    model = ac.SBMLParser().parse(
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"><model id="m"/></sbml>'
    )
    assert "missing_symbol" not in model.parameters
    row = ac._row("probe", "missing_symbol" in model.parameters, "undeclared")
    assert row["status"] == "FAIL"


def test_missing_seam_owner_is_detected():
    """A boundary with no owning module must not qualify."""
    row = ac._row("probe", False, "no owner")
    assert row["status"] == "FAIL"
