"""A species concentration rate rule over an event-driven compartment size.

SBML Level 3 Version 2 Core Sec. 4.6 ties a species' amount to its
concentration through the size of the species' compartment, and Sec. 4.9.4
makes a rate rule set the rate of change of the quantity the rule names.  A
rate rule on a concentration-valued species therefore needs

    d(amount)/dt = V * d(concentration)/dt + concentration * dV/dt

and a compartment whose size is driven by a rule keeps that size in a BNGL
state species, which an event assignment has to update.  The SBML Test Suite
cases ``semantic/01505`` and ``semantic/01506`` exercise exactly that
combination; their official reference trajectories are the arbiter.
"""

import pytest
from _extdep import require_extension

cpp = require_extension()

# SBML Test Suite semantic/01505 and semantic/01506 official reference
# trajectories (``-results.csv``), with the suite's own ``-settings.txt``
# tolerance (absolute 1e-4, relative 1e-4).  ``C1`` is the compartment size,
# ``S1`` the species amount and ``x`` the species concentration.
REFERENCE_01505 = [
    (0.0, 0.5, 0.0, 0.0),
    (0.1, 0.52, 0.0208, 0.04),
    (0.2, 0.54, 0.0432, 0.08),
    (0.3, 0.56, 0.0672, 0.12),
    (0.4, 0.58, 0.0928, 0.16),
    (0.5, 0.21, 0.11571, 0.551),
    (0.6, 0.23, 0.13593, 0.591),
    (0.7, 0.25, 0.15775, 0.631),
    (0.8, 0.27, 0.18117, 0.671),
    (0.9, 0.29, 0.20619, 0.711),
    (1.0, 0.31, 0.23281, 0.751),
]
REFERENCE_01506 = [
    (0.0, 0.5, 0.0, 0.0),
    (0.1, 0.52, 0.0208, 0.04),
    (0.2, 0.54, 0.0432, 0.08),
    (0.3, 0.56, 0.0672, 0.12),
    (0.4, 0.58, 0.0928, 0.16),
    (0.5, 0.21, 0.1281, 0.61),
    (0.6, 0.23, 0.1495, 0.65),
    (0.7, 0.25, 0.1725, 0.69),
    (0.8, 0.27, 0.1971, 0.73),
    (0.9, 0.29, 0.2233, 0.77),
    (1.0, 0.31, 0.2511, 0.81),
]
EVENT_TIME = 0.45
ABSOLUTE_TOLERANCE = 1e-4
RELATIVE_TOLERANCE = 1e-4


def source(assign_species=False):
    """SBML Test Suite semantic/01505, with the species assignment of 01506."""

    species_assignment = (
        """
    <eventAssignment variable="S1">
      <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.2</cn></math>
    </eventAssignment>"""
        if assign_species
        else ""
    )
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="case01505">
  <listOfCompartments>
    <compartment id="C1" spatialDimensions="3" size="0.5" constant="false"/>
  </listOfCompartments>
  <listOfSpecies>
    <species id="S1" compartment="C1" initialConcentration="0" hasOnlySubstanceUnits="false" boundaryCondition="true" constant="false"/>
  </listOfSpecies>
  <listOfParameters>
    <parameter id="x" constant="false"/>
  </listOfParameters>
  <listOfRules>
    <rateRule variable="S1">
      <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.4</cn></math>
    </rateRule>
    <rateRule variable="C1">
      <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.2</cn></math>
    </rateRule>
    <assignmentRule variable="x">
      <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>S1</ci></math>
    </assignmentRule>
  </listOfRules>
  <listOfEvents>
    <event id="E0" useValuesFromTriggerTime="true">
      <trigger initialValue="true" persistent="true">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <geq/>
            <csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol>
            <cn>0.45</cn>
          </apply>
        </math>
      </trigger>
      <listOfEventAssignments>{species_assignment}
        <eventAssignment variable="C1">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.2</cn></math>
        </eventAssignment>
      </listOfEventAssignments>
    </event>
  </listOfEvents>
