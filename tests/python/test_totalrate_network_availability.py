"""Finite-network TotalRate channels retain canonical reactant availability."""

from __future__ import annotations

import pytest

from _extdep import require_extension

cpp = require_extension()

MODEL = """
begin model
begin parameters
    k_init 1
    k_elong 1
    k_term 1
end parameters
begin molecule types
    mrna(p0~free~blocked,p1,p2)
    ribosome(asite)
end molecule types
begin seed species
    mrna(p0~free,p1,p2) 1
    ribosome(asite) 5
end seed species
begin observables
    Molecules rib_elong ribosome(asite!1).mrna(p1,p2!1)
end observables
begin reaction rules
    initiate: ribosome(asite) + mrna(p0~free) -> ribosome(asite!1).mrna(p0~blocked!1) k_init TotalRate
    elongate_1: ribosome(asite!1).mrna(p0~blocked!1,p1) -> ribosome(asite!1).mrna(p0~free,p1!1) k_elong
    elongate_2: ribosome(asite!1).mrna(p1!1,p2) -> ribosome(asite!1).mrna(p1,p2!1) k_elong
    terminate: ribosome(asite!1).mrna(p2!1) -> ribosome(asite) + mrna(p2) k_term
end reaction rules
end model
"""


def _molecule_total(species_names, values, molecule_type):
    return sum(
        float(value) * species_name.count(f"{molecule_type}(")
        for species_name, value in zip(species_names, values)
    )


def test_totalrate_reaction_cannot_fire_without_finite_network_reactants():
    ode_model = cpp.parse_string(MODEL)
    ode_network = cpp.generate_network(ode_model)
    ode = cpp.simulate_ode(ode_model, ode_network, t_end=20.0, n_steps=40)
    assert min(ode["observables"]["rib_elong"]) >= -1e-8
    assert max(ode["observables"]["rib_elong"]) <= 1.0 + 1e-8
    for row in ode["concentrations"]:
        assert _molecule_total(ode_network.species_names, row, "mrna") == pytest.approx(1.0)
        assert _molecule_total(ode_network.species_names, row, "ribosome") == pytest.approx(5.0)

    ssa_model = cpp.parse_string(MODEL)
    ssa_network = cpp.generate_network(ssa_model)
    ssa = cpp.simulate_ssa(ssa_model, ssa_network, t_end=20.0, n_steps=40, seed=21001)
    for row in ssa["concentrations"]:
        assert _molecule_total(ssa_network.species_names, row, "mrna") == 1.0
        assert _molecule_total(ssa_network.species_names, row, "ribosome") == 5.0


def test_absolute_flux_ssa_still_requires_stoichiometric_availability():
    source = '''setOption("BNG3AbsoluteFluxRules", "r")
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
  B() 0
end seed species
begin reaction rules
  r: A() + A() -> B() k TotalRate
end reaction rules
end model'''
    model = cpp.parse_string(source)
    network = cpp.generate_network(model)
    result = cpp.simulate_ssa(model, network, t_end=5.0, n_steps=10, seed=21001)

    assert max(result["concentrations"][i][network.species_names.index("B()")]
               for i in range(len(result["concentrations"]))) == 0.0


def test_atomizer_full_flux_metadata_reaches_native_execution():
    from bionetgen.atomizer.modern import Atomizer

    source = '''<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="absolute_flux">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true" constant="false"/>
          <species id="B" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J" reversible="false">
            <listOfReactants><speciesReference species="A"/></listOfReactants>
            <listOfProducts><speciesReference species="B"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>'''
    result = Atomizer(atomize=False, quiet_mode=True).atomize(source)
    assert result.success, result.error
    assert 'setOption("BNG3AbsoluteFluxRules","J")' in result.bngl

    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model)
    trajectory = cpp.simulate_ode(model, network, t_end=0.1, n_steps=1)
    initial, final = trajectory["concentrations"]
    assert _molecule_total(network.species_names, initial, "A") == pytest.approx(1.0)
    assert _molecule_total(network.species_names, final, "A") == pytest.approx(0.9)
    assert _molecule_total(network.species_names, final, "B") == pytest.approx(0.1)


