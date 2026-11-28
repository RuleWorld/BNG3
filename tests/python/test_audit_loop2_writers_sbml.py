"""Regression tests for Loop 2 audit fixes (SBML IO, Net IO, BNGL/XML writers, code exporters)."""

from __future__ import annotations

import importlib.util
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

import bionetgen


def _read_gdat(path: Path) -> dict[str, np.ndarray]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    header = next(line for line in lines if line.startswith("#"))
    cols = [c for c in header.lstrip("#").split() if c]
    rows = np.loadtxt([line for line in lines if not line.startswith("#")], ndmin=2)
    return {col: rows[:, idx] for idx, col in enumerate(cols)}


def _run_bngl(tmp_path: Path, name: str, source: str) -> Path:
    bngl = tmp_path / name
    bngl.write_text(source, encoding="utf-8")
    bionetgen.load(str(bngl)).execute()
    return bngl


def _load_py_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. SbmlReader (Tier-P, L2-11-02, L2-11-10b, L2-09-04)
# ---------------------------------------------------------------------------


def test_sbml_reader_zero_additive_identity_in_observables(tmp_path: Path):
    xml_path = tmp_path / "flat_zero_plus.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version3" level="2" version="3">
  <model id="flat_zero">
    <listOfCompartments>
      <compartment id="cell" size="1"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialAmount="10" name="A()"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.5"/>
      <parameter id="Aobs" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="Aobs">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><plus/><cn> 0 </cn><ci> S1 </ci></apply>
        </math>
      </assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="S1"/></listOfReactants>
        <listOfProducts/>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>S1</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
""",
        encoding="utf-8",
    )
    _run_bngl(
        tmp_path,
        "run.bngl",
        """readFile({file=>"flat_zero_plus.xml"})
simulate({method=>"ode", t_end=>2, n_steps=>10})
""",
    )
    gdat = _read_gdat(tmp_path / "run.gdat")
    assert "Aobs" in gdat
    assert gdat["Aobs"][0] == pytest.approx(10.0, rel=1e-6)
    assert gdat["Aobs"][-1] == pytest.approx(10.0 * math.exp(-1.0), rel=1e-4)


def test_sbml_reader_large_weight_overflow_is_guarded(tmp_path: Path):
    xml_path = tmp_path / "overflow_weights.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version3" level="2" version="3">
  <model id="overflow_model">
    <listOfCompartments>
      <compartment id="cell" size="1"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialAmount="1" name="A()"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="HugeObs" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="HugeObs">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <plus/>
            <apply><times/><cn>2000000000</cn><ci>S1</ci></apply>
            <apply><times/><cn>2000000000</cn><ci>S1</ci></apply>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
  </model>
</sbml>
""",
        encoding="utf-8",
    )
    _run_bngl(
        tmp_path,
        "run.bngl",
        """readFile({file=>"overflow_weights.xml"})
writeNetwork({overwrite=>1})
""",
    )
    net_text = (tmp_path / "run.net").read_text(encoding="utf-8")
    # Overflowing group weight must fall back to function instead of wrapping negative
    assert "HugeObs" in net_text
    assert "-294967296" not in net_text


@pytest.mark.parametrize(
    "compartment_xml",
    [
        '<compartment size="1"/>',
        '<compartment id="" size="1"/>',
        '<compartment id="cell" size="0"/>',
        '<compartment id="cell" size="-2.5"/>',
        '<compartment id="cell" size="NaN"/>',
    ],
)
def test_sbml_reader_rejects_invalid_compartments(tmp_path: Path, compartment_xml: str):
    xml_path = tmp_path / "bad_comp.xml"
    xml_path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version3" level="2" version="3">
  <model id="bad_comp">
    <listOfCompartments>{compartment_xml}</listOfCompartments>
  </model>
