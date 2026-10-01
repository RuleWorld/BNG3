import json
from pathlib import Path

import pytest

import bionetgen

jsonschema = pytest.importorskip("jsonschema")

from _extdep import require_extension
require_extension()


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


def test_bngir_v02_is_structural_and_schema_valid():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    document = json.loads(model.to_bngir(version="0.2"))
    assert document["version"] == "0.2"
    assert "structured_patterns" in document["features"]["required"]
    assert "structured_expressions" in document["features"]["required"]
    seed_pattern = document["model"]["seeds"][0]["pattern"]
    assert seed_pattern["molecules"][0]["type"] == "X"
    assert not isinstance(seed_pattern, str)
    assert document["model"]["parameters"][0]["expression"]["kind"] == "number"
    schema_path = (
        Path(__file__).parents[2] / "provenance" / "schemas" / "bngir-0.2.schema.json"
    )
    jsonschema.validate(document, json.loads(schema_path.read_text()))


def test_bngir_v02_round_trip_semantic_equality():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    restored = bionetgen.from_bngir(model.to_bngir(version="0.2"))
    assert bionetgen.semantic_equal(model, restored, version="0.2")
    assert restored.name == "bngir_fixture"


def test_bngir_v02_preserves_protocol_scopes():
    source = MODEL.replace(
        "end model\n",
        "begin protocol\nsimulate({method=>ode,t_end=>1,n_steps=>2})\nend protocol\nend model\nbegin actions\ngenerate_network({overwrite=>1})\nend actions\n",
    )
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(source))
    document = json.loads(model.to_bngir(version="0.2"))
    assert [action["scope"] for action in document["protocol"]["actions"]] == [
        "model",
        "simulation_protocol",
    ]
    restored = bionetgen.from_bngir(document)
    assert bionetgen.semantic_equal(model, restored, version="0.2")


BUILTIN_MODEL = r"""
version("2.2")
begin model
begin parameters
    phi 0.5
    Ea 1
    kcat 1.5
    Km 100
    n 2
end parameters
begin molecule types
    A(s~U~P)
    E()
end molecule types
begin seed species
    A(s~U) 100
    E() 10
end seed species
begin reaction rules
    r_arr: A(s~U) <-> A(s~P) Arrhenius(phi, Ea)
    r_sat: A(s~U) + E() -> A(s~P) + E() Sat(kcat, Km)
    r_hill: A(s~U) + E() -> A(s~P) + E() Hill(kcat, Km, n)
    r_mm: A(s~U) + E() -> A(s~P) + E() MM(kcat, Km)
end reaction rules
end model
"""


def test_bngir_v02_round_trip_preserves_builtin_rate_laws():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(BUILTIN_MODEL))
    restored = bionetgen.from_bngir(model.to_bngir(version="0.2"))

    assert bionetgen.semantic_equal(model, restored, version="0.2")


COUNT_MODEL = r"""
version("2.2")
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    R(l,l)
    A()
end molecule types
begin seed species
    R(l,l) 100
    A() 5
end seed species
begin observables
    Molecules Rfree R(l,l)
    Species R2 R==2
    Species R5 R>4
    Species Amin A>=1
    Species Mix R(l,l).A()>1
end observables
begin reaction rules
    R(l!1,l) -> R(l!1,l) k
end reaction rules
end model
"""


def test_bngir_v02_round_trip_preserves_observable_count_relations():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(COUNT_MODEL))
    restored = bionetgen.from_bngir(model.to_bngir(version="0.2"))

    assert bionetgen.semantic_equal(model, restored, version="0.2")


UNIT_MODEL = r"""
version("2.2")
begin model
begin units
    timeUnits = second
    substanceUnits = item
    volumeUnits = litre
    unit per_s = second^-1
end units
begin parameters
    KD = 100 [nM]
    koff = 0.02 [per_s]
end parameters
begin compartments
    cyto 3 1 [fL]
end compartments
begin molecule types
    A(x)
end molecule types
begin seed species
    A(x)@cyto 10 [molecule]
end seed species
begin reaction rules
    A(x~u) -> A(x~p) koff
end reaction rules
end model
"""


