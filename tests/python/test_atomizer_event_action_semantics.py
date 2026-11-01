"""Contracts for the scheduled actions an SBML event lowers to.

An SBML event assigns a symbol's *value*.  For a species whose identifier
denotes a concentration (``hasOnlySubstanceUnits="false"``) that value is a
concentration, and the species' amount is the assigned value times the size of
the species' compartment (SBML Level 3 Version 2 Core, Sec. 4.6.5 and
Sec. 4.6.8).  BNGL keeps the amount as the species' state and
``setConcentration`` assigns that state, so the Atomizer has to lower the
concentration to the amount.

A species with ``boundaryCondition="true"`` may not be changed by a reaction,
but an event may still change it (SBML Level 3 Version 2 Core, Sec. 4.6.6).
The generated network therefore keeps such a species fixed and the scheduled
action has to reach it.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from bionetgen.atomizer.modern import Atomizer


def _load_actions():
    path = Path(__file__).parents[2] / "scripts" / "ci" / "sbml_reference_actions.py"
    spec = importlib.util.spec_from_file_location("sbml_reference_actions", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# The minimal reproducer of the concentration-assignment defect: a species in a
# compartment whose size is not 1, and an event that assigns the species'
# concentration.  The species' amount has to become 1 * 0.1 = 0.1.
CONCENTRATION_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="concentration_assignment">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="0.1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
      <species id="S2" compartment="C" initialAmount="2" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><ci>time</ci><cn>0.5</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="S2">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>
"""


# The minimal reproducer of the boundary-species defect: the species carries
# ``boundaryCondition="true"``, so the generated network keeps it fixed and the
# event still assigns it.
BOUNDARY_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="boundary_assignment">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false" boundaryCondition="true" constant="false"/>
      <species id="S2" compartment="C" initialAmount="2" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfEvents>
      <event id="E0" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><geq/><ci>time</ci><cn>0.5</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="S1">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>
"""


def _atomize(source: str) -> str:
    result = Atomizer(atomize=False, quiet_mode=True).atomize(source)
    assert result.success, result.error
    return result.bngl


def _assignment_lines(bngl: str) -> list[str]:
    return [
        line.strip()
        for line in bngl.splitlines()
        if "setConcentration" in line or "setVolume" in line
    ]


def test_concentration_event_assignment_lowers_to_the_species_amount():
    """The scheduled action has to carry the amount, not the concentration."""

    bngl = _atomize(CONCENTRATION_MODEL)

    # The compartment size is 0.1, so the assigned concentration 1 is the
    # amount 0.1.
    assert _assignment_lines(bngl) == ['setConcentration("@C:M_S2()", "0.1")']


def test_concentration_event_assignment_reaches_the_native_dispatcher(tmp_path):
    """The native dispatcher has to apply the lowered amount."""

    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    actions = _load_actions()
    bngl = _atomize(CONCENTRATION_MODEL)
    times = [0.0, 0.5, 1.0]

    rewritten, _block = actions.rewrite_action_output_grid(bngl, times)
    run = actions.execute_action_block(
        cpp,
        rewritten,
        tmp_path,
        times=times,
        aliases={"S2": "S2_amt"},
    )

    # The species keeps its amount until the event fires and then holds the
    # assigned concentration scaled by the compartment size.
    assert run.values["S2"][0] == pytest.approx(2.0)
    assert run.values["S2"][-1] == pytest.approx(0.1)


def test_boundary_species_event_assignment_reaches_the_constant_species(tmp_path):
    """A boundary species stays fixed for the reactions but an event moves it."""

    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    actions = _load_actions()
    bngl = _atomize(BOUNDARY_MODEL)

    # The generated network keeps the boundary species fixed ...
    assert "@C:$M_S1() 1" in bngl
    # ... and the action names the same species the observables name.
    assert _assignment_lines(bngl) == ['setConcentration("@C:M_S1()", "3")']

    times = [0.0, 0.5, 1.0]
    rewritten, _block = actions.rewrite_action_output_grid(bngl, times)
    run = actions.execute_action_block(
        cpp,
        rewritten,
        tmp_path,
        times=times,
        aliases={"S1": "S1_amt"},
    )

    assert run.values["S1"][0] == pytest.approx(1.0)
    assert run.values["S1"][-1] == pytest.approx(3.0)


# The SBML Test Suite cases the campaign's official-reference comparison
# measured.  Both models are the two-reaction model of case 00369 with one
# event that assigns a species' value; case 00375 marks the assigned species
# as a boundary species and uses a unit compartment.
def _two_reaction_model(compartment_size: str, boundary_species: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="case00369">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="{compartment_size}" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
      <species id="S2" compartment="C" initialAmount="2" hasOnlySubstanceUnits="false" boundaryCondition="{boundary_species}" constant="false"/>
      <species id="S3" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k1" value="0.75" constant="true"/>
      <parameter id="k2" value="0.25" constant="true"/>
    </listOfParameters>
    <listOfReactions>
      <reaction id="reaction1" reversible="false">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
          <speciesReference species="S2" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="S3" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>C</ci><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
      <reaction id="reaction2" reversible="false">
        <listOfReactants>
          <speciesReference species="S3" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
          <speciesReference species="S2" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>C</ci><ci>k2</ci><ci>S3</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="event1" useValuesFromTriggerTime="true">
        <trigger initialValue="true" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><lt/><ci>S1</ci><cn>0.75</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="S2">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
  </model>
</sbml>
"""