</sbml>
""",
        encoding="utf-8",
    )
    bngl = tmp_path / "run.bngl"
    bngl.write_text('readFile({file=>"bad_comp.xml"})\n', encoding="utf-8")
    with pytest.raises(RuntimeError):
        bionetgen.load(str(bngl)).execute()


def test_sbml_reader_local_parameters_and_initial_concentration(tmp_path: Path):
    xml_path = tmp_path / "local_param_conc.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="local_param_conc">
    <listOfCompartments>
      <compartment id="cell" size="3.0" spatialDimensions="3" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialConcentration="2.0"
               hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false" name="A()"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="Aobs" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="Aobs">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S1</ci></math>
      </assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="R1" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>cell</ci><ci>k_loc</ci><ci>S1</ci></apply>
          </math>
          <listOfLocalParameters>
            <localParameter id="k_loc" value="0.5"/>
          </listOfLocalParameters>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
""",
        encoding="utf-8",
    )
    _run_bngl(
        tmp_path,
        "run.bngl",
        """readFile({file=>"local_param_conc.xml"})
simulate({method=>"ode", t_end=>2.0, n_steps=>20})
""",
    )
    gdat = _read_gdat(tmp_path / "run.gdat")
    # initialAmount = initialConcentration * compartmentVolume = 2.0 * 3.0 = 6.0
    # flux = cell * k_loc * [S1] = 3.0 * 0.5 * (S1 / 3.0) = 0.5 * S1 => S1(t) = 6 * exp(-0.5 * t)
    assert gdat["Aobs"][0] == pytest.approx(6.0, rel=1e-6)
    assert gdat["Aobs"][-1] == pytest.approx(6.0 * math.exp(-1.0), rel=1e-4)


@pytest.mark.parametrize(
    "unsupported_block",
    [
        """<listOfRules>
             <rateRule variable="k">
               <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
             </rateRule>
           </listOfRules>""",
        """<listOfRules>
             <algebraicRule>
               <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math>
             </algebraicRule>
           </listOfRules>""",
        """<listOfEvents>
             <event id="e1">
               <trigger><math xmlns="http://www.w3.org/1998/Math/MathML"><true/></math></trigger>
               <listOfEventAssignments>
                 <eventAssignment variable="k">
                   <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math>
                 </eventAssignment>
               </listOfEventAssignments>
             </event>
           </listOfEvents>""",
        """<listOfInitialAssignments>
             <initialAssignment symbol="k">
               <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>5</cn></math>
             </initialAssignment>
           </listOfInitialAssignments>""",
        """<listOfFunctionDefinitions>
             <functionDefinition id="f">
               <math xmlns="http://www.w3.org/1998/Math/MathML">
                 <lambda><bvar><ci>x</ci></bvar><ci>x</ci></lambda>
               </math>
             </functionDefinition>
           </listOfFunctionDefinitions>""",
    ],
)
def test_sbml_reader_rejects_unsupported_core_constructs(
    tmp_path: Path, unsupported_block: str
):
    xml_path = tmp_path / "unsupported.xml"
    xml_path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version4" level="2" version="4">
  <model id="unsup">
    <listOfCompartments><compartment id="cell" size="1"/></listOfCompartments>
    <listOfSpecies><species id="S1" compartment="cell" initialAmount="1" name="A()"/></listOfSpecies>
    <listOfParameters><parameter id="k" value="1" constant="false"/></listOfParameters>
    {unsupported_block}
  </model>
</sbml>
""",
        encoding="utf-8",
    )
    bngl = tmp_path / "run.bngl"
    bngl.write_text('readFile({file=>"unsupported.xml"})\n', encoding="utf-8")
    with pytest.raises(RuntimeError):
        bionetgen.load(str(bngl)).execute()


# ---------------------------------------------------------------------------
# 2. SbmlWriter (L2-09-03, L2-09-05)
# ---------------------------------------------------------------------------


def test_sbml_writer_l2_and_l3_event_schema(tmp_path: Path):
    _run_bngl(
        tmp_path,
        "ev.bngl",
        """begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Aobs A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
begin bng3_events version 1
  event "e1"
    trigger: time >= 1.0
    initial_value: false
    persistent: true
    use_values_from_trigger_time: true
    delay: 0.5
    assignment: k = 2.0
  end event
