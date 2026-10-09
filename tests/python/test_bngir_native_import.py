"""Behavioral contract for the explicit parser-free BNGIR v0.2 import route."""

from __future__ import annotations

import copy
import importlib
import json

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


def _document(source: str = SOURCE) -> dict:
    source_model = bionetgen.BioNetGenModel(_cpp.parse_string(source))
    return json.loads(source_model.to_bngir(version="0.2"))


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
    assert bionetgen.semantic_equal(source_model, restored, version="0.2")


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
        ("pattern", False, "molecule mutation reference"),
        ("molecule", 0.0, "molecule reference is out of range"),
        ("molecule", False, "molecule mutation reference"),
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
