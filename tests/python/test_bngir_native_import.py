"""Behavioral contract for the explicit parser-free BNGIR v0.2 import route."""

from __future__ import annotations

import copy
import importlib
from itertools import permutations
import json
from pathlib import Path

import jsonschema
import pytest

import bionetgen
from _extdep import require_extension

require_extension()

from bionetgen.model import _cpp

SOURCE = r"""
version("2.2")
setModelName("native_bngir_decay")
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
end seed species
begin reaction rules
    convert: A() -> B() k
end reaction rules
end model
"""

SEED_ONLY_SOURCE = r"""
version("2.2")
setModelName("native_bngir_static")
begin model
begin molecule types
    A()
end molecule types
begin seed species
    A() 5
end seed species
end model
"""

SITES_SOURCE = r"""
version("2.2")
setModelName("native_bngir_sites")
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A(x~u~p)
    B(x~u~p)
end molecule types
begin seed species
    A(x~u) 10
end seed species
begin reaction rules
    convert: A(x~u) -> B(x~p) k
end reaction rules
end model
"""

POPULATION_SOURCE = r"""
begin model
begin molecule types
    A()
    P() population
end molecule types
begin seed species
    A() 1
end seed species
end model
"""

# A model with a transition-state barrier. The barrier needs a matching
# energy pattern: there is no Arrhenius expansion for a barrier to modify
# without one.
BARRIER_SOURCE = r"""
begin model
begin molecule types
    A(s~U~P)
end molecule types
begin seed species
    A(s~U) 10
end seed species
begin energy patterns
    e: A(s~U) 1.0
end energy patterns
begin barrier patterns
    b: A(s~U) -> A(s~P) 2.0
end barrier patterns
begin reaction rules
    A(s~U) -> A(s~P) 3.0
end reaction rules
end model
"""

# A model whose rate law is written with model functions: one function binds
# its own argument, one calls another model function, and one names an
# observable the way the Playground-derived Atomizer writes its helpers.
FUNCTION_SOURCE = r"""
version("2.2")
setModelName("native_bngir_functions")
begin model
begin parameters
    k 0.1
    base 2
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 100
end seed species
begin observables
    Molecules A_total A()
end observables
begin functions
    scaled(x) = x*k
    doubled(x) = scaled(x)*2
    _c_A() = A_total
end functions
begin reaction rules
    convert: A() -> B() doubled(base)
end reaction rules
end model
"""


def _document(source: str = SOURCE) -> dict:
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    return json.loads(source_model.to_bngir(version="0.2"))


def _reorder_parameter_ids(model: dict, names: tuple[str, ...]) -> None:
    """Reorder declarations and remap all parameter symbol references."""
    declarations = {item["name"]: item for item in model["parameters"]}
    old_to_new = {declarations[name]["id"]: new_id for new_id, name in enumerate(names)}
    model["parameters"] = [declarations[name] for name in names]
    for new_id, parameter in enumerate(model["parameters"]):
        parameter["id"] = new_id

    def remap(value):
        if isinstance(value, dict):
            symbol = value.get("symbol")
            if isinstance(symbol, dict) and symbol.get("kind") == "parameter":
                symbol["index"] = old_to_new[symbol["index"]]
            for child in value.values():
                remap(child)
        elif isinstance(value, list):
            for child in value:
                remap(child)

    remap(model)


def test_direct_native_builder_accepts_a_schema_valid_population_type():
    document = _document(POPULATION_SOURCE)
    schema_path = (
        Path(__file__).parents[2] / "provenance" / "schemas" / "bngir-0.2.schema.json"
    )
    jsonschema.validate(document, json.loads(schema_path.read_text()))
    population_type = next(
        item for item in document["model"]["molecule_types"] if item["name"] == "P"
    )
    assert population_type["population"] is True

    model = _cpp._model_from_bngir_v02(document["model"])
    imported = next(item for item in model.molecule_types if item.name == "P")
    assert imported.is_population


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing", "molecule type is missing population"),
        ("integer", "molecule type population must be boolean"),
        ("string", "molecule type population must be boolean"),
        ("null", "molecule type population must be boolean"),
    ],
    ids=["missing", "integer", "string", "null"],
)
def test_direct_native_builder_rejects_malformed_population_flag(mutation, expected):
    document = _document()
    molecule_type = document["model"]["molecule_types"][0]
    if mutation == "missing":
        del molecule_type["population"]
    elif mutation == "integer":
        molecule_type["population"] = 1
    elif mutation == "string":
        molecule_type["population"] = "false"
    else:
        molecule_type["population"] = None

    with pytest.raises(RuntimeError, match=expected):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_preserves_ordinary_population_false():
    document = _document()
    assert document["model"]["molecule_types"][0]["population"] is False

    restored = _cpp._model_from_bngir_v02(document["model"])

    assert restored.molecule_types[0].is_population is False


def _nested_arithmetic_document() -> dict:
    document = _document()
    document["model"]["rules"][0]["forward"]["rate"]["expression"] = {
        "kind": "unary",
        "operator": "plus",
        "arguments": [
            {
                "kind": "binary",
                "operator": "add",
                "arguments": [
                    {
                        "kind": "parameter_ref",
                        "symbol": {"kind": "parameter", "index": 0},
                    },
                    {"kind": "number", "value": 0.1},
                ],
            }
        ],
    }
    return document


def _direct_native_model(document: dict):
    return bionetgen.BioNetGenModel(
        _cpp._model_from_bngir_v02(copy.deepcopy(document["model"]))
    )


def _set_numeric_expression(document: dict, location: str, value: float) -> None:
    model = document["model"]
    if location == "parameter":
        expression = model["parameters"][0]["expression"]
    elif location == "rate":
        expression = model["rules"][0]["forward"]["rate"]["expression"]
    elif location == "seed":
        expression = model["seeds"][0]["amount"]
    else:
        raise ValueError(f"unknown expression location: {location}")
    expression.clear()
    expression.update({"kind": "number", "value": value})


@pytest.mark.parametrize(
    ("source", "species_count", "reaction_count"),
    [(SOURCE, 2, 1), (SEED_ONLY_SOURCE, 1, 0)],
    ids=["conversion", "seed-only"],
)
def test_direct_native_builder_preserves_supported_models_and_executes(
    source, species_count, reaction_count
):
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    document = json.loads(source_model.to_bngir(version="0.2"))
    restored = _direct_native_model(document)

    assert json.loads(restored.to_bngir(version="0.2")) == document
    network = restored.generate_network()
    assert network.num_species == species_count
    assert network.num_reactions == reaction_count
    result = restored.simulate(method="ode", t_end=0.1, n_steps=1)
    assert result.time.tolist() == pytest.approx([0.0, 0.1])
    assert bionetgen.semantic_equal(source_model, restored, version="0.2")


def test_direct_native_builder_accepts_molecule_type_components():
    document = _document()
    document["model"]["molecule_types"][0]["components"] = [
        {"index": 0, "name": "x", "states": ["u", "p"]}
    ]

    model = _cpp._model_from_bngir_v02(document["model"])
    imported = next(item for item in model.molecule_types if item.name == "A")
    assert [component.name for component in imported.components] == ["x"]


@pytest.mark.parametrize("location", ["seed", "reactant", "product"])
def test_direct_native_builder_accepts_molecule_sites(location):
    document = _document(SITES_SOURCE)
    model = document["model"]

    patterns = {
        "seed": model["seeds"][0]["pattern"],
        "reactant": model["rules"][0]["forward"]["reactants"][0],
        "product": model["rules"][0]["forward"]["products"][0],
    }
    selected_sites = copy.deepcopy(patterns[location]["molecules"][0]["sites"])
    for pattern in patterns.values():
        pattern["molecules"][0]["sites"] = []
    patterns[location]["molecules"][0]["sites"] = selected_sites

    imported = _cpp._model_from_bngir_v02(model)
    assert imported is not None


