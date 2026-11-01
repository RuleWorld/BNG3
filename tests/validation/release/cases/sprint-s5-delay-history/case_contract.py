"""Source contract for the sprint's state-dependent SBML delay cases."""

from __future__ import annotations

import math
from pathlib import Path

SPECIFICATION = (
    "SBML Level 3 Version 2 Core Release 2, sections 3.4.6, 3.4.8, " "and 4.12.7"
)
CASE_IDS = ("ordinary", "boundary", "interaction")
ROOT = Path(__file__).parent
SPEC_URL = (
    "https://sbml.org/specifications/sbml-level-3/version-2/core/"
    "release-2/sbml-level-3-version-2-release-2-core.pdf"
)


def sample_times(case_id: str) -> tuple[float, ...]:
    if case_id == "ordinary":
        return (0.0, 0.4, 1.0, 2.0)
    if case_id == "boundary":
        return (0.0, 0.999999, 1.0, 1.000001, 2.0)
    if case_id == "interaction":
        return (0.0, 0.4, 0.5, 0.8, 1.0, 1.2, 2.0)
    raise KeyError(case_id)


def continuation_segments(case_id: str) -> tuple[tuple[float, float], ...]:
    if case_id != "interaction":
        return ((0.0, 2.0),)
    return ((0.0, 0.4), (0.4, 0.8), (0.8, 1.2), (1.2, 2.0))


def expected(case_id: str, t: float) -> dict[str, float]:
    """Closed-form values derived from the raw rate rules and event."""
    if case_id == "ordinary":
        return {"z": t, "k": 1.0, "x": 1.0 + t, "y": 1.0 + t / 2, "q": 1.0}
    if case_id not in {"boundary", "interaction"}:
        raise KeyError(case_id)
    k = 1.0 if t < 0.5 else 3.0
    x = 1.0 + t if t <= 0.5 else 1.5 + 3.0 * (t - 0.5)
    y = 1.0 + t / 2 if t <= 1.0 else 1.5 * t
    # The event's value at t=0.5 is its post-assignment value; the delayed
    # read therefore takes the right-side k at queried time t=1.
    q = 1.0 if t < 1.0 else 3.0
    return {"z": t, "k": k, "x": x, "y": y, "q": q}


def self_check() -> None:
    """Check exact boundaries and each interaction continuation junction."""
    assert expected("ordinary", 0.0)["y"] == 1.0
    assert expected("boundary", 0.0)["y"] == expected("boundary", 0.0)["x"]
    assert expected("boundary", 0.999999)["q"] == 1.0
    assert expected("boundary", 1.0)["q"] == 3.0
    assert expected("boundary", 1.000001)["q"] == 3.0
    assert math.isclose(expected("interaction", 0.4)["x"], 1.4, abs_tol=1e-14)
    assert math.isclose(expected("interaction", 0.8)["x"], 2.4, abs_tol=1e-14)
    assert math.isclose(expected("interaction", 1.2)["x"], 3.6, abs_tol=1e-14)
    assert math.isclose(expected("interaction", 2.0)["x"], 6.0, abs_tol=1e-14)
    assert expected("interaction", 1.0)["y"] == 1.5
    assert expected("interaction", 1.000001)["y"] == 1.5 * 1.000001


def source_path(case_id: str) -> Path:
    if case_id not in CASE_IDS:
        raise KeyError(case_id)
    return ROOT / f"{case_id}.xml"


def source_text(case_id: str) -> str:
    """Return a raw L3V2 Core source model; no BNG3 lowering is involved."""
    if case_id not in CASE_IDS:
        raise KeyError(case_id)
    event = (
        """<listOfEvents>
    <event id="change_rate" useValuesFromTriggerTime="true">
      <trigger initialValue="false" persistent="true">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>0.5</cn></apply>
        </math>
      </trigger>
      <listOfEventAssignments>
        <eventAssignment variable="k">
          <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>3</cn></math>
        </eventAssignment>
      </listOfEventAssignments>
    </event>
  </listOfEvents>"""
        if case_id != "ordinary"
        else ""
    )
    event_section = f"    {event}\n" if event else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="s5_{case_id}" timeUnits="second">
    <listOfUnitDefinitions>
      <unitDefinition id="per_second"><listOfUnits><unit kind="second" exponent="-1" scale="0" multiplier="1"/></listOfUnits></unitDefinition>
    </listOfUnitDefinitions>
    <listOfParameters>
      <parameter id="x" value="1" constant="false"/>
      <parameter id="z" value="0" units="second" constant="false"/>
      <parameter id="k" value="1" units="per_second" constant="{str(case_id == "ordinary").lower()}"/>
      <parameter id="y" value="1" constant="false"/>
      <parameter id="q" value="1" units="per_second" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="x"><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math></rateRule>
      <rateRule variable="z"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></rateRule>
      <assignmentRule variable="y">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol><ci>x</ci><apply><divide/><ci>z</ci><cn>2</cn></apply></apply>
        </math>
      </assignmentRule>
      <assignmentRule variable="q">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/delay">delay</csymbol><ci>k</ci><apply><divide/><ci>z</ci><cn>2</cn></apply></apply>
        </math>
      </assignmentRule>
    </listOfRules>
{event_section}
  </model>
</sbml>
"""