# The published reference trajectory of SBML Test Suite case 00369
# (00369-results.csv) at the official output grid.
CASE_00369_REFERENCE = [
    (0.0, 1.0, 2.0, 1.0),
    (0.4, 0.0773445289747388, 1.077344528974739, 1.922655471025261),
    (0.5, 0.1076567509976469, 0.1326567510076469, 1.892343249002353),
    (1.0, 0.2086880884966271, 0.2336880885066271, 1.791311911503373),
]

# The published reference trajectory of SBML Test Suite case 00375
# (00375-results.csv) at the official output grid.
CASE_00375_REFERENCE = [
    (0.0, 1.0, 2.0, 1.0),
    (0.24, 0.7550334427100202, 2.0, 1.24496655728998),
    (0.3, 0.7368963215165583, 1.0, 1.263103678483441),
    (0.36, 0.7231005537379923, 1.0, 1.276899446262008),
]


def _run_reference(tmp_path, model: str, reference, grid_step: float):
    cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
    actions = _load_actions()
    bngl = _atomize(model)
    times = [round(index * grid_step, 10) for index in range(51)]

    rewritten, _block = actions.rewrite_action_output_grid(bngl, times)
    run = actions.execute_action_block(
        cpp,
        rewritten,
        tmp_path,
        times=times,
        aliases={"S1": "S1_amt", "S2": "S2_amt", "S3": "S3_amt"},
    )

    for time, s1, s2, s3 in reference:
        index = int(round(time / grid_step))
        assert run.times[index] == pytest.approx(time)
        assert run.values["S1"][index] == pytest.approx(s1, rel=1e-3, abs=1e-6)
        assert run.values["S2"][index] == pytest.approx(s2, rel=1e-3, abs=1e-6)
        assert run.values["S3"][index] == pytest.approx(s3, rel=1e-3, abs=1e-6)


def test_official_case_00369_matches_the_published_trajectory(tmp_path):
    """The assigned concentration is the amount the reference publishes."""

    _run_reference(
        tmp_path,
        _two_reaction_model("0.1", "false"),
        CASE_00369_REFERENCE,
        0.1,
    )


def test_official_case_00375_matches_the_published_trajectory(tmp_path):
    """An event may change a boundary species, as the reference publishes."""

    _run_reference(
        tmp_path,
        _two_reaction_model("1", "true"),
        CASE_00375_REFERENCE,
        0.06,
    )


def test_synthesize_event_actions_pads_short_and_degenerate_sampling_grids():
    """Short event phases with < 3 points are padded to at least 3 points."""
    from bionetgen.atomizer.modern.events import synthesize_event_actions, EventTranslationContext, SBMLEvent, SBMLEventAssignment
    # Event fires at time=1.0, base_t_end=2.5, base_steps=2
    # Phases: [0.0, 1.0] and [1.0, 2.5]
    event = SBMLEvent(
        id="e1",
        name="e1",
        trigger="gt(time, 1.0)",
        assignments=[SBMLEventAssignment("p", "3")],
        trigger_persistent=True,
    )
    ctx = EventTranslationContext(
        resolve_species_pattern=lambda _s: None,
        resolve_param=lambda _p: 0.0,
        is_param=lambda _p: True,
        method="ode",
        base_t_end=2.5,
        base_steps=2,
    )
    res = synthesize_event_actions([event], ctx)
    assert res.actions is not None
    import re
    matches = re.findall(r"sample_times=>\[(.*?)\]", res.actions)
    assert len(matches) >= 1
    for m in matches:
        pts = [float(x.strip()) for x in m.split(",")]
        assert len(pts) >= 3
