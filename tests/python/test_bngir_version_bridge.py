"""Version-bridge contract for frozen BNGIR v0.1 and v0.2 fixtures."""

import json
from pathlib import Path

import jsonschema

import bionetgen

from _extdep import require_extension

require_extension()


ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "bngir"
LEGACY_FIXTURE = FIXTURES / "v0.1-version-bridge.json"
STRUCTURAL_FIXTURE = FIXTURES / "v0.2-version-bridge.json"


def _schema(version):
    path = ROOT / "provenance" / "schemas" / f"bngir-{version}.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _state_value(pattern):
    return pattern["molecules"][0]["sites"][0]["state"]["value"]


def _assert_hand_reviewed_semantics(document):
    model = document["model"]
    assert model["metadata"]["name"] == "bngir_version_bridge"
    assert model["parameters"] == [
        {
            "constant_value": 0.1,
            "expression": {"kind": "number", "value": 0.1},
            "id": 0,
            "name": "k",
        }
    ]
    assert model["molecule_types"][0]["components"] == [
        {"index": 0, "name": "x", "states": ["u", "p"]}
    ]
    assert model["seeds"][0]["amount"] == {"kind": "number", "value": 10.0}
    assert model["seeds"][0]["pattern"]["molecules"][0]["type"] == "A"
    assert _state_value(model["seeds"][0]["pattern"]) == "u"

    rule = model["rules"][0]
    assert rule["label"] == "convert:"
    assert rule["forward"]["rate"] == {
        "expression": {
            "kind": "parameter_ref",
            "symbol": {"index": 0, "kind": "parameter"},
        },
        "kind": 0,
    }
    assert _state_value(rule["forward"]["reactants"][0]) == "u"
    assert _state_value(rule["forward"]["products"][0]) == "p"
    assert rule["forward"]["mutations"] == [
        {
            "kind": "change_state",
            "source": {"molecule": 0, "pattern": 0, "side": "reactant", "site": 0},
            "state": "p",
            "state_index": 1,
        }
    ]


def test_frozen_v01_migrates_to_pinned_schema_valid_v02_and_round_trips():
    legacy_document = json.loads(LEGACY_FIXTURE.read_text(encoding="utf-8"))
    expected_document = json.loads(STRUCTURAL_FIXTURE.read_text(encoding="utf-8"))
    jsonschema.validate(legacy_document, _schema("0.1"))
    jsonschema.validate(expected_document, _schema("0.2"))
    _assert_hand_reviewed_semantics(expected_document)
    expected_wire = json.dumps(
        expected_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    legacy_model = bionetgen.from_bngir(legacy_document)
    first_export = bionetgen.to_bngir(legacy_model, version="0.2").encode("utf-8")
    second_export = bionetgen.to_bngir(legacy_model, version="0.2").encode("utf-8")

    assert first_export == expected_wire
    assert second_export == expected_wire
    structural_document = json.loads(first_export)
    jsonschema.validate(structural_document, _schema("0.2"))

    restored_model = bionetgen.from_bngir(structural_document)
    assert bionetgen.semantic_equal(legacy_model, restored_model, version="0.2")
    restored_export = bionetgen.to_bngir(restored_model, version="0.2").encode("utf-8")
    assert restored_export == expected_wire