@pytest.mark.parametrize(
    ("side", "pattern_count", "message"),
    [
        ("reactants", 0, "without a reactant and product pattern"),
        ("reactants", 2, "delete-and-add operations"),
        ("products", 0, "without a reactant and product pattern"),
        ("products", 2, "delete-and-add operations"),
    ],
    ids=["no-reactants", "extra-reactant", "no-products", "extra-product"],
)
def test_direct_native_builder_rejects_invalid_rule_pattern_counts(
    side, pattern_count, message
):
    document = _document()
    direction = document["model"]["rules"][0]["forward"]
    if pattern_count == 0:
        direction[side].clear()
    else:
        direction[side].append(copy.deepcopy(direction[side][0]))

    with pytest.raises(RuntimeError, match=message):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize(
    ("section", "index", "value"),
    [
        ("parameters", 0, 1),
        ("molecule_types", 1, 0),
        ("seeds", 0, 1),
        ("rules", 0, 1),
    ],
    ids=[
        "parameter-misordered",
        "molecule-type-duplicate",
        "seed-misordered",
        "rule-misordered",
    ],
)
def test_direct_native_builder_rejects_non_dense_declaration_ids(section, index, value):
    document = _document()
    document["model"][section][index]["id"] = value

    with pytest.raises(RuntimeError, match="dense and ordered"):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_rejects_boolean_declaration_ids():
    document = _document()
    document["model"]["parameters"][0]["id"] = False

    with pytest.raises(RuntimeError):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_rejects_boolean_numeric_expression_values():
    document = _document()
    document["model"]["parameters"][0]["expression"]["value"] = True

    with pytest.raises(
        RuntimeError, match="native BNGIR expression value must be numeric"
    ):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize("location", ["parameter", "rate", "seed"])
@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_direct_native_builder_rejects_non_finite_numeric_expressions(location, value):
    document = _document()
    _set_numeric_expression(document, location, value)

    with pytest.raises(
        RuntimeError, match="native BNGIR expression value must be finite"
    ):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize(
    ("location", "value"),
    [
        ("parameter", 0.25),
        ("parameter", 0.0),
        ("parameter", -0.25),
        ("rate", 0.25),
        ("rate", 0.0),
        ("seed", 10.0),
        ("seed", 0.0),
    ],
    ids=[
        "parameter-positive",
        "parameter-zero",
        "parameter-negative",
        "rate-positive",
        "rate-zero",
        "seed-positive",
        "seed-zero",
    ],
)
def test_direct_native_builder_accepts_finite_numeric_expressions(location, value):
    document = _document()
    _set_numeric_expression(document, location, value)

    _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_accepts_integer_parameter_expression():
    document = _document()
    _set_numeric_expression(document, "parameter", 1)

    _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_reports_oversized_parameter_expression():
    document = _document()
    _set_numeric_expression(document, "parameter", 10**400)

    with pytest.raises(
        RuntimeError, match="native BNGIR expression value must be finite"
    ):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (float("nan"), "must be finite"),
        (float("inf"), "must be finite"),
        (float("-inf"), "must be finite"),
        (True, "must be numeric, not boolean"),
        ("0.1", "must be numeric"),
    ],
    ids=["nan", "positive-infinity", "negative-infinity", "boolean", "string"],
)
def test_direct_native_builder_rejects_invalid_optional_constant_values(
    value, expected
):
    document = _document()
    document["model"]["parameters"][0]["constant_value"] = value

    with pytest.raises(
        RuntimeError,
        match=f"native BNGIR parameter constant_value {expected}",
    ):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize(
    "value", [0.25, 0.0, -0.25], ids=["positive", "zero", "negative"]
)
def test_direct_native_builder_accepts_finite_optional_constant_values(value):
    document = _document()
    _set_numeric_expression(document, "parameter", value)
    document["model"]["parameters"][0]["constant_value"] = value

    _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_accepts_integer_optional_constant_value():
    document = _document()
    document["model"]["parameters"][0]["constant_value"] = 1

    _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_rejects_oversized_optional_constant_value():
    document = _document()
    document["model"]["parameters"][0]["constant_value"] = 10**400

    with pytest.raises(
        RuntimeError, match="native BNGIR parameter constant_value must be finite"
    ):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_rejects_unknown_expression_properties():
    document = _document()
    document["model"]["parameters"][0]["expression"]["future_semantics"] = "stateful"

    with pytest.raises(
        RuntimeError, match="native BNGIR expression has unsupported future_semantics"
    ):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_rejects_unknown_nested_expression_properties():
    document = _nested_arithmetic_document()
    number = document["model"]["rules"][0]["forward"]["rate"]["expression"]
    number = number["arguments"][0]["arguments"][1]
    number["future_semantics"] = "stateful"

    with pytest.raises(
        RuntimeError, match="native BNGIR expression has unsupported future_semantics"
    ):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_rejects_boolean_nested_expression_values():
    document = _nested_arithmetic_document()
    number = document["model"]["rules"][0]["forward"]["rate"]["expression"]
    number = number["arguments"][0]["arguments"][1]
    number["value"] = True

    with pytest.raises(
        RuntimeError, match="native BNGIR expression value must be numeric"
    ):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize(
    ("node_kind", "arguments", "expected"),
    [
        ("unary", [], "one argument"),
        (
            "unary",
            [
                {"kind": "number", "value": 0.1},
                {"kind": "number", "value": 0.2},
            ],
            "one argument",
        ),
        ("binary", [], "two arguments"),
        (
            "binary",
            [
                {"kind": "parameter_ref", "symbol": {"kind": "parameter", "index": 0}},
                {"kind": "number", "value": 0.1},
                {"kind": "number", "value": 0.2},
            ],
            "two arguments",
        ),
    ],
    ids=["unary-missing", "unary-extra", "binary-missing", "binary-extra"],
)
def test_direct_native_builder_rejects_invalid_expression_arity(
    node_kind, arguments, expected
):
    document = _nested_arithmetic_document()
    expression = document["model"]["rules"][0]["forward"]["rate"]["expression"]
    node = expression if node_kind == "unary" else expression["arguments"][0]
    node["arguments"] = arguments

    with pytest.raises(RuntimeError, match=expected):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_preserves_nested_arithmetic_and_references():
    restored = _direct_native_model(_nested_arithmetic_document())
    network = restored.generate_network()
    state = [100.0 if name == "A()" else 0.0 for name in network.species_names]
    derivative = _cpp._validation_ode_rhs(restored._model, network, 0.0, state)
    by_species = dict(zip(network.species_names, derivative))

    assert by_species["A()"] == pytest.approx(-20.0)
    assert by_species["B()"] == pytest.approx(20.0)


def test_direct_native_builder_rejects_unknown_parameter_properties():
    document = _document()
    document["model"]["parameters"][0]["future_semantics"] = {
        "rate_units": "molecules/s"
    }

    with pytest.raises(
        RuntimeError, match=r"native BNGIR parameter has unsupported future_semantics"
    ):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_rejects_missing_required_parameter_properties():
    document = _document()
    del document["model"]["parameters"][0]["expression"]

    with pytest.raises(
        RuntimeError, match=r"native BNGIR parameter is missing expression"
    ):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_accepts_optional_parameter_constant_value():
    document = _document()
    document["model"]["parameters"][0]["constant_value"] = 0.1

    _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_accepts_parameter_without_optional_constant_value():
    document = _document()
    document["model"]["parameters"][0].pop("constant_value")

    _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize(
    "value",
    [True, 0.0, -1, 99, 10**100],
    ids=["boolean", "float", "negative", "out-of-range", "integer-overflow"],
)
def test_direct_native_builder_rejects_invalid_molecule_type_indices(value):
    document = _document()
    document["model"]["seeds"][0]["pattern"]["molecules"][0]["type_id"] = value

    with pytest.raises(RuntimeError):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize(
    "value",
    [True, 0.0, -1, 99, 10**100],
    ids=["boolean", "float", "negative", "out-of-range", "integer-overflow"],
)
def test_direct_native_builder_rejects_invalid_parameter_reference_indices(value):
    source = SOURCE.replace("    k 0.1", "    k 0.1\n    k2 0.2")
    document = _document(source)
    expression = document["model"]["rules"][0]["forward"]["rate"]["expression"]
    expression["symbol"]["index"] = value

    with pytest.raises(RuntimeError):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("wrong-kind", "parameter reference symbol kind must be parameter"),
        ("nonstring-kind", "parameter reference symbol kind must be parameter"),
        ("missing-kind", "parameter reference symbol is missing kind"),
        (
            "extra-property",
            "parameter reference symbol has unsupported future_semantics",
        ),
    ],
    ids=["wrong-kind", "nonstring-kind", "missing-kind", "extra-property"],
)
def test_direct_native_builder_rejects_invalid_parameter_reference_symbols(
    mutation, expected
):
    document = _document()
    symbol = document["model"]["rules"][0]["forward"]["rate"]["expression"]["symbol"]
    if mutation == "wrong-kind":
        symbol["kind"] = "observable"
    elif mutation == "nonstring-kind":
        symbol["kind"] = 1
    elif mutation == "missing-kind":
        del symbol["kind"]
    else:
        symbol["future_semantics"] = "stateful"

    with pytest.raises(RuntimeError, match=expected):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_reconstructs_a_barrier_pattern():
    document = _document(BARRIER_SOURCE)
    barrier = document["model"]["barrier_patterns"][0]
    assert barrier["center_resolved"] is True
    assert barrier["reaction_center"]

    model = _cpp._model_from_bngir_v02(document["model"])

    barriers = list(model.barrier_patterns)
    assert len(barriers) == 1
    assert barriers[0].label == "b"
    assert barriers[0].has_expression
    assert barriers[0].transition.reactant_patterns == ["A(s~U)"]
    assert barriers[0].transition.product_patterns == ["A(s~P)"]