def test_bngir_v02_round_trip_preserves_unit_metadata():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(UNIT_MODEL))
    restored = bionetgen.from_bngir(model.to_bngir(version="0.2"))

    assert bionetgen.semantic_equal(model, restored, version="0.2")
    assert dict(restored._model.unit_defaults) == {
        "timeUnits": "second",
        "substanceUnits": "item",
        "volumeUnits": "litre",
    }
    assert [p.unit for p in restored._model.parameters] == ["nM", "per_s"]
    assert restored._model.compartments[0].unit == "fL"
    assert restored._model.seed_species[0].unit == "molecule"


def test_bngir_v01_refuses_unit_metadata_instead_of_dropping_it():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(UNIT_MODEL))

    with pytest.raises(ValueError, match="physical-unit metadata"):
        model.to_bngir()

    # semantic_equal builds the wire form it compares, so it surfaces the
    # same named refusal instead of silently comparing unit-stripped models.
    with pytest.raises(ValueError, match="physical-unit metadata"):
        bionetgen.semantic_equal(model, model)
    assert bionetgen.semantic_equal(model, model, version="0.2")


COUNTER_MODEL = r"""
version("2.2")
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules Ma A()
    Counter Ca A()
end observables
begin reaction rules
    A() -> A() k
end reaction rules
end model
"""


def test_bngir_v02_refuses_counter_observables_and_v01_preserves_them():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(COUNTER_MODEL))

    with pytest.raises(ValueError, match="observable kinds"):
        model.to_bngir(version="0.2")

    restored = bionetgen.from_bngir(model.to_bngir())
    assert bionetgen.semantic_equal(model, restored)
    assert [(o.name, o.type) for o in restored._model.observables] == [
        ("Ma", "Molecules"),
        ("Ca", "Counter"),
    ]


def test_bngir_v02_rejects_unknown_observable_kind():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    document = json.loads(model.to_bngir(version="0.2"))
    document["model"]["observables"][0]["kind"] = "unknown"

    with pytest.raises(ValueError, match="unsupported observable kind"):
        bionetgen.from_bngir(document)


def test_bngir_v02_rejects_reverse_direction_on_irreversible_rule():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    document = json.loads(model.to_bngir(version="0.2"))
    rule = document["model"]["rules"][0]
    assert rule["bidirectional"] is False
    rule["reverse"] = rule["forward"]

    with pytest.raises(ValueError, match="reverse direction on a non-bidirectional"):
        bionetgen.from_bngir(document)


def test_bngir_v02_rejects_unrepresentable_rule_modifiers():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODEL))
    document = json.loads(model.to_bngir(version="0.2"))
    document["model"]["rules"][0]["modifiers"] = [{"kind": "future_modifier"}]

    with pytest.raises(ValueError, match="unsupported modifier kind"):
        bionetgen.from_bngir(document)

    document["model"]["rules"][0]["modifiers"] = [{"kind": "include_reactants"}]

    with pytest.raises(ValueError, match="no matching filter"):
        bionetgen.from_bngir(document)


MODIFIER_MODEL = r"""
version("2.2")
begin model
begin parameters
    k 0.1
    k2 0.2
end parameters
begin molecule types
    A(x~u~p)
    B(y)
end molecule types
begin seed species
    A(x~u) 100
    B(y) 50
end seed species
begin reaction rules
    r1: A(x~u) -> A(x~p) k include_reactants(1, A(x~u))
    r2: A(x) + B(y) -> A(x!1).B(y!1) k2 MatchOnce
    r3: A(x!1).B(y!1) -> A(x) + B(y) k2 DeleteMolecules
end reaction rules
end model
"""


def test_bngir_v02_round_trip_preserves_rule_modifiers():
    model = bionetgen.BioNetGenModel(bionetgen.model._cpp.parse_string(MODIFIER_MODEL))
    document = json.loads(model.to_bngir(version="0.2"))
    # The include modifier serializes through direction.filters; the pairing
    # the reader requires is exactly what the writer emitted.
    kinds = [
        modifier["kind"]
        for rule in document["model"]["rules"]
        for modifier in rule["modifiers"]
    ]
    assert "include_reactants" in kinds

    restored = bionetgen.from_bngir(document)
    assert bionetgen.semantic_equal(model, restored, version="0.2")
