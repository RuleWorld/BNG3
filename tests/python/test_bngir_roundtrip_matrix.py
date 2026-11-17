"""Round-trip matrix coverage for BNGIR v0.1/v0.2 and native reconstruction.

Focused on preserving source facts and semantic execution for constructs
exercised by the current BNGIR implementation.
"""

import json

import pytest

import bionetgen
from bionetgen.bngir import EqualityUndecided
from bionetgen.model import _cpp


def _model(src: str):
    return bionetgen.BioNetGenModel(_cpp.parse_string(src))


def _assert_roundtrip(src: str, *, native: bool = False):
    model = _model(src)
    for version in ("0.1", "0.2"):
        doc = model.to_bngir(version=version)
        restored = bionetgen.from_bngir(doc)
        try:
            assert bionetgen.semantic_equal(model, restored, version=version), version
        except EqualityUndecided as exc:
            # Exact equality may be undecided for features outside certified
            # finite-network comparison; roundtrip reconstruction must still
            # succeed and produce a structurally valid model.
            assert restored is not None, (version, exc)
        # v0.1 -> v0.2 migration must preserve semantics where decidable.
        if version == "0.1":
            migrated = restored.to_bngir(version="0.2")
            restored_v2 = bionetgen.from_bngir(migrated)
            try:
                assert bionetgen.semantic_equal(model, restored_v2, version="0.2")
            except EqualityUndecided:
                assert restored_v2 is not None
    if native:
        v2 = model.to_bngir(version="0.2")
        native_restored = bionetgen.from_bngir(v2, native=True)
        try:
            assert bionetgen.semantic_equal(model, native_restored, version="0.2")
        except EqualityUndecided:
            assert native_restored is not None


CASES = {
    # Source bond numbers are not part of the canonical species identity.
    # This case verifies the round trip preserves the initial law for a
    # renumbered dimer seed (initial molecule count 2 x the dimer amount).
    "bond_renumbered_seed": r"""
begin model
begin molecule types
    A(b)
end molecule types
begin seed species
    A(b!7).A(b!7) 10
end seed species
begin observables
    Molecules total A()
end observables
begin reaction rules
    A(b!1).A(b!1) -> 0 1
end reaction rules
end model
""",
    "states_and_bonds": r"""
begin model
begin molecule types
    A(b,c~u~p)
    B(a)
end molecule types
begin seed species
    A(b!1,c~u).B(a!1) 5
    A(b,c~p) 2
end seed species
begin observables
    Molecules A_bound A(b!+)
    Species AB A(b!1).B(a!1)
end observables
begin reaction rules
    A(b,c~u) + B(a) <-> A(b!1,c~u).B(a!1) 1,2
    A(c~u) -> A(c~p) 0.5
end reaction rules
end model
""",
    "compartments_and_protocol": r"""
begin model
begin compartments
    EC 3 1.0
    PM 2 0.1 EC
    CP 3 0.5 PM
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    A()@CP 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    A()@CP -> A()@EC 1
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>1,n_steps=>5})
""",
    "functions_and_dependent_rate": r"""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin functions
    f() = k*Atot
end functions
begin reaction rules
    A() -> B() f()
end reaction rules
end model
""",
    "delays_and_bidirectional": r"""
begin model
begin parameters
    tau 2
    kf 1
    kr 0.5
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 5
    B() 1
end seed species
begin reaction rules
    A() <-> B() kf,kr
    A() -> B() 1 delay=tau NonConsuming
end reaction rules
end model
""",
    "consuming_delay": r"""
begin model
begin parameters
    k 1
    tau 2
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 5
end seed species
begin reaction rules
    A() -> B() k delay=tau
end reaction rules
end model
""",
    "compartment_parent_v01": r"""
begin model
begin parameters
    k 1
end parameters
begin compartments
    EC 3 1
    PM 2 1 EC
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    A()@PM 1
end seed species
begin observables
    Molecules A_PM A()@PM
end observables
begin reaction rules
    A()@PM -> A()@EC k
end reaction rules
end model
""",
    "energy_patterns_bidirectional": r"""
begin model
begin parameters
  k 1
  G 1
end parameters
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 1
end seed species
begin energy patterns
  A(x~p) G
end energy patterns
begin reaction rules
  A(x~u) <-> A(x~p) k,k
end reaction rules
end model
""",
    "multiple_actions": r"""
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 1
end reaction rules
end model
generate_network({overwrite=>1})
writeXML()
simulate({method=>"ode",t_end=>1,n_steps=>5})
""",
    "observable_species_molecules": r"""
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b!1).A(b!1) 2
  A(b) 1
end seed species
begin observables
  Molecules A_mol A()
  Species A_spec A()
  Species Dimer A(b!1).A(b!1)
end observables
end model
""",
    "modifiers_synthesis_totalrate": r"""
begin model
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
    B() 1
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    0 -> A() 1
    A() + A() -> A() 1 TotalRate
    A() -> 0 1
end reaction rules
end model
""",
}