def test_direct_native_builder_rejects_a_mismatched_barrier_reaction_center():
    document = _document(BARRIER_SOURCE)
    document["model"]["barrier_patterns"][0]["reaction_center"] = "state:B.x~p|B.x~u"

    with pytest.raises(RuntimeError, match="reaction center does not match"):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_reconstructs_rendered_observables():
    document = _document()
    document["model"]["observables"] = [
        {"name": "A_total", "type": "Molecules", "patterns": ["A()"]},
        {"name": "all_species", "type": "Species", "patterns": ["A()", "B()"]},
    ]

    restored = _cpp._model_from_bngir_v02(document["model"])

    assert [
        (item.name, item.type, list(item.patterns)) for item in restored.observables
    ] == [
        ("A_total", "Molecules", ["A()"]),
        ("all_species", "Species", ["A()", "B()"]),
    ]


def test_v01_population_map_and_barrier_pattern_migrate_and_import_natively():
    """A v0.1 document with both features migrates and imports natively.

    The population map carries its rate, and the barrier pattern carries the
    matching energy pattern a barrier needs: there is no Arrhenius expansion
    for a barrier to modify without one.
    """
    document = {
        "format": "BNGIR",
        "version": "0.1",
        "features": {
            "required": [],
            "used": [
                "barrier_patterns",
                "energy_patterns",
                "population_maps",
                "rules",
                "seeds",
            ],
        },
        "model": {
            "name": "population_and_barrier",
            "version": "2.2",
            "substance_units": "",
            "options": {},
            "parameters": [{"name": "k", "expression": "0.1"}],
            "molecule_types": [
                {
                    "name": "A",
                    "population": False,
                    "components": [{"name": "x", "allowed_states": ["u", "p"]}],
                },
                {"name": "P", "population": True, "components": []},
            ],
            "compartments": [],
            "seeds": [
                {
                    "pattern": "A(x~u)",
                    "amount": "10",
                    "constant": False,
                    "compartment": "",
                }
            ],
            "observables": [],
            "functions": [],
            "energy_patterns": [
                {"label": "e", "pattern": "A(x~u)", "expression": "1.0"}
            ],
            "barrier_patterns": [
                {
                    "label": "b",
                    "reactants": ["A(x~u)"],
                    "products": ["A(x~p)"],
                    "bidirectional": False,
                    "expression": "1.0",
                }
            ],
            "population_maps": [
                {
                    "label": "pm",
                    "pattern": "A(x~u)",
                    "function": "P",
                    "args": [],
                    "rate": "1.0",
                }
            ],
            "rules": [
                {
                    "name": "convert",
                    "label": "convert",
                    "reactants": ["A(x~u)"],
                    "products": ["A(x~p)"],
                    "rates": ["k"],
                    "modifiers": [],
                    "bidirectional": False,
                    "driving_work": "",
                }
            ],
        },
        "protocol": {"actions": []},
    }

    model = bionetgen.from_bngir(document)
    migrated = json.loads(model.to_bngir(version="0.2"))

    schema_path = (
        Path(__file__).parents[2] / "provenance" / "schemas" / "bngir-0.2.schema.json"
    )
    jsonschema.validate(migrated, json.loads(schema_path.read_text()))

    # Both features survive the migration with their semantics.
    assert migrated["model"]["barrier_patterns"][0]["center_resolved"] is True
    assert migrated["model"]["barrier_patterns"][0]["reaction_center"]
    assert migrated["model"]["population_maps"][0]["population"] == "P"
    assert migrated["model"]["population_maps"][0]["rate"] == {
        "kind": "number",
        "value": 1.0,
    }

    restored = bionetgen.from_bngir(migrated, native=True)
    assert json.loads(restored.to_bngir(version="0.2")) == migrated

    barriers = list(restored._model.barrier_patterns)
    assert len(barriers) == 1
    assert barriers[0].label == "b"
    mappings = list(restored._model.population_maps)
    assert len(mappings) == 1
    assert mappings[0].label == "pm"
    assert mappings[0].function == "P"
    assert mappings[0].rate == "1"


def test_native_import_reconstructs_and_executes_without_source_parsing(monkeypatch):
    document = _document()
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(SOURCE))
    bngir_module = importlib.import_module("bionetgen.bngir")

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import rendered or parsed BNGL source")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    monkeypatch.setattr(bngir_module, "_as_bngl_v02", forbidden)

    restored = bionetgen.from_bngir(document, native=True)
    assert json.loads(restored.to_bngir(version="0.2")) == document
    with pytest.raises(ValueError, match="cannot be exported as v0.1"):
        restored.to_bngir(version="0.1")

    network = restored.generate_network()
    assert network.num_species == 2
    assert network.num_reactions == 1
    assert set(network.species_names) == {"A()", "B()"}

    state = [100.0 if name == "A()" else 0.0 for name in network.species_names]
    derivative = _cpp._validation_ode_rhs(restored._model, network, 0.0, state)
    by_species = dict(zip(network.species_names, derivative))
    assert by_species["A()"] == pytest.approx(-10.0)
    assert by_species["B()"] == pytest.approx(10.0)
    finite_result = restored.simulate(method="ode", t_end=0.1, n_steps=1)
    assert finite_result.time.tolist() == pytest.approx([0.0, 0.1])
    nf_result = restored.simulate(method="nf", t_end=0.1, n_steps=1, seed=1)
    assert nf_result.time.tolist() == pytest.approx([0.0, 0.1])
    assert nf_result.construction_path == "direct"
    assert bionetgen.semantic_equal(source_model, restored, version="0.2")


def test_native_import_reconstructs_observables_without_source_parsing(monkeypatch):
    source = SOURCE.replace(
        "begin seed species",
        "begin observables\n"
        "    Molecules A_molecules A()\n"
        "    Species A_species A()\n"
        "    Species A_exact A==1\n"
        "    Species A_at_least A>=1\n"
        "    Species A_more A>0\n"
        "end observables\n"
        "begin seed species",
    )
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    document = json.loads(source_model.to_bngir(version="0.2"))
    bngir_module = importlib.import_module("bionetgen.bngir")

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import rendered or parsed BNGL source")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    monkeypatch.setattr(bngir_module, "_as_bngl_v02", forbidden)

    restored = bionetgen.from_bngir(document, native=True)

    assert json.loads(restored.to_bngir(version="0.2")) == document
    assert [(item.name, item.type) for item in restored._model.observables] == [
        ("A_molecules", "Molecules"),
        ("A_species", "Species"),
        ("A_exact", "Species"),
        ("A_at_least", "Species"),
        ("A_more", "Species"),
    ]
    network = restored.generate_network()
    assert network.num_species == 2
    assert network.num_reactions == 1
    result = restored.simulate(method="ode", t_end=0.1, n_steps=1)
    assert result.observables["A_molecules"][0] == pytest.approx(100.0)
    assert result.observables["A_species"][0] == pytest.approx(100.0)
    assert result.observables["A_exact"][0] == pytest.approx(100.0)
    assert result.observables["A_at_least"][0] == pytest.approx(100.0)
    assert result.observables["A_more"][0] == pytest.approx(100.0)
    assert bionetgen.semantic_equal(source_model, restored, version="0.2")


