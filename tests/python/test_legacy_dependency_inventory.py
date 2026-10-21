"""The legacy compatibility-path dependency inventory is executable and honest.

Issue #172 asks for the imports and callers of the modelapi, legacy
network/parser/simulator and Cement paths to be traced and for a deliberate
compatibility adapter to be retained.  ``tools/check_legacy_dependency_inventory.py``
is the executable form of that trace: it walks the live source tree and fails
when the recorded inventory in
``provenance/architecture/legacy_dependency_inventory.json`` no longer matches
reality.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "tools" / "check_legacy_dependency_inventory.py"
INVENTORY = REPO / "provenance" / "architecture" / "legacy_dependency_inventory.json"

RETIRED_PATHS = ("network",)
RETAINED_PATHS = (
    "modelapi",
    "simulator",
    "cement",
    "compat-adapter",
    "legacy-network-rule-kernel",
)


def _inventory() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def _entry(key: str) -> dict:
    for entry in _inventory()["paths"]:
        if entry["key"] == key:
            return entry
    raise AssertionError(f"the inventory does not record the {key!r} path")


def test_dependency_inventory_check_passes_against_the_live_tree():
    result = subprocess.run(
        [sys.executable, str(CHECK)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "legacy dependency inventory check passed" in result.stdout


def test_dependency_inventory_check_fails_when_the_recorded_callers_drift(tmp_path):
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    inventory["paths"][0]["dependents"]["product"].append("bionetgen.fake_caller")
    perturbed = tmp_path / "legacy_dependency_inventory.json"
    perturbed.write_text(
        json.dumps(inventory, indent=2, sort_keys=True), encoding="utf-8"
    )

    result = subprocess.run(
        [sys.executable, str(CHECK), "--inventory", str(perturbed)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "drifted from the live tree" in result.stderr


def test_every_recorded_path_states_its_status_and_blocker():
    for entry in _inventory()["paths"]:
        assert entry["status"] in {"retired", "retained", "migration-target"}
        if entry["status"] == "retired":
            assert entry["blocker"] is None
        else:
            assert entry["blocker"], entry["key"]
        assert entry["qualified_checks"], entry["key"]


@pytest.mark.parametrize("key", RETAINED_PATHS)
def test_retained_paths_state_the_qualified_checks_that_cover_them(key):
    entry = _entry(key)

    assert entry["status"] in {"retained", "migration-target"}
    assert entry["qualified_checks"]
    assert entry["blocker"]


@pytest.mark.parametrize("key", RETIRED_PATHS)
def test_retired_paths_have_no_live_dependents(key):
    entry = _entry(key)

    assert entry["status"] == "retired"
    assert entry["dependents"]["product"] == []
    assert entry["dependents"]["tests"] == []


def test_the_modelapi_path_still_has_live_product_callers():
    entry = _entry("modelapi")

    assert "bionetgen" in entry["dependents"]["product"]
    assert "bionetgen.core.tools.cli" in entry["dependents"]["product"]


def test_the_cement_path_is_still_reached_through_the_modelapi_path():
    entry = _entry("cement")

    dependents = entry["dependents"]["product"]
    assert "bionetgen.modelapi.model" in dependents
    assert "bionetgen.modelapi.bngfile" in dependents


def test_the_legacy_network_rule_kernel_is_only_used_by_the_compile_owned_plan():
    entry = _entry("legacy-network-rule-kernel")

    assert entry["status"] == "retained"
    assert entry["dependents"]["product"] == ["cpp/engine/NetworkRulePlan.cpp"]


def test_the_retired_legacy_network_path_fails_with_an_explicit_diagnostic():
    # The retired reader must not disappear silently: importing it has to name
    # the missing module rather than fail somewhere inside the package.
    with pytest.raises(ModuleNotFoundError) as error:
        __import__("bionetgen.network.network")

    assert "bionetgen.network" in str(error.value)