end bng3_events
end model
writeSBML({level=>2, prefix=>"ev_l2v3", suffix=>""})
writeSBML({level=>3, prefix=>"ev_l3v2", suffix=>""})
""",
    )
    l2_root = ET.fromstring((tmp_path / "ev_l2v3.xml").read_text(encoding="utf-8"))
    ns2 = {"sbml": "http://www.sbml.org/sbml/level2/version3"}
    l2_event = l2_root.find(".//sbml:event", ns2)
    assert l2_event is not None
    assert "delay" not in l2_event.attrib
    assert "useValuesFromTriggerTime" not in l2_event.attrib
    l2_trigger = l2_event.find("sbml:trigger", ns2)
    assert l2_trigger is not None
    assert "initialValue" not in l2_trigger.attrib
    assert "persistent" not in l2_trigger.attrib
    l2_delay = l2_event.find("sbml:delay", ns2)
    assert l2_delay is not None
    assert l2_delay.find("{http://www.w3.org/1998/Math/MathML}math") is not None

    l3_root = ET.fromstring((tmp_path / "ev_l3v2.xml").read_text(encoding="utf-8"))
    ns3 = {"sbml": "http://www.sbml.org/sbml/level3/version2/core"}
    l3_event = l3_root.find(".//sbml:event", ns3)
    assert l3_event is not None
    assert "delay" not in l3_event.attrib
    assert l3_event.attrib.get("useValuesFromTriggerTime") == "true"
    l3_trigger = l3_event.find("sbml:trigger", ns3)
    assert l3_trigger is not None
    assert "initialValue" in l3_trigger.attrib
    assert "persistent" in l3_trigger.attrib
    assert l3_event.find("sbml:delay/{http://www.w3.org/1998/Math/MathML}math", ns3) is not None


def test_sbml_writer_observable_quantifiers_and_molecule_compartments(tmp_path: Path):
    _run_bngl(
        tmp_path,
        "obs_sbml.bngl",
        """begin model
begin compartments
  EC 3 10
  PM 2 1 EC
  CP 3 5 PM
end compartments
begin parameters
  kf 0.1
end parameters
begin molecule types
  L(r)
  R(l)
end molecule types
begin seed species
  @EC:L(r) 5
  @CP:L(r) 7
  @PM:R(l) 3
end seed species
begin observables
  Molecules L_ec L(r!?)@EC
  Molecules L_cp L(r!?)@CP
  Species   Dimers L==2
end observables
begin reaction rules
  L(r)@EC + L(r)@EC -> L(r!1)@EC.L(r!1)@EC kf
end reaction rules
end model
generate_network({overwrite=>1})
writeSBML({level=>2, prefix=>"obs_sbml", suffix=>""})
""",
    )
    root = ET.fromstring((tmp_path / "obs_sbml.xml").read_text(encoding="utf-8"))
    ns = {
        "sbml": "http://www.sbml.org/sbml/level2/version3",
        "m": "http://www.w3.org/1998/Math/MathML",
    }
    species_by_id = {
        el.attrib["id"]: el.attrib.get("name", "")
        for el in root.findall(".//sbml:species", ns)
    }
    species_comp_by_id = {
        el.attrib["id"]: el.attrib.get("compartment", "")
        for el in root.findall(".//sbml:species", ns)
    }
    rules = {
        el.attrib["variable"]: [
            ci.text.strip() for ci in el.findall(".//m:ci", ns) if ci.text
        ]
        for el in root.findall(".//sbml:assignmentRule", ns)
    }
    assert set(rules["L_ec"]).isdisjoint(set(rules["L_cp"]))
    assert len(rules["L_cp"]) == 1
    assert species_comp_by_id[rules["L_cp"][0]] == "CP"
    assert len(rules["Dimers"]) == 1
    assert "!1" in species_by_id[rules["Dimers"][0]]


# ---------------------------------------------------------------------------
# 3. SbmlMultiWriter (L2-09-06) & SbmlUnitWriter (L2-09-07)
# ---------------------------------------------------------------------------


def test_sbml_multi_writer_compartments_default_and_lambda_globals(tmp_path: Path):
    _run_bngl(
        tmp_path,
        "multi_fix.bngl",
        """begin model
begin compartments
  EC 3 10
  PM 2 1 EC
  CP 3 5 PM
end compartments
begin parameters
  k0 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  @CP:A() 10
end seed species
begin observables
  Molecules AllA A()
end observables
begin functions
  scaled(x) = k0 * x
end functions
begin reaction rules
  @CP:A() -> 0 scaled(AllA)
