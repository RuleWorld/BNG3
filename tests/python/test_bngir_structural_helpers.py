"""Pure-Python contracts for BNGIR v0.2.

These intentionally avoid importing the package-level C++ extension so the
wire-format validation remains testable in dependency-constrained builds.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "bngir_standalone", ROOT / "python" / "bionetgen" / "bngir.py"
)
assert SPEC and SPEC.loader
bngir = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bngir)


def minimal_document() -> dict:
    return {
        "format": "BNGIR",
        "version": "0.2",
        "features": {
            "required": ["structured_patterns", "structured_expressions"],
            "used": ["structured_patterns", "structured_expressions", "rules"],
        },
        "model": {
            "metadata": {
                "name": "structural",
                "version": "2.2",
                "substance_units": "Number",
                "options": {},
            },
            "parameters": [{"id": 0, "name": "k", "expression": {"kind": "number", "value": 1.0}, "constant_value": 1.0}],
            "molecule_types": [{"id": 0, "name": "A", "population": False, "components": [{"index": 0, "name": "x", "states": ["u", "p"]}]}],
            "compartments": [],
            "seeds": [],
            "observables": [],
            "functions": [],
            "energy_patterns": [],
            "population_maps": [],
            "rules": [],
        },
        "protocol": {"actions": []},
    }


def test_v02_validates_used_features_as_well_as_required():
    document = minimal_document()
    document["features"]["used"].append("future_semantics")
    with pytest.raises(ValueError, match="unsupported used BNGIR features"):
        bngir._load_document_v02(document)


def test_v02_requires_structural_feature_contract():
    document = minimal_document()
    document["features"]["required"] = ["structured_patterns"]
    with pytest.raises(ValueError, match="must require structured patterns and expressions"):
        bngir._load_document_v02(document)


def test_v02_expression_and_pattern_render_without_source_text():
    document = minimal_document()
    model = document["model"]
    expression = {
        "kind": "binary",
        "operator": "multiply",
        "arguments": [
            {"kind": "parameter_ref", "symbol": {"kind": "parameter", "index": 0}},
            {"kind": "number", "value": 2.0},
        ],
    }
    assert bngir._expression_v02(expression, model) == "(k * 2.0)"

    pattern = {
        "compartment_prefix": False,
        "molecules": [{
            "occurrence": 0,
            "type": "A",
            "type_id": 0,
            "sites": [{
                "occurrence": 0,
                "component": "x",
                "component_index": 0,
                "state": {"kind": "exact", "value": "p", "index": 1},
                "bond": {"kind": "unbound"},
            }],
        }],
    }
    assert bngir._pattern_v02(pattern) == "A(x~p.)"


def test_v02_minimal_document_matches_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "provenance" / "schemas" / "bngir-0.2.schema.json").read_text())
    jsonschema.validate(minimal_document(), schema)
