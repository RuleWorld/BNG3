"""A corpus pass requires each selected SBML record to be comparable."""

from pathlib import Path
import pytest
from bionetgen import BioNetGenModel
import bionetgen._bionetgen_cpp as cpp
from scripts.ci.validate_published_biomodels import (
    _simulate_and_compare,
    _supported_surface_passed,
)


def test_not_comparable_record_prevents_supported_surface_pass():
    assert not _supported_surface_passed(
        partial=False,
        counts_match=True,
        failed_records=0,
        harness_error_records=0,
        timeout_records=0,
        not_comparable_records=1,
    )


def test_complete_compared_surface_passes_and_hard_nonpasses_do_not():
    arguments = {
        "partial": False,
        "counts_match": True,
        "failed_records": 0,
        "harness_error_records": 0,
        "timeout_records": 0,
        "not_comparable_records": 0,
    }
    assert _supported_surface_passed(**arguments)
    for key in (
        "partial",
        "failed_records",
        "harness_error_records",
        "timeout_records",
    ):
        altered = arguments.copy()
        altered[key] = True if key == "partial" else 1
        assert not _supported_surface_passed(**altered)


def test_action_trajectory_beyond_t_end_is_sliced_to_requested_horizon():
    sbml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="test_horizon" timeUnits="second">
    <listOfCompartments>
      <compartment id="cell" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialConcentration="10" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="deg" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math>
          <listOfLocalParameters>
            <localParameter id="k" value="1.0"/>
          </listOfLocalParameters>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""
    action_bngl = """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10.0
end seed species
begin observables
  Molecules A A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
simulate({method=>"ode",t_end=>1.0,n_steps=>10})
simulate({method=>"ode",t_start=>1.0,t_end=>5.0,n_steps=>10,continue=>1})
"""
    result = _simulate_and_compare(
        None,
        BioNetGenModel,
        Path("test.sbml"),
        t_end=1.0,
        n_steps=10,
        rtol=1e-4,
        atol=1e-6,
        reference_model=sbml,
        action_bngl=action_bngl,
        action_model_parser=cpp.parse_string,
        reference_selections={"A": "A"},
    )
    assert result.get("passed") is True

