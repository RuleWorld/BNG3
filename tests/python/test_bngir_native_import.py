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


def test_direct_native_builder_refuses_schema_valid_population_type():
    document = _document(POPULATION_SOURCE)
    schema_path = (
        Path(__file__).parents[2] / "provenance" / "schemas" / "bngir-0.2.schema.json"
    )
    jsonschema.validate(document, json.loads(schema_path.read_text()))
    population_type = next(
        item for item in document["model"]["molecule_types"] if item["name"] == "P"
    )
    assert population_type["population"] is True

    with pytest.raises(RuntimeError, match="population molecule types are unsupported"):
        _cpp._model_from_bngir_v02(document["model"])


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


def test_direct_native_builder_rejects_molecule_type_components():
    document = _document()
    document["model"]["molecule_types"][0]["components"] = [
        {"index": 0, "name": "x", "states": ["u", "p"]}
    ]

    with pytest.raises(RuntimeError, match="molecule type components are unsupported"):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize("location", ["seed", "reactant", "product"])
def test_direct_native_builder_rejects_molecule_sites(location):
    document = _document(SITES_SOURCE)
    model = document["model"]
    # Isolate the pattern-site boundary from the earlier molecule-type guard.
    for molecule_type in model["molecule_types"]:
        molecule_type["components"] = []

    patterns = {
        "seed": model["seeds"][0]["pattern"],
        "reactant": model["rules"][0]["forward"]["reactants"][0],
        "product": model["rules"][0]["forward"]["products"][0],
    }
    selected_sites = copy.deepcopy(patterns[location]["molecules"][0]["sites"])
    for pattern in patterns.values():
        pattern["molecules"][0]["sites"] = []
    patterns[location]["molecules"][0]["sites"] = selected_sites

    with pytest.raises(RuntimeError, match="does not support molecule sites"):
        _cpp._model_from_bngir_v02(model)


@pytest.mark.parametrize(
    ("side", "pattern_count"),
    [
        ("reactants", 0),
        ("reactants", 2),
        ("products", 0),
        ("products", 2),
    ],
    ids=["no-reactants", "extra-reactant", "no-products", "extra-product"],
)
def test_direct_native_builder_rejects_invalid_rule_pattern_counts(side, pattern_count):
    document = _document()
    direction = document["model"]["rules"][0]["forward"]
    if pattern_count == 0:
        direction[side].clear()
    else:
        direction[side].append(copy.deepcopy(direction[side][0]))

    with pytest.raises(
        RuntimeError, match="requires exactly one reactant and product pattern"
    ):
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


@pytest.mark.parametrize(
    "section",
    [
        "functions",
        "energy_patterns",
        "barrier_patterns",
        "population_maps",
        "population_types",
    ],
)
def test_direct_native_builder_rejects_nonempty_unsupported_sections(section):
    document = _document()
    unsupported_entry = (
        {
            "id": 0,
            "name": "f",
            "arguments": [],
            "expression": {"kind": "number", "value": 1.0},
        }
        if section == "functions"
        else {}
    )
    document["model"][section].append(unsupported_entry)

    with pytest.raises(
        RuntimeError, match=f"native BNGIR model.{section} is not supported"
    ):
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
    document["model"]["functions"].append(
        {
            "id": 0,
            "name": "f",
            "arguments": [],
            "expression": {"kind": "number", "value": 1.0},
        }
    )

    def forbidden(*_args, **_kwargs):
        pytest.fail("native BNGIR import fell back to the BNGL parser")

    monkeypatch.setattr(_cpp, "parse_string", forbidden)
    with pytest.raises(
        ValueError, match="native BNGIR.*functions|functions.*native BNGIR"
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
    with pytest.raises(ValueError, match="substance-unit metadata"):
        bionetgen.from_bngir(document, native=True)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("bidirectional", True, "forward ordinary rule"),
        ("bidirectional", 0, "forward ordinary rule"),
        ("modifiers", ["DeleteMolecules"], "forward ordinary rule"),
        ("reverse", {}, "unsupported reverse"),
    ],
)
def test_direct_native_builder_refuses_unrepresented_rule_semantics(
    field, value, expected
):
    document = _document()
    document["model"]["rules"][0][field] = value
    with pytest.raises(RuntimeError, match=expected):
        _cpp._model_from_bngir_v02(document["model"])


@pytest.mark.parametrize("field", ["filters", "local_scopes"])
def test_direct_native_builder_refuses_unrepresented_direction_semantics(field):
    document = _document()
    document["model"]["rules"][0]["forward"][field] = [{}]
    with pytest.raises(RuntimeError, match="filters or local scopes"):
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