def test_absolute_flux_metadata_survives_native_bngir_roundtrip():
    import bionetgen

    source = '''setOption("BNG3AbsoluteFluxRules", "J")
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 1
end seed species
begin reaction rules
  J: A() -> B() k TotalRate
end reaction rules
end model'''
    parsed = bionetgen.BioNetGenModel(cpp.parse_string(source))

    import json

    document = json.loads(parsed.to_bngir(version="0.2"))
    assert document["model"]["metadata"]["options"]["BNG3AbsoluteFluxRules"] == "J"
    with pytest.raises(ValueError, match="does not support BNG3AbsoluteFluxRules"):
        bionetgen.from_bngir(document, native=True)

    restored = bionetgen.from_bngir(document)
    assert json.loads(restored.to_bngir(version="0.2")) == document

    network = restored.generate_network()
    trajectory = restored.simulate(method="ode", t_end=0.1, n_steps=1)
    initial, final = trajectory.concentrations
    assert _molecule_total(network.species_names, initial, "A") == pytest.approx(1.0)
    assert _molecule_total(network.species_names, final, "A") == pytest.approx(0.9)
    assert _molecule_total(network.species_names, final, "B") == pytest.approx(0.1)


def test_imported_sbml_flux_survives_sbml_and_net_channel_roundtrips(tmp_path):
    import bionetgen

    source = tmp_path / "absolute.xml"
    source.write_text('''<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
        xmlns:bng="https://bionetgen.org/sbml" level="3" version="2">
      <model id="absolute_flux">
        <listOfCompartments><compartment id="C" size="1" constant="true"/></listOfCompartments>
        <listOfSpecies>
          <species id="A" compartment="C" initialAmount="2" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
          <species id="B" compartment="C" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
        </listOfSpecies>
        <listOfReactions>
          <reaction id="J" reversible="false">
            <annotation><bng:absoluteFlux/></annotation>
            <listOfReactants><speciesReference species="A" stoichiometry="2" constant="true"/></listOfReactants>
            <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
            <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>''', encoding="utf-8")

    imported = tmp_path / "import.bngl"
    imported.write_text('''begin model
end model
begin actions
  readFile({file=>"absolute.xml"})
  writeSBML({suffix=>"roundtrip"})
  writeNetwork({prefix=>"absolute",overwrite=>1})
  simulate_ode({prefix=>"sbml_import",t_start=>0,t_end=>0.1,n_steps=>1,print_CDAT=>1})
end actions
''', encoding="utf-8")
    bionetgen.load(str(imported)).execute()

    net_path = tmp_path / "absolute.net"
    assert 'setOption("BNG3AbsoluteFluxReactionIndices","1")' in net_path.read_text()
    roundtrip_sbml = tmp_path / "import_roundtrip.xml"
    assert "bng:absoluteFlux" in roundtrip_sbml.read_text()

    reimported = tmp_path / "reimport.bngl"
    reimported.write_text('''begin model
end model
begin actions
  readFile({file=>"absolute.net"})
  simulate_ode({prefix=>"net_import",t_start=>0,t_end=>0.1,n_steps=>1,print_CDAT=>1})
end actions
''', encoding="utf-8")
    bionetgen.load(str(reimported)).execute()

    def final_species(prefix):
        rows = [
            line.split()
            for line in (tmp_path / f"{prefix}.cdat").read_text().splitlines()
            if line and not line.startswith("#")
        ]
        return [float(value) for value in rows[-1][1:]]

    assert final_species("sbml_import") == pytest.approx([1.8, 0.1])
    assert final_species("net_import") == pytest.approx([1.8, 0.1])


@pytest.mark.parametrize(
    ("indices", "message"),
    [("1,1", "duplicate"), ("2", "outside the reaction table")],
)
def test_net_absolute_flux_indices_fail_closed(tmp_path, indices, message):
    import bionetgen

    (tmp_path / "invalid.net").write_text(f'''setOption("BNG3AbsoluteFluxReactionIndices","{indices}")
begin species
    1 A() 1
    2 B() 0
end species
begin reactions
    1 1 2 1
end reactions
''', encoding="utf-8")
    protocol = tmp_path / "invalid.bngl"
    protocol.write_text('''begin model
end model
begin actions
  readFile({file=>"invalid.net"})
end actions
''', encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        bionetgen.load(str(protocol)).execute()