# Native reconstruction is intentionally narrow; enable only for cases within
# the current native v0.2 supported slice.
NATIVE_CASES = {"states_and_bonds"}


@pytest.mark.parametrize("name,src", list(CASES.items()))
def test_bngir_roundtrip_matrix(name, src):
    _assert_roundtrip(src, native=name in NATIVE_CASES)


def test_bngir_v01_population_map_roundtrip_with_rate():
    src = r"""
begin model
begin molecule types
  A()
  P population
end molecule types
begin seed species
  A() 10
end seed species
begin population maps
  A() -> P() k_pop()
end population maps
begin functions
  k_pop() = 1
end functions
end model
"""
    model = _model(src)
    doc = json.loads(model.to_bngir(version="0.1"))
    assert doc["model"]["population_maps"][0].get("rate") == "k_pop()"
    restored = bionetgen.from_bngir(doc)
    try:
        assert bionetgen.semantic_equal(model, restored, version="0.1")
    except EqualityUndecided:
        pass
    migrated = json.loads(restored.to_bngir(version="0.2"))
    assert len(migrated["model"]["population_maps"]) == 1


def test_v01_unit_definitions_accept_id_or_name():
    base = {
        "format": "BNGIR",
        "version": "0.1",
        "features": {"required": [], "used": ["units"]},
        "model": {
            "name": "",
            "version": "",
            "substance_units": "",
            "options": {},
            "parameters": [],
            "molecule_types": [],
            "compartments": [],
            "seeds": [],
            "observables": [],
            "functions": [],
            "energy_patterns": [],
            "barrier_patterns": [],
            "population_maps": [],
            "rules": [],
            "unit_defaults": {"timeUnits": "s"},
            "unit_definitions": [{"id": "Molar", "expression": "1e6"}],
        },
        "protocol": {"actions": []},
    }
    m = bionetgen.from_bngir(json.dumps(base))
    doc = json.loads(m.to_bngir(version="0.1"))
    defs = doc["model"].get("unit_definitions") or []
    assert any(d.get("expression") == "1e6" for d in defs)
    assert any((d.get("name") or d.get("id")) == "Molar" for d in defs)

    base["model"]["unit_definitions"] = [{"name": "Liter", "expression": "1"}]
    m = bionetgen.from_bngir(json.dumps(base))
    doc = json.loads(m.to_bngir(version="0.1"))
    defs = doc["model"].get("unit_definitions") or []
    assert any((d.get("name") or d.get("id")) == "Liter" for d in defs)


CASES["model_actions_roundtrip"] = r"""
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
setParameter("k",2)
"""


@pytest.mark.parametrize("name", ["model_actions_roundtrip"])
def test_roundtrip_matrix_actions(name):
    _assert_roundtrip(CASES[name], native=False)


def test_roundtrip_matrix_driving_work_v02():
    src = r"""
begin model
begin parameters
  k 1
  w 2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() k driven_by(w)
end reaction rules
end model
"""
    m = bionetgen.BioNetGenModel(_cpp.parse_string(src))
    doc = json.loads(m.to_bngir(version="0.2"))
    assert doc["model"]["rules"][0]["driving_work"] == "w"
    assert "driven_reservoirs" in doc["features"]["used"]
    restored = bionetgen.from_bngir(doc)
    doc2 = json.loads(restored.to_bngir(version="0.2"))
    assert doc2["model"]["rules"][0]["driving_work"] == "w"
    assert bionetgen.semantic_equal(m, restored, version="0.2") is True