def test_native_import_reconstructs_compartmented_observables_without_source_parsing(
    monkeypatch,
):
    source = """
begin model
begin compartments
    cell 3 1
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    @cell:A() 10
end seed species
begin observables
    Molecules A_molecules @cell:A()
    Species A_species @cell:A()
end observables
end model
"""
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    document = json.loads(source_model.to_bngir(version="0.2"))
    bngir_module = importlib.import_module("bionetgen.bngir")

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import rendered or parsed BNGL source")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    monkeypatch.setattr(bngir_module, "_as_bngl_v02", forbidden)

    restored = bionetgen.from_bngir(document, native=True)

    assert json.loads(restored.to_bngir(version="0.2")) == document
    assert [(item.name, item.type) for item in restored._model.observables] == [
        ("A_molecules", "Molecules"),
        ("A_species", "Species"),
    ]
    network = restored.generate_network()
    assert network.num_species == 1
    assert network.num_reactions == 0
    source_result = source_model.simulate(method="ode", t_end=0.1, n_steps=1)
    result = restored.simulate(method="ode", t_end=0.1, n_steps=1)
    for name in ("A_molecules", "A_species"):
        assert result.observables[name] == pytest.approx(
            source_result.observables[name]
        )
    assert bionetgen.semantic_equal(source_model, restored, version="0.2")

    explicit_compartments = copy.deepcopy(document)
    for pattern in [
        explicit_compartments["model"]["seeds"][0]["pattern"],
        *[
            term["pattern"]
            for observable in explicit_compartments["model"]["observables"]
            for term in observable["terms"]
        ],
    ]:
        pattern["molecules"][0]["compartment"] = "cell"
    explicit_restored = bionetgen.from_bngir(explicit_compartments, native=True)
    assert (
        json.loads(explicit_restored.to_bngir(version="0.2")) == explicit_compartments
    )


@pytest.mark.parametrize(
    ("parent", "parent_id", "expected"),
    [
        ("missing", None, "compartment parent references an unknown compartment"),
        ("cell", 7, "compartment parent id is out of range"),
    ],
)
def test_direct_native_builder_rejects_invalid_compartment_parent_reference(
    parent, parent_id, expected
):
    document = _document("""
begin model
begin compartments
    cell 3 1
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    @cell:A() 1
end seed species
end model
""")
    compartment = document["model"]["compartments"][0]
    compartment["parent"] = parent
    if parent_id is not None:
        compartment["parent_id"] = parent_id

    with pytest.raises(RuntimeError, match=f"native BNGIR {expected}"):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize("method", ["ode", "ssa"])
def test_native_import_reconstructs_and_executes_seed_only_model_without_source_parsing(
    monkeypatch, method
):
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(SEED_ONLY_SOURCE))
    document = json.loads(source_model.to_bngir(version="0.2"))
    bngir_module = importlib.import_module("bionetgen.bngir")

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import rendered or parsed BNGL source")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    monkeypatch.setattr(bngir_module, "_as_bngl_v02", forbidden)

    restored = bionetgen.from_bngir(document, native=True)
    assert json.loads(restored.to_bngir(version="0.2")) == document

    network = restored.generate_network()
    assert network.num_species == 1
    assert network.num_reactions == 0
    assert network.species_names == ["A()"]

    derivative = _cpp._validation_ode_rhs(restored._model, network, 0.0, [5.0])
    assert derivative == pytest.approx([0.0])
    result = restored.simulate(method=method, t_end=0.1, n_steps=1, seed=1)
    assert result.time.tolist() == pytest.approx([0.0, 0.1])
    assert result.concentrations[:, 0].tolist() == pytest.approx([5.0, 5.0])
    assert bionetgen.semantic_equal(source_model, restored, version="0.2")


def test_native_import_still_requires_at_least_one_seed():
    document = _document()
    document["model"]["seeds"] = []
    document["features"]["used"].remove("seeds")

    with pytest.raises(ValueError, match="requires at least one seed"):
        bionetgen.from_bngir(document, native=True)


@pytest.mark.parametrize(
    "method",
    [
        "write_xml",
        "write_bngl",
        "write_net",
        "write_sbml",
        "write_matlab",
        "write_latex",
        "contact_map",
        "regulatory_graph",
        "rule_influence_graph",
        "reaction_network_graph",
        "ruleviz_pattern",
        "ruleviz_operation",
        "process_graph",
        "sbml_multi",
    ],
)
def test_native_import_refuses_unqualified_file_exports_without_output(
    tmp_path, method
):
    model = bionetgen.from_bngir(_document(), native=True)
    output = tmp_path / f"{method}.out"

    with pytest.raises(
        RuntimeError,
        match="not supported for native BNGIR v0.2 imports",
    ):
        getattr(model, method)(str(output))

    assert not output.exists()
    assert model._network is None


@pytest.mark.parametrize("method", ["to_xml", "to_bngl"])
def test_native_import_refuses_unqualified_string_exports(method):
    model = bionetgen.from_bngir(_document(), native=True)

    with pytest.raises(
        RuntimeError,
        match="not supported for native BNGIR v0.2 imports",
    ):
        getattr(model, method)()


def test_native_import_refuses_sbml_multi_module_entrypoint_before_writing(
    tmp_path,
):
    from bionetgen.viz import write_sbml_multi

    model = bionetgen.from_bngir(_document(), native=True)
    output = tmp_path / "direct-sbml-multi.xml"
    with pytest.raises(
        RuntimeError,
        match="not supported for native BNGIR v0.2 imports",
    ):
        write_sbml_multi(model, output)
    assert not output.exists()


def test_native_import_refuses_unavailable_action_execution():
    model = bionetgen.from_bngir(_document(), native=True)
    with pytest.raises(
        RuntimeError,
        match="not supported for native BNGIR v0.2 imports",
    ):
        model.execute()


def test_source_backed_model_legacy_exports_remain_available(tmp_path):
    model = bionetgen.BioNetGenModel(_cpp.parse_string(SOURCE))

    bngl = model.to_bngl()
    xml = model.to_xml()
    assert "A() 100" in bngl
    assert "convert: A() -> B() k" in bngl
    assert "<Molecule id=" in xml

    bngl_path = tmp_path / "source.bngl"
    xml_path = tmp_path / "source.xml"
    model.write_bngl(str(bngl_path))
    model.write_xml(str(xml_path))
    assert "A() 100" in bngl_path.read_text()
    assert "<Molecule id=" in xml_path.read_text()


def test_native_nf_simulation_does_not_use_forced_xml_fallback(monkeypatch):
    model = bionetgen.from_bngir(_document(), native=True)
    monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
    monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
    monkeypatch.delenv("BNG_NFSIM_REQUIRE_DIRECT", raising=False)

    with pytest.raises(
        RuntimeError,
        match="direct AST initialization required but unavailable.*FORCE_XML",
    ):
        model.simulate(method="nf", t_end=0.1, n_steps=1, seed=1)


def test_native_import_surfaces_builder_failure_without_fallback(monkeypatch):
    document = _document()
    bngir_module = importlib.import_module("bionetgen.bngir")

    def builder_failure(*_args, **_kwargs):
        raise RuntimeError("native graph builder failed")

    def forbidden(*_args, **_kwargs):
        pytest.fail("native builder failure fell back to rendering or parsing")

    monkeypatch.setattr(_cpp, "_model_from_bngir_v02", builder_failure)
    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    monkeypatch.setattr(bngir_module, "_as_bngl_v02", forbidden)
    with pytest.raises(RuntimeError, match="native graph builder failed"):
        bionetgen.from_bngir(document, native=True)


def test_native_import_rejects_malformed_declaration_ids_before_building(monkeypatch):
    document = _document()
    document["model"]["molecule_types"][1]["id"] = 9

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import fell back to the BNGL parser")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    with pytest.raises(ValueError, match="molecule type.*id|dense|id order"):
        bionetgen.from_bngir(document, native=True)


def test_native_import_rejects_out_of_slice_semantics_without_fallback(monkeypatch):
    document = _document()
    document["model"]["population_types"].append(
        {
            "id": 0,
            "name": "P",
        }
    )

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import fell back to the BNGL parser")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    with pytest.raises(
        ValueError,
        match="native BNGIR.*population_types|population_types.*native BNGIR",
    ):
        bionetgen.from_bngir(document, native=True)


def test_native_import_route_is_explicit_and_default_compatibility_remains():
    document = _document()
    assert bionetgen.from_bngir(document).name == "native_bngir_decay"
    assert bionetgen.from_bngir(copy.deepcopy(document), native=False).name == (
        "native_bngir_decay"
    )


