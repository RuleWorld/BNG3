import json
from pathlib import Path

import pytest

import bionetgen

jsonschema = pytest.importorskip("jsonschema")

pytest.importorskip("bionetgen._bionetgen_cpp")


MODEL = r"""
version("2.2")
setModelName("bngir_fixture")
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin functions
    rate() = 2*k
end functions
begin reaction rules
    X() -> 0 k
end reaction rules
end model
"""


def test_bngir_is_deterministic_and_source_free():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    first = model.to_bngir(provenance={"source": "fixture"})
    second = bionetgen.to_bngir(model, provenance={"source": "fixture"})

    assert first == second
    assert "begin model" not in first
    assert "GeneratedNetwork" not in first
    document = json.loads(first)
    assert document["format"] == "BNGIR"
    assert document["version"] == "0.1"
    assert "functions" in document["features"]["used"]
    assert document["model"]["parameters"] == [{"name": "k", "expression": "0.1"}]


def test_bngir_round_trip_semantic_equality():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    restored = bionetgen.from_bngir(model.to_bngir())

    assert bionetgen.semantic_equal(model, restored)
    assert restored.name == "bngir_fixture"


def test_bngir_document_conforms_to_published_schema():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    document = json.loads(model.to_bngir())
    schema_path = (
        Path(__file__).parents[2] / "provenance" / "schemas" / "bngir-0.1.schema.json"
    )

    jsonschema.validate(document, json.loads(schema_path.read_text()))


def test_bngir_rejects_unknown_required_features():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    document = json.loads(model.to_bngir())
    document["features"]["required"] = ["future_backend_state"]

    with pytest.raises(ValueError, match="unsupported required BNGIR features"):
        bionetgen.from_bngir(document)


def test_bngir_population_reconstruction_fails_closed():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    document = json.loads(model.to_bngir())
    document["model"]["population_maps"] = [
        {"label": "pop", "pattern": "X()", "function": "lumped", "args": []}
    ]

    with pytest.raises(ValueError, match="population_maps deserialization"):
        bionetgen.from_bngir(document)


def test_bngir_rejects_unknown_action_scope():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    document = json.loads(model.to_bngir())
    document["protocol"]["actions"] = [
        {"scope": "future", "name": "simulate", "arguments": {}}
    ]

    with pytest.raises(ValueError, match="unsupported BNGIR action scope"):
        bionetgen.from_bngir(document)


def test_bngir_preserves_model_and_simulation_protocol_actions():
    source = MODEL.replace(
        "end model\n",
        "begin protocol\nsimulate({method=>ode,t_end=>1,n_steps=>2})\nend protocol\nend model\nbegin actions\ngenerate_network({overwrite=>1})\nend actions\n",
    )
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(source))
    schema_path = (
        Path(__file__).parents[2] / "provenance" / "schemas" / "bngir-0.1.schema.json"
    )
    jsonschema.validate(
        json.loads(model.to_bngir()), json.loads(schema_path.read_text())
    )
    restored = bionetgen.from_bngir(model.to_bngir())

    assert bionetgen.semantic_equal(model, restored)


def test_bngir_round_trip_preserves_compartments_energy_and_population_types():
    source = r"""
version("2.2")
begin model
begin compartments
    CYT 3 1
    NUC 3 0.5 CYT
end compartments
begin molecule types
    X(site~u~p)
    P() population
end molecule types
begin seed species
    @NUC:X(site~u) 100
end seed species
begin energy patterns
    bind: X(site~p) 1.0
end energy patterns
end model
"""
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(source))
    restored = bionetgen.from_bngir(model.to_bngir())

    assert bionetgen.semantic_equal(model, restored)
