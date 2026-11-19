"""Focused regressions for SBML compartment-volume kinetic lowering.

Verifies that elementary reaction rules in non-unit compartments do not
duplicate the compartment volume factor when rate parameters are governed by
assignment rules, rate rules, or time expressions. Also verifies contrasting
models where non-elementary explicit volume factors must survive as complete
TotalRate fluxes.
"""

from pathlib import Path
import re

import libsbml
import numpy as np
import pytest
import roadrunner
from _extdep import require_extension

from bionetgen.atomizer.modern import Atomizer

cpp = require_extension()

_SSTS_DIR = Path("/private/tmp/official-ssts")


def _atomize(source: str, *, atomize: bool = False):
    document = libsbml.readSBMLFromString(source)
    document.checkConsistency()
    errors = [
        document.getError(i).getMessage()
        for i in range(document.getNumErrors())
        if document.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert not errors, errors
    result = Atomizer(atomize=atomize, quiet_mode=True).atomize(source)
    assert result.success, result.error
    return result


@pytest.mark.parametrize("atomize", [False, True], ids=["flat", "atomized"])
@pytest.mark.parametrize("compartment_size", [0.5, 2.5, 9.8])
def test_elementary_rate_with_assignment_rule_does_not_duplicate_volume(
    atomize: bool, compartment_size: float
):
    """Elementary reaction with assignment-rule rate constant does not scale by V^2.

    In SBML, kineticLaw = C * k * S represents substance/time extent rate.
    Because S is concentration [S] = S_amt / C, the extent rate is k * S_amt.
    In BNGL, an elementary rule `@C:M_S() -> @C:M_P() k` evaluates extent flux as
    k * [S] * C = k * S_amt.
    The emitted rate coefficient must be `k()` and MUST NOT contain `__compartment_C__`.
    """
    source = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="test_assignment_volume" timeUnits="second">
 <listOfCompartments><compartment id="C" size="{compartment_size}" constant="true"/></listOfCompartments>
 <listOfSpecies>
  <species id="S" compartment="C" initialAmount="1.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
  <species id="P" compartment="C" initialAmount="0.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
 </listOfSpecies>
 <listOfParameters><parameter id="k" value="0.1" constant="false"/></listOfParameters>
 <listOfRules><assignmentRule variable="k"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.1</cn></math></assignmentRule></listOfRules>
 <listOfReactions><reaction id="r1" reversible="false">
  <listOfReactants><speciesReference species="S" stoichiometry="1" constant="true"/></listOfReactants>
  <listOfProducts><speciesReference species="P" stoichiometry="1" constant="true"/></listOfProducts>
  <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply><times/><ci>C</ci><ci>k</ci><ci>S</ci></apply>
  </math></kineticLaw>
 </reaction></listOfReactions>
</model></sbml>"""

    result = _atomize(source, atomize=atomize)
    rule_lines = [
        line.strip()
        for line in result.bngl.splitlines()
        if "->" in line and not line.strip().startswith("#")
    ]
    assert len(rule_lines) == 1
    # Ensure redundant volume factor was stripped and not reintroduced
    assert "__compartment_C__ * k" not in rule_lines[0]
    assert "TotalRate" not in rule_lines[0]

    # Independent oracle comparison against libRoadRunner and exact analytic law
    times = np.array([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    rr = roadrunner.RoadRunner(source)
    rr.integrator.setValue("relative_tolerance", 1e-12)
    rr.integrator.setValue("absolute_tolerance", 1e-14)
    expected_amt = np.asarray(rr.simulate(times=times, selections=["time", "S"]))[:, 1]
    analytic_amt = 1.0 * np.exp(-0.1 * times)

    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=5)
    sim = cpp.simulate_ode(
        model, network, sample_times=times.tolist(), rtol=1e-10, atol=1e-14
    )
    actual_amt = np.asarray(sim["observables"]["S_amt"])

    np.testing.assert_allclose(actual_amt, expected_amt, rtol=1e-7, atol=1e-9)
    np.testing.assert_allclose(actual_amt, analytic_amt, rtol=1e-7, atol=1e-9)


@pytest.mark.parametrize("atomize", [False, True], ids=["flat", "atomized"])
@pytest.mark.parametrize("compartment_size", [0.15, 2.5])
def test_elementary_rate_with_rate_rule_does_not_duplicate_volume(
    atomize: bool, compartment_size: float
):
    """Elementary reaction with rate-rule parameter does not duplicate volume."""
    source = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="test_rate_rule_volume" timeUnits="second">
 <listOfCompartments><compartment id="C" size="{compartment_size}" constant="true"/></listOfCompartments>
 <listOfSpecies>
  <species id="S" compartment="C" initialAmount="1.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
  <species id="P" compartment="C" initialAmount="0.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
 </listOfSpecies>
 <listOfParameters><parameter id="k" value="0.1" constant="false"/></listOfParameters>
 <listOfRules><rateRule variable="k"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.05</cn></math></rateRule></listOfRules>
 <listOfReactions><reaction id="r1" reversible="false">
  <listOfReactants><speciesReference species="S" stoichiometry="1" constant="true"/></listOfReactants>
  <listOfProducts><speciesReference species="P" stoichiometry="1" constant="true"/></listOfProducts>
  <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply><times/><ci>C</ci><ci>k</ci><ci>S</ci></apply>
  </math></kineticLaw>
 </reaction></listOfReactions>
</model></sbml>"""

    result = _atomize(source, atomize=atomize)
    r1_lines = [
        line.strip()
        for line in result.bngl.splitlines()
        if line.strip().startswith("r1:")
    ]
    assert len(r1_lines) == 1
    assert "__compartment_C__" not in r1_lines[0]

    times = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    rr = roadrunner.RoadRunner(source)
    rr.integrator.setValue("relative_tolerance", 1e-12)
    rr.integrator.setValue("absolute_tolerance", 1e-14)
    expected_amt = np.asarray(rr.simulate(times=times, selections=["time", "S"]))[:, 1]

    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=5)
    sim = cpp.simulate_ode(
        model, network, sample_times=times.tolist(), rtol=1e-10, atol=1e-14
    )
    actual_amt = np.asarray(sim["observables"]["S_amt"])
    np.testing.assert_allclose(actual_amt, expected_amt, rtol=1e-7, atol=1e-9)


