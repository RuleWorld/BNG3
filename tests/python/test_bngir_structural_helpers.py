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
            "parameters": [
                {
                    "id": 0,
                    "name": "k",
                    "expression": {"kind": "number", "value": 1.0},
                    "constant_value": 1.0,
                }
            ],
            "molecule_types": [
                {
                    "id": 0,
                    "name": "A",
                    "population": False,
                    "components": [{"index": 0, "name": "x", "states": ["u", "p"]}],
                }
            ],
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
    with pytest.raises(
        ValueError, match="must require structured patterns and expressions"
    ):
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
        "molecules": [
            {
                "occurrence": 0,
                "type": "A",
                "type_id": 0,
                "sites": [
                    {
                        "occurrence": 0,
                        "component": "x",
                        "component_index": 0,
                        "state": {"kind": "exact", "value": "p", "index": 1},
                        "bond": {"kind": "unbound"},
                    }
                ],
            }
        ],
    }
    assert bngir._pattern_v02(pattern) == "A(x~p.)"


def test_v02_minimal_document_matches_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (ROOT / "provenance" / "schemas" / "bngir-0.2.schema.json").read_text()
    )
    jsonschema.validate(minimal_document(), schema)


def test_v02_builtin_calls_render_bngl_keyword_spellings():
    model = minimal_document()["model"]
    ref = {"kind": "parameter_ref", "symbol": {"kind": "parameter", "index": 0}}
    for builtin, spelling in (
        ("arrhenius", "Arrhenius"),
        ("saturation", "Sat"),
        ("hill", "Hill"),
        ("michaelis_menten", "MM"),
        ("exp", "exp"),
    ):
        expression = {
            "kind": "builtin_call",
            "builtin": builtin,
            "arguments": [ref, ref],
        }
        assert bngir._expression_v02(expression, model) == f"{spelling}(k,k)"


def test_v02_refuses_unknown_builtin_calls():
    document = minimal_document()
    document["model"]["functions"] = [
        {
            "id": 0,
            "name": "f",
            "arguments": [],
            "expression": {
                "kind": "builtin_call",
                "builtin": "future_builtin",
                "arguments": [],
            },
        }
    ]

    with pytest.raises(ValueError, match="unsupported builtin"):
        bngir._load_document_v02(document)


def test_v02_renders_unit_defaults_definitions_and_annotations():
    document = minimal_document()
    metadata = document["model"]["metadata"]
    metadata["unit_defaults"] = {"timeUnits": "second"}
    metadata["unit_definitions"] = [
        {
            "id": "per_s",
            "expression": "second^-1",
            "builtin": False,
            "unit": "per_s",
            "factor": 1.0,
        }
    ]
    document["model"]["parameters"][0]["unit"] = "per_s"

    root = bngir._load_document_v02(document)
    source = bngir._as_bngl_v02(root)

    assert (
        "begin units\n  timeUnits = second\n  unit per_s = second^-1\nend units"
        in source
    )
    assert "  k 1.0 [per_s]" in source


def test_v02_refuses_unsupported_unit_default_roles():
    document = minimal_document()
    document["model"]["metadata"]["unit_defaults"] = {"durationUnits": "second"}

    with pytest.raises(ValueError, match="unsupported role"):
        bngir._load_document_v02(document)


def test_v02_refuses_builtin_unit_definitions():
    document = minimal_document()
    document["model"]["metadata"]["unit_definitions"] = [
        {"id": "second", "expression": "s", "builtin": True, "unit": "s", "factor": 1.0}
    ]

    with pytest.raises(ValueError, match="builtin definition"):
        bngir._load_document_v02(document)


def test_v02_barrier_patterns_render_from_transition_text():
    document = minimal_document()
    # The wire transition is BarrierPattern::toString(): label, arrow, and
    # energy expression in one string.
    document["model"]["barrier_patterns"] = [
        {
            "index": 0,
            "label": "slow",
            "transition": "slow: A(s~U) -> A(s~P) Gbar",
            "expression": "Gbar",
            "reaction_center": "A|s|U->P",
            "center_resolved": True,
            "value": 1.0,
        }
    ]

    root = bngir._load_document_v02(document)
    source = bngir._as_bngl_v02(root)

    assert "  slow: A(s~U) -> A(s~P) Gbar\n" in source
    # Exactly once: the transition already carries both label and energy.
    assert source.count("Gbar") == 1
    assert source.count("slow:") == 1


def test_v02_refuses_unresolved_barrier_centers():
    document = minimal_document()
    document["model"]["barrier_patterns"] = [
        {
            "index": 0,
            "label": "slow",
            "transition": "slow: A(s~U) -> A(s~P) Gbar",
            "expression": "Gbar",
            "reaction_center": "",
            "center_resolved": False,
            "value": None,
        }
    ]

    with pytest.raises(ValueError, match="resolved reaction center"):
        bngir._load_document_v02(document)


def test_v02_observable_count_relations_render_bare_molecule_patterns():
    document = minimal_document()
    document["model"]["observables"] = [
        {
            "id": 0,
            "name": "R2",
            "kind": "species",
            "terms": [
                {
                    "pattern": {
                        "compartment_prefix": False,
                        "molecules": [{"occurrence": 0, "type": "R", "sites": []}],
                    },
                    "quantity": 2,
                    "relation": "==",
                }
            ],
        }
    ]

    root = bngir._load_document_v02(document)

    assert "  Species R2 R==2\n" in bngir._as_bngl_v02(root)


def test_v02_refuses_sited_count_relation_patterns():
    document = minimal_document()
    document["model"]["observables"] = [
        {
            "id": 0,
            "name": "R2",
            "kind": "species",
            "terms": [
                {
                    "pattern": {
                        "compartment_prefix": False,
                        "molecules": [
                            {
                                "occurrence": 0,
                                "type": "A",
                                "sites": [
                                    {
                                        "occurrence": 0,
                                        "component": "x",
                                        "state": {"kind": "any"},
                                        "bond": {"kind": "unspecified"},
                                    }
                                ],
                            }
                        ],
                    },
                    "quantity": 2,
                    "relation": "==",
                }
            ],
        }
    ]

    with pytest.raises(ValueError, match="requires a bare molecule pattern"):
        bngir._load_document_v02(document)