def test_native_import_reconstructs_arithmetic_parameter_expressions():
    source = SOURCE.replace(
        "    k 0.1",
        "    base -0.05\n    k -2*base",
    )
    document = _document(source)
    restored = bionetgen.from_bngir(document, native=True)
    assert json.loads(restored.to_bngir(version="0.2")) == document

    network = restored.generate_network()
    state = [100.0 if name == "A()" else 0.0 for name in network.species_names]
    derivative = _cpp._validation_ode_rhs(restored._model, network, 0.0, state)
    by_species = dict(zip(network.species_names, derivative))
    assert by_species["A()"] == pytest.approx(-10.0)
    assert by_species["B()"] == pytest.approx(10.0)


@pytest.mark.parametrize("duplicate_index", [0, 1])
def test_direct_native_builder_rejects_duplicate_parameter_names(duplicate_index):
    source = SOURCE.replace(
        "    k 0.1",
        "    k1 0.1\n    k2 0.2",
    ).replace("A() -> B() k", "A() -> B() k1")
    document = _document(source)
    parameters = document["model"]["parameters"]
    parameters[duplicate_index]["name"] = parameters[1 - duplicate_index]["name"]

    # The wire IDs still distinguish k1 (0.1) from k2 (0.2), and the rule
    # still references ID 0. Name-based reconstruction must refuse this
    # alias instead of collapsing both IDs onto one native parameter.
    document["model"]["rules"][0]["forward"]["rate"]["expression"] = {
        "kind": "parameter_ref",
        "symbol": {"kind": "parameter", "index": 0},
    }
    with pytest.raises(RuntimeError, match="parameter names must be unique"):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_rejects_duplicate_molecule_type_names():
    document = _document()
    molecule_types = document["model"]["molecule_types"]
    molecule_types[1]["name"] = molecule_types[0]["name"]

    with pytest.raises(RuntimeError, match="molecule type names must be unique"):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize(
    "parameter_order",
    list(permutations(("base", "scaled", "rate"))),
    ids=lambda order: "-".join(order),
)
def test_native_import_parameter_id_reordering_preserves_transitive_dependencies(
    monkeypatch, parameter_order
):
    source = SOURCE.replace(
        "    k 0.1",
        "    base 0.025\n    scaled 2*base\n    rate 2*scaled",
    ).replace("A() -> B() k", "A() -> B() rate")
    document = _document(source)
    _reorder_parameter_ids(document["model"], parameter_order)

    bngir_module = importlib.import_module("bionetgen.bngir")

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import rendered or parsed BNGL source")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    monkeypatch.setattr(bngir_module, "_as_bngl_v02", forbidden)
    restored = bionetgen.from_bngir(document, native=True)
    network = restored.generate_network()
    state = [100.0 if name == "A()" else 0.0 for name in network.species_names]
    derivative = _cpp._validation_ode_rhs(restored._model, network, 0.0, state)
    by_species = dict(zip(network.species_names, derivative))
    assert by_species["A()"] == pytest.approx(-10.0)
    assert by_species["B()"] == pytest.approx(10.0)


def test_native_import_preserves_rebuilt_molecule_mapping():
    source = SOURCE.replace("    B()\n", "").replace("A() -> B()", "A() -> A()")
    document = _document(source)
    assert document["model"]["rules"][0]["molecule_mappings"] == [
        {
            "product": {"molecule": 0, "pattern": 0, "side": "product"},
            "reactant": {"molecule": 0, "pattern": 0, "side": "reactant"},
        }
    ]
    restored = bionetgen.from_bngir(document, native=True)
    assert json.loads(restored.to_bngir(version="0.2")) == document
    network = restored.generate_network()
    assert _cpp._validation_ode_rhs(
        restored._model, network, 0.0, [100.0]
    ) == pytest.approx([0.0])


def test_native_import_rejects_bad_mutation_reference_before_native_builder(
    monkeypatch,
):
    document = _document()
    document["model"]["rules"][0]["forward"]["mutations"][0]["molecule"]["pattern"] = 4

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid BNGIR reached the native model builder")

    monkeypatch.setattr(_cpp, "_model_from_bngir_v02", forbidden)
    with pytest.raises(ValueError, match="pattern reference is out of range"):
        bionetgen.from_bngir(document, native=True)


def test_native_import_accepts_only_integer_zero_mutation_references(monkeypatch):
    document = _document()
    mutations = document["model"]["rules"][0]["forward"]["mutations"]
    assert mutations
    for mutation in mutations:
        reference = mutation["molecule"]
        assert type(reference["pattern"]) is int and reference["pattern"] == 0
        assert type(reference["molecule"]) is int and reference["molecule"] == 0

    assert (
        json.loads(bionetgen.from_bngir(document, native=True).to_bngir(version="0.2"))
        == document
    )

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid mutation reference reached the native model builder")

    monkeypatch.setattr(_cpp, "_model_from_bngir_v02", forbidden)
    for field, value, message in (
        ("pattern", 0.0, "pattern reference is out of range"),
        ("pattern", False, "pattern reference is out of range"),
        ("molecule", 0.0, "molecule reference is out of range"),
        ("molecule", False, "molecule reference is out of range"),
    ):
        invalid = copy.deepcopy(document)
        invalid["model"]["rules"][0]["forward"]["mutations"][0]["molecule"][
            field
        ] = value
        with pytest.raises(ValueError, match=message):
            bionetgen.from_bngir(invalid, native=True)


def test_native_import_rejects_bad_mapping_reference_before_native_builder(
    monkeypatch,
):
    source = SOURCE.replace("    B()\n", "").replace("A() -> B()", "A() -> A()")
    document = _document(source)
    document["model"]["rules"][0]["molecule_mappings"][0]["reactant"]["pattern"] = 5

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid BNGIR reached the native model builder")

    monkeypatch.setattr(_cpp, "_model_from_bngir_v02", forbidden)
    with pytest.raises(ValueError, match="out-of-slice molecule mapping reference"):
        bionetgen.from_bngir(document, native=True)


def test_native_import_refuses_contradictory_resolved_mapping():
    document = _document()
    document["model"]["rules"][0]["molecule_mappings"] = [
        {
            "product": {"pattern": 0, "molecule": 0, "side": "product"},
            "reactant": {"pattern": 0, "molecule": 0, "side": "reactant"},
        }
    ]
    with pytest.raises(
        ValueError, match="does not match reconstructed compiled semantics"
    ):
        bionetgen.from_bngir(document, native=True)


def test_native_import_rejects_unknown_fields_and_provenance():
    document = _document()
    document["model"]["parameters"][0]["source_expression"] = "k"
    with pytest.raises(ValueError, match="unsupported source_expression"):
        bionetgen.from_bngir(document, native=True)

    document = _document()
    document["provenance"] = {"source": "fixture"}
    with pytest.raises(ValueError, match="unsupported provenance"):
        bionetgen.from_bngir(document, native=True)

    document = _document()
    document["model"]["metadata"]["substance_units"] = "mole"
    model = bionetgen.from_bngir(document, native=True)
    exported = json.loads(model.to_bngir(version="0.2"))
    assert exported["model"]["metadata"]["substance_units"] == "mole"


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("bidirectional", True, "missing its reverse direction"),
        ("bidirectional", 0, "bidirectional flag must be a boolean"),
        ("modifiers", ["DeleteMolecules"], "rule modifier must be an object"),
        ("modifiers", [{}], "rule modifier is missing its kind"),
        (
            "modifiers",
            [{"kind": "include_reactants"}],
            "modifier kind is not supported",
        ),
        ("reverse", {}, "reverse direction on a forward rule"),
    ],
)
def test_direct_native_builder_refuses_unrepresented_rule_semantics(
    field, value, expected
):
    document = _document()
    document["model"]["rules"][0][field] = value
    with pytest.raises(RuntimeError, match=expected):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_accepts_a_bidirectional_rule_with_its_reverse():
    document = _document()
    forward = document["model"]["rules"][0]["forward"]
    reverse = copy.deepcopy(forward)
    reverse["reactants"] = forward["products"]
    reverse["products"] = forward["reactants"]
    document["model"]["rules"][0]["bidirectional"] = True
    document["model"]["rules"][0]["reverse"] = reverse
    model = _cpp._model_from_bngir_v02(document["model"])
    assert model.reaction_rules[0].is_bidirectional