end reaction rules
end model
writeSBMLMulti({prefix=>"multi_fix", suffix=>""})
""",
    )
    xml_text = (tmp_path / "multi_fix.xml").read_text(encoding="utf-8")
    root = ET.fromstring(xml_text)
    ns = {
        "sbml": "http://www.sbml.org/sbml/level3/version1/core",
        "m": "http://www.w3.org/1998/Math/MathML",
    }
    compartments = root.findall(".//sbml:compartment", ns)
    comp_ids = {c.attrib["id"] for c in compartments}
    # No illegal L2 outside="..." attribute on L3 compartments
    for comp in compartments:
        assert "outside" not in comp.attrib
    # Uncompartmented observable pattern requires declared "default" compartment
    assert "default" in comp_ids
    # Parameterized functionDefinition must pass referenced global parameter k0 as <bvar>
    fn_def = root.find(".//sbml:functionDefinition[@id='scaled']", ns)
    assert fn_def is not None
    bvars = [
        ci.text.strip()
        for ci in fn_def.findall(".//m:lambda/m:bvar/m:ci", ns)
        if ci.text
    ]
    assert "x" in bvars
    assert "k0" in bvars


def test_sbml_unit_writer_emits_scale_zero_on_non_power_of_10(tmp_path: Path):
    _run_bngl(
        tmp_path,
        "units_l3.bngl",
        """begin model
begin units
  timeunits second
  unit half_dim = 2 * dimensionless
end units
begin compartments
  cell 3 1.0 [fL]
end compartments
begin parameters
  c = 0.5 [half_dim]
  k = 0.5 [1/second]
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  @cell:A() 10
end seed species
begin reaction rules
  @cell:A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
writeSBML({level=>3, prefix=>"units_l3", suffix=>""})
""",
    )
    root = ET.fromstring((tmp_path / "units_l3.xml").read_text(encoding="utf-8"))
    ns = {"sbml": "http://www.sbml.org/sbml/level3/version2/core"}
    half_dim = root.find(".//sbml:unitDefinition[@id='half_dim']", ns)
    assert half_dim is not None
    units = half_dim.findall(".//sbml:unit", ns)
    assert len(units) > 0
    for unit_el in units:
        assert unit_el.attrib.get("scale") == "0"
        assert "exponent" in unit_el.attrib
        assert "multiplier" in unit_el.attrib


# ---------------------------------------------------------------------------
# 4. NetReader (L2-02-04, L2-02-08)
# ---------------------------------------------------------------------------


def test_net_reader_tabs_and_symbolic_parameter_expressions(tmp_path: Path):
    net_path = tmp_path / "tabbed.net"
    net_path.write_text(
        "begin parameters\n"
        "\t1\tk1\t0.25\n"
        "\t2\tk2\t2*k1\n"
        "\t3\tk3\tk1*3\n"
        "\t4\tk4\t(2 * k1)\n"
        "end parameters\n"
        "begin species\n"
        "\t1\tA()\t10\n"
        "end species\n"
        "begin reactions\n"
        "\t1\t1\t0\tk2\n"
        "\t2\t1\t0\tk3\n"
        "\t3\t1\t0\tk4\n"
        "end reactions\n"
        "begin groups\n"
        "\t1\tAobs\t1\n"
        "end groups\n",
        encoding="utf-8",
    )
    _run_bngl(
        tmp_path,
        "run.bngl",
        """readFile({file=>"tabbed.net"})
simulate({method=>"ode", t_end=>1.0, n_steps=>10})
""",
    )
    gdat = _read_gdat(tmp_path / "run.gdat")
    # Effective decay rate = k2 + k3 + k4 = 0.5 + 0.75 + 0.5 = 1.75
    assert gdat["Aobs"][-1] == pytest.approx(10.0 * math.exp(-1.75), rel=1e-4)


# ---------------------------------------------------------------------------
# 5. NetWriter (L2-01-12, L2-08-02, L2-10-09)
# ---------------------------------------------------------------------------


def test_net_writer_scoped_function_referencing_global_observable(tmp_path: Path):
    _run_bngl(
        tmp_path,
        "scoped_obs.bngl",
        """begin model
begin parameters
  k 0.2
end parameters
begin molecule types
  A(s~0~1)
  C()
end molecule types
begin seed species
  A(s~0) 10
  C() 5
end seed species
begin observables
  Molecules C_tot C()
  Molecules A_p A(s~1)
end observables
begin functions
  f(x) = k * C_tot * (1 + A_p(x))
end functions
begin reaction rules
  %x:A(s~0) -> %x:A(s~1) f(x)
