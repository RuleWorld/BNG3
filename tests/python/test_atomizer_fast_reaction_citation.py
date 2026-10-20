"""Regression tests for the ``fast`` reaction import diagnostic.

SBML Level 3 Version 2 Core Sec. 4.11 removed the ``fast`` attribute: "every
Reaction in a L3V2 model is equivalent to an SBML Level 3 Version 1 Reaction
with a fast value of false".  The pseudo steady-state approximation belongs to
Level 3 Version 1 and Level 2, whose Sec. 4.11 asks that "software tools
should use a pseudo steady-state approximation for the set of fast reactions
when constructing the system of equations for the model".

The diagnostic therefore has to name the rule that applies to the document's
own level and version, and it has to keep its severity: BNG3 has no
fast-equilibrium solve, so a fast reaction is approximated by an ordinary
reaction and the import is reported as ``approximated``.
"""

from __future__ import annotations

import pytest

from bionetgen.atomizer.modern import SBMLParser


def _document(level: int, version: int) -> str:
    namespace = f"http://www.sbml.org/sbml/level{level}/version{version}/core"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="{namespace}" level="{level}" version="{version}">
  <model id="fast_case">
    <listOfCompartments>
      <compartment id="c" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="c" initialAmount="1"
               hasOnlySubstanceUnits="true" constant="false"/>
      <species id="S2" compartment="c" initialAmount="0"
               hasOnlySubstanceUnits="true" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="R1" reversible="false" fast="true">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="S2" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>S1</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""


def _fast_warning(level: int, version: int) -> dict:
    model = SBMLParser().parse(_document(level, version))
    warnings = [
        warning for warning in model.import_warnings
        if warning["category"] == "fastReaction"
    ]
    assert len(warnings) == 1, model.import_warnings
    return warnings[0]


@pytest.mark.parametrize(
    ("level", "version", "citation"),
    [
        (3, 1, "SBML Level 3 Version 1 Core Sec. 4.11"),
        (2, 5, "SBML Level 2 Sec. 4.13"),
        (2, 3, "SBML Level 2 Sec. 4.11"),
    ],
)
def test_fast_diagnostic_cites_the_rule_of_the_document_level(level, version, citation):
    warning = _fast_warning(level, version)

    assert warning["severity"] == "approximated"
    assert citation in warning["message"]
    assert "pseudo steady-state approximation" in warning["message"]
    assert "ordinary reaction" in warning["message"]
    assert "changes the trajectory" in warning["message"]


def test_fast_diagnostic_reports_the_level_3_version_2_removal():
    warning = _fast_warning(3, 2)

    assert warning["severity"] == "approximated"
    assert "SBML Level 3 Version 2 Core Sec. 4.11 removed the fast attribute" in (
        warning["message"]
    )
    assert "pseudo steady-state approximation" in warning["message"]
    assert "ordinary reaction" in warning["message"]
    assert "changes the trajectory" in warning["message"]


def test_fast_diagnostic_keeps_the_reported_reason_markers():
    # The harness classifies the diagnostic by these fragments, so they must
    # survive the citation change.
    warning = _fast_warning(3, 1)

    assert "is marked fast" in warning["message"]
    assert "fast-equilibrium" in warning["message"]