def test_direct_native_builder_accepts_a_rule_modifier():
    document = _document()
    document["model"]["rules"][0]["modifiers"] = [{"kind": "total_rate"}]
    model = _cpp._model_from_bngir_v02(document["model"])
    assert list(model.reaction_rules[0].modifiers) == ["TotalRate"]


DRIVEN_SCOPED_SOURCE = r"""
begin model
begin parameters
    k 0.1
    w 2.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin reaction rules
    %x::A() -> %x::B() k driven_by(w)
end reaction rules
end model
"""


def _driven_scoped_document() -> dict:
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(DRIVEN_SCOPED_SOURCE))
    return json.loads(source_model.to_bngir(version="0.2"))


def test_native_import_round_trips_a_rule_with_driving_work_and_local_scopes():
    """A v0.2 document with a reservoir work and local scopes reproduces itself."""
    document = _driven_scoped_document()
    rule = document["model"]["rules"][0]
    assert rule["driving_work"] == {
        "kind": "parameter_ref",
        "symbol": {"kind": "parameter", "index": 1},
    }
    assert rule["forward"]["local_scopes"] == [
        {
            "name": "x",
            "kind": "species",
            "side": "reactant",
            "pattern_index": 0,
            "reactant_pattern": 0,
        }
    ]
    schema_path = (
        Path(__file__).parents[2] / "provenance" / "schemas" / "bngir-0.2.schema.json"
    )
    jsonschema.validate(document, json.loads(schema_path.read_text()))

    restored = bionetgen.from_bngir(document, native=True)

    assert json.loads(restored.to_bngir(version="0.2")) == document
    assert restored.reaction_rules[0].has_driving_work is True
    assert restored.reaction_rules[0].driving_work == "w"


def test_native_import_carries_local_scopes_and_driving_work_into_the_compiled_model():
    document = _driven_scoped_document()

    restored = bionetgen.from_bngir(document, native=True)
    snapshot = _cpp._compiled_snapshot(restored._model)

    assert snapshot["rules"][0]["forward"]["local_scopes"] == [
        {
            "name": "x",
            "kind": "species",
            "side": "reactant",
            "pattern_index": 0,
            "reactant_pattern": 0,
        }
    ]
    assert snapshot["rules"][0]["driving_work"] == {
        "kind": "parameter_ref",
        "symbol": {"kind": "parameter", "index": 1},
    }


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("kind", "unsupported native BNGIR expression kind: unresolved"),
        ("value", "expression value must be numeric"),
        ("index", "parameter reference is out of range"),
    ],
    ids=["kind", "value", "index"],
)
def test_direct_native_builder_refuses_malformed_driving_work(mutation, expected):
    document = _document()
    work = {
        "kind": "parameter_ref",
        "symbol": {"kind": "parameter", "index": 0},
    }
    if mutation == "kind":
        work = {"kind": "unresolved"}
    elif mutation == "value":
        work = {"kind": "number", "value": "fast"}
    elif mutation == "index":
        work = {
            "kind": "parameter_ref",
            "symbol": {"kind": "parameter", "index": 7},
        }
    document["model"]["rules"][0]["driving_work"] = work

    with pytest.raises(RuntimeError, match=expected):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (
            {
                "name": "x",
                "kind": "species",
                "side": "reactant",
                "pattern_index": 3,
                "reactant_pattern": 3,
            },
            "rule direction local scope pattern index is out of range",
        ),
        (
            {
                "name": "x",
                "kind": "species",
                "side": "reactant",
                "pattern_index": 0,
                "reactant_pattern": 1,
            },
            "rule direction local scope reactant pattern does not match its "
            "pattern index",
        ),
        (
            {
                "name": "x",
                "kind": "species",
                "side": "product",
                "pattern_index": 0,
                "reactant_pattern": 0,
            },
            "rule direction local scope product-side scope must not name a "
            "reactant pattern",
        ),
        (
            {
                "name": "x",
                "kind": "species",
                "side": "reactant",
                "pattern_index": 0,
                "reactant_pattern": 0,
                "molecule_occurrence": 0,
            },
            "rule direction local scope species scope must not name a molecule "
            "occurrence",
        ),
    ],
    ids=["pattern", "reactant-pattern", "product-side", "species-occurrence"],
)
def test_direct_native_builder_refuses_malformed_local_scopes(scope, expected):
    document = _document()
    document["model"]["rules"][0]["forward"]["local_scopes"] = [scope]

    with pytest.raises(RuntimeError, match=expected):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_refuses_duplicate_local_scope_names():
    document = _document()
    scope = {
        "name": "x",
        "kind": "species",
        "side": "reactant",
        "pattern_index": 0,
        "reactant_pattern": 0,
    }
    document["model"]["rules"][0]["forward"]["local_scopes"] = [scope, dict(scope)]

    with pytest.raises(RuntimeError, match="local scope names must be nonempty"):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_refuses_malformed_local_scopes():
    document = _document()
    document["model"]["rules"][0]["forward"]["local_scopes"] = [{}]
    with pytest.raises(
        RuntimeError, match="rule direction local scope is missing name"
    ):
        _cpp._model_from_bngir_v02(document["model"])


def test_direct_native_builder_refuses_unknown_direction_semantics():
    document = _document()
    document["model"]["rules"][0]["forward"]["future_semantics"] = True
    with pytest.raises(
        RuntimeError, match="rule direction has unsupported future_semantics"
    ):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize("location", ["seed", "reactant", "product"])
@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("pattern-extra", "pattern has unsupported future_semantics"),
        ("pattern-compartment", "references an unknown compartment"),
        ("prefix-integer", "compartment_prefix must be boolean"),
        ("molecule-extra", "pattern molecule has unsupported future_semantics"),
        ("molecule-compartment", "pattern molecule references an unknown compartment"),
        ("molecule-compartment-id", "pattern molecule compartment id is out of range"),
        ("occurrence-boolean", "non-boolean integer index"),
        ("occurrence-nonzero", "requires molecule occurrence zero"),
        ("type-name", "molecule type name does not match type_id"),
        ("empty-pattern", "requires exactly one molecule"),
        ("multiple-molecules", "requires exactly one molecule"),
    ],
)
def test_direct_native_builder_refuses_lossy_pattern_identity(
    location, mutation, expected
):
    document = _document()
    model = document["model"]
    pattern = (
        model["seeds"][0]["pattern"]
        if location == "seed"
        else model["rules"][0]["forward"][
            "reactants" if location == "reactant" else "products"
        ][0]
    )
    molecule = pattern["molecules"][0]
    if mutation == "pattern-extra":
        pattern["future_semantics"] = True
    elif mutation == "pattern-compartment":
        pattern["compartment"] = "cell"
    elif mutation == "prefix-true":
        pattern["compartment_prefix"] = True
    elif mutation == "prefix-integer":
        pattern["compartment_prefix"] = 0
    elif mutation == "molecule-extra":
        molecule["future_semantics"] = True
    elif mutation == "molecule-compartment":
        molecule["compartment"] = "cell"
    elif mutation == "molecule-compartment-id":
        molecule["compartment_id"] = 0
    elif mutation == "occurrence-boolean":
        molecule["occurrence"] = False
    elif mutation == "occurrence-nonzero":
        molecule["occurrence"] = 7
    elif mutation == "type-name":
        molecule["type"] = "B" if molecule["type"] == "A" else "A"
    elif mutation == "empty-pattern":
        pattern["molecules"] = []
    else:
        pattern["molecules"].append(copy.deepcopy(molecule))

    # Call the native boundary itself: Python validation/round-trip comparison
    # must not be the only protection against silently discarded graph data.
    with pytest.raises(RuntimeError, match=expected):
        _cpp._model_from_bngir_v02(model)