end reaction rules
end model
generate_network({overwrite=>1})
writeNetwork({overwrite=>1})
simulate({method=>"ode", t_end=>1.0, n_steps=>10})
""",
    )
    net_text = (tmp_path / "scoped_obs.net").read_text(encoding="utf-8")
    assert "C_tot" in net_text
    gdat = _read_gdat(tmp_path / "scoped_obs.gdat")
    # With C_tot=5 and A_p(x)=0 on A(s~0), rate = k*5 = 1.0 => A_p(1) = 10*(1 - exp(-1))
    assert gdat["A_p"][-1] == pytest.approx(10.0 * (1.0 - math.exp(-1.0)), rel=1e-4)


def test_net_writer_energy_species_prefix_compartment(tmp_path: Path):
    _run_bngl(
        tmp_path,
        "energy_comp.bngl",
        """begin model
begin compartments
  PM 2 1
  CP 3 1 PM
end compartments
begin parameters
  Ea 0.0
  Gf 2.0
  phi 0.5
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  @PM:A(s~0) 10
  @CP:A(s~0) 10
end seed species
begin energy patterns
  @PM:A(s~1) Gf
end energy patterns
begin observables
  Molecules PM_1 @PM:A(s~1)
  Molecules CP_1 @CP:A(s~1)
end observables
begin reaction rules
  @PM:A(s~0) <-> @PM:A(s~1) Arrhenius(phi, Ea)
  @CP:A(s~0) <-> @CP:A(s~1) Arrhenius(phi, Ea)
end reaction rules
end model
generate_network({overwrite=>1})
writeNetwork({overwrite=>1})
simulate({method=>"ode", t_end=>10.0, n_steps=>50})
""",
    )
    net_text = (tmp_path / "energy_comp.net").read_text(encoding="utf-8")
    assert "Gf" in net_text
    gdat = _read_gdat(tmp_path / "energy_comp.gdat")
    # At equilibrium: CP has dG=0 => CP_1 = 5.0; PM has dG=+2 => PM_1 = 10 / (1 + exp(2))
    assert gdat["CP_1"][-1] == pytest.approx(5.0, rel=1e-3)
    assert gdat["PM_1"][-1] == pytest.approx(10.0 / (1.0 + math.exp(2.0)), rel=1e-3)


def test_net_writer_total_rate_compartments_and_reverse_rate_lifting(tmp_path: Path):
    _run_bngl(
        tmp_path,
        "totalrate_rev.bngl",
        """begin model
begin compartments
  EC 3 10
end compartments
begin parameters
  kf 0.5
  kr 0.2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  @EC:A() 5
  @EC:B() 5
end seed species
begin reaction rules
  r1: @EC:A() + @EC:B() <-> @EC:A() + @EC:B() kf, 0.25+kr TotalRate
end reaction rules
end model
generate_network({overwrite=>1})
writeNetwork({overwrite=>1})
""",
    )
    net_text = (tmp_path / "totalrate_rev.net").read_text(encoding="utf-8")
    assert "begin compartments" in net_text
    # TotalRate bimolecular rule must NOT include 1/10 volume factor
    assert "1/10" not in net_text
    # Reverse compound rate must be lifted out of begin reactions into a named rate parameter
    rxn_section = net_text.split("begin reactions", 1)[1].split("end reactions", 1)[0]
    assert "0.25+kr" not in rxn_section


# ---------------------------------------------------------------------------
# 6. BnglWriter (L2-02-11)
# ---------------------------------------------------------------------------


def test_bngl_writer_fixed_compartment_species_and_net_observables(tmp_path: Path):
    _run_bngl(
        tmp_path,
        "fixed_comp.bngl",
        """begin model
begin compartments
  EC 3 10
end compartments
begin parameters
  k 0.1
end parameters
begin molecule types
  L(r)
end molecule types
begin seed species
  @EC:$L(r) 100
end seed species
begin observables
  Molecules L_tot L(r)
end observables
begin reaction rules
  @EC:L(r) -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
writeBNGL({prefix=>"fixed_comp_out", suffix=>""})
""",
    )
    bngl_out = (tmp_path / "fixed_comp_out.bngl").read_text(encoding="utf-8")
    assert "@EC:$L(r)" in bngl_out
    assert "$@EC:" not in bngl_out

    # Round-trip a .net-loaded model with indexed observables through writeBNGL
    net_path = tmp_path / "indexed.net"
    net_path.write_text(
        """begin parameters
  1 k 0.1
