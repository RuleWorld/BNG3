"""Qualification tests for documented migration guide workflows and examples.

Verifies the migration workflows documented in docs/migration_guide.md:
- bionetgen.load(path)
- model.simulate(method="ode", t_end=...)
- result inspection: result.time, result.observables, result.to_dataframe()
- parameter scan: model.parameter_scan(parameter=..., values=...)
- programmatic model building: ModelBuilder
- SBML import: bionetgen.from_sbml(...)
- file runner: bionetgen.run(path, out=...) and positional forms
- CLI entry points
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import bionetgen
from bionetgen.builder import ModelBuilder


TEST_BNGL = """begin model
begin parameters
  k_on 1.0
  k_off 0.1
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 100
  B(a) 200
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
  Molecules A_free A(b)
  Molecules B_free B(a)
end observables
begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) k_on, k_off
end reaction rules
end model
"""


def test_migration_guide_load_and_simulate(tmp_path: Path):
    """Section 'Before And After' -> 'Load A Model' & 'Run A Simulation'."""
    model_path = tmp_path / "model.bngl"
    model_path.write_text(TEST_BNGL, encoding="utf-8")

    # Migration syntax:
    model = bionetgen.load(str(model_path))
    assert model is not None
    assert len(model.parameters) == 2
    assert len(model.observables) == 3

    result = model.simulate(method="ode", t_end=10.0, n_steps=20)
    assert result is not None
    assert len(result.time) == 21
    assert "AB" in result.observables
    assert len(result.observables["AB"]) == 21


def test_migration_guide_inspect_results(tmp_path: Path):
    """Section 'Before And After' -> 'Inspect Results'."""
    model_path = tmp_path / "model.bngl"
    model_path.write_text(TEST_BNGL, encoding="utf-8")

    model = bionetgen.load(str(model_path))
    result = model.simulate(method="ode", t_end=10.0, n_steps=20)

    # Accessors documented in guide:
    time_arr = np.asarray(result.time)
    ab_arr = np.asarray(result.observables["AB"])
    assert time_arr[0] == 0.0
    assert time_arr[-1] == 10.0
    assert ab_arr[0] == 0.0
    assert ab_arr[-1] > 0.0

    df = result.to_dataframe()
    assert "time" in df.columns
    assert "AB" in df.columns
    assert len(df) == 21


def test_migration_guide_parameter_scan(tmp_path: Path):
    """Section 'Before And After' -> 'Parameter Scans'."""
    model_path = tmp_path / "model.bngl"
    model_path.write_text(TEST_BNGL, encoding="utf-8")

    model = bionetgen.load(str(model_path))
    scan = model.parameter_scan(
        parameter="k_on",
        values=np.logspace(-1, 1, 5),
        method="ode",
        t_end=5.0,
    )
    assert scan is not None
    final_ab = scan.final("AB")
    assert len(final_ab) == 5
    # Higher k_on should yield higher bound complex AB
    assert final_ab[-1] > final_ab[0]


def test_migration_guide_sbml_import(tmp_path: Path):
    """Section 'Before And After' -> 'SBML Import'."""
    sbml_xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="simple_conversion">
    <listOfCompartments>
      <compartment id="cell" size="1.0" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialAmount="10.0" hasOnlySubstanceUnits="true" constant="false"/>
      <species id="S2" compartment="cell" initialAmount="0.0" hasOnlySubstanceUnits="true" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="0.5" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="S2" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k1</ci><ci>S1</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    sbml_file = tmp_path / "model.xml"
    sbml_file.write_text(sbml_xml, encoding="utf-8")
    model = bionetgen.from_sbml(str(sbml_file), atomize=True)
    assert model is not None
    result = model.simulate(method="ode", t_end=2.0, n_steps=10)
    assert result is not None
    assert len(result.time) == 11


def test_migration_guide_model_builder():
    """Section 'Before And After' -> 'Programmatic Model Building'."""
    builder = ModelBuilder("MyModel")
    builder.add_parameter("k_on", 1.0)
    builder.add_parameter("k_off", 0.1)
    builder.add_molecule_type("A(b)")
    builder.add_molecule_type("B(a)")
    builder.add_seed_species("A(b)", 100)
    builder.add_seed_species("B(a)", 200)
    builder.add_observable("Molecules", "AB", "A(b!1).B(a!1)")
    builder.add_rule("A(b) + B(a) -> A(b!1).B(a!1)", "k_on")
    builder.add_rule("A(b!1).B(a!1) -> A(b) + B(a)", "k_off")

    model = builder.build()
    assert model is not None
    result = model.simulate(method="ode", t_end=5.0, n_steps=10)
    assert result is not None
    assert "AB" in result.observables


def test_migration_guide_file_runner_and_positional(tmp_path: Path):
    """Section 'Python and CLI Run Contracts'."""
    model_path = tmp_path / "model.bngl"
    model_path.write_text(TEST_BNGL, encoding="utf-8")

    # Positional method and grid on single simulation:
    result = bionetgen.run(str(model_path), "ode", 5.0, 10)
    assert hasattr(result, "observables")

    # File runner with output directory:
    out_dir = tmp_path / "results"
    bng_res = bionetgen.run(str(model_path), out=str(out_dir))
    assert bng_res is not None


def test_cli_version_and_help():
    """CLI smoke test for packaging qualification."""
    proc_version = subprocess.run(
        [sys.executable, "-m", "bionetgen.cli", "--version"],
        capture_output=True,
        text=True,
    )
    assert proc_version.returncode == 0
    assert "3.0" in proc_version.stdout or "bionetgen" in proc_version.stdout

    proc_help = subprocess.run(
        [sys.executable, "-m", "bionetgen.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert proc_help.returncode == 0
    assert "Usage:" in proc_help.stdout