@pytest.mark.parametrize("atomize", [False, True], ids=["flat", "atomized"])
@pytest.mark.parametrize("compartment_size", [0.57, 2.45])
def test_elementary_rate_with_time_does_not_duplicate_volume(
    atomize: bool, compartment_size: float
):
    """Elementary reaction with explicit time operand does not duplicate volume."""
    source = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="test_time_volume" timeUnits="second">
 <listOfCompartments><compartment id="C" size="{compartment_size}" constant="true"/></listOfCompartments>
 <listOfSpecies>
  <species id="S" compartment="C" initialAmount="1.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
  <species id="P" compartment="C" initialAmount="0.0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
 </listOfSpecies>
 <listOfParameters><parameter id="k" value="0.2" constant="true"/></listOfParameters>
 <listOfReactions><reaction id="r1" reversible="false">
  <listOfReactants><speciesReference species="S" stoichiometry="1" constant="true"/></listOfReactants>
  <listOfProducts><speciesReference species="P" stoichiometry="1" constant="true"/></listOfProducts>
  <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply><times/><ci>C</ci><ci>k</ci><ci>S</ci><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol></apply>
  </math></kineticLaw>
 </reaction></listOfReactions>
</model></sbml>"""

    result = _atomize(source, atomize=atomize)
    trate_lines = [
        line.strip()
        for line in result.bngl.splitlines()
        if "_trate_" in line and "=" in line
    ]
    assert len(trate_lines) == 1
    assert "__compartment_C__" not in trate_lines[0]

    times = np.array([0.0, 0.2, 0.5, 1.0])
    analytic_amt = 1.0 * np.exp(-0.2 * (times**2) / 2.0)
    rr = roadrunner.RoadRunner(source)
    rr.integrator.setValue("relative_tolerance", 1e-12)
    rr.integrator.setValue("absolute_tolerance", 1e-14)
    expected_amt = np.asarray(rr.simulate(times=times, selections=["time", "S"]))[:, 1]

    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=5)
    sim = cpp.simulate_ode(
        model, network, sample_times=times.tolist(), rtol=1e-10, atol=1e-14
    )
    actual_amt = np.asarray(sim["observables"]["S_amt"])

    np.testing.assert_allclose(actual_amt, expected_amt, rtol=1e-7, atol=1e-9)
    np.testing.assert_allclose(actual_amt, analytic_amt, rtol=1e-7, atol=1e-9)


@pytest.mark.parametrize("atomize", [False, True], ids=["flat", "atomized"])
@pytest.mark.parametrize("compartment_size", [0.5, 2.5])
def test_contrasting_explicit_volume_flux_survives(
    atomize: bool, compartment_size: float
):
    """Nonlinear complete flux retains explicit volume factor as TotalRate."""
    source = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="test_contrast_volume" timeUnits="second">
 <listOfCompartments><compartment id="cell" size="{compartment_size}" constant="true"/></listOfCompartments>
 <listOfSpecies><species id="S" compartment="cell" initialAmount="2.0"
   hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/></listOfSpecies>
 <listOfReactions><reaction id="outflow" reversible="false">
  <listOfReactants><speciesReference species="S" stoichiometry="1" constant="true"/></listOfReactants>
  <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply><times/><ci>cell</ci><apply><power/><ci>S</ci><cn>3</cn></apply></apply>
  </math></kineticLaw>
 </reaction></listOfReactions>
</model></sbml>"""

    result = _atomize(source, atomize=atomize)
    rule_lines = [
        line.strip()
        for line in result.bngl.splitlines()
        if "outflow:" in line and "->" in line
    ]
    assert len(rule_lines) == 1
    # The explicit volume factor MUST survive on complete fluxes
    assert "__compartment_cell__" in rule_lines[0]
    assert "TotalRate" in rule_lines[0]

    times = np.array([0.0, 0.2, 0.5, 1.0])
    rr = roadrunner.RoadRunner(source)
    rr.integrator.setValue("relative_tolerance", 1e-12)
    rr.integrator.setValue("absolute_tolerance", 1e-14)
    expected_amt = np.asarray(rr.simulate(times=times, selections=["time", "S"]))[:, 1]

    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=5)
    sim = cpp.simulate_ode(
        model, network, sample_times=times.tolist(), rtol=1e-10, atol=1e-14
    )
    actual_amt = np.asarray(sim["observables"]["S_amt"])
    np.testing.assert_allclose(actual_amt, expected_amt, rtol=1e-7, atol=1e-9)


@pytest.mark.parametrize("case_id", ["00673", "00712", "00857", "00862"])
def test_primary_official_cases_pass_reproducers(case_id: str):
    """Primary official SSTS cases 00673, 00712, 00857, 00862 reproduce clean pass."""
    case_dir = _SSTS_DIR / "cases" / "semantic" / case_id
    if not case_dir.is_dir():
        return

    xml_files = sorted(case_dir.glob(f"{case_id}-sbml-l3v*.xml"))
    if not xml_files:
        xml_files = sorted(case_dir.glob(f"{case_id}-sbml-*.xml"))
    assert xml_files, f"No SBML file found for case {case_id}"
    xml_path = xml_files[-1]
    source = xml_path.read_text(encoding="utf-8")

    result = _atomize(source, atomize=False)
    assert result.success

    # Check that elementary reaction rules do not contain redundant compartment multiplier
    for line in result.bngl.splitlines():
        if "reaction1:" in line and "->" in line and "TotalRate" not in line:
            assert "__compartment_C__" not in line