end parameters
begin species
  1 A() 10
  2 B() 5
end species
begin reactions
  1 1 2 k
end reactions
begin groups
  1 Aobs 1
  2 Weighted 1,2*2
end groups
""",
        encoding="utf-8",
    )
    _run_bngl(
        tmp_path,
        "from_net.bngl",
        """readFile({file=>"indexed.net"})
writeBNGL({prefix=>"from_net_out", suffix=>""})
""",
    )
    re_bngl = (tmp_path / "from_net_out.bngl").read_text(encoding="utf-8")
    assert "Species Aobs A()" in re_bngl
    assert "Species Weighted A(),B()" in re_bngl
    # Must re-parse cleanly
    bionetgen.load(str(tmp_path / "from_net_out.bngl"))


# ---------------------------------------------------------------------------
# 7. XmlWriter (L2-07-02, L2-07-03, L2-07-09, L2-07-10, L2-07-14, L2-08-05)
# ---------------------------------------------------------------------------


def test_xml_writer_symmetry_filters_rates_and_bond_counts(tmp_path: Path):
    _run_bngl(
        tmp_path,
        "xml_features.bngl",
        """begin model
begin compartments
  EC 3 10
  PM 2 1 EC
end compartments
begin parameters
  k1 0.5
  Km 4.0
end parameters
begin molecule types
  A(b,c)
  B(a,b)
  C()
  D(b,b)
end molecule types
begin seed species
  @EC:A(b,c) 10
  @EC:B(a,b) 5
  @EC:C() 2
  @EC:D(b,b) 4
end seed species
begin observables
  Molecules M1 A(b!1!?).B(a!1)
end observables
begin reaction rules
  self_bond: D(b,b) <-> D(b!1,b!1) k1, k1
  dimer_mc: A(b) + A(b) -> A(b!1).A(b!1) k1 MoveConnected
  dimer_tr: A(b) + A(b) -> A(b!1).A(b!1) k1 TotalRate
  multi_excl: A(b)@EC -> 0 k1 exclude_reactants(1,@EC:B(b)) exclude_reactants(1,C()@EC)
  sat_expr: A(b) -> 0 Sat(2*k1, Km/2)
end reaction rules
end model
writeXML({prefix=>"xml_features", suffix=>""})
""",
    )
    root = ET.fromstring((tmp_path / "xml_features.xml").read_text(encoding="utf-8"))
    ns = {"sbml": "http://www.sbml.org/sbml/level3"}
    rules = {
        r.attrib["name"]: r for r in root.findall(".//sbml:ReactionRule", ns)
    }

    # L2-07-02: intra-pattern self-bond symmetry factor = 0.5
    assert rules["self_bond"].attrib.get("symmetry_factor") == "0.5"
    rev_key = "_reverse__self_bond" if "_reverse__self_bond" in rules else "_reverse_self_bond"
    assert rules[rev_key].attrib.get("symmetry_factor") == "0.5"

    # L2-07-03: non-TotalRate modifiers keep symmetry_factor=0.5; TotalRate omits it
    assert rules["dimer_mc"].attrib.get("symmetry_factor") == "0.5"
    assert "symmetry_factor" not in rules["dimer_tr"].attrib

    # L2-07-09: merged filter list with unique IDs and compartment attribute on <Pattern> or <Molecule>
    excl_lists = rules["multi_excl"].findall(".//sbml:ListOfExcludeReactants", ns)
    assert len(excl_lists) == 1
    excl_pats = excl_lists[0].findall("sbml:Pattern", ns)
    assert len(excl_pats) == 2
    assert len({p.attrib["id"] for p in excl_pats}) == 2
    assert excl_pats[0].attrib.get("compartment") == "EC"
    assert excl_pats[1].find(".//sbml:Molecule", ns).attrib.get("compartment") == "EC"

    # L2-07-10: evaluated arithmetic expressions in Sat <RateConstant>
    sat_rc = rules["sat_expr"].findall(".//sbml:RateLaw/sbml:ListOfRateConstants/sbml:RateConstant", ns)
    assert len(sat_rc) == 2
    assert float(sat_rc[0].attrib["value"]) == pytest.approx(1.0)
    assert float(sat_rc[1].attrib["value"]) == pytest.approx(2.0)

    # L2-07-14: explicit bond count + wildcard preserved ("1?")
    obs_m1 = root.find(".//sbml:Observable[@name='M1']", ns)
    assert obs_m1 is not None
    bc_comp = obs_m1.find(".//sbml:Component[@name='b']", ns)
    assert bc_comp is not None
    assert bc_comp.attrib.get("numberOfBonds") == "1?"


def test_xml_writer_validates_unconditional_barrier_transitions(tmp_path: Path):
    bngl = tmp_path / "bad_barrier.bngl"
    bngl.write_text(
        """begin model