</model></sbml>"""


def convert(xml):
    from bionetgen.atomizer.modern import Atomizer

    converted = Atomizer(atomize=False, quiet_mode=True).atomize(xml)
    assert converted.success, converted.error
    return converted.bngl


def sample_on_reference_grid(bngl, grid):
    """Re-time the action phases onto the official output grid.

    The Atomizer splits the simulation at the event time, so the two phases
    sample their own grids.  The reference trajectory is defined on the
    suite's grid, so the phases are re-timed onto it; only the sampling
    changes, not the model's dynamics.
    """

    import re

    before = [time for time in grid if time < EVENT_TIME] + [EVENT_TIME]
    after = [time for time in grid if time > EVENT_TIME]
    lines = []
    first = True
    for line in bngl.splitlines():
        stripped = line.strip()
        if stripped.startswith("simulate("):
            m_start = re.search(r"t_start=>([0-9.eE+-]+)", stripped)
            m_end = re.search(r"t_end=>([0-9.eE+-]+)", stripped)
            if m_start and m_end and float(m_start.group(1)) == float(m_end.group(1)):
                t = m_start.group(1)
                lines.append(
                    f'  simulate({{continue=>1, method=>"ode", t_start=>{t}, '
                    f"t_end=>{t}, n_steps=>1, print_functions=>1}})"
                )
            elif first:
                first = False
                lines.append(
                    f'  simulate({{method=>"ode", t_start=>0, '
                    f"sample_times=>[{','.join(repr(time) for time in before)}], "
                    f"print_functions=>1}})"
                )
            else:
                lines.append(
                    f'  simulate({{continue=>1, method=>"ode", t_start=>{EVENT_TIME}, '
                    f"sample_times=>[{','.join(repr(time) for time in after)}], "
                    f"print_functions=>1}})"
                )
        else:
            lines.append(line)
    return "\n".join(lines)


def run_actions(bngl, tmp_path):
    import bionetgen

    source_path = tmp_path / "model.bngl"
    source_path.write_text(bngl, encoding="utf-8")
    bionetgen.load(str(source_path)).execute()
    output = (tmp_path / "model.gdat").read_text()
    header = [field.strip() for field in output.splitlines()[0].lstrip("#").split()]
    samples = {}
    for line in output.splitlines()[1:]:
        if not line.strip() or line.startswith("#"):
            continue
        fields = [float(field) for field in line.split()]
        samples[round(fields[0], 9)] = dict(zip(header, fields))
    return samples


def assert_matches_reference(samples, reference):
    for time, compartment, amount, concentration in reference:
        row = samples[round(time, 9)]
        for name, expected in (
            ("C1_amt", compartment),
            ("S1_amt", amount),
            ("x", concentration),
        ):
            tolerance = ABSOLUTE_TOLERANCE + RELATIVE_TOLERANCE * abs(expected)
            assert (
                abs(row[name] - expected) <= tolerance
            ), f"{name} at t={time}: {row[name]!r} != {expected!r}"


def test_event_driven_compartment_converts_with_the_product_rate_rule():
    bngl = convert(source())

    # The concentration rate rule needs the compartment size and its
    # derivative: dN/dt = V*dC/dt + C*dV/dt.
    assert "__rate_rule__S1() = (0.4) * C1_amt + _c_S1() * __rate_rule__C1()" in bngl
    # The compartment's size lives in a state species, so the event has to
    # update that state.
    assert 'setConcentration("@C1:M___rate_rule_state__C1()", "0.2")' in bngl
    # The species' amount is not assigned by this event, so it keeps its
    # value and only its concentration jumps.
    assert 'setConcentration("@C1:M_S1()"' not in bngl


def test_event_driven_compartment_reproduces_the_official_reference(tmp_path):
    bngl = convert(source())
    grid = [row[0] for row in REFERENCE_01505]
    samples = run_actions(sample_on_reference_grid(bngl, grid), tmp_path)
    assert_matches_reference(samples, REFERENCE_01505)


def test_simultaneous_species_and_compartment_assignment_reproduces_reference(
    tmp_path,
):
    bngl = convert(source(assign_species=True))

    # SBML Test Suite 01779: an event evaluates every assignment against the
    # state before the event, so the species' amount becomes the assigned
    # concentration times the compartment size in effect before the event
    # (0.2 * (0.5 + 0.2 * 0.45) = 0.118).
    assert 'setConcentration("@C1:M_S1()", "0.118")' in bngl
    assert 'setConcentration("@C1:M___rate_rule_state__C1()", "0.2")' in bngl

    grid = [row[0] for row in REFERENCE_01506]
    samples = run_actions(sample_on_reference_grid(bngl, grid), tmp_path)
    assert_matches_reference(samples, REFERENCE_01506)


def test_event_driven_compartment_without_a_rate_rule_is_refused():
    """A compartment that only changes at an event has no size derivative."""

    from bionetgen.atomizer.modern import Atomizer

    xml = source().replace(
        '<rateRule variable="C1">\n'
        '      <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.2</cn></math>\n'
        "    </rateRule>\n",
        "",
    )
    converted = Atomizer(atomize=False, quiet_mode=True).atomize(xml)
    assert not converted.success
    assert (
        "species concentration rate rule requires an explicit compartment derivative"
        in converted.error
    )
    assert "event-driven compartment size without a rate rule" in converted.error


@pytest.mark.parametrize("volume", [0.5, 1.75])
def test_static_compartment_keeps_the_plain_volume_factor(volume):
    """A constant compartment size needs no compartment derivative."""

    from bionetgen.atomizer.modern import Atomizer

    xml = """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="static_volume"><listOfCompartments>
<compartment id="C" size="%s" spatialDimensions="3" constant="true"/>
</listOfCompartments><listOfSpecies>
<species id="S" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
</listOfSpecies><listOfRules>
<rateRule variable="S"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0.4</cn></math></rateRule>
</listOfRules></model></sbml>""" % (
        volume
    )
    converted = Atomizer(atomize=False, quiet_mode=True).atomize(xml)
    assert converted.success, converted.error
    assert f"__rate_rule__S() = (0.4) * __compartment_C__" in converted.bngl