@pytest.mark.parametrize("type_order", [("A", "B"), ("B", "A")])
def test_native_molecule_id_reordering_preserves_downstream_rhs(
    monkeypatch, type_order
):
    document = _document()
    model = document["model"]
    declarations = {item["name"]: item for item in model["molecule_types"]}
    model["molecule_types"] = [declarations[name] for name in type_order]
    for new_id, molecule_type in enumerate(model["molecule_types"]):
        molecule_type["id"] = new_id
    patterns = [model["seeds"][0]["pattern"]]
    for side in ("reactants", "products"):
        patterns.extend(model["rules"][0]["forward"][side])
    for pattern in patterns:
        molecule = pattern["molecules"][0]
        molecule["type_id"] = type_order.index(molecule["type"])

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import rendered or parsed BNGL source")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    monkeypatch.setattr(
        importlib.import_module("bionetgen.bngir"), "_as_bngl_v02", forbidden
    )
    restored = bionetgen.from_bngir(document, native=True)
    network = restored.generate_network()
    state = [100.0 if name == "A()" else 0.0 for name in network.species_names]
    derivative = _cpp._validation_ode_rhs(restored._model, network, 0.0, state)
    assert dict(zip(network.species_names, derivative)) == pytest.approx(
        {"A()": -10.0, "B()": 10.0}
    )


def _function_document() -> dict:
    return _document(FUNCTION_SOURCE)


def _native_model_section(document: dict) -> dict:
    """The model section in the shape the native builder consumes."""
    bngir_module = importlib.import_module("bionetgen.bngir")
    model = copy.deepcopy(document["model"])
    model["observables"] = [
        {
            "name": observable["name"],
            "type": "Molecules" if observable["kind"] == "molecules" else "Species",
            "patterns": [
                bngir_module._observable_term_v02(term) for term in observable["terms"]
            ],
        }
        for observable in model["observables"]
    ]
    return model


def test_native_import_reconstructs_model_functions_and_executes(tmp_path):
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(FUNCTION_SOURCE))
    document = json.loads(source_model.to_bngir(version="0.2"))
    assert [item["name"] for item in document["model"]["functions"]] == [
        "scaled",
        "doubled",
        "_c_A",
    ]

    restored = bionetgen.from_bngir(document, native=True)

    # The reconstructed model keeps the declared functions, their arguments
    # and their bodies, so the wire document survives the round trip.
    assert json.loads(restored.to_bngir(version="0.2")) == document
    assert [(item.name, list(item.args)) for item in restored._model.functions] == [
        ("scaled", ["x"]),
        ("doubled", ["x"]),
        ("_c_A", []),
    ]

    network = restored.generate_network()
    assert network.num_species == 2
    assert network.num_reactions == 1
    assert set(network.species_names) == {"A()", "B()"}

    # The rate law runs through the reconstructed function: doubled(base) is
    # 2 * base * k, so dA/dt starts at -40.
    state = [100.0 if name == "A()" else 0.0 for name in network.species_names]
    derivative = _cpp._validation_ode_rhs(restored._model, network, 0.0, state)
    assert dict(zip(network.species_names, derivative)) == pytest.approx(
        {"A()": -40.0, "B()": 40.0}
    )

    for method in ("ode", "ssa"):
        source_result = source_model.simulate(
            method=method, t_end=0.2, n_steps=2, seed=1
        )
        restored_result = restored.simulate(method=method, t_end=0.2, n_steps=2, seed=1)
        assert restored_result.time.tolist() == pytest.approx(
            source_result.time.tolist()
        )
        for restored_row, source_row in zip(
            restored_result.concentrations, source_result.concentrations
        ):
            assert list(restored_row) == pytest.approx(list(source_row))

    # The reconstructed model writes the same trajectory the BNGL model does.
    gdat = tmp_path / "functions.gdat"
    result = restored.simulate(method="ode", t_end=0.2, n_steps=2)
    gdat.write_text(
        "\n".join(
            " ".join([f"{time:.17g}"] + [f"{value:.17g}" for value in amounts])
            for time, amounts in zip(result.time, result.concentrations)
        )
        + "\n"
    )
    source_result = source_model.simulate(method="ode", t_end=0.2, n_steps=2)
    written = [
        [float(value) for value in line.split()]
        for line in gdat.read_text().splitlines()
        if line.strip()
    ]
    assert [row[0] for row in written] == pytest.approx(
        [float(value) for value in source_result.time]
    )
    assert [row[1] for row in written] == pytest.approx(
        [float(value) for value in source_result.concentrations[:, 0]]
    )


def test_native_import_reconstructs_a_function_body_naming_an_observable():
    document = _function_document()
    assert document["model"]["functions"][2]["expression"] == {
        "kind": "observable_ref",
        "symbol": {"kind": "observable", "index": 0},
    }

    restored = bionetgen.from_bngir(document, native=True)

    assert json.loads(restored.to_bngir(version="0.2")) == document


def _function_with(name, arguments, expression):
    return {
        "id": 0,
        "name": name,
        "arguments": arguments,
        "expression": expression,
    }


def test_direct_native_builder_rejects_a_function_that_shadows_a_parameter():
    document = _function_document()
    document["model"]["functions"][0]["name"] = "k"

    with pytest.raises(
        RuntimeError,
        match="native BNGIR function names must not collide with parameter names",
    ):
        _cpp._model_from_bngir_v02(_native_model_section(document))


def test_direct_native_builder_rejects_duplicate_function_names():
    document = _function_document()
    document["model"]["functions"][1]["name"] = "scaled"

    with pytest.raises(
        RuntimeError, match="native BNGIR function names must be nonempty and unique"
    ):
        _cpp._model_from_bngir_v02(_native_model_section(document))


def test_direct_native_builder_rejects_duplicate_function_arguments():
    document = _function_document()
    document["model"]["functions"][0]["arguments"] = ["x", "x"]

    with pytest.raises(
        RuntimeError, match="native BNGIR function argument names must be unique"
    ):
        _cpp._model_from_bngir_v02(_native_model_section(document))


def test_direct_native_builder_rejects_a_local_reference_outside_the_arguments():
    document = _function_document()
    document["model"]["functions"][0]["expression"]["arguments"][0] = {
        "kind": "local_ref",
        "name": "y",
    }

    with pytest.raises(
        RuntimeError, match="native BNGIR local reference is not a function argument"
    ):
        _cpp._model_from_bngir_v02(_native_model_section(document))


def test_direct_native_builder_rejects_a_parameter_shadowed_by_an_argument():
    document = _function_document()
    document["model"]["functions"][0]["arguments"] = ["x", "k"]
    document["model"]["functions"][0]["expression"]["arguments"][1] = {
        "kind": "parameter_ref",
        "symbol": {"kind": "parameter", "index": 0},
    }

    with pytest.raises(
        RuntimeError,
        match="native BNGIR function parameter reference is shadowed by an argument",
    ):
        _cpp._model_from_bngir_v02(_native_model_section(document))


def test_direct_native_builder_rejects_a_function_call_with_the_wrong_arity():
    document = _function_document()
    document["model"]["functions"][1]["expression"]["arguments"][0]["arguments"].append(
        {"kind": "local_ref", "name": "x"}
    )

    with pytest.raises(
        RuntimeError,
        match="native BNGIR function call arity does not match the declaration",
    ):
        _cpp._model_from_bngir_v02(_native_model_section(document))


def test_direct_native_builder_rejects_an_unknown_function_reference():
    document = _function_document()
    document["model"]["functions"][1]["expression"]["arguments"][0]["symbol"][
        "index"
    ] = 7

    with pytest.raises(
        RuntimeError, match="native BNGIR function reference is out of range"
    ):
        _cpp._model_from_bngir_v02(_native_model_section(document))


@pytest.mark.parametrize(
    ("kind", "expression"),
    [
        ("builtin_call", {"kind": "builtin_call", "builtin": "sin", "arguments": []}),
        ("time_ref", {"kind": "time_ref"}),
        (
            "table_function",
            {"kind": "table_function", "x": [0.0, 1.0], "y": [0.0, 1.0]},
        ),
        ("reactant_count_ref", {"kind": "reactant_count_ref"}),
        ("unresolved", {"kind": "unresolved"}),
    ],
    ids=["builtin-call", "time-ref", "table-function", "reactant-count", "unresolved"],
)
def test_direct_native_builder_refuses_unsupported_function_bodies(kind, expression):
    document = _function_document()
    document["model"]["functions"][0]["expression"] = expression

    with pytest.raises(RuntimeError, match="unsupported native BNGIR expression kind"):
        _cpp._model_from_bngir_v02(_native_model_section(document))


def test_native_import_refuses_an_unsupported_function_body_without_fallback(
    monkeypatch,
):
    document = _function_document()
    document["model"]["functions"][0]["expression"] = {
        "kind": "builtin_call",
        "builtin": "sin",
        "arguments": [],
    }

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import fell back to the BNGL parser")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    with pytest.raises(ValueError, match="outside the supported expression subset"):
        bionetgen.from_bngir(document, native=True)


