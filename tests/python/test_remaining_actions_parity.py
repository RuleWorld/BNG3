"""Focused regression tests for remaining BNG2 action parity fixes."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

import bionetgen

BASE_MODEL = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() -> B() k
end reaction rules
end model
"""

SBML_DECAY = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="sbml_decay">
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters><parameter id="k" value="0.5" constant="true"/></listOfParameters>
    <listOfReactions>
      <reaction id="r1" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>A</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""


def _read_last_row(gdat: Path) -> list[float]:
    lines = [
        line.strip()
        for line in gdat.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return [float(tok) for tok in lines[-1].split()]


def test_read_model_recompiles_generator_and_simulates(tmp_path: Path) -> None:
    (tmp_path / "sub.bngl").write_text(BASE_MODEL, encoding="utf-8")
    driver = tmp_path / "driver.bngl"
    driver.write_text(
        'readModel({file=>"sub.bngl"})\n'
        "generate_network({overwrite=>1})\n"
        'simulate({method=>"ode",t_end=>2,n_steps=>4})\n',
        encoding="utf-8",
    )
    bionetgen.load(str(driver)).execute()
    row = _read_last_row(tmp_path / "driver.gdat")
    assert math.isclose(row[1], 10.0 * math.exp(-1.0), rel_tol=1e-5)
    assert math.isclose(row[2], 10.0 * (1.0 - math.exp(-1.0)), rel_tol=1e-5)


def test_set_model_name_sets_default_output_prefix(tmp_path: Path) -> None:
    model_path = tmp_path / "input.bngl"
    model_path.write_text(
        'setModelName("renamed_model");\n'
        + BASE_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'simulate({method=>"ode",t_end=>2,n_steps=>4})\n',
        encoding="utf-8",
    )
    bionetgen.load(str(model_path)).execute()
    assert (tmp_path / "renamed_model.net").is_file()
    assert (tmp_path / "renamed_model.gdat").is_file()
    row = _read_last_row(tmp_path / "renamed_model.gdat")
    assert math.isclose(row[1], 10.0 * math.exp(-1.0), rel_tol=1e-5)


def test_print_net_writes_save_net_with_prefix(tmp_path: Path) -> None:
    model_path = tmp_path / "m.bngl"
    model_path.write_text(
        BASE_MODEL
        + "generate_network({overwrite=>1})\n"
        + 'simulate({method=>"ode",t_end=>2,n_steps=>4,prefix=>"p1",print_net=>1})\n',
        encoding="utf-8",
    )
    bionetgen.load(str(model_path)).execute()
    assert (tmp_path / "m.net").is_file()
    assert (tmp_path / "p1_save.net").is_file()


def test_simulate_protocol_honors_prefix(tmp_path: Path) -> None:
    model_path = tmp_path / "m.bngl"
    model_path.write_text(
        BASE_MODEL.replace(
            "end model",
            'begin protocol\n  simulate({method=>"ode",t_end=>2,n_steps=>4})\nend protocol\nend model',
        )
        + "generate_network({overwrite=>1})\n"
        + 'simulate_protocol({prefix=>"proto_run"})\n',
        encoding="utf-8",
    )
    bionetgen.load(str(model_path)).execute()
    assert (tmp_path / "proto_run.gdat").is_file()
    row = _read_last_row(tmp_path / "proto_run.gdat")
    assert math.isclose(row[1], 10.0 * math.exp(-1.0), rel_tol=1e-5)


def test_read_nf_species_overrides_initial_concentrations(tmp_path: Path) -> None:
    (tmp_path / "init.species").write_text(
        "# species\nA() 7\nB() 3\n", encoding="utf-8"
    )
    model_path = tmp_path / "m.bngl"
    model_path.write_text(
        BASE_MODEL
        + 'readNFspecies("init.species")\n'
        + "generate_network({overwrite=>1})\n"
        + 'simulate({method=>"ode",t_end=>2,n_steps=>4})\n',
        encoding="utf-8",
    )
    bionetgen.load(str(model_path)).execute()
    row = _read_last_row(tmp_path / "m.gdat")
    assert math.isclose(row[1], 7.0 * math.exp(-1.0), rel_tol=1e-5)
    assert math.isclose(row[2], 3.0 + 7.0 * (1.0 - math.exp(-1.0)), rel_tol=1e-5)


def test_read_sbml_loads_xml_and_simulates(tmp_path: Path) -> None:
    (tmp_path / "decay.xml").write_text(SBML_DECAY, encoding="utf-8")
    driver = tmp_path / "driver.bngl"
    driver.write_text(
        'readSBML({file=>"decay.xml",basename=>"from_sbml"})\n'
        'simulate({method=>"ode",t_end=>2,n_steps=>4})\n',
        encoding="utf-8",
    )
    bionetgen.load(str(driver)).execute()
    assert (tmp_path / "from_sbml.cdat").is_file()
    row = _read_last_row(tmp_path / "from_sbml.cdat")
    assert math.isclose(row[1], 10.0 * math.exp(-1.0), rel_tol=1e-5)
    assert math.isclose(row[2], 10.0 * (1.0 - math.exp(-1.0)), rel_tol=1e-5)


def test_lps_net_file_and_codename_rejection(tmp_path: Path) -> None:
    rev_path = tmp_path / "rev.bngl"
    rev_path.write_text(
        BASE_MODEL.replace("A() -> B() k", "A() <-> B() k, 0.2")
        + "generate_network({overwrite=>1})\n"
        + 'LinearParameterSensitivity({net_file=>"rev",t_end=>2,n_steps=>4,init_equil=>1,re_equil=>1,t_equil=>100})\n',
        encoding="utf-8",
    )
    bionetgen.load(str(rev_path)).execute()
    row = _read_last_row(tmp_path / "rev_k_.gdat")
    expected_a = 10.0 * (0.2 / (0.5 * 1.05 + 0.2))
    assert math.isclose(row[1], expected_a, rel_tol=1e-5)

    code_path = tmp_path / "code.bngl"
    code_path.write_text(
        BASE_MODEL + 'codename("unknown_codename")\n', encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="codename"):
        bionetgen.load(str(code_path)).execute()
