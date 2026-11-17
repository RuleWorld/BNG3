"""Static compartment symbols must not leak into native event values or fluxes."""

import re

import libsbml
import pytest
from _extdep import require_extension

from bionetgen.atomizer.modern import Atomizer

cpp = require_extension()


def _source(*, piecewise=False, compartment_size=2.0, rate_rule=False):
    increment = (
        "<apply><plus/><ci>S</ci>"
        "<apply><divide/><cn>1</cn><ci>cell</ci></apply></apply>"
    )
    value = (
        f"<piecewise><piece>{increment}"
        "<apply><gt/><ci>S</ci><cn>0</cn></apply></piece>"
        "<otherwise><cn>0</cn></otherwise></piecewise>"
        if piecewise
        else increment
    )
    rules = ""
    if rate_rule:
        rules = (
            '<listOfRules><rateRule variable="cell">'
            '<math xmlns="http://www.w3.org/1998/Math/MathML">'
            "<cn>0.1</cn></math></rateRule></listOfRules>"
        )
    constant = "false" if rate_rule else "true"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="static_event_compartment" timeUnits="second">
 <listOfCompartments><compartment id="cell" size="{compartment_size}" constant="{constant}"/></listOfCompartments>
 <listOfSpecies><species id="S" compartment="cell" initialConcentration="0"
   hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/></listOfSpecies>
 <listOfReactions><reaction id="inflow" reversible="false">
  <listOfProducts><speciesReference species="S" stoichiometry="1" constant="true"/></listOfProducts>
  <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>cell</ci></math></kineticLaw>
 </reaction>
 <reaction id="outflow" reversible="false">
  <listOfReactants><speciesReference species="S" stoichiometry="1" constant="true"/></listOfReactants>
  <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply><times/><ci>cell</ci><apply><power/><ci>S</ci><cn>3</cn></apply></apply>
  </math></kineticLaw>
 </reaction></listOfReactions>
 {rules}
 <listOfEvents><event id="pulse" useValuesFromTriggerTime="true">
  <trigger initialValue="false" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply><gt/><ci>S</ci><cn>0.5</cn></apply>
  </math></trigger>
  <listOfEventAssignments><eventAssignment variable="S">
   <math xmlns="http://www.w3.org/1998/Math/MathML">{value}</math>
  </eventAssignment></listOfEventAssignments>
 </event></listOfEvents>
</model></sbml>"""


def _atomize(source):
    document = libsbml.readSBMLFromString(source)
    document.checkConsistency()
    errors = [
        document.getError(i).getMessage()
        for i in range(document.getNumErrors())
        if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors
    result = Atomizer(atomize=False, quiet_mode=True).atomize(source)
    assert result.success, result.error
    return result


@pytest.mark.parametrize("piecewise", [False, True], ids=["arithmetic", "piecewise"])
@pytest.mark.parametrize("compartment_size", [2.0, 4.0])
def test_static_compartment_is_inlined_in_native_event_value(
    piecewise, compartment_size
):
    result = _atomize(_source(piecewise=piecewise, compartment_size=compartment_size))
    assignments = [
        line.strip() for line in result.bngl.splitlines() if "assignment:" in line
    ]
    assert len(assignments) == 1
    assignment = assignments[0]
    # The compartment id is not a scalar and the native runtime rejects it as
    # an unresolved denominator; its constant size must be inlined instead.
    assert "cell" not in assignment
    assert (
        f"/ {compartment_size:g}" in assignment or f"/ {compartment_size}" in assignment
    )
    model = cpp.parse_string(result.bngl)
    cpp.generate_network(model, max_iter=5)


@pytest.mark.parametrize("compartment_size", [2.0, 4.0])
def test_explicit_compartment_flux_is_not_dropped(compartment_size):
    source = re.sub(
        r"<listOfEvents>.*?</listOfEvents>",
        "",
        _source(compartment_size=compartment_size),
        flags=re.S,
    )
    result = _atomize(source)
    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=5)
    # The outflow law is "cell * S^3"; its compartment factor is part of the
    # SBML amount/time flux.  It must survive lowering, not be stripped while
    # no mass-action constant can carry the volume correction.
    rate_laws = list(network.reaction_rate_laws)
    assert len(rate_laws) == 2
    assert any("compartment_cell" in law and "3" in law for law in rate_laws), rate_laws


def test_dynamic_compartment_is_never_frozen_to_a_literal():
    result = _atomize(_source(compartment_size=2.0, rate_rule=True))
    assignments = [
        line.strip() for line in result.bngl.splitlines() if "assignment:" in line
    ]
    # A size governed by a rate rule is dynamic: it must not be replaced by a
    # static literal.  The native event lowering declines in that case.
    assert not assignments
    assert "begin bng3_events" not in result.bngl
