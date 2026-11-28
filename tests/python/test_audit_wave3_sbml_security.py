"""Regression tests for Audit Wave 3: SBML/Atomizer semantics, security, memory, and performance."""

from __future__ import annotations

import io
import inspect
import math
import time
import zipfile
from pathlib import Path
from unittest import mock

import pytest

import bionetgen
from bionetgen.atomizer.modern import (
    Atomizer,
    SBMLParser,
    convert_math_expression,
)
from bionetgen.atomizer.modern.archive import (
    MAX_ARCHIVE_MEMBERS,
    extract_sbml_from_archive,
    extract_sbml_from_combine_archive,
)
from bionetgen.atomizer.modern.arrays import flatten_arrays_package
from bionetgen.atomizer.modern.core import analyze_naming_conventions
from bionetgen.atomizer.modern.math_builtins import (
    TRUNCATED_LN10,
    evaluate_math_builtin,
)
from bionetgen.atomizer.modern.multi import parse_multi_package
from bionetgen.atomizer.modern.writer import _event_metadata_block
from bionetgen.sbml import BioNetGenError


def _write_sbml(tmp_path: Path, name: str, xml: str) -> str:
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# SBML-01: from_sbml().simulate() preserves and executes SBML events
# ---------------------------------------------------------------------------


def test_sbml01_from_sbml_executes_fixed_time_parameter_event(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="ev_param">
    <listOfCompartments>
      <compartment id="c" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="10"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.1" constant="false"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="e1" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>3</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="k">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""
    path = _write_sbml(tmp_path, "ev_param.xml", xml)
    res = bionetgen.from_sbml(path).simulate(method="ode", t_end=10.0, n_steps=50)
    expected = 10.0 * math.exp(-0.1 * 3.0) * math.exp(-1.0 * 7.0)
    assert float(res.observables["A"][-1]) == pytest.approx(expected, rel=1e-3)


def test_sbml01_from_sbml_executes_delayed_state_events_and_priority(tmp_path):
    # Delayed event with useValuesFromTriggerTime=true and =false
    def _delay_xml(use_trig: bool) -> str:
        flag = "true" if use_trig else "false"
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="ev_delay">
    <listOfCompartments><compartment id="c" spatialDimensions="3" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><cn>0.3</cn><ci>A</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="e1" useValuesFromTriggerTime="{flag}">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><leq/><ci>A</ci><cn>5</cn></apply></math>
        </trigger>
        <delay><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></delay>
        <listOfEventAssignments>
          <eventAssignment variable="B"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>A</ci></math></eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>"""

    p_true = _write_sbml(tmp_path, "delay_t.xml", _delay_xml(True))
    r_true = bionetgen.from_sbml(p_true).simulate(method="ode", t_end=10.0, n_steps=50)
    assert float(r_true.observables["B"][-1]) == pytest.approx(5.0, rel=1e-4)

    p_false = _write_sbml(tmp_path, "delay_f.xml", _delay_xml(False))
    r_false = bionetgen.from_sbml(p_false).simulate(
        method="ode", t_end=10.0, n_steps=50
    )
    expected_b_false = 5.0 * math.exp(-0.3 * 2.0)
    assert float(r_false.observables["B"][-1]) == pytest.approx(
        expected_b_false, rel=1e-3
    )


# ---------------------------------------------------------------------------
# SBML-02: units.py does not mis-scale species initialAssignments
# ---------------------------------------------------------------------------


def test_sbml02_unit_scaled_initial_assignments_hosu_true_and_false(tmp_path):
    hosu_true_xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="unit_hosu_true" substanceUnits="mole" volumeUnits="mL" timeUnits="second" extentUnits="mole">
    <listOfUnitDefinitions>
      <unitDefinition id="mL"><listOfUnits><unit kind="litre" exponent="1" scale="-3" multiplier="1"/></listOfUnits></unitDefinition>
    </listOfUnitDefinitions>
    <listOfCompartments><compartment id="c" spatialDimensions="3" size="2" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="c" initialAmount="3" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="S2" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfInitialAssignments>
      <initialAssignment symbol="S2">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><cn>2</cn><ci>S1</ci></apply></math>
      </initialAssignment>
    </listOfInitialAssignments>
  </model>
</sbml>"""
    p1 = _write_sbml(tmp_path, "unit_hosu_true.xml", hosu_true_xml)
    r1 = bionetgen.from_sbml(p1).simulate(method="ode", t_end=1.0, n_steps=2)
    assert float(r1.observables["S1"][0]) == pytest.approx(3.0, rel=1e-9)
    assert float(r1.observables["S2"][0]) == pytest.approx(6.0, rel=1e-9)

    conc_xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="unit_conc" substanceUnits="mole" volumeUnits="mL" timeUnits="second" extentUnits="mole">
    <listOfUnitDefinitions>
      <unitDefinition id="mL"><listOfUnits><unit kind="litre" exponent="1" scale="-3" multiplier="1"/></listOfUnits></unitDefinition>
    </listOfUnitDefinitions>
    <listOfCompartments><compartment id="c" spatialDimensions="3" size="2" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="c" initialConcentration="3" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
      <species id="S2" compartment="c" initialConcentration="0" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfInitialAssignments>
      <initialAssignment symbol="S2">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><ci>S1</ci><cn>5</cn></apply></math>
      </initialAssignment>
    </listOfInitialAssignments>
  </model>
</sbml>"""
    p2 = _write_sbml(tmp_path, "unit_conc.xml", conc_xml)
    r2 = bionetgen.from_sbml(p2).simulate(method="ode", t_end=1.0, n_steps=2)
    assert float(r2.observables["S1"][0]) == pytest.approx(6.0, rel=1e-9)
    assert float(r2.observables["S2"][0]) == pytest.approx(16.0, rel=1e-9)


# ---------------------------------------------------------------------------
# SBML-04: distrib draw duplication in abs() & fail-closed outside events
# ---------------------------------------------------------------------------


def test_sbml04_abs_does_not_duplicate_distrib_draw():
    lowered = convert_math_expression("abs(distrib_normal(0, 10))")
    assert lowered == "abs(distrib_normal(0, 10))"
    assert lowered.count("distrib_normal") == 1


def test_sbml04_distrib_in_initial_assignment_fails_closed(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
      xmlns:distrib="http://www.sbml.org/sbml/level3/version1/distrib/version1"
      level="3" version="2" distrib:required="true">
  <model id="distrib_ia">
    <listOfCompartments><compartment id="c" size="1" spatialDimensions="3" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="1" constant="false"/>
    </listOfParameters>
    <listOfInitialAssignments>
      <initialAssignment symbol="k">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <csymbol definitionURL="http://www.sbml.org/sbml/symbols/distrib/normal">normal</csymbol>
            <cn>5</cn><cn>0.5</cn>
          </apply>
        </math>
      </initialAssignment>
    </listOfInitialAssignments>
  </model>
</sbml>"""
    parsed = SBMLParser().parse(xml)
    assert any(
        w.get("category") == "package:distrib" and w.get("severity") == "dropped"
        for w in parsed.import_warnings
    )
    path = _write_sbml(tmp_path, "distrib_ia.xml", xml)
    with pytest.raises(BioNetGenError, match="package:distrib"):
        bionetgen.from_sbml(path)


# ---------------------------------------------------------------------------
# SBML-05, SBML-06, SBML-07: Core SBML round-trip symmetry & compartments
# ---------------------------------------------------------------------------


def test_sbml05_homodimer_automorphism_rate_not_doubled(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version3" level="2" version="3">
  <model id="homodimer">
    <listOfCompartments><compartment id="default" spatialDimensions="3" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S2" name="A(b!1,p~u).A(b!1,p~u)" compartment="default" initialAmount="100" hasOnlySubstanceUnits="true"/>
      <species id="S3" name="A(b!1,p~p).A(b!1,p~u)" compartment="default" initialAmount="0" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="R3" reversible="false">
        <listOfReactants><speciesReference species="S2"/></listOfReactants>
        <listOfProducts><speciesReference species="S3"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>2</cn><cn>0.5</cn><ci>S2</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    path = _write_sbml(tmp_path, "homodimer.xml", xml)
    res = bionetgen.from_sbml(path).simulate(method="ode", t_end=1.0, n_steps=10)
    # Macroscopic rate is 2 * 0.5 * S2 = 1.0 * S2 => S2(1) = 100 * exp(-1)
    assert float(res.observables["S2"][-1]) == pytest.approx(
        100.0 * math.exp(-1.0), rel=1e-4
    )


def test_sbml06_symmetric_molecules_observable_not_doubled(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version3" level="2" version="3">
  <model id="sym_obs">
    <listOfCompartments><compartment id="default" spatialDimensions="3" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" name="A(b,b)" compartment="default" initialAmount="50" hasOnlySubstanceUnits="true"/>
      <species id="S2" name="L(a)" compartment="default" initialAmount="100" hasOnlySubstanceUnits="true"/>
      <species id="S4" name="A(b!1,b!2).L(a!1).L(a!2)" compartment="default" initialAmount="10" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="A_free" value="0" constant="false"/>
      <parameter id="AL2" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="A_free">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>2</cn><ci>S1</ci></apply>
        </math>
      </assignmentRule>
      <assignmentRule variable="AL2">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>2</cn><ci>S4</ci></apply>
        </math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>"""
    path = _write_sbml(tmp_path, "sym_obs.xml", xml)
    res = bionetgen.from_sbml(path).simulate(method="ode", t_end=1.0, n_steps=2)
    assert float(res.observables["A_free"][0]) == pytest.approx(100.0, rel=1e-9)
    assert float(res.observables["AL2"][0]) == pytest.approx(20.0, rel=1e-9)


def test_sbml07_multicompartment_complex_preserves_molecule_compartments(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version3" level="2" version="3">
  <model id="comp3d2d3d">
    <listOfCompartments>
      <compartment id="EC" spatialDimensions="3" size="100" constant="true"/>
      <compartment id="PM" spatialDimensions="2" size="10" constant="true" outside="EC"/>
      <compartment id="CP" spatialDimensions="3" size="1" constant="true" outside="PM"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" name="L(r)" compartment="EC" initialAmount="500" hasOnlySubstanceUnits="true"/>
      <species id="S2" name="R(c,l)" compartment="PM" initialAmount="200" hasOnlySubstanceUnits="true"/>
      <species id="S3" name="X(r)" compartment="CP" initialAmount="100" hasOnlySubstanceUnits="true"/>
      <species id="S4" name="L(r!1).R(c,l!1)" compartment="PM" initialAmount="0" hasOnlySubstanceUnits="true"/>
      <species id="S5" name="L(r!1).R(c!2,l!1).X(r!2)" compartment="PM" initialAmount="0" hasOnlySubstanceUnits="true"/>
      <species id="S6" name="R(c!1,l).X(r!1)" compartment="PM" initialAmount="0" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="kf" value="0.1" constant="true"/>
      <parameter id="kr" value="0.2" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="S1"/><speciesReference species="S2"/></listOfReactants>
        <listOfProducts><speciesReference species="S4"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>0.01</cn><ci>kf</ci><ci>S1</ci><ci>S2</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="R2" reversible="false">
        <listOfReactants><speciesReference species="S4"/></listOfReactants>
        <listOfProducts><speciesReference species="S1"/><speciesReference species="S2"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>kr</ci><ci>S4</ci></apply>
        </math></kineticLaw>
      </reaction>
      <reaction id="R3" reversible="false">
        <listOfReactants><speciesReference species="S3"/><speciesReference species="S4"/></listOfReactants>
        <listOfProducts><speciesReference species="S5"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>kf</ci><ci>S4</ci><ci>S3</ci></apply>
        </math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    path = _write_sbml(tmp_path, "comp3d2d3d.xml", xml)
    model = bionetgen.from_sbml(path)
    net = model.generate_network()
    # Must NOT explode into phantom species (stays at exact 6 species, 3 reactions).
    assert net.num_species == 6
    assert net.num_reactions == 3


# ---------------------------------------------------------------------------
# SBML-08: fail-closed on unsupported packages / fast="true" & Multi homodimer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,xml",
    [
        (
            "fbc",
            """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:fbc="http://www.sbml.org/sbml/level3/version1/fbc/version2"
      level="3" version="1" fbc:required="false">
  <model id="m_fbc" fbc:strict="true">
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies><species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/></listOfSpecies>
    <fbc:listOfObjectives fbc:activeObjective="obj"><fbc:objective fbc:id="obj" fbc:type="maximize"/></fbc:listOfObjectives>
  </model>
</sbml>""",
        ),
        (
            "spatial_required",
            """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:spatial="http://www.sbml.org/sbml/level3/version1/spatial/version1"
      level="3" version="1" spatial:required="true">
  <model id="m_spatial">
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies><species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/></listOfSpecies>
  </model>
</sbml>""",
        ),
        (
            "unknown_required",
            """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core"
      xmlns:bogus="http://www.sbml.org/sbml/level3/version2/bogus/version1"
      level="3" version="2" bogus:required="true">
  <model id="m_bogus">
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies><species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/></listOfSpecies>
  </model>
</sbml>""",
        ),
        (
            "unhandled_fast",
            """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="m_fast">
    <listOfCompartments><compartment id="c" size="1" spatialDimensions="3" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r_fast" reversible="false" fast="true">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><cn>2</cn><ci>A</ci></apply></math></kineticLaw>
      </reaction>
      <reaction id="r_slow" reversible="false" fast="false">
        <listOfProducts><speciesReference species="A" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.5</cn></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>""",
        ),
    ],
)
def test_sbml08_unsupported_or_approximated_models_fail_closed(tmp_path, label, xml):
    path = _write_sbml(tmp_path, f"{label}.xml", xml)
    with pytest.raises(BioNetGenError):
        bionetgen.from_sbml(path)


def test_sbml08_multi_allows_intermolecular_homodimer_bond():
    homodimer_multi_xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="multi_homodimer">
    <listOfCompartments>
      <compartment id="cell" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="bSite" multi:name="b"/>
      <multi:speciesType multi:id="st_A" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="inst_b" multi:speciesType="bSite"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="st_AA" multi:name="AA" multi:compartment="cell">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="a1" multi:speciesType="st_A"/>
          <multi:speciesTypeInstance multi:id="a2" multi:speciesType="st_A"/>
        </multi:listOfSpeciesTypeInstances>
        <multi:listOfSpeciesTypeComponentIndexes>
          <multi:speciesTypeComponentIndex multi:id="idx1" multi:component="inst_b" multi:identifyingParent="a1"/>
          <multi:speciesTypeComponentIndex multi:id="idx2" multi:component="inst_b" multi:identifyingParent="a2"/>
        </multi:listOfSpeciesTypeComponentIndexes>
        <multi:listOfInSpeciesTypeBonds>
          <multi:inSpeciesTypeBond multi:bindingSite1="idx1" multi:bindingSite2="idx2"/>
        </multi:listOfInSpeciesTypeBonds>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
    <listOfSpecies>
      <species id="sp_AA" compartment="cell" initialAmount="10"
               hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="st_AA"/>
    </listOfSpecies>
  </model>
</sbml>"""
    parsed = parse_multi_package(homodimer_multi_xml)
    assert parsed.executable is True, parsed.warnings
    assert parsed.type_patterns["st_AA"] == "A(b!1)@cell.A(b!1)@cell"


# ---------------------------------------------------------------------------
# SBML-09, SBML-10, SBML-14, SBML-16
# ---------------------------------------------------------------------------


def test_sbml09_quotient_and_rem_truncate_toward_zero(tmp_path):
    assert evaluate_math_builtin("quotient", [-7.5, 2.0]) == -3.0
    assert evaluate_math_builtin("quotient", [7.5, -2.0]) == -3.0
    assert evaluate_math_builtin("rem", [-7.5, 2.0]) == pytest.approx(-1.5)
    assert evaluate_math_builtin("rem", [7.5, -2.0]) == pytest.approx(1.5)

    for op, a, b, expected in [
        ("quotient", -7.5, 2.0, -3.0),
        ("quotient", 7.5, -2.0, -3.0),
        ("rem", -7.5, 2.0, -1.5),
        ("rem", 7.5, -2.0, 1.5),
    ]:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="m_{op}">
    <listOfCompartments><compartment id="c" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies><species id="A" compartment="c" initialAmount="1" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/></listOfSpecies>
    <listOfParameters>
      <parameter id="x" value="{a}" constant="true"/>
      <parameter id="y" value="{b}" constant="true"/>
      <parameter id="out" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="out">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><{op}/><ci>x</ci><ci>y</ci></apply>
        </math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>"""
        path = _write_sbml(tmp_path, f"{op}_{a}_{b}.xml", xml)
        r = bionetgen.from_sbml(path).simulate(method="ode", t_end=1.0, n_steps=2)
        assert float(r.functions["out"][0]) == pytest.approx(expected, rel=1e-12)


def test_sbml09_arrays_quotient_and_rem_truncate_toward_zero():
    import xml.etree.ElementTree as ET
    from fractions import Fraction
    from bionetgen.atomizer.modern.arrays import _eval_static_value

    q_node = ET.fromstring(
        '<apply xmlns="http://www.w3.org/1998/Math/MathML">'
        "<quotient/><cn>-7</cn><cn>2</cn></apply>"
    )
    r_node = ET.fromstring(
        '<apply xmlns="http://www.w3.org/1998/Math/MathML">'
        "<rem/><cn>-7</cn><cn>2</cn></apply>"
    )
    q_pos_neg = ET.fromstring(
        '<apply xmlns="http://www.w3.org/1998/Math/MathML">'
        "<quotient/><cn>7</cn><cn>-2</cn></apply>"
    )
    r_pos_neg = ET.fromstring(
        '<apply xmlns="http://www.w3.org/1998/Math/MathML">'
        "<rem/><cn>7</cn><cn>-2</cn></apply>"
    )
    assert _eval_static_value(q_node, {}, {}, {}, {}) == Fraction(-3)
    assert _eval_static_value(r_node, {}, {}, {}, {}) == Fraction(-1)
    assert _eval_static_value(q_pos_neg, {}, {}, {}, {}) == Fraction(-3)
    assert _eval_static_value(r_pos_neg, {}, {}, {}, {}) == Fraction(1)


def test_sbml10_nonlinear_algebraic_rule_referenced_in_kinetic_law(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="alg_quad">
    <listOfCompartments><compartment id="c" spatialDimensions="3" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="c" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="X" value="3.3166247903554" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <algebraicRule>
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><minus/><apply><power/><ci>X</ci><cn>2</cn></apply><apply><plus/><ci>A</ci><cn>1</cn></apply></apply>
        </math>
      </algebraicRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>0.1</cn><ci>X</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    path = _write_sbml(tmp_path, "alg_quad.xml", xml)
    res = bionetgen.from_sbml(path).simulate(method="ode", t_end=5.0, n_steps=50)
    expected_a = (math.sqrt(11.0) - 0.25) ** 2 - 1.0
    assert float(res.observables["A"][-1]) == pytest.approx(expected_a, rel=1e-3)


def test_sbml14_identifier_collisions_amt_and_compartment_param(tmp_path):
    # Collision 1: species A and species A_amt
    xml_amt = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="col_amt">
    <listOfCompartments><compartment id="c" spatialDimensions="3" size="1" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
      <species id="A_amt" compartment="c" initialAmount="3" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="A_amt" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><plus/>
              <apply><times/><cn>0.2</cn><ci>A</ci></apply>
              <apply><times/><cn>0.1</cn><ci>A_amt</ci></apply>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    p1 = _write_sbml(tmp_path, "col_amt.xml", xml_amt)
    r1 = bionetgen.from_sbml(p1).simulate(method="ode", t_end=2.0, n_steps=20)
    # Exact ODE: A + A_amt = 13 => dA/dt = -0.2*A - 0.1*(13 - A) = -0.1*A - 1.3
    # => A(t) = (10 + 13)*exp(-0.1*t) - 13
    expected_a1 = 23.0 * math.exp(-0.2) - 13.0
    assert float(r1.observables["A"][-1]) == pytest.approx(expected_a1, rel=1e-4)

    # Collision 2: user parameter __compartment_c__ alongside compartment c
    xml_comp = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="col_comp">
    <listOfCompartments><compartment id="c" spatialDimensions="3" size="2" constant="true"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialConcentration="5" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="__compartment_c__" value="0.5" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="r1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>__compartment_c__</ci><ci>A</ci><ci>c</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    p2 = _write_sbml(tmp_path, "col_comp.xml", xml_comp)
    r2 = bionetgen.from_sbml(p2).simulate(method="ode", t_end=2.0, n_steps=20)
    # Exact ODE: A_amt(0) = 10, dA_amt/dt = -0.5 * A_amt => A_amt(2) = 10 * exp(-1)
    assert float(r2.observables["A"][-1]) == pytest.approx(
        10.0 * math.exp(-1.0), rel=1e-4
    )


def test_sbml16_ln10_full_ieee754_precision():
    assert abs(TRUNCATED_LN10 - math.log(10.0)) < 1e-15
    assert abs(evaluate_math_builtin("log10", [100.0]) - 2.0) < 1e-15


# ---------------------------------------------------------------------------
# SEC-01, SEC-03, SEC-04, SEC-05, SEC-06, MEM-07, MEM-09
# ---------------------------------------------------------------------------


def test_sec01_safe_sympify_blocks_rce_and_allows_math():
    from sympy.core.sympify import SympifyError
    from bionetgen.atomizer.utils.util import safe_sympify

    # Valid mathematical expressions succeed
    expr = safe_sympify("2 * k * A + sin(x) ** 2")
    assert str(expr)

    # Code execution / reflection / import probes are rejected
    for payload in [
        "__import__('builtins').len('probe_eval')",
        "eval('1 + 1')",
        "open('/etc/passwd')",
        "(1).__class__.__mro__",
        "[x for x in (1, 2)]",
        "(lambda x: x)(1)",
        "getattr(int, '__name__')",
    ]:
        with pytest.raises(SympifyError):
            safe_sympify(payload)


def test_sec01_legacy_atomizer_blocks_sympify_rce_probe(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version4" level="2" version="4">
  <model id="m">
    <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
    <listOfSpecies><species id="A" compartment="c" initialConcentration="10"/></listOfSpecies>
    <listOfParameters><parameter id="k" value="1"/></listOfParameters>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1"/></listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <times/>
              <ci>A</ci>
              <ci>__import__('builtins').len('probe_eval')</ci>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
    path = _write_sbml(tmp_path, "sympify_probe.xml", xml)
    # Must either fail closed or refuse to evaluate the injected expression to 10.
    try:
        out = bionetgen.sbml_to_bngl(path, atomizer_backend="legacy")
    except Exception:
        return
    assert "R1: A() -> 0 10.0" not in out


def test_sec03_no_raw_eval_or_cpickle_in_atomizer_submodules():
    repo_root = Path(__file__).resolve().parents[2]
    post_src = (
        repo_root / "python" / "bionetgen" / "atomizer" / "rulifier" / "postAnalysis.py"
    ).read_text(encoding="utf-8")
    assert "ast.literal_eval(" in post_src
    assert " eval(" not in post_src

    for rel in [
        "python/bionetgen/atomizer/contactMap.py",
        "python/bionetgen/atomizer/utils/annotationComparison.py",
    ]:
        src = (repo_root / rel).read_text(encoding="utf-8")
        assert "cPickle" not in src
        assert "pickle.load(" not in src


def test_sec04_pathwaycommons_defaults_https_timeout_and_no_hardcoded_key(
    tmp_path, monkeypatch
):
    from bionetgen.atomizer.atomizeTool import AtomizeTool
    from bionetgen.atomizer.utils import pathwaycommons

    dummy = tmp_path / "dummy.xml"
    dummy.write_text("<sbml/>", encoding="utf-8")
    tool = AtomizeTool(input_file=str(dummy))
    assert tool.config["pathwaycommons"] is False

    src = inspect.getsource(pathwaycommons)
    assert "f74b8d6f4c394fcc9d97b11c8c83d7f3" not in src
    assert "http://" not in src
    assert "timeout=" in src

    # Without BIOGRID_API_KEY set, queryBioGridByName returns False without network I/O
    monkeypatch.delenv("BIOGRID_API_KEY", raising=False)
    pathwaycommons.queryBioGridByName.cache.clear()
    with mock.patch("urllib.request.urlopen") as mocked_open:
        assert pathwaycommons.queryBioGridByName("A", "B", [], "A", "B") is False
        mocked_open.assert_not_called()

    # queryActiveSite with truthy organism does not fail with double-urlencode TypeError
    pathwaycommons.queryActiveSite.cache.clear()
    fake_resp = mock.MagicMock()
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.read.return_value = (
        b"Entry name\tEntry\tActive site\nEGF_HUMAN\tP01133\tACT_SITE 1\n"
    )
    with mock.patch("urllib.request.urlopen", return_value=fake_resp) as mocked_open:
        result = pathwaycommons.queryActiveSite("EGF", ["9606"])
        assert result == ["EGF_HUMAN"]
        assert mocked_open.call_args.kwargs.get("timeout") == 30


def test_mem07_archive_blocks_zip_bomb_and_path_traversal():
    # 1. Zip-bomb (>200x ratio over 1 MiB)
    bomb_buf = io.BytesIO()
    with zipfile.ZipFile(bomb_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "model.xml",
            "<sbml>" + (" " * (2 * 1024 * 1024)) + "</sbml>",
        )
    with pytest.raises(ValueError, match="decompression ratio|uncompressed size"):
        extract_sbml_from_archive(bomb_buf.getvalue())

    # 2. Path traversal ('../escape.xml')
    trav_buf = io.BytesIO()
    with zipfile.ZipFile(trav_buf, "w") as zf:
        zf.writestr("../escape.xml", "<sbml/>")
    with pytest.raises(ValueError, match="traversal"):
        extract_sbml_from_combine_archive(trav_buf.getvalue())

    # 3. Absolute path ('/etc/model.xml')
    abs_buf = io.BytesIO()
    with zipfile.ZipFile(abs_buf, "w") as zf:
        zf.writestr("/etc/model.xml", "<sbml/>")
    with pytest.raises(ValueError, match="absolute path"):
        extract_sbml_from_combine_archive(abs_buf.getvalue())

    # 4. Member count cap
    many_buf = io.BytesIO()
    with zipfile.ZipFile(many_buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for i in range(MAX_ARCHIVE_MEMBERS + 1):
            zf.writestr(f"f{i}.txt", b"x")
    with pytest.raises(ValueError, match="too many entries"):
        extract_sbml_from_archive(many_buf.getvalue())


def test_sec05_and_mem09_annotation_extender_and_parse_annotation():
    from bionetgen.atomizer import parseAnnotation

    repo_root = Path(__file__).resolve().parents[2]
    ext_src = (
        repo_root
        / "python"
        / "bionetgen"
        / "atomizer"
        / "utils"
        / "annotationExtender.py"
    ).read_text(encoding="utf-8")
    assert "os.chdir(tempfile.tempdir)" not in ext_src
    assert "TemporaryDirectory()" in ext_src

    # parseAnnotation works in Python 3 on XML containing text nodes & rdf:resource
    xml = (
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:li rdf:resource="urn:miriam:uniprot:P01133">text node</rdf:li>'
        "</rdf:RDF>"
    )
    assert parseAnnotation.parseAnnotation(xml) == ["urn:miriam:uniprot:P01133"]

    # Rejects DOCTYPE/ENTITY declarations
    with pytest.raises(ValueError, match="DOCTYPE|ENTITY"):
        parseAnnotation.parseAnnotation(
            '<!DOCTYPE foo [<!ENTITY xxe "bar">]><root>&xxe;</root>'
        )


# ---------------------------------------------------------------------------
# PERF-04: O(N^2) analyze_naming_conventions & single-pass _event_metadata_block
# ---------------------------------------------------------------------------


def test_perf04_naming_conventions_and_event_metadata_scale_cleanly():
    names = [f"S{i}" for i in range(250)]
    t0 = time.perf_counter()
    result = analyze_naming_conventions(names)
    elapsed_naming = time.perf_counter() - t0
    assert isinstance(result["keys"], list)
    assert (
        elapsed_naming < 3.0
    ), f"analyze_naming_conventions took {elapsed_naming:.2f}s"

    from bionetgen.atomizer.modern.types import (
        SBMLEvent,
        SBMLEventAssignment,
        SBMLModel,
        SBMLSpecies,
    )

    model = SBMLModel(
        id="perf_ev",
        species={f"S{i}": SBMLSpecies(id=f"S{i}", compartment="c") for i in range(150)},
        events=[
            SBMLEvent(
                id=f"e{i}",
                trigger=f"geq(S{i}, 1)",
                delay="",
                priority="",
                assignments=[SBMLEventAssignment(variable=f"S{i}", math="0")],
            )
            for i in range(150)
        ],
    )
    t1 = time.perf_counter()
    lines = _event_metadata_block(model, {f"S{i}": f"@c:M_S{i}()" for i in range(150)})
    elapsed_ev = time.perf_counter() - t1
    assert len(lines) > 150
    assert elapsed_ev < 1.0, f"_event_metadata_block took {elapsed_ev:.2f}s"
