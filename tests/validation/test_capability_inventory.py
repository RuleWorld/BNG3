"""Fault controls for the capability-union inventory check (#137).

The inventory records what the supported surfaces expose.  These tests
inject the faults that would make it meaningless: a capability without an
owner, without a support status, without an acceptance gate, with a gate
that names a check which does not exist, with an implicit exclusion, and a
surface that is not inventoried at all.
"""

from __future__ import annotations

import copy

from tests.validation import capability_inventory as inventory_check
from tests.validation import integrated_extensions as extensions


def _rows():
    return inventory_check.union_rows()


def _by_check(rows):
    return {row["check"]: row for row in rows}


def test_the_generated_inventory_carries_every_capability_union_row():
    rows = inventory_check.generated_inventory()
    union = [row for row in rows if row.get("kind") == "capability-union"]
    assert union
    assert len(union) == len(inventory_check.union_document()["capabilities"])
    for row in union:
        assert row["support"] in inventory_check.SUPPORT
        assert row["owner"]
        assert row["owner_assignment"]
        assert row["acceptance_gate"]
        assert "exclusions" in row


def test_every_supported_surface_is_inventoried():
    surfaces = {row["surface"] for row in _rows()}
    assert set(inventory_check.SURFACES) <= surfaces


def test_every_implementation_status_row_is_crosswalked():
    matrix = inventory_check.matrix_document()
    crosswalked = {
        row.get("matrix_row") for row in _rows() if row.get("matrix_row") is not None
    }
    assert {entry["id"] for entry in matrix["rows"]} <= crosswalked


def test_the_acceptance_gate_names_checks_that_exist():
    for row in _rows():
        executable, _decisions = inventory_check._gate_entries(row)
        assert executable or row["acceptance_gate"]
        for entry in executable:
            assert (inventory_check.ROOT / entry.split("::")[0]).exists()


def test_a_capability_without_an_owner_is_refused():
    union = copy.deepcopy(_rows())
    union[0]["owner"] = ""
    union[0]["owner_assignment"] = ""
    rows = _by_check(
        inventory_check.assess(
            union,
            *(
                inventory_check.union_document(),
                inventory_check.matrix_document(),
            ),
        )
    )
    assert rows["owner"]["status"] == "FAIL"
    assert union[0]["id"] in rows["owner"]["first_difference"]["missing_owner"]


def test_a_capability_without_a_support_status_is_refused():
    union = copy.deepcopy(_rows())
    union[0]["support"] = "probably-fine"
    rows = _by_check(
        inventory_check.assess(
            union,
            *(
                inventory_check.union_document(),
                inventory_check.matrix_document(),
            ),
        )
    )
    assert rows["support-status"]["status"] == "FAIL"


def test_a_gate_that_names_a_missing_check_is_refused():
    union = copy.deepcopy(_rows())
    union[0]["acceptance_gate"] = ["tests/validation/test_does_not_exist.py"]
    rows = _by_check(
        inventory_check.assess(
            union,
            *(
                inventory_check.union_document(),
                inventory_check.matrix_document(),
            ),
        )
    )
    assert rows["acceptance-gate"]["status"] == "FAIL"
    assert rows["acceptance-gate"]["broken_gates"]


def test_an_implicit_exclusion_is_refused():
    union = copy.deepcopy(_rows())
    partial = next(row for row in union if row["support"] != "implemented")
    partial["exclusions"] = []
    rows = _by_check(
        inventory_check.assess(
            union,
            *(
                inventory_check.union_document(),
                inventory_check.matrix_document(),
            ),
        )
    )
    assert rows["explicit-exclusions"]["status"] == "FAIL"
    assert (
        partial["id"]
        in rows["explicit-exclusions"]["first_difference"]["implicit_exclusions"]
    )


def test_a_surface_without_a_capability_is_refused():
    union = copy.deepcopy(_rows())
    union = [row for row in union if row["surface"] != "atomizer"]
    rows = _by_check(
        inventory_check.assess(
            union,
            *(
                inventory_check.union_document(),
                inventory_check.matrix_document(),
            ),
        )
    )
    assert rows["surface-coverage"]["status"] == "FAIL"
    assert (
        "atomizer" in rows["surface-coverage"]["first_difference"]["missing_surfaces"]
    )


def test_the_operation_is_registered_in_the_campaign_registry():
    assert "capability-inventory" in extensions.OPERATIONS
    assert extensions.check_ids("capability-inventory") == inventory_check.check_ids()
    assert set(inventory_check.check_ids()) <= set(extensions.expected_ids([]))
    for name in inventory_check.CHECKS:
        assert f"capability-inventory:{name}" in inventory_check.check_ids()
    assert (
        f"qualification:issue:137:{inventory_check.OBLIGATION_CHECK}"
        in inventory_check.check_ids()
    )