def test_native_import_refuses_a_function_that_shadows_a_parameter():
    document = _function_document()
    document["model"]["functions"][0]["name"] = "k"

    with pytest.raises(
        ValueError,
        match="native BNGIR function names must not collide with parameter names",
    ):
        bionetgen.from_bngir(document, native=True)


def test_native_import_refuses_a_rule_direction_outside_the_native_slice():
    """A second reactant pattern changes the rule's operations.

    The native importer rebuilds a direction from its patterns, so a direction
    with more than one pattern is only rebuilt faithfully when the document
    states the same operations. A copy of the first reactant pattern does not.
    """
    document = _document()
    direction = document["model"]["rules"][0]["forward"]
    direction["reactants"].append(copy.deepcopy(direction["reactants"][0]))

    with pytest.raises(ValueError, match="delete-and-add operations"):
        bionetgen.from_bngir(document, native=True)


DIMERIZATION_SOURCE = r"""
version("2.2")
setModelName("native_bngir_dimerization")
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    D()
end molecule types
begin seed species
    A() 10
    D() 0
end seed species
begin reaction rules
    dimerize: A() + A() -> D() k
end reaction rules
end model
"""


def test_native_import_reconstructs_a_multi_reactant_rule_direction():
    """Two reactant patterns rebuild the rule the document states.

    The rule consumes both reactants and creates the product, which is what
    the document's mutations state, and the reconstructed model executes with
    the same numbers as the same model written in BNGL.
    """
    document = _document(DIMERIZATION_SOURCE)
    direction = document["model"]["rules"][0]["forward"]
    assert len(direction["reactants"]) == 2
    assert document["model"]["rules"][0]["molecule_mappings"] == []
    assert {mutation["kind"] for mutation in direction["mutations"]} == {
        "delete_molecule",
        "add_molecule",
    }

    restored = bionetgen.from_bngir(document, native=True)
    assert json.loads(restored.to_bngir(version="0.2")) == document

    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(DIMERIZATION_SOURCE))
    derivatives = []
    for model in (restored, source_model):
        network = model.generate_network()
        state = [10.0 if name == "A()" else 0.0 for name in network.species_names]
        derivative = _cpp._validation_ode_rhs(model._model, network, 0.0, state)
        by_species = dict(zip(network.species_names, derivative))
        assert by_species["A()"] < 0.0
        assert by_species["D()"] > 0.0
        derivatives.append(by_species)
    # The reconstructed rule consumes both reactants and creates the product,
    # exactly as the same model written in BNGL does.
    assert derivatives[0] == pytest.approx(derivatives[1])


def test_native_import_refuses_a_multi_reactant_direction_with_a_mapping():
    """A molecule mapping cannot be rebuilt from several patterns."""
    document = _document(DIMERIZATION_SOURCE)
    document["model"]["rules"][0]["molecule_mappings"] = [
        {
            "product": {"molecule": 0, "pattern": 0, "side": "product"},
            "reactant": {"molecule": 0, "pattern": 0, "side": "reactant"},
        }
    ]

    with pytest.raises(ValueError, match="molecule mapping"):
        bionetgen.from_bngir(document, native=True)


def test_native_import_refuses_a_multi_reactant_direction_that_carries_a_molecule():
    """A product that matches a reactant type is a transformation."""
    document = _document(DIMERIZATION_SOURCE)
    product = document["model"]["rules"][0]["forward"]["products"][0]
    product["molecules"][0]["type"] = "A"
    product["molecules"][0]["type_id"] = 0

    with pytest.raises(ValueError, match="transformation"):
        bionetgen.from_bngir(document, native=True)


OBSERVABLES_SOURCE = SOURCE.replace(
    "begin seed species",
    "begin observables\n"
    "    Molecules a_count A()\n"
    "    Species b_count B()\n"
    "end observables\n"
    "begin seed species",
)


def test_native_import_reconstructs_observables():
    document = _document(OBSERVABLES_SOURCE)
    assert "observables" in document["features"]["used"]
    restored = bionetgen.from_bngir(document, native=True)
    assert [(item.name, item.type) for item in restored.observables] == [
        ("a_count", "Molecules"),
        ("b_count", "Species"),
    ]
    rebuilt = json.loads(restored.to_bngir(version="0.2"))
    assert rebuilt == document


@pytest.mark.parametrize("relation", [">", ">=", "<", "<=", "=="])
def test_native_import_reconstructs_observable_relations(relation):
    document = _document(OBSERVABLES_SOURCE)
    document["model"]["observables"][0]["terms"][0]["relation"] = relation
    document["model"]["observables"][0]["terms"][0]["quantity"] = 3
    restored = bionetgen.from_bngir(document, native=True)
    rebuilt = json.loads(restored.to_bngir(version="0.2"))
    assert rebuilt == document


def test_native_import_rejects_unknown_observable_kind():
    document = _document(OBSERVABLES_SOURCE)
    document["model"]["observables"][0]["kind"] = "unknown"
    with pytest.raises(ValueError, match="unsupported.*kind"):
        bionetgen.from_bngir(document, native=True)


def test_native_import_rejects_invalid_observable_relation():
    document = _document(OBSERVABLES_SOURCE)
    document["model"]["observables"][0]["terms"][0]["relation"] = "="
    with pytest.raises(ValueError, match="unsupported count relation"):
        bionetgen.from_bngir(document, native=True)


def test_native_import_rejects_non_dense_observable_ids():
    document = _document(OBSERVABLES_SOURCE)
    document["model"]["observables"][1]["id"] = 5
    with pytest.raises(ValueError, match="observable ids must be dense"):
        bionetgen.from_bngir(document, native=True)


def test_native_import_rejects_duplicate_observable_names():
    document = _document(OBSERVABLES_SOURCE)
    document["model"]["observables"][1]["name"] = "a_count"
    with pytest.raises(ValueError, match="duplicate"):
        bionetgen.from_bngir(document, native=True)


def test_native_import_rejects_empty_observable_terms():
    document = _document(OBSERVABLES_SOURCE)
    document["model"]["observables"][0]["terms"] = []
    with pytest.raises(ValueError, match="at least one term"):
        bionetgen.from_bngir(document, native=True)


def test_native_import_rejects_unsupported_observable_keys():
    document = _document(OBSERVABLES_SOURCE)
    document["model"]["observables"][0]["future_semantics"] = True
    with pytest.raises(ValueError, match="unsupported"):
        bionetgen.from_bngir(document, native=True)


def test_observable_python_binding_round_trips():
    """The Python-exposed Observable constructor + Model.addObservable must
    produce the same structured snapshot as a native BNGL-parsed model."""
    source = OBSERVABLES_SOURCE
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    reference = json.loads(source_model.to_bngir(version="0.2"))

    from bionetgen._bionetgen_cpp import Observable

    model = _cpp.parse_string(SOURCE)
    model.addObservable(Observable("a_count", "Molecules", ["A()"]))
    model.addObservable(Observable("b_count", "Species", ["B()"]))
    restored = bionetgen.BioNetGenModel(model)
    assert json.loads(restored.to_bngir(version="0.2")) == reference


def test_native_import_reconstructs_multi_term_observables():
    """An observable with multiple terms (e.g. A(), B()) must round-trip."""
    document = _document(OBSERVABLES_SOURCE)
    document["model"]["observables"][1]["terms"].append(
        {
            "pattern": {
                "compartment_prefix": False,
                "molecules": [
                    {"occurrence": 0, "sites": [], "type": "A", "type_id": 0}
                ],
            },
            "quantity": 0,
        }
    )
    restored = bionetgen.from_bngir(document, native=True)
    rebuilt = json.loads(restored.to_bngir(version="0.2"))
    assert rebuilt == document


def test_neq_observable_round_trips():
    """The ``!=`` count relation is supported by the C++ matcher
    (``splitObservablePattern`` / ``observablePatternCountMatches``) and is
    included in the native v0.2 accepted-relation set."""
    document = _document(OBSERVABLES_SOURCE)
    document["model"]["observables"][0]["terms"][0]["relation"] = "!="
    document["model"]["observables"][0]["terms"][0]["quantity"] = 2
    restored = bionetgen.from_bngir(document, native=True)
    rebuilt = json.loads(restored.to_bngir(version="0.2"))
    assert rebuilt == document