begin parameters
  G_P 0.0
  Gbar 5.0
  phi 0.5
  Ea 0.0
end parameters
begin molecule types
  A(s~U~P,b)
end molecule types
begin seed species
  A(s~U,b) 100
end seed species
begin energy patterns
  A(s~P) G_P
end energy patterns
begin barrier patterns
  B_cond: A(s~U,b!+) -> A(s~P,b!+) Gbar
end barrier patterns
begin reaction rules
  R1: A(s~U) <-> A(s~P) Arrhenius(phi, Ea)
end reaction rules
end model
writeXML({prefix=>"bad_barrier", suffix=>""})
""",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        bionetgen.load(str(bngl)).execute()


# ---------------------------------------------------------------------------
# 8. Code Exporters (L2-02-06, L2-02-07, L2-11-09, L2-12-09)
# ---------------------------------------------------------------------------


def test_exporters_escape_hostile_model_name(tmp_path: Path):
    _run_bngl(
        tmp_path,
        "hostile.bngl",
        r"""setModelName("evil'name*/\tail")
begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Aobs A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
writeCPYfile({prefix=>"safe", suffix=>""})
writeMfile({prefix=>"safe", suffix=>""})
writeCppfile({prefix=>"safe", suffix=>""})
writeMEXfile({prefix=>"safe", suffix=>""})
writeLatex({prefix=>"safe", suffix=>""})
""",
    )
    py_src = (tmp_path / "safe_pyode.py").read_text(encoding="utf-8")
    compile(py_src, "safe_pyode.py", "exec")

    m_src = (tmp_path / "safe.m").read_text(encoding="utf-8")
    assert "title('evil''name" in m_src

    cpp_src = (tmp_path / "safe_cvode.h").read_text(encoding="utf-8")
    header_cpp = cpp_src.split("#include", 1)[0]
    assert "evil'name*/" not in header_cpp

    mex_src = (tmp_path / "safe_mex.c").read_text(encoding="utf-8")
    header_mex = mex_src.split("#include", 1)[0]
    assert "evil'name*/" not in header_mex

    tex_src = (tmp_path / "safe.tex").read_text(encoding="utf-8")
    assert r"\textbackslash{}" in tex_src


def test_exporters_net_compound_rate_and_indexed_observables(tmp_path: Path):
    net_path = tmp_path / "compound.net"
    net_path.write_text(
        """begin parameters
  1 k1 0.3
  2 k2 0.7
end parameters
begin species
  1 A() 10
end species
begin reactions
  1 1 0 k1+k2
end reactions
begin groups
  1 Aobs 1
end groups
""",
        encoding="utf-8",
    )
    _run_bngl(
        tmp_path,
        "run.bngl",
        """readFile({file=>"compound.net"})
writeCPYfile({prefix=>"cmp", suffix=>""})
writeMfile({prefix=>"cmp", suffix=>""})
writeCppfile({prefix=>"cmp", suffix=>""})
writeMEXfile({prefix=>"cmp", suffix=>""})
""",
    )
    py_path = tmp_path / "cmp_pyode.py"
    py_src = py_path.read_text(encoding="utf-8")
    assert (
        "(expressions[0] + expressions[1])*species[0]" in py_src
        or "(expressions[1] + expressions[0])*species[0]" in py_src
    )
    assert "observables[0] = species[0]" in py_src

    m_src = (tmp_path / "cmp.m").read_text(encoding="utf-8")
    assert (
        "(expressions(1) + expressions(2))*species(1)" in m_src
        or "(expressions(2) + expressions(1))*species(1)" in m_src
    )
    assert "observables(1) = species(1)" in m_src

    cpp_src = (tmp_path / "cmp_cvode.h").read_text(encoding="utf-8")
    assert (
        "(NV_Ith_S(expressions,0) + NV_Ith_S(expressions,1))*NV_Ith_S(species,0)" in cpp_src
        or "(NV_Ith_S(expressions,1) + NV_Ith_S(expressions,0))*NV_Ith_S(species,0)" in cpp_src
    )
    assert "NV_Ith_S(observables,0) = NV_Ith_S(species,0)" in cpp_src

    mex_src = (tmp_path / "cmp_mex.c").read_text(encoding="utf-8")
    assert (
        "(expressions[0] + expressions[1])*species[0]" in mex_src
        or "(expressions[1] + expressions[0])*species[0]" in mex_src
    )
    assert "observables[0] = species[0]" in mex_src

    mod = _load_py_module(py_path, "cmp_pyode_mod")
    tps = np.linspace(0.0, 2.0, 21)
    _, _, obs_out = mod.simulate(tps)
    assert obs_out[-1, 0] == pytest.approx(10.0 * math.exp(-2.0), rel=1e-4)


def test_exporters_functions_time_sat_mm_hill_and_compartments(tmp_path: Path):
    _run_bngl(
        tmp_path,
        "rich_ode.bngl",
        """begin model
begin compartments
  EC 3 1
  CP 3 1 EC
end compartments
begin parameters
  k0 0.2
  Vmax 1.5
  Km 5.0
  kcat 0.8
  Kh 4.0
  nh 2.0
end parameters
begin molecule types
  A()
  B()
  E()
  S()
  H()
end molecule types
begin seed species
  @EC:A() 10
  @CP:A() 20
  @EC:B() 10
  @EC:E() 2
  @EC:S() 8
  @EC:H() 6
end seed species
begin observables
  Molecules A_ec @EC:A()
  Molecules A_cp @CP:A()
  Molecules B_obs @EC:B()
  Molecules S_obs @EC:S()
  Molecules H_obs @EC:H()
end observables
begin functions
  decay_rate() = k0 * (1 + if(time > 0.5, 0.5, 0.0))
end functions
begin reaction rules
  @EC:A() -> 0 decay_rate()
  @EC:B() -> 0 Sat(Vmax, Km)
  @EC:S() + @EC:E() -> @EC:E() MM(kcat, Km)
  @EC:H() -> 0 Hill(Vmax, Kh, nh)
end reaction rules
end model
generate_network({overwrite=>1})
writeCPYfile({prefix=>"rich_ode", suffix=>""})
writeMfile({prefix=>"rich_ode", suffix=>""})
writeCppfile({prefix=>"rich_ode", suffix=>""})
writeMEXfile({prefix=>"rich_ode", suffix=>""})
simulate({method=>"ode", t_end=>2.0, n_steps=>20})
""",
    )
    gdat = _read_gdat(tmp_path / "rich_ode.gdat")

    # Python export must compile and match native BNG3 CVODE on every observable
    py_path = tmp_path / "rich_ode_pyode.py"
    py_src = py_path.read_text(encoding="utf-8")
    assert "decay_rate(" not in py_src
    assert "Sat(" not in py_src
    assert "MM(" not in py_src
    assert "Hill(" not in py_src
    mod = _load_py_module(py_path, "rich_ode_pyode_mod")
    _, _, obs_out = mod.simulate(gdat["time"])
    for idx, name in enumerate(["A_ec", "A_cp", "B_obs", "S_obs", "H_obs"]):
        np.testing.assert_allclose(obs_out[:, idx], gdat[name], rtol=1e-3, atol=1e-4)

    # MATLAB export must use bng_if helper (never invalid MATLAB `if(cond, a, b)`)
    m_src = (tmp_path / "rich_ode.m").read_text(encoding="utf-8")
    assert "bng_if(" in m_src
    assert "function val = bng_if(cond, a, b)" in m_src
    m_code_only = "\n".join(
        line.split("%", 1)[0] for line in m_src.splitlines()
    )
    assert not re.search(r"(?<![A-Za-z0-9_])if\s*\([^;\n]+,", m_code_only)
    assert "decay_rate(" not in m_src

    # C++ and MEX exports must inline functions and never double-multiply Sat/MM/Hill reactants
    for fname in ("rich_ode_cvode.h", "rich_ode_mex.c"):
        src = (tmp_path / fname).read_text(encoding="utf-8")
        assert "decay_rate(" not in src
        assert "Sat(" not in src
        assert "MM(" not in src
        assert "Hill(" not in src
        assert "double t" in src
